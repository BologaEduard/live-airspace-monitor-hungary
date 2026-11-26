import json
import math
from dataclasses import replace

import pytest

from airspace_monitor.airspace import (
    AIRPORTS,
    boundary_distance_m,
    project_position,
    spatial_context,
)
from airspace_monitor.alerts import AlertTracker
from airspace_monitor.config import BoundingBox
from airspace_monitor.features import FeatureExtractor
from airspace_monitor.preprocess import TelemetryAudit
from airspace_monitor.rules import MotionRules, RuleConfig, squawk_candidate


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


def at(obs, time, **fields):
    return replace(obs, api_time=time, time_position=time, last_contact=time, **fields)


def evaluate(observations):
    features, rules = FeatureExtractor(), MotionRules()
    return [rules.evaluate(obs, features.add(obs), BoundingBox()) for obs in observations]


def circle(obs, *, direction=1, radius=5000, missing_track=False):
    for i in range(13):
        lat, lon = project_position(47, 19, direction * i * 30, radius)
        track = (direction * i * 30 + direction * 90) % 360
        yield at(
            obs,
            100 + i * 15,
            latitude=lat,
            longitude=lon,
            true_track=None if missing_track and i == 5 else track,
        )


@pytest.mark.parametrize("airport", AIRPORTS)
def test_airport_context_uses_configured_reference_points(airport):
    context = spatial_context(airport.latitude, airport.longitude, BoundingBox())
    assert context["nearest_configured_airport"] == airport.icao
    assert context["airport_distance_m"] == 0


def test_boundary_and_constant_track_projection():
    bbox = BoundingBox()
    assert boundary_distance_m(47, 19, bbox) > 100000
    assert boundary_distance_m(47, bbox.lomax, bbox) == 0
    assert boundary_distance_m(47, 23, bbox) == 0
    lat, lon = project_position(0, 0, 0, 111195.08)
    assert lat == pytest.approx(1, abs=1e-5) and lon == pytest.approx(0)


@pytest.mark.parametrize("direction", [1, -1])
def test_holding_circle_is_detected_with_measurable_evidence(observation, direction):
    result = evaluate(circle(observation, direction=direction))[-1]
    assert [alert.alert_type for alert in result] == ["holding_pattern"]
    alert = result[0]
    assert alert.evidence["unwrapped_turn_deg"] == direction * 360
    assert alert.severity == "info" and "radius" in alert.physical_evidence
    json.dumps(alert.evidence, allow_nan=False)


def test_zigzag_absolute_turn_is_not_holding(observation):
    points = [
        at(
            observation,
            100 + i * 15,
            true_track=0 if i % 2 == 0 else 90,
            latitude=47,
            longitude=19 + i * 0.001,
        )
        for i in range(13)
    ]
    assert all(not alerts for alerts in evaluate(points))


@pytest.mark.parametrize("kwargs", [{"radius": 20000}, {"missing_track": True}])
def test_nonlocalized_or_incomplete_holding_evidence_does_not_alert(observation, kwargs):
    assert all(not alerts for alerts in evaluate(circle(observation, **kwargs)))


def test_holding_needs_sufficient_time_coverage(observation):
    assert all(not alerts for alerts in evaluate(list(circle(observation))[:10]))


def test_persistent_rapid_descent_alerts_at_confirmation_boundary(observation):
    results = evaluate(
        [at(observation, 100, vertical_rate=-15), at(observation, 115, vertical_rate=-15)]
    )
    assert not results[0]
    assert results[1][0].alert_type == "unusual_descent"
    assert results[1][0].evidence["confirmed_duration_seconds"] == 15


def test_single_moderate_descent_sample_does_not_alert(observation):
    assert all(
        not alerts
        for alerts in evaluate(
            [
                at(observation, 100, vertical_rate=-15),
                at(observation, 115, vertical_rate=-2),
            ]
        )
    )


def test_normal_three_degree_airport_approach_is_not_anomaly(observation):
    rate = 75 * math.tan(math.radians(-3))
    airport = AIRPORTS[0]
    points = []
    for i in range(13):
        lat, lon = project_position(airport.latitude, airport.longitude, 270, 15000 - 75 * 15 * i)
        points.append(
            at(
                observation,
                100 + i * 15,
                velocity=75,
                vertical_rate=rate,
                baro_altitude=1000 + rate * 15 * i,
                latitude=lat,
                longitude=lon,
                true_track=90,
            )
        )
    assert all(not alerts for alerts in evaluate(points))


