import sqlite3
import sys

import pytest
from conftest import response

from airspace_monitor.cli import main


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
