"""Causal sliding-window kinematics, without imputing missing telemetry."""

import math
from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path

from airspace_monitor.exports import atomic_text, write_json_line, write_report
from airspace_monitor.geo import haversine_distance_m, spherical_center
from airspace_monitor.preprocess import (
    ANALYSIS_FIELDS,
    Observation,
    finite_number,
    read_observations,
)
from airspace_monitor.trajectories import TrajectoryBuilder

ML_FEATURE_ORDER = (
    "velocity_mps",
    "vertical_rate_mps",
    "abs_turn_rate_deg_s",
    "tortuosity",
    "baro_altitude_m",
)


def heading_delta_degrees(before: float, after: float) -> float | None:
    """Shortest signed turn, clockwise positive; an exact half-turn is ambiguous."""
    delta = (after - before + 180) % 360 - 180
    return None if math.isclose(abs(delta), 180, abs_tol=1e-9, rel_tol=0) else delta


@dataclass(frozen=True)
class WindowConfig:
    window_seconds: float = 300
    min_duration_seconds: float = 180
    min_points: int = 8
    max_sample_gap_seconds: float = 45
    max_segment_gap_seconds: float = 120
    min_net_displacement_m: float = 1

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not finite_number(value) or value <= 0:
                raise ValueError(f"Window configuration {name} must be finite and positive.")
        if type(self.min_points) is not int or self.min_points < 2:
            raise ValueError("A feature window needs at least two points.")
        if self.min_duration_seconds > self.window_seconds:
            raise ValueError("Minimum duration cannot exceed the window length.")


def window_metrics(points: list[Observation], config: WindowConfig) -> dict:
    first, last = points[0], points[-1]
    duration = last.time_position - first.time_position
    pairs = list(zip(points, points[1:]))
    intervals = [b.time_position - a.time_position for a, b in pairs]
    max_interval = max(intervals) if intervals else None
    flags = []
    if len(points) < config.min_points:
        flags.append("insufficient_points")
    if duration < config.min_duration_seconds:
        flags.append("insufficient_duration")
    if max_interval is not None and max_interval > config.max_sample_gap_seconds:
        flags.append("sparse_window")
    window_ready = not flags
    missing = {
        name: sum(getattr(point, name) is None for point in points) for name in ANALYSIS_FIELDS
    }
    flags.extend(f"missing_{name}" for name, count in missing.items() if count)

    positions = [(point.latitude, point.longitude) for point in points]
    path = math.fsum(haversine_distance_m(*a, *b) for a, b in zip(positions, positions[1:]))
    displacement = haversine_distance_m(*positions[0], *positions[-1])
    tortuosity = path / displacement if displacement >= config.min_net_displacement_m else None
    if tortuosity is None:
        flags.append("near_zero_displacement")
    straightness = displacement / path if path > 0 else None
    center = spherical_center(positions)
    radius = max(haversine_distance_m(*center, *p) for p in positions) if center else None
    if center is None:
        flags.append("undefined_position_center")

    deltas = []
    if not missing["true_track"]:
        deltas = [heading_delta_degrees(a.true_track, b.true_track) for a, b in pairs]
    ambiguous_turn = any(delta is None for delta in deltas)
    if ambiguous_turn:
        flags.append("ambiguous_heading_change")
    signed_turn = absolute_turn = None
    if pairs and not missing["true_track"] and not ambiguous_turn:
        signed_turn = math.fsum(deltas)
        absolute_turn = math.fsum(abs(delta) for delta in deltas)

    gradient = None
    if last.velocity is not None and last.vertical_rate is not None:
        if last.velocity > 0:
            gradient = math.degrees(math.atan2(last.vertical_rate, last.velocity))
        else:
            flags.append("zero_horizontal_speed")
    vertical_acceleration = None
    last_turn_rate = None
    if pairs:
        previous = points[-2]
        dt = last.time_position - previous.time_position
        if last.vertical_rate is not None and previous.vertical_rate is not None:
            vertical_acceleration = (last.vertical_rate - previous.vertical_rate) / dt
        if last.true_track is not None and previous.true_track is not None:
            delta = heading_delta_degrees(previous.true_track, last.true_track)
            last_turn_rate = delta / dt if delta is not None else None
    altitude_change = None
    if pairs and first.baro_altitude is not None and last.baro_altitude is not None:
        altitude_change = last.baro_altitude - first.baro_altitude
    metrics = {
        "velocity_mps": last.velocity,
        "vertical_rate_mps": last.vertical_rate,
        "baro_altitude_m": last.baro_altitude,
        "path_length_m": path,
        "net_displacement_m": displacement,
        "tortuosity": tortuosity,
        "straightness": straightness,
        "bounding_radius_m": radius,
        "center_latitude_deg": center[0] if center else None,
        "center_longitude_deg": center[1] if center else None,
        "unwrapped_turn_deg": signed_turn,
        "cumulative_abs_turn_deg": absolute_turn,
        "net_turn_rate_deg_s": signed_turn / duration if signed_turn is not None else None,
        "abs_turn_rate_deg_s": absolute_turn / duration if absolute_turn is not None else None,
        "last_turn_rate_deg_s": last_turn_rate,
        "descent_gradient_deg": gradient,
        "vertical_acceleration_mps2": vertical_acceleration,
        "altitude_change_m": altitude_change,
        "altitude_change_rate_mps": altitude_change / duration
        if altitude_change is not None
        else None,
        "last_contact_gap_s": last.api_time - last.last_contact,
        "position_age_s": last.api_time - last.time_position,
    }
    # Valid finite inputs can still overflow during subtraction. Never emit JSON infinity.
    for name, value in metrics.items():
        if value is not None and not finite_number(value):
            metrics[name] = None
            flags.append(f"nonfinite_{name}")
    ml_eligible = (
        window_ready
        and not any(missing.values())
        and all(metrics[name] is not None for name in ML_FEATURE_ORDER)
        and not any(flag.startswith("nonfinite_") for flag in flags)
    )
    return {
        "window_start_position_time": first.time_position,
        "window_end_position_time": last.time_position,
        "duration_seconds": duration,
        "point_count": len(points),
        "max_observation_interval_seconds": max_interval,
        "window_ready": window_ready,
        "ml_eligible": ml_eligible,
        "quality_flags": flags,
        "missing_telemetry_counts": missing,
        "metrics": metrics,
        "ml_vector": [metrics[name] for name in ML_FEATURE_ORDER] if ml_eligible else None,
    }


