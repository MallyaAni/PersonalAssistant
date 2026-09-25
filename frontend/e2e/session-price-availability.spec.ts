import {expect as baseExpect, test as base, type Page, type Request, type TestInfo} from '@playwright/test'

const expect = baseExpect.configure({timeout: 1000})
const DESK = '/api/v1/market/ani.mallya/desk'
const INITIAL = '2026-09-24T22:00:00Z'
const BAR = '2026-09-24T19:45:00Z'
type Session = 'pre-market' | 'post-market' | 'overnight' | 'regular' | 'closed' | 'unknown'
type Quote = {price: number | null; bid?: number; ask?: number; at: string | null; feed: string | null;
  indicative: boolean; status: 'fresh' | 'stale' | 'unavailable'; valid_until: string | null; reason: string; session?: Session}
type Scenario = {stamp: string; captured: string; schedule: Session; marketStamp: string; marketOpen: boolean;
  marketPhase: string; quote: Quote | null; malformedEnvelope: boolean; pending: Set<Request>; changed: number;
  requests: {path: string; method: string; body?: unknown}[]; errors: string[]}

// Supply fresh quote evidence with its own timestamp and observation schedule, independent of market status.
function quote(at = INITIAL, session: Session = 'post-market'): Quote {
  return {price: 102, bid: 101.9, ask: 102.1, at, feed: 'iex', indicative: false, status: 'fresh', session,
    valid_until: new Date(Date.parse(at) + 60_000).toISOString(), reason: 'Quoted midpoint'}
}

// Isolate each case's schedule, quote and complete read-only request audit.
function scenario(): Scenario {
  return {stamp: INITIAL, captured: INITIAL, schedule: 'post-market', marketStamp: INITIAL, marketOpen: false,
    marketPhase: 'post-market', quote: quote(), malformedEnvelope: false, pending: new Set(), changed: Date.now(), requests: [], errors: []}
}

