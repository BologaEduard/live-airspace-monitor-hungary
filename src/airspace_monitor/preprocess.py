"""Causal telemetry audit, shared by recording exports and future live processing."""

import json
import math
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

from airspace_monitor.exports import atomic_text, write_json_line, write_report
from airspace_monitor.recordings import RecordingReader

FIELDS = {
    "time_position": 3,
    "last_contact": 4,
    "longitude": 5,
    "latitude": 6,
    "baro_altitude": 7,
    "velocity": 9,
    "true_track": 10,
    "vertical_rate": 11,
    "geo_altitude": 13,
    "squawk": 14,
}
ANALYSIS_FIELDS = ("baro_altitude", "velocity", "true_track", "vertical_rate")


def finite_number(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def timestamp(value: object) -> bool:
    return type(value) is int and 0 <= value < 2**63


def valid_numeric(name: str, value: object) -> bool:
    if not finite_number(value):
        return False
    if name == "longitude":
        return -180 <= value <= 180
    if name == "latitude":
        return -90 <= value <= 90
    if name == "velocity":
        return value >= 0
    if name == "true_track":
        return 0 <= value < 360
    return True


@dataclass(frozen=True)
class Observation:
    run_id: str
    source_attempt_id: int
    api_time: int
    icao24: str
    time_position: int
    last_contact: int
    longitude: float
    latitude: float
    baro_altitude: float | None
    velocity: float | None
    true_track: float | None
    vertical_rate: float | None
    geo_altitude: float | None
    callsign: str | None
    origin_country: str | None
    squawk: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("Invalid collection run ID.")
        if not timestamp(self.source_attempt_id) or self.source_attempt_id == 0:
            raise ValueError("Invalid source attempt ID.")
        if not isinstance(self.icao24, str) or re.fullmatch(r"[0-9a-f]{6}", self.icao24) is None:
            raise ValueError("Invalid ICAO24 identifier.")
        times = (self.time_position, self.last_contact, self.api_time)
        if not all(timestamp(value) for value in times) or not times[0] <= times[1] <= times[2]:
            raise ValueError("Invalid or noncausal observation timestamps.")
        for name in ("longitude", "latitude"):
            if not valid_numeric(name, getattr(self, name)):
                raise ValueError("Invalid observation position.")
        for name in (*ANALYSIS_FIELDS, "geo_altitude"):
            value = getattr(self, name)
            if value is not None and not valid_numeric(name, value):
                raise ValueError("Invalid observation telemetry.")
        for name in ("callsign", "origin_country", "squawk"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), str):
                raise ValueError("Invalid observation metadata.")

    @property
    def missing_analysis_fields(self) -> tuple[str, ...]:
        return tuple(name for name in ANALYSIS_FIELDS if getattr(self, name) is None)

    @property
    def analysis_eligible(self) -> bool:
        return not self.missing_analysis_fields


def read_observations(source: TextIO) -> Iterator[Observation]:
    """Validate each JSONL line in arrival order, without looking ahead."""
    for line_number, line in enumerate(source, 1):
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError
            observation = Observation(**payload)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"Invalid observation at JSONL line {line_number}.") from None
        yield observation


@dataclass(frozen=True)
class AuditDecision:
    disposition: str
    reasons: tuple[str, ...]
    observation: Observation | None = None


