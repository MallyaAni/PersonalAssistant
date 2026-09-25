import {expect, test as base, type Page, type TestInfo} from '@playwright/test'
import type {DeskPersonalReceipt} from '../src/services/api'

const OWNER = 'ani.mallya'
const SESSION = '2026-09-24'
const WRITTEN = '2026-09-24T00:00:00Z'
const NOW = '2026-09-24T14:00:00Z'
const DEADLINE = '2026-09-24T14:10:00Z'

// Give every synthetic receipt a real UUID shape, including pagination cursors.
function receiptId(index: number) {
  return `00000000-0000-4000-8000-${index.toString(16).padStart(12, '0')}`
}

const INITIAL_ID = receiptId(1)
const SELL_ID = receiptId(2)
const BUY_ID = receiptId(3)
const FOREIGN_ID = receiptId(4)

type Action = 'Buy' | 'Sell' | 'Hold'
type Gate = {wait: Promise<void>; release: () => void}
type Reply = {body?: unknown; status?: number; gate?: Gate}
type LedgerEntry = {
  method: string; path: string; query: string; owner: string; writable: boolean;
  body?: unknown; receiptId?: string; returnedIds?: string[]; cursor?: string | null;
  held?: boolean; completed: boolean; status?: number;
}
type Paint = {action: string; center: number}
type CandlePaint = {center: number; width: number}
type Diagnostics = {consoleErrors: string[]; pageErrors: string[]; failedRequests: string[];
  badResponses: string[]; unexpectedRequests: string[]; forbiddenWrites: string[]}
type Scenario = {
  owner: string; writable: boolean; current: DeskPersonalReceipt;
  head: DeskPersonalReceipt[]; older: DeskPersonalReceipt[]; oldest: DeskPersonalReceipt[];
  exactReplies: Map<string, Reply[]>; pageReplies: Map<string, Reply[]>; mineReplies: Reply[];
  ackReplies: Map<string, Reply[]>; gates: Gate[]; requests: LedgerEntry[];
  diagnostics: Diagnostics; expectedHttpErrors: string[]; expectedConsoleErrors: string[];
}

// Retain a route until the test deliberately selects its response order.
function deferred(state: Scenario): Gate {
  let release!: () => void
  const wait = new Promise<void>(resolve => {release = resolve})
  const gate = {wait, release}
  state.gates.push(gate)
  return gate
}

// Model immutable generated advice without broker orders, cash or share quantities.
function saved(id: string, at: string, action: Action): DeskPersonalReceipt {
  const move = action === 'Buy' ? .001 : action === 'Sell' ? -.001 : 0
  return {
    id, generated_at: at, acknowledged_at: null, acknowledge_before: DEADLINE,
    payload: {
      schema_version: 'personal-decision-receipt/1', policy_version: 'cash-bounded-breakout-rotation/3',
      decision_version: 'desk-decision-view/1', decision_policy: 'Personal manual execution',
      session: SESSION, written: WRITTEN, record_sha256: 'a'.repeat(64), code_fingerprint: {}, event_state: {},
      rows: {AAPL: {
        action, strategy_action: action, grade: 'A', move_weight: move, strategy_move_weight: move,
        target_weight: .01 + move, current_weight: .01, delta_weight: move,
        executable: action !== 'Hold', blocker: null, reason: `Accepted ${action} receipt ${id}`,
        valid_until: DEADLINE, quote: {feed: 'sip', at, bid: 109.99, ask: 110, valid_until: DEADLINE},
        band_z: 1.5, bar: {at: '2026-09-24T13:45:00Z', price: 110},
      }},
    },
  }
}

// Make a full twenty-row descending page with one visible action and nineteen Hold separators.
function historicalPage(firstId: number, day: string, action: Action) {
  return Array.from({length: 20}, (_, index) => saved(receiptId(firstId + index),
    `${day}T14:${String(19 - index).padStart(2, '0')}:00Z`, index === 19 ? action : 'Hold'))
}