def test_airport_proximity_does_not_hide_extreme_descent(observation):
    airport = AIRPORTS[0]
    result = evaluate(
        [
            replace(
                observation,
                latitude=airport.latitude,
                longitude=airport.longitude,
                vertical_rate=-30,
            )
        ]
    )[0]
    assert result[0].severity == "critical"
    assert result[0].evidence["airport_distance_m"] == 0


def test_steep_gradient_can_trigger_below_absolute_rate_threshold(observation):
    rate = 80 * math.tan(math.radians(-6.1))
    results = evaluate([at(observation, t, velocity=80, vertical_rate=rate) for t in [100, 115]])
    assert results[-1][0].evidence["triggers"] == ["steep_ground_path"]


def test_low_speed_gradient_and_missing_rate_do_not_fake_descent(observation):
    points = [
        at(observation, 100, velocity=1, vertical_rate=-2),
        at(observation, 115, velocity=1, vertical_rate=-2),
        at(observation, 130, vertical_rate=None),
    ]
    assert all(not alerts for alerts in evaluate(points))


def test_abrupt_vertical_change_uses_two_real_samples(observation):
    results = evaluate(
        [at(observation, 100, vertical_rate=0), at(observation, 105, vertical_rate=-12)]
    )
    assert not results[0]
    assert "rapid_vertical_speed_change" in results[1][0].evidence["triggers"]


def test_descent_confirmation_does_not_bridge_long_gaps(observation):
    results = evaluate([at(observation, t, vertical_rate=-15) for t in [100, 145, 300]])
    assert all(not alerts for alerts in results)


@pytest.mark.parametrize("code", ["7500", "7600", "7700"])
def test_emergency_squawk_is_a_separate_alert_type(code):
    alert = squawk_candidate(
        code, run_id="run1", icao24="abc123", source_attempt_id=1, api_time=100, last_contact=100
    )
    assert alert.alert_type == "emergency_squawk"
    assert alert.evidence["squawk"] == code
    assert "descent" in alert.limitations[0]


@pytest.mark.parametrize("code", [None, "7000", 7700, "7700 "])
def test_non_emergency_or_invalid_codes_do_not_alert(code):
    assert (
        squawk_candidate(
            code,
            run_id="run1",
            icao24="abc123",
            source_attempt_id=1,
            api_time=100,
            last_contact=100,
        )
        is None
    )


def candidate(icao24="abc123", kind="emergency_squawk", severity="critical"):
    return replace(
        squawk_candidate(
            "7700",
            run_id="run1",
            icao24=icao24,
            source_attempt_id=1,
            api_time=100,
            last_contact=100,
        ),
        alert_type=kind,
        severity=severity,
    )


def test_alert_identity_is_stable_and_old_events_are_not_mutated():
    tracker = AlertTracker()
    first = tracker.reconcile([candidate()], 100, {"abc123"})[0]
    second = tracker.reconcile([candidate()], 115, {"abc123"})[0]
    assert first["event"] == "opened" and second["event"] == "updated"
    assert first["alert_id"] == second["alert_id"]
    assert first["last_seen"] == 100 and len(tracker.active) == 1
    assert tracker.opened_by_type["emergency_squawk"] == 1


def test_provider_uncertainty_closes_alert_without_claiming_normality():
    tracker = AlertTracker()
    tracker.reconcile([candidate()], 100, {"abc123"})
    event = tracker.close_all(None, "provider_poll_failed")[0]
    assert event["event_time"] is None and event["close_reason"] == "provider_poll_failed"


def test_reacquisition_has_explicit_close_reason():
    tracker = AlertTracker()
    tracker.reconcile([candidate(kind="signal_loss")], 100, set())
    assert tracker.reconcile([], 115, {"abc123"})[0]["close_reason"] == "contact_reacquired"


def test_active_panel_is_capped_and_prioritizes_severity():
    tracker = AlertTracker()
    values = [candidate(f"abc{i:03x}", severity="info") for i in range(6)]
    values.append(candidate("def456", severity="critical"))
    tracker.reconcile(values, 100, set())
    top = tracker.top_active()
    assert len(top) == 5 and top[0]["icao24"] == "def456"
    assert len(tracker.active) == 7


@pytest.mark.parametrize(
    "settings",
    [
        {"loss_gap_seconds": 0},
        {"mass_loss_fraction": 1.1},
        {"holding_max_straightness": float("nan")},
        {"severe_descent_rate_mps": 10},
        {"loss_gap_seconds": 200},
        {"mass_loss_min_population": 2.5},
    ],
)
def test_invalid_rule_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        RuleConfig(**settings)
