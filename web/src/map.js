import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { icon, planeIcon, unknownTrackIcon } from './icons.js';

maplibregl.setWorkerUrl(workerUrl);

const empty = () => ({ type: 'FeatureCollection', features: [] });
const line = (coordinates, properties = {}) => ({ type: 'Feature', properties, geometry: { type: 'LineString', coordinates } });
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export class AirspaceMap {
  constructor(onSelect) {
    this.onSelect = onSelect;
    this.markers = new Map();
    this.loaded = false;
    this.scene = null;
    try {
      this.map = new maplibregl.Map({
        container: 'airspace-map', center: [19.3, 47.1], zoom: 6.1,
        minZoom: 5, maxZoom: 11, maxBounds: [[12, 42], [27, 53]],
        renderWorldCopies: false, pitchWithRotate: false, dragRotate: false,
        style: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#152b3b' } }] },
        attributionControl: false,
      });
      this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      this.map.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: 'Natural Earth · public domain' }), 'bottom-right');
      this.map.on('load', () => this.loadGeography());
      new ResizeObserver(() => this.map.resize()).observe(document.getElementById('map-viewport'));
    } catch {
      this.showError();
    }
  }

  showError() { document.getElementById('map-error').hidden = false; }

  async loadGeography() {
    try {
      const files = ['countries', 'lakes', 'rivers', 'cities'];
      const data = await Promise.all(files.map(async (name) => {
        const response = await fetch(`/map/${name}.geojson`);
        if (!response.ok) throw new Error('Map geography unavailable');
        return response.json();
      }));
      files.slice(0, 3).forEach((name, index) => this.map.addSource(name, { type: 'geojson', data: data[index] }));
      const graticule = [];
      for (let lon = 12; lon <= 27; lon += 1) graticule.push(line([[lon, 42], [lon, 53]]));
      for (let lat = 42; lat <= 53; lat += 1) graticule.push(line([[12, lat], [27, lat]]));
      this.map.addSource('graticule', { type: 'geojson', data: { type: 'FeatureCollection', features: graticule } });
      this.map.addLayer({ id: 'countries-fill', type: 'fill', source: 'countries', paint: { 'fill-color': ['case', ['==', ['get', 'code'], 'HUN'], '#244658', '#1c3445'] } });
      this.map.addLayer({ id: 'graticule-lines', type: 'line', source: 'graticule', paint: { 'line-color': '#3a5365', 'line-opacity': .3, 'line-width': .65 } });
      this.map.addLayer({ id: 'countries-outline', type: 'line', source: 'countries', paint: { 'line-color': '#526f80', 'line-width': .8, 'line-opacity': .7 } });
      this.map.addLayer({ id: 'hungary-outline', type: 'line', source: 'countries', filter: ['==', ['get', 'code'], 'HUN'], paint: { 'line-color': '#8bb5c6', 'line-width': 1.25 } });
      this.map.addLayer({ id: 'lake-water', type: 'fill', source: 'lakes', paint: { 'fill-color': '#507689', 'fill-opacity': .6 } });
      this.map.addLayer({ id: 'river-water', type: 'line', source: 'rivers', paint: { 'line-color': '#587f91', 'line-width': 1.2, 'line-opacity': .75 } });
      this.map.addSource('observation-bounds', { type: 'geojson', data: empty() });
      this.map.addLayer({ id: 'observation-edge', type: 'line', source: 'observation-bounds', paint: { 'line-color': '#7ba6b7', 'line-opacity': .45, 'line-width': .8, 'line-dasharray': [4, 5] } });
      this.map.addSource('flight-trails', { type: 'geojson', data: empty() });
      this.map.addLayer({ id: 'trails', type: 'line', source: 'flight-trails', paint: { 'line-color': '#82b9cf', 'line-width': 1, 'line-opacity': .32 } });
      this.map.addSource('selected-trail', { type: 'geojson', data: empty() });
      this.map.addLayer({ id: 'selected-trail-line', type: 'line', source: 'selected-trail', paint: { 'line-color': '#e5b664', 'line-width': 2.1, 'line-opacity': .95 } });
      const labelCodes = new Set(['HUN', 'AUT', 'SVK', 'ROU', 'SRB', 'HRV', 'SVN', 'UKR']);
      for (const feature of data[0].features) {
        const p = feature.properties;
        if (!labelCodes.has(p.code) || !Number.isFinite(p.label_lon) || !Number.isFinite(p.label_lat)) continue;
        const element = document.createElement('span');
        element.className = `country-label${p.code === 'HUN' ? ' is-hungary' : ''}`;
        element.textContent = p.name;
        new maplibregl.Marker({ element }).setLngLat([p.label_lon, p.label_lat]).addTo(this.map);
      }
      for (const feature of data[3].features) {
        const element = document.createElement('span');
        element.className = 'city-label';
        element.textContent = feature.properties.name;
        new maplibregl.Marker({ element, anchor: 'left', offset: [5, 0] }).setLngLat(feature.geometry.coordinates).addTo(this.map);
      }
      this.loaded = true;
      this.fitRegion(false);
      if (this.scene) this.update(...this.scene);
    } catch {
      this.showError();
    }
  }

  fitRegion(animate = true) {
    if (!this.map) return;
    const bbox = this.scene?.[3] ?? { lomin: 16.1, lamin: 45.7, lomax: 22.9, lamax: 48.6 };
    this.map.fitBounds([[bbox.lomin - .35, bbox.lamin - .25], [bbox.lomax + .35, bbox.lamax + .25]], { padding: { top: 65, bottom: 45, left: 30, right: 30 }, duration: animate && !reducedMotion ? 650 : 0 });
  }

  update(aircraft, trails, selectedId, bbox, airports = []) {
    this.scene = [aircraft, trails, selectedId, bbox, airports];
    if (!this.loaded) return;
    const visible = new Set(aircraft.map((plane) => plane.icao24));
    for (const [id, marker] of this.markers) {
      if (!visible.has(id)) { marker.remove(); this.markers.delete(id); }
    }
    for (const plane of aircraft) {
      let marker = this.markers.get(plane.icao24);
      if (!marker) {
        const element = document.createElement('button');
        element.type = 'button';
        element.addEventListener('click', (event) => { event.stopPropagation(); this.onSelect(plane.icao24); });
        marker = new maplibregl.Marker({ element, rotationAlignment: 'map' }).setLngLat([plane.longitude, plane.latitude]).addTo(this.map);
        this.markers.set(plane.icao24, marker);
      }
      const element = marker.getElement();
      element.className = `maplibregl-marker aircraft-marker${plane.baro_altitude === null ? ' altitude-unknown' : plane.baro_altitude < 9000 ? ' low' : ''}${plane.position_stale ? ' stale' : ''}${plane.icao24 === selectedId ? ' is-selected' : ''}`;
      element.innerHTML = plane.true_track === null ? unknownTrackIcon : planeIcon;
      element.setAttribute('aria-label', `Select ${plane.callsign || plane.icao24}`);
      element.setAttribute('aria-pressed', String(plane.icao24 === selectedId));
      element.title = `${plane.callsign || plane.icao24}${plane.baro_altitude === null ? ' — altitude unavailable' : ''}${plane.position_stale ? ' — stale position' : ''}`;
      marker.setLngLat([plane.longitude, plane.latitude]);
      marker.setRotation(plane.true_track === null ? 0 : plane.true_track);
    }
    const allTrails = [], selected = [];
    for (const [id, coordinates] of trails) {
      if (coordinates.length < 2 || !visible.has(id)) continue;
      const feature = line(coordinates, { icao24: id });
      (id === selectedId ? selected : allTrails).push(feature);
    }
    this.map.setPaintProperty('trails', 'line-opacity', window.matchMedia('(max-width: 780px)').matches ? .1 : .32);
    this.map.getSource('flight-trails').setData({ type: 'FeatureCollection', features: allTrails });
    this.map.getSource('selected-trail').setData({ type: 'FeatureCollection', features: selected });
    this.map.getSource('observation-bounds').setData({ type: 'FeatureCollection', features: [line([[bbox.lomin, bbox.lamin], [bbox.lomax, bbox.lamin], [bbox.lomax, bbox.lamax], [bbox.lomin, bbox.lamax], [bbox.lomin, bbox.lamin]])] });
    if (!this.airportsAdded) {
      airports.forEach((airport) => {
        const element = document.createElement('span');
        element.className = 'airport-label';
        element.innerHTML = icon('airport');
        element.append(document.createTextNode(airport.icao));
        new maplibregl.Marker({ element, anchor: 'left', offset: [5, 0] }).setLngLat([airport.longitude, airport.latitude]).addTo(this.map);
      });
      this.airportsAdded = true;
    }
    document.getElementById('airspace-map').dataset.ready = 'true';
  }
}
