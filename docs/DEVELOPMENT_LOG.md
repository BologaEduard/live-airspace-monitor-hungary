# AI-assisted development log

Record actual work, not planned or assumed results. Add the tool/model when known,
the relevant prompt or request, the resulting change, verification, and any manual correction.

## 2026-11-20 — Project scaffold

- Tool: Codex coding assistant.
- Request: establish the project folder structure and preserve the option of using
  a future subdomain of `bologaeduard.app`.
- Change: added a Python package scaffold, CLI entry point, development configuration,
  folder layout, repository instructions, and setup documentation.
- Existing OpenSky access-check script and sample snapshot remain at their original paths.
- Verification: parsed `pyproject.toml` with Python's TOML parser, parsed all package
  files with `ast`, and successfully ran `python -m airspace_monitor` with and without
  `--help` using `src` on the import path. Checked Git exclusions for credentials,
  local environments, recordings, and generated artifacts; `git diff --check` passed.
- Limitations: package installation and Ruff were not run; Ruff is not installed in
  the current interpreter. No unit tests exist yet.
- Deployment: not performed; no DNS records changed and no live API calls made.

## 2026-11-20 — OpenSky client and raw collection

- Tool: Codex coding assistant, local Python 3.13.1, pytest, Ruff, and Git.
- Request: proceed with the next implementation unit and commit/push logical units.
- Relevant design prompt: implement reusable OAuth authentication, bounded periodic
  collection, explicit failure recording, and append-only raw SQLite storage; test
  with synthetic responses without consuming live API credits.
