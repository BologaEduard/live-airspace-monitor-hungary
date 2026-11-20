# Project Specification: Live Airspace Monitor for Hungary

- **Course:** AI in Practice — BME MSc (2026)
- **Assignment:** `#1. Live airspace monitor for Hungary`
- **Repository:** `https://github.com/BologaEduard/live-airspace-monitor-hungary`
- **Estimated Effort:** 15–20 hours (AI-assisted development with copilots/agents)

---

## 1. Deadlines & Milestones

| Milestone | Date | Status / Deliverable |
| :--- | :--- | :--- |
| **Topic Reservation** | Nov 12–20, 2026 | Claim `#1` in MS Teams *Homework Assignments* channel (**Done**) |
| **Data Access Checkpoint** | Before Nov 20, 2026 | Verified OpenSky OAuth2 API access (96 live vectors over Hungary), pushed `check_opensky.py` & `sample_hungary_states.json` (**Done**) |
| **Final Submission** | **December 7, 2026** | Upload deliverables via Moodle (`https://edu.vik.bme.hu`) |
| **Oral Defense** | Exam / Defense period | ~1-minute explanation and defense of the ML/statistical analysis component |

---

## 2. Official Course Requirements & Deliverables

1. **Public Git Repository:**
   - Clean, reproducible codebase in `live-airspace-monitor-hungary`.
   - Sensitive credentials (`credentials.json`, `.env`) strictly excluded via `.gitignore`.
2. **Live Deployed Application:**
   - Publicly accessible URL hosted on **GitHub Pages**, **Vercel**, or **Hugging Face Spaces**.
3. **Comprehensive `README.md`:**
   - Clear setup and usage instructions (both live deployment and local execution).
   - Technical overview of the data pipeline, preprocessing audit, hybrid anomaly detector, and evaluation results.
   - **AI Development & Testing Log:** Documentation of which copilots/agents were used, key prompts that shaped the system, what had to be fixed manually, and how LLMs were used to generate adversarial `pytest` edge-case suites.
4. **Analytical / ML Component (Oral Defense Requirement):**
   - At least one machine learning, statistical, or quantitative evaluation component that can be explained and defended in ~1 minute.
5. **Demo Video *(Optional, strongly recommended)*:**
   - A ~3-minute walkthrough demonstrating live map tracking, history replay, and anomaly detection alerts.

---

## 3. Functional & UX Requirements

### 3.1 Live Airspace Map
- Display real-time aircraft state vectors over Hungary and its immediate border region.
- **Geographic Bounding Box:** `lamin=45.7`, `lomin=16.1`, `lamax=48.6`, `lomax=22.9` (with optional regional buffer around Budapest / LHBP).
- Render aircraft markers rotated by `true_track`, color-coded by altitude or anomaly status, with interactive popups/sidebars showing `callsign`, `icao24`, `origin_country`, barometric/geometric altitude, ground speed, vertical rate, and squawk code.

### 3.2 History Replay Mode
- Allow the user to scrub and play back recorded airspace trajectories over time (Play/Pause, timeline slider, `1x` / `5x` / `20x` playback speeds).
- Bundle a multi-hour recorded dataset of Hungarian airspace traffic so the replay mode works deterministically offline or when live API rate limits are reached.

### 3.3 Airspace Anomaly Detection
Detect, highlight on the map, and explain three core anomaly types:
1. **Holding Patterns:**
   - Sustained circular or racetrack orbits where an aircraft accumulates significant heading change ($\ge 360^\circ$ unwrapped turn) within a localized spatial radius without net translational progress.
2. **Unusual Descents:**
   - Abrupt negative vertical speed spikes (`vertical_rate`), unusually steep descent gradients ($\arctan(\text{vertical\_rate} / \text{velocity})$) outside standard final approach glideslopes, or emergency squawk codes (`7700`, `7600`, `7500`).
3. **Sudden Loss of Signal:**
   - Unexpected disappearance of an active airborne transponder (`on_ground == False`, `baro_altitude > 1500 m`) well inside Hungarian radar coverage, distinguished from normal landings near airports (LHBP Budapest, LHDC Debrecen, LHSM Sármellék) and border exits.

