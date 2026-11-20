import json
import sqlite3

import pytest
import requests
from conftest import FakeClock, response

from airspace_monitor.collector import collect
from airspace_monitor.storage import SnapshotStore


def run_collection(tmp_path, client_factory, states, *, tokens=None, **kwargs):
    clock = FakeClock()
    client, session = client_factory(states, tokens, clock)
    path = tmp_path / "recordings" / "test.sqlite3"
    with SnapshotStore(path) as store:
        result = collect(
            client,
            store,
            monotonic=clock,
            sleep=clock.sleep,
            **kwargs,
        )
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM collection_attempts ORDER BY id").fetchall()
    return result, rows, clock, session


def test_success_failure_success_are_all_persisted(tmp_path, client_factory):
    result, rows, clock, _ = run_collection(
        tmp_path,
        client_factory,
        [
            response(payload={"time": 100, "states": None}),
            requests.Timeout(),
            response(payload={"time": 130, "states": []}),
        ],
        max_polls=3,
    )
    assert (result.attempts, result.successes, result.failures) == (3, 2, 1)
    assert result.stop_reason == "max_polls_reached"
    assert [row["outcome"] for row in rows] == ["success", "network_error", "success"]
    assert rows[1]["raw_body"] is None and rows[1]["vector_count"] is None
    assert json.loads(rows[0]["raw_body"])["states"] is None
    assert len({row["run_id"] for row in rows}) == 1
    assert json.loads(rows[0]["bbox_json"])["lamin"] == 45.7
    assert clock.sleeps == [15, 15]


def test_server_wait_is_not_capped_by_local_backoff(tmp_path, client_factory):
    result, rows, clock, _ = run_collection(
        tmp_path,
        client_factory,
        [
            response(429, headers={"X-Rate-Limit-Retry-After-Seconds": "600"}),
            response(payload={"time": 700, "states": []}),
        ],
        max_polls=2,
        max_backoff_seconds=30,
    )
    assert result.successes == 1 and len(rows) == 2
    assert clock.sleeps == [600]


def test_backoff_grows_and_resets_after_success(tmp_path, client_factory):
    result, _, clock, _ = run_collection(
        tmp_path,
        client_factory,
        [
            response(503),
            response(503),
            response(payload={"time": 100, "states": []}),
            response(503),
            response(payload={"time": 130, "states": []}),
        ],
        max_polls=5,
    )
    assert result.failures == 3
    assert clock.sleeps == [15, 30, 15, 15]


def test_long_rate_limit_does_not_trigger_another_request(tmp_path, client_factory):
    result, rows, clock, session = run_collection(
        tmp_path,
        client_factory,
        [response(429, headers={"Retry-After": "7200"})],
        duration_seconds=3600,
    )
    assert result.stop_reason == "next_poll_after_deadline" and len(rows) == 1
    assert not clock.sleeps and len(session.get_calls) == 1


def test_zero_credits_stops_after_saving_last_snapshot(tmp_path, client_factory):
    result, rows, clock, _ = run_collection(
        tmp_path,
        client_factory,
        [response(payload={"time": 100, "states": []}, headers={"X-Rate-Limit-Remaining": "0"})],
    )
    assert result.stop_reason == "credits_exhausted" and rows[0]["api_time"] == 100
    assert not clock.sleeps


def test_bad_credentials_stop_without_retry_or_secret_storage(tmp_path, client_factory):
    result, rows, clock, session = run_collection(
        tmp_path,
        client_factory,
        [],
        tokens=[response(401, text="test-secret test-token")],
    )
    assert result.stop_reason == "non_retryable_error"
    assert rows[0]["phase"] == "authentication" and rows[0]["raw_body"] is None
    assert not clock.sleeps and not session.get_calls


def test_repeated_failures_stop_at_limit(tmp_path, client_factory):
    result, rows, _, _ = run_collection(
        tmp_path,
        client_factory,
        [response(503)] * 3,
        max_consecutive_failures=3,
    )
    assert result.stop_reason == "failure_limit" and len(rows) == 3


def test_duration_prevents_poll_at_deadline(tmp_path, client_factory):
    result, rows, clock, _ = run_collection(
        tmp_path,
        client_factory,
        [response(payload={"time": 100, "states": []})] * 2,
        duration_seconds=30,
    )
    assert result.stop_reason == "next_poll_after_deadline" and len(rows) == 2
    assert clock.sleeps == [15]


def test_reopening_database_appends_and_preserves_duplicate_api_times(tmp_path, client_factory):
    for _ in range(2):
        result, rows, _, _ = run_collection(
            tmp_path,
            client_factory,
            [response(payload={"time": 100, "states": []})],
            max_polls=1,
        )
    assert result.successes == 1 and len(rows) == 2
    assert rows[0]["run_id"] != rows[1]["run_id"]
    assert [row["api_time"] for row in rows] == [100, 100]


def test_interrupt_preserves_previously_committed_polls(tmp_path, client_factory):
    client, _ = client_factory([response(payload={"time": 100, "states": []})])
    path = tmp_path / "interrupted.sqlite3"

    def interrupt(seconds):
        raise KeyboardInterrupt

    with SnapshotStore(path) as store, pytest.raises(KeyboardInterrupt):
        collect(client, store, sleep=interrupt)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM collection_attempts").fetchone()[0] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval_seconds": 0},
        {"duration_seconds": float("nan")},
        {"max_polls": 0},
        {"max_consecutive_failures": 0},
    ],
)
def test_invalid_settings_make_no_requests(tmp_path, client_factory, kwargs):
    client, session = client_factory()
    with SnapshotStore(tmp_path / "invalid.sqlite3") as store, pytest.raises(ValueError):
        collect(client, store, **kwargs)
    assert not session.post_calls and not session.get_calls
