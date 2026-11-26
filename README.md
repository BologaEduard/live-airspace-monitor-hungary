# Live Airspace Monitor for Hungary

BME MSc – AI in Practice (2026) Homework Assignment #1.

## Data Access Checkpoint
- **Data Source:** OpenSky Network REST API (`/api/states/all`)
- **Verification Script:** `check_opensky.py` (OAuth2 client credentials flow, Hungary bounding box)
- **Sample Output:** `sample_hungary_states.json`

## Current status

Implemented: an OAuth2 OpenSky client, bounded data collection, append-only SQLite
recordings, causal telemetry auditing, derived JSONL exports, and offline tests.
The existing access-check script is also available.
Trajectory segmentation, anomaly detection, ML evaluation, and the web application are planned;
they are not implemented yet. See [SPEC.md](SPEC.md) for the specification.

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

The Python package currently contains `config`, `opensky_client`, `collector`,
`storage`, `recordings`, `exports`, `preprocess`, and `cli`. Planned modules: `features`, `rules`,
`anomaly_detector`, `benchmark`, `evaluate`, and `app`.

## Local setup (PowerShell)

Requires Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m airspace_monitor --help
.\.venv\Scripts\python.exe -m airspace_monitor
```

With no subcommand, the entry point displays help and makes no network requests.
An installed console entry point, `airspace-monitor`, is also available inside the environment.

## Collect airspace data

Commands below contact OpenSky and consume API credits. Run from the repository root;
relative credentials and database paths are resolved against the current directory.

First, record a single poll using the existing local credential file:

```powershell
.\.venv\Scripts\python.exe -m airspace_monitor collect --credentials credentials.json --max-polls 1
```

Record three hours at 15-second intervals (approximately 720 successful state requests,
excluding retries; actual duration and count depend on request latency and errors):

```powershell
.\.venv\Scripts\python.exe -m airspace_monitor collect --credentials credentials.json --interval-seconds 15 --duration-seconds 10800
```

Defaults are 15-second polling, a one-hour collection window, a 15-second HTTP timeout,
and `data/raw/opensky.sqlite3`. Use `--db data/raw/evening.sqlite3` for another file.
The configured Hungary bounding box is `45.7, 16.1, 48.6, 22.9` (south, west, north, east).
Keep one collector running per account; multiple processes do not coordinate API credits.

Alternatively, set **both** `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` in the
process environment. They take precedence over `--credentials`. A partial or empty
environment pair is an error, even when a valid file is supplied. No `.env` file is
loaded automatically. Credential files accept `clientId`/`clientSecret` or
`client_id`/`client_secret`. The collector never prints either value.

### Scheduling and failures

- Tokens are cached and refreshed shortly before expiry. A states `401` is recorded;
  the next scheduled poll obtains a new token.
- Network errors, malformed responses, `408`, `429`, and server errors are recorded
  and retried with exponential backoff. A server's `Retry-After` or
  `X-Rate-Limit-Retry-After-Seconds` is respected even above the local 300-second cap.
- Other HTTP errors stop collection. Eight consecutive retryable failures also stop it.
- A reported zero-credit balance stops collection after saving the current result.
- `--max-polls` counts collection attempts, including failures, not individual HTTP calls.
  A poll can include an OAuth request followed by a states request.
- No new poll starts outside the collection window. A pending request can finish after
  the deadline (up to one timeout per HTTP operation); this is not a hard cancellation.
  If the next permitted poll would fall outside the window, collection returns early
  with `next_poll_after_deadline` rather than waiting unnecessarily.
- Ctrl+C closes resources; already committed results remain available. Interrupting an
  in-flight poll may leave that last unfinished poll unrecorded.
- Exit codes: `0` for a bounded run with at least one successful snapshot, `1` for a
  fatal error/failure limit or no successful snapshots, `2` for invalid arguments or
  credentials configuration, and `130` for interruption.

### Recording format

`collection_attempts` has one append-only row per completed poll, with:

| Field | Meaning |
| --- | --- |
| `run_id`, `bbox_json` | Collection session and geographic scope |
| `requested_at`, `completed_at` | UTC poll timestamps; poll start includes authentication |
| `phase`, `outcome`, `http_status` | Authentication/states failure or successful states response |
| `raw_body` | Original decoded states-response text, including invalid/error responses |
| `api_time`, `vector_count` | Valid response-envelope timestamp and row count |
| `remaining_credits`, `retry_after_seconds` | Valid quota and waiting information, when provided |

OAuth response bodies, request headers, tokens, and credentials are **never stored**.
A successful OAuth exchange is not a separate recording row; an unsuccessful exchange
produces an authentication-failure row without a states request. Raw telemetry nulls,
duplicate API timestamps, and empty snapshots are preserved. A failed request has no
successful snapshot metadata; it must not be interpreted as empty airspace. This layer
validates only the response envelope; the separate audit command checks telemetry.

Each row is committed immediately. Reusing the database appends another run without
overwriting earlier recordings. The SQLite database uses schema version 1.

API behavior reference: [OpenSky REST API documentation](https://openskynetwork.github.io/opensky-api/rest.html).

The existing live access check is a separate, optional operation. It requires a local,
Git-ignored `credentials.json` containing `clientId` and `clientSecret`, consumes API
credits, and overwrites `sample_hungary_states.json`:

```powershell
.\.venv\Scripts\python.exe check_opensky.py
```

Never put credentials in source code, browser assets, screenshots, or logs.

## Audit recordings (offline)

```powershell
.\.venv\Scripts\python.exe -m airspace_monitor audit --db data/raw/opensky.sqlite3
```

Use the actual recording filename for a separately named session. The command needs
no credentials and makes no network requests. Defaults: `--max-age-seconds 30` and
`--output-dir data/processed`. It creates:

- `<recording>.audit.json`: poll outcomes, disjoint tracking dispositions, missing-field
  counts, raw numeric min/max ranges, analysis eligibility, and source provenance.
- `<recording>.observations.jsonl`: fresh, unique, airborne position observations with
  named fields in recording order. Null telemetry stays null; no values are imputed.
- `<recording>.exclusions.jsonl`: reasons and source attempt/vector indices for rejected
  observations, incomplete analysis inputs, and unsuccessful/invalid source polls.

The audit rejects malformed vectors (fewer than 17 fields), invalid IDs/types/ranges,
missing positions/contact times, nonfinite telemetry, future or inconsistent timestamps,
and positions older than the age limit. Ground records are counted separately. A duplicate
position timestamp is not a new movement measurement, even if contact time changed;
older positions arriving later are excluded rather than reordered. Deduplication state
is independent for each `(run_id, icao24)` pair.

Fresh positions with missing barometric altitude, speed, track, or vertical rate are
retained for tracking and counted as `analysis_quarantined`; records complete in those
four fields count as `analysis_eligible`. Eligibility here means basic data availability,
not that a trajectory window is long enough or physically verified. Missing optional
squawk/geometric altitude does not by itself quarantine the analysis input.

Counts reconcile as follows:

```text
raw_vectors = accepted_airborne + all excluded_* counts
accepted_airborne = analysis_eligible + analysis_quarantined
```

Missing-field and reason counts can overlap; numeric ranges describe finite values in
all structurally complete raw vectors, including ground and subsequently excluded rows.
There is no interpolation or aircraft-disappearance inference. Later continuity detection
must use raw poll/contact information as well: absence from cleaned positions can be an
audit exclusion, not signal loss.

The database opens read-only. Its maximum attempt ID is captured at start, so collection
can continue while the audit processes a bounded prefix in short read batches. The report
records that ID. Run the audit again after collection ends for the complete session.
Derived exports are replaced atomically per file on success; this is not a transaction
across all export files. Use a different directory from the raw database.

## Development checks

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Tests use synthetic responses and temporary SQLite databases. An automatic fixture blocks
Requests network access, so missed mocks fail instead of spending live OpenSky credits.
The suite covers credentials precedence, token reuse/refresh, rate limits, malformed
responses, backoff, quota exhaustion, interruption, and append-only persistence.
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
