import json

import pytest

from airspace_monitor.config import BoundingBox
from airspace_monitor.detector import detect_recording
from airspace_monitor.opensky_client import CollectionAttempt
from airspace_monitor.preview import latest_recording, read_preview
from airspace_monitor.storage import SnapshotStore


def save(store, item):
    return store.save(
        CollectionAttempt(
            requested_at=item["requested_at"],
            completed_at=item["completed_at"],
            phase=item["phase"],
            outcome=item["outcome"],
            http_status=item["http_status"],
            api_time=item["api_time"],
            raw_body=item["raw_body"],
        ),
        run_id=item["run_id"],
        bbox=BoundingBox(),
    )


def test_preview_is_bounded_read_only_and_preserves_missing_values(tmp_path, poll, state_vector):
    source = tmp_path / "raw/test.sqlite3"
    with SnapshotStore(source) as store:
        for at in [100, 115, 130]:
            save(
                store,
                poll(
                    at,
                    [
                        state_vector(at=at, velocity=0, vertical_rate=None),
                        state_vector(at=at, icao24="def456", on_ground=True),
                    ],
                ),
            )
    original = source.read_bytes()
    result = read_preview(source, max_frames=2, now=140)
    assert [frame["time"] for frame in result["frames"]] == [115, 130]
    plane = result["frames"][-1]["aircraft"][0]
    assert plane["velocity"] == 0 and plane["vertical_rate"] is None
    assert result["frames"][-1]["ground_count"] == 1
    assert result["source"]["status"] == "fresh_recording"
    assert result["source"]["polls_total"] == 3
    assert source.read_bytes() == original
    assert str(tmp_path) not in json.dumps(result)


def test_invalid_positions_are_omitted_but_stale_positions_are_flagged(
    tmp_path, poll, state_vector
):
    source = tmp_path / "raw/test.sqlite3"
    with SnapshotStore(source) as store:
        save(
            store,
            poll(
                100,
                [
                    state_vector(at=60),
                    state_vector(at=100, latitude=None, icao24="def456"),
                    state_vector(at=100, velocity=float("nan"), icao24="abc789"),
                ],
            ),
        )
    result = read_preview(source, now=100)
    aircraft = result["frames"][0]["aircraft"]
    assert len(aircraft) == 2 and aircraft[0]["position_stale"]
    assert aircraft[1]["velocity"] is None
    json.dumps(result, allow_nan=False)


def test_failed_latest_poll_does_not_present_saved_frame_as_fresh(tmp_path, poll, state_vector):
    source = tmp_path / "raw/test.sqlite3"
    with SnapshotStore(source) as store:
        save(store, poll(100, [state_vector()]))
        save(store, poll(115, [], outcome="network_error"))
    result = read_preview(source, now=116)
    assert result["source"]["status"] == "source_interrupted"
    assert result["source"]["failed_polls"] == 1
    assert result["frames"][-1]["time"] == 100


def test_saved_clock_and_absent_recording_have_explicit_states(tmp_path, poll, state_vector):
    assert read_preview(None)["source"]["status"] == "no_recording"
    source = tmp_path / "raw/test.sqlite3"
    with SnapshotStore(source) as store:
        save(store, poll(100, [state_vector()]))
    assert read_preview(source, now=200)["source"]["status"] == "saved_recording"
    assert read_preview(source, now=90)["source"]["status"] == "source_clock_unknown"


def test_preview_never_joins_different_runs(tmp_path, poll, state_vector):
    source = tmp_path / "raw/test.sqlite3"
    with SnapshotStore(source) as store:
        save(store, poll(100, [state_vector()]))
        save(store, poll(115, [state_vector(at=115)], run="run2"))
    assert [frame["time"] for frame in read_preview(source, now=115)["frames"]] == [115]


def test_analysis_history_is_provenanced_and_does_not_claim_current_active_alerts(
    tmp_path, poll, state_vector
):
    source = tmp_path / "raw/test.sqlite3"
    with SnapshotStore(source) as store:
        save(store, poll(100, [state_vector(squawk="7700")]))
    detect_recording(source, tmp_path / "processed")
    with SnapshotStore(source) as store:
        save(store, poll(115, [state_vector(at=115)]))
    result = read_preview(source, now=115)
    assert result["analysis"]["available"]
    assert result["analysis"]["as_of_time"] == 100
    assert result["analysis"]["events"][0]["source_api_time"] == 100
    assert "active_alerts" not in result["analysis"]
    assert result["source"]["last_api_time"] == 115


def test_missing_directory_has_no_automatic_source(tmp_path):
    assert latest_recording(tmp_path / "missing") is None


@pytest.mark.parametrize("limit", [0, 121, True])
def test_invalid_preview_limits_are_rejected(limit):
    with pytest.raises(ValueError):
        read_preview(None, max_frames=limit)
