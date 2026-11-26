"""Spherical surface geometry in metres; altitude is handled separately."""

import math
from collections.abc import Sequence

from airspace_monitor.preprocess import valid_numeric

# IUGG mean radius rounded to 0.1 m. This is a spherical approximation, not WGS84 geodesy.
EARTH_RADIUS_M = 6_371_008.8


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    for name, value in (
        ("latitude", lat1),
        ("longitude", lon1),
        ("latitude", lat2),
        ("longitude", lon2),
    ):
        if not valid_numeric(name, value):
            raise ValueError("Invalid coordinates for surface distance.")
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def spherical_center(positions: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """Avoid longitude averaging across the dateline; antipodal centres are undefined."""
    if not positions:
        return None
    xyz = [
        (
            math.cos(math.radians(lat)) * math.cos(math.radians(lon)),
            math.cos(math.radians(lat)) * math.sin(math.radians(lon)),
            math.sin(math.radians(lat)),
        )
        for lat, lon in positions
    ]
    x, y, z = (math.fsum(point[i] for point in xyz) / len(xyz) for i in range(3))
    if math.sqrt(x * x + y * y + z * z) < 1e-12:
        return None
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))
