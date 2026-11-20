"""Bounded, sequential collection with visible failures and server-aware backoff."""

import logging
import math
import time
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from airspace_monitor.opensky_client import OpenSkyClient
from airspace_monitor.storage import SnapshotStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionSummary:
    run_id: str
    attempts: int
    successes: int
    failures: int
    stop_reason: str


def collect(
    client: OpenSkyClient,
    store: SnapshotStore,
    *,
    interval_seconds: float = 15,
    duration_seconds: float = 3600,
    max_polls: int | None = None,
    max_consecutive_failures: int = 8,
    max_backoff_seconds: float = 300,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectionSummary:
    for name, value in (
        ("interval", interval_seconds),
        ("duration", duration_seconds),
        ("maximum backoff", max_backoff_seconds),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Collection {name} must be finite and positive.")
    if max_polls is not None and (type(max_polls) is not int or max_polls < 1):
        raise ValueError("Maximum polls must be a positive integer.")
    if type(max_consecutive_failures) is not int or max_consecutive_failures < 1:
        raise ValueError("Maximum consecutive failures must be a positive integer.")
    run_id = uuid4().hex
    deadline = monotonic() + duration_seconds
    attempts = successes = failures = consecutive_failures = 0
    reason = "duration_reached"
    while monotonic() < deadline:
        poll_started = monotonic()
        attempt = client.fetch_states()
        store.save(attempt, run_id=run_id, bbox=client.bbox)
        attempts += 1
        logger.info(
            "poll=%s phase=%s outcome=%s http=%s vectors=%s credits=%s",
            attempts,
            attempt.phase,
            attempt.outcome,
            attempt.http_status,
            attempt.vector_count,
            attempt.remaining_credits,
        )
        if attempt.successful:
            successes += 1
            consecutive_failures = 0
        else:
            failures += 1
            consecutive_failures += 1
        if not attempt.successful and not attempt.retryable:
            reason = "non_retryable_error"
            break
        if attempt.remaining_credits == 0:
            reason = "credits_exhausted"
            break
        if consecutive_failures >= max_consecutive_failures:
            reason = "failure_limit"
            break
        if max_polls is not None and attempts >= max_polls:
            reason = "max_polls_reached"
            break
        if attempt.successful:
            delay = max(0.0, interval_seconds - (monotonic() - poll_started))
        else:
            backoff = min(
                max_backoff_seconds,
                interval_seconds * 2 ** min(consecutive_failures - 1, 20),
            )
            # Never cap a provider-mandated wait to the local backoff maximum.
            delay = max(interval_seconds, backoff, attempt.retry_after_seconds or 0.0)
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        if delay >= remaining:
            reason = "next_poll_after_deadline"
            break
        logger.info("next_poll_in_seconds=%.1f", delay)
        sleep(delay)
    return CollectionSummary(run_id, attempts, successes, failures, reason)
