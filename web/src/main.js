import './styles.css';
import { icon, planeIcon } from './icons.js';
import { AirspaceMap } from './map.js';

const $ = (id) => document.getElementById(id);
const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const number = (value, digits = 0) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(value);
const utc = (value, seconds = true) => finite(value) ? new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) }).format(new Date(value * 1000)) : 'Unavailable';
const dateUtc = (value) => new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(value * 1000));
const state = { data: null, index: 0, selected: null, selectedLabel: '', query: '', mode: 'latest', playing: false, timer: null };

document.querySelectorAll('[data-icon]').forEach((element) => { element.innerHTML = icon(element.dataset.icon); });
$('search-icon').innerHTML = icon('search');
$('selected-plane-icon').innerHTML = planeIcon;
const map = new AirspaceMap(selectAircraft);

function currentFrame() { return state.data?.frames[state.index]; }
function visibleAircraft() {
  return (currentFrame()?.aircraft ?? []).filter((plane) => `${plane.callsign ?? ''} ${plane.icao24} ${plane.registration_country ?? ''}`.toLowerCase().includes(state.query));
}
function selectAircraft(id) {
  state.selected = id;
  const plane = currentFrame()?.aircraft.find((item) => item.icao24 === id);
  state.selectedLabel = plane?.callsign || id;
  render();
  $('announcer').textContent = `Selected ${state.selectedLabel}`;
}
function renderMeasurement(id, value, unit, digits = 0) {
  const element = $(id);
  element.replaceChildren();
  element.classList.toggle('unavailable', !finite(value));
  element.append(document.createTextNode(finite(value) ? number(value, digits) : 'Unavailable'));
  if (finite(value)) { const label = document.createElement('small'); label.textContent = unit; element.append(label); }
}
function renderAircraft(aircraft) {
  const frame = currentFrame();
  const plane = frame?.aircraft.find((item) => item.icao24 === state.selected);
  const picker = $('aircraft-select');
  picker.replaceChildren();
  if (!plane) picker.add(new Option(state.selected ? 'Aircraft not in this frame' : 'Choose an aircraft', ''));
  [...aircraft].sort((a, b) => (a.callsign || a.icao24).localeCompare(b.callsign || b.icao24)).forEach((item) => picker.add(new Option(`${item.callsign || item.icao24} / ${item.icao24}`, item.icao24)));
  picker.value = plane ? plane.icao24 : '';
  $('selected-callsign').textContent = plane?.callsign || (plane ? plane.icao24 : state.selectedLabel || 'Select an aircraft');
  $('selected-identity').textContent = plane ? plane.icao24 : state.selected ? 'No position in this frame' : 'Choose a marker on the map.';
  renderMeasurement('selected-altitude', plane?.baro_altitude, 'm');
  renderMeasurement('selected-speed', finite(plane?.velocity) ? plane.velocity * 3.6 : null, 'km/h');
  renderMeasurement('selected-vertical', plane?.vertical_rate, 'm/s', 1);
  renderMeasurement('selected-track', plane?.true_track, 'deg');
  $('selected-country').textContent = plane?.registration_country || 'Unavailable';
  $('selected-geo-altitude').textContent = finite(plane?.geo_altitude) ? `${number(plane.geo_altitude)} m` : 'Unavailable';
  $('selected-squawk').textContent = plane?.squawk || 'Unavailable';
  $('selected-position-time').textContent = plane ? `${utc(plane.time_position)} UTC` : 'Unavailable';
  const missing = plane ? ['baro_altitude', 'velocity', 'true_track', 'vertical_rate'].filter((key) => plane[key] === null).length : 0;
  const quality = $('quality-note');
  quality.classList.toggle('is-stale', Boolean(plane?.position_stale));
  quality.querySelector('p').textContent = !plane ? 'Choose an available aircraft or move the recording timeline.' : plane.position_stale ? `Position is ${number(plane.position_age_seconds)} seconds older than this frame. Treat it as stale.` : missing ? `${missing} telemetry field${missing === 1 ? ' is' : 's are'} unavailable. Missing values are not treated as zero.` : 'Telemetry is present for this recorded frame. This is not a model assessment.';
}

