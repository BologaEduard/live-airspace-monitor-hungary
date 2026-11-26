import json
from dataclasses import asdict, replace

import pytest

from airspace_monitor.preprocess import TelemetryAudit
from airspace_monitor.trajectories import TrajectoryBuilder, segment_observations


@pytest.fixture
def observation(state_vector):
    return (
        TelemetryAudit()
        .process(
            state_vector(),
            api_time=100,
            run_id="run1",
            source_attempt_id=1,
        )
        .observation
    )


def at(observation, time, **fields):
    return replace(observation, api_time=time, time_position=time, last_contact=time, **fields)


def test_interleaved_aircraft_keep_independent_segments(observation):
    builder = TrajectoryBuilder()
    a1 = builder.add(observation)
    b1 = builder.add(replace(observation, icao24="def456"))
    a2 = builder.add(at(observation, 115))
    assert a1["segment_id"] == a2["segment_id"] != b1["segment_id"]
    assert a1["point_index"] == 0 and a2["point_index"] == 1
    assert a1["starts_segment"] and not a2["starts_segment"]
    assert builder.report()["segment_count"] == 2


def test_exact_gap_threshold_stays_together_and_longer_gap_splits(observation):
    builder = TrajectoryBuilder(max_gap_seconds=120)
    first = builder.add(observation)
    boundary = builder.add(at(observation, 220))
    split = builder.add(at(observation, 341))
    assert first["segment_id"] == boundary["segment_id"] != split["segment_id"]
    assert split["segment_number"] == 2 and split["point_index"] == 0
    assert split["segment_start_reason"] == "observation_gap"
    assert [s["point_count"] for s in builder.report()["segments"]] == [2, 1]


def test_duplicates_and_late_points_do_not_change_state(observation):
    builder = TrajectoryBuilder()
    builder.add(at(observation, 120))
    assert builder.add(at(observation, 120)) is None
    assert builder.add(at(observation, 110)) is None
    point = builder.add(at(observation, 130))
    assert point["point_index"] == 1
    assert builder.report()["counts"] == {
        "observations_read": 4,
        "points_written": 2,
        "duplicate_points": 1,
        "out_of_order_points": 1,
    }


def test_collection_runs_are_not_joined(observation):
    builder = TrajectoryBuilder()
    one = builder.add(observation)
    two = builder.add(replace(observation, run_id="run2"))
    assert one["segment_id"] != two["segment_id"]
    assert two["segment_number"] == 1 and two["starts_segment"]


def test_missing_vertical_speed_remains_missing_and_not_analysis_eligible(observation):
    builder = TrajectoryBuilder()
    point = builder.add(replace(observation, vertical_rate=None))
    assert point["observation"]["vertical_rate"] is None
    assert point["analysis_eligible"] is False
    assert builder.report()["segments"][0]["analysis_eligible_points"] == 0


def test_replay_and_incremental_processing_produce_identical_prefixes(observation):
    sequence = [at(observation, t) for t in [100, 115, 250, 265]]
    live = TrajectoryBuilder()
    live_points = []
    for obs in sequence:
        point = live.add(obs)
        live_points.append(point)
        replay = TrajectoryBuilder()
        assert [replay.add(old) for old in sequence[: len(live_points)]] == live_points
    # Later input must not mutate previously returned point records.
    assert live_points[0]["point_index"] == 0
    assert live_points[0]["observation"]["time_position"] == 100


def test_jsonl_exports_are_repeatable_and_keep_source_unchanged(tmp_path, observation):
    source = tmp_path / "test.observations.jsonl"
    source.write_text("\n".join(json.dumps(asdict(at(observation, t))) for t in [100, 115, 300]))
    original = source.read_bytes()
    output = tmp_path / "processed"
    report = segment_observations(source, output)
    points = (output / "test.trajectories.jsonl").read_bytes()
    assert report["segment_count"] == 2
    assert segment_observations(source, output) == report
    assert (output / "test.trajectories.jsonl").read_bytes() == points
    assert source.read_bytes() == original


def test_invalid_line_fails_without_replacing_previous_export(tmp_path, observation):
    source = tmp_path / "test.observations.jsonl"
    source.write_text(json.dumps(asdict(observation)) + "\nnot-json")
    destination = tmp_path / "test.trajectories.jsonl"
    destination.write_text("previous complete export")
    with pytest.raises(ValueError, match="line 2"):
        segment_observations(source, tmp_path)
    assert destination.read_text() == "previous complete export"
    assert not list(tmp_path.glob(".export-*.tmp"))


@pytest.mark.parametrize("gap", [0, -1, float("inf"), float("nan")])
def test_invalid_gap_settings_are_rejected(gap):
    with pytest.raises(ValueError):
        TrajectoryBuilder(gap)
