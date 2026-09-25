import {expect as baseExpect, test as base, type Page, type Request, type TestInfo} from '@playwright/test'
import type {DeskSessionPrices} from '../src/services/api'

const expect = baseExpect.configure({timeout: 1000})
const OWNER = 'ani.mallya'
const DESK = `/api/v1/market/${OWNER}/desk`
const SESSION = '2026-09-24'
const OPENED = '2026-09-24T22:00:15Z'
const CAPTURED = '2026-09-24T22:00:00Z'
const OBSERVED = '2026-09-24T21:59:55Z'
const BAR = '2026-09-24T19:45:00Z'
type Snapshot = Omit<DeskSessionPrices, 'as_of'> & {as_of: string | null}
type Read = {snapshot: Snapshot; browserAt: string}
type Scenario = {snapshot: Snapshot; requests: {path: string; method: string; body?: unknown}[];
  reads: Read[]; pending: Set<Request>; changed: number; errors: string[]}

// Prepare already-collected evidence independently of every browser request and its clock.
function snapshot(captured: string | null = CAPTURED, observed = OBSERVED, price = 102): Snapshot {
  return {as_of: captured, session: 'post-market', signal_scope: 'regular-session', quotes: {AAPL: {
    at: observed, price, bid: price - .1, ask: price + .1, feed: 'iex', indicative: false,
    session: 'post-market', status: 'fresh', reason: 'Quoted midpoint',
    valid_until: new Date(Date.parse(observed) + 60_000).toISOString(),
  }}}
}

// Represent a completed failed collection rather than a failed browser HTTP request.
function unavailable(captured = '2026-09-24T22:00:25Z'): Snapshot {
  return {as_of: captured, session: 'post-market', signal_scope: 'regular-session', quotes: {AAPL: {
    at: null, price: null, feed: null, indicative: false, session: 'unknown', status: 'unavailable',
    reason: 'No fresh quote from available feeds', valid_until: null,
  }}}
}

// Start each case with an independent fixed snapshot and a complete read-only network audit.
function scenario(): Scenario {
  return {snapshot: snapshot(), requests: [], reads: [], pending: new Set(), changed: Date.now(), errors: []}
}