// Initialize independent page, exact-read, acknowledgement and mine-response controls.
function scenario(): Scenario {
  const current = saved(INITIAL_ID, '2026-09-24T13:59:00Z', 'Hold')
  return {
    owner: OWNER, writable: true, current,
    head: [current, ...historicalPage(100, '2026-09-23', 'Buy').slice(1)],
    older: historicalPage(200, '2026-09-22', 'Sell'), oldest: historicalPage(300, '2026-09-21', 'Buy'),
    exactReplies: new Map(), pageReplies: new Map(), mineReplies: [], ackReplies: new Map(),
    gates: [], requests: [], expectedHttpErrors: [], expectedConsoleErrors: [],
    diagnostics: {consoleErrors: [], pageErrors: [], failedRequests: [], badResponses: [], unexpectedRequests: [], forbiddenWrites: []},
  }
}

// Return a complete current decision whose recording envelope is independent of acknowledgement.
function mine(item: DeskPersonalReceipt) {
  return {
    session: SESSION, market_status: market(), rows: [], grades_live: {},
    decisions: {session: SESSION, written: WRITTEN, rows: item.payload.rows},
    history_receipt: {status: 'generated', id: item.id, generated_at: item.generated_at, acknowledge_before: item.acknowledge_before},
  }
}

// Keep the fixture's market clock explicit and separate from receipt generation times.
function market() {
  return {exchange: 'XNYS', as_of: NOW, session: SESSION, calendar_known: true, is_session: true,
    open: true, phase: 'open', opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
}

// Observe actual canvas marker paints while leaving every drawing operation intact.
async function observeCanvas(page: Page) {
  await page.addInitScript(() => {
    const observed = window as typeof window & {__receiptRefreshPaints: Paint[]; __receiptChartPaintCount: number; __receiptCandlePaints: CandlePaint[]}
    observed.__receiptRefreshPaints = []
    observed.__receiptChartPaintCount = 0
    observed.__receiptCandlePaints = []
    let candleCanvas: HTMLCanvasElement | null = null
    const original = CanvasRenderingContext2D.prototype.fillText
    const originalRect = CanvasRenderingContext2D.prototype.fillRect
    // Count actual frames and retain only the candle canvas's latest complete repaint geometry.
    CanvasRenderingContext2D.prototype.fillRect = function (x: number, y: number, width: number, height: number) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]')) observed.__receiptChartPaintCount += 1
      if (this.canvas === candleCanvas && this.globalCompositeOperation === 'copy'
        && x === 0 && y === 0 && width === this.canvas.width && height === this.canvas.height) {
        observed.__receiptCandlePaints = []
      }
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && this.fillStyle === '#2da44e' && width > 2) {
        if (candleCanvas !== this.canvas) {candleCanvas = this.canvas; observed.__receiptCandlePaints = []}
        const transform = this.getTransform()
        const point = new DOMPoint(x + width / 2, y).matrixTransform(transform)
        const ratio = this.canvas.getBoundingClientRect().width / this.canvas.width
        observed.__receiptCandlePaints.push({center: point.x * ratio, width: Math.abs(width * transform.a * ratio)})
      }
      return originalRect.call(this, x, y, width, height)
    }
    // Track transformed marker centers, never the chart's independent text caption.
    CanvasRenderingContext2D.prototype.fillText = function (text: string, x: number, y: number, maxWidth?: number) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && (text === 'Buy' || text === 'Sell')) {
        const point = new DOMPoint(x + this.measureText(text).width / 2, y).matrixTransform(this.getTransform())
        observed.__receiptRefreshPaints.push({action: text, center: point.x * this.canvas.getBoundingClientRect().width / this.canvas.width})
      }
      return maxWidth === undefined ? original.call(this, text, x, y) : original.call(this, text, x, y, maxWidth)
    }
  })
}

// Read only the canvas instrumentation installed before the application loaded.
async function paints(page: Page) {
  return page.evaluate(() => (window as typeof window & {__receiptRefreshPaints: Paint[]}).__receiptRefreshPaints)
}

// Compare actual horizontal candle geometry after zoom, independently of labels or a React wrapper.
async function candleGeometry(page: Page) {
  const geometry = await page.evaluate(() => (window as typeof window & {__receiptCandlePaints: CandlePaint[]}).__receiptCandlePaints)
  return [...new Set(geometry.map(item => `${item.center.toFixed(1)}:${item.width.toFixed(1)}`))].sort()
}

