import {expect as baseExpect, test as base, type Page, type Request, type TestInfo} from '@playwright/test'

const expect = baseExpect.configure({timeout: 1000})

const OWNER = 'ani.mallya'
const DESK = `/api/v1/market/${OWNER}/desk`
const SESSION = '2026-09-24'
const INITIAL = '2026-09-24T22:00:00Z'
const UPDATED = '2026-09-24T22:01:01Z'
const WRITTEN = '2026-09-24T07:00:00Z'
const REGULAR_BAR = '2026-09-24T19:45:00Z'
const REGULAR_FAILURE = 'Regular-session data refresh failed; showing last known regular data.'

type Session = 'pre-market' | 'post-market' | 'overnight'
type Gate = {wait: Promise<void>; release: () => void}
type Reply = {gate?: Gate; body?: unknown; raw?: string; status?: number; abort?: boolean}
type Entry = {method: string; path: string; body?: Record<string, unknown>; held: boolean;
  completed: boolean; finished: boolean; returned?: unknown}
type Diagnostics = {consoleErrors: string[]; pageErrors: string[]; failedRequests: string[];
  badResponses: string[]; unexpectedRequests: string[]; forbiddenWrites: string[]}
type Scenario = {stamp: string; price: number; session: Session; reason: string; validForMs: number;
  requests: Entry[]; ledger: Map<Request, Entry>; lastNetworkChange: number;
  replies: Map<string, Reply[]>; gates: Gate[]; diagnostics: Diagnostics;
  expectedFailedRequests: string[]; expectedConsoleErrors: string[]; expectedBadResponses: string[]}

// Give every case its own response queue and strict browser/network mutation audit.
function scenario(): Scenario {
  return {stamp: INITIAL, price: 102, session: 'post-market', reason: 'Initial regular-session snapshot', validForMs: 60_000,
    requests: [], ledger: new Map(), lastNetworkChange: Date.now(), replies: new Map(), gates: [],
    diagnostics: {consoleErrors: [], pageErrors: [], failedRequests: [], badResponses: [], unexpectedRequests: [], forbiddenWrites: []},
    expectedFailedRequests: [], expectedConsoleErrors: [], expectedBadResponses: []}
}

// State only the regular exchange phase; this is not evidence that every trading venue is closed.
function market(state: Scenario) {
  return {exchange: 'XNYS', as_of: state.stamp, session: SESSION, calendar_known: true, is_session: true,
    open: false, phase: state.session, opens_at: `${SESSION}T09:30:00-04:00`, closes_at: `${SESSION}T16:00:00-04:00`}
}

// Keep display-only quotes distinct from the fixed regular-session candle and execution inputs.
function envelope(state: Scenario, price = state.price) {
  return {session: state.session, as_of: state.stamp, signal_scope: 'regular-session', quotes: {AAPL: {
    price, bid: price - .1, ask: price + .1, at: state.stamp, feed: state.session === 'overnight' ? 'overnight' : 'iex',
    indicative: state.session === 'overnight', status: 'fresh', reason: 'Quoted midpoint',
    valid_until: new Date(Date.parse(state.stamp) + state.validForMs).toISOString(),
  }}}
}

// Queue one controlled response without changing later requests at the same boundary.
function queue(state: Scenario, endpoint: string, reply: Reply) {
  state.replies.set(endpoint, [...(state.replies.get(endpoint) ?? []), reply])
}

// Hold one request until the test explicitly releases it, including after a failed assertion.
function hold(state: Scenario, endpoint: string, reply: Omit<Reply, 'gate'> = {}) {
  let release!: () => void
  const wait = new Promise<void>(resolve => {release = resolve})
  const gate = {wait, release}
  state.gates.push(gate)
  queue(state, endpoint, {...reply, gate})
  return gate
}

