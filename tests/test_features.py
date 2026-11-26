import json
import math
from dataclasses import asdict, replace

import pytest

from airspace_monitor.features import FeatureExtractor, WindowConfig, export_features
from airspace_monitor.geo import EARTH_RADIUS_M, haversine_distance_m, spherical_center
from airspace_monitor.preprocess import TelemetryAudit


@pytest.fixture
def observation(state_vector):
    return (
        TelemetryAudit()
        .process(
            state_vector(),
            api_time=100,
            run_id="run1",
            source_attempt_id=1,
        )
        .observation
    )


def at(observation, t, **fields):
    return replace(observation, time_position=t, last_contact=t, api_time=t, **fields)


def test_surface_geometry_handles_metres_dateline_and_antipodes():
    assert haversine_distance_m(47, 19, 47, 19) == 0
    assert haversine_distance_m(0, 0, 0, 1) == pytest.approx(111195.08, abs=0.1)
    assert haversine_distance_m(0, 179.9, 0, -179.9) == pytest.approx(22239.016, abs=0.1)
    assert haversine_distance_m(0, 0, 0, 180) == pytest.approx(math.pi * EARTH_RADIUS_M)
    assert abs(spherical_center([(0, 179.9), (0, -179.9)])[1]) == pytest.approx(180)
    assert spherical_center([(0, 0), (0, 180)]) is None


@pytest.mark.parametrize(
    "coordinates",
    [
        (91, 0, 0, 0),
        (0, float("nan"), 0, 0),
        (True, 0, 0, 0),
    ],
)
def test_invalid_surface_coordinates_are_rejected(coordinates):
    with pytest.raises(ValueError):
        haversine_distance_m(*coordinates)


def test_straight_constant_descent_produces_ready_features(observation):
    extractor = FeatureExtractor()
    rate = 220 * math.tan(math.radians(-3))
    for i in range(13):
        row = extractor.add(
            at(
                observation,
                100 + 15 * i,
                latitude=0,
                longitude=i * 0.01,
                true_track=90,
                vertical_rate=rate,
                baro_altitude=10000 + rate * 15 * i,
            )
        )
    metrics = row["metrics"]
    assert row["window_ready"] and row["ml_eligible"]
    assert row["duration_seconds"] == 180 and row["point_count"] == 13
    assert metrics["path_length_m"] == pytest.approx(metrics["net_displacement_m"])
    assert metrics["tortuosity"] == pytest.approx(1)
    assert metrics["straightness"] == pytest.approx(1)
    assert metrics["unwrapped_turn_deg"] == 0
    assert metrics["abs_turn_rate_deg_s"] == 0
    assert metrics["descent_gradient_deg"] == pytest.approx(-3)
    assert metrics["vertical_acceleration_mps2"] == 0
    assert metrics["altitude_change_rate_mps"] == pytest.approx(rate)
    assert row["ml_vector"] == [220, rate, 0, pytest.approx(1), metrics["baro_altitude_m"]]


@pytest.mark.parametrize("tracks,expected", [([359, 2], 3), ([2, 359], -3)])
def test_heading_wraparound_uses_short_signed_turn(observation, tracks, expected):
    extractor = FeatureExtractor()
    extractor.add(at(observation, 100, true_track=tracks[0]))
    row = extractor.add(at(observation, 115, true_track=tracks[1]))
    assert row["metrics"]["unwrapped_turn_deg"] == expected
    assert row["metrics"]["cumulative_abs_turn_deg"] == abs(expected)
    assert row["metrics"]["last_turn_rate_deg_s"] == pytest.approx(expected / 15)


def test_zigzag_is_not_a_signed_full_circle(observation):
    extractor = FeatureExtractor()
    for i, track in enumerate([0, 90, 0, 90, 0]):
        row = extractor.add(at(observation, 100 + i * 15, true_track=track))
    assert row["metrics"]["unwrapped_turn_deg"] == 0
    assert row["metrics"]["cumulative_abs_turn_deg"] == 360


