import {expect, test as base, type Page, type Request, type TestInfo} from '@playwright/test'

const OWNER = 'archived-fill-owner'
const DESK = `/api/v1/market/${OWNER}/desk`
const DECIDED = '2026-10-13'
const FILLED = '2026-10-14'
const FILLED_AT = '2026-10-14T13:32:46.922719Z'
const ORIGINAL_PRICE = 739.236667
const ARCHIVED_PRICE = 739.2367
type RecordFill = {client_order_id: string; symbol: string; side: string; qty: number; price: number;
  filled_at: string; session: string; created_at: string; reconciled_at: string | null;
  original_qty?: number; source?: string; execution?: Record<string, string | number>}
type ArchiveFill = {date: string; side: string; qty: number; price: number; filled_at?: string; client_order_id?: string}
type Entry = {method: string; path: string; completed: boolean; finished: boolean}
type Diagnostics = {pageErrors: string[]; consoleErrors: string[]; failedRequests: string[];
  badResponses: string[]; unexpectedRequests: string[]; forbiddenWrites: string[]}
type Scenario = {recorded: RecordFill[]; archived: ArchiveFill[]; requests: Entry[]; diagnostics: Diagnostics;
  activitySession?: string;
  observations: {label: string; executionText: string; chartText: string; legacyTexts: string[]; markerTexts: string[]}[]}
type MarkerWindow = Window & {__archivedPaperMarkerText: string[]}

base.setTimeout(60000)

// Retain exact legacy archive values, or explicit original identities, beside full-precision journal evidence.
function scenario(count: number, timestamped: boolean, identified = false): Scenario {
  const now = new Date().toISOString()
  return {recorded: Array.from({length: count}, (_, index) => ({
    client_order_id: `anios-${DECIDED}-sell-stx-${135 + index}`, symbol: 'STX', side: 'sell', qty: 12,
    price: ORIGINAL_PRICE, filled_at: FILLED_AT, session: DECIDED, created_at: `${DECIDED}T23:46:44Z`, reconciled_at: now,
  })), archived: Array.from({length: count}, (_, index) => ({date: FILLED, side: 'sell', qty: 12,
    price: identified ? ORIGINAL_PRICE : ARCHIVED_PRICE, ...(timestamped ? {filled_at: FILLED_AT} : {}),
    ...(identified ? {client_order_id: `anios-${DECIDED}-sell-stx-${135 + index}`} : {})})), requests: [], observations: [],
    diagnostics: {pageErrors: [], consoleErrors: [], failedRequests: [], badResponses: [], unexpectedRequests: [], forbiddenWrites: []}}
}

// Observe real canvas text without replacing clock, chart layout, rendering or marker grouping.
async function observeMarkers(page: Page) {
  await page.addInitScript(() => {
    const state = window as unknown as MarkerWindow
    state.__archivedPaperMarkerText = []
    const original = CanvasRenderingContext2D.prototype.fillText
    // Retain actual chart paint calls and let the browser draw each marker normally.
    CanvasRenderingContext2D.prototype.fillText = function (this: CanvasRenderingContext2D, ...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]')) state.__archivedPaperMarkerText.push(args[0])
      return original.apply(this, args)
    }
  })
}

