"""Collector configuration and credentials, without implicit dotenv loading."""

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"


@dataclass(frozen=True)
class BoundingBox:
    lamin: float = 45.7
    lomin: float = 16.1
    lamax: float = 48.6
    lomax: float = 22.9

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in asdict(self).values()):
            raise ValueError("Bounding box coordinates must be finite.")
        if not (-90 <= self.lamin < self.lamax <= 90):
            raise ValueError("Invalid latitude bounds.")
        if not (-180 <= self.lomin < self.lomax <= 180):
            raise ValueError("Invalid longitude bounds.")

    def as_params(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class Credentials:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.client_id, self.client_secret)
        ):
            raise ValueError("OpenSky client ID and secret must be nonempty strings.")


def load_credentials(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> Credentials:
    """Prefer a complete environment pair; partial configuration is an error."""
    env = os.environ if environ is None else environ
    names = ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET")
    if any(name in env for name in names):
        return Credentials(env.get(names[0], ""), env.get(names[1], ""))
    if path is None:
        raise ValueError("Set OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET or use --credentials.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("Cannot read the credentials JSON file.") from None
    if not isinstance(data, dict):
        raise ValueError("Credentials JSON must be an object.")
    return Credentials(
        data.get("clientId") or data.get("client_id"),
        data.get("clientSecret") or data.get("client_secret"),
    )
