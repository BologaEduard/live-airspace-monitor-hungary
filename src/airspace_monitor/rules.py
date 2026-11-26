"""Transparent kinematic screening rules; thresholds require benchmark calibration."""

from dataclasses import asdict, dataclass

from airspace_monitor.airspace import spatial_context
from airspace_monitor.config import BoundingBox
from airspace_monitor.preprocess import Observation, finite_number

EMERGENCY_SQUAWKS = {
    "7500": "unlawful interference code",
    "7600": "radio communication failure code",
    "7700": "general emergency code",
}


@dataclass(frozen=True)
class RuleConfig:
    holding_turn_deg: float = 360
    holding_max_radius_m: float = 10000
    holding_max_progress_m: float = 10000
    holding_max_straightness: float = 0.35
    holding_min_turn_coherence: float = 0.8
    holding_min_speed_mps: float = 50
    descent_rate_mps: float = 15
    descent_gradient_deg: float = 6
    gradient_min_descent_mps: float = 8
    gradient_min_speed_mps: float = 50
    severe_descent_rate_mps: float = 30
    abrupt_acceleration_mps2: float = 1.5
    abrupt_min_descent_mps: float = 12
    descent_confirmation_seconds: float = 15
    descent_max_interval_seconds: float = 30
    loss_gap_seconds: float = 60
    loss_min_altitude_m: float = 1500
    loss_max_position_age_seconds: float = 180
    boundary_margin_m: float = 10000
    airport_guard_radius_m: float = 15000
    airport_guard_altitude_m: float = 3000
    source_max_age_seconds: float = 30
    source_max_gap_seconds: float = 45
    mass_loss_fraction: float = 0.5
    mass_loss_min_population: int = 5

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not finite_number(value) or value <= 0:
                raise ValueError(f"Rule configuration {name} must be finite and positive.")
        for name in (
            "holding_max_straightness",
            "holding_min_turn_coherence",
            "mass_loss_fraction",
        ):
            if getattr(self, name) > 1:
                raise ValueError("Rule fractions cannot exceed one.")
        if self.descent_gradient_deg >= 90:
            raise ValueError("Descent gradient threshold must be below 90 degrees.")
        if type(self.mass_loss_min_population) is not int or self.mass_loss_min_population < 2:
            raise ValueError("Mass-disappearance screening needs an integer population >= 2.")
        if self.severe_descent_rate_mps < self.descent_rate_mps:
            raise ValueError("Severe descent threshold cannot be below the ordinary threshold.")
        if self.loss_max_position_age_seconds < self.loss_gap_seconds:
            raise ValueError("Maximum loss-position age cannot be below the loss threshold.")


@dataclass(frozen=True)
class AlertCandidate:
    alert_type: str
    severity: str
    run_id: str
    icao24: str
    source_attempt_id: int
    source_api_time: int
    evidence: dict
    physical_evidence: str
    limitations: tuple[str, ...]


def squawk_candidate(
    code: object,
    *,
    run_id: str,
    icao24: str,
    source_attempt_id: int,
    api_time: int,
    last_contact: int,
) -> AlertCandidate | None:
    if not isinstance(code, str) or code not in EMERGENCY_SQUAWKS:
        return None
    return AlertCandidate(
        "emergency_squawk",
        "critical",
        run_id,
        icao24,
        source_attempt_id,
        api_time,
        {"squawk": code, "meaning": EMERGENCY_SQUAWKS[code], "last_contact": last_contact},
        f"Observed squawk {code}: {EMERGENCY_SQUAWKS[code]}.",
        ("An observed code is not independent confirmation of an emergency or descent.",),
    )


