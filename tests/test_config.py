import json

import pytest

from airspace_monitor.config import BoundingBox, Credentials, load_credentials


def test_environment_takes_precedence_without_reading_file(tmp_path):
    result = load_credentials(
        tmp_path / "does-not-exist.json",
        environ={"OPENSKY_CLIENT_ID": "env-id", "OPENSKY_CLIENT_SECRET": "env-secret"},
    )
    assert result.client_id == "env-id"
    assert "env-secret" not in repr(result)
    assert "env-id" not in repr(result)


@pytest.mark.parametrize(
    "env",
    [
        {"OPENSKY_CLIENT_ID": "only-id"},
        {"OPENSKY_CLIENT_SECRET": "only-secret"},
        {"OPENSKY_CLIENT_ID": "", "OPENSKY_CLIENT_SECRET": "secret"},
    ],
)
def test_partial_environment_does_not_fall_back_to_file(tmp_path, env):
    path = tmp_path / "creds.json"
    path.write_text('{"clientId":"file-id","clientSecret":"file-secret"}')
    with pytest.raises(ValueError):
        load_credentials(path, environ=env)


@pytest.mark.parametrize("keys", [("clientId", "clientSecret"), ("client_id", "client_secret")])
def test_both_existing_credential_formats_work(tmp_path, keys):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps(dict(zip(keys, ("id", "secret")))))
    assert load_credentials(path, environ={}) == Credentials("id", "secret")


@pytest.mark.parametrize("text", ['["secret"]', "{broken-secret", '{"clientId":123}'])
def test_invalid_file_errors_do_not_include_contents(tmp_path, text):
    path = tmp_path / "creds.json"
    path.write_text(text)
    with pytest.raises(ValueError) as error:
        load_credentials(path, environ={})
    assert "secret" not in str(error.value).lower() or "nonempty strings" in str(error.value)
    assert text not in str(error.value)


def test_no_credentials_is_actionable():
    with pytest.raises(ValueError, match="OPENSKY_CLIENT_ID"):
        load_credentials(environ={})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lamin": float("nan")},
        {"lamax": 91},
        {"lomin": 23},
        {"lomax": float("inf")},
    ],
)
def test_invalid_bounding_box_is_rejected(kwargs):
    with pytest.raises(ValueError):
        BoundingBox(**kwargs)