function renderEvidence() {
  const frame = currentFrame();
  const analysis = state.data?.analysis;
  const events = (analysis?.events ?? []).filter((event) => frame && event.source_api_time <= frame.time && event.event_time <= frame.completed_at && event.source_attempt_id <= frame.attempt_id).reverse();
  $('candidate-count').textContent = analysis?.available ? String(events.length) : '—';
  $('analysis-caption').textContent = analysis?.available ? `Recent history from analysis through ${utc(analysis.as_of_time)} UTC.` : 'Rule analysis has not been loaded for this recording.';
  const list = $('evidence-list');
  list.replaceChildren();
  if (!events.length) {
    const box = document.createElement('div'); box.className = 'empty-evidence';
    const title = document.createElement('strong'); title.textContent = analysis?.available ? 'No earlier candidates loaded' : 'Evidence is not available yet';
    const description = document.createElement('p'); description.textContent = analysis?.available ? 'There are no candidates in the loaded history before this frame. This does not establish that the airspace was normal.' : 'Recorded candidates will appear here after rule analysis is available. Aircraft measurements can still be inspected.';
    box.append(title, description); list.append(box); return;
  }
  const titles = { unusual_descent: 'Descent profile', signal_loss: 'Contact gap', holding_pattern: 'Holding-like movement', emergency_squawk: 'Emergency code' };
  events.slice(0, 6).forEach((event) => {
    const details = document.createElement('details'); details.className = 'evidence-entry';
    const summary = document.createElement('summary');
    const symbol = document.createElement('span'); symbol.className = 'candidate-symbol'; symbol.innerHTML = icon('warning');
    const heading = document.createElement('span'); heading.className = 'candidate-heading'; heading.append(document.createTextNode(`${titles[event.alert_type] || 'Recorded observation'} candidate`));
    const metadata = document.createElement('small'); metadata.textContent = `${event.icao24} / ${utc(event.source_api_time)} UTC`; heading.append(metadata);
    const chevron = document.createElement('span'); chevron.className = 'candidate-chevron'; chevron.innerHTML = icon('chevron');
    summary.append(symbol, heading, chevron);
    const body = document.createElement('div'); body.className = 'candidate-body';
    const evidence = document.createElement('p'); evidence.textContent = event.physical_evidence; body.append(evidence);
    const limitation = document.createElement('p'); limitation.textContent = event.limitations?.[0] || 'This screening candidate is not a verified incident.'; body.append(limitation);
    details.append(summary, body); list.append(details);
  });
}

function render() {
  const frame = currentFrame();
  const aircraft = visibleAircraft();
  if (!state.selected && aircraft.length) { state.selected = aircraft[0].icao24; state.selectedLabel = aircraft[0].callsign || aircraft[0].icao24; }
  const trails = new Map();
  (state.data?.frames ?? []).slice(0, state.index + 1).forEach((past) => past.aircraft.forEach((plane) => {
    if (plane.position_stale) return;
    const positions = trails.get(plane.icao24) ?? [];
    const last = positions.at(-1);
    if (!last || last[0] !== plane.longitude || last[1] !== plane.latitude) positions.push([plane.longitude, plane.latitude]);
    trails.set(plane.icao24, positions);
  }));
  map.update(aircraft, trails, state.selected, state.data?.bbox ?? { lomin: 16.1, lamin: 45.7, lomax: 22.9, lamax: 48.6 }, state.data?.airports ?? []);
  $('visible-count').textContent = frame ? `${aircraft.length} mapped aircraft` : 'Positions unavailable';
  $('map-empty').hidden = aircraft.length > 0 || !state.data;
  $('map-time').textContent = frame ? `${utc(frame.time)} UTC / recorded positions` : 'Recorded positions unavailable';
  $('trail-caption').textContent = state.selected ? `${state.selectedLabel || state.selected} / observed trail, up to this frame` : 'Select an aircraft to inspect its recorded trail.';
  const frames = state.data?.frames ?? [];
  $('timeline').max = String(Math.max(0, frames.length - 1));
  $('timeline').value = String(state.index);
  $('timeline').disabled = frames.length < 2;
  $('timeline').setAttribute('aria-valuetext', frame ? `${utc(frame.time)} UTC` : 'No frames');
  $('play-toggle').disabled = frames.length < 2;
  $('play-toggle').setAttribute('aria-label', state.playing ? 'Pause recording' : 'Play recording');
  $('play-toggle').innerHTML = `<span class="icon">${icon(state.playing ? 'pause' : 'play')}</span>`;
  $('selected-time').replaceChildren(document.createTextNode(frame ? utc(frame.time) : '--:--:--'));
  const utcLabel = document.createElement('small'); utcLabel.textContent = 'UTC'; $('selected-time').append(utcLabel);
  $('selected-time').title = frame ? new Date(frame.time * 1000).toISOString() : '';
  $('timeline-start').textContent = frames.length ? utc(frames[0].time, false) : '--:--';
  $('timeline-end').textContent = frames.length ? utc(frames.at(-1).time, false) : '--:--';
  $('timeline-window').textContent = frames.length > 1 ? `${Math.round((frames.at(-1).time - frames[0].time) / 60)} min loaded` : 'Recent frames';
  $('follow-latest').classList.toggle('is-active', state.mode === 'latest');
  $('follow-latest').setAttribute('aria-pressed', String(state.mode === 'latest'));
  renderSource(); renderAircraft(aircraft); renderEvidence();
}