class FeatureExtractor:
    def __init__(self, config: WindowConfig | None = None) -> None:
        self.config = config or WindowConfig()
        self.builder = TrajectoryBuilder(self.config.max_segment_gap_seconds)
        self.windows: dict[tuple[str, str], deque[Observation]] = {}
        self.counts = {"features_written": 0, "ready_windows": 0, "ml_eligible_windows": 0}
        self.flags: Counter[str] = Counter()
        self.source_prefix = {"min_api_time": None, "max_api_time": None, "max_attempt_id": 0}

    def add(self, observation: Observation) -> dict | None:
        for key, reducer in (("min_api_time", min), ("max_api_time", max)):
            previous = self.source_prefix[key]
            self.source_prefix[key] = (
                observation.api_time
                if previous is None
                else reducer(previous, observation.api_time)
            )
        self.source_prefix["max_attempt_id"] = max(
            self.source_prefix["max_attempt_id"],
            observation.source_attempt_id,
        )
        tagged = self.builder.add(observation)
        if tagged is None:
            return None
        key = (observation.run_id, observation.icao24)
        if tagged["starts_segment"]:
            self.windows[key] = deque()
        window = self.windows[key]
        window.append(observation)
        cutoff = observation.time_position - self.config.window_seconds
        while window[0].time_position < cutoff:
            window.popleft()
        features = window_metrics(list(window), self.config)
        self.counts["features_written"] += 1
        self.counts["ready_windows"] += int(features["window_ready"])
        self.counts["ml_eligible_windows"] += int(features["ml_eligible"])
        self.flags.update(features["quality_flags"])
        return {
            "segment_id": tagged["segment_id"],
            "run_id": observation.run_id,
            "icao24": observation.icao24,
            "source_attempt_id": observation.source_attempt_id,
            "as_of_api_time": observation.api_time,
            **features,
        }

    def report(self) -> dict:
        return {
            "configuration": asdict(self.config),
            "ml_feature_order": list(ML_FEATURE_ORDER),
            "counts": {**self.builder.counts, **self.counts},
            "quality_flag_counts": dict(self.flags),
            "source_observation_prefix": dict(self.source_prefix),
        }


def export_features(
    observations_path: Path,
    output_dir: Path,
    *,
    config: WindowConfig | None = None,
) -> dict:
    extractor = FeatureExtractor(config)
    stem = observations_path.name.removesuffix(".jsonl").removesuffix(".observations")
    features_path = output_dir / f"{stem}.features.jsonl"
    report_path = output_dir / f"{stem}.features.json"
    if observations_path.resolve() in {features_path.resolve(), report_path.resolve()}:
        raise ValueError("Feature outputs must not overwrite source observations.")
    with observations_path.open(encoding="utf-8") as source, atomic_text(features_path) as target:
        for observation in read_observations(source):
            features = extractor.add(observation)
            if features is not None:
                write_json_line(target, features)
    report = {
        "schema_version": 1,
        "source_observations": str(observations_path.resolve()),
        **extractor.report(),
        "outputs": {"features": str(features_path), "report": str(report_path)},
    }
    write_report(report_path, report)
    return report
