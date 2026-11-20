from datetime import datetime, timezone

import pytest
import requests
from conftest import FakeClock, response

from airspace_monitor.opensky_client import retry_delay


def test_tokens_are_reused_and_null_telemetry_is_preserved(client_factory):
    # Raw ingestion must not turn missing vertical speed into normal level flight.
    raw = '{ "time": 100, "states": [["abc123", null, null, 100, 100, 19, 47, null]] }'
    client, session = client_factory(
        [
            response(text=raw, headers={"X-Rate-Limit-Remaining": "3999"}),
            response(payload={"time": 115, "states": None}),
        ]
    )
    first = client.fetch_states()
    second = client.fetch_states()
    assert first.successful and first.vector_count == 1
    assert first.raw_body == raw
    assert first.api_time == 100 and first.remaining_credits == 3999
    assert second.successful and second.vector_count == 0
    assert len(session.post_calls) == 1
    assert session.get_calls[0][1]["params"] == client.bbox.as_params()
    assert session.get_calls[0][1]["allow_redirects"] is False
    assert session.post_calls[0][1]["allow_redirects"] is False


def test_token_refreshes_before_expiry(client_factory):
    clock = FakeClock()
    client, session = client_factory(
        [response(payload={"time": 100, "states": []})] * 3,
        [response(payload={"access_token": token, "expires_in": 100}) for token in ["a", "b"]],
        clock,
    )
    client.fetch_states()
    clock.value = 89
    client.fetch_states()
    clock.value = 90
    client.fetch_states()
    assert len(session.post_calls) == 2
    assert [call[1]["headers"]["Authorization"] for call in session.get_calls] == [
        "Bearer a",
        "Bearer a",
        "Bearer b",
    ]


def test_401_is_recorded_and_next_poll_refreshes(client_factory):
    client, session = client_factory(
        [response(401, text="expired"), response(payload={"time": 100, "states": []})],
        [response(payload={"access_token": token, "expires_in": 100}) for token in ["a", "b"]],
    )
    failed = client.fetch_states()
    assert failed.http_status == 401 and failed.retryable
    assert len(session.get_calls) == 1
    assert client.fetch_states().successful
    assert len(session.post_calls) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"time": True, "states": []},
        {"time": 2**63, "states": []},
        {"time": 100},
        {"time": 100, "states": {}},
        {"time": 100, "states": ["not-a-vector"]},
    ],
)
def test_invalid_envelopes_are_quarantined_with_raw_body(client_factory, payload):
    raw_response = response(payload=payload)
    client, _ = client_factory([raw_response])
    result = client.fetch_states()
    assert result.outcome == "invalid_response" and result.retryable
    assert result.raw_body == raw_response.text
    assert result.api_time is None


def test_non_json_response_is_preserved(client_factory):
    client, _ = client_factory([response(text="<html>maintenance</html>")])
    result = client.fetch_states()
    assert result.outcome == "invalid_response"
    assert result.raw_body == "<html>maintenance</html>"


def test_unusable_credit_header_does_not_break_snapshot_storage(client_factory):
    client, _ = client_factory(
        [response(payload={"time": 100, "states": []}, headers={"X-Rate-Limit-Remaining": "1e100"})]
    )
    result = client.fetch_states()
    assert result.successful and result.remaining_credits is None


@pytest.mark.parametrize(
    "token_response",
    [
        response(401, text="test-secret test-token"),
        response(text="test-secret test-token"),
        response(payload={"access_token": "test-token", "expires_in": "NaN"}),
        response(payload={"access_token": "test-token", "expires_in": 0}),
    ],
)
def test_authentication_failures_never_store_token_bodies(client_factory, token_response):
    client, session = client_factory(tokens=[token_response])
    result = client.fetch_states()
    assert result.phase == "authentication" and not result.successful
    assert result.raw_body is None
    assert "test-secret" not in repr(result) and "test-token" not in repr(result)
    assert not session.get_calls


@pytest.mark.parametrize("phase", ["states", "authentication"])
def test_transport_errors_do_not_leak_exception_details(client_factory, phase):
    error = requests.Timeout("test-secret test-token")
    client, _ = client_factory(
        states=[error] if phase == "states" else [],
        tokens=[error] if phase == "authentication" else None,
    )
    result = client.fetch_states()
    assert result.phase == phase and result.outcome == "network_error"
    assert result.retryable and result.raw_body is None
    assert "test-secret" not in repr(result)


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({"X-Rate-Limit-Retry-After-Seconds": "120", "Retry-After": "30"}, 120),
        ({"Retry-After": "Fri, 20 Nov 2026 00:02:00 GMT"}, 120),
        ({"Retry-After": "NaN"}, None),
        ({"Retry-After": "-1"}, None),
        ({"X-Rate-Limit-Retry-After-Seconds": "bad", "Retry-After": "60"}, 60),
    ],
)
def test_retry_headers_use_longest_valid_wait(headers, expected):
    assert (
        retry_delay(
            requests.structures.CaseInsensitiveDict(headers),
            datetime(2026, 11, 20, tzinfo=timezone.utc),
        )
        == expected
    )