function renderSource() {
  const source = state.data?.source;
  const badge = $('source-badge');
  const labels = { fresh_recording: 'Recording updates', saved_recording: 'Saved recording', source_interrupted: 'Source interrupted', source_clock_unknown: 'Source time uncertain', no_recording: 'No recording loaded', no_usable_frames: 'No usable frames' };
  const label = state.mode === 'replay' ? 'Recording replay' : labels[source?.status] || 'Loading recording';
  badge.replaceChildren(document.createElement('span'), document.createTextNode(label));
  badge.dataset.state = state.mode === 'replay' ? 'replay' : source?.status ?? 'loading';
  $('source-caption').textContent = currentFrame() ? `Captured ${dateUtc(currentFrame().time)} UTC` : 'The preview needs a local recording.';
}

async function refresh() {
  try {
    const response = await fetch('/api/preview', { cache: 'no-store' });
    if (!response.ok) throw new Error('Preview request failed');
    const data = await response.json();
    if (state.mode !== 'latest') return;
    state.data = data;
    state.index = Math.max(0, data.frames.length - 1);
    $('notice').hidden = true;
    render();
  } catch {
    $('notice').hidden = false;
    $('notice').textContent = 'The recording could not be refreshed. Showing any previously loaded frame. Check that the local server is running, then try Latest frame.';
    $('source-badge').replaceChildren(document.createElement('span'), document.createTextNode('Refresh unavailable'));
    $('source-badge').dataset.state = 'source_interrupted';
  }
}

function pause() { state.playing = false; window.clearTimeout(state.timer); state.timer = null; }
function scheduleNext() {
  if (!state.playing) return;
  const frames = state.data?.frames ?? [];
  if (state.index >= frames.length - 1) { pause(); render(); return; }
  const delay = Math.max(50, ((frames[state.index + 1].time - frames[state.index].time) * 1000) / Number($('playback-speed').value));
  state.timer = window.setTimeout(() => { state.index += 1; render(); scheduleNext(); }, delay);
}
function setTab(name, focus = false) {
  ['flight', 'evidence'].forEach((tab) => {
    const active = name === tab;
    $(`${tab}-panel`).hidden = !active;
    $(`${tab}-tab`).setAttribute('aria-selected', String(active));
    $(`${tab}-tab`).tabIndex = active ? 0 : -1;
  });
  if (focus) $(`${name}-tab`).focus();
}

$('aircraft-select').addEventListener('change', (event) => { if (event.target.value) selectAircraft(event.target.value); });
$('flight-search').addEventListener('input', (event) => {
  state.query = event.target.value.trim().toLowerCase();
  const match = visibleAircraft()[0];
  state.selected = match?.icao24 ?? null; state.selectedLabel = match?.callsign || match?.icao24 || '';
  render();
});
$('fit-region').addEventListener('click', () => map.fitRegion());
$('timeline').addEventListener('input', (event) => { pause(); state.mode = 'replay'; state.index = Number(event.target.value); render(); });
$('play-toggle').addEventListener('click', () => {
  if (state.playing) { pause(); render(); return; }
  state.mode = 'replay'; state.playing = true;
  if (state.index >= state.data.frames.length - 1) state.index = 0;
  render(); scheduleNext();
});
$('playback-speed').addEventListener('change', () => { if (state.playing) { window.clearTimeout(state.timer); scheduleNext(); } });
$('follow-latest').addEventListener('click', () => { pause(); state.mode = 'latest'; refresh(); });
$('flight-tab').addEventListener('click', () => setTab('flight'));
$('evidence-tab').addEventListener('click', () => setTab('evidence'));
document.querySelector('.primary-nav a[href="#evidence"]').addEventListener('click', () => setTab('evidence'));
document.querySelector('.primary-nav a[href="#workspace"]').addEventListener('click', () => setTab('flight'));
document.querySelector('.inspector-tabs').addEventListener('keydown', (event) => {
  if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); setTab(event.key === 'Home' ? 'flight' : event.key === 'End' ? 'evidence' : $('flight-tab').getAttribute('aria-selected') === 'true' ? 'evidence' : 'flight', true); }
});
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !event.target.closest('input, select, textarea, [contenteditable]')) { event.preventDefault(); $('flight-search').focus(); }
});
function updateClock() { $('wall-clock').textContent = `${utc(Date.now() / 1000)} UTC`; }
updateClock(); window.setInterval(updateClock, 1000);
window.setInterval(() => { if (state.mode === 'latest') refresh(); }, 15000);
refresh();