// Restrict every browser API request to synthetic GET fixtures and refuse external traffic and all writes.
async function install(page: Page, state: Scenario, baseURL: string) {
  const ledger = new Map<Request, Entry>()
  await observeMarkers(page)
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) state.diagnostics.consoleErrors.push(message.text())})
  page.on('requestfinished', request => {const entry = ledger.get(request); if (entry) entry.finished = true})
  page.on('requestfailed', request => state.diagnostics.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // Return source-shaped API data locally before a backend, broker, account or provider can be contacted.
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (url.origin !== new URL(baseURL).origin) {
      state.diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    if (!path.startsWith('/api/')) return route.continue()
    const entry: Entry = {method: request.method(), path, completed: false, finished: false}
    ledger.set(request, entry)
    state.requests.push(entry)
    if (entry.method !== 'GET') {
      state.diagnostics.forbiddenWrites.push(`${entry.method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Fixture refuses mutations'}})
    }
    const at = new Date().toISOString()
    const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date())
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
      recorded_fills: state.recorded, activity: {session: state.activitySession ?? today, complete: true, fills: []},
      plan: {policy: 'grade-led-learned-sizing/1', rule: 'next_open', orders: []}}
    else if (path === `${DESK}/paper/history`) json = {source: 'paper_account_records', rows: []}
    else if (path === `${DESK}/history/STX`) json = {ticker: 'STX', rows: [], fills: state.archived, backtest: null}
    else if (path === `${DESK}/chart/STX`) json = {ticker: 'STX', timeframe: url.searchParams.get('timeframe') ?? 'daily',
      adjusted: true, basis: 'Synthetic daily candles', data_status: 'complete',
      bars: [DECIDED, FILLED, '2026-10-15', '2026-10-16'].map(date => state.recorded[0].side === 'buy'
        ? {date, open: 100, high: 105, low: 99, close: 102, volume: 100}
        : {date, open: 730, high: 750, low: 720, close: 740, volume: 100}),
      overlays: {}, levels: {}, entries: []}
    else if (path === `${DESK}/live/read/STX`) json = {symbol: 'STX', read: null, lines: {short: [], medium: [], long: []}, stale: true}
    else if (path === `${DESK}/earnings/STX`) json = {symbol: 'STX', read: null}
    else if (path === `${DESK}/strategy-simulation/STX`) json = {schema: 'latest-strategy-simulation/1', ticker: 'STX',
      policy: 'synthetic-research/1', start: DECIDED, through: '2026-10-16', counterfactual: true, real_orders: false,
      decisions: [], trades: [], targets: [], latest_target: null, latest_holding: 0,
      provenance: {cost_bps: 10, account_sha256: 'a'.repeat(64), config_sha256: 'b'.repeat(64), basis: 'Synthetic research fixture'}}
    else {
      state.diagnostics.unexpectedRequests.push(`${entry.method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    await route.fulfill({json})
    entry.completed = true
  })
}

// Wait for actual required requests to finish before inspecting or reloading the rendered page.
async function settle(state: Scenario) {
  let previous = -1, stable = 0
  await expect.poll(() => {
    const pending = state.requests.some(entry => !entry.finished)
    stable = !pending && previous === state.requests.length ? stable + 1 : 0
    previous = state.requests.length
    return stable
  }, {intervals: [50]}).toBeGreaterThanOrEqual(3)
}

// Retain source-shaped inputs, rendered outcomes and unconditional browser diagnostics even on RED.
async function finish(state: Scenario, info: TestInfo) {
  try {await settle(state)} finally {
    await info.attach('archived-fill-evidence', {body: JSON.stringify(state, null, 2), contentType: 'application/json'})
    for (const [category, failures] of Object.entries(state.diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
  }
}

// Return distinct marker texts from the actual chart canvas rather than synthesizing expected labels.
async function markers(page: Page) {
  return page.evaluate(() => [...new Set((window as unknown as MarkerWindow).__archivedPaperMarkerText.filter(text => /^(BUY|SELL) \d+ sh$/.test(text)))])
}

// Keep every anonymous source row available without treating an unproved overlap as another execution.
async function inspectLegacy(page: Page, state: Scenario) {
  const originals = state.archived.filter(fill => !fill.client_order_id)
  const evidence = page.getByLabel('STX legacy paper evidence', {exact: true})
  if (!originals.length) {
    await expect(evidence).toHaveCount(0)
    return []
  }
  await expect(evidence.getByRole('status')).toContainText('may overlap confirmed executions')
  await expect(evidence.getByRole('status')).toContainText('excluded from confirmed quantities and chart markers')
  await evidence.getByText(`Original legacy records (${originals.length}) · overlap unresolved`, {exact: true}).click()
  const rows = evidence.locator('li')
  await expect(rows).toHaveCount(originals.length)
  for (const [index, original] of originals.entries()) {
    await expect(rows.nth(index)).toContainText(`${original.date}`)
    await expect(rows.nth(index)).toContainText(`${original.side.toUpperCase()} ${original.qty} @ $${original.price}`)
    if (original.filled_at) await expect(rows.nth(index).locator('time')).toHaveAttribute('datetime', original.filled_at)
    else expect(await rows.nth(index).locator('time').getAttribute('datetime')).toBeNull()
    expect(await rows.nth(index).getAttribute('data-client-order-id')).toBeNull()
  }
  return rows.allTextContents()
}

// Compare the account list, ticker list and real daily marker on the same loaded data.
async function inspectViews(page: Page, state: Scenario, label: string) {
  const count = state.recorded.length
  const side = state.recorded[0].side.toUpperCase()
  const quantity = state.recorded.reduce((total, fill) => total + fill.qty, 0)
  expect(state.recorded.every(fill => fill.side === state.recorded[0].side)).toBe(true)
  const activityDay = state.activitySession ?? new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date())
  expect(FILLED < activityDay, 'The historical fill is earlier than the broker activity day').toBe(true)
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await settle(state)
  await page.getByRole('button', {name: 'Paper account', exact: true}).click()
  await page.locator('details[aria-label="Paper account"] > summary').click()
  const executions = page.getByRole('region', {name: 'Paper execution', exact: true})
  await expect(executions.locator('[data-client-order-id]')).toHaveCount(count)
  for (const fill of state.recorded) {
    const price = fill.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})
    await expect(executions.locator(`[data-client-order-id="${fill.client_order_id}"]`)).toContainText(`${fill.side === 'buy' ? 'Bought' : 'Sold'} ${fill.qty} ${fill.symbol} @ $${price}`)
  }
  const executionText = await executions.innerText()
  await page.getByRole('button', {name: 'Stocks', exact: true}).click()
  await page.getByRole('button', {name: 'STX', exact: true}).click()
  const chart = page.getByRole('region', {name: 'STX price chart', exact: true})
  await chart.getByRole('checkbox', {name: 'Actual paper executions', exact: true}).check()
  await settle(state)
  const list = chart.getByLabel('STX actual paper executions', {exact: true})
  await expect.soft(list.locator('li')).toHaveCount(count)
  for (const fill of state.recorded) {
    await expect.soft(list.locator(`[data-client-order-id="${fill.client_order_id}"]`)).toHaveCount(1)
    const price = fill.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})
    await expect.soft(list.locator(`[data-client-order-id="${fill.client_order_id}"]`)).toContainText(`${fill.side.toUpperCase()} ${fill.qty} @ $${price}`)
  }
  await expect.soft.poll(() => markers(page)).toContain(`${side} ${quantity} sh`)
  const markerTexts = await markers(page)
  expect.soft(markerTexts).not.toContain(`${side} ${quantity * 2} sh`)
  expect.soft(markerTexts).toEqual([`${side} ${quantity} sh`])
  const legacyTexts = await inspectLegacy(page, state)
  state.observations.push({label, executionText, chartText: await list.innerText(), legacyTexts, markerTexts})
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  await settle(state)
  await page.getByRole('button', {name: 'Paper account', exact: true}).click()
  await page.getByRole('button', {name: 'STX', exact: true}).click()
  const accountChart = page.getByRole('region', {name: 'STX price chart', exact: true})
  await settle(state)
  await expect(accountChart.getByLabel('STX paper fills', {exact: true}).locator('li')).toHaveCount(count)
  for (const fill of state.recorded) {
    const price = fill.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})
    await expect(accountChart.getByLabel('STX paper fills', {exact: true})).toContainText(`${fill.side.toUpperCase()} ${fill.qty} @ $${price}`)
  }
  const accountLegacy = await inspectLegacy(page, state)
  expect(accountLegacy).toEqual(legacyTexts)
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  await page.getByRole('button', {name: 'Stocks', exact: true}).click()
  await settle(state)
}

