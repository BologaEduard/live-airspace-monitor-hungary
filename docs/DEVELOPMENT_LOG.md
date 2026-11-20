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