### 3.4 Cognitive-Load & Automation-Bias Safeguards
- **Working Memory Budget ($7 \pm 2$ items):** Present a focused **Top Active Alerts** panel (capped to highest-severity events) rather than overwhelming the user with ~100 raw simultaneous flight rows.
- **Mitigating Shallow Processing & Automation Bias:** Every ML or rule-based alert must display concrete, verifiable physical evidence alongside its anomaly score (e.g., *"Unwrapped turn: 410° in 4.5 min within 7.8 km radius"* or *"Descent rate: -21.4 m/s at FL280, 48 km from LHBP"*), enabling immediate human verification.

---

## 4. Data Source, Ingestion & Preprocessing Audit

- **Primary API:** OpenSky Network REST API (`https://opensky-network.org/api/states/all`)
- **Authentication:** OAuth2 Client Credentials flow (`https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token`), providing **4,000 API credits/day**.
- **Key State Vector Fields (`states[i]`):**
  - `[0]` `icao24` (unique transponder hex ID — primary tracking key)
  - `[1]` `callsign`, `[2]` `origin_country`
  - `[3]` `time_position`, `[4]` `last_contact`
  - `[5]` `longitude`, `[6]` `latitude`, `[7]` `baro_altitude`, `[13]` `geo_altitude`
  - `[8]` `on_ground`, `[9]` `velocity` (m/s), `[10]` `true_track` (deg), `[11]` `vertical_rate` (m/s)
  - `[14]` `squawk`
- **Resilient Ingestion & Caching:**
  - Run `collector.py` at 10–15 second intervals across peak daytime traffic and evening arrival waves, storing timestamped snapshots in SQLite / JSONL.
  - Implement exponential backoff for HTTP `429` rate limits and local snapshot caching.
- **Explicit Data Audit (Zero Silent Failures):**
  - Inspect raw telemetry distributions before modeling.
  - Never allow missing fields (`None` for `baro_altitude`, `vertical_rate`, `velocity`, or `true_track`) to silently coerce to `0` or default to "normal".
  - Log explicit preprocessing audit counters per run: total raw vectors fetched, `on_ground` aircraft excluded, null-telemetry records quarantined, and valid airborne trajectories processed.

---

## 5. Hybrid ML / Statistical Analysis & Evaluation Design (Oral Defense Focus)

### 5.1 Trajectory Feature Engineering
Group sequential snapshots by `icao24` into sliding time windows (3–5 minutes) and compute kinematic features:
- **Angular & Path Features:** Unwrapped heading change rate ($\Delta \psi / \Delta t$, properly handling $359^\circ \leftrightarrow 0^\circ$ wraparound), cumulative absolute turn angle ($\sum |\Delta \psi|$), and **path tortuosity / straightness index** ($L_{\text{path}} / d_{\text{net}}$).
- **Vertical Profile Features:** `vertical_rate` (m/s), vertical acceleration ($\Delta v_z / \Delta t$), descent gradient ($\arctan(\text{vertical\_rate} / \text{velocity})$), and distance/bearing to nearest major Hungarian runway.
- **Continuity Features:** Time elapsed since `last_contact` ($\Delta t_{\text{gap}}$) conditioned on altitude and distance from bounding-box boundaries.

### 5.2 Hybrid Anomaly Detection Model (Deterministic + ML)
- **Deterministic Kinematic Rules:** Provide byte-identical, transparent physical thresholds for holding orbits, steep non-ILS descents, and mid-air transponder dropouts.
- **Unsupervised ML Scorer (`IsolationForest`):** Train a `scikit-learn` `IsolationForest` on normal Hungarian overflight and standard arrival windows using `[velocity, vertical_rate, abs_turn_rate, tortuosity, baro_altitude]` to surface multi-dimensional kinematic outliers.
- **Complementary Failure Modes:** Deterministic rules guarantee crisp, auditable physical boundaries, while the Isolation Forest catches subtle multi-feature trajectory anomalies that single-threshold rules miss.

