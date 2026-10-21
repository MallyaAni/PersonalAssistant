import {expect, test, type Page, type Request, type TestInfo} from '@playwright/test'

const OWNER = 'paper-history-error-owner'
const DESK = `/api/v1/market/${OWNER}/desk`
const REASON = 'Saved execution history could not be verified'
const DECIDED = '2026-10-13'
type Entry = {method: string; path: string; finished: boolean}
type State = {withActivity: boolean; day: string; filledAt: string; requests: Entry[];
  diagnostics: Record<string, string[]>; observations: {view: string; label: string; text: string}[]}

test.setTimeout(60000)

// Keep independently valid broker activity separate from the failed saved-journal projection.
function scenario(withActivity: boolean): State {
  const filledAt = new Date(Date.now() - 60000).toISOString()
  return {withActivity, filledAt,
    day: new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date(filledAt)),
    requests: [], observations: [], diagnostics: {pageErrors: [], consoleErrors: [], failedRequests: [],
      badResponses: [], unexpectedRequests: [], forbiddenWrites: []}}
}

// Serve every API read locally and reject external traffic and mutations before any real account is reachable.
async function install(page: Page, state: State, baseURL: string) {
  const ledger = new Map<Request, Entry>()
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) state.diagnostics.consoleErrors.push(message.text())})
  page.on('requestfinished', request => {const entry = ledger.get(request); if (entry) entry.finished = true})
  page.on('requestfailed', request => request.failure()?.errorText === 'net::ERR_ABORTED' ? undefined : state.diagnostics.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // Return source-shaped failure and activity data without contacting a backend or provider.
  await page.route('**/*', async route => {
    // Added after this fixture was written: the board polls the model allocation on every desk view. An empty 2xx reads as "no publication" (the older desk record path); a 418 would be a console error and an unexpected request the spec counts.
    if (route.request().method() === 'GET' && new URL(route.request().url()).pathname.endsWith('/desk/model-allocation')) return route.fulfill({status: 204})
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
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: OWNER,
      is_admin: false, desk_access: true, desk_write: false}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: DECIDED, written: `${DECIDED}T23:47:45Z`,
      grades: {STX: {grade: 'C'}}, targets: {policy: 'grade-led-learned-sizing/1', weights: {}},
      actions: [], book: [], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: [DECIDED]}
    else if (path === `${DESK}/live`) json = {as_of: at, decision_session: DECIDED, quotes: {},
      technical: {}, technical_detail: {}, market_status: {phase: 'closed'}}
    else if (path === `${DESK}/session-prices`) json = {session: 'closed', signal_scope: 'regular-session', as_of: at, quotes: {}}
    else if (path === `${DESK}/holdings`) json = {holdings: []}
    else if (path === `${DESK}/paper`) json = {as_of: at, equity: 100000, cash: 100000, positions: [], orders: [],
      recorded_fills: [], recorded_fills_reason: REASON,
      activity: {session: state.day, complete: true, fills: state.withActivity ? [{
        client_order_id: 'original-broker-fill-3', symbol: 'STX', side: 'buy', qty: 3,
        price: 101.25, filled_at: state.filledAt}] : []},
      plan: {policy: 'grade-led-learned-sizing/1', rule: 'next_open', orders: []}}
    else if (path === `${DESK}/paper/history`) json = {source: 'paper_account_records', rows: []}
    else if (path === `${DESK}/history/STX`) json = {ticker: 'STX', rows: [], fills: [], backtest: null}
    else if (path === `${DESK}/chart/STX`) json = {ticker: 'STX', timeframe: url.searchParams.get('timeframe') ?? 'daily',
      adjusted: true, basis: 'Synthetic daily candles', data_status: 'complete',
      bars: [...new Set([DECIDED, '2026-10-14', '2026-10-15', '2026-10-16', state.day])].sort().map(date => ({
        date, open: 100, high: 105, low: 99, close: 102, volume: 100})), overlays: {}, levels: {}, entries: []}
    else if (path === `${DESK}/live/read/STX`) json = {symbol: 'STX', read: null, lines: {short: [], medium: [], long: []}, stale: true}
    else if (path === `${DESK}/earnings/STX`) json = {symbol: 'STX', read: null}
    else if (path === `${DESK}/strategy-simulation/STX`) json = {schema: 'latest-strategy-simulation/1', ticker: 'STX',
      policy: 'synthetic-research/1', start: DECIDED, through: state.day, counterfactual: true, real_orders: false,
      decisions: [], trades: [], targets: [], latest_target: null, latest_holding: 0,
      provenance: {cost_bps: 10, account_sha256: 'a'.repeat(64), config_sha256: 'b'.repeat(64), basis: 'Synthetic research fixture'}}
    else {
      state.diagnostics.unexpectedRequests.push(`${entry.method} ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    await route.fulfill({json})
  })
}

// Wait for required GETs and a stable request count instead of replacing the application's timers.
async function settle(state: State) {
  let previous = -1, stable = 0
  await expect.poll(() => {
    stable = !state.requests.some(entry => !entry.finished) && previous === state.requests.length ? stable + 1 : 0
    previous = state.requests.length
    return stable
  }, {intervals: [50]}).toBeGreaterThanOrEqual(3)
}

// Check both ticker contexts and preserve independently valid activity alongside the history warning.
async function inspectViews(page: Page, state: State, label: string) {
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await settle(state)
  await page.getByRole('button', {name: 'Paper account', exact: true}).click()
  await page.locator('details[aria-label="Paper account"] > summary').click()
  const execution = page.getByRole('region', {name: 'Paper execution', exact: true})
  await expect(execution.getByRole('alert')).toHaveText(REASON)
  if (state.withActivity) await expect(execution).toContainText('Bought 3 STX @ $101.25')
  for (const view of ['Stocks', 'Paper account']) {
    await page.getByRole('button', {name: view, exact: true}).click()
    await page.getByRole('button', {name: 'STX', exact: true}).click()
    const chart = page.getByRole('region', {name: 'STX price chart', exact: true})
    if (view === 'Stocks') await chart.getByRole('checkbox', {name: 'Actual paper executions', exact: true}).check()
    await settle(state)
    state.observations.push({view, label, text: await chart.innerText()})
    await expect.soft(chart.getByRole('alert').filter({hasText: REASON})).toHaveText(REASON)
    await expect.soft(chart.getByText('No confirmed paper executions in the loaded history.', {exact: true})).toHaveCount(0)
    if (state.withActivity) {
      const list = chart.getByLabel(view === 'Stocks' ? 'STX actual paper executions' : 'STX paper fills', {exact: true})
      await expect.soft(list.locator('li')).toHaveCount(1)
      await expect.soft(list).toContainText('BUY 3 @ $101.25')
    }
    await page.getByRole('button', {name: 'Close', exact: true}).click()
  }
  await page.getByRole('button', {name: 'Stocks', exact: true}).click()
}

// Retain every diagnostic category even when the expected disclosure fails on the deployed RED build.
async function finish(state: State, info: TestInfo) {
  try {await settle(state)} finally {
    await info.attach('paper-history-error-evidence', {body: JSON.stringify(state, null, 2), contentType: 'application/json'})
    for (const [category, failures] of Object.entries(state.diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
  }
}

for (const withActivity of [false, true]) {
  // A journal failure stays explicit on both ticker views and after reload without discarding real activity.
  test(`failed saved history disclosed in both tickers ${withActivity ? 'beside current broker fills' : 'with empty later-day activity'} and reload`, async ({page, baseURL}, info) => {
    const state = scenario(withActivity)
    expect(state.day > '2026-10-14').toBe(true)
    await install(page, state, baseURL!)
    try {
      await page.goto('/#desk')
      await inspectViews(page, state, 'before reload')
      await page.reload()
      await inspectViews(page, state, 'after reload')
    } finally {await finish(state, info)}
  })
}
