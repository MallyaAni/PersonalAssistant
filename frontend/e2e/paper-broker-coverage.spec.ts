import {expect, test, type Page, type Request, type TestInfo} from '@playwright/test'

const OWNER = 'paper-broker-coverage-owner'
const DESK = `/api/v1/market/${OWNER}/desk`
const DECIDED = '2026-10-13'
const FAILED = "Today's fill history could not be loaded"
const INCOMPLETE = 'Broker fill history may be incomplete; other fills may be missing.'
const ACCOUNT_UNAVAILABLE = 'Paper account is unavailable; execution history could not be verified.'
type Entry = {method: string; path: string; finished: boolean}
type Fill = {symbol: string; side: string; qty: number; price: number; filled_at: string}
type State = {incomplete: boolean; accountUnavailable: boolean; day: string; activity: {reason: string} | {session: string; complete: boolean; fills: Fill[]};
  requests: Entry[]; diagnostics: Record<string, string[]>; observations: {view: string; label: string; text: string; markers: string[]}[]}
type MarkerWindow = Window & {__brokerCoverageMarkers: string[]}

test.setTimeout(60000)

// Match the API's failed activity shape or the broker adapter's exact full-page incomplete shape.
function scenario(incomplete: boolean): State {
  const filledAt = new Date(Date.now() - 60000).toISOString()
  const day = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date(filledAt))
  return {incomplete, accountUnavailable: false, day, activity: incomplete ? {session: day, complete: false,
    fills: [{symbol: 'STX', side: 'buy', qty: 3, price: 101.25, filled_at: filledAt},
      ...Array.from({length: 99}, () => ({symbol: 'OTHER', side: 'buy', qty: 0.5, price: 200.25, filled_at: filledAt}))]}
    : {reason: FAILED}, requests: [], observations: [], diagnostics: {pageErrors: [], consoleErrors: [],
      failedRequests: [], badResponses: [], unexpectedRequests: [], forbiddenWrites: []}}
}

// Observe actual canvas marker painting while leaving rendering and the real clock unchanged.
async function observeMarkers(page: Page) {
  await page.addInitScript(() => {
    const state = window as unknown as MarkerWindow
    state.__brokerCoverageMarkers = []
    const original = CanvasRenderingContext2D.prototype.fillText
    // Retain chart marker labels and let the real browser render each call normally.
    CanvasRenderingContext2D.prototype.fillText = function (this: CanvasRenderingContext2D, ...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]')) state.__brokerCoverageMarkers.push(args[0])
      return original.apply(this, args)
    }
  })
}