- Reference: verified authentication, state-envelope fields, and rate-limit headers
  against the [official OpenSky API documentation](https://openskynetwork.github.io/opensky-api/rest.html).
- Change: added configuration and credential precedence, token reuse/expiry refresh,
  a single-poll API client, collection scheduling/backoff, SQLite schema version 1,
  and the `collect` CLI. Kept the original checkpoint script's behavior unchanged
  (only import spacing was adjusted for lint).
- Design decisions: persist a completed poll before scheduling the next; preserve
  invalid states responses and duplicate API timestamps; never store OAuth bodies
  or external exception messages. Authentication failures are explicit poll outcomes.
  Successful token requests are not separate rows. A states 401 is saved before
  reauthentication at the next poll; server retry delays are never shortened.
- AI-generated edge cases: partial environment credentials, expiry boundary, 401,
  malformed JSON/envelopes, null states, provider waits above the local backoff cap,
  quota exhaustion, repeated failures, interrupted runs, duplicate source timestamps,
  and oversized integers that SQLite cannot store.
- Review corrections: removed an unused import, corrected import spacing, named early
  deadline stops explicitly, and rejected oversized source timestamps/credit headers.
  No human manual code corrections were supplied in this step.
- Verification: editable installation of `.[dev]` into `.venv` succeeded;
  `ruff check .`, `pip check`, module/console help commands, and `git diff --check`
  passed. The full offline suite passed: **59 tests**. A test fixture blocks Requests
  network access; the CLI is exercised with fake responses and real temporary SQLite files.
- Limitations: no live collection was run and no new flight recordings were produced.
  Telemetry auditing, trajectory processing, anomaly detection, and the UI remain future work.

## 2026-11-20 — First live collector verification

- Request: fetch live data to verify the completed ingestion pipeline.
- Ran `collect --credentials credentials.json --max-polls 1`. The sandboxed attempt
  failed during authentication with a network error and was recorded as such. Retried
  with network access; authentication and the states request succeeded (HTTP 200).
- Verified the saved response in local `data/raw/opensky.sqlite3`: API timestamp
  `2026-11-20T21:35:13Z`, 70 vectors, 61 airborne and 9 on ground. Of the airborne
  vectors, 59 have non-null position time, coordinates, barometric altitude, velocity,
  track, and vertical rate. Two airborne position timestamps are older than 30 seconds.
  Missing-field and stale-position counts are separate checks and may overlap.
- The response reported 3,998 remaining credits. Both the failed attempt and successful
  poll remain in the database. Confirmed the database is ignored by Git; no credentials
  or raw recordings are included in this documentation commit.
- This is a single live snapshot, not a trajectory dataset. Multi-hour collection and
  systematic telemetry auditing are still required.

## 2026-11-26 — Background recording and telemetry audit

- Request: begin a multi-hour recording, implement telemetry auditing, and then build
  trajectory segments; continue committing and pushing logical units.
- Started one hidden, three-hour collector at `2026-11-26T10:06:41Z`, polling every
  15 seconds into local `data/raw/session-20261126T100641Z.sqlite3`. Logs and process
  metadata are in ignored `data/raw/` files. Checked for an already running collector
  before launch. Collection is ongoing; a completed three-hour dataset is not yet claimed.
- Added a read-only bounded-prefix recording reader, atomic derived-file exports,
  named validated observations, incremental telemetry audit, and the offline `audit` CLI.
- Design: preserve fresh partial telemetry for tracking but explicitly quarantine it
  for full analysis; preserve nulls, exclude stale/duplicate/late points with reasons,
  keep independent per-run tracking state, and never classify provider failures as
  empty-airspace snapshots. Raw recordings are not modified.
- AI-generated tests cover real zeros, missing optional versus required fields,
  nonfinite values, causal timestamps, malformed rows, age boundaries, run isolation,
  source preservation, concurrent appends, safe export replacement, and credential-free CLI use.
- Review correction: guard numeric validation against oversized Python integers that
  overflow float conversion. No human manual code corrections were supplied.
- Verification: Ruff passed and all **96 tests** in the collector/audit suite passed.
  The uncommitted trajectory module is excluded from this checkpoint's test count.
  A live-data audit of the first 20 completed polls found 2,314 raw vectors,
  709 ground exclusions, 1,605 accepted airborne observations, and one incomplete
  analysis input. These are prefix statistics, not final session totals.

## 2026-11-26 — Causal trajectory segments and recording finalization

- Added `TrajectoryBuilder.add()` and the offline `segment` command. Each accepted
  point gets a deterministic segment ID and index; gaps over 120 seconds and separate
  collection runs produce separate segments. Duplicate/late observations cannot move
  state backwards. Missing telemetry is preserved and analysis eligibility is explicit.
- AI-generated tests cover interleaved aircraft, the exact gap threshold, late and
  duplicate points, run isolation, incomplete telemetry, stable replay prefixes,
  repeatable exports, safe failure on malformed JSONL, and credential-free CLI use.
- Verification: **109 tests passed**, and Ruff passed. Two isolated in-memory mutation
  probes confirmed that the appropriate tests fail for silent `None`-to-zero coercion
  and for ignoring long observation gaps. No source files were modified by the probes.
- End-to-end check on the first 39 live polls: 4,556 raw vectors, 1,423 ground exclusions,
  one duplicate position, 3,132 accepted points (3,131 complete for analysis), and 114
  trajectory segments. This prefix is a smoke test, not the final three-hour dataset.
- Started a hidden local finalizer which waits for the existing collector process to end,
  then runs audit and segmentation again. Its script, status, and logs are in ignored
  `data/raw/`; status was verified as `waiting_for_collector`. It makes no API requests.
  A `processed` status means the available recording was processed, not proof that
  collection ran for all three hours; final timestamps and poll outcomes must be checked.
- Collection was still active at this checkpoint. No raw telemetry, derived datasets,
  credentials, or process metadata were included in the commits.

## 2026-11-26 — Kinematic features while recording continues

- Request: make progress alongside the background recording and check its health occasionally.
- Added spherical geometry helpers, configurable trailing-window kinematics, and the
  offline `features` CLI. Reused the existing trajectory builder and extracted shared
  validated observation reading to avoid different live/replay preprocessing paths.
- Features include signed/absolute turns and rates, path length, net displacement,
  tortuosity/straightness, a sample-centred spatial radius, descent gradient, vertical
  acceleration, altitude change, contact age, and the fixed five-feature ML input order.
- Defaults: 300-second windows, 180-second minimum duration, 8 points, maximum 45-second
  sample gap, and 120-second segment gap. Window coverage and ML eligibility are distinct.
  Missing telemetry is not imputed; undefined metrics stay null with quality flags.
- Verified geometric conventions against the official scikit-learn haversine documentation
  and GeoPy's mean-earth-radius documentation (linked in README). No new dependency added.
- AI-generated tests cover north crossings, signed versus absolute turns, closed loops,
  sample timing, zero speed, window expiry, missing tracks, segment resets, run isolation,
  causal prefixes, overflow, dateline geometry, repeatable exports, and CLI validation.
- Verification: **142 tests passed** and Ruff passed. An in-memory naive-heading-subtraction
  mutation was caught by the north-crossing tests; source files were not modified by it.
- Live checks during development confirmed 60, 83, 89, then 97 successful polls with no
  recorded failures. At the 89-poll check the latest completed poll was 11.1 seconds old.
  The 97-poll prefix audit yielded 8,391 accepted points, of which 6,416 windows had
  sufficient coverage and 6,365 were ML-input eligible. These are temporary prefix counts.
- Extended the waiting finalizer to run audit, segmentation, and feature export when the
  collector exits. Verified the waiting process identity before replacing it; the live
  collector was not restarted. Finalizer status was confirmed as `waiting_for_collector`.
- No human manual code corrections supplied in this step. No ML model or anomaly rules
  implemented yet. Raw data, derived exports, and process metadata remain local and ignored.

## 2026-11-26 — Motion rules, geographic context, and alert lifecycle

- Request: continue with the deterministic anomaly detector while recording continues.
- Added explicit, configurable screening rules for localized signed-turn accumulation,
  sustained rapid/steep descent, abrupt vertical-speed changes, and separately typed
  emergency squawk observations. These are initial engineering thresholds, not calibrated
  or operational flight-safety limits. Every candidate carries numeric evidence and limitations.
- Added airport-reference proximity, bounding-box clearance, and constant-track projection
  helpers; none is presented as proof of radar coverage or runway/ILS alignment.
- Verified LHBP/LHDC/LHSM reference coordinates against the primary OurAirports CSV at
  `https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv`.
  Verified emergency-code labels against official EASA/FAA documentation. No OpenSky
  credits were used for this reference lookup.
- Added stable opened/updated/closed alert identities, explicit uncertainty/reacquisition
  close reasons, per-type opened-event counts, and a severity-ranked panel capped at five.
- Verification: **35 targeted motion/context/lifecycle tests passed** within the full
  offline suite. Cases include north-crossing circles in both directions, zigzags,
  insufficient/partial evidence, a three-degree approach-like descent, extreme descent
  near an airport, confirmation gaps, code typing, and lifecycle deduplication.
- The approach fixture uses coherent moving positions and an altitude profile; it is
  an analytical unit fixture, not a verified LHBP runway procedure or benchmark label.

## 2026-11-26 — Source-aware continuity and recording detector

- Added conservative raw-contact continuity state, source-health/reset guards, a shared
  causal `RuleEngine.process_poll()`, and the credential-free offline `detect` command.
  Exports include alert lifecycle events, source-quality events, and a full configuration
  and diagnostic report. The collector remains a recorder; no web/live inference loop added.
- Source failures, empty/all-stale traffic, capture/API clock problems, changed scope,
  large poll gaps, and mass disappearances cannot be turned into individual loss claims.
  Fresh contacts update continuity even when cleaned positions are unavailable. Ground,
  altitude, configured airport proximity, projected boundary exit, and context age are
  explicit guards. Expiry/uncertainty does not assert a recovered or normal aircraft.
- Review corrections: reject future API time relative to event time, detect regressing
  capture clocks, require all four stored bounding-box coordinates instead of silently
  using defaults, reset descent confirmation on ground observations, and guard extreme
  projections. Readable descent evidence now includes ground angle/abrupt acceleration.
- Verification: **213 offline tests passed**, Ruff passed, CLI help and a real recording
  prefix completed successfully. Tests include source outages and recovery, landing versus
  high overflight, predicted exits, stale/missing/duplicate positions with fresh contacts,
  unsynchronised clocks, run/scope isolation, context expiry, JSON/SQLite reproducibility,
  source preservation, and causal replay prefixes.
- In-memory mutation probes confirmed tests fail when loss baselines survive a source
  outage or when projected boundary exits are ignored. Probes did not modify source files.
- Smoke test on the first 180 polls: 179 advancing usable snapshots, one cached/nonadvancing
  diagnostic, seven opened candidates (six descent, one contact gap), twelve updates, seven
  closes, and zero active candidates at that prefix's end. These are unlabelled heuristic
  outputs, not verified real anomalies or precision/recall estimates. Thresholds were not
  tuned against this prefix. Later live checks showed 187 and 193 successful collector polls.
- Final CLI verification on the 213-poll prefix reported eight opened candidates (seven
  descent and one contact gap), sixteen updates, eight closes, and one nonadvancing
  source diagnostic. These updated counts have the same unlabelled screening status.
- Extended the identity-checked, waiting local finalizer to run `detect` after audit,
  segmentation, and feature export. The original collector process was left running.
- No human manual code corrections supplied. No ML training, quantitative benchmark,
  application deployment, or DNS modification occurred. All recording/derived data and
  process metadata remain local and ignored by Git.

## 2026-11-26 — Read-only local preview API

- Tool: Codex. User moved the first local website ahead of the synthetic benchmark;
  collection should continue independently. Implemented a bounded presentation adapter,
  optional FastAPI application, and `serve` command bound only to `127.0.0.1`.
- Reads at most 48 recent successful polls from the newest successful run. Snapshot
  times advance strictly; future positions, malformed coordinates and scope are rejected.
  Missing telemetry stays null, zero stays zero, stale positions are explicitly flagged.
  Recording freshness, source interruption, empty data and uncertain clocks are distinct.
- Matching detector exports supply historical candidates only. The browser can restrict
  visibility by source time, capture time and attempt ID; no inference or OpenSky call
  is added to the preview. Static serving is limited to the built public frontend directory.
- Verification: **229 offline Python tests passed**, Ruff passed. Added bounded/read-only,
  run-isolation, null/zero, malformed/stale telemetry, source-health, analysis-provenance,
  static traversal and arbitrary-file query tests using synthetic fixtures.
- One upstream Starlette TestClient deprecation warning remains for its supported `httpx`
  adapter; it does not fail these checks. No human manual code corrections supplied.
- Existing raw recording and waiting finalizer were left running. No credentials read,
  DNS changes, public deployment, synthetic benchmark or model training performed.

## 2026-11-26 — Night atlas local web foundation

- User requested downloading and applying Impeccable and Anthropic Frontend Design.
  Installed both from their upstream GitHub repositories using skill-installer. Also
  followed the Sites local-repository workflow without registering or publishing a Site.
  The Impeccable engine v0.1.31 was downloaded only after checking its shipped SHA-256
  manifest, and run from an ignored local directory with telemetry disabled.
- User confirmed **English** and **Night atlas** in native chat questions. A local
  graphical direction chooser was served too; the decision was a chat answer, not a
  claimed chooser click. Recorded product context, a direction contract and design tokens.
- Added a Vite/vanilla-JavaScript interface with self-hosted Manrope, locally bundled
  Natural Earth geography, MapLibre, search, aircraft selection, recent-frame replay,
  1×/5×/20× controls, and historical evidence details. Asset provenance is in web/ASSETS.md.
  No fabricated flights, raster mockups, ML scores, or verified-incident claims ship.
- Corrections during implementation: MapLibre 6 uses named exports and requires its
  worker to be explicitly bundled for Vite; aircraft markers must retain MapLibre's
  positioning class. Browser tests guard worker console errors as well as selection.
  A mobile icon-only Fit Hungary button also needed an explicit accessible name.
- Impeccable first-viewport capture verified the map and playback action at 1440×900
  and 390×844. A fresh independent finish reviewer requested three material changes:
  explicit missing-altitude encoding, protected mobile annotations, and quieter compact
  background traffic. Applied them together; the same reviewer scored all three resolved
  with disposition **ship**. This verdict covers those fixes, not production readiness.
- Ran the mechanical detector once. Its only finding claimed flat heading hierarchy
  from index.html; external CSS and the actual captures demonstrate distinct heading
  sizes, so the reviewer classified it as a false positive. Did not rerun the detector.
- Verification: production build succeeded; **9 offline Playwright browser tests passed**
  in isolated Chromium/Edge. Covered worker errors, selection, null/zero measurements,
  causal evidence visibility, playback, search recovery, keyboard tabs, unavailable data,
  HTTP failure, and overflow at 320/390/768/1440px. Physical mobile/Safari not tested.
  Build reports the map library's >500kB chunk advisory; bundle splitting is deferred.
- README now distinguishes the local foundation from planned full-session replay,
  benchmark, trained ML and deployment. The running app is loopback-only on port 8000.
  At 11:55 UTC the independent collector had 434 successful polls and no recorded failures;
  its existing finalizer was still waiting. Raw/derived data and runtime files stay ignored.
- No human manual code corrections supplied. No DNS change or public deployment occurred.
