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
