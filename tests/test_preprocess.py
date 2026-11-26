import json
import sqlite3
from dataclasses import asdict

import pytest

from airspace_monitor.config import BoundingBox
from airspace_monitor.exports import atomic_text
from airspace_monitor.opensky_client import CollectionAttempt
from airspace_monitor.preprocess import Observation, TelemetryAudit, audit_recording
from airspace_monitor.recordings import RecordingReader
from airspace_monitor.storage import SnapshotStore


def process(audit, row, at=100, run="run1", attempt=1):
    return audit.process(row, api_time=at, run_id=run, source_attempt_id=attempt)


def save(store, at, states, *, run="run1", outcome="success", raw=None):
    store.save(
        CollectionAttempt(
            requested_at="2026-11-26T10:00:00+00:00",
            completed_at="2026-11-26T10:00:01+00:00",
            phase="states",
            outcome=outcome,
            http_status=200 if outcome == "success" else None,
            raw_body=raw if raw is not None else json.dumps({"time": at, "states": states}),
            api_time=at if outcome == "success" else None,
        ),
        run_id=run,
        bbox=BoundingBox(),
    )


def test_named_observation_and_real_zero_are_preserved(state_vector):
    audit = TelemetryAudit()
    decision = process(audit, state_vector(velocity=0, vertical_rate=0, baro_altitude=-10))
    obs = decision.observation
    assert obs.analysis_eligible and obs.vertical_rate == 0 and obs.velocity == 0
    assert obs.baro_altitude == -10 and obs.callsign == "TEST1"
    assert Observation(**asdict(obs)) == obs


@pytest.mark.parametrize("field", ["baro_altitude", "velocity", "true_track", "vertical_rate"])
def test_missing_telemetry_is_retained_but_quarantined_for_analysis(state_vector, field):
    audit = TelemetryAudit()
    decision = process(audit, state_vector(**{field: None}))
    assert decision.disposition == "accepted"
    assert getattr(decision.observation, field) is None
    assert not decision.observation.analysis_eligible
    assert decision.reasons == (f"missing_{field}",)
    assert audit.counts["analysis_quarantined"] == 1
    assert audit.counts["analysis_eligible"] == 0


def test_missing_optional_metadata_does_not_quarantine_analysis(state_vector):
    audit = TelemetryAudit()
    result = process(audit, state_vector(squawk=None, geo_altitude=None))
    assert result.observation.analysis_eligible
    assert audit.missing_fields["squawk"] == 1


def test_ground_is_excluded_before_missing_flight_telemetry(state_vector):
    audit = TelemetryAudit()
    result = process(audit, state_vector(on_ground=True, baro_altitude=None, vertical_rate=None))
    assert result.disposition == "ground"
    assert audit.counts["excluded_ground"] == 1
    assert audit.counts["analysis_quarantined"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("longitude", None),
        ("latitude", 91),
        ("velocity", -1),
        ("true_track", 360),
        ("vertical_rate", float("nan")),
        ("baro_altitude", float("inf")),
        ("velocity", True),
        ("velocity", 10**400),
        ("on_ground", None),
        ("time_position", 101),
        ("last_contact", 99),
        ("last_contact", None),
        ("time_position", True),
    ],
)
def test_invalid_and_future_records_have_explicit_reasons(state_vector, field, value):
    result = process(TelemetryAudit(), state_vector(**{field: value}))
    assert result.disposition == "invalid" and result.observation is None
    assert result.reasons


@pytest.mark.parametrize("row", [None, [], ["short"], {"icao24": "abc123"}])
def test_malformed_rows_are_counted_not_crashed(row):
    audit = TelemetryAudit()
    assert process(audit, row).reasons == ("malformed_vector",)
    assert audit.counts["raw_vectors"] == audit.counts["excluded_invalid"] == 1


def test_age_boundary_duplicates_order_and_run_isolation(state_vector):
    audit = TelemetryAudit(max_age_seconds=30)
    assert process(audit, state_vector(at=70)).disposition == "accepted"
    assert process(audit, state_vector(at=69)).disposition == "stale"
    assert process(audit, state_vector(at=70)).disposition == "duplicate"
    assert process(audit, state_vector(at=80)).disposition == "accepted"
    assert process(audit, state_vector(at=75)).disposition == "out_of_order"
    assert process(audit, state_vector(at=70), run="another").disposition == "accepted"
    counts = audit.counts
    assert counts["raw_vectors"] == counts["accepted_airborne"] + sum(
        count for name, count in counts.items() if name.startswith("excluded_")
    )


def test_extended_vectors_and_uppercase_icao_are_supported(state_vector):
    row = state_vector(icao24="ABC123") + [3]
    assert process(TelemetryAudit(), row).observation.icao24 == "abc123"


def test_audit_exports_failures_empty_snapshots_and_partial_records(tmp_path, state_vector):
    source = tmp_path / "raw" / "test.sqlite3"
    with SnapshotStore(source) as store:
        save(
            store,
            100,
            [
                state_vector(),
                state_vector(icao24="def456", vertical_rate=None),
                state_vector(icao24="abc999", on_ground=True),
            ],
        )
        save(store, 115, None, outcome="network_error")
        save(store, 130, None)
        save(store, 145, [], raw="broken-json")
    before = source.read_bytes()
    report = audit_recording(source, tmp_path / "processed")
    assert source.read_bytes() == before
    assert report["polls"] == {
        "total": 4,
        "failed": 1,
        "successful": 3,
        "invalid_success_payload": 1,
        "empty_successful": 1,
    }
    assert report["counts"]["accepted_airborne"] == 2
    assert report["counts"]["analysis_quarantined"] == 1
    observations = [
        json.loads(line)
        for line in (tmp_path / "processed/test.observations.jsonl").read_text().splitlines()
    ]
    assert observations[1]["vertical_rate"] is None
    exclusions = [
        json.loads(line)
        for line in (tmp_path / "processed/test.exclusions.jsonl").read_text().splitlines()
    ]
    assert {entry["scope"] for entry in exclusions} == {"analysis", "tracking", "poll"}
    assert report["max_attempt_id"] == 4


def test_reader_does_not_include_appends_after_start(tmp_path, state_vector):
    source = tmp_path / "test.sqlite3"
    with SnapshotStore(source) as store:
        save(store, 100, [state_vector()])
        with RecordingReader(source) as reader:
            save(store, 115, [state_vector(at=115)])
            assert [row["id"] for row in reader.attempts()] == [1]
            assert reader.max_attempt_id == 1
        assert (
            store.connection.execute("SELECT COUNT(*) FROM collection_attempts").fetchone()[0] == 2
        )


def test_reader_missing_database_does_not_create_it(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.Error):
        RecordingReader(path)
    assert not path.exists()


def test_raw_directory_is_not_an_export_destination(tmp_path):
    source = tmp_path / "test.sqlite3"
    with pytest.raises(ValueError, match="separate"):
        audit_recording(source, tmp_path)


@pytest.mark.parametrize("age", [0, -1, float("inf"), float("nan")])
def test_invalid_age_limits_are_rejected(age):
    with pytest.raises(ValueError):
        TelemetryAudit(age)


def test_failed_export_keeps_previous_complete_file(tmp_path):
    target = tmp_path / "report.json"
    target.write_text("previous report")
    with pytest.raises(RuntimeError):
        with atomic_text(target) as stream:
            stream.write("incomplete")
            raise RuntimeError("disk or processing failure")
    assert target.read_text() == "previous report"
    assert not list(tmp_path.glob(".export-*.tmp"))
