import pytest


@pytest.fixture
def web_client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from airspace_monitor.app import create_app

    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<html><body>Local airspace preview</body></html>")
    (tmp_path / "credentials.json").write_text('{"clientSecret":"private-test-value"}')
    with TestClient(create_app(None, public)) as client:
        yield client


def test_local_frontend_and_health_are_available(web_client):
    assert web_client.get("/").status_code == 200
    assert web_client.get("/api/health").json()["mode"] == "local-preview"
    result = web_client.get("/api/preview")
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json()["source"]["status"] == "no_recording"


@pytest.mark.parametrize(
    "path",
    [
        "/credentials.json",
        "/.env",
        "/%2e%2e/credentials.json",
        "/api/preview/../../credentials.json",
    ],
)
def test_static_server_does_not_expose_repository_files(web_client, path):
    response = web_client.get(path)
    assert response.status_code == 404
    assert "private-test-value" not in response.text


def test_query_parameters_cannot_select_arbitrary_files(web_client):
    response = web_client.get("/api/preview?db=credentials.json")
    assert response.json()["source"]["status"] == "no_recording"
    assert "private-test-value" not in response.text
