# Live Airspace Monitor for Hungary

BME MSc – AI in Practice (2026) Homework Assignment #1.

## Data Access Checkpoint
- **Data Source:** OpenSky Network REST API (`/api/states/all`)
- **Verification Script:** `check_opensky.py` (OAuth2 client credentials flow, Hungary bounding box)
- **Sample Output:** `sample_hungary_states.json`

## Current status

The repository contains a working standalone API access-check script and a Python
application scaffold. The collector, detector, evaluation pipeline, and web application
are planned; they are not implemented yet. See [SPEC.md](SPEC.md) for the specification.

## Folder structure

```text
src/airspace_monitor/   Python application package and CLI
tests/                 Automated tests and small synthetic fixtures
web/                   Future map, replay controls, and alert inspector
data/raw/              Local original recordings (ignored by Git)
data/processed/        Local cleaned trajectories and features (ignored by Git)
data/demo/             Deliberately selected replay datasets (currently empty)
artifacts/models/      Generated models and metadata (ignored by Git)
artifacts/evaluation/  Generated metrics and reports (ignored by Git)
docs/                  Development log and future technical documentation
check_opensky.py       Existing standalone live access check
sample_hungary_states.json  Existing single-snapshot sample, not a replay dataset
```

Modules will be added to the Python package as their behavior is implemented:
`opensky_client`, `collector`, `storage`, `preprocess`, `features`, `rules`,
`anomaly_detector`, `benchmark`, `evaluate`, and `app`.

## Local setup (PowerShell)

Requires Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m airspace_monitor --help
.\.venv\Scripts\python.exe -m airspace_monitor
```

The current entry point prints scaffold status; it does not collect data or start a server.
An installed console entry point, `airspace-monitor`, is also available inside the environment.

The existing live access check is a separate, optional operation. It requires a local,
Git-ignored `credentials.json` containing `clientId` and `clientSecret`, consumes API
credits, and overwrites `sample_hungary_states.json`:

```powershell
.\.venv\Scripts\python.exe check_opensky.py
```

Never put credentials in source code, browser assets, screenshots, or logs.

## Development checks

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

No tests exist yet; until tests are added, pytest reports no tests collected (exit code 5).
Automated tests will use synthetic fixtures rather than live OpenSky calls.
See [AGENTS.md](AGENTS.md) for development conventions and
[the development log](docs/DEVELOPMENT_LOG.md) for AI-assisted work.

## Implementation order

1. Extract a reusable OpenSky client; implement collection and raw storage.
2. Audit telemetry and build causal trajectory segments and features.
3. Add deterministic rules, synthetic edge cases, and tests.
4. Train Isolation Forest and evaluate it on held-out source trajectories.
5. Build replay, the map and evidence-backed alerts; then connect live data.
6. Deploy, document results, and prepare the demonstration.

## Deployment plan

The proposed hosting target is a Docker-based Hugging Face Space. The owner has
`bologaeduard.app` registered through Name.com; a future subdomain may point to
the deployed application. The hostname, host support for custom domains, DNS records,
and HTTPS configuration will be verified during deployment. No domain or DNS changes
have been made. The application must also work at the hosting provider's own URL.
