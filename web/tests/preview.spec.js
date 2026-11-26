import { test, expect } from '@playwright/test';

const start = 1795692000;
const plane = (id, at, extra = {}) => ({
  icao24: id, callsign: id === 'abc123' ? 'TEST ONE' : 'TEST TWO',
  registration_country: 'Hungary', longitude: 19 + (at - start) / 500,
  latitude: 47.2, time_position: at, position_age_seconds: 0, position_stale: false,
  last_contact: at, squawk: '1000', baro_altitude: 9000, velocity: 0,
  true_track: null, vertical_rate: null, geo_altitude: 9050, ...extra,
});
function fixture() {
  return {
    mode: 'recording', bbox: { lamin: 45.7, lomin: 16.1, lamax: 48.6, lomax: 22.9 }, airports: [],
    source: { status: 'saved_recording' },
    frames: [0, 15, 30].map((offset, index) => ({
      time: start + offset, completed_at: start + offset + 1, attempt_id: index + 1,
      aircraft: [plane('abc123', start + offset), plane('def456', start + offset, { latitude: 47.7 })],
    })),
    analysis: { available: true, as_of_time: start + 30, events: [{
      source_api_time: start + 30, event_time: start + 31, source_attempt_id: 3,
      alert_type: 'unusual_descent', icao24: 'abc123',
      physical_evidence: 'Synthetic evidence: descent rate -25 m/s.',
      limitations: ['Synthetic test candidate, not a verified incident.'],
    }] },
  };
}
async function open(page, data = fixture()) {
  await page.route('**/api/preview', (route) => route.fulfill({ json: data }));
  await page.route(/^https?:\/\/(?!127\.0\.0\.1(?::\d+)?\/)/, (route) => route.abort());
  await page.goto('/');
  await expect(page.locator('#source-badge')).not.toHaveText('Loading recording');
}

test('map worker loads, selection preserves zero and unavailable telemetry', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  await open(page);
  await expect(page.locator('#airspace-map')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('.aircraft-marker')).toHaveCount(2);
  await page.getByRole('button', { name: 'Select TEST TWO', exact: true }).click();
  await expect(page.locator('#selected-callsign')).toHaveText('TEST TWO');
  await expect(page.locator('#selected-speed')).toHaveText('0km/h');
  await expect(page.locator('#selected-vertical')).toHaveText('Unavailable');
  await expect(page.locator('#selected-track')).toHaveText('Unavailable');
  // A failed map worker previously left the canvas blank despite DOM markers.
  await page.waitForTimeout(1200);
  expect(errors).toEqual([]);
});

test('scrubbing hides future candidate evidence and supports playback controls', async ({ page }) => {
  await open(page);
  await expect(page.locator('#candidate-count')).toHaveText('1');
  await page.locator('#timeline').fill('0');
  await expect(page.locator('#source-badge')).toHaveText('Recording replay');
  await expect(page.locator('#candidate-count')).toHaveText('0');
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.locator('#evidence-list')).toContainText('No earlier candidates loaded');
  await page.locator('#playback-speed').selectOption('20');
  await page.getByRole('button', { name: 'Play recording', exact: true }).click();
  await expect(page.locator('#timeline')).toHaveValue('2');
  await expect(page.locator('#candidate-count')).toHaveText('1');
  await page.locator('.evidence-entry summary').click();
  await expect(page.locator('.candidate-body')).toContainText('Synthetic evidence');
  await page.getByRole('button', { name: 'Latest frame' }).click();
  await expect(page.locator('#source-badge')).toHaveText('Saved recording');
});

test('search, keyboard tabs and no-results recovery work', async ({ page }) => {
  await open(page);
  await page.keyboard.press('/');
  await expect(page.locator('#flight-search')).toBeFocused();
  await page.locator('#flight-search').fill('NO MATCH');
  await expect(page.locator('#map-empty')).toBeVisible();
  await expect(page.locator('#selected-altitude')).toHaveText('Unavailable');
  await page.locator('#flight-search').fill('');
  await expect(page.locator('#map-empty')).toBeHidden();
  await page.getByRole('tab', { name: 'Aircraft' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Evidence' })).toBeFocused();
  await page.getByText('About this preview', { exact: true }).click();
  await expect(page.getByText('A local view of recorded airspace.', { exact: true })).toBeVisible();
});

test('an empty recording never asserts normal traffic', async ({ page }) => {
  const data = fixture(); data.frames = []; data.source.status = 'no_recording';
  data.analysis = { available: false, events: [] };
  await open(page, data);
  await expect(page.locator('#source-badge')).toHaveText('No recording loaded');
  await expect(page.getByRole('button', { name: 'Play recording', exact: true })).toBeDisabled();
  await expect(page.locator('#selected-speed')).toHaveText('Unavailable');
});

test('a source failure has a visible recovery action', async ({ page }) => {
  await page.route('**/api/preview', (route) => route.fulfill({ status: 503 }));
  await page.goto('/');
  await expect(page.locator('#notice')).toContainText('Latest frame');
  await expect(page.locator('#source-badge')).toHaveText('Refresh unavailable');
});

for (const width of [320, 390, 768, 1440]) {
  test(`workspace has no horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator('#play-toggle')).toBeInViewport();
    await page.getByRole('button', { name: 'Fit Hungary', exact: true }).click();
  });
}
