"""Single-poll OpenSky client. Retry scheduling belongs to the collector."""

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import requests

from airspace_monitor.config import STATES_URL, TOKEN_URL, BoundingBox, Credentials


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def nonnegative_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def retry_delay(headers: requests.structures.CaseInsensitiveDict, now: datetime) -> float | None:
    delays = []
    for name in ("X-Rate-Limit-Retry-After-Seconds", "Retry-After"):
        value = headers.get(name)
        if value is None:
            continue
        delay = nonnegative_number(value)
        if delay is None and name == "Retry-After":
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is not None:
                    delay = max(0.0, (when - now).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
        if delay is not None:
            delays.append(delay)
    return max(delays) if delays else None


@dataclass(frozen=True)
class CollectionAttempt:
    requested_at: str
    completed_at: str
    phase: str
    outcome: str
    http_status: int | None = None
    raw_body: str | None = None
    api_time: int | None = None
    vector_count: int | None = None
    remaining_credits: int | None = None
    retry_after_seconds: float | None = None

    @property
    def successful(self) -> bool:
        return self.outcome == "success"

    @property
    def retryable(self) -> bool:
        if self.successful:
            return False
        if self.outcome in {"network_error", "invalid_response"}:
            return True
        return (
            self.http_status in {408, 429}
            or (self.http_status is not None and self.http_status >= 500)
            or (self.phase == "states" and self.http_status == 401)
        )


class OpenSkyClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        bbox: BoundingBox | None = None,
        timeout: float = 15,
        session: requests.Session | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("HTTP timeout must be finite and positive.")
        self.credentials = credentials
        self.bbox = bbox or BoundingBox()
        self.timeout = timeout
        self.session = session if session is not None else requests.Session()
        self.monotonic = monotonic
        self.now = now
        self._token: str | None = None
        self._expires_at = 0.0

    def close(self) -> None:
        self.session.close()

    def _attempt(
        self,
        started: datetime,
        phase: str,
        outcome: str,
        response: requests.Response | None = None,
        **fields: object,
    ) -> CollectionAttempt:
        finished = self.now()
        if response is not None:
            fields["http_status"] = response.status_code
            fields["retry_after_seconds"] = retry_delay(response.headers, finished)
            # Never persist OAuth response bodies, including failed responses.
            if phase == "states":
                fields["raw_body"] = response.text
                remaining = nonnegative_number(response.headers.get("X-Rate-Limit-Remaining"))
                if remaining is not None and remaining.is_integer() and remaining < 2**63:
                    fields["remaining_credits"] = int(remaining)
        return CollectionAttempt(
            requested_at=started.astimezone(timezone.utc).isoformat(),
            completed_at=finished.astimezone(timezone.utc).isoformat(),
            phase=phase,
            outcome=outcome,
            **fields,
        )

    def _authenticate(self, started: datetime) -> CollectionAttempt | None:
        token_started = self.monotonic()
        try:
            response = self.session.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.credentials.client_id,
                    "client_secret": self.credentials.client_secret,
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            return self._attempt(started, "authentication", "network_error")
        if response.status_code != 200:
            return self._attempt(started, "authentication", "http_error", response)
        try:
            payload = response.json()
            token = payload.get("access_token") if isinstance(payload, dict) else None
            lifetime = (
                nonnegative_number(payload.get("expires_in")) if isinstance(payload, dict) else None
            )
            if not isinstance(token, str) or not token.strip() or lifetime is None or lifetime <= 0:
                raise ValueError
        except ValueError:
            return self._attempt(started, "authentication", "invalid_response", response)
        # Measure from request start so network time cannot extend the token lifetime.
        self._expires_at = token_started + lifetime - min(30.0, lifetime * 0.1)
        self._token = token
        return None

    def fetch_states(self) -> CollectionAttempt:
        """Return one poll result, preserving a states response even if malformed.

        A 401 invalidates the cached token. The next scheduled poll reauthenticates;
        there is no hidden immediate retry that would bypass collection logging.
        """
        started = self.now()
        if self._token is None or self.monotonic() >= self._expires_at:
            failure = self._authenticate(started)
            if failure is not None:
                return failure
        try:
            response = self.session.get(
                STATES_URL,
                params=self.bbox.as_params(),
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            return self._attempt(started, "states", "network_error")
        if response.status_code == 401:
            self._token = None
        if response.status_code != 200:
            return self._attempt(started, "states", "http_error", response)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            api_time = payload.get("time")
            states = payload.get("states")
            if type(api_time) is not int or not 0 <= api_time < 2**63 or "states" not in payload:
                raise ValueError
            if states is not None and (
                not isinstance(states, list) or not all(isinstance(row, list) for row in states)
            ):
                raise ValueError
        except ValueError:
            return self._attempt(started, "states", "invalid_response", response)
        return self._attempt(
            started,
            "states",
            "success",
            response,
            api_time=api_time,
            vector_count=len(states) if states is not None else 0,
        )