// A source-shaped working partial remains a confirmed BUY after the broker activity day has moved on.
base('working partial execution remains visible after nextday empty activity and reload', async ({page, baseURL}, info) => {
  const state = scenario(1, true)
  state.recorded = [{client_order_id: `anios-${DECIDED}-buy-stx-7`, symbol: 'STX', side: 'buy', qty: 2,
    price: 101.25, filled_at: '2026-10-14T13:31:00Z', session: DECIDED, created_at: '2026-10-14T13:30:00Z',
    reconciled_at: null, original_qty: 8, source: 'recorded_paper_journal', execution: {
      decision_at: '2026-10-13T23:45:00Z', reference_price: 100, reference_session: DECIDED,
      reference_source: 'synthetic original daily close', created_at: '2026-10-14T13:30:00Z',
      submitted_at: '2026-10-14T13:30:01Z', filled_at: '2026-10-14T13:31:00Z',
    }}]
  state.archived = []
  state.activitySession = '2026-10-15'
  const originalEvidence = JSON.stringify(state.recorded)
  await install(page, state, baseURL!)
  try {
    await page.goto('/#desk')
    await inspectViews(page, state, 'working partial before reload')
    await page.reload()
    await inspectViews(page, state, 'working partial after reload')
    expect(JSON.stringify(state.recorded)).toBe(originalEvidence)
  } finally {await finish(state, info)}
})

for (const sample of [{name: 'anonymous timestamped', count: 1, timestamped: true, identified: false},
  {name: 'anonymous date-only', count: 1, timestamped: false, identified: false},
  {name: 'anonymous two distinct identical-valued', count: 2, timestamped: true, identified: false},
  {name: 'identified', count: 1, timestamped: true, identified: true}]) {
  // Conserve confirmed identities across reload while retaining unresolved legacy evidence on both ticker views.
  base(`rounded ${sample.name} archived fill history conserves original executions across reload`, async ({page, baseURL}, info) => {
    const state = scenario(sample.count, sample.timestamped, sample.identified)
    const originalArchive = JSON.stringify(state.archived)
    await install(page, state, baseURL!)
    try {
      if (sample.identified) expect(state.archived[0].price).toBe(state.recorded[0].price)
      else expect(state.archived[0].price).not.toBe(state.recorded[0].price)
      expect(state.archived.every(fill => Boolean(fill.client_order_id) === sample.identified)).toBe(true)
      await page.goto('/#desk')
      await inspectViews(page, state, 'before reload')
      await page.reload()
      await inspectViews(page, state, 'after reload')
      expect(JSON.stringify(state.archived)).toBe(originalArchive)
    } finally {await finish(state, info)}
  })
}