// Serve only synthetic APIs; the mutable snapshot models a contract, not a real collector or store.
async function install(page: Page, state: Scenario, baseURL: string) {
  await page.clock.install({time: new Date(OPENED)})
  await page.clock.pauseAt(new Date(OPENED))
  page.on('pageerror', error => state.errors.push(`page: ${error.message}`))
  page.on('console', message => {if (message.type() === 'error') state.errors.push(`console: ${message.text()}`)})
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) {state.pending.add(request); state.changed = Date.now()}
  })
  // Track consumed responses so assertions never race an earlier navigation's idle event.
  const finished = (request: Request) => {if (state.pending.delete(request)) state.changed = Date.now()}
  page.on('requestfinished', finished)
  page.on('requestfailed', request => {finished(request); state.errors.push(`failed: ${request.url()} ${request.failure()?.errorText}`)})
  page.on('response', response => {if (response.status() >= 400) state.errors.push(`HTTP ${response.status()}: ${response.url()}`)})
  // Deny unknown reads, real account writes and external access before supplying fixture data.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== new URL(baseURL).origin) {state.errors.push(`external: ${request.url()}`); return route.abort('blockedbyclient')}
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const path = url.pathname
    const method = request.method()
    const body: Record<string, unknown> | undefined = method === 'POST' ? request.postDataJSON() : undefined
    state.requests.push({path, method, body})
    const readingMine = method === 'POST' && path === `${DESK}/mine` && body?.record_history === false
      && Object.keys(body).every(key => ['equity', 'available_cash', 'risk_budget_pct', 'record_history'].includes(key))
    if (method !== 'GET' && !readingMine) {
      state.errors.push(`forbidden mutation: ${method} ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Read-only fixture'}})
    }
    const endpoint = path.startsWith(DESK) ? path.slice(DESK.length) : path
    const market = {exchange: 'XNYS', as_of: OPENED, session: SESSION, calendar_known: true,
      is_session: true, open: false, phase: 'post-market', opens_at: `${SESSION}T09:30:00-04:00`, closes_at: `${SESSION}T16:00:00-04:00`}
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: OWNER, is_admin: true, desk_access: true, desk_write: false}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: SESSION, written: `${SESSION}T07:00:00Z`, regime: {exposure: 1, flags: []},
      grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: [SESSION]}
    else if (endpoint === '/holdings') json = {holdings: []}
    else if (endpoint === '/live') json = {as_of: OPENED, data_at: BAR, market_status: market,
      quotes: {AAPL: {last: 100, open: 99, high: 101, low: 98, bar: BAR}}, technical: {}, technical_detail: {}}
    else if (endpoint === '/session-prices') {
      const saved = structuredClone(state.snapshot)
      state.reads.push({snapshot: saved, browserAt: await page.evaluate(() => new Date().toISOString())})
      json = saved
    } else if (readingMine) json = {session: SESSION, market_status: market, rows: [], grades_live: {},
      history_receipt: {status: 'not_requested'}, decisions: {session: SESSION, written: `${SESSION}T07:00:00Z`, rows: {AAPL: {
        action: 'Hold', strategy_action: 'Hold', move_weight: 0, executable: false, reason: 'Regular-session execution policy unchanged',
      }}}}
    else if (endpoint === '/history/AAPL') json = {ticker: 'AAPL', rows: [], backtest: null}
    else if (endpoint === '/live/read/AAPL') json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else if (endpoint === '/earnings/AAPL') json = {user_id: OWNER, symbol: 'AAPL', read: null}
    else if (endpoint === '/chart/AAPL') json = {ticker: 'AAPL', timeframe: 'daily', adjusted: true, basis: 'adjusted prices', sessions: 2,
      quote_bar: BAR, bars: ['2026-09-23', SESSION].map(date => ({date, open: 99, high: 101, low: 98, close: 100, volume: 100})),
      overlays: {ema9: [99, 99]}, levels: {}, entries: [], data_status: 'complete'}
    else if (endpoint === '/entries' || endpoint === '/intraday') json = {rows: [], top_buys: [], changed: []}
    else if (endpoint === '/paper') json = {reason: 'unavailable'}
    else {state.errors.push(`unexpected: ${method} ${path}`); return route.fulfill({status: 418, json: {detail: 'Unknown fixture path'}})}
    await route.fulfill({json})
  })
}

// Wait for the current API batch to finish and allow its rendered updates to settle.
async function settle(page: Page, state: Scenario) {
  await expect.poll(() => !state.pending.size && Date.now() - state.changed >= 150, {timeout: 5000, intervals: [50]}).toBe(true)
  await page.clock.runFor(100)
}

// Preserve every returned snapshot and reject all browser, network and mutation diagnostics.
async function finish(page: Page, state: Scenario, info: TestInfo) {
  await settle(page, state)
  await info.attach('background-session-contract-evidence', {body: JSON.stringify({requests: state.requests, reads: state.reads,
    errors: state.errors, readings: await page.getByLabel('AAPL session price', {exact: true}).allTextContents()}, null, 2), contentType: 'application/json'})
  expect(state.errors).toEqual([])
}

const test = base.extend<{scenario: Scenario}>({
  // Install isolated fixtures and check diagnostics even when a rendering assertion fails.
  scenario: async ({page, baseURL}, use, info) => {
    const state = scenario()
    await install(page, state, baseURL!)
    try {await use(state)} finally {await finish(page, state, info)}
  },
})

// Open the stock's real chart without assuming any particular quote succeeded.
async function openChart(page: Page, state: Scenario) {
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: 'AAPL', exact: true}).click()
  await expect(page.getByRole('region', {name: 'AAPL price chart'})).toBeVisible()
  await settle(page, state)
}

// Exercise first navigation or reload against whatever snapshot existed before opening the desk.
async function openDesk(page: Page, state: Scenario, reload = false) {
  const before = state.reads.length
  if (reload) await page.reload()
  else await page.goto('/#desk')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await settle(page, state)
  await expect.poll(() => state.reads.length).toBeGreaterThan(before)
  await openChart(page, state)
}

// Use the real Refresh control after closing its modal, then inspect the newly opened chart too.
async function refresh(page: Page, state: Scenario) {
  await page.getByRole('dialog', {name: 'AAPL history'}).getByRole('button', {name: 'Close', exact: true}).click()
  const before = state.reads.length
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect.poll(() => state.reads.length).toBeGreaterThan(before)
  await settle(page, state)
  await openChart(page, state)
}

// Keep quote display separate from the unchanged regular-session candle, intent and sizing.
async function expectBoundary(page: Page) {
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  await expect(board.getByLabel('AAPL strategy intent', {exact: true})).toHaveText('Hold')
  await expect(board.getByLabel('AAPL size', {exact: true})).toHaveText('—')
  await expect(board.getByLabel('AAPL displayed grade')).toContainText('A')
  await expect(chart.locator('dl')).toContainText('$100.00')
  await expect(chart.locator('dl')).not.toContainText('$102.00')
  await expect(chart.locator('dl')).not.toContainText('$103.75')
}

// Check both rendered midpoint locations against the original provider timestamp, never the serve time.
async function expectFresh(page: Page, observed = OBSERVED, price = '$102.00', time = '5:59:55 PM') {
  for (const reading of await page.getByLabel('AAPL session price', {exact: true}).all()) {
    await expect(reading).toContainText(`${price}`)
    await expect(reading).toContainText(`post-market · IEX · ${time} ET`)
    await expect(reading).not.toContainText('stale')
    await expect(reading).toHaveAttribute('title', `Regular-session bar $100.00 · ${BAR}. Signal: regular session. Midpoint is not a trade or guaranteed fill. Reported quote timestamp: ${observed}. Expected schedule: post-market; not proof of venue availability.`)
  }
  await expect(page.getByLabel('AAPL session price', {exact: true})).toHaveCount(2)
  await expectBoundary(page)
}

// Require absent current midpoints on board and chart while keeping the regular bar explicitly labelled.
async function expectAbsent(page: Page, text = 'No fresh quote from available feeds') {
  for (const reading of await page.getByLabel('AAPL session price', {exact: true}).all()) {
    await expect(reading).toContainText(text)
    await expect(reading).not.toContainText('$102.00')
    await expect(reading).not.toContainText('$103.75')
  }
  await expect(page.getByLabel('AAPL session price', {exact: true})).toHaveCount(2)
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'}).getByLabel('AAPL session price')).toContainText('Regular bar $100.00')
  await expectBoundary(page)
}

// A first-open response may predate the browser and must render its original source evidence.
test('first open renders a precollected snapshot without redating it', async ({page, scenario: state}) => {
  const saved = structuredClone(state.snapshot)
  await openDesk(page, state)
  await expectFresh(page)
  expect(state.reads.length).toBeGreaterThan(0)
  for (const read of state.reads) {
    expect(read.snapshot).toEqual(saved)
    expect(Date.parse(read.browserAt)).toBeGreaterThan(Date.parse(CAPTURED))
  }
})

// Repeated manual reads may serve the same saved snapshot but cannot move its source or capture timestamps.
test('repeated Refresh keeps original capture and source timestamps', async ({page, scenario: state}) => {
  await openDesk(page, state)
  for (const stamp of ['2026-09-24T22:00:25Z', '2026-09-24T22:00:40Z']) {
    await page.clock.setFixedTime(new Date(stamp))
    await refresh(page, state)
    await expectFresh(page)
  }
  expect(new Set(state.reads.map(read => read.snapshot.as_of))).toEqual(new Set([CAPTURED]))
  expect(new Set(state.reads.map(read => read.snapshot.quotes.AAPL.at))).toEqual(new Set([OBSERVED]))
  expect(new Set(state.reads.map(read => read.browserAt)).size).toBeGreaterThan(1)
})

// Local expiry must reject an unchanged saved fresh status before another quote request and after repeated old responses.
test('stopped collection expires locally and repeated old snapshots cannot revive the midpoint', async ({page, scenario: state}) => {
  await openDesk(page, state)
  await expectFresh(page)
  const reads = state.reads.length
  await page.clock.runFor(40_001)
  await expectAbsent(page, 'post-market quote stale · IEX · 5:59:55 PM ET')
  expect(state.reads).toHaveLength(reads)
  expect(state.snapshot.quotes.AAPL.status).toBe('fresh')
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await refresh(page, state)
    await expectAbsent(page, 'post-market quote stale · IEX · 5:59:55 PM ET')
  }
  for (const read of state.reads) {
    expect(read.snapshot.as_of).toBe(CAPTURED)
    expect(read.snapshot.quotes.AAPL.at).toBe(OBSERVED)
  }
})

// A successful HTTP read of a saved failure must remove the earlier quote before that quote would expire.
test('a failed persisted attempt clears a still-unexpired quote and survives reopening', async ({page, scenario: state}) => {
  await openDesk(page, state)
  await expectFresh(page)
  await page.clock.setFixedTime(new Date('2026-09-24T22:00:25Z'))
  state.snapshot = unavailable()
  await refresh(page, state)
  await expectAbsent(page)
  expect(await page.evaluate(() => Date.now())).toBeLessThan(Date.parse(OBSERVED) + 60_000)
  await openDesk(page, state, true)
  await expectAbsent(page)
  expect(state.reads.at(-1)?.snapshot).toEqual(unavailable())
})

// A later successful saved snapshot restores its new dated midpoint without reviving the earlier one.
test('a fresh later snapshot recovers from the saved unavailable attempt', async ({page, scenario: state}) => {
  state.snapshot = unavailable(CAPTURED)
  await openDesk(page, state)
  await expectAbsent(page)
  await page.clock.setFixedTime(new Date('2026-09-24T22:00:30Z'))
  state.snapshot = snapshot('2026-09-24T22:00:29Z', '2026-09-24T22:00:28Z', 103.75)
  await refresh(page, state)
  await expectFresh(page, '2026-09-24T22:00:28Z', '$103.75', '6:00:28 PM')
  await openDesk(page, state, true)
  await expectFresh(page, '2026-09-24T22:00:28Z', '$103.75', '6:00:28 PM')
  expect(state.reads.at(-1)?.snapshot).toEqual(state.snapshot)
})

// A recent capture of old provider evidence is not a current quote even if the stored row claims freshness.
test('a new collection timestamp cannot make old source evidence fresh', async ({page, scenario: state}) => {
  state.snapshot = snapshot('2026-09-24T22:00:10Z', '2026-09-24T21:59:00Z')
  await openDesk(page, state)
  await expectAbsent(page, 'post-market quote stale · IEX · 5:59:00 PM ET')
  await refresh(page, state)
  await expectAbsent(page, 'post-market quote stale · IEX · 5:59:00 PM ET')
})

// Missing collection evidence cannot authorize a midpoint even when a malformed row advertises a fresh price.
test('a null capture timestamp fails closed despite an otherwise fresh quote row', async ({page, scenario: state}) => {
  state.snapshot = snapshot(null)
  await openDesk(page, state)
  await expectAbsent(page)
})
