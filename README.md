# Live Airspace Monitor for Hungary

BME MSc – AI in Practice (2026) Homework Assignment #1.

## Data Access Checkpoint
- **Data Source:** OpenSky Network REST API (`/api/states/all`)
- **Verification Script:** `check_opensky.py` (OAuth2 client credentials flow, Hungary bounding box)
- **Sample Output:** `sample_hungary_states.json`

## Current status

Implemented: an OAuth2 OpenSky client, bounded data collection, append-only SQLite
recordings, causal telemetry auditing, incremental trajectory segmentation,
sliding-window kinematic features, rule-based recording analysis, evidence-backed
alert lifecycles, derived JSONL exports, an initial local map/replay interface,
and offline tests.
The existing access-check script is also available.
ML training/evaluation, full-session replay, and a public deployment are planned.
The current website is a local foundation, not the complete specified application.
See [SPEC.md](SPEC.md) for the specification.

## Folder structure

```text
src/airspace_monitor/   Python application package and CLI
tests/                 Automated tests and small synthetic fixtures
web/                   Local map, recent replay controls, and evidence inspector
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
`storage`, `recordings`, `exports`, `preprocess`, `trajectories`, `geo`, `features`,
`airspace`, `rules`, `alerts`, `continuity`, `detector`, `preview`, `app`, and `cli`.
Planned modules:
`anomaly_detector`, `benchmark`, and `evaluate`.

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

## Local website preview

The English **Night atlas** interface reads existing SQLite recordings. It includes
an offline regional map, aircraft search and selection, telemetry, recent-frame
playback at 1×/5×/20×, and available historical rule candidates with evidence.
It makes no OpenSky requests and can run alongside the independent collector.

Requires Node.js 22.12+ (or a compatible Vite-supported version) and Python 3.11+.
Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,web]"
npm.cmd --prefix web ci
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe -m airspace_monitor serve
```

Open **http://127.0.0.1:8000/**. The server binds only to loopback. `--port 8001`
selects another local port. Ctrl+C stops the server; it does not stop collection.
Without `--db`, the newest `data/raw/*.sqlite3` file is chosen at startup. To pin it:

```powershell
.\.venv\Scripts\python.exe -m airspace_monitor serve --db data/raw/my-recording.sqlite3
```

No recording produces an explicit empty state. The initial API returns at most
48 recent successful polls from the newest successful run, about 12 minutes at
15-second intervals. Scrubbing freezes this window; **Latest frame** resumes
15-second refreshes. Trails and candidate visibility never use frames later than
the selected recording time. Full-session replay and live inference are future work.

The API keeps UTC timestamps and SI telemetry; the browser displays ground speed
in km/h. Missing telemetry is **Unavailable**, stale positions are flagged, and source
interruption is separate from an individual contact gap. A recent recording can keep
updating, but the UI never claims that saved observations are verified live traffic.

Historical candidate evidence is loaded from matching `data/processed/<stem>.detection.json`
and `<stem>.alerts.jsonl` exports when available; run the existing `detect` command to
produce them. These are heuristic screening candidates, not verified incidents or
ML results. Their analysis timestamp can precede the most recent recording frame.

Only `web/dist/` is served publicly to the local browser. Credentials, raw databases,
and the repository root are not static mounts. Fonts and selected Natural Earth
geography are bundled locally; see [asset provenance](web/ASSETS.md).
No DNS or deployment is configured. Design context is in [PRODUCT.md](PRODUCT.md),
[DESIGN.md](DESIGN.md), and [.impeccable/surfaces/web.md](.impeccable/surfaces/web.md).

For frontend development, leave the Python server running and use
`npm.cmd --prefix web run dev`; Vite proxies `/api` to port 8000.
After a build, run `npm.cmd --prefix web run test:ui` against the running local server
for synthetic, offline browser checks. Microsoft Edge is the default test browser;
set `PLAYWRIGHT_CHANNEL=chrome` for an installed Chrome, or configure your Playwright
browser. These tests mock telemetry and do not spend API credits.

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

## Build trajectory segments (offline)

After auditing the chosen recording:

