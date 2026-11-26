# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

The repository already contains a Python collector, audit, features, and deterministic
rule engine. SPEC.md proposes FastAPI with a lightweight Leaflet/MapLibre frontend.
Implementation assumption for this local iteration: FastAPI, vanilla JavaScript, Vite,
and MapLibre. The user requested no particular JavaScript framework.

## Users

The author is building a BME MSc AI in Practice assignment and wants to understand every
implementation step. Course assessors are an inferred secondary audience. This iteration
is a local project preview, not a deployed professional air traffic control service.

## Product Purpose

Explore recorded aircraft over Hungary, inspect a selected flight, and review preliminary
rule candidates with physical evidence and data-quality context.

## Operating Context

The user requested moving the first visually polished web foundation ahead of the synthetic
benchmark. A complete website is not required in this iteration. Existing multi-hour
OpenSky collection should continue independently. Work is committed and pushed in logical units.

## Capabilities and Constraints

- Preview runs on the user's computer; no publication, DNS change, or Sites registration.
- Existing SQLite recordings and detector exports are real local evidence.
- Credentials remain server-side and must never be exposed by static file serving.
- Missing telemetry remains missing; recorded data must not be presented as verified live data.
- Rule candidates are preliminary heuristics; ML training and quantitative evaluation are pending.
- Bound replay/trail data and preserve source timestamps and causal visibility.
- A future subdomain under bologaeduard.app is possible; the hostname is undecided.

## Brand Commitments

The user explicitly chose an English interface. Development explanations remain Hungarian.
No established visual identity or commercial brand was supplied. Impeccable and Frontend
Design were explicitly requested as design guidance. The user chose Night atlas:
a cool light shell, a large deep-blue map, and amber aircraft selection. The choice
was supplied in the native chat question, not through a claimed graphical-board click.

## Evidence on Hand

SPEC.md, README.md, src/airspace_monitor/, local data/raw/ SQLite recordings, and local
data/processed/ analysis exports. Recordings, credentials, and generated results remain
ignored by Git. No fabricated anomaly labels, model scores, or safety claims.

## Product Principles

- Let the geographical view lead, with selected-flight details close to the map.
- Show evidence and provenance beside rule candidates.
- Make freshness, replay, missing data, and unavailable analysis distinguishable.
- Build a useful, visually coherent foundation before expanding feature scope.
