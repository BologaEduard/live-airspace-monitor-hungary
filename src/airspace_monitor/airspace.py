"""Approximate observation-boundary and airport context, not a radar coverage model."""

import math
from dataclasses import dataclass

from airspace_monitor.config import BoundingBox
from airspace_monitor.geo import EARTH_RADIUS_M, haversine_distance_m


@dataclass(frozen=True)
class Airport:
    icao: str
    latitude: float
    longitude: float


# Selected reference points checked on 2026-11-26 against the primary OurAirports CSV:
# https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv
# These are airport reference locations, not runway thresholds or approach corridors.
AIRPORTS = (
    Airport("LHBP", 47.43018, 19.262393),
    Airport("LHDC", 47.489469, 21.616278),
    Airport("LHSM", 46.686391, 17.159084),
)


def boundary_distance_m(latitude: float, longitude: float, bbox: BoundingBox) -> float:
    if not (bbox.lamin <= latitude <= bbox.lamax and bbox.lomin <= longitude <= bbox.lomax):
        return 0.0
    return min(
        haversine_distance_m(latitude, longitude, bbox.lamin, longitude),
        haversine_distance_m(latitude, longitude, bbox.lamax, longitude),
        haversine_distance_m(latitude, longitude, latitude, bbox.lomin),
        haversine_distance_m(latitude, longitude, latitude, bbox.lomax),
    )


def project_position(
    latitude: float,
    longitude: float,
    track_deg: float,
    distance_m: float,
) -> tuple[float, float]:
    """Constant-track spherical projection; a screening assumption, not a flight prediction."""
    phi, lam, theta = map(math.radians, (latitude, longitude, track_deg))
    angle = distance_m / EARTH_RADIUS_M
    sin_phi2 = math.sin(phi) * math.cos(angle) + math.cos(phi) * math.sin(angle) * math.cos(theta)
    phi2 = math.asin(min(1.0, max(-1.0, sin_phi2)))
    lam2 = lam + math.atan2(
        math.sin(theta) * math.sin(angle) * math.cos(phi),
        math.cos(angle) - math.sin(phi) * math.sin(phi2),
    )
    return math.degrees(phi2), (math.degrees(lam2) + 180) % 360 - 180


def spatial_context(latitude: float, longitude: float, bbox: BoundingBox) -> dict:
    nearest = min(
        AIRPORTS,
        key=lambda airport: haversine_distance_m(
            latitude,
            longitude,
            airport.latitude,
            airport.longitude,
        ),
    )
    return {
        "nearest_configured_airport": nearest.icao,
        "airport_distance_m": haversine_distance_m(
            latitude,
            longitude,
            nearest.latitude,
            nearest.longitude,
        ),
        "observation_boundary_distance_m": boundary_distance_m(latitude, longitude, bbox),
    }