### 5.3 Rigorous Evaluation Protocol
Because anomalies represent a tiny minority of airspace traffic (~2–8%), evaluation avoids raw-accuracy traps:
1. **Majority-Class Floor:** Always report the constant majority-class ("all normal") baseline accuracy alongside every detector's accuracy.
2. **Imbalance-Aware Metrics:** Report **Accuracy (vs. Majority-Class Floor)**, **Macro-F1**, **Cohen's kappa** (correcting for chance agreement), and **Per-Class Recall** (separately for *Holding Pattern*, *Unusual Descent*, and *Signal Loss*), accompanied by 95% Wilson confidence intervals.
3. **Paired Statistical Significance (`McNemar's Test`):** Compare the deterministic rule-only baseline against the hybrid (`Rules + IsolationForest`) detector on the exact same trajectory windows using **McNemar's exact paired test** to verify whether improvements are statistically significant.
4. **Synthetic Anomaly Benchmark & Artifact Check:** Inject realistic synthetic anomalies (holding loops, rapid emergency descents, mid-air signal dropouts) into clean recorded Hungarian flight tracks. Validate that injected tracks preserve realistic kinematic continuity (no unnatural step artifacts that a classifier could exploit instead of true anomaly physics).

### 5.4 Optional Grounded LLM Briefing Helper
- If added to the inspector sidebar, a *"Generate ATC Summary"* action passes **only** precomputed deterministic kinematic metrics (never raw unverified telemetry) with a strict JSON output schema (`summary`, `severity`, `physical_evidence`, `recommended_check`) to prevent hallucination.

---

## 6. Recommended System Architecture & Testing

- **Data, ML & Evaluation Pipeline (`Python`):**
  - `check_opensky.py`: OAuth2 credential verification and live snapshot test (**Done**).
  - `collector.py`: Rate-limit-safe OpenSky poller saving snapshots to SQLite / JSONL.
  - `preprocess.py`: Trajectory segmentation, heading unwrapping, and explicit null-telemetry audit logging.
  - `anomaly_detector.py`: Hybrid kinematic rule + `IsolationForest` scorer producing structured anomaly alerts with physical evidence strings.
  - `evaluate.py`: Synthetic anomaly benchmark outputting a complete evaluation table (Majority Floor, Accuracy, Macro-F1, Cohen's kappa, Per-Class Recall, and McNemar $p$-value).
- **Adversarial `pytest` Suite (`tests/`):**
  - Use LLMs to generate adversarial edge-case unit tests (e.g., $359^\circ \to 2^\circ$ north-crossing turns, `None` vertical rates, border exits vs. mid-air signal dropouts, normal LHBP ILS glideslopes) and verify that the test suite fails on naive/broken implementations before passing on the fixed pipeline.
- **Web Application & Deployment:**
  - **Option A (Hugging Face Spaces — Full Python + Web UI):** FastAPI backend serving live authenticated OpenSky proxy requests, real-time hybrid ML inference, and pre-recorded replay datasets to an interactive Leaflet / MapLibre frontend.
  - **Option B (Vercel / GitHub Pages — Static Frontend + Precomputed Bundles):** React / Preact + TypeScript + MapLibre GL frontend with anomaly-annotated replay datasets and a lightweight serverless proxy for live state updates.

---

## 7. Implementation Roadmap (~17 Hours Total)

1. **Data Collection & Audit Pipeline (2–3 hours):**
   - Collect 2–3 multi-hour snapshots of Hungarian air traffic, run the raw telemetry audit, and export clean replay bundles.
2. **Hybrid Detector, Adversarial Pytest & Evaluation (4–5 hours):**
   - Implement trajectory segmentation, kinematic features, `IsolationForest` scorer, adversarial `pytest` suite, and the `evaluate.py` statistical benchmark.
3. **Cognitive-Load-Aware Map & Replay Frontend (5–6 hours):**
   - Build live map view, flight trail overlays, timeline playback controls, and the evidence-backed *Top Active Alerts* inspector panel.
4. **Deployment, Documentation & Demo (3–4 hours):**
   - Deploy to a public URL, write the full `README.md` (including evaluation tables and AI prompt/debugging log), and record the optional 3-minute demo video.