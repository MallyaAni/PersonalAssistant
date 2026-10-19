import {expect, test, type Page, type Request, type TestInfo} from '@playwright/test'

const OWNER = 'event-recovery-coverage-owner'
const DESK = `/api/v1/market/${OWNER}/desk`
const DECIDED = '2026-10-13'
type Mode = 'fresh failure' | 'stale failure' | 'healthy monitoring'
type Entry = {method: string; path: string; finished: boolean}
type State = {mode: Mode; asOf: string; filledAt: string; day: string; requests: Entry[];
  diagnostics: Record<string, string[]>; observations: {label: string; policy: string; today: string; execution: string; order: string}[]}

test.setTimeout(60000)

// Date actual API-shaped failure observations with real time and retain an independent confirmed regular fill.
function scenario(mode: Mode): State {
  const filledAt = new Date(Date.now() - 60000).toISOString()
  return {mode, filledAt, asOf: new Date(Date.now() - (mode === 'stale failure' ? 1200000 : 1000)).toISOString(),
    day: new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date(filledAt)),
    requests: [], observations: [], diagnostics: {pageErrors: [], consoleErrors: [], failedRequests: [],
      badResponses: [], unexpectedRequests: [], forbiddenWrites: []}}
}

// Supply only local GET fixtures and reject writes or external traffic before any live account can be reached.
async function install(page: Page, state: State, baseURL: string) {
  const ledger = new Map<Request, Entry>()
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) state.diagnostics.consoleErrors.push(message.text())})
  page.on('requestfinished', request => {const entry = ledger.get(request); if (entry) entry.finished = true})
  page.on('requestfailed', request => state.diagnostics.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // Match processed event_status.load responses, including authoritative boolean active and pause fields.
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (url.origin !== new URL(baseURL).origin) {
      state.diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    if (!path.startsWith('/api/')) return route.continue()
    const entry = {method: request.method(), path, finished: false}
    ledger.set(request, entry)
    state.requests.push(entry)
    if (entry.method !== 'GET') {
      state.diagnostics.forbiddenWrites.push(`${entry.method} ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Fixture refuses mutations'}})
    }
    const at = new Date().toISOString()
    const policy = {enabled: true, session: DECIDED, decision_date: '2026-11-04', factor: 1,
      calendar_known: true, spy_five_session_return: 0.01, evaluation_since: '2026-06-18'}
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: OWNER,
      is_admin: false, desk_access: true, desk_write: false}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: DECIDED, written: `${DECIDED}T23:47:45Z`,
      grades: {STX: {grade: 'C'}}, targets: {policy: 'grade-led-learned-sizing/1', weights: {}},
      actions: [], book: [], briefs: {}, regime: {exposure: 1, flags: []}, event_risk: policy}, sessions: [DECIDED],
      event_policy: {enabled: true}, event_status: {as_of: state.asOf,
        status: state.mode === 'healthy monitoring' ? 'monitoring' : 'recovery unavailable',
        stale: state.mode === 'stale failure', active: false, planning_paused: state.mode === 'fresh failure', pending_orders: 0,
        ...(state.mode === 'healthy monitoring' ? {policy} : {error_type: 'PermissionError'})}}
    else if (path === `${DESK}/live`) json = {as_of: at, decision_session: DECIDED, quotes: {},
      technical: {}, technical_detail: {}, market_status: {phase: 'closed'}}
    else if (path === `${DESK}/session-prices`) json = {session: 'closed', signal_scope: 'regular-session', as_of: at, quotes: {}}
    else if (path === `${DESK}/holdings`) json = {holdings: []}
    else if (path === `${DESK}/paper`) json = {as_of: at, equity: 100000, cash: 100000, positions: [], orders: [],
      recorded_fills: [], recorded_fills_reason: null, activity: {session: state.day, complete: true, fills: [{
        symbol: 'STX', side: 'buy', qty: 3, price: 101.25, filled_at: state.filledAt}]},
      plan: {policy: 'grade-led-learned-sizing/1', rule: 'next_open', until_rebalance: 12, orders: [{
        client_order_id: 'original-regular-stx-3', symbol: 'STX', side: 'buy', action: 'BUY', qty: 3,
        price: 101.25, notional: 303.75, weight: 0.0030375, leg: 'entry', why: 'Synthetic original regular order',
        timing: 'next_open', decided: DECIDED, execute_on: state.day, state: 'filled', status: 'Bought 3 @ $101.25',
        when: 'Original regular execution', filled_qty: 3, filled_price: 101.25, filled_at: state.filledAt,
        submitted_qty: 3, planned_qty: 3, terminal: true, quantity_basis: 'filled'}]}}
    else if (path === `${DESK}/paper/history`) json = {source: 'paper_account_records', rows: []}
    else {
      state.diagnostics.unexpectedRequests.push(`${entry.method} ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    await route.fulfill({json})
  })
}

// Wait for actual GET completion and a stable request count without clock or timer replacements.
async function settle(state: State) {
  let previous = -1, stable = 0
  await expect.poll(() => {
    stable = !state.requests.some(entry => !entry.finished) && previous === state.requests.length ? stable + 1 : 0
    previous = state.requests.length
    return stable
  }, {intervals: [50]}).toBeGreaterThanOrEqual(3)
}

// Preserve known regular executions while checking that a failed recovery never becomes a successful empty event state.
async function inspect(page: Page, state: State, label: string) {
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board).toBeVisible()
  await settle(state)
  await page.locator('details[aria-label="Paper account"] > summary').click()
  const execution = page.getByRole('region', {name: 'Paper execution', exact: true})
  await expect(execution.getByText(/Bought 3 STX @ \$101\.25/)).toHaveCount(1)
  const order = board.getByLabel('STX order status', {exact: true})
  await expect(order).toContainText('Bought 3 @ $101.25')
  await page.locator('details[aria-label="Strategy details"] > summary').click()
  const policy = page.getByRole('region', {name: 'FOMC exposure policy', exact: true})
  const today = page.getByRole('region', {name: 'Today', exact: true})
  state.observations.push({label, policy: await policy.innerText(), today: await today.innerText(),
    execution: await execution.innerText(), order: await order.innerText()})
  await expect.soft(today).toContainText('Paper orders: 1 filled.')
  await expect.soft(policy).not.toContainText('PermissionError')
  if (state.mode === 'healthy monitoring') {
    await expect.soft(policy.getByRole('alert')).toHaveCount(0)
    await expect.soft(policy.getByRole('heading')).toContainText('FOMC · monitoring')
    await expect.soft(policy).toContainText('no pre-meeting reduction requested')
    await expect.soft(policy).toContainText('Nothing is being traded for this policy right now.')
    await expect.soft(today).not.toContainText('execution unconfirmed')
  } else {
    const warning = state.mode === 'stale failure'
      ? 'The last FOMC recovery check failed; current event execution is unconfirmed.'
      : 'FOMC recovery could not be verified; current event execution is unconfirmed.'
    await expect.soft(policy.getByRole('alert')).toHaveText(warning)
    await expect.soft(policy).not.toContainText('Nothing is being traded')
    await expect.soft(policy).not.toContainText('no pre-meeting reduction requested')
    await expect.soft(today).toContainText('FOMC execution unconfirmed')
    await expect.soft(today).not.toContainText('paper FOMC cycle active')
    if (state.mode === 'stale failure') {
      await expect.soft(policy).toContainText('last known status')
      await expect.soft(policy.getByRole('heading')).toContainText('last recovery unavailable')
      await expect.soft(page.getByRole('status', {name: 'Trading restriction', exact: true})).toHaveCount(0)
    } else await expect.soft(page.getByRole('status', {name: 'Trading restriction', exact: true})).toContainText('FOMC cycle:')
  }
}

// Retain all diagnostics and source-shaped observations even if a RED content assertion fails.
async function finish(state: State, info: TestInfo) {
  try {await settle(state)} finally {
    await info.attach('event-recovery-unavailable-evidence', {body: JSON.stringify(state, null, 2), contentType: 'application/json'})
    for (const [category, failures] of Object.entries(state.diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
  }
}

for (const mode of ['fresh failure', 'stale failure', 'healthy monitoring'] as const) {
  // Exercise current and stale recovery failures plus a healthy control on real wallclock dates and after reload.
  test(`FOMC ${mode} keeps execution certainty and original fills explicit after reload`, async ({page, baseURL}, info) => {
    const state = scenario(mode)
    await install(page, state, baseURL!)
    try {
      await page.goto('/?deskView=paper#desk')
      await inspect(page, state, 'before reload')
      await page.reload()
      await inspect(page, state, 'after reload')
    } finally {await finish(state, info)}
  })
}
