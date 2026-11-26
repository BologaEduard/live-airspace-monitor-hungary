"""Replayable rule engine over recorded polls, including explicit source uncertainty."""

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from airspace_monitor.alerts import AlertTracker
from airspace_monitor.config import BoundingBox
from airspace_monitor.continuity import ContinuityRules
from airspace_monitor.exports import atomic_text, write_json_line, write_report
from airspace_monitor.features import FeatureExtractor, WindowConfig
from airspace_monitor.preprocess import Observation, TelemetryAudit, finite_number, timestamp
from airspace_monitor.recordings import RecordingReader
from airspace_monitor.rules import AlertCandidate, MotionRules, RuleConfig, squawk_candidate


@dataclass(frozen=True)
class DetectionBatch:
    alerts: list[dict]
    source_events: list[dict]


class RuleEngine:
    def __init__(
        self, config: RuleConfig | None = None, window: WindowConfig | None = None
    ) -> None:
        self.config = config or RuleConfig()
        self.audit = TelemetryAudit(self.config.source_max_age_seconds)
        self.features = FeatureExtractor(window)
        self.motion = MotionRules(self.config)
        self.continuity = ContinuityRules(self.config)
        self.tracker = AlertTracker()
        self.run_id: str | None = None
        self.bbox: BoundingBox | None = None
        self.last_api_time: int | None = None
        self.previous_fresh: set[str] = set()
        self.observations: dict[str, Observation] = {}
        self.motion_cache: dict[str, list[AlertCandidate]] = {}
        self.capture_times: dict[str, int] = {}
        self.counts = Counter({"polls_read": 0, "usable_snapshots": 0})
        self.source_reasons: Counter[str] = Counter()

    def _source_event(self, attempt: dict, reason: str, clock: int | None) -> dict:
        self.source_reasons[reason] += 1
        return {
            "source_attempt_id": attempt["id"],
            "run_id": attempt["run_id"],
            "event_time": clock,
            "reason": reason,
            "phase": attempt["phase"],
            "outcome": attempt["outcome"],
            "http_status": attempt["http_status"],
            "source_api_time": attempt["api_time"],
        }

    def _reset(self, clock: int | None, reason: str) -> list[dict]:
        self.continuity.clear()
        self.motion.clear()
        self.motion_cache.clear()
        self.previous_fresh.clear()
        self.last_api_time = None
        return self.tracker.close_all(clock, reason)

    def _unavailable(self, attempt: dict, reason: str, clock: int | None) -> DetectionBatch:
        return DetectionBatch(
            self._reset(clock, reason), [self._source_event(attempt, reason, clock)]
        )

    def process_poll(self, attempt: dict) -> DetectionBatch:
        """Use collection completion as event time; API time governs measurement ages."""
        self.counts["polls_read"] += 1
        try:
            completed = datetime.fromisoformat(attempt["completed_at"])
            if completed.tzinfo is None:
                raise ValueError
            clock = int(completed.timestamp())
            if not timestamp(clock):
                raise ValueError
        except (ValueError, TypeError, OverflowError, OSError):
            return self._unavailable(attempt, "invalid_capture_time", None)
        run_id = attempt["run_id"]
        if not isinstance(run_id, str) or not run_id.strip():
            return self._unavailable(attempt, "invalid_snapshot_or_scope", clock)
        previous_clock = self.capture_times.get(run_id)
        if previous_clock is not None and clock < previous_clock:
            return self._unavailable(attempt, "capture_time_regressed", None)
        self.capture_times[run_id] = clock
        if attempt["outcome"] != "success":
            return self._unavailable(attempt, "provider_poll_failed", clock)
        try:
            scope = json.loads(attempt["bbox_json"])
            if (
                not isinstance(scope, dict)
                or set(scope) != {"lamin", "lomin", "lamax", "lomax"}
                or not all(finite_number(value) for value in scope.values())
            ):
                raise ValueError
            bbox = BoundingBox(**scope)
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
            return self._unavailable(attempt, "invalid_snapshot_or_scope", clock)
        if api_time > clock or clock - api_time > self.config.source_max_age_seconds:
            return self._unavailable(attempt, "stale_or_future_source_time", clock)
        alerts, source_events = [], []
        if self.run_id == run_id and self.bbox != bbox:
            return self._unavailable(attempt, "scope_changed_within_run", clock)
        if self.run_id is not None and (self.run_id != attempt["run_id"] or self.bbox != bbox):
            alerts.extend(self._reset(clock, "collection_scope_changed"))
            self.observations.clear()
        self.run_id, self.bbox = attempt["run_id"], bbox
        if self.last_api_time is not None and api_time <= self.last_api_time:
            if api_time < self.last_api_time:
                return self._unavailable(attempt, "source_time_regressed", clock)
            return DetectionBatch([], [self._source_event(attempt, "nonadvancing_snapshot", clock)])

        rows = []
        fresh_airborne: set[str] = set()
        fresh_contacts: set[str] = set()
        for row in states:
            decision = self.audit.process(
                row,
                api_time=api_time,
                run_id=self.run_id,
                source_attempt_id=attempt["id"],
            )
            features = None
            if decision.observation is not None:
                self.observations[decision.observation.icao24] = decision.observation
                features = self.features.add(decision.observation)
            if not isinstance(row, list) or len(row) < 17:
                continue
            icao24 = row[0].lower() if isinstance(row[0], str) else ""
            if re.fullmatch(r"[0-9a-f]{6}", icao24) is None:
                continue
            contact = row[4] if timestamp(row[4]) and row[4] <= api_time else None
            if contact is not None and api_time - contact <= self.config.source_max_age_seconds:
                fresh_contacts.add(icao24)
                if row[8] is False:
                    fresh_airborne.add(icao24)
            rows.append((icao24, row, contact, decision, features))
        if not fresh_airborne:
            result = self._unavailable(attempt, "no_fresh_airborne_witness", clock)
            return DetectionBatch(alerts + result.alerts, source_events + result.source_events)
        if (
            self.last_api_time is not None
            and api_time - self.last_api_time > self.config.source_max_gap_seconds
        ):
            alerts.extend(self._reset(clock, "source_observation_gap"))
            source_events.append(self._source_event(attempt, "source_observation_gap", clock))
        lost = self.previous_fresh - fresh_airborne
        if (
            len(self.previous_fresh) >= self.config.mass_loss_min_population
            and len(lost) / len(self.previous_fresh) >= self.config.mass_loss_fraction
        ):
            alerts.extend(self._reset(clock, "mass_disappearance"))
            source_events.append(self._source_event(attempt, "mass_disappearance", clock))

        candidates = []
        visible_motion = set()
        for icao24, row, contact, decision, features in rows:
            self.continuity.contact(icao24, contact, row[8])
            if row[8] is not False:
                self.motion.forget(self.run_id, icao24)
            # Source contact updates remain significant even for duplicate/missing positions.
            obs = decision.observation
            if obs is None and decision.disposition == "duplicate" and icao24 in fresh_airborne:
                obs = self.observations.get(icao24)
            if obs is not None:
                self.continuity.observe(obs)
            if features is not None:
                self.motion_cache[icao24] = self.motion.evaluate(
                    decision.observation, features, bbox
                )
            if (
                icao24 in fresh_airborne
                and decision.disposition in {"accepted", "duplicate"}
                and icao24 in self.motion_cache
            ):
                candidates.extend(self.motion_cache[icao24])
                visible_motion.add(icao24)
            if icao24 in fresh_airborne:
                emergency = squawk_candidate(
                    row[14],
                    run_id=self.run_id,
                    icao24=icao24,
                    source_attempt_id=attempt["id"],
                    api_time=api_time,
                    last_contact=contact,
                )
                if emergency is not None:
                    candidates.append(emergency)
        self.motion_cache = {
            key: value for key, value in self.motion_cache.items() if key in visible_motion
        }
        candidates.extend(
            self.continuity.candidates(
                api_time=api_time,
                source_attempt_id=attempt["id"],
                bbox=bbox,
                fresh_airborne_count=len(fresh_airborne),
            )
        )
        alerts.extend(self.tracker.reconcile(candidates, clock, fresh_contacts))
        self.last_api_time = api_time
        self.previous_fresh = fresh_airborne
        self.counts["usable_snapshots"] += 1
        return DetectionBatch(alerts, source_events)

    def report(self) -> dict:
        return {
            "rule_configuration": asdict(self.config),
            "counts": dict(self.counts),
            "source_reason_counts": dict(self.source_reasons),
            "alert_event_counts": dict(self.tracker.counts),
            "opened_alert_counts_by_type": dict(self.tracker.opened_by_type),
            "continuity_abstention_counts": dict(self.continuity.abstentions),
            "audit": self.audit.report(),
            "features": self.features.report(),
            "active_alert_count": len(self.tracker.active),
            "top_active_alerts": self.tracker.top_active(),
        }


def detect_recording(database: Path, output_dir: Path, *, config: RuleConfig | None = None) -> dict:
    if output_dir.resolve() == database.resolve().parent:
        raise ValueError("Use a separate directory for detection outputs.")
    engine = RuleEngine(config)
    alerts_path = output_dir / f"{database.stem}.alerts.jsonl"
    source_path = output_dir / f"{database.stem}.source-events.jsonl"
    report_path = output_dir / f"{database.stem}.detection.json"
    with RecordingReader(database) as reader:
        with atomic_text(alerts_path) as alerts, atomic_text(source_path) as sources:
            for attempt in reader.attempts():
                batch = engine.process_poll(attempt)
                for event in batch.alerts:
                    write_json_line(alerts, event)
                for event in batch.source_events:
                    write_json_line(sources, event)
        report = {
            "schema_version": 1,
            "source_database": str(reader.path),
            "max_attempt_id": reader.max_attempt_id,
            **engine.report(),
            "outputs": {
                "alerts": str(alerts_path),
                "source_events": str(source_path),
                "report": str(report_path),
            },
        }
    write_report(report_path, report)
    return report
