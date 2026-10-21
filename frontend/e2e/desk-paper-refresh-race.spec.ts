import {expect, test as base, type Page, type Request, type TestInfo} from '@playwright/test'

const OWNER = 'paper-refresh-owner'
const DESK = `/api/v1/market/${OWNER}/desk`
const POLICY = 'grade-led-learned-sizing/1'
const HISTORY_WARNING = 'Saved execution history could not be verified'

type Gate = {wait: Promise<void>; release: () => void}
type Reply = {body: unknown; gate?: Gate}
type Entry = {method: string; path: string; started: number; held: boolean; completed: boolean; finished: boolean}
type Diagnostics = {pageErrors: string[]; consoleErrors: string[]; failedRequests: string[];
  badResponses: string[]; unexpectedRequests: string[]; forbiddenWrites: string[]}
type Scenario = {session: string; paper: unknown; replies: Map<string, Reply[]>; gates: Gate[];
  requests: Entry[]; diagnostics: Diagnostics; observations: {label: string; at: number; text: string}[]}

// Give the compiled board a complete numeric plan and a separately observable actual holding.
function paperSnapshot(state: Scenario, quantity: number, label: string, historyReason?: string) {
  const at = new Date(Date.now() - 1000).toISOString()
  return {as_of: at, equity: 100000, cash: 50000, positions: [{symbol: 'AAPL', qty: quantity,
    market_value: quantity * 100, avg_entry_price: 100, current_price: 100, unrealized_pl: 0}], orders: [],
    recorded_fills: [], ...(historyReason ? {recorded_fills_reason: historyReason} : {}),
    activity: {session: state.session, complete: true, fills: []},
    plan: {policy: POLICY, rule: 'next_open', orders: []},
    model_decisions: {version: 'live-model-decisions/1', status: 'available', session: state.session,
      policy: POLICY, observed_at: at, valid_until: new Date(Date.now() + 600000).toISOString(),
      record_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64),
      rows: {AAPL: {grade: 'A', signal_session: state.session, action: 'buy', qty: quantity,
        status: 'planned', reason: label, when: `${label} · next open`, executions: []}}}}
}

// Keep all fixture state and real request timestamps inside this test's own browser session.
function scenario(): Scenario {
  const state: Scenario = {session: '2026-09-23', paper: null, replies: new Map(), gates: [], requests: [],
    observations: [], diagnostics: {pageErrors: [], consoleErrors: [], failedRequests: [], badResponses: [],
      unexpectedRequests: [], forbiddenWrites: []}}
  state.paper = paperSnapshot(state, 1, 'Initial admitted plan')
  return state
}

// Defer one selected HTTP response without replacing browser clocks, timers or application functions.
function hold(state: Scenario, endpoint: string, body: unknown) {
  let release!: () => void
  const wait = new Promise<void>(resolve => {release = resolve})
  const gate = {wait, release}
  state.gates.push(gate)
  state.replies.set(endpoint, [...(state.replies.get(endpoint) ?? []), {body, gate}])
  return gate
}

