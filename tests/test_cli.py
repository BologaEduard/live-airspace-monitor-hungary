import json
import sqlite3
import sys
from dataclasses import asdict

import pytest
from conftest import response

from airspace_monitor.cli import main
from airspace_monitor.config import BoundingBox
from airspace_monitor.opensky_client import CollectionAttempt
from airspace_monitor.preprocess import TelemetryAudit
from airspace_monitor.storage import SnapshotStore


def test_no_command_displays_help_without_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["airspace-monitor"])
    main()
    assert "collect" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [
        ["--interval-seconds", "0"],
        ["--duration-seconds", "nan"],
        ["--timeout-seconds", "inf"],
        ["--max-polls", "-1"],
    ],
)
def test_invalid_arguments_fail_before_authentication(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["airspace-monitor", "collect", *args])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_partial_credentials_are_reported_without_values(monkeypatch, capsys):
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "private-client-id")
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(sys, "argv", ["airspace-monitor", "collect", "--max-polls", "1"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "private-client-id" not in capsys.readouterr().err


def test_collect_command_wires_credentials_client_and_database(
    monkeypatch, tmp_path, capsys, client_factory
):
    client, session = client_factory([response(payload={"time": 100, "states": []})])
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("airspace_monitor.cli.OpenSkyClient", lambda *a, **kw: client)
    path = tmp_path / "recordings.sqlite3"
    monkeypatch.setattr(
        sys, "argv", ["airspace-monitor", "collect", "--db", str(path), "--max-polls", "1"]
    )
    main()
    assert session.closed
    assert "successes=1" in capsys.readouterr().out
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT api_time FROM collection_attempts").fetchone() == (100,)


def test_collect_command_exits_nonzero_when_authentication_fails(
    monkeypatch, tmp_path, capsys, client_factory
):
    client, session = client_factory(tokens=[response(401, text="test-secret")])
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("airspace_monitor.cli.OpenSkyClient", lambda *a, **kw: client)
    monkeypatch.setattr(
        sys, "argv", ["airspace-monitor", "collect", "--db", str(tmp_path / "failed.sqlite3")]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1 and session.closed
    assert "stop=non_retryable_error" in capsys.readouterr().out


def test_database_error_closes_client_before_request(monkeypatch, tmp_path, capsys, client_factory):
    client, session = client_factory()
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("airspace_monitor.cli.OpenSkyClient", lambda *a, **kw: client)
    monkeypatch.setattr(sys, "argv", ["airspace-monitor", "collect", "--db", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1 and session.closed
    assert not session.get_calls and not session.post_calls
    assert "database" in capsys.readouterr().err


def test_audit_command_needs_no_credentials(monkeypatch, tmp_path, capsys, state_vector):
    path = tmp_path / "raw" / "test.sqlite3"
    with SnapshotStore(path) as store:
        store.save(
            CollectionAttempt(
                requested_at="2026-11-26T10:00:00+00:00",
                completed_at="2026-11-26T10:00:01+00:00",
                phase="states",
                outcome="success",
                api_time=100,
                raw_body=json.dumps({"time": 100, "states": [state_vector()]}),
            ),
            run_id="run1",
            bbox=BoundingBox(),
        )
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "partial-environment-must-not-be-used")
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "airspace-monitor",
            "audit",
            "--db",
            str(path),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["accepted_airborne"] == 1


def test_audit_missing_source_exits_nonzero_without_creating_database(monkeypatch, tmp_path):
    path = tmp_path / "missing.sqlite3"
    monkeypatch.setattr(sys, "argv", ["airspace-monitor", "audit", "--db", str(path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1 and not path.exists()


def test_segment_command_exports_without_authentication(
    monkeypatch, tmp_path, capsys, state_vector
):
    observation = (
        TelemetryAudit()
        .process(
            state_vector(),
            api_time=100,
            run_id="run1",
            source_attempt_id=1,
        )
        .observation
    )
    source = tmp_path / "test.observations.jsonl"
    source.write_text(json.dumps(asdict(observation)))
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "partial-environment-must-not-be-used")
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "airspace-monitor",
            "segment",
            "--observations",
            str(source),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["segment_count"] == 1
    assert (tmp_path / "out/test.trajectories.jsonl").is_file()
