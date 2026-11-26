import json
from dataclasses import fields

import pytest

from airspace_monitor.config import BoundingBox
from airspace_monitor.detector import RuleEngine, detect_recording
from airspace_monitor.opensky_client import CollectionAttempt
from airspace_monitor.storage import SnapshotStore


def new_loss_events(batch):
    return [
        event
        for event in batch.alerts
        if event["alert_type"] == "signal_loss" and event["event"] == "opened"
    ]


def witness(state_vector, at):
    return state_vector(at=at, icao24="def456", latitude=47, longitude=19)


def test_individual_gap_alerts_at_threshold_and_closes_on_contact(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(at=100), witness(state_vector, 100)]))
    for t in [115, 130, 145]:
        assert not new_loss_events(engine.process_poll(poll(t, [witness(state_vector, t)])))
    opened = new_loss_events(engine.process_poll(poll(160, [witness(state_vector, 160)])))
    assert len(opened) == 1 and opened[0]["icao24"] == "abc123"
    assert opened[0]["evidence"]["contact_gap_seconds"] == 60
    assert "does not establish" in opened[0]["limitations"][0]
    again = engine.process_poll(poll(175, [state_vector(at=175), witness(state_vector, 175)]))
    closed = [e for e in again.alerts if e["event"] == "closed"]
    assert closed[0]["close_reason"] == "contact_reacquired"


def test_provider_failure_invalidates_old_loss_baselines(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    failed = engine.process_poll(poll(115, None, outcome="network_error"))
    assert failed.source_events[0]["reason"] == "provider_poll_failed"
    for t in [130, 145, 160, 175, 190]:
        assert not new_loss_events(engine.process_poll(poll(t, [witness(state_vector, t)])))


def test_large_poll_gap_rebaselines_instead_of_reporting_missing_aircraft(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    batch = engine.process_poll(poll(200, [witness(state_vector, 200)]))
    assert not new_loss_events(batch)
    assert batch.source_events[0]["reason"] == "source_observation_gap"


@pytest.mark.parametrize("states", [None, []])
def test_empty_success_is_source_uncertainty_not_mass_signal_loss(poll, state_vector, states):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    batch = engine.process_poll(poll(160, states))
    assert not new_loss_events(batch)
    assert batch.source_events[0]["reason"] == "no_fresh_airborne_witness"


def test_all_stale_rows_cannot_certify_source_health(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    batch = engine.process_poll(poll(160, [state_vector(), witness(state_vector, 100)]))
    assert not new_loss_events(batch)
    assert batch.source_events[0]["reason"] == "no_fresh_airborne_witness"


def test_mass_disappearance_is_reported_as_source_uncertainty(poll, state_vector):
    engine = RuleEngine()
    rows = [state_vector(icao24=f"abc{i:03x}") for i in range(6)]
    engine.process_poll(poll(100, rows))
    batch = engine.process_poll(poll(115, [state_vector(at=115, icao24="abc000")]))
    assert batch.source_events[0]["reason"] == "mass_disappearance"
    for t in [130, 145, 160, 175]:
        assert not new_loss_events(
            engine.process_poll(poll(t, [state_vector(at=t, icao24="abc000")]))
        )


@pytest.mark.parametrize(
    "fields_to_change",
    [
        {"baro_altitude": 1500},
        {"baro_altitude": None},
        {"velocity": None},
        {"true_track": None},
        {"longitude": 22.85},
        {"longitude": 22.72, "latitude": 47, "velocity": 250, "true_track": 90},
        {"latitude": 47.43018, "longitude": 19.262393, "baro_altitude": 2000},
    ],
)
def test_landing_boundary_exit_and_unknown_context_do_not_fake_loss(
    poll, state_vector, fields_to_change
):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(**fields_to_change), witness(state_vector, 100)]))
    for t in [115, 130, 145, 160]:
        assert not new_loss_events(engine.process_poll(poll(t, [witness(state_vector, t)])))
    assert engine.continuity.abstentions


def test_high_overflight_near_airport_is_not_automatically_treated_as_landing(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(
        poll(
            100, [state_vector(latitude=47.43018, longitude=19.262393), witness(state_vector, 100)]
        )
    )
    for t in [115, 130, 145, 160]:
        batch = engine.process_poll(poll(t, [witness(state_vector, t)]))
    assert len(new_loss_events(batch)) == 1


def test_ground_observation_cancels_loss_baseline(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    engine.process_poll(
        poll(115, [state_vector(at=115, on_ground=True), witness(state_vector, 115)])
    )
    for t in [130, 145, 160, 175]:
        assert not new_loss_events(engine.process_poll(poll(t, [witness(state_vector, t)])))


def test_ground_observation_resets_descent_confirmation(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(vertical_rate=-15), witness(state_vector, 100)]))
    engine.process_poll(
        poll(115, [state_vector(at=115, on_ground=True), witness(state_vector, 115)])
    )
    result = engine.process_poll(
        poll(130, [state_vector(at=130, vertical_rate=-15), witness(state_vector, 130)])
    )
    assert not [event for event in result.alerts if event["alert_type"] == "unusual_descent"]


