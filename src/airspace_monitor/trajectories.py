"""Incrementally assign accepted observations to causal trajectory segments."""

import math
from dataclasses import asdict, dataclass
from pathlib import Path

from airspace_monitor.exports import atomic_text, write_json_line, write_report
from airspace_monitor.preprocess import Observation, read_observations


@dataclass
class Segment:
    segment_id: str
    run_id: str
    icao24: str
    number: int
    start_reason: str
    first_position_time: int
    last_position_time: int
    point_count: int = 0
    analysis_eligible_points: int = 0


class TrajectoryBuilder:
    def __init__(self, max_gap_seconds: float = 120) -> None:
        if not math.isfinite(max_gap_seconds) or max_gap_seconds <= 0:
            raise ValueError("Maximum trajectory gap must be finite and positive.")
        self.max_gap_seconds = max_gap_seconds
        self.active: dict[tuple[str, str], Segment] = {}
        self.segments: list[Segment] = []
        self.counts = {
            "observations_read": 0,
            "points_written": 0,
            "duplicate_points": 0,
            "out_of_order_points": 0,
        }

    def add(self, observation: Observation) -> dict | None:
        """Use only this observation and preceding state; never sort with future data."""
        self.counts["observations_read"] += 1
        key = (observation.run_id, observation.icao24)
        segment = self.active.get(key)
        if segment is not None:
            delta = observation.time_position - segment.last_position_time
            if delta <= 0:
                label = "duplicate_points" if delta == 0 else "out_of_order_points"
                self.counts[label] += 1
                return None
        starts_segment = segment is None or delta > self.max_gap_seconds
        if starts_segment:
            number = segment.number + 1 if segment else 1
            reason = "observation_gap" if segment else "first_observation"
            segment = Segment(
                segment_id=f"{observation.run_id}:{observation.icao24}:{number:04d}",
                run_id=observation.run_id,
                icao24=observation.icao24,
                number=number,
                start_reason=reason,
                first_position_time=observation.time_position,
                last_position_time=observation.time_position,
            )
            self.active[key] = segment
            self.segments.append(segment)
        point_index = segment.point_count
        segment.last_position_time = observation.time_position
        segment.point_count += 1
        segment.analysis_eligible_points += int(observation.analysis_eligible)
        self.counts["points_written"] += 1
        return {
            "segment_id": segment.segment_id,
            "segment_number": segment.number,
            "segment_start_reason": segment.start_reason,
            "starts_segment": starts_segment,
            "point_index": point_index,
            "analysis_eligible": observation.analysis_eligible,
            "observation": asdict(observation),
        }

    def report(self) -> dict:
        return {
            "counts": dict(self.counts),
            "segment_count": len(self.segments),
            "segments": [asdict(segment) for segment in self.segments],
        }


def segment_observations(
    observations_path: Path,
    output_dir: Path,
    *,
    max_gap_seconds: float = 120,
) -> dict:
    builder = TrajectoryBuilder(max_gap_seconds)
    stem = observations_path.name.removesuffix(".jsonl").removesuffix(".observations")
    points_path = output_dir / f"{stem}.trajectories.jsonl"
    report_path = output_dir / f"{stem}.segments.json"
    if observations_path.resolve() in {points_path.resolve(), report_path.resolve()}:
        raise ValueError("Trajectory output must not overwrite the input observations.")
    # Capture the opened file before exports. An audit's atomic replacement cannot change it.
    with observations_path.open(encoding="utf-8") as source, atomic_text(points_path) as target:
        for observation in read_observations(source):
            point = builder.add(observation)
            if point is not None:
                write_json_line(target, point)
    report = {
        "schema_version": 1,
        "source_observations": str(observations_path.resolve()),
        "max_gap_seconds": max_gap_seconds,
        **builder.report(),
        "outputs": {"trajectories": str(points_path), "report": str(report_path)},
    }
    write_report(report_path, report)
    return report