def test_closed_circle_retains_turn_evidence_without_infinite_tortuosity(observation):
    extractor = FeatureExtractor()
    radius = 5000
    for i in range(13):
        angle = math.radians(i * 30)
        row = extractor.add(
            at(
                observation,
                100 + i * 15,
                latitude=math.degrees(radius * math.cos(angle) / EARTH_RADIUS_M),
                longitude=math.degrees(radius * math.sin(angle) / EARTH_RADIUS_M),
                true_track=(i * 30 + 90) % 360,
            )
        )
    assert row["window_ready"] and not row["ml_eligible"]
    assert row["metrics"]["unwrapped_turn_deg"] == 360
    assert row["metrics"]["cumulative_abs_turn_deg"] == 360
    assert row["metrics"]["tortuosity"] is None
    assert row["metrics"]["straightness"] == pytest.approx(0, abs=1e-10)
    assert 4500 < row["metrics"]["bounding_radius_m"] < 5500
    assert "near_zero_displacement" in row["quality_flags"]
    json.dumps(row, allow_nan=False)


def test_single_point_does_not_claim_zero_turn_or_zero_acceleration(observation):
    row = FeatureExtractor().add(observation)
    assert not row["window_ready"] and row["ml_vector"] is None
    assert row["metrics"]["unwrapped_turn_deg"] is None
    assert row["metrics"]["vertical_acceleration_mps2"] is None


def test_missing_headings_are_not_bridged(observation):
    extractor = FeatureExtractor()
    for i, heading in enumerate([359, None, 2]):
        row = extractor.add(at(observation, 100 + 15 * i, true_track=heading))
    assert row["metrics"]["unwrapped_turn_deg"] is None
    assert row["metrics"]["last_turn_rate_deg_s"] is None
    assert row["missing_telemetry_counts"]["true_track"] == 1
    assert "missing_true_track" in row["quality_flags"]


def test_exact_half_turn_is_marked_ambiguous(observation):
    extractor = FeatureExtractor()
    extractor.add(at(observation, 100, true_track=0))
    row = extractor.add(at(observation, 115, true_track=180))
    assert row["metrics"]["unwrapped_turn_deg"] is None
    assert "ambiguous_heading_change" in row["quality_flags"]


def test_turn_rate_uses_real_elapsed_time(observation):
    extractor = FeatureExtractor()
    for t, heading in [(100, 350), (110, 0), (140, 20)]:
        row = extractor.add(at(observation, t, true_track=heading))
    assert row["metrics"]["abs_turn_rate_deg_s"] == pytest.approx(30 / 40)
    assert row["metrics"]["last_turn_rate_deg_s"] == pytest.approx(20 / 30)


def test_vertical_acceleration_uses_last_pair_only(observation):
    extractor = FeatureExtractor()
    extractor.add(at(observation, 100, vertical_rate=-2))
    row = extractor.add(at(observation, 110, vertical_rate=-12))
    assert row["metrics"]["vertical_acceleration_mps2"] == -1
    extractor.add(at(observation, 120, vertical_rate=None))
    row = extractor.add(at(observation, 130, vertical_rate=-20))
    assert row["metrics"]["vertical_acceleration_mps2"] is None
    assert not row["ml_eligible"]


def test_zero_horizontal_speed_does_not_divide_by_zero(observation):
    row = FeatureExtractor().add(replace(observation, velocity=0, vertical_rate=-2))
    assert row["metrics"]["descent_gradient_deg"] is None
    assert row["metrics"]["velocity_mps"] == 0
    assert "zero_horizontal_speed" in row["quality_flags"]