def test_old_position_context_expires_without_claiming_recovery(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    events = []
    for t in range(115, 296, 15):
        events.extend(engine.process_poll(poll(t, [witness(state_vector, t)])).alerts)
    closed = [
        event
        for event in events
        if event["alert_type"] == "signal_loss" and event["event"] == "closed"
    ]
    assert closed[-1]["close_reason"] == "context_uncertain"
    assert engine.continuity.abstentions["position_too_old"] == 1


def test_continuity_component_requires_a_source_witness(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    assert (
        engine.continuity.candidates(
            api_time=160,
            source_attempt_id=2,
            bbox=BoundingBox(),
            fresh_airborne_count=0,
        )
        == []
    )
    assert engine.continuity.abstentions["source_health_unknown"] == 1


def test_duplicate_positions_with_fresh_contacts_are_not_signal_loss(poll, state_vector):
    engine = RuleEngine()
    for t in [100, 115, 130, 145, 160, 175]:
        batch = engine.process_poll(
            poll(t, [state_vector(at=100, last_contact=t), witness(state_vector, t)])
        )
        assert not new_loss_events(batch)


def test_missing_position_with_fresh_contact_is_not_disappearance(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    for t in [115, 130, 145, 160, 175]:
        batch = engine.process_poll(
            poll(t, [state_vector(at=t, latitude=None), witness(state_vector, t)])
        )
        assert not new_loss_events(batch)


def test_emergency_code_is_detected_even_on_duplicate_position(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector()]))
    batch = engine.process_poll(poll(115, [state_vector(last_contact=115, squawk="7700")]))
    assert [e["alert_type"] for e in batch.alerts] == ["emergency_squawk"]
    assert batch.alerts[0]["evidence"]["squawk"] == "7700"


def test_emergency_code_does_not_require_complete_kinematics(poll, state_vector):
    engine = RuleEngine()
    batch = engine.process_poll(
        poll(100, [state_vector(latitude=None, vertical_rate=None, squawk="7600")])
    )
    assert batch.alerts[0]["alert_type"] == "emergency_squawk"


@pytest.mark.parametrize("age", [-10, -1, 31])
def test_future_or_stale_api_time_blocks_inference(poll, state_vector, age):
    batch = RuleEngine().process_poll(poll(100, [state_vector(squawk="7700")], received_age=age))
    assert not batch.alerts
    assert batch.source_events[0]["reason"] == "stale_or_future_source_time"


def test_repeated_or_regressed_snapshot_does_not_advance_loss_clock(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    repeated = engine.process_poll(poll(100, [witness(state_vector, 100)]))
    assert repeated.source_events[0]["reason"] == "nonadvancing_snapshot"
    regressed = engine.process_poll(poll(90, [witness(state_vector, 90)], received_age=25))
    assert regressed.source_events[0]["reason"] == "source_time_regressed"


def test_capture_clock_regression_does_not_backdate_decisions(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(squawk="7700")]))
    batch = engine.process_poll(poll(90, [state_vector(at=90)]))
    assert batch.source_events[0]["reason"] == "capture_time_regressed"
    assert batch.source_events[0]["event_time"] is None
    assert batch.alerts[0]["event_time"] is None


def test_scope_changes_inside_a_run_block_continuity_inference(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    bbox = BoundingBox(lamin=46, lomin=17, lamax=48, lomax=22)
    batch = engine.process_poll(poll(115, [witness(state_vector, 115)], bbox=bbox))
    assert not new_loss_events(batch)
    assert batch.source_events[0]["reason"] == "scope_changed_within_run"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"raw_body": "not-json"}, "invalid_snapshot_or_scope"),
        ({"completed_at": "not-a-time"}, "invalid_capture_time"),
        ({"bbox_json": "{}"}, "invalid_snapshot_or_scope"),
    ],
)
def test_malformed_metadata_is_explicit_source_uncertainty(poll, state_vector, change, reason):
    item = poll(100, [state_vector()])
    item.update(change)
    batch = RuleEngine().process_poll(item)
    assert batch.source_events[0]["reason"] == reason


def test_collection_runs_never_share_continuity_baselines(poll, state_vector):
    engine = RuleEngine()
    engine.process_poll(poll(100, [state_vector(), witness(state_vector, 100)]))
    for t in [115, 130, 145, 160]:
        assert not new_loss_events(
            engine.process_poll(poll(t, [witness(state_vector, t)], run="run2"))
        )


def test_replay_prefixes_match_incremental_processing(poll, state_vector):
    sequence = [poll(100, [state_vector(), witness(state_vector, 100)])]
    sequence += [poll(t, [witness(state_vector, t)]) for t in [115, 130, 145, 160, 175]]
    engine = RuleEngine()
    events = []
    for i, item in enumerate(sequence):
        events.append(engine.process_poll(item))
        replay = RuleEngine()
        assert [replay.process_poll(p) for p in sequence[: i + 1]] == events


def test_detection_export_is_repeatable_and_preserves_raw_source(tmp_path, poll, state_vector):
    source = tmp_path / "raw/test.sqlite3"
    sequence = [poll(100, [state_vector(squawk="7700")]), poll(115, [], outcome="network_error")]
    names = {field.name for field in fields(CollectionAttempt)}
    with SnapshotStore(source) as store:
        for item in sequence:
            store.save(
                CollectionAttempt(**{key: value for key, value in item.items() if key in names}),
                run_id=item["run_id"],
                bbox=BoundingBox(),
            )
    original = source.read_bytes()
    output = tmp_path / "processed"
    report = detect_recording(source, output)
    first = (output / "test.alerts.jsonl").read_bytes()
    assert report["alert_event_counts"]["opened"] == 1
    assert report["source_reason_counts"]["provider_poll_failed"] == 1
    assert report == detect_recording(source, output)
    assert (output / "test.alerts.jsonl").read_bytes() == first
    assert source.read_bytes() == original
    events = [json.loads(line) for line in first.decode().splitlines()]
    assert events[-1]["event"] == "closed"
    assert events[-1]["close_reason"] == "provider_poll_failed"