```powershell
.\.venv\Scripts\python.exe -m airspace_monitor segment --observations data/processed/opensky.observations.jsonl
```

Defaults: `--max-gap-seconds 120` and `--output-dir data/processed`. The command creates:

- `<recording>.trajectories.jsonl`: one tagged observation per line, with a deterministic
  segment ID, segment number, start reason, zero-based point index, and analysis eligibility.
- `<recording>.segments.json`: point/exclusion counts and each segment's start/end
  position timestamps, point count, and analysis-eligible point count.

`TrajectoryBuilder.add()` maintains independent state per `(run_id, icao24)`. The first
point starts a segment; a position-time gap **greater than** 120 seconds starts another.
A gap of exactly 120 seconds stays in the same segment. Duplicate and older points are
counted and skipped without moving state backwards. Separate collection runs never join.

Processing is incremental and follows arrival/recording order; it does not sort the entire
flight using future observations. This same builder can therefore be used in live mode
and replay. Prefixes produce identical point assignments. No interpolation, flight-phase
inference, feature engineering, or anomaly detection occurs yet. A segment may contain
only one point and is not necessarily an entire flight. Missing telemetry remains null,
and an analysis-eligible point does not imply a complete analysis window.

Malformed observation JSONL stops the export with a nonzero exit; existing complete
trajectory files remain unchanged. Source observations are never overwritten. After a
long recording finishes, rerun **audit then segment** to include all completed polls.

## Compute kinematic features (offline)

```powershell
.\.venv\Scripts\python.exe -m airspace_monitor features --observations data/processed/opensky.observations.jsonl
```

The command consumes audited observations directly, reusing `TrajectoryBuilder` internally
to obtain the same segment IDs; a separate trajectory export is not required. Outputs:

- `<recording>.features.jsonl`: one causal feature record per accepted observation,
  including source provenance, window duration, point count, metrics, and quality flags.
- `<recording>.features.json`: configuration, fixed ML feature order, readiness/quality
  counts, and the API-time range and maximum attempt ID represented by source observations.

Each aircraft/run has a trailing, position-time window. Defaults are 300 seconds,
minimum 180 seconds of actual coverage, minimum 8 points, and no adjacent sample interval
over 45 seconds. CLI options are `--window-seconds`, `--min-duration-seconds`, `--min-points`,
`--max-sample-gap-seconds`, and `--max-gap-seconds` (segment reset; default 120).
The left window boundary is inclusive. A new segment clears its history.

| Metric | Definition / units |
| --- | --- |
| `velocity_mps`, `vertical_rate_mps`, `baro_altitude_m` | Latest observed values, including nulls |
| `path_length_m` | Sum of successive spherical ground distances |
| `net_displacement_m` | Ground distance between first and last window positions |
| `tortuosity` | Path length / net displacement; null below 1 m net displacement |
| `straightness` | Net displacement / path length; null for zero path length |
| `bounding_radius_m` | Maximum distance to the spherical mean of the window positions |
| `unwrapped_turn_deg` | Sum of shortest signed track changes; clockwise positive |
| `cumulative_abs_turn_deg` | Sum of absolute track changes; distinct from net turn |
| `abs_turn_rate_deg_s`, `net_turn_rate_deg_s` | Corresponding total angle / actual window duration |
| `last_turn_rate_deg_s` | Last adjacent pair's signed change / elapsed time |
| `descent_gradient_deg` | `atan2(vertical_rate, horizontal_speed)` in degrees; negative for descent |
| `vertical_acceleration_mps2` | Last adjacent pair's vertical-speed difference / elapsed time |
| `altitude_change_m`, `altitude_change_rate_mps` | Endpoint barometric-altitude difference and average rate |
| `last_contact_gap_s`, `position_age_s` | Age relative to the latest source API time, not current wall time |

