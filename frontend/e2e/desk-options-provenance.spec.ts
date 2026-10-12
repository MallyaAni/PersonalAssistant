import {expect, test, type Locator, type Page, type TestInfo} from '@playwright/test'

const USER = 'options-provenance-fixture'
const NOW = '2026-09-25T15:35:00Z'
const BAR = '2026-09-25T15:15:00Z'
const SESSION = '2026-09-24'
const LEGACY_WALLS = {expiry: '2026-09-18', through: '2026-10-16', fetched_at: '2026-09-01T13:05:00Z', put_wall: 95, call_wall: 105, put_wall_oi: 1200, call_wall_oi: 1800, net_gamma: 0, put_wall_distance: -.05, call_wall_distance: .05}
const COMMON = {checked_at: NOW, collected_at: '2026-09-01T13:05:00Z', collection_status: 'recorded', collection_age_seconds: 2082600, oi_effective_at: null, oi_freshness: 'unknown'}
const RECORDED = {...COMMON, status: 'recorded', calculation_version: 'raw-option-oi-levels/1', calculated_on: '2026-09-01', calculation_date_status: 'historical', reference_price: 100, reference_basis: 'raw_panel_close', reference_session: '2026-09-01', reference_bar_start: '2026-09-01T14:15:00Z', expiry: '2026-09-18', through: '2026-10-16', method: {min_days: 1, max_days: 60, strike_range_fraction: .25, min_open_interest: 500}, put_level: 95, call_level: 105, put_oi: 1200, call_oi: 1800, put_distance: -.05, call_distance: .05}
type Evidence = Record<string, unknown>