// Intercept every request and permit only explicitly scoped synthetic reads, generation and acknowledgement.
async function install(page: Page, state: Scenario, baseURL: string) {
  await page.clock.install({time: new Date(NOW)})
  await observeCanvas(page)
  page.on('pageerror', error => state.diagnostics.pageErrors.push(error.message))
  page.on('console', message => {if (message.type() === 'error') state.diagnostics.consoleErrors.push(message.text())})
  page.on('requestfailed', request => state.diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  // A single interceptor prevents any unrecognised API or external request escaping to a real service.
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
    const entry: LedgerEntry = {method, path, query: url.search, owner: state.owner, writable: state.writable,
      body: path === '/api/v1/auth/login' ? {username: body?.username, password: '[synthetic input omitted]'} : body, completed: false}
    state.requests.push(entry)
    const desk = `/api/v1/market/${state.owner}/desk`
    const id = path.startsWith(`${desk}/personal-history/`) ? path.split('/')[7] : undefined
    const acknowledge = Boolean(id && path === `${desk}/personal-history/${id}/acknowledge`)
    const privateRead = path === `${desk}/personal-history` || Boolean(id)
    const permittedPost = method === 'POST' && (path === '/api/v1/auth/login'
      || path === `${desk}/mine` && body?.record_history === state.writable
      || acknowledge && state.writable && JSON.stringify(body) === JSON.stringify({session: SESSION, written: WRITTEN}))
    if (method !== 'GET' && !permittedPost || privateRead && !state.writable) {
      state.diagnostics.forbiddenWrites.push(`${method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 403, json: {detail: 'Fixture refuses this operation'}})
    }
    let json: unknown
    let reply: Reply | undefined
    if (path === '/api/v1/auth/session' || path === '/api/v1/auth/login') {
      json = {authentication_required: true, user_id: state.owner, is_admin: state.writable, desk_access: true, desk_write: state.writable}
    } else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === desk) json = {latest: {session: SESSION, written: WRITTEN,
      regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}},
      book: [], actions: [], briefs: {}}, sessions: [SESSION]}
    else if (path === `${desk}/holdings`) json = {holdings: [{ticker: 'AAPL', shares: 10, entry_price: 100, entry_date: '2026-08-28'}]}
    else if (path === `${desk}/live`) json = {as_of: NOW, data_at: '2026-09-24T13:45:00Z',
      quotes: {AAPL: {last: 110, bar: '2026-09-24T13:45:00Z'}}, technical: {}, technical_detail: {}, market_status: market()}
    else if (path === `${desk}/session-prices`) json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {}}
    else if (path === `${desk}/mine`) {
      reply = state.mineReplies.shift()
      json = reply?.body ?? mine(state.current)
      entry.receiptId = (json as ReturnType<typeof mine>).history_receipt.id
    } else if (acknowledge) {
      reply = state.ackReplies.get(id!)?.shift()
      entry.receiptId = id
      json = {id, status: 'acknowledged', acknowledged_at: new Date().toISOString()}
    } else if (path === `${desk}/personal-history`) {
      const before = url.searchParams.get('before') ?? ''
      if (url.searchParams.get('limit') !== '20') state.diagnostics.unexpectedRequests.push(`Invalid page limit: ${url.search}`)
      const items = before === '' ? state.head : before === state.head.at(-1)?.id ? state.older : before === state.older.at(-1)?.id ? state.oldest : null
      if (!items) state.diagnostics.unexpectedRequests.push(`Unknown cursor: ${before}`)
      const cursor = before === state.older.at(-1)?.id ? null : items?.at(-1)?.id ?? null
      reply = state.pageReplies.get(before)?.shift()
      json = {items: items ?? [], next_cursor: cursor, retention: {acknowledged_days: 90, unacknowledged_hours: 24}, limitations: []}
    } else if (id && path === `${desk}/personal-history/${id}`) {
      reply = state.exactReplies.get(id)?.shift()
      json = [state.current, ...state.head, ...state.older, ...state.oldest].find(item => item.id === id)
      if (!json && !reply?.body) state.diagnostics.unexpectedRequests.push(`Unknown exact receipt: ${id}`)
      entry.receiptId = id
    } else if (path === `${desk}/history/AAPL`) json = {ticker: 'AAPL', rows: [], backtest: null,
      recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (path === `${desk}/earnings/AAPL`) json = {symbol: 'AAPL', read: null}
    else if (path === `${desk}/live/read/AAPL`) json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else if (path === `${desk}/chart/AAPL`) {
      const days = ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24']
      json = {ticker: 'AAPL', timeframe: 'daily', adjusted: true, basis: 'adjusted fixture prices', sessions: days.length,
        bars: days.map(date => ({date, open: 100, high: 120, low: 90, close: 110, volume: 100})),
        overlays: {}, levels: {}, entries: [], data_status: 'complete', missing_sessions: []}
    } else if (path === `${desk}/entries` || path === `${desk}/intraday`) json = {rows: [], top_buys: [], changed: []}
    else if (path === `${desk}/paper`) json = {reason: 'unavailable'}
    else {
      state.diagnostics.unexpectedRequests.push(`${method} ${path}`)
      entry.completed = true
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    json = reply?.body ?? json
    const status = reply?.status ?? 200
    if (status === 503) {
      state.expectedHttpErrors.push(`503 ${request.url()}`)
      state.expectedConsoleErrors.push('Failed to load resource: the server responded with a status of 503 (Service Unavailable)')
    }
    if (reply?.gate) {entry.held = true; await reply.gate.wait}
    if (path === `${desk}/personal-history`) {
      const result = json as {items: DeskPersonalReceipt[]; next_cursor: string | null}
      entry.returnedIds = result.items.map(item => item.id)
      entry.cursor = result.next_cursor
    } else if (id && !acknowledge && json) entry.returnedIds = [(json as DeskPersonalReceipt).id]
    entry.status = status
    await route.fulfill({status, json})
    entry.completed = true
  })
}

// Preserve every request and error even when a semantic or race assertion fails first.
async function finish(page: Page, state: Scenario, testInfo: TestInfo) {
  for (const gate of state.gates) gate.release()
  await expect.soft.poll(() => state.requests.filter(entry => entry.held && !entry.completed).length).toBe(0)
  await testInfo.attach('receipt-refresh-evidence', {body: JSON.stringify({requests: state.requests,
    diagnostics: state.diagnostics, expectedHttpErrors: state.expectedHttpErrors,
    expectedConsoleErrors: state.expectedConsoleErrors, paints: await paints(page)}, null, 2), contentType: 'application/json'})
  for (const [category, failures] of Object.entries(state.diagnostics)) {
    const expected = category === 'badResponses' ? state.expectedHttpErrors : category === 'consoleErrors' ? state.expectedConsoleErrors : []
    expect.soft(failures, `Browser ${category}`).toEqual(expected)
  }
}

const test = base.extend<{scenario: Scenario}>({
  // Isolate each race and always report diagnostics, including expected failure-boundary evidence.
  scenario: async ({page, baseURL}, use, testInfo) => {
    const state = scenario()
    await install(page, state, baseURL!)
    try {await use(state)} finally {await finish(page, state, testInfo)}
  },
})

// Reach the real desk and its mounted chart without opening the separate personal-history panel.
async function openChart(page: Page, state: Scenario) {
  await page.goto('/#desk')
  if (state.writable) await expect(page.getByLabel('Personal history recording status')).toContainText('Snapshot loaded into dashboard')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: 'AAPL', exact: true}).click()
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  await expect(chart.getByTestId('ticker-chart-canvas')).toBeVisible()
  await chart.getByRole('button', {name: 'Full history', exact: true}).click()
  if (state.writable) await chart.locator('summary').filter({hasText: /^Saved recommendations \(/}).click()
  await chart.evaluate(element => { (element as HTMLElement).dataset.receiptChartIdentity = 'original' })
  return chart
}

// Advance the existing quote-refresh timer so a generated receipt is accepted while the chart stays mounted.
async function publish(page: Page, state: Scenario, item: DeskPersonalReceipt) {
  state.current = item
  await page.clock.fastForward(15_000)
  await expect.poll(() => state.requests.some(entry => entry.path.endsWith('/mine') && entry.receiptId === item.id && entry.completed)).toBe(true)
}

// Count immutable snapshots independently of the intentionally grouped action transitions.
async function expectSnapshots(chart: ReturnType<Page['getByRole']>, count: number) {
  await expect(chart.getByText(`Saved recommendations (${count} saved record${count === 1 ? '' : 's'})`, {exact: true})).toBeVisible()
}

// Exact generated advice updates the same canvas before acknowledgement and does not reset paged history.
test('generated receipt updates the mounted chart before acknowledgement and preserves pages', async ({page, scenario: state}) => {
  const chart = await openChart(page, state)
  await expectSnapshots(chart, 20)
  await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
  await expectSnapshots(chart, 40)
  await expect.poll(async () => (await paints(page)).some(item => item.action === 'Sell')).toBe(true)
  const previousSell = Math.max(...(await paints(page)).filter(item => item.action === 'Sell').map(item => item.center))
  const item = saved(SELL_ID, '2026-09-24T14:00:15Z', 'Sell')
  const ack = deferred(state)
  state.ackReplies.set(item.id, [{gate: ack}])
  await page.evaluate(() => { (window as typeof window & {__receiptRefreshPaints: Paint[]}).__receiptRefreshPaints = [] })
  await publish(page, state, item)
  await expectSnapshots(chart, 41)
  await expect(page.getByLabel('Personal history recording status')).toContainText('confirming that it loaded')
  await expect(chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'}).locator('tbody tr')).toHaveCount(3)
  await expect(chart.getByLabel('Buy and Sell markers')).toContainText('Sell · Sep 24, 2026, 10:00:15 AM EDT')
  await expect.poll(async () => (await paints(page)).some(paint => paint.action === 'Sell' && paint.center > previousSell + 3)).toBe(true)
  await expect(chart).toHaveAttribute('data-receipt-chart-identity', 'original')
  expect(item.acknowledged_at).toBeNull()
  await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
  await expectSnapshots(chart, 61)
  await expect(chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'}).locator('tbody tr')).toHaveCount(4)
  await expect(chart.getByLabel('Saved recommendation history')).toContainText('No earlier saved records were reported by the last history page.')
  const pages = state.requests.filter(entry => entry.path.endsWith('/personal-history'))
  expect(pages.map(entry => new URLSearchParams(entry.query).get('before'))).toEqual([null, state.head.at(-1)!.id, state.older.at(-1)!.id])
  ack.release()
  await expect(page.getByLabel('Personal history recording status')).toContainText('Snapshot loaded into dashboard')
  await publish(page, state, item)
  await expectSnapshots(chart, 61)
  expect(state.requests.filter(entry => entry.method === 'GET' && entry.path.endsWith(`/${item.id}`))).toHaveLength(1)
})

for (const exactFirst of [true, false]) {
  // Initial page/exact completions may arrive in either order without losing or duplicating their shared receipt.
  test(`initial page and exact receipt merge when ${exactFirst ? 'exact' : 'page'} finishes first`, async ({page, scenario: state}) => {
    const initial = deferred(state)
    const exact = deferred(state)
    state.pageReplies.set('', [{gate: initial}])
    state.exactReplies.set(INITIAL_ID, [{gate: exact}])
    const chart = await openChart(page, state)
    await expect.poll(() => state.requests.filter(entry => entry.held).length).toBe(2)
    if (exactFirst) {
      exact.release()
      await expectSnapshots(chart, 1)
      initial.release()
    } else {
      initial.release()
      await expectSnapshots(chart, 20)
      exact.release()
    }
    await expectSnapshots(chart, 20)
    await expect(chart.getByText('Loading newly generated recommendations…', {exact: true})).not.toBeVisible()
    await expect(chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'}).locator('tbody tr')).toHaveCount(1)
    await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
    await expectSnapshots(chart, 40)
  })

  // A concurrent older-page read must not replace the newly accepted exact receipt or its cursor.
  test(`older page and new exact receipt merge when ${exactFirst ? 'exact' : 'page'} finishes first`, async ({page, scenario: state}) => {
    const chart = await openChart(page, state)
    await expectSnapshots(chart, 20)
    const older = deferred(state)
    const exact = deferred(state)
    state.pageReplies.set(state.head.at(-1)!.id, [{gate: older}])
    await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
    const item = saved(SELL_ID, '2026-09-24T14:00:15Z', 'Sell')
    state.exactReplies.set(item.id, [{gate: exact}])
    await publish(page, state, item)
    await expect.poll(() => state.requests.filter(entry => entry.held && !entry.completed).length).toBe(2)
    if (exactFirst) {
      exact.release()
      await expectSnapshots(chart, 21)
      older.release()
    } else {
      older.release()
      await expectSnapshots(chart, 40)
      exact.release()
    }
    await expectSnapshots(chart, 41)
    await expect(chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'}).locator('tbody tr')).toHaveCount(3)
    await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
    await expectSnapshots(chart, 61)
    expect(state.requests.filter(entry => entry.path.endsWith('/personal-history')).at(-1)!.query).toBe(`?limit=20&before=${state.older.at(-1)!.id}`)
  })
}

// Accepted receipts survive reverse completions, including an absent-ticker snapshot that breaks an action run.
test('out-of-order exact receipt completions retain both accepted action transitions', async ({page, scenario: state}) => {
  const chart = await openChart(page, state)
  await expectSnapshots(chart, 20)
  const first = saved(SELL_ID, '2026-09-24T14:00:15Z', 'Sell')
  const second = saved(BUY_ID, '2026-09-24T14:00:30Z', 'Buy')
  const slow = deferred(state)
  state.exactReplies.set(first.id, [{body: first, gate: slow}])
  await publish(page, state, first)
  await expect(chart.getByText('Loading newly generated recommendations…')).toBeVisible()
  await publish(page, state, second)
  await expectSnapshots(chart, 21)
  slow.release()
  await expectSnapshots(chart, 22)
  const rows = chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'}).locator('tbody tr')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(1)).toContainText('10:00:15 AM EDT')
  await expect(rows.nth(1).locator('td').nth(1)).toHaveText('Sell')
  await expect(rows.nth(2)).toContainText('10:00:30 AM EDT')
  await expect(rows.nth(2).locator('td').nth(1)).toHaveText('Buy')
  await expect(chart.getByText('Loading newly generated recommendations…')).not.toBeVisible()
  await expect(chart).toHaveAttribute('data-receipt-chart-identity', 'original')
  const absent = saved(receiptId(5), '2026-09-24T14:00:45Z', 'Hold')
  absent.payload.rows = {MSFT: absent.payload.rows.AAPL}
  await publish(page, state, absent)
  await expectSnapshots(chart, 23)
  await expect(rows).toHaveCount(3)
  const laterBuy = saved(receiptId(6), '2026-09-24T14:01:00Z', 'Buy')
  await publish(page, state, laterBuy)
  await expectSnapshots(chart, 24)
  await expect(rows).toHaveCount(4)
  await expect(rows.last()).toContainText('10:01:00 AM EDT')
  await expect(rows.last().locator('td').nth(1)).toHaveText('Buy')
})

// Updating only an accepted receipt must preserve the chart instance and the user's chosen zoom.
test('receipt-only update preserves actual canvas identity and zoomed candle geometry', async ({page, scenario: state}) => {
  const chart = await openChart(page, state)
  await expectSnapshots(chart, 20)
  await page.clock.runFor(100)
  const canvas = chart.getByTestId('ticker-chart-canvas').locator('canvas').first()
  const original = await canvas.elementHandle()
  expect(original).not.toBeNull()
  const beforeZoom = await candleGeometry(page)
  expect(beforeZoom.length).toBeGreaterThan(0)
  const bounds = await chart.getByTestId('ticker-chart-canvas').boundingBox()
  expect(bounds).not.toBeNull()
  await page.mouse.move(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2)
  await page.evaluate(() => { (window as typeof window & {__receiptCandlePaints: CandlePaint[]}).__receiptCandlePaints = [] })
  await page.mouse.wheel(0, -360)
  await page.clock.runFor(100)
  await expect.poll(() => candleGeometry(page)).not.toEqual([])
  const zoomed = await candleGeometry(page)
  expect(zoomed).not.toEqual(beforeZoom)
  const pricesBefore = state.requests.filter(entry => entry.path.endsWith('/chart/AAPL')).length
  await page.evaluate(() => { (window as typeof window & {__receiptCandlePaints: CandlePaint[]}).__receiptCandlePaints = [] })
  await publish(page, state, saved(SELL_ID, '2026-09-24T14:00:15Z', 'Sell'))
  await expectSnapshots(chart, 21)
  await expect(chart.getByLabel('Buy and Sell markers')).toContainText('Sell · Sep 24, 2026')
  await page.clock.runFor(100)
  expect(state.requests.filter(entry => entry.path.endsWith('/chart/AAPL'))).toHaveLength(pricesBefore)
  expect.soft(await original!.evaluate(element => element.isConnected), 'The original lightweight-chart canvas remains mounted').toBe(true)
  expect.soft(await canvas.evaluate((element, previous) => element === previous, original), 'Receipt refresh retains the actual canvas node').toBe(true)
  await expect.poll(() => candleGeometry(page)).not.toEqual([])
  expect.soft(await candleGeometry(page), 'Receipt refresh preserves zoomed horizontal candle positions and widths').toEqual(zoomed)
})

for (const failure of ['http', 'mismatched ID'] as const) {
  // A failed exact read preserves old evidence, reports the gap, and retries only the rejected receipt.
  test(`${failure} exact read is disclosed and recovers through retry and explicit reload`, async ({page, scenario: state}) => {
    const chart = await openChart(page, state)
    await expectSnapshots(chart, 20)
    await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
    await expectSnapshots(chart, 40)
    const item = saved(SELL_ID, '2026-09-24T14:00:15Z', 'Sell')
    state.exactReplies.set(item.id, [failure === 'http' ? {status: 503, body: {detail: 'Synthetic receipt read unavailable'}}
      : {body: saved(FOREIGN_ID, item.generated_at, 'Sell')}])
    await publish(page, state, item)
    await expect(chart.getByRole('status').filter({hasText: 'Some newly generated recommendation reads failed.'})).toBeVisible()
    await expectSnapshots(chart, 40)
    await expect(chart.getByLabel('Buy and Sell markers')).not.toContainText('Sep 24, 2026')
    await chart.getByRole('button', {name: 'Retry new recommendations'}).click()
    await expectSnapshots(chart, 41)
    await expect(chart.getByRole('status').filter({hasText: 'Some newly generated recommendation reads failed.'})).not.toBeVisible()
    await expect(chart.getByLabel('Buy and Sell markers')).toContainText('Sell · Sep 24, 2026')
    expect(state.requests.filter(entry => entry.method === 'GET' && entry.path.endsWith(`/${item.id}`))).toHaveLength(2)
    const head = [item, ...state.head.slice(0, 19)]
    state.pageReplies.set('', [{body: {items: head, next_cursor: null,
      retention: {acknowledged_days: 90, unacknowledged_hours: 24}, limitations: []}}])
    await chart.getByRole('button', {name: 'Reload saved history'}).click()
    await expectSnapshots(chart, 20)
    await expect(chart.getByLabel('Buy and Sell markers')).not.toContainText('Sep 22, 2026')
    await expect(chart.getByRole('button', {name: 'Load earlier recommendations'})).not.toBeVisible()
    await expect(chart.getByLabel('Saved recommendation history')).toContainText('No earlier saved records were reported by the last history page.')
    await expect(chart).toHaveAttribute('data-receipt-chart-identity', 'original')
  })
}

// A later accepted mine response suppresses an older response before it can request or paint that receipt.
test('superseded mine response cannot introduce its rejected receipt into the chart', async ({page, scenario: state}) => {
  const chart = await openChart(page, state)
  await expectSnapshots(chart, 20)
  const rejected = saved(SELL_ID, '2026-09-24T14:00:15Z', 'Sell')
  const accepted = saved(BUY_ID, '2026-09-24T14:00:30Z', 'Buy')
  const slowMine = deferred(state)
  state.mineReplies.push({body: mine(rejected), gate: slowMine})
  await page.clock.fastForward(15_000)
  await expect.poll(() => state.requests.some(entry => entry.path.endsWith('/mine') && entry.receiptId === rejected.id && entry.held)).toBe(true)
  state.current = accepted
  // Foreground resumption runs the independent poll while the quote-refresh mine remains in flight.
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await expectSnapshots(chart, 21)
  await expect(page.getByRole('region', {name: 'Latest available grade', exact: true})).toContainText(`Accepted Buy receipt ${accepted.id}`)
  slowMine.release()
  await expect.poll(() => state.requests.filter(entry => entry.held && !entry.completed).length).toBe(0)
  await expectSnapshots(chart, 21)
  await expect(chart.getByLabel('Buy and Sell markers')).not.toContainText('Sell · Sep 24, 2026')
  expect(state.requests.filter(entry => entry.path.includes(`/personal-history/${rejected.id}`))).toEqual([])
})

// Signing into a different read-only scope tears down private reads without leaking them into the new chart.
test('pending receipts cannot survive an owner and permission change through sign-in', async ({page, scenario: state}) => {
    const chart = await openChart(page, state)
    await expectSnapshots(chart, 20)
    const oldPage = deferred(state)
    state.pageReplies.set(state.head.at(-1)!.id, [{gate: oldPage}])
    await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
    const oldExact = deferred(state)
    const item = saved(SELL_ID, '2026-09-24T14:00:15Z', 'Sell')
    state.exactReplies.set(item.id, [{gate: oldExact}])
    await publish(page, state, item)
    await expect.poll(() => state.requests.filter(entry => entry.held && !entry.completed).length).toBe(2)
    // Exercise the application's existing expired-session boundary, not a direct React state mutation.
    await page.evaluate(() => window.dispatchEvent(new Event('anios:unauthorized')))
    await expect(page.getByLabel('Username', {exact: true})).toBeVisible()
    await expect(chart).not.toBeVisible()
    const boundary = state.requests.length
    state.writable = false
    state.owner = 'receipt.viewer'
    await page.getByLabel('Username', {exact: true}).fill(state.owner)
    await page.getByLabel('Password', {exact: true}).fill('synthetic-fixture-only')
    await page.getByRole('button', {name: 'Continue', exact: true}).click()
    await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: 'AAPL', exact: true}).click()
    const readonlyChart = page.getByRole('region', {name: 'AAPL price chart'})
    await expect(readonlyChart.getByTestId('ticker-chart-canvas')).toBeVisible()
    oldExact.release()
    oldPage.release()
    await expect.poll(() => state.requests.filter(entry => entry.held && !entry.completed).length).toBe(0)
    await expect(readonlyChart.getByLabel('Saved recommendation history')).not.toBeVisible()
    await expect(readonlyChart.getByRole('checkbox', {name: 'Buy / Sell', exact: true})).not.toBeVisible()
    await expect(page.getByLabel('Personal history recording status')).not.toBeVisible()
    const after = state.requests.slice(boundary)
    expect(after.filter(entry => entry.path.includes('/personal-history'))).toEqual([])
    expect(after.filter(entry => entry.path.includes('/market/')).every(entry => entry.path.startsWith(`/api/v1/market/${state.owner}/desk`))).toBe(true)
    expect(after.filter(entry => entry.path.endsWith('/mine')).every(entry => (entry.body as {record_history: boolean}).record_history === false)).toBe(true)
    await page.evaluate(() => {
      const observed = window as typeof window & {__receiptRefreshPaints: Paint[]; __receiptChartPaintCount: number}
      observed.__receiptRefreshPaints = []
      observed.__receiptChartPaintCount = 0
    })
    await readonlyChart.getByRole('button', {name: 'Full history', exact: true}).click()
    await expect(readonlyChart.getByRole('button', {name: 'Full history', exact: true})).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => page.evaluate(() => (window as typeof window & {__receiptChartPaintCount: number}).__receiptChartPaintCount)).toBeGreaterThan(0)
    expect(await paints(page)).toEqual([])
})