class TelemetryAudit:
    def __init__(self, max_age_seconds: float = 30) -> None:
        if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("Maximum observation age must be finite and positive.")
        self.max_age_seconds = max_age_seconds
        self.counts = Counter(
            {
                name: 0
                for name in (
                    "raw_vectors",
                    "accepted_airborne",
                    "analysis_eligible",
                    "analysis_quarantined",
                    "excluded_ground",
                    "excluded_invalid",
                    "excluded_stale",
                    "excluded_duplicate",
                    "excluded_out_of_order",
                )
            }
        )
        self.missing_fields = Counter({name: 0 for name in FIELDS})
        self.reasons = Counter()
        self.ranges: dict[str, dict[str, float]] = {}
        self.last_position: dict[tuple[str, str], int] = {}
        self.aircraft: set[str] = set()

    def _excluded(self, disposition: str, *reasons: str) -> AuditDecision:
        self.counts[f"excluded_{disposition}"] += 1
        self.reasons.update(reasons)
        return AuditDecision(disposition, tuple(reasons))

    def process(
        self,
        row: object,
        *,
        api_time: int,
        run_id: str,
        source_attempt_id: int,
    ) -> AuditDecision:
        self.counts["raw_vectors"] += 1
        if not isinstance(row, list) or len(row) < 17:
            return self._excluded("invalid", "malformed_vector")
        for name, index in FIELDS.items():
            value = row[index]
            if value is None:
                self.missing_fields[name] += 1
            elif name not in {"squawk", "time_position", "last_contact"} and finite_number(value):
                limits = self.ranges.setdefault(name, {"min": value, "max": value})
                limits["min"] = min(limits["min"], value)
                limits["max"] = max(limits["max"], value)
        if row[8] is True:
            return self._excluded("ground", "on_ground")
        if row[8] is not False:
            return self._excluded("invalid", "invalid_ground_status")
        missing_position = tuple(
            f"missing_{name}"
            for name in ("time_position", "last_contact", "longitude", "latitude")
            if row[FIELDS[name]] is None
        )
        if missing_position:
            return self._excluded("invalid", *missing_position)
        try:
            observation = Observation(
                run_id=run_id,
                source_attempt_id=source_attempt_id,
                api_time=api_time,
                icao24=row[0].lower() if isinstance(row[0], str) else row[0],
                callsign=row[1].strip() if isinstance(row[1], str) else row[1],
                origin_country=row[2],
                **{name: row[index] for name, index in FIELDS.items()},
            )
        except (ValueError, TypeError, OverflowError):
            return self._excluded("invalid", "invalid_value_or_timestamp")
        if api_time - observation.time_position > self.max_age_seconds:
            return self._excluded("stale", "stale_position")
        key = (run_id, observation.icao24)
        previous = self.last_position.get(key)
        if previous is not None and observation.time_position <= previous:
            if observation.time_position == previous:
                return self._excluded("duplicate", "duplicate_position_timestamp")
            return self._excluded("out_of_order", "out_of_order_position_timestamp")
        self.last_position[key] = observation.time_position
        self.aircraft.add(observation.icao24)
        self.counts["accepted_airborne"] += 1
        if observation.analysis_eligible:
            self.counts["analysis_eligible"] += 1
        else:
            self.counts["analysis_quarantined"] += 1
        reasons = tuple(f"missing_{name}" for name in observation.missing_analysis_fields)
        self.reasons.update(reasons)
        return AuditDecision("accepted", reasons, observation)

    def report(self) -> dict:
        return {
            "counts": dict(self.counts),
            "missing_fields": dict(self.missing_fields),
            "reason_counts": dict(self.reasons),
            "raw_numeric_ranges": self.ranges,
            "unique_accepted_aircraft": len(self.aircraft),
        }


def audit_recording(
    database: Path,
    output_dir: Path,
    *,
    max_age_seconds: float = 30,
) -> dict:
    """Export only the database prefix visible at start; never alter the raw input."""
    if output_dir.resolve() == database.resolve().parent:
        raise ValueError("Use a separate output directory for derived data.")
    audit = TelemetryAudit(max_age_seconds)
    stem = database.stem
    observations_path = output_dir / f"{stem}.observations.jsonl"
    exclusions_path = output_dir / f"{stem}.exclusions.jsonl"
    report_path = output_dir / f"{stem}.audit.json"
    polls = Counter(
        {
            name: 0
            for name in (
                "total",
                "failed",
                "successful",
                "invalid_success_payload",
                "empty_successful",
            )
        }
    )
    with RecordingReader(database) as reader:
        with (
            atomic_text(observations_path) as observations,
            atomic_text(exclusions_path) as exclusions,
        ):
            for attempt in reader.attempts():
                polls["total"] += 1
                if attempt["outcome"] != "success":
                    polls["failed"] += 1
                    write_json_line(
                        exclusions,
                        {
                            "source_attempt_id": attempt["id"],
                            "run_id": attempt["run_id"],
                            "scope": "poll",
                            "reasons": ["provider_poll_failed"],
                            "phase": attempt["phase"],
                            "outcome": attempt["outcome"],
                        },
                    )
                    continue
                polls["successful"] += 1
                try:
                    payload = json.loads(attempt["raw_body"])
                    if not isinstance(payload, dict) or "states" not in payload:
                        raise ValueError
                    api_time = payload.get("time")
                    states = payload["states"]
                    if not timestamp(api_time) or api_time != attempt["api_time"]:
                        raise ValueError
                    if states is None:
                        states = []
                    if not isinstance(states, list):
                        raise ValueError
                except (ValueError, TypeError):
                    polls["invalid_success_payload"] += 1
                    write_json_line(
                        exclusions,
                        {
                            "source_attempt_id": attempt["id"],
                            "run_id": attempt["run_id"],
                            "scope": "poll",
                            "reasons": ["invalid_snapshot_envelope"],
                        },
                    )
                    continue
                if not states:
                    polls["empty_successful"] += 1
                for index, row in enumerate(states):
                    decision = audit.process(
                        row,
                        api_time=api_time,
                        run_id=attempt["run_id"],
                        source_attempt_id=attempt["id"],
                    )
                    if decision.observation is not None:
                        write_json_line(observations, asdict(decision.observation))
                    if decision.reasons:
                        write_json_line(
                            exclusions,
                            {
                                "source_attempt_id": attempt["id"],
                                "run_id": attempt["run_id"],
                                "vector_index": index,
                                "scope": "analysis" if decision.observation else "tracking",
                                "disposition": decision.disposition,
                                "reasons": decision.reasons,
                            },
                        )
        report = {
            "schema_version": 1,
            "source_database": str(reader.path),
            "max_attempt_id": reader.max_attempt_id,
            "max_age_seconds": max_age_seconds,
            "polls": dict(polls),
            **audit.report(),
            "outputs": {
                "observations": str(observations_path),
                "exclusions": str(exclusions_path),
                "report": str(report_path),
            },
        }
    write_report(report_path, report)
    return report