Distances use a sphere of radius 6,371,008.8 m and ignore altitude; they approximate
ellipsoidal ground distance. See the [haversine definition](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.haversine_distances.html)
and [mean-radius convention](https://geopy.readthedocs.io/en/stable/#calculating-distance).
The gradient is a ground-relative path estimate, not aircraft pitch or proof of ILS
alignment. Derivatives use position-time intervals as sample-time estimates; individual
telemetry fields have no independent timestamps in these recordings.

North-crossing track changes are unwrapped (`359 -> 2` is `+3` degrees). Shortest-turn
unwrapping assumes sampling resolves the turn; an exact 180-degree pair is ambiguous
and gets a flag instead of an arbitrary direction. Missing track anywhere in the window
makes whole-window turn totals unavailable; it is never bridged by skipping that point.
Single-point windows have null turn/acceleration metrics. Zero horizontal speed makes
the path gradient unavailable. Near-closed loops retain turn and straightness evidence
while tortuosity remains null; no denominator clamp or artificial infinity is substituted.

`window_ready` means coverage, point count, and sample spacing meet the configured
requirements. `ml_eligible` additionally requires complete telemetry throughout the window
and a finite, defined five-feature vector in this fixed order:

```text
velocity_mps, vertical_rate_mps, abs_turn_rate_deg_s, tortuosity, baro_altitude_m
```

`ml_vector` is null when ineligible. Individual metrics and quality flags are still
exported during warmup or partial data. This is an input-availability check, not an
anomaly score, a physical plausibility guarantee, or a trained model. Airport/runway
context and distance to coverage boundaries will be added with the detection rules.
Source poll/contact information is still needed to evaluate disappearance; feature
records alone must not be interpreted as a live connection heartbeat.

The same `FeatureExtractor.add()` handles incremental live observations and replay
prefixes without future data. Exports are repeatable and protect existing complete files
on malformed input. After collection ends, rerun **audit then features** for all available
points; run `segment` as well if a separate trajectory export is needed.

## Screen recorded airspace with deterministic rules

```powershell
.\.venv\Scripts\python.exe -m airspace_monitor detect --db data/raw/opensky.sqlite3
```

This offline command reads raw polls directly. It needs no credentials, makes no network
requests, and reuses the telemetry audit and feature extractor internally. Raw poll
presence/contact and provider failures are essential for continuity; a cleaned-position
or feature file alone is insufficient. The collector currently records data only;
continuous live inference, notifications, and a web inspector are not implemented yet.

Outputs under `data/processed` (or `--output-dir`):

- `<recording>.alerts.jsonl`: opened/updated/closed events with stable alert IDs,
  severity, ICAO24, source attempt/API time, numeric evidence, readable physical evidence,
  and explicit limitations. Event/first-seen/last-seen times are Unix UTC seconds based
  on collection completion. An unknown event time remains null.
- `<recording>.source-events.jsonl`: provider, timing, scope, and source-health uncertainty
  with source attempt, HTTP status, and outcome. Cached nonadvancing snapshots are
  diagnostic events, not new measurements or automatically provider failures.
- `<recording>.detection.json`: complete rule/window configuration, audit diagnostics,
  source-prefix ID, source-health and lifecycle counts, opened counts by type, continuity
  abstention reasons, total active count, and up to five severity-ranked active alerts.

### Initial screening thresholds

`RuleConfig` records all thresholds in the report. These are initial engineering
heuristics to be calibrated on training/validation data. A threshold crossing is not
a verified abnormal flight, emergency, or calibrated probability. Planned fast descents
can exceed the rate threshold; precision and recall have not been established yet.

| Alert type | Required evidence |
| --- | --- |
| `holding_pattern` (info) | Ready window; absolute **signed net turn** at least 360 deg; signed/absolute turn coherence at least 0.8; sample-centred radius and net progress each at most 10 km; straightness at most 0.35; latest speed at least 50 m/s |
| `unusual_descent` (warning) | Rate at most -15 m/s **or** ground-path angle at most -6 deg with rate at most -8 m/s and speed at least 50 m/s; qualifying samples span at least 15 s with no adjacent confirmation gap over 30 s |
| `unusual_descent` (immediate) | Rate at most -30 m/s (critical), or estimated vertical acceleration at most -1.5 m/s² with current rate at most -12 m/s and no sparse-window flag (warning) |
| `emergency_squawk` (critical) | Fresh airborne contact reporting exactly `7500`, `7600`, or `7700`; this is a separate code observation, not evidence of descent |
| `signal_loss` (warning) | Contact gap at least 60 s, known airborne position no older than 180 s, last barometric altitude above 1500 m, known speed/track, source witnesses, and passing boundary/airport guards |

Holding-like motion can be an ordinary ATC procedure. The tested normal 75 m/s,
three-degree approach-like descent stays below these screening thresholds; airport
proximity does not blanket-suppress extreme descent. Airport locations are reference
points from the [OurAirports primary dataset](https://github.com/davidmegginson/ourairports-data),
checked on 2026-11-26: LHBP `(47.43018, 19.262393)`, LHDC `(47.489469, 21.616278)`,
and LHSM `(46.686391, 17.159084)`. No runway alignment or ILS procedure is inferred.
Emergency-code descriptions follow [EASA SERA documentation](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-standardised-european?erules-id=ERULES-1963177438-9921).
An observed code is not independent confirmation of the corresponding emergency.

### Continuity and source-health guards

- The source must have fresh airborne contacts. Ground-only, empty, all-stale, failed,
  or malformed responses cannot justify individual disappearance alerts.
- API time must not be ahead of collection completion or more than 30 s behind it.
  Repeated API time does not advance inference; regressed API/capture time is uncertainty.
- A source-poll interval over 45 s, or disappearance of at least half the previous fresh
  airborne population when that population had at least five members, clears old loss
  baselines. Recovery rearms only aircraft actually observed after that uncertainty.
- Runs have independent contact baselines. A changed geographic scope inside the same
  run is rejected as uncertainty; start a new collection run for a new scope.
- Contact updates still count when position is duplicate, stale, or missing. Explicit
  ground observations remove airborne loss eligibility and reset descent confirmation.
- Last and constant-track projected positions must both remain at least 10 km inside
  the **observation bounding box**. This is not Hungary's national border or a verified
  coverage polygon. Implausibly long projections also abstain as possible exits.
- At barometric altitude up to 3000 m, a last/projected position within 15 km of one of
  the configured airports suppresses loss screening as a possible arrival. Higher
  overflights are not automatically treated as landings.
- Old position context expires after 180 s. A resulting `context_uncertain` close means
  insufficient evidence to keep the alert active, not proven recovery.

Fresh traffic elsewhere does not establish local receiver coverage, and constant-track
projection assumes the last known motion continues. Accordingly, `signal_loss` means a
possible observation/contact gap, not proven transponder failure. No alerts during source
uncertainty must not be interpreted as confirmed normal airspace.

### Lifecycle and reproducibility

Persistent candidates update one alert ID rather than opening a new alert every poll.
Closed events distinguish reacquired contact, unavailable observations, source uncertainty,
and a condition no longer observed. The source-end summary retains whatever was active
at the last poll; end-of-file does not fabricate future signal-loss observations.
Duplicate fresh positions may retain already established motion evidence until the audit's
age limit, with original measurement provenance; emergency code changes can be observed
even without a new position. Top-five presentation does not discard other alert history.

`RuleEngine.process_poll()` is incremental, deterministic, and uses no future records.
The offline exporter processes a read-only bounded prefix while collection can continue;
rerun it at the end for the complete recording. A negative/empty alert result is a
screening output with data-quality context, not an ML evaluation or ground-truth label.

## Development checks

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Tests use synthetic responses and temporary SQLite databases. An automatic fixture blocks
Requests network access, so missed mocks fail instead of spending live OpenSky credits.
The suite covers credentials precedence, token reuse/refresh, rate limits, malformed
responses, backoff, quota exhaustion, interruption, append-only persistence, audit
exclusions, age boundaries, trajectory gaps, run isolation, causal replay prefixes,
heading wraparound, signed versus absolute turns, closed loops, missing telemetry,
window readiness, surface geometry, numerical overflow, evidence-backed rules, alert
lifecycle, source outages/recovery, cached/stale clocks, mass disappearances, border exits,
airport context, and recorded-poll replay causality.
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
