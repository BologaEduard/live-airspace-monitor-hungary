"""Stable alert identities and explicit lifecycle reasons for a bounded active panel."""

from collections import Counter
from dataclasses import asdict

from airspace_monitor.rules import AlertCandidate

SEVERITY = {"critical": 3, "warning": 2, "info": 1}


class AlertTracker:
    def __init__(self) -> None:
        self.active: dict[tuple[str, str, str], dict] = {}
        self.counts: Counter[str] = Counter({name: 0 for name in ("opened", "updated", "closed")})
        self.opened_by_type: Counter[str] = Counter()

    def close_all(self, event_time: int | None, reason: str) -> list[dict]:
        events = []
        for key in sorted(self.active):
            previous = self.active[key]
            events.append(
                {**previous, "event": "closed", "event_time": event_time, "close_reason": reason}
            )
            self.counts["closed"] += 1
        self.active.clear()
        return events

    def reconcile(
        self,
        candidates: list[AlertCandidate],
        event_time: int,
        fresh_contacts: set[str],
    ) -> list[dict]:
        events = []
        current = {(c.run_id, c.icao24, c.alert_type): c for c in candidates}
        for key in sorted(set(self.active) - set(current)):
            previous = self.active.pop(key)
            if previous["alert_type"] == "signal_loss":
                reason = (
                    "contact_reacquired"
                    if previous["icao24"] in fresh_contacts
                    else "context_uncertain"
                )
            else:
                reason = (
                    "condition_no_longer_observed"
                    if previous["icao24"] in fresh_contacts
                    else "observation_unavailable"
                )
            events.append(
                {**previous, "event": "closed", "event_time": event_time, "close_reason": reason}
            )
            self.counts["closed"] += 1
        for key, candidate in sorted(current.items()):
            old = self.active.get(key)
            event = "updated" if old else "opened"
            snapshot = {
                **asdict(candidate),
                "alert_id": old["alert_id"] if old else ":".join((*key, str(event_time))),
                "first_seen": old["first_seen"] if old else event_time,
                "last_seen": event_time,
            }
            self.active[key] = snapshot
            events.append({**snapshot, "event": event, "event_time": event_time})
            self.counts[event] += 1
            if event == "opened":
                self.opened_by_type[candidate.alert_type] += 1
        return events

    def top_active(self, limit: int = 5) -> list[dict]:
        return sorted(
            self.active.values(),
            key=lambda alert: (
                -SEVERITY[alert["severity"]],
                -alert["last_seen"],
                alert["alert_id"],
            ),
        )[:limit]