// Intercept all API requests locally and reject other origins and writes before any account can be contacted.
async function install(page: Page, state: State, baseURL: string) {
  const ledger = new Map<Request, Entry>()
  await observeMarkers(page)
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) state.diagnostics.consoleErrors.push(message.text())})
  page.on('requestfinished', request => {const entry = ledger.get(request); if (entry) entry.finished = true})
  page.on('requestfailed', request => state.diagnostics.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // Return complete synthetic endpoint shapes without a backend, broker, model or provider call.
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
    else if (path === `${DESK}/paper`) json = state.accountUnavailable ? {user_id: OWNER, reason: 'Paper broker unavailable'} : {as_of: at, equity: 100000, cash: 100000, positions: [], orders: [],
      recorded_fills: [], recorded_fills_reason: null, activity: state.activity,
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

// Wait for required GET completion and a stable count without overriding application timers.
async function settle(state: State) {
  let previous = -1, stable = 0
  await expect.poll(() => {
    stable = !state.requests.some(entry => !entry.finished) && previous === state.requests.length ? stable + 1 : 0
    previous = state.requests.length
    return stable
  }, {intervals: [50]}).toBeGreaterThanOrEqual(3)
}

// Read distinct actual marker paint labels rather than constructing chart evidence from fixture totals.
async function markers(page: Page) {
  return page.evaluate(() => [...new Set((window as unknown as MarkerWindow).__brokerCoverageMarkers.filter(text => /^(BUY|SELL) \d+ sh$/.test(text)))])
}

// Compare coverage disclosure and the preserved STX execution in both ticker contexts and account summary.
async function inspectViews(page: Page, state: State, label: string) {
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await settle(state)
  await page.getByRole('button', {name: 'Paper account', exact: true}).click()
  await page.locator('details[aria-label="Paper account"] > summary').click()
  const execution = page.getByRole('region', {name: 'Paper execution', exact: true})
  if (state.incomplete) {
    await expect(execution).toContainText(`100+ fills · ${state.day}`)
    await expect(execution.getByText(/Bought 3 STX @ \$101\.25/)).toHaveCount(1)
  } else await expect(execution).toContainText('Today’s fill history unavailable')
  for (const view of ['Stocks', 'Paper account']) {
    await page.getByRole('button', {name: view, exact: true}).click()
    await page.getByRole('button', {name: 'STX', exact: true}).click()
    const chart = page.getByRole('region', {name: 'STX price chart', exact: true})
    if (view === 'Stocks') await chart.getByRole('checkbox', {name: 'Actual paper executions', exact: true}).check()
    await settle(state)
    const warning = state.accountUnavailable ? ACCOUNT_UNAVAILABLE : state.incomplete ? INCOMPLETE : FAILED
    state.observations.push({view, label, text: await chart.innerText(), markers: await markers(page)})
    await expect.soft(chart.getByRole('alert').filter({hasText: warning})).toHaveText(warning)
    await expect.soft(chart.getByText('No confirmed paper executions in the loaded history.', {exact: true})).toHaveCount(0)
    if (state.incomplete) {
      const list = chart.getByLabel(view === 'Stocks' ? 'STX actual paper executions' : 'STX paper fills', {exact: true})
      await expect.soft(list.locator('li')).toHaveCount(1)
      await expect.soft(list).toContainText('BUY 3 @ $101.25')
      await expect.soft(list).not.toContainText('OTHER')
      if (view === 'Stocks') await expect.soft.poll(() => markers(page)).toEqual(['BUY 3 sh'])
    } else expect.soft(await markers(page)).toEqual([])
    await page.getByRole('button', {name: 'Close', exact: true}).click()
  }
  await page.getByRole('button', {name: 'Stocks', exact: true}).click()
}

// A successful HTTP response with a broker-unavailable reason cannot become verified-empty execution history.
test('top-level paper account failure is disclosed in both tickers and reload', async ({page, baseURL}, info) => {
  const state = scenario(false)
  state.accountUnavailable = true
  await install(page, state, baseURL!)
  try {
    await page.goto('/#desk')
    await inspectViews(page, state, 'before reload')
    await page.reload()
    await inspectViews(page, state, 'after reload')
  } finally {await finish(state, info)}
})

// Preserve all diagnostic categories and fixture evidence even when the RED disclosure assertions fail.
async function finish(state: State, info: TestInfo) {
  try {await settle(state)} finally {
    await info.attach('paper-broker-coverage-evidence', {body: JSON.stringify(state, null, 2), contentType: 'application/json'})
    for (const [category, failures] of Object.entries(state.diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
  }
}

for (const incomplete of [false, true]) {
  // Preserve broker uncertainty across both ticker views and reload without discarding valid returned fills.
  test(`broker history ${incomplete ? 'incomplete 100-row page retains STX fill' : 'failure is not verified empty'} in both tickers and reload`, async ({page, baseURL}, info) => {
    const state = scenario(incomplete)
    const original = JSON.stringify(state.activity)
    if ('fills' in state.activity) expect(state.activity.fills).toHaveLength(100)
    await install(page, state, baseURL!)
    try {
      await page.goto('/#desk')
      await inspectViews(page, state, 'before reload')
      await page.reload()
      await inspectViews(page, state, 'after reload')
      expect(JSON.stringify(state.activity)).toBe(original)
    } finally {await finish(state, info)}
  })
}
