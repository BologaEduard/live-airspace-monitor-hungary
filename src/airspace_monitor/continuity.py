"""Conservative contact-gap screening; caller must establish source health first."""

from collections import Counter
from dataclasses import dataclass

from airspace_monitor.airspace import boundary_distance_m, project_position, spatial_context
from airspace_monitor.config import BoundingBox
from airspace_monitor.geo import haversine_distance_m
from airspace_monitor.preprocess import Observation, finite_number
from airspace_monitor.rules import AlertCandidate, RuleConfig


@dataclass
class ContactState:
    observation: Observation
    latest_contact: int


class ContinuityRules:
    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()
        self.tracked: dict[str, ContactState] = {}
        self.abstentions: Counter[str] = Counter()

    def clear(self) -> None:
        self.tracked.clear()

    def contact(self, icao24: str, last_contact: int | None, on_ground: object) -> None:
        if on_ground is not False or last_contact is None:
            self.tracked.pop(icao24, None)
        elif icao24 in self.tracked:
            state = self.tracked[icao24]
            state.latest_contact = max(state.latest_contact, last_contact)

    def observe(self, obs: Observation) -> None:
        previous = self.tracked.get(obs.icao24)
        latest = max(obs.last_contact, previous.latest_contact) if previous else obs.last_contact
        self.tracked[obs.icao24] = ContactState(obs, latest)

    def candidates(
        self,
        *,
        api_time: int,
        source_attempt_id: int,
        bbox: BoundingBox,
        fresh_airborne_count: int,
    ) -> list[AlertCandidate]:
        candidates = []
        config = self.config
        if fresh_airborne_count < 1:
            self.abstentions["source_health_unknown"] += 1
            return candidates
        for icao24, state in list(self.tracked.items()):
            obs = state.observation
            gap = api_time - state.latest_contact
            if gap < config.loss_gap_seconds:
                continue
            position_age = api_time - obs.time_position
            if position_age > config.loss_max_position_age_seconds:
                self.abstentions["position_too_old"] += 1
                self.tracked.pop(icao24)
                continue
            if obs.baro_altitude is None or obs.velocity is None or obs.true_track is None:
                self.abstentions["missing_context_telemetry"] += 1
                continue
            if obs.baro_altitude <= config.loss_min_altitude_m:
                self.abstentions["low_altitude"] += 1
                continue
            projected_distance = obs.velocity * position_age
            if not finite_number(projected_distance):
                self.abstentions["invalid_projection"] += 1
                continue
            if projected_distance > haversine_distance_m(
                bbox.lamin,
                bbox.lomin,
                bbox.lamax,
                bbox.lomax,
            ):
                self.abstentions["possible_boundary_exit"] += 1
                continue
            projected = project_position(
                obs.latitude, obs.longitude, obs.true_track, projected_distance
            )
            context = spatial_context(obs.latitude, obs.longitude, bbox)
            projected_boundary = boundary_distance_m(*projected, bbox)
            if (
                min(context["observation_boundary_distance_m"], projected_boundary)
                < config.boundary_margin_m
            ):
                self.abstentions["possible_boundary_exit"] += 1
                continue
            projected_context = spatial_context(*projected, bbox)
            if (
                obs.baro_altitude <= config.airport_guard_altitude_m
                and min(context["airport_distance_m"], projected_context["airport_distance_m"])
                <= config.airport_guard_radius_m
            ):
                self.abstentions["possible_airport_arrival"] += 1
                continue
            evidence = {
                **context,
                "last_contact": state.latest_contact,
                "contact_gap_seconds": gap,
                "last_position_time": obs.time_position,
                "last_position_age_seconds": position_age,
                "last_baro_altitude_m": obs.baro_altitude,
                "last_velocity_mps": obs.velocity,
                "last_track_deg": obs.true_track,
                "projected_boundary_distance_m": projected_boundary,
                "fresh_other_airborne_count": fresh_airborne_count,
                "threshold_gap_seconds": config.loss_gap_seconds,
                "threshold_min_altitude_m": config.loss_min_altitude_m,
                "threshold_boundary_margin_m": config.boundary_margin_m,
                "airport_guard_radius_m": config.airport_guard_radius_m,
                "airport_guard_altitude_m": config.airport_guard_altitude_m,
            }
            candidates.append(
                AlertCandidate(
                    "signal_loss",
                    "warning",
                    obs.run_id,
                    icao24,
                    source_attempt_id,
                    api_time,
                    evidence,
                    f"No fresh contact for {gap} s; last barometric altitude "
                    f"{obs.baro_altitude:.0f} m; last position "
                    f"{context['observation_boundary_distance_m'] / 1000:.1f} km "
                    "inside observation bounds; "
                    f"{fresh_airborne_count} other fresh airborne contacts.",
                    (
                        "A contact gap does not establish transponder failure or an emergency.",
                        "Other traffic does not prove local receiver coverage.",
                        "Boundary-exit screening assumes constant last ground speed and track.",
                        "Airport context covers only three configured reference points.",
                    ),
                )
            )
        return candidates