class MotionRules:
    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()
        self.descent_state: dict[tuple[str, str], tuple[str, int, int]] = {}

    def clear(self) -> None:
        self.descent_state.clear()

    def forget(self, run_id: str, icao24: str) -> None:
        self.descent_state.pop((run_id, icao24), None)

    def evaluate(self, obs: Observation, features: dict, bbox: BoundingBox) -> list[AlertCandidate]:
        config = self.config
        metrics = features["metrics"]
        context = spatial_context(obs.latitude, obs.longitude, bbox)
        candidates = []
        turn = metrics["unwrapped_turn_deg"]
        absolute = metrics["cumulative_abs_turn_deg"]
        radius = metrics["bounding_radius_m"]
        straightness = metrics["straightness"]
        progress = metrics["net_displacement_m"]
        if (
            features["window_ready"]
            and obs.velocity is not None
            and obs.velocity >= config.holding_min_speed_mps
            and all(value is not None for value in (turn, absolute, radius, straightness, progress))
            and abs(turn) + 1e-6 >= config.holding_turn_deg
            and absolute > 0
            and abs(turn) / absolute >= config.holding_min_turn_coherence
            and radius <= config.holding_max_radius_m
            and progress <= config.holding_max_progress_m
            and straightness <= config.holding_max_straightness
        ):
            evidence = {
                **context,
                "unwrapped_turn_deg": turn,
                "cumulative_abs_turn_deg": absolute,
                "duration_seconds": features["duration_seconds"],
                "bounding_radius_m": radius,
                "net_displacement_m": progress,
                "straightness": straightness,
                "threshold_turn_deg": config.holding_turn_deg,
                "threshold_max_radius_m": config.holding_max_radius_m,
                "threshold_max_progress_m": config.holding_max_progress_m,
                "threshold_max_straightness": config.holding_max_straightness,
                "threshold_min_turn_coherence": config.holding_min_turn_coherence,
                "threshold_min_speed_mps": config.holding_min_speed_mps,
                "window_point_count": features["point_count"],
                "max_observation_interval_seconds": features["max_observation_interval_seconds"],
                "velocity_mps": obs.velocity,
            }
            candidates.append(
                AlertCandidate(
                    "holding_pattern",
                    "info",
                    obs.run_id,
                    obs.icao24,
                    obs.source_attempt_id,
                    obs.api_time,
                    evidence,
                    f"Net turn {turn:.1f} deg in {features['duration_seconds']} s; "
                    f"sample-centred radius {radius / 1000:.2f} km; "
                    f"net progress {progress / 1000:.2f} km.",
                    ("Holding-like motion may be normal ATC behaviour; intent is unknown.",),
                )
            )
        key = (obs.run_id, obs.icao24)
        vr = obs.vertical_rate
        gradient = metrics["descent_gradient_deg"]
        acceleration = metrics["vertical_acceleration_mps2"]
        rapid = vr is not None and vr <= -config.descent_rate_mps
        steep = (
            vr is not None
            and vr <= -config.gradient_min_descent_mps
            and obs.velocity is not None
            and obs.velocity >= config.gradient_min_speed_mps
            and gradient is not None
            and gradient <= -config.descent_gradient_deg
        )
        severe = vr is not None and vr <= -config.severe_descent_rate_mps
        abrupt = (
            vr is not None
            and vr <= -config.abrupt_min_descent_mps
            and acceleration is not None
            and acceleration <= -config.abrupt_acceleration_mps2
            and "sparse_window" not in features["quality_flags"]
        )
        confirmed_for = 0
        if rapid or steep:
            previous = self.descent_state.get(key)
            if (
                previous is None
                or previous[0] != features["segment_id"]
                or obs.time_position - previous[2] > config.descent_max_interval_seconds
            ):
                start = obs.time_position
            else:
                start = previous[1]
            self.descent_state[key] = (features["segment_id"], start, obs.time_position)
            confirmed_for = obs.time_position - start
        else:
            self.descent_state.pop(key, None)
        if severe or abrupt or confirmed_for >= config.descent_confirmation_seconds:
            reasons = [
                name
                for name, active in (
                    ("rapid_descent", rapid),
                    ("steep_ground_path", steep),
                    ("extreme_descent_rate", severe),
                    ("rapid_vertical_speed_change", abrupt),
                )
                if active
            ]
            evidence = {
                **context,
                "vertical_rate_mps": vr,
                "velocity_mps": obs.velocity,
                "baro_altitude_m": obs.baro_altitude,
                "descent_gradient_deg": gradient,
                "vertical_acceleration_mps2": acceleration,
                "confirmed_duration_seconds": confirmed_for,
                "triggers": reasons,
                "threshold_descent_rate_mps": config.descent_rate_mps,
                "threshold_descent_gradient_deg": config.descent_gradient_deg,
                "threshold_severe_descent_rate_mps": config.severe_descent_rate_mps,
                "threshold_abrupt_acceleration_mps2": config.abrupt_acceleration_mps2,
                "threshold_abrupt_min_descent_mps": config.abrupt_min_descent_mps,
                "threshold_gradient_min_descent_mps": config.gradient_min_descent_mps,
                "threshold_gradient_min_speed_mps": config.gradient_min_speed_mps,
                "threshold_confirmation_seconds": config.descent_confirmation_seconds,
                "quality_flags": features["quality_flags"],
            }
            gradient_text = (
                f"ground-path angle {gradient:.2f} deg; "
                if gradient is not None
                else "ground-path angle unavailable; "
            )
            acceleration_text = f"sample acceleration {acceleration:.2f} m/s2; " if abrupt else ""
            candidates.append(
                AlertCandidate(
                    "unusual_descent",
                    "critical" if severe else "warning",
                    obs.run_id,
                    obs.icao24,
                    obs.source_attempt_id,
                    obs.api_time,
                    evidence,
                    f"Vertical speed {vr:.2f} m/s; "
                    f"{gradient_text}{acceleration_text}qualifying samples span {confirmed_for} s; "
                    f"{context['airport_distance_m'] / 1000:.1f} km "
                    f"from {context['nearest_configured_airport']}.",
                    (
                        "Ground kinematics do not establish aircraft intent or ILS alignment.",
                        "Barometric altitude is not height above terrain.",
                    ),
                )
            )
        return candidates
