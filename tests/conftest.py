"""Offline fixtures: a missed mock must never spend live API credits."""

import json
from datetime import datetime, timezone

import pytest
import requests

from airspace_monitor.config import BoundingBox, Credentials
from airspace_monitor.opensky_client import OpenSkyClient


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests.")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)


def response(status=200, payload=None, headers=None, *, text=None):
    result = requests.Response()
    result.status_code = status
    result.encoding = "utf-8"
    result._content = (json.dumps(payload) if text is None else text).encode("utf-8")
    result.headers.update(headers or {})
    return result


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class FakeSession:
    def __init__(self, states=(), tokens=None):
        self.states = list(states)
        self.tokens = (
            list(tokens)
            if tokens is not None
            else [response(payload={"access_token": "test-token", "expires_in": 1800})]
        )
        self.get_calls = []
        self.post_calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        result = self.states.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        result = self.tokens.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


@pytest.fixture
def client_factory():
    def make(states=(), tokens=None, clock=None):
        session = FakeSession(states, tokens)
        client = OpenSkyClient(
            Credentials("test-id", "test-secret"),
            session=session,
            monotonic=clock or FakeClock(),
            now=lambda: datetime(2026, 11, 20, tzinfo=timezone.utc),
        )
        return client, session

    return make


@pytest.fixture
def state_vector():
    def make(at=100, icao24="abc123", **fields):
        row = [
            icao24,
            " TEST1  ",
            "Hungary",
            at,
            at,
            19.1,
            47.5,
            10000,
            False,
            220,
            359,
            0,
            None,
            10030,
            "1234",
            False,
            0,
        ]
        indices = {
            "time_position": 3,
            "last_contact": 4,
            "longitude": 5,
            "latitude": 6,
            "baro_altitude": 7,
            "on_ground": 8,
            "velocity": 9,
            "true_track": 10,
            "vertical_rate": 11,
            "geo_altitude": 13,
            "squawk": 14,
        }
        for name, value in fields.items():
            row[indices[name]] = value
        return row

    return make


@pytest.fixture
def poll():
    def make(at, states, *, run="run1", outcome="success", received_age=0, raw=None, bbox=None):
        completed = datetime.fromtimestamp(at + received_age, timezone.utc).isoformat()
        return {
            "id": at + 1,
            "run_id": run,
            "bbox_json": json.dumps((bbox or BoundingBox()).as_params()),
            "requested_at": completed,
            "completed_at": completed,
            "phase": "states",
            "outcome": outcome,
            "http_status": 200 if outcome == "success" else None,
            "api_time": at if outcome == "success" else None,
            "raw_body": raw if raw is not None else json.dumps({"time": at, "states": states}),
        }

    return make
