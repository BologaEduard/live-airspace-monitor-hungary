"""Offline fixtures: a missed mock must never spend live API credits."""

import json
from datetime import datetime, timezone

import pytest
import requests

from airspace_monitor.config import Credentials
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
