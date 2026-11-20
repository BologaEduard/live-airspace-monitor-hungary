# Project development instructions

- Read `SPEC.md` and `README.md` before changing project behavior. Distinguish
  implemented behavior from planned features in code and documentation.
- Keep Python application code in `src/airspace_monitor/` and tests in `tests/`.
- Use UTC timestamps and SI units internally. Convert display units at the UI boundary.
- Preserve missing telemetry as missing; never silently replace it with zero or normal status.
- Preserve raw recordings. Record preprocessing exclusions and their reasons.
- Use the same causal processing and detection logic in live and replay modes.
  A decision must not use observations later than the current simulation time.
- Distinguish provider outages and stale observations from individual aircraft disappearance.
- Every alert must include measurable evidence and relevant data-quality limitations.
- Split source trajectories before creating synthetic variants. Keep related windows and
  variants together; do not tune models or thresholds on test data.
- Never read, print, commit, or send credentials unless needed for an explicitly authorized
  authentication operation. Keep secrets on the server and out of browser bundles and logs.
- Keep recordings, generated models, and evaluation outputs out of Git by default.
  Commit only deliberately selected, documented demo data and reproducible reports.
- Run checks appropriate to each change. Use synthetic fixtures for automated tests;
  do not spend live API credits in tests.
- Record meaningful AI-assisted decisions, checks, and manual corrections in
  `docs/DEVELOPMENT_LOG.md`.
- The intended future domain is a subdomain of `bologaeduard.app`; the hostname is
  undecided. Do not change DNS or publish a deployment as part of local scaffolding.