def test_window_boundary_is_inclusive_and_missing_data_eventually_expires(observation):
    extractor = FeatureExtractor(
        WindowConfig(window_seconds=60, min_duration_seconds=30, min_points=3)
    )
    extractor.add(at(observation, 100, true_track=None))
    for i in range(1, 6):
        row = extractor.add(at(observation, 100 + i * 15, longitude=19.1 + i * 0.01))
        if i == 4:
            assert row["point_count"] == 5 and not row["ml_eligible"]
    assert row["window_start_position_time"] == 115
    assert row["point_count"] == 5 and row["ml_eligible"]


def test_segment_gaps_reset_windows_and_sparse_samples_are_flagged(observation):
    extractor = FeatureExtractor()
    first = extractor.add(observation)
    sparse = extractor.add(at(observation, 160))
    assert "sparse_window" in sparse["quality_flags"]
    split = extractor.add(at(observation, 281))
    assert split["segment_id"] != first["segment_id"]
    assert split["point_count"] == 1 and split["metrics"]["unwrapped_turn_deg"] is None


def test_independent_aircraft_and_runs_do_not_share_history(observation):
    extractor = FeatureExtractor()
    extractor.add(observation)
    a = extractor.add(at(observation, 115))
    b = extractor.add(at(observation, 115, icao24="def456"))
    c = extractor.add(at(observation, 115, run_id="other"))
    assert [a["point_count"], b["point_count"], c["point_count"]] == [2, 1, 1]


def test_duplicate_and_late_points_leave_window_unchanged(observation):
    extractor = FeatureExtractor()
    extractor.add(at(observation, 120))
    assert extractor.add(at(observation, 120)) is None
    assert extractor.add(at(observation, 110)) is None
    assert extractor.add(at(observation, 130))["point_count"] == 2
    assert extractor.report()["counts"]["duplicate_points"] == 1


def test_future_data_does_not_change_previous_feature_records(observation):
    sequence = [at(observation, 100 + i * 15, longitude=19 + i * 0.01) for i in range(5)]
    live = FeatureExtractor()
    snapshots = []
    for i, point in enumerate(sequence):
        snapshots.append(live.add(point))
        replay = FeatureExtractor()
        assert [replay.add(p) for p in sequence[: i + 1]] == snapshots


def test_arithmetic_overflow_is_explicit_and_json_safe(observation):
    extractor = FeatureExtractor()
    extractor.add(at(observation, 100, vertical_rate=1e308))
    row = extractor.add(at(observation, 115, vertical_rate=-1e308))
    assert row["metrics"]["vertical_acceleration_mps2"] is None
    assert "nonfinite_vertical_acceleration_mps2" in row["quality_flags"]
    json.dumps(row, allow_nan=False)


def test_feature_exports_are_repeatable_and_preserve_source(tmp_path, observation):
    source = tmp_path / "test.observations.jsonl"
    source.write_text("\n".join(json.dumps(asdict(at(observation, t))) for t in [100, 115]))
    original = source.read_bytes()
    first = export_features(source, tmp_path)
    data = (tmp_path / "test.features.jsonl").read_bytes()
    assert first["counts"]["features_written"] == 2
    assert first == export_features(source, tmp_path)
    assert (tmp_path / "test.features.jsonl").read_bytes() == data
    assert source.read_bytes() == original


def test_bad_observation_does_not_replace_previous_feature_export(tmp_path):
    source = tmp_path / "test.observations.jsonl"
    source.write_text("not-json")
    target = tmp_path / "test.features.jsonl"
    target.write_text("complete previous export")
    with pytest.raises(ValueError, match="line 1"):
        export_features(source, tmp_path)
    assert target.read_text() == "complete previous export"


@pytest.mark.parametrize(
    "settings",
    [
        {"window_seconds": 0},
        {"min_duration_seconds": -1},
        {"min_points": 1},
        {"min_points": 2.5},
        {"max_sample_gap_seconds": float("nan")},
        {"max_segment_gap_seconds": float("inf")},
        {"window_seconds": 100},
        {"min_net_displacement_m": 0},
    ],
)
def test_invalid_window_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        WindowConfig(**settings)
