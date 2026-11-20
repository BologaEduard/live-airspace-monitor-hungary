import json
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
CRED_PATH = BASE_DIR / "credentials.json"
OUT_PATH = BASE_DIR / "sample_hungary_states.json"

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"

# Bounding box covering Hungary
BBOX_HUNGARY = {
    "lamin": 45.7,
    "lomin": 16.1,
    "lamax": 48.6,
    "lomax": 22.9,
}


def get_access_token() -> str:
    """Authenticate via OAuth2 client credentials and return a bearer token."""
    creds = json.loads(CRED_PATH.read_text(encoding="utf-8"))
    client_id = creds.get("clientId") or creds.get("client_id")
    client_secret = creds.get("clientSecret") or creds.get("client_secret")

    if not client_id or not client_secret:
        raise ValueError("Missing clientId or clientSecret in credentials.json")

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> None:
    """Fetch live state vectors over Hungary and save a sample snapshot."""
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(STATES_URL, params=BBOX_HUNGARY, headers=headers, timeout=15)
    response.raise_for_status()

    data = response.json()
    states = data.get("states") or []
    remaining_credits = response.headers.get("X-Rate-Limit-Remaining", "unknown")
    timestamp_utc = datetime.fromtimestamp(data["time"], tz=timezone.utc)

    print(f"Authentication successful! Timestamp (UTC): {timestamp_utc}")
    print(f"Aircraft detected over Hungary: {len(states)}")
    print(f"Remaining API credits (X-Rate-Limit-Remaining): {remaining_credits}\n")

    for state in states[:5]:
        callsign = (state[1] or "N/A").strip()
        origin_country = state[2]
        longitude, latitude, baro_altitude = state[5], state[6], state[7]
        velocity, vertical_rate = state[9], state[11]
        print(
            f"- {callsign:<8} ({origin_country}) | pos: ({latitude}, {longitude}) | "
            f"alt: {baro_altitude} m | speed: {velocity} m/s | v_rate: {vertical_rate} m/s"
        )

    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSample snapshot saved to: {OUT_PATH.name}")


if __name__ == "__main__":
    main()