// Keep the current stock quote and the independently dated options record under fixture control.
async function installScenario(page: Page, frontendURL: string, evidence: Evidence | undefined) {
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-25', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: null, closes_at: null}
  const latest = {session: SESSION, written: '2026-09-24T21:05:00Z', regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []}, grades: {AAA: {grade: 'A', votes: 2, stances: {technical: 1, fundamental: 1}, ranks: {technical: .6}, score: .7, side: 'ai', headline: 'Synthetic recorded grade.', reason: 'Synthetic evidence.'}}, book: [], briefs: {}, paper: null}
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAA: {symbol: 'AAA', last: 150, open: 149, high: 151, low: 148, bar: BAR, as_of: NOW}}, technical: {AAA: {now: .8, close: .6}}, technical_detail: {AAA: {now: .8, short: {}, medium: {}, long: {}, walls: LEGACY_WALLS}}, ...(evidence ? {options_evidence: {AAA: evidence}} : {})}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  const reads: string[] = []
  // A successful content assertion cannot hide an error elsewhere on the page.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // Record exceptions even when React leaves part of the previous view visible.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // All required browser requests must finish.
  page.on('requestfailed', request => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  // Reject silent HTTP failures behind fallback content.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(NOW)})
  // Synthetic browser appearance must not depend on the operator's local preferences.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Intercept every API call and refuse external requests or writes before any transport occurs.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const base = `/api/v1/market/${USER}/desk`
    const preview = url.pathname === `${base}/mine` && request.method() === 'POST' && request.postDataJSON()?.record_history === false
    if (request.method() !== 'GET' && !preview) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids persistence'}})
    }
    reads.push(url.pathname)
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-28T00:00:00Z', is_admin: false, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = live
    else if (url.pathname === `${base}/session-prices`) json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {AAA: {price: null, at: null, feed: null, indicative: false, status: 'unavailable', reason: 'No optional quote in fixture.', valid_until: null}}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = {session: SESSION, market_status: market, grade_valid_until: {}, grades_live: {}, rows: [], decisions: {session: SESSION, written: latest.written, as_of: NOW, rows: {AAA: {action: 'Hold', strategy_action: 'Hold', executable: false, reason: 'Synthetic read-only fixture.', valid_until: null, target_weight: 0, current_weight: 0, move_weight: 0}}}}
    else if (url.pathname === `${base}/intraday`) json = {session: SESSION, as_of: NOW, equity: 100000, rows: [], changed: [], top_buys: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/entries`) json = {user_id: USER, session: SESSION, rows: []}
    else if (url.pathname === `${base}/history/AAA`) json = {ticker: 'AAA', asof: SESSION, horizon: 20, backtest: null, rows: [], recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname === `${base}/earnings/AAA`) json = {user_id: USER, symbol: 'AAA', read: null}
    else if (url.pathname === `${base}/chart/AAA`) json = {user_id: USER, ticker: 'AAA', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'synthetic fixture', sessions: 0, bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname === `${base}/live/read/AAA`) json = {symbol: 'AAA', now: null, data_at: BAR, read_at: NOW, stale: false, read: 'Synthetic technical evidence remains available.', lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    return route.fulfill({json})
  })
  return {live, reads, diagnostics}
}

// Preserve the actual old or new text before checking both existing options display locations.
async function openOptions(page: Page, testInfo: TestInfo) {
  await page.getByRole('button', {name: 'AAA', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'AAA history'})
  const latest = dialog.getByRole('region', {name: 'Latest available grade', exact: true})
  const technical = dialog.getByLabel('All the evidence', {exact: true})
  await technical.locator(':scope > summary').click()
  await expect(technical).toContainText('Synthetic technical evidence remains available.')
  await testInfo.attach('observed-options-content', {body: JSON.stringify({latest: await latest.innerText(), technical: await technical.innerText()}, null, 2), contentType: 'application/json'})
  const displays = [latest.getByLabel('Stored option OI levels', {exact: true}), technical.getByLabel('Stored option OI levels', {exact: true})]
  for (const display of displays) {
    await expect(display).toBeVisible()
    await display.locator(':scope > summary').click()
    await expect(display).toContainText('OI effective time: unknown. OI freshness: unknown.')
  }
  return {dialog, latest, technical, displays}
}

// Check both copies of the same provenance instead of sampling just the longer explanation.
async function expectBoth(displays: Locator[], text: string) {
  for (const display of displays) await expect(display).toContainText(text)
}

// Retain every error category even if content or interaction assertions fail first.
async function recordDiagnostics(testInfo: TestInfo, diagnostics: object, reads: string[]) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json'})
  await testInfo.attach('synthetic-api-reads', {body: JSON.stringify(reads, null, 2), contentType: 'application/json'})
  for (const [category, errors] of Object.entries(diagnostics)) expect.soft(errors, category).toEqual([])
}

// A fresh stock quote cannot make a collected chain or its historical calculation current.
test('separates a fresh stock quote from old collection and historical raw reference', async ({page, baseURL}, testInfo) => {
  const {diagnostics, reads} = await installScenario(page, baseURL!, {...RECORDED})
  try {
    await page.goto('/#desk')
    const {latest, displays} = await openOptions(page, testInfo)
    await expect(latest).toContainText('$150.00')
    await expectBoth(displays, 'Collected Sep 1, 2026, 09:05:00 AM ET')
    await expectBoth(displays, '24d 2h 30m 0s as of Sep 25, 2026, 11:35:00 AM ET')
    await expectBoth(displays, 'Expiry selection date: 2026-09-01')
    await expectBoth(displays, 'Calculation version: raw-option-oi-levels/1')
    await expectBoth(displays, 'Historical expiry selection; eligibility has not been rechecked for the current date.')
    await expectBoth(displays, 'Reference $100.00: raw panel close. Raw panel row date: 2026-09-01')
    await expectBoth(displays, 'Reference bar Sep 1, 2026, 10:15:00 AM ET (15-minute interval start)')
    await expectBoth(displays, '1–60 calendar days after 2026-09-01; same-day expiry excluded')
    await expectBoth(displays, 'within ±25% of the recorded reference')
    await expectBoth(displays, 'Select the largest summed put OI at or below the reference and the largest summed call OI at or above it; ties choose the strike nearest the reference')
    await expectBoth(displays, 'A selected strike must have at least 500 summed contracts on that side')
    await expectBoth(displays, 'Included expiry span: 2026-09-18 to 2026-10-16')
    await expectBoth(displays, 'Put $95.00 · 1,200 summed contracts · 5.0% below recorded reference')
    await expectBoth(displays, 'Call $105.00 · 1,800 summed contracts · 5.0% above recorded reference')
    await expectBoth(displays, 'These are not gamma exposure, dealer positioning, a buy/sell signal or guaranteed support/resistance.')
    for (const [index, display] of displays.entries()) {
      await expect(display.locator(':scope > summary')).toContainText('historical expiry selection; not rechecked for current date')
      await expect(display).not.toContainText('ET ET')
      await expect(display).not.toContainText(/↑|↓/)
      await display.screenshot({path: testInfo.outputPath(`historical-options-${index}.png`)})
    }
    await page.reload()
    await expectBoth((await openOptions(page, testInfo)).displays, 'Reference $100.00: raw panel close. Raw panel row date: 2026-09-01')
  } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
})

for (const [name, evidence, explanation] of [
  ['missing descriptor', undefined, 'Calculation provenance unavailable; stored levels withheld'],
  ['unverified calculation', {...COMMON, status: 'unverified', reason: 'legacy_calculation'}, 'Calculation provenance unavailable; stored levels withheld'],
  ['unavailable data', {...COMMON, status: 'unavailable', reason: 'options_data_unavailable'}, 'Stored options data unavailable'],
  ['absent diagnostic', {...COMMON, status: 'absent', reason: 'not_supplied'}, 'No stored options diagnostic supplied'],
] as const) {
  // Identical legacy levels must stay withheld when their supplied provenance cannot establish a calculation.
  test(`withholds legacy numeric levels for ${name}`, async ({page, baseURL}, testInfo) => {
    const {diagnostics, reads} = await installScenario(page, baseURL!, evidence)
    try {
      await page.goto('/#desk')
      const {displays} = await openOptions(page, testInfo)
      await expectBoth(displays, explanation)
      for (const display of displays) {
        await expect(display).not.toContainText('$95.00')
        await expect(display).not.toContainText('$105.00')
        await expect(display).not.toContainText('no qualifying level')
      }
    } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
  })
}

// Newly recorded provenance can qualify identical numeric levels while an unrecorded bar remains unavailable.
test('shows same-date selection with OI freshness unknown and reference bar unavailable', async ({page, baseURL}, testInfo) => {
  const {diagnostics, reads} = await installScenario(page, baseURL!, {...RECORDED, calculated_on: '2026-09-25', calculation_date_status: 'same_date', reference_session: '2026-09-25', reference_bar_start: null, expiry: '2026-10-16', through: '2026-11-20'})
  try {
    await page.goto('/#desk')
    const {displays} = await openOptions(page, testInfo)
    await expectBoth(displays, 'Expiry selection date: 2026-09-25')
    await expectBoth(displays, 'Put $95.00')
    await expectBoth(displays, 'Reference bar time unavailable; panel row date does not establish quote freshness')
    for (const display of displays) {
      await expect(display).not.toContainText('Historical expiry selection')
      await expect(display).not.toContainText('15-minute interval start')
      await expect(display).not.toContainText('OI freshness: fresh')
    }
  } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
})

// A row's date and an older bar timestamp remain distinct pieces of recorded evidence.
test('keeps a newer panel row date separate from its older source bar', async ({page, baseURL}, testInfo) => {
  const {diagnostics, reads} = await installScenario(page, baseURL!, {...RECORDED, calculated_on: '2026-09-25', calculation_date_status: 'same_date', reference_session: '2026-09-25', expiry: '2026-10-16', through: '2026-11-20'})
  try {
    await page.goto('/#desk')
    const {displays} = await openOptions(page, testInfo)
    await expectBoth(displays, 'Raw panel row date: 2026-09-25')
    await expectBoth(displays, 'Reference bar Sep 1, 2026, 10:15:00 AM ET (15-minute interval start)')
    for (const display of displays) await expect(display).not.toContainText('Reference bar Sep 25')
  } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
})

for (const [status, collected, explanation] of [
  ['missing', null, 'Collection time missing'],
  ['invalid', null, 'Collection time invalid'],
  ['future', '2026-09-26T13:05:00Z', 'Collection timestamp is after the evidence check'],
] as const) {
  // Invalid clock provenance cannot acquire a plausible age from the fresh stock candle.
  test(`makes a ${status} collection clock explicit`, async ({page, baseURL}, testInfo) => {
    const {diagnostics, reads} = await installScenario(page, baseURL!, {...RECORDED, collection_status: status, collected_at: collected, collection_age_seconds: null})
    try {
      await page.goto('/#desk')
      const {displays} = await openOptions(page, testInfo)
      await expectBoth(displays, explanation)
      await expectBoth(displays, 'Collection age unknown as of Sep 25, 2026, 11:35:00 AM ET')
      for (const display of displays) await expect(display).not.toContainText('Invalid Date')
    } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
  })
}

// Neutral distance words preserve a true zero instead of implying that a level must be above or below.
test('shows zero distance neutrally at the recorded reference', async ({page, baseURL}, testInfo) => {
  const {diagnostics, reads} = await installScenario(page, baseURL!, {...RECORDED, put_level: 100, call_level: 100, put_distance: 0, call_distance: 0})
  try {
    await page.goto('/#desk')
    const {displays} = await openOptions(page, testInfo)
    await expectBoth(displays, 'Put $100.00 · 1,200 summed contracts · at recorded reference (0.0%)')
    await expectBoth(displays, 'Call $100.00 · 1,800 summed contracts · at recorded reference (0.0%)')
    for (const display of displays) await expect(display).not.toContainText(/↑|↓|below recorded|above recorded/)
  } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
})

// A completed calculation with no qualifying level is evidence, distinct from data or provenance failure.
test('distinguishes no qualifying levels from unavailable data', async ({page, baseURL}, testInfo) => {
  const {diagnostics, reads} = await installScenario(page, baseURL!, {...RECORDED, put_level: null, call_level: null, put_oi: 0, call_oi: 0, put_distance: null, call_distance: null})
  try {
    await page.goto('/#desk')
    const {displays} = await openOptions(page, testInfo)
    await expectBoth(displays, 'Put: no qualifying level')
    await expectBoth(displays, 'Call: no qualifying level')
    await expectBoth(displays, 'Expiry selection date: 2026-09-01')
    for (const display of displays) await expect(display).not.toContainText('Stored options data unavailable')
  } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
})

// A malformed method number must not become a false scope claim in an otherwise readable record.
test('withholds an invalid method description without inventing numeric bounds', async ({page, baseURL}, testInfo) => {
  const {diagnostics, reads} = await installScenario(page, baseURL!, {...RECORDED, method: {...RECORDED.method, strike_range_fraction: null}})
  try {
    await page.goto('/#desk')
    const {displays} = await openOptions(page, testInfo)
    await expectBoth(displays, 'Method scope unavailable')
    for (const display of displays) await expect(display).not.toContainText('±0%')
  } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
})

// Clock passage and a later read may update collection age, never the old calculation's reference price.
test('keeps age pinned to checked_at until a refreshed response arrives', async ({page, baseURL}, testInfo) => {
  const evidence = {...RECORDED}
  const {live, diagnostics, reads} = await installScenario(page, baseURL!, evidence)
  try {
    await page.goto('/#desk')
    let opened = await openOptions(page, testInfo)
    await page.clock.fastForward(60_000)
    await expectBoth(opened.displays, '24d 2h 30m 0s as of Sep 25, 2026, 11:35:00 AM ET')
    evidence.checked_at = '2026-09-26T15:35:00Z'
    evidence.collection_age_seconds += 86400
    live.quotes.AAA.last = 180
    await page.clock.setSystemTime(new Date(evidence.checked_at))
    await page.reload()
    opened = await openOptions(page, testInfo)
    await expect(opened.latest).toContainText('$180.00')
    await expectBoth(opened.displays, '25d 2h 30m 0s as of Sep 26, 2026, 11:35:00 AM ET')
    await expectBoth(opened.displays, 'Reference $100.00: raw panel close. Raw panel row date: 2026-09-01')
    await expectBoth(opened.displays, '5.0% below recorded reference')
    expect(reads.filter(path => path.endsWith('/live')).length).toBeGreaterThanOrEqual(2)
  } finally {await recordDiagnostics(testInfo, diagnostics, reads)}
})
