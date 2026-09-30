import {expect, test as base, type Page, type Request, type TestInfo} from '@playwright/test'

const OWNER = 'ani.mallya'
const DESK = `/api/v1/market/${OWNER}/desk`
const SESSION = '2026-09-24'
const NOW = '2026-09-24T14:00:00Z'
const WRITTEN = '2026-09-24T00:00:00Z'
const LIVE_FAILURE = 'Regular-session data refresh failed; showing last known regular data.'

type Gate = {wait: Promise<void>; release: () => void}
type Reply = {gate?: Gate; body?: unknown; abort?: boolean}
type Entry = {method: string; path: string; body?: unknown; held: boolean; completed: boolean; finished: boolean; aborted: boolean}
type Diagnostics = {consoleErrors: string[]; pageErrors: string[]; failedRequests: string[];
  badResponses: string[]; unexpectedRequests: string[]; forbiddenWrites: string[]}
type Scenario = {live: ReturnType<typeof liveSnapshot>; replies: Map<string, Reply[]>; requests: Entry[];
  gates: Gate[]; diagnostics: Diagnostics; expectedFailedRequests: string[]; expectedConsoleErrors: string[]}

// Keep the exchange open and its clock independent of the receipt or request completion time.
function market() {
  return {exchange: 'XNYS', as_of: NOW, session: SESSION, calendar_known: true, is_session: true,
    open: true, phase: 'open', opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
}

// Give each response a visible price and source description that reveals an obsolete overwrite.
function liveSnapshot(price: number, reason: string) {
  return {as_of: NOW, data_at: '2026-09-24T13:45:00Z', stale: false, reason,
    quotes: {AAPL: {last: price, bar: '2026-09-24T13:45:00Z'}}, technical: {}, technical_detail: {}, market_status: market()}
}

// Prepare one isolated response queue and a complete browser/request/write audit for each case.
function scenario(): Scenario {
  return {live: liveSnapshot(110, 'Initial synthetic market snapshot'), replies: new Map(), requests: [], gates: [],
    expectedFailedRequests: [], expectedConsoleErrors: [],
    diagnostics: {consoleErrors: [], pageErrors: [], failedRequests: [], badResponses: [], unexpectedRequests: [], forbiddenWrites: []}}
}

// Hold only the next named API boundary so the test can choose its completion order.
function hold(state: Scenario, endpoint: string, reply: Omit<Reply, 'gate'> = {}) {
  let release!: () => void
  const wait = new Promise<void>(resolve => {release = resolve})
  const gate = {wait, release}
  state.gates.push(gate)
  state.replies.set(endpoint, [...(state.replies.get(endpoint) ?? []), {...reply, gate}])
  return gate
}

// Restrict the browser to fixture reads; every write is refused and recorded.
async function install(page: Page, state: Scenario, baseURL: string) {
  const ledger = new Map<Request, Entry>()
  await page.clock.install({time: new Date('2026-09-24T13:59:59Z')})
  await page.clock.pauseAt(new Date(NOW))
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (message.type() === 'error') state.diagnostics.consoleErrors.push(message.text())})
  page.on('requestfinished', request => {const entry = ledger.get(request); if (entry) entry.finished = true})
  page.on('requestfailed', request => {
    const entry = ledger.get(request)
    if (entry) entry.finished = true
    state.diagnostics.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`)
  })
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // Reject unknown paths and real mutations before responding to any application request.
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
    const body = method === 'POST' ? request.postDataJSON() : undefined
    const entry: Entry = {method, path, body, held: false, completed: false, finished: false, aborted: false}
    ledger.set(request, entry)
    state.requests.push(entry)
    if (method !== 'GET') {
      state.diagnostics.forbiddenWrites.push(`${method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Fixture refuses this mutation'}})
    }
    let json: unknown
    const endpoint = path.startsWith(DESK) ? path.slice(DESK.length) : path
    const reply = state.replies.get(endpoint)?.shift()
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: OWNER,
      is_admin: true, desk_access: true, desk_write: true}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: SESSION, written: WRITTEN,
      regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}},
      book: [], actions: [], briefs: {}}, sessions: [SESSION]}
    else if (endpoint === '/holdings') json = {holdings: [{ticker: 'AAPL', shares: 10, entry_price: 100, entry_date: '2026-08-28'}]}
    else if (endpoint === '/live') json = state.live
    else if (endpoint === '/session-prices') json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {}}
    else if (endpoint === '/paper') json = {reason: 'unavailable'}
    else {
      state.diagnostics.unexpectedRequests.push(`${method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    if (reply?.gate) {entry.held = true; await reply.gate.wait}
    if (reply?.abort) {
      entry.aborted = true
      state.expectedFailedRequests.push(`${method} ${request.url()} net::ERR_FAILED`)
      state.expectedConsoleErrors.push('Failed to load resource: net::ERR_FAILED')
      await route.abort('failed')
    } else await route.fulfill({json: reply?.body ?? json})
    entry.completed = true
  })
}

// Preserve all diagnostics and request provenance even if a primary race assertion fails.
async function finish(state: Scenario, info: TestInfo) {
  for (const gate of state.gates) gate.release()
  await expect.soft.poll(() => state.requests.filter(entry => !entry.completed).length).toBe(0)
  await info.attach('poll-context-evidence', {body: JSON.stringify(state, (_key, value) => value instanceof Map ? Object.fromEntries(value) : value, 2), contentType: 'application/json'})
  for (const [category, failures] of Object.entries(state.diagnostics)) {
    const expected = category === 'failedRequests' ? state.expectedFailedRequests : category === 'consoleErrors' ? state.expectedConsoleErrors : []
    expect.soft(failures, `Browser ${category}`).toEqual(expected)
  }
}

const test = base.extend<{scenario: Scenario}>({
  // Supply every case with strict isolated routes and an unconditional evidence/diagnostic teardown.
  scenario: async ({page, baseURL}, use, info) => {
    const state = scenario()
    await install(page, state, baseURL!)
    try {await use(state)} finally {await finish(state, info)}
  },
})

// Wait for response consumption and a quiet ledger, not an already-fired navigation load-state event.
async function settle(page: Page, state: Scenario, ignoreHeld = false) {
  let previous = -1
  let stable = 0
  await expect.poll(() => {
    const pending = state.requests.some(entry => !entry.finished && !(ignoreHeld && entry.held && !entry.completed))
    stable = !pending && previous === state.requests.length ? stable + 1 : 0
    previous = state.requests.length
    return stable
  }, {intervals: [50]}).toBeGreaterThanOrEqual(2)
  await page.clock.runFor(50)
}

// Reach a settled desk: the board and the first poll's read chain complete.
async function openDesk(page: Page, state: Scenario) {
  await page.goto('/#desk')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await settle(page, state)
}

// Start a real manual refresh and identify the deliberately held request it produced.
async function refreshHeld(page: Page, state: Scenario, endpoint: string) {
  const before = state.requests.length
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect.poll(() => state.requests.slice(before).some(entry => entry.path === `${DESK}${endpoint}` && entry.held)).toBe(true)
  return state.requests.slice(before).find(entry => entry.path === `${DESK}${endpoint}` && entry.held)!
}

// Inspect one ticker's rendered price and the regular feed's status line, which names the snapshot it came from.
async function expectCurrentBoard(page: Page, price: number, reason: string) {
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const row = board.getByRole('row').filter({has: page.getByRole('button', {name: 'AAPL', exact: true})})
  await expect.soft(row).toContainText(`$${price.toFixed(2)}`)
  await expect.soft(page.getByLabel('AAPL strategy intent', {exact: true})).toHaveText('—')
  await expect.soft(page.getByLabel('Plan status')).toContainText(reason)
  await expect.soft(page.getByLabel('Today')).toContainText('XNYS regular session scheduled open')
}

// A current poll must still complete its full read chain: the candle, then the paper account's orders.
test('current-context successful poll refreshes the board and completes its read chain', async ({page, scenario: state}) => {
  await openDesk(page, state)
  state.live = liveSnapshot(222, 'Current-context successful market snapshot')
  const gate = hold(state, '/live')
  const before = state.requests.length
  await refreshHeld(page, state, '/live')
  gate.release()
  await settle(page, state)
  const requests = state.requests.slice(before)
  expect(requests.filter(entry => entry.path === `${DESK}/paper`)).toHaveLength(1)
  expect(requests.map(entry => entry.path).indexOf(`${DESK}/paper`)).toBeGreaterThan(requests.map(entry => entry.path).indexOf(`${DESK}/live`))
  await expectCurrentBoard(page, 222, state.live.reason)
})

// A genuinely current live failure keeps the last price visibly stale while still re-reading the orders.
test('current-context network failure retains disclosed fallback and continues the read chain', async ({page, scenario: state}) => {
  await openDesk(page, state)
  const gate = hold(state, '/live', {abort: true})
  const before = state.requests.length
  await refreshHeld(page, state, '/live')
  gate.release()
  await settle(page, state)
  const requests = state.requests.slice(before)
  expect(requests.filter(entry => entry.path === `${DESK}/paper`)).toHaveLength(1)
  await expectCurrentBoard(page, 110, LIVE_FAILURE)
  await expect(page.getByLabel('Plan status')).toContainText('not updating')
})

for (const abort of [false, true]) {
  // Later poll starts supersede earlier live results: the obsolete completion neither repaints nor reads on.
  test(`newest same-context poll survives an older live ${abort ? 'failure' : 'success'}`, async ({page, scenario: state}) => {
    await openDesk(page, state)
    const gate = hold(state, '/live', {body: liveSnapshot(111, 'Obsolete overlapping market snapshot'), abort})
    await refreshHeld(page, state, '/live')
    const beforeNew = state.requests.length
    state.live = liveSnapshot(222, 'Newest overlapping market snapshot')
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await expect.poll(() => state.requests.slice(beforeNew).some(entry => entry.path === `${DESK}/paper` && entry.completed)).toBe(true)
    await settle(page, state, true)
    await expectCurrentBoard(page, 222, state.live.reason)
    const afterNew = state.requests.length
    gate.release()
    await settle(page, state)
    expect.soft(state.requests.slice(afterNew).filter(entry => entry.path === `${DESK}/paper`), 'Superseded poll cannot start a later read chain').toEqual([])
    await expectCurrentBoard(page, 222, state.live.reason)
    await expect.soft(page.getByLabel('Plan status')).not.toContainText(LIVE_FAILURE)
    await expect.soft(page.getByLabel('Plan status')).not.toContainText('Obsolete overlapping market snapshot')
  })
}

// Navigating away invalidates a live read before it can continue the poll chain.
test('unmount during live read stops the paper read', async ({page, scenario: state}) => {
  await openDesk(page, state)
  const gate = hold(state, '/live')
  await refreshHeld(page, state, '/live')
  await page.getByRole('navigation', {name: 'Primary navigation'}).getByRole('button', {name: 'Conversations', exact: true}).click()
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).not.toBeVisible()
  const afterLeave = state.requests.length
  gate.release()
  await settle(page, state)
  expect(state.requests.slice(afterLeave).filter(entry => entry.path.startsWith(DESK)), 'An unmounted poll starts no further desk requests').toEqual([])
})

// The later await boundary must stop continuation too, not just the initial live-price request.
test('unmount during the paper read prevents any remaining desk request', async ({page, scenario: state}) => {
  await openDesk(page, state)
  const gate = hold(state, '/paper')
  await refreshHeld(page, state, '/paper')
  await page.getByRole('navigation', {name: 'Primary navigation'}).getByRole('button', {name: 'Conversations', exact: true}).click()
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).not.toBeVisible()
  const afterLeave = state.requests.length
  gate.release()
  await settle(page, state)
  expect(state.requests.slice(afterLeave).filter(entry => entry.path.startsWith(DESK)), 'The paper continuation is discarded after unmount').toEqual([])
})