// Allow only local static assets and known synthetic GET responses; every mutation is refused.
async function install(page: Page, state: Scenario, baseURL: string) {
  const ledger = new Map<Request, Entry>()
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) state.diagnostics.consoleErrors.push(message.text())})
  page.on('requestfinished', request => {const entry = ledger.get(request); if (entry) entry.finished = true})
  page.on('requestfailed', request => request.failure()?.errorText === 'net::ERR_ABORTED' ? undefined : state.diagnostics.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // Terminate all API requests in this fixture before any backend, account or provider can be reached.
  await page.route('**/*', async route => {
    // Added after this fixture was written: the board polls the model allocation on every desk view. An empty 2xx reads as "no publication" (the older desk record path); a 418 would be a console error and an unexpected request the spec counts.
    if (route.request().method() === 'GET' && new URL(route.request().url()).pathname.endsWith('/desk/model-allocation')) return route.fulfill({status: 204})
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (url.origin !== new URL(baseURL).origin) {
      state.diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    if (!path.startsWith('/api/')) return route.continue()
    const entry: Entry = {method: request.method(), path, started: Date.now(), held: false, completed: false, finished: false}
    ledger.set(request, entry)
    state.requests.push(entry)
    if (entry.method !== 'GET') {
      state.diagnostics.forbiddenWrites.push(`${entry.method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Fixture refuses mutations'}})
    }
    const endpoint = path.startsWith(DESK) ? path.slice(DESK.length) : path
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: OWNER,
      is_admin: false, desk_access: true, desk_write: false}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: state.session, written: `${state.session}T23:30:00Z`,
      grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}},
      targets: {policy: POLICY, weights: {AAPL: .1}}, book: [], actions: [], briefs: {}, regime: {exposure: 1, flags: []}},
      sessions: [state.session]}
    else if (endpoint === '/holdings') json = {holdings: []}
    else if (endpoint === '/session-prices') json = {session: 'closed', as_of: new Date().toISOString(),
      signal_scope: 'regular-session', quotes: {}}
    else if (endpoint === '/live') json = {as_of: new Date().toISOString(), quotes: {}, technical: {},
      technical_detail: {}, market_status: {phase: 'closed'}}
    else if (endpoint === '/paper') json = state.paper
    else if (endpoint === '/paper/history') json = {source: 'paper_account_records', rows: []}
    else {
      state.diagnostics.unexpectedRequests.push(`${entry.method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    const reply = state.replies.get(endpoint)?.shift()
    if (reply?.gate) {entry.held = true; await reply.gate.wait}
    await route.fulfill({json: reply?.body ?? json})
    entry.completed = true
  })
}

// Wait for actual response consumption while deliberately held requests remain pending.
async function settle(state: Scenario, ignoreHeld = false) {
  let previous = -1, stable = 0
  await expect.poll(() => {
    const pending = state.requests.some(entry => !entry.finished && !(ignoreHeld && entry.held && !entry.completed))
    stable = !pending && previous === state.requests.length ? stable + 1 : 0
    previous = state.requests.length
    return stable
  }, {intervals: [50]}).toBeGreaterThanOrEqual(3)
}

// Preserve the request order and all browser diagnostics even when a regression assertion is red.
async function finish(state: Scenario, info: TestInfo) {
  for (const gate of state.gates) gate.release()
  try {await settle(state)} finally {
    await info.attach('paper-refresh-evidence', {body: JSON.stringify({session: state.session,
      requests: state.requests, observations: state.observations, diagnostics: state.diagnostics}, null, 2), contentType: 'application/json'})
    for (const [category, failures] of Object.entries(state.diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
  }
}

const test = base.extend<{scenario: Scenario}>({
  // Install isolated HTTP fixtures and retain unconditional diagnostic evidence for every case.
  scenario: async ({page, baseURL}, use, info) => {
    const state = scenario()
    await install(page, state, baseURL!)
    try {await use(state)} finally {await finish(state, info)}
  },
})

test.setTimeout(75000)

// Reach the actual Stocks view and allow its initial dependent polling effects to complete.
async function openDesk(page: Page, state: Scenario) {
  await page.goto('/#desk')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await settle(state)
  await expect(page.getByLabel('AAPL size', {exact: true})).toHaveText('1 sh funded')
}

// Wait for a particular deferred request and expose its real start time to the assertions.
async function heldRequest(state: Scenario, endpoint: string, after: number, timeout = 30000) {
  await expect.poll(() => state.requests.slice(after).some(entry => entry.path === `${DESK}${endpoint}` && entry.held),
    {timeout, intervals: [50]}).toBe(true)
  return state.requests.slice(after).find(entry => entry.path === `${DESK}${endpoint}` && entry.held)!
}

// Record and compare both the admitted proposal and actual holding after real HTTP completion.
async function expectPaper(page: Page, state: Scenario, quantity: number, label: string) {
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  state.observations.push({label, at: Date.now(), text: await board.innerText()})
  await expect(board.getByLabel('AAPL size', {exact: true})).toHaveText(`${quantity} sh funded`)
  await expect(board.getByLabel('AAPL position', {exact: true})).toContainText(`${quantity} sh`)
  await expect(board.getByLabel('AAPL strategy timing', {exact: true})).toContainText(label)
}

// A later manual answer must survive an older independent twenty-second account response.
test('newer manual paper snapshot survives an older independent timer response', async ({page, scenario: state}) => {
  await openDesk(page, state)
  const beforeTick = state.requests.length
  const liveGate = hold(state, '/live', {as_of: new Date().toISOString(), quotes: {}, technical: {}, technical_detail: {}})
  const paperGate = hold(state, '/paper', paperSnapshot(state, 2, 'Obsolete independent timer plan'))
  const timerPaper = await heldRequest(state, '/paper', beforeTick)
  const timerLive = await heldRequest(state, '/live', beforeTick)
  expect(timerPaper.started - state.requests[0].started).toBeGreaterThanOrEqual(19000)
  expect(state.requests.slice(beforeTick).filter(entry => entry.path === `${DESK}/paper`)).toHaveLength(1)
  expect(timerLive.completed).toBe(false)
  state.paper = paperSnapshot(state, 9, 'Newest manual plan')
  const beforeManual = state.requests.length
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect.poll(() => state.requests.slice(beforeManual).some(entry => entry.path === `${DESK}/paper` && entry.completed)).toBe(true)
  await settle(state, true)
  await expectPaper(page, state, 9, 'Newest manual plan')
  paperGate.release()
  await settle(state, true)
  await expectPaper(page, state, 9, 'Newest manual plan')
  liveGate.release()
  await settle(state)
  await expectPaper(page, state, 9, 'Newest manual plan')
})

// A shifted main poll must not let its older manual answer replace a newer independent timer snapshot.
test('newer independent timer paper snapshot survives an older manual response', async ({page, scenario: state}) => {
  await openDesk(page, state)
  // A new saved session resets only the main poll effect; the original twenty-second account timer continues.
  await page.waitForTimeout(7000)
  state.session = '2026-09-24'
  state.paper = paperSnapshot(state, 1, 'Initial admitted plan')
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await settle(state)
  await expect(page.getByLabel('AAPL displayed grade', {exact: true})).toContainText(state.session)
  const beforeManual = state.requests.length
  const oldGate = hold(state, '/paper', paperSnapshot(state, 2, 'Obsolete manual plan'))
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  const oldPaper = await heldRequest(state, '/paper', beforeManual, 5000)
  const beforeTick = state.requests.length
  state.paper = paperSnapshot(state, 9, 'Newest independent timer plan')
  await expect.poll(() => state.requests.slice(beforeTick).some(entry => entry.path === `${DESK}/paper` && entry.completed),
    {timeout: 25000, intervals: [50]}).toBe(true)
  const timerPaper = state.requests.slice(beforeTick).find(entry => entry.path === `${DESK}/paper`)!
  expect(timerPaper.started - oldPaper.started).toBeGreaterThan(5000)
  expect(state.requests.slice(beforeTick).filter(entry => entry.path === `${DESK}/live`), 'No main poll superseded the held manual request').toEqual([])
  await settle(state, true)
  await expectPaper(page, state, 9, 'Newest independent timer plan')
  oldGate.release()
  await settle(state)
  await expectPaper(page, state, 9, 'Newest independent timer plan')
})

// Invalid saved history must remain visible as unavailable alongside independently valid current broker fills.
test('saved execution history failure is disclosed without hiding current broker fills', async ({page, scenario: state}) => {
  const fillAt = new Date(Date.now() - 60000).toISOString()
  const fillSession = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date(fillAt))
  state.paper = {...paperSnapshot(state, 1, 'Initial admitted plan', HISTORY_WARNING),
    activity: {session: fillSession, complete: true, fills: [{symbol: 'AAPL', side: 'buy', qty: 3, price: 100, filled_at: fillAt}]}}
  await openDesk(page, state)
  await page.getByRole('button', {name: 'Paper account', exact: true}).click()
  await page.locator('details[aria-label="Paper account"] > summary').click()
  const execution = page.getByRole('region', {name: 'Paper execution', exact: true})
  await expect(execution).toContainText('Bought 3 AAPL @ $100.00')
  await expect(execution).toContainText(`1 fills · ${fillSession}`)
  await expect(execution).toContainText(HISTORY_WARNING)
  state.paper = {...paperSnapshot(state, 1, 'Verified history refreshed'),
    activity: {session: fillSession, complete: true, fills: [{symbol: 'AAPL', side: 'buy', qty: 3, price: 100, filled_at: fillAt}]}}
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await settle(state)
  await expect(execution).not.toContainText(HISTORY_WARNING)
  await expect(execution).toContainText('Bought 3 AAPL @ $100.00')
})