// Install read-only synthetic APIs and fail closed on real writes, external requests or unknown routes.
async function install(page: Page, state: Scenario, baseURL: string) {
  await page.clock.install({time: new Date(INITIAL)})
  await page.clock.pauseAt(new Date(INITIAL))
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (message.type() === 'error') state.diagnostics.consoleErrors.push(message.text())})
  // Track the current API batch rather than an already-achieved navigation load state.
  const complete = (request: Request) => {
    const entry = state.ledger.get(request)
    if (entry) {entry.finished = true; state.lastNetworkChange = Date.now()}
  }
  page.on('requestfinished', complete)
  page.on('requestfailed', request => {
    complete(request)
    state.diagnostics.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`)
  })
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // Capture response values before any gate so an older request cannot accidentally return newer fixture data.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== new URL(baseURL).origin) {
      state.diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const path = url.pathname
    const method = request.method()
    const body: Record<string, unknown> | undefined = method === 'POST' ? request.postDataJSON() : undefined
    const entry: Entry = {method, path, body, held: false, completed: false, finished: false}
    state.requests.push(entry)
    state.ledger.set(request, entry)
    state.lastNetworkChange = Date.now()
    const readingMine = method === 'POST' && path === `${DESK}/mine` && body?.record_history === false
      && Object.keys(body).every(key => ['equity', 'available_cash', 'risk_budget_pct', 'record_history'].includes(key))
    if (method !== 'GET' && !readingMine) {
      state.diagnostics.forbiddenWrites.push(`${method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Fixture refuses this mutation'}})
    }
    const endpoint = path.startsWith(DESK) ? path.slice(DESK.length) : path
    const reply = state.replies.get(endpoint)?.shift()
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: OWNER, is_admin: true, desk_access: true, desk_write: false}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: SESSION, written: WRITTEN, regime: {exposure: 1, flags: []},
      grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: [SESSION]}
    else if (endpoint === '/holdings') json = {holdings: []}
    else if (endpoint === '/live') json = {as_of: state.stamp, data_at: REGULAR_BAR, stale: false, reason: state.reason,
      market_status: market(state), quotes: {AAPL: {last: 100, open: 99, high: 101, low: 98, bar: REGULAR_BAR}}, technical: {}, technical_detail: {}}
    else if (endpoint === '/session-prices') json = envelope(state)
    else if (endpoint === '/live/read/AAPL') json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else if (endpoint === '/earnings/AAPL') json = {user_id: OWNER, symbol: 'AAPL', read: null}
    else if (readingMine) json = {session: SESSION, market_status: market(state), rows: [], grades_live: {},
      history_receipt: {status: 'not_requested'}, decisions: {session: SESSION, written: WRITTEN, rows: {AAPL: {
        action: 'Hold', strategy_action: 'Hold', move_weight: 0, executable: false, reason: 'Regular-session policy unchanged',
      }}}}
    else if (endpoint === '/history/AAPL') json = {ticker: 'AAPL', rows: [], backtest: null}
    else if (endpoint === '/chart/AAPL') json = {ticker: 'AAPL', timeframe: 'daily', adjusted: true, basis: 'adjusted prices',
      sessions: 2, quote_bar: REGULAR_BAR, bars: ['2026-09-23', SESSION].map(date => ({date, open: 99, high: 101, low: 98, close: 100, volume: 100})),
      overlays: {ema9: [99, 99]}, levels: {}, entries: [], data_status: 'complete'}
    else if (endpoint === '/entries' || endpoint === '/intraday') json = {session: SESSION, rows: [], top_buys: [], changed: []}
    else if (endpoint === '/paper') json = {reason: 'unavailable'}
    else {
      state.diagnostics.unexpectedRequests.push(`${method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    entry.returned = reply && 'body' in reply ? reply.body : json
    if (reply?.gate) {entry.held = true; await reply.gate.wait}
    if (reply?.abort) {
      state.expectedFailedRequests.push(`${method} ${request.url()} net::ERR_FAILED`)
      state.expectedConsoleErrors.push('Failed to load resource: net::ERR_FAILED')
      await route.abort('failed')
    } else {
      if (reply?.status && reply.status >= 400) {
        state.expectedBadResponses.push(`${reply.status} ${request.url()}`)
        state.expectedConsoleErrors.push(`Failed to load resource: the server responded with a status of ${reply.status} (Service Unavailable)`)
      }
      await route.fulfill(reply?.raw !== undefined
        ? {status: reply.status ?? 200, body: reply.raw, contentType: 'application/json'}
        : {status: reply?.status ?? 200, json: entry.returned})
    }
    entry.completed = true
  })
}

// Wait for all non-held requests to finish and for their batch to remain quiet before checking React state.
async function settle(page: Page, state: Scenario, ignoreHeld = false) {
  await expect.poll(() => state.requests.every(entry => entry.finished || ignoreHeld && entry.held && !entry.completed)
    && Date.now() - state.lastNetworkChange >= 150, {intervals: [50], timeout: 5000}).toBe(true)
  await page.clock.runFor(100)
}

// Preserve network outcomes and rendered evidence even when the primary regression assertion fails.
async function finish(page: Page, state: Scenario, info: TestInfo) {
  for (const gate of state.gates) gate.release()
  await settle(page, state)
  const readings = await page.getByLabel('AAPL session price', {exact: true}).allTextContents()
  await info.attach('independent-session-evidence', {body: JSON.stringify({requests: state.requests,
    diagnostics: state.diagnostics, readings}, null, 2), contentType: 'application/json'})
  for (const [category, failures] of Object.entries(state.diagnostics)) {
    const expected = category === 'failedRequests' ? state.expectedFailedRequests
      : category === 'consoleErrors' ? state.expectedConsoleErrors
      : category === 'badResponses' ? state.expectedBadResponses : []
    expect.soft(failures, `Browser ${category}`).toEqual(expected)
  }
}

const test = base.extend<{scenario: Scenario}>({
  // Ensure every case has isolated routes and unconditional diagnostics with no backend access.
  scenario: async ({page, baseURL}, use, info) => {
    const state = scenario()
    await install(page, state, baseURL!)
    try {await use(state)} finally {await finish(page, state, info)}
  },
})

// Reach the actual stock board and open chart only after the initial response batch settles.
async function openDesk(page: Page, state: Scenario) {
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('AAPL session price')).toContainText('$102.00')
  await settle(page, state)
  await openChart(page)
  await expect(page.getByRole('region', {name: 'AAPL price chart'}).getByLabel('AAPL session price')).toContainText('$102.00')
  await settle(page, state)
}

// Open the chart through its real stock-row interaction without assuming a particular quote value.
async function openChart(page: Page) {
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: 'AAPL', exact: true}).click()
  await expect(page.getByRole('region', {name: 'AAPL price chart'})).toBeVisible()
}

// Dismiss the chart before using background controls, matching an actual user's interaction path.
async function closeChart(page: Page) {
  await page.getByRole('dialog', {name: 'AAPL history'}).getByRole('button', {name: 'Close', exact: true}).click()
  await expect(page.getByRole('dialog', {name: 'AAPL history'})).toHaveCount(0)
}

// Refresh the desk through its accessible button, then reopen the independent chart display.
async function manualRefresh(page: Page) {
  await closeChart(page)
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await openChart(page)
}

// Assert the exact independent source/time, explicit midpoint meaning and unchanged signal price/action.
async function expectPrice(page: Page, state: Scenario, price = state.price, time = '6:00:00 PM') {
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  for (const surface of [board, chart]) {
    const reading = surface.getByLabel('AAPL session price')
    await expect.soft(reading).toContainText(`$${price.toFixed(2)}`)
    await expect.soft(reading).toContainText(`${state.session} · ${state.session === 'overnight' ? 'Indicative · OVERNIGHT' : 'IEX'} · ${time} ET`)
    await expect.soft(reading).not.toContainText('stale')
    await expect.soft(reading).toHaveAttribute('title', `Regular-session bar $100.00 · ${REGULAR_BAR}. Signal: regular session. Midpoint is not a trade or guaranteed fill. Reported quote timestamp: ${state.stamp}. Expected schedule: ${state.session}; not proof of venue availability. For display only; execution checks are separate.`)
  }
  await expect.soft(chart.getByLabel('AAPL session price')).toContainText('Price signals use regular-session candles.')
  await expect.soft(chart.locator('dl')).toContainText('$100.00')
  await expect.soft(chart.locator('dl')).not.toContainText(`$${price.toFixed(2)}`)
  await expect.soft(board.getByLabel('AAPL strategy intent', {exact: true})).toHaveText('Hold')
  await expect.soft(board.getByLabel('AAPL size', {exact: true})).toHaveText('—')
  await expect.soft(board.getByLabel('AAPL displayed grade')).toContainText('A')
}

// Identify the deliberately held completion triggered by a real manual refresh.
async function refreshHeld(page: Page, state: Scenario, endpoint: string) {
  const before = state.requests.length
  await manualRefresh(page)
  await expect.poll(() => state.requests.slice(before).some(entry => entry.path === `${DESK}${endpoint}` && entry.held)).toBe(true)
  return state.requests.slice(before).find(entry => entry.path === `${DESK}${endpoint}` && entry.held)!
}

// Periodic session prices must refresh while XNYS regular execution is closed, including on regular-feed failure.
for (const outcome of ['healthy', 'network failure', 'invalid JSON'] as const) {
  // Verify real 60-second polling updates both displays without changing candles or execution eligibility.
  test(`periodic fresh midpoint survives regular data ${outcome}`, async ({page, scenario: state}) => {
    await openDesk(page, state)
    await expectPrice(page, state)
    state.stamp = UPDATED
    state.price = 103
    if (outcome !== 'healthy') queue(state, '/live', outcome === 'network failure' ? {abort: true} : {raw: '{'})
    const before = state.requests.length
    await page.clock.fastForward(61_000)
    await expect.poll(() => state.requests.slice(before).some(entry => entry.path === `${DESK}/session-prices` && entry.completed)).toBe(true)
    await settle(page, state)
    await expectPrice(page, state, 103, '6:01:01 PM')
    if (outcome !== 'healthy') {
      await expect(page.getByRole('region', {name: 'Stocks and cash', exact: true})).toContainText(REGULAR_FAILURE)
      expect(state.diagnostics.failedRequests).toHaveLength(outcome === 'network failure' ? 1 : 0)
    }
  })
}

// A pending regular request must not withhold a successfully returned session quote.
test('fresh session midpoint renders before the held regular request completes', async ({page, scenario: state}) => {
  await openDesk(page, state)
  state.price = 103
  const gate = hold(state, '/live')
  const pending = await refreshHeld(page, state, '/live')
  await settle(page, state, true)
  expect(pending.completed).toBe(false)
  await expectPrice(page, state)
  gate.release()
  await settle(page, state)
  await expectPrice(page, state)
})

// Optional feed failure must invalidate an unexpired old price without withholding healthy regular data.
for (const outcome of ['network failure', 'invalid envelope', 'invalid JSON', 'HTTP failure'] as const) {
  // An unavailable optional quote is not a stale successful quote or a replacement regular signal.
  test(`optional ${outcome} clears the old midpoint on board and chart`, async ({page, scenario: state}) => {
    await openDesk(page, state)
    state.reason = 'Updated regular-session snapshot'
    queue(state, '/session-prices', outcome === 'network failure' ? {abort: true}
      : outcome === 'invalid envelope' ? {body: {}}
      : outcome === 'invalid JSON' ? {raw: '{'} : {status: 503, body: {detail: 'Unavailable'}})
    await manualRefresh(page)
    await settle(page, state)
    for (const reading of [page.getByRole('table', {name: 'Ranked stocks and cash'}).getByLabel('AAPL session price'),
      page.getByRole('region', {name: 'AAPL price chart'}).getByLabel('AAPL session price')]) {
      await expect.soft(reading).toContainText('No recent quote to display')
      await expect.soft(reading).not.toContainText('$102.00')
      await expect.soft(reading).not.toContainText('stale')
      await expect.soft(reading).toHaveAttribute('title', /Regular-session bar \$100\.00/)
    }
    await expect(page.getByRole('region', {name: 'Stocks and cash', exact: true})).toContainText(state.reason)
    const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
    await expect(board.getByLabel('AAPL strategy intent', {exact: true})).toHaveText('Hold')
    await expect(board.getByLabel('AAPL size', {exact: true})).toHaveText('—')
    await expect(page.getByRole('region', {name: 'AAPL price chart'}).locator('dl')).toContainText('$100.00')
  })
}

// Invalidating an optional quote must not wait for the separate regular-data response either.
test('optional failure removes the old midpoint before a held regular response completes', async ({page, scenario: state}) => {
  await openDesk(page, state)
  const gate = hold(state, '/live')
  queue(state, '/session-prices', {body: {}})
  const pending = await refreshHeld(page, state, '/live')
  await settle(page, state, true)
  expect(pending.completed).toBe(false)
  for (const surface of [page.getByRole('table', {name: 'Ranked stocks and cash'}), page.getByRole('region', {name: 'AAPL price chart'})]) {
    await expect.soft(surface.getByLabel('AAPL session price')).toContainText('No recent quote to display')
    await expect.soft(surface.getByLabel('AAPL session price')).not.toContainText('$102.00')
  }
  gate.release()
  await settle(page, state)
})

for (const abort of [false, true]) {
  // A later poll supersedes earlier optional success and failure completions in the same account context.
  test(`newer session quote survives obsolete same-context ${abort ? 'failure' : 'success'}`, async ({page, scenario: state}) => {
    await openDesk(page, state)
    const gate = hold(state, '/session-prices', {body: envelope(state, 101), abort})
    await refreshHeld(page, state, '/session-prices')
    await settle(page, state, true)
    state.price = 103
    const before = state.requests.length
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await expect.poll(() => state.requests.slice(before).some(entry => entry.path === `${DESK}/session-prices` && entry.completed)).toBe(true)
    await settle(page, state, true)
    await expectPrice(page, state)
    const afterNew = state.requests.length
    gate.release()
    await settle(page, state)
    await expectPrice(page, state)
    expect(state.requests.slice(afterNew).filter(entry => entry.path.startsWith(DESK)), 'Obsolete optional completion starts no further desk work').toEqual([])
  })

  // Applying account inputs invalidates an in-flight optional completion without any receipt or holdings write.
  test(`account Apply rejects an earlier session-price ${abort ? 'failure' : 'success'}`, async ({page, scenario: state}) => {
    await openDesk(page, state)
    const gate = hold(state, '/session-prices', {body: envelope(state, 101), abort})
    await refreshHeld(page, state, '/session-prices')
    await settle(page, state, true)
    state.price = 103
    const before = state.requests.length
    await closeChart(page)
    await page.getByLabel('Personal account equity', {exact: true}).fill('200000')
    await page.getByLabel('Personal available cash', {exact: true}).fill('5000')
    await page.getByLabel('Risk per position (%)', {exact: true}).fill('0.5')
    await page.getByRole('button', {name: 'Apply', exact: true}).click()
    await expect.poll(() => state.requests.slice(before).some(entry => entry.path === `${DESK}/mine`
      && entry.completed && entry.body?.equity === 200000 && entry.body?.available_cash === 5000 && entry.body?.risk_budget_pct === .5)).toBe(true)
    await openChart(page)
    await settle(page, state, true)
    await expectPrice(page, state)
    const afterNew = state.requests.length
    gate.release()
    await settle(page, state)
    await expectPrice(page, state)
    expect(state.requests.slice(afterNew).filter(entry => entry.path.startsWith(DESK)), 'Invalidated optional completion starts no later reads or writes').toEqual([])
    await expect(page.getByLabel('Personal account equity', {exact: true})).toHaveValue('200000')
    await expect(page.getByLabel('Personal available cash', {exact: true})).toHaveValue('5000')
    await expect(page.getByLabel('Risk per position (%)', {exact: true})).toHaveValue('0.5')
  })

  // An unmounted optional completion must not start later requests or leak its price into a newly mounted desk.
  test(`navigation discards a pending session-price ${abort ? 'failure' : 'success'}`, async ({page, scenario: state}) => {
    await openDesk(page, state)
    const gate = hold(state, '/session-prices', {body: envelope(state, 101), abort})
    await refreshHeld(page, state, '/session-prices')
    await settle(page, state, true)
    await closeChart(page)
    await page.getByRole('navigation', {name: 'Primary navigation'}).getByRole('button', {name: 'Conversations', exact: true}).click()
    await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).not.toBeVisible()
    const afterLeave = state.requests.length
    gate.release()
    await settle(page, state)
    expect(state.requests.slice(afterLeave).filter(entry => entry.path.startsWith(DESK)), 'Unmounted optional completion starts no later desk requests').toEqual([])
    await expect(page.getByLabel('AAPL session price', {exact: true})).toHaveCount(0)
    state.price = 102
    await openDesk(page, state)
    await expectPrice(page, state)
  })
}

for (const session of ['pre-market', 'overnight'] as const) {
  // The session/feed labels come from independent evidence, not from the regular-exchange closed flag.
  test(`${session} quote retains exact source time and midpoint qualification`, async ({page, scenario: state}) => {
    state.session = session
    state.stamp = session === 'pre-market' ? '2026-09-25T12:00:00Z' : '2026-09-25T01:00:00Z'
    await page.clock.setFixedTime(new Date(state.stamp))
    await openDesk(page, state)
    await expectPrice(page, state, 102, session === 'pre-market' ? '8:00:00 AM' : '9:00:00 PM')
  })
}

// Expired evidence must remain distinguishable from an absent or failed optional response.
test('expired midpoint becomes stale without changing the regular signal price', async ({page, scenario: state}) => {
  state.validForMs = 20_000
  await openDesk(page, state)
  await page.clock.fastForward(21_000)
  await settle(page, state)
  for (const surface of [page.getByRole('table', {name: 'Ranked stocks and cash'}), page.getByRole('region', {name: 'AAPL price chart'})]) {
    await expect(surface.getByLabel('AAPL session price')).toContainText('No recent quote to display · Last quote: 6:00:00 PM ET · post-market · IEX')
    await expect(surface.getByLabel('AAPL session price')).not.toContainText('$102.00')
    await expect(surface.getByLabel('AAPL session price')).not.toContainText('unavailable')
  }
  await expect(page.getByRole('region', {name: 'AAPL price chart'}).locator('dl')).toContainText('$100.00')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'}).getByLabel('AAPL strategy intent', {exact: true})).toHaveText('Hold')
})