// Route only documented fixture reads and reject all external requests or persistence operations.
async function install(page: Page, state: Scenario, baseURL: string) {
  await page.clock.install({time: new Date(INITIAL)})
  await page.clock.pauseAt(new Date(INITIAL))
  page.on('pageerror', error => state.errors.push(`page: ${error.message}`))
  page.on('console', message => {if (message.type() === 'error') state.errors.push(`console: ${message.text()}`)})
  page.on('request', request => {if (new URL(request.url()).pathname.startsWith('/api/')) {state.pending.add(request); state.changed = Date.now()}})
  // Track this request batch through completion, not a previous navigation's network-idle event.
  const finished = (request: Request) => {if (state.pending.delete(request)) state.changed = Date.now()}
  page.on('requestfinished', finished)
  page.on('requestfailed', request => {finished(request); state.errors.push(`failed: ${request.url()} ${request.failure()?.errorText}`)})
  page.on('response', response => {if (response.status() >= 400) state.errors.push(`HTTP ${response.status()}: ${response.url()}`)})
  // Keep account reads non-recording and fail closed on unrecognized API paths.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== new URL(baseURL).origin) {state.errors.push(`external: ${request.url()}`); return route.abort('blockedbyclient')}
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const path = url.pathname
    const method = request.method()
    const body = method === 'POST' ? request.postDataJSON() : undefined
    state.requests.push({path, method, body})
    if (method !== 'GET' && !(method === 'POST' && path === `${DESK}/mine` && body?.record_history === false)) {
      state.errors.push(`forbidden mutation: ${method} ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Read-only fixture'}})
    }
    const endpoint = path.startsWith(DESK) ? path.slice(DESK.length) : path
    const market = {exchange: 'XNYS', as_of: state.marketStamp, session: '2026-09-24', calendar_known: true,
      is_session: true, open: state.marketOpen, phase: state.marketPhase, opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_access: true, desk_write: false}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: '2026-09-24', written: '2026-09-24T07:00:00Z', regime: {exposure: 1, flags: []},
      grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: ['2026-09-24']}
    else if (endpoint === '/holdings') json = {holdings: []}
    else if (endpoint === '/live') json = {as_of: state.marketStamp, data_at: BAR, market_status: market,
      quotes: {AAPL: {last: 100, open: 99, high: 101, low: 98, bar: BAR}}, technical: {}, technical_detail: {}}
    else if (endpoint === '/session-prices') json = state.malformedEnvelope ? {} : {session: state.schedule, as_of: state.captured,
      signal_scope: 'regular-session', quotes: state.quote ? {AAPL: state.quote} : {}}
    else if (endpoint === '/mine') json = {session: '2026-09-24', market_status: market, rows: [], grades_live: {},
      history_receipt: {status: 'not_requested'}, decisions: {session: '2026-09-24', written: '2026-09-24T07:00:00Z', rows: {AAPL: {
        action: 'Hold', strategy_action: 'Hold', move_weight: 0, executable: false, reason: 'Regular-session execution policy unchanged',
      }}}}
    else if (endpoint === '/history/AAPL') json = {ticker: 'AAPL', rows: [], backtest: null}
    else if (endpoint === '/live/read/AAPL') json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else if (endpoint === '/earnings/AAPL') json = {user_id: 'ani.mallya', symbol: 'AAPL', read: null}
    else if (endpoint === '/chart/AAPL') json = {ticker: 'AAPL', timeframe: 'daily', adjusted: true, basis: 'adjusted prices', sessions: 2,
      quote_bar: BAR, bars: ['2026-09-23', '2026-09-24'].map(date => ({date, open: 99, high: 101, low: 98, close: 100, volume: 100})),
      overlays: {ema9: [99, 99]}, levels: {}, entries: [], data_status: 'complete'}
    else if (endpoint === '/entries' || endpoint === '/intraday') json = {rows: [], top_buys: [], changed: []}
    else if (endpoint === '/paper') json = {reason: 'unavailable'}
    else {state.errors.push(`unexpected: ${method} ${path}`); return route.fulfill({status: 418, json: {detail: 'Unknown fixture path'}})}
    await route.fulfill({json})
  })
}

// Await consumed API responses and a stable batch before inspecting rendered state.
async function settle(page: Page, state: Scenario) {
  await expect.poll(() => !state.pending.size && Date.now() - state.changed >= 150, {timeout: 5000, intervals: [50]}).toBe(true)
  await page.clock.runFor(100)
}

// Retain the read ledger and exact quote wording, and reject all browser or network errors.
async function finish(page: Page, state: Scenario, info: TestInfo) {
  await settle(page, state)
  await info.attach('session-availability-evidence', {body: JSON.stringify({requests: state.requests, errors: state.errors,
    readings: await page.getByLabel('AAPL session price', {exact: true}).allTextContents()}, null, 2), contentType: 'application/json'})
  expect(state.errors).toEqual([])
}

const test = base.extend<{scenario: Scenario}>({
  // Install isolated routes and unconditional evidence checks for every availability case.
  scenario: async ({page, baseURL}, use, info) => {
    const state = scenario()
    await install(page, state, baseURL!)
    try {await use(state)} finally {await finish(page, state, info)}
  },
})

// Open the real board and ticker chart without assuming that the quote already rendered correctly.
async function openDesk(page: Page, state: Scenario) {
  await page.clock.setFixedTime(new Date(state.stamp))
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board).toBeVisible()
  await settle(page, state)
  await board.getByRole('button', {name: 'AAPL', exact: true}).click()
  await expect(page.getByRole('region', {name: 'AAPL price chart'})).toBeVisible()
  await settle(page, state)
}

// Check both independently rendered quotes and the unchanged regular-session execution/candle boundary.
async function expectReading(page: Page, text: string, price = true) {
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  for (const surface of [board, chart]) {
    const reading = surface.getByLabel('AAPL session price')
    await expect.soft(reading).toContainText(text)
    if (price) await expect.soft(reading).toContainText('$102.00')
    else await expect.soft(reading).not.toContainText('$102.00')
    await expect.soft(reading).toHaveAttribute('title', /Midpoint is not a trade or guaranteed fill/)
  }
  await expect(board.getByLabel('AAPL strategy intent', {exact: true})).toHaveText('Hold')
  await expect(board.getByLabel('AAPL size', {exact: true})).toHaveText('—')
  await expect(chart.locator('dl')).toContainText('$100.00')
  await expect(chart.locator('dl')).not.toContainText('$102.00')
}

// A same-schedule fresh quote is the baseline control for the broader availability checks.
test('current postmarket midpoint retains its exact source and observation time', async ({page, scenario: state}) => {
  await openDesk(page, state)
  await expectReading(page, 'post-market · IEX · 6:00:00 PM ET')
})

// A stale open-status snapshot is not authority to suppress a newer independent quote.
test('newer independent quote survives stale regular-session open status', async ({page, scenario: state}) => {
  state.marketOpen = true
  state.marketPhase = 'open'
  state.marketStamp = '2026-09-24T19:00:00Z'
  await openDesk(page, state)
  await expectReading(page, 'post-market · IEX · 6:00:00 PM ET')
})

// Fresh session-price evidence is displayable during regular hours without enabling execution.
test('regular schedule does not suppress its fresh display-only midpoint', async ({page, scenario: state}) => {
  state.stamp = state.captured = state.marketStamp = '2026-09-25T14:00:00Z'
  state.schedule = 'regular'
  state.marketOpen = true
  state.marketPhase = 'open'
  state.quote = quote(state.stamp, 'regular')
  await openDesk(page, state)
  await expectReading(page, 'regular · IEX · 10:00:00 AM ET')
})

for (const schedule of ['closed', 'unknown'] as const) {
  // A schedule classification is context, not proof that available feeds have no fresh quote.
  test(`${schedule} schedule retains fresh independent evidence without claiming venue closure`, async ({page, scenario: state}) => {
    state.schedule = schedule
    state.marketPhase = schedule
    state.quote = quote(INITIAL, schedule)
    await openDesk(page, state)
    await expectReading(page, 'Quote · IEX · 6:00:00 PM ET')
    const reading = page.getByRole('table', {name: 'Ranked stocks and cash'}).getByLabel('AAPL session price')
    await expect(reading).not.toContainText('closed')
    await expect(reading).toHaveAttribute('title', /Expected schedule.*not.*venue/i)
  })
}

for (const legacy of [false, true]) {
  // Fresh evidence crossing the open retains the actual premarket observation rather than being relabelled regular.
  test(`${legacy ? 'legacy' : 'dated'} premarket observation remains qualified across the regular open`, async ({page, scenario: state}) => {
    state.stamp = state.marketStamp = '2026-09-25T13:30:10Z'
    state.captured = legacy ? '2026-09-25T13:29:50Z' : state.stamp
    state.schedule = legacy ? 'pre-market' : 'regular'
    state.marketOpen = true
    state.marketPhase = 'open'
    state.quote = quote('2026-09-25T13:29:45Z', 'pre-market')
    if (legacy) delete state.quote.session
    await openDesk(page, state)
    await expectReading(page, 'pre-market · IEX · 9:29:45 AM ET')
    for (const reading of await page.getByLabel('AAPL session price', {exact: true}).all()) {
      await expect(reading).toContainText('previous-session observation')
      await expect(reading).not.toContainText('regular · IEX')
      await expect(reading).not.toContainText('9:30:10 AM')
      await expect(reading).toHaveAttribute('title', /2026-09-25T13:29:45Z/)
    }
  })
}

// A legacy regular envelope cannot establish which schedule contained its earlier quote timestamp.
test('legacy regular envelope leaves the quote session unrecorded', async ({page, scenario: state}) => {
  state.stamp = state.captured = state.marketStamp = '2026-09-25T13:30:10Z'
  state.schedule = 'regular'
  state.marketOpen = true
  state.marketPhase = 'open'
  state.quote = quote('2026-09-25T13:29:45Z')
  delete state.quote.session
  await openDesk(page, state)
  await expectReading(page, 'Quote · IEX · 9:29:45 AM ET')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'}).getByLabel('AAPL session price')).toContainText('session unrecorded')
})

for (const failure of ['missing', 'invalid envelope', 'future timestamp', 'missing feed', 'invalid price'] as const) {
  // Missing or invalid evidence is unavailable rather than proof that trading venues are closed.
  test(`${failure} reports no fresh feed quote and labels the regular-bar fallback`, async ({page, scenario: state}) => {
    if (failure === 'missing') state.quote = null
    else if (failure === 'invalid envelope') state.malformedEnvelope = true
    else if (failure === 'future timestamp') state.quote!.at = '2026-09-24T22:00:01Z'
    else if (failure === 'missing feed') state.quote!.feed = null
    else state.quote!.price = -1
    await openDesk(page, state)
    await expectReading(page, 'No fresh quote from available feeds', false)
    const reading = page.getByRole('table', {name: 'Ranked stocks and cash'}).getByLabel('AAPL session price')
    await expect(reading).toContainText('Regular bar $100.00')
    await expect(reading).not.toContainText('market closed')
  })
}

for (const oldDay of [false, true]) {
  // Stale evidence retains the original source and a visible date when a time alone could imply today.
  test(`${oldDay ? 'previous-day' : 'same-day'} stale evidence retains dated source without a current price`, async ({page, scenario: state}) => {
    state.quote = {...quote(oldDay ? '2026-09-23T22:00:00Z' : '2026-09-24T21:58:00Z'), price: null, status: 'stale', valid_until: null}
    await openDesk(page, state)
    await expectReading(page, oldDay ? 'post-market quote stale · IEX · Sep 23, 6:00:00 PM ET' : 'post-market quote stale · IEX · 5:58:00 PM ET', false)
    await expect(page.getByRole('table', {name: 'Ranked stocks and cash'}).getByLabel('AAPL session price')).toHaveAttribute('title', new RegExp(state.quote.at!))
  })
}

// The header distinguishes completed regular bars from how often independent quote evidence is checked.
test('bar cadence wording is separate from session-quote polling', async ({page, scenario: state}) => {
  await openDesk(page, state)
  const board = page.getByRole('region', {name: 'Stocks and cash', exact: true})
  await expect(board).toContainText('Regular-session bar')
  await expect(board).toContainText('completed 15-minute bars')
  await expect(board).toContainText('session quotes checked every minute')
  await expect(board).not.toContainText('updates every 15 minutes while the market is open')
})

// An unknown current schedule cannot establish a phase change from a known quote observation.
test('unknown current schedule does not claim a previous-session observation', async ({page, scenario: state}) => {
  state.stamp = state.captured = state.marketStamp = '2026-09-25T14:00:00Z'
  state.schedule = 'unknown'
  state.marketPhase = 'unknown'
  state.quote = quote(state.stamp, 'regular')
  await openDesk(page, state)
  await expectReading(page, 'regular · IEX · 10:00:00 AM ET')
  for (const reading of await page.getByLabel('AAPL session price', {exact: true}).all()) {
    await expect.soft(reading).not.toContainText('previous-session observation')
    await expect(reading).toHaveAttribute('title', /Expected schedule: unknown/)
  }
})

for (const earlyMorning of [false, true]) {
  // XNYS pre/post labels cover overnight hours too and cannot establish a change in the finer quote schedule.
  test(`newer XNYS ${earlyMorning ? 'pre-market' : 'post-market'} status does not mislabel current overnight evidence`, async ({page, scenario: state}) => {
    state.captured = earlyMorning ? '2026-09-25T07:00:00Z' : '2026-09-25T01:00:00Z'
    state.stamp = state.marketStamp = earlyMorning ? '2026-09-25T07:00:01Z' : '2026-09-25T01:00:01Z'
    state.schedule = 'overnight'
    state.marketPhase = earlyMorning ? 'pre-market' : 'post-market'
    state.quote = {...quote(state.captured, 'overnight'), feed: 'overnight', indicative: true}
    await openDesk(page, state)
    await expectReading(page, `overnight · Indicative · OVERNIGHT · ${earlyMorning ? '3:00:00 AM' : '9:00:00 PM'} ET`)
    for (const reading of await page.getByLabel('AAPL session price', {exact: true}).all()) {
      await expect.soft(reading).not.toContainText('previous-session observation')
      await expect.soft(reading).toHaveAttribute('title', /Expected schedule: overnight/)
    }
  })
}
