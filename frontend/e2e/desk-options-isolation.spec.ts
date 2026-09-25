import {expect, test, type Locator, type Page, type TestInfo} from '@playwright/test'

const USER = 'options-fixture-viewer'
const SESSION = '2026-09-24'
const WRITTEN = '2026-09-24T21:05:00Z'
const NOW = '2026-09-25T15:35:00Z'
const BAR = '2026-09-25T15:15:00Z'
const STANCES = {fundamental: 1, technical: 1, sentiment: 1, value: 0, rotation: 0}
const VALID_WALLS = {
  expiry: '2026-10-16', through: '2026-11-20', fetched_at: '2026-09-25T13:05:00Z',
  put_wall: 95, call_wall: 105, put_wall_oi: 1200, call_wall_oi: 1800, net_gamma: 0,
  put_wall_distance: -.05, call_wall_distance: .05,
}
type OptionsState = 'unavailable' | 'available' | 'absent'

// Supply only synthetic read responses and refuse any provider request or persisted write.
async function installOptionsFixture(page: Page, frontendURL: string, state: OptionsState) {
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-25', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: null, closes_at: null}
  const latest = {
    session: SESSION, written: WRITTEN,
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAA: {grade: 'A+', votes: 3, stances: STANCES, ranks: {technical: .6}, score: .82, side: 'ai', headline: 'Synthetic recorded grade.', reason: 'Synthetic recorded evidence.'}},
    book: [], briefs: {}, paper: null,
  }
  const walls = state === 'available' ? VALID_WALLS : {status: 'unavailable', reason: 'options_data_unavailable'}
  const detail = {now: .8, short: {support_level: 90}, medium: {distance_50: .1}, long: {distance_high: -.1}, ...(state === 'absent' ? {} : {walls})}
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAA: {symbol: 'AAA', last: 100, open: 99, high: 101, low: 98, bar: BAR, as_of: NOW}}, technical: {AAA: {now: .8, close: .6}}, technical_detail: {AAA: detail}}
  const mine = {session: SESSION, market_status: market, grade_valid_until: {}, grades_live: {}, rows: [],
    decisions: {session: SESSION, written: WRITTEN, as_of: NOW, rows: {AAA: {action: 'Hold', strategy_action: 'Hold', executable: false, reason: 'Synthetic read-only fixture.', valid_until: null, target_weight: 0, current_weight: 0, move_weight: 0}}}}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  const reads: string[] = []
  const frontendOrigin = new URL(frontendURL).origin
  // Capture console failures independently of whether the expected content still renders.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A partially rendered panel cannot conceal a JavaScript exception.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Every required request must complete successfully.
  page.on('requestfailed', request => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  // Retain failed responses even when the component has a fallback.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(NOW)})
  // Keep rendering independent of the operator's stored appearance setting.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Fulfill each known API path locally; an unmatched path is a test failure.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === frontendOrigin) return route.continue()
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
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-26T00:00:00Z', is_admin: false, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = live
    else if (url.pathname === `${base}/session-prices`) json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {AAA: {price: null, at: null, feed: null, indicative: false, status: 'unavailable', reason: 'No optional session quote in this fixture.', valid_until: null}}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = mine
    else if (url.pathname === `${base}/intraday`) json = {session: SESSION, as_of: NOW, equity: 100000, rows: [], changed: [], top_buys: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/entries`) json = {user_id: USER, session: SESSION, rows: []}
    else if (url.pathname === `${base}/history/AAA`) json = {ticker: 'AAA', asof: SESSION, horizon: 20, backtest: null, rows: [], recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname === `${base}/earnings/AAA`) json = {user_id: USER, symbol: 'AAA', read: null}
    else if (url.pathname === `${base}/chart/AAA`) json = {user_id: USER, ticker: 'AAA', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'synthetic fixture', sessions: 0, bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname === `${base}/live/read/AAA`) json = {symbol: 'AAA', now: null, data_at: BAR, read_at: NOW, stale: false, read: 'Synthetic technical evidence remains available.', lines: {short: ['Daily support is $90.'], medium: ['Weekly trend evidence remains available.'], long: ['Longer-term reference evidence remains available.']}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    return route.fulfill({json})
  })
  return {diagnostics, reads, live}
}

// Disclose the full technical evidence through the same controls a dashboard reader uses.
async function openTechnicalEvidence(page: Page) {
  await page.getByRole('button', {name: 'AAA', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'AAA history'})
  const allEvidence = dialog.getByLabel('All the evidence', {exact: true})
  await allEvidence.locator(':scope > summary').click()
  await allEvidence.getByText('All readings, by timeframe', {exact: true}).click()
  return {dialog, allEvidence}
}

// Verify both wall locations without losing unrelated rank, price or technical content.
async function expectOptionsState(dialog: Locator, allEvidence: Locator, state: OptionsState) {
  const latest = dialog.getByRole('region', {name: 'Latest available grade', exact: true})
  await expect(latest).toContainText('$100.00')
  await expect(latest).toContainText('technical rank 80 of 100')
  await expect(allEvidence).toContainText('Technical rank at the available candle: 80 out of 100')
  await expect(allEvidence.getByText('Synthetic technical evidence remains available.', {exact: true})).toBeVisible()
  await expect(allEvidence.getByText('· Daily support is $90.', {exact: true})).toBeVisible()
  await expect(allEvidence.getByText('· Weekly trend evidence remains available.', {exact: true})).toBeVisible()
  await expect(allEvidence.getByText('· Longer-term reference evidence remains available.', {exact: true})).toBeVisible()
  if (state === 'available') {
    await expect(latest).toContainText('option walls $95.00 / $105.00')
    const wallLine = allEvidence.locator('p').filter({hasText: /^Option walls/})
    await expect(wallLine).toBeVisible()
    await expect(wallLine).toHaveText('Option walls (expiries 10-16 to 11-20, open interest fetched Sep 25, 09:05 AM ET ET): put $95.00(↓ -5.0% below) · call $105.00(↑ +5.0% above)')
  } else {
    await expect(latest).not.toContainText('option walls')
    await expect(allEvidence.locator('p').filter({hasText: /^Option walls/})).toHaveCount(0)
    await expect(dialog).not.toContainText('options_data_unavailable')
  }
}

// Preserve every browser diagnostic even when an earlier content assertion fails.
async function recordDiagnostics(testInfo: TestInfo, diagnostics: object, reads: string[]) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json'})
  await testInfo.attach('synthetic-api-reads', {body: JSON.stringify(reads, null, 2), contentType: 'application/json'})
  for (const [category, failures] of Object.entries(diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
}

for (const state of ['unavailable', 'available', 'absent'] as const) {
  // Optional chain state must survive re-fetch after reload without suppressing technical evidence.
  test(`preserves technical evidence with ${state} options before and after reload`, async ({page, baseURL}, testInfo) => {
    const {diagnostics, reads, live} = await installOptionsFixture(page, baseURL!, state)
    const original = JSON.stringify(live)
    try {
      await page.goto('/#desk')
      const initial = await openTechnicalEvidence(page)
      await expectOptionsState(initial.dialog, initial.allEvidence, state)
      await initial.dialog.screenshot({path: testInfo.outputPath(`${state}-options.png`)})
      await page.reload()
      const reloaded = await openTechnicalEvidence(page)
      await expectOptionsState(reloaded.dialog, reloaded.allEvidence, state)
      const base = `/api/v1/market/${USER}/desk`
      expect(reads.filter(path => path === `${base}/live`).length).toBeGreaterThanOrEqual(2)
      expect(reads.filter(path => path === `${base}/live/read/AAA`).length).toBeGreaterThanOrEqual(2)
      expect(JSON.stringify(live)).toBe(original)
    } finally {
      await recordDiagnostics(testInfo, diagnostics, reads)
    }
  })
}
