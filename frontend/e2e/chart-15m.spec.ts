import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'chart-15m-fixture'
const POLICY = 'graded-equal-weight/4'
const NOTE = 'decisions at the close, filled at the next open; sizes are % of equity'
type CanvasState = Window & {__markerDraws: {text: string; timeframe: string | null}[]}
const REBALANCE_NOTE = 'reset sessions from the paper state\'s rebalance clock and the nightly records; add/trim markers only on those, target drift between resets is not traded'
type DecisionRow = {date: string; grade: string; action?: string; target_weight?: number; delta_weight?: number; rebalance?: boolean}

// The equal-weight policy's replayed decisions in one name: a buy decided on Monday
// (the name enters the A/A+ book), then a hold on Tuesday whose target drift is not a
// trade, with the paper account's entry fill and a redeploy fill at Tuesday's open.
const ROWS: DecisionRow[] = [
  {date: '2026-09-14', grade: 'A', action: 'buy', target_weight: 0.14, delta_weight: 0.14, rebalance: false},
  {date: '2026-09-15', grade: 'A', action: 'hold', target_weight: 0.15, delta_weight: 0.01, rebalance: false},
]
const FILLS = [
  {date: '2026-09-15', side: 'buy', qty: 63, price: 224.81},
  {date: '2026-09-15', side: 'buy', qty: 7, price: 225.1, kind: 'redeploy'},
]
// The two sessions of fifteen-minute bars the 15m view serves, in September (EDT).
const SESSIONS = ['2026-09-14', '2026-09-15']

// One session's fifteen-minute bars: the 26 regular slots from 09:30 New York
// plus the closing-auction bar at 16:00, stamped with the EDT offset.
function sessionBars(date: string) {
  const bars = []
  for (let slot = 0; slot < 26; slot += 1) {
    const minutes = 9 * 60 + 30 + slot * 15
    const hh = String(Math.floor(minutes / 60)).padStart(2, '0')
    const mm = String(minutes % 60).padStart(2, '0')
    bars.push({time: `${date}T${hh}:${mm}:00-04:00`, date, open: 100 + slot, high: 101 + slot, low: 99 + slot, close: 100.5 + slot, volume: 1000})
  }
  bars.push({time: `${date}T16:00:00-04:00`, date, open: 126, high: 126.5, low: 125.5, close: 126, volume: 5000, auction: true})
  return bars
}

// Serve one name's history and both chart timeframes behind the real chart, and record its paint calls.
async function install(page: Page, frontendURL: string) {
  const history = {
    ticker: 'AAPL', asof: '2026-09-15', horizon: 20,
    policy: POLICY, decision_note: NOTE, rebalance_note: REBALANCE_NOTE, reset_sessions: [],
    rows: ROWS.map(row => ({...row, said: true, votes: 3, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, earnings: false})),
    fills: FILLS,
    backtest: null, recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false},
  }
  const original = JSON.stringify(history)
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  const reads: string[] = []
  // Keep runtime errors visible even when a text assertion passes.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // Fail on exceptions from partially rendered charts.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Record incomplete required requests instead of accepting silent fallbacks.
  page.on('requestfailed', request => diagnostics.failedRequests.push(request.url()))
  // Record unsuccessful responses independently of browser exceptions.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date('2026-09-24T14:00:00Z')})
  // Observe the real canvas text of every marker without replacing chart rendering.
  await page.addInitScript(() => {
    localStorage.setItem('anios.theme', 'light')
    const state = window as unknown as CanvasState
    state.__markerDraws = []
    const fillText = CanvasRenderingContext2D.prototype.fillText
    // Preserve every production paint call while recording marker labels and the selected timeframe.
    CanvasRenderingContext2D.prototype.fillText = function (this: CanvasRenderingContext2D, ...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && /^(Buy |Add |Trim |Rebalance |Sell|Filled |Saved grade)/.test(args[0])) {
        const timeframe = this.canvas.closest('section')?.querySelector('[aria-label="Chart timeframe"] [aria-pressed="true"]')?.textContent ?? null
        state.__markerDraws.push({text: args[0], timeframe})
      }
      return fillText.apply(this, args)
    }
  })
  // Admit only named synthetic reads; no request reaches a real account and nothing is written.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const base = `/api/v1/market/${USER}/desk`
    // The panel reads its decision rows with a POST (recording or not); every other write is refused.
    const mineRead = url.pathname === `${base}/mine` && request.method() === 'POST'
    if (request.method() !== 'GET' && !mineRead) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids writes'}})
    }
    reads.push(`${url.pathname}${url.search}`)
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, is_admin: false, desk_access: true, desk_write: true}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest: {session: '2026-09-24', written: '2026-09-24T00:00:00Z', regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: 'B', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: ['2026-09-24']}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = {session: '2026-09-24', rows: [], grades_live: {}, history_receipt: {status: 'not_requested'},
      decisions: {session: '2026-09-24', written: '2026-09-24T00:00:00Z', rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, executable: false, reason: 'Waiting'}}}}
    else if (url.pathname === `${base}/live`) json = {as_of: '2026-09-24T14:00:00Z', quotes: {AAPL: {last: 110, bar: '2026-09-24T13:45:00Z'}}, technical: {}, technical_detail: {}}
    else if (url.pathname === `${base}/session-prices`) json = {as_of: '2026-09-24T14:00:00Z', session: 'regular', signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/personal-history`) json = {items: [], next_cursor: null}
    else if (url.pathname === `${base}/history/AAPL`) json = history
    else if (url.pathname === `${base}/chart/AAPL` && url.searchParams.get('timeframe') === '15m') {
      // The last two sessions of raw fifteen-minute bars with the three marker lists the server computes.
      const sessions = Number(url.searchParams.get('sessions') ?? '10')
      const bars = SESSIONS.flatMap(sessionBars)
      json = {ticker: 'AAPL', timeframe: '15m', adjusted: false, basis: 'raw prices as printed (consolidated SIP)', sessions: SESSIONS.length, sessions_requested: sessions,
        policy: POLICY, rebalance_note: REBALANCE_NOTE,
        bars, overlays: {session_vwap: bars.map(bar => bar.close)}, levels: {}, entries: [], data_status: 'complete', data_reason: null, missing_sessions: [], quote_bar: null, last_bar_complete: true,
        decisions: [{time: '2026-09-14T15:45:00-04:00', date: '2026-09-14', action: 'buy', target_weight: 0.14, label: 'Buy 14% decided at the close', rebalance: false}],
        fills_at: [{time: '2026-09-15T09:30:00-04:00', date: '2026-09-15', action: 'buy', target_weight: 0.14, label: 'Buy 14% fills at the open', rebalance: false}],
        fills: [
          {time: '2026-09-15T09:30:00-04:00', date: '2026-09-15', side: 'buy', qty: 63, price: 224.81, label: 'Filled buy 63 @ 224.81'},
          {time: '2026-09-15T09:30:00-04:00', date: '2026-09-15', side: 'buy', qty: 7, price: 225.1, label: 'Filled buy 7 @ 225.10 (redeploy)', kind: 'redeploy'},
        ]}
    } else if (url.pathname === `${base}/chart/AAPL`) {
      const weekly = url.searchParams.get('timeframe') === 'weekly'
      const dates = weekly ? ['2026-09-11', '2026-09-18', '2026-09-24'] : ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-24']
      const series = (value: number) => dates.map(() => value)
      json = {ticker: 'AAPL', timeframe: weekly ? 'weekly' : 'daily', adjusted: true, basis: 'synthetic adjusted prices', sessions: dates.length, bars: dates.map(date => ({date, open: 100, high: 120, low: 90, close: 110, volume: 100})), overlays: weekly
        ? {ema9: series(100), ema21: series(125)}
        : {ema9: series(100), ema21: series(125), ema50: series(110), ema200: series(100), band_upper: series(125), band_lower: series(0)},
      levels: weekly ? {} : {high_52w: series(140), low_52w: series(80)}, entries: [], data_status: 'complete', quote_bar: '2026-09-24T13:45:00Z', last_bar_complete: false}
    } else if (url.pathname === `${base}/entries` || url.pathname === `${base}/intraday`) json = {rows: [], top_buys: [], changed: []}
    else if (url.pathname === `${base}/paper`) json = {reason: 'unavailable'}
    else if (url.pathname === `${base}/earnings/AAPL`) json = {symbol: 'AAPL', read: null}
    else if (url.pathname === `${base}/live/read/AAPL`) json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified request'}})
    }
    return route.fulfill({json})
  })
  return {history, original, diagnostics, reads}
}

// Persist strict browser diagnostics and confirm rendering never rewrote the served history.
async function finish(testInfo: TestInfo, fixture: Awaited<ReturnType<typeof install>>) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(fixture.diagnostics, null, 2), contentType: 'application/json'})
  await testInfo.attach('source-and-reads', {body: JSON.stringify({history: fixture.history, reads: fixture.reads}, null, 2), contentType: 'application/json'})
  for (const [category, errors] of Object.entries(fixture.diagnostics)) expect.soft(errors, category).toEqual([])
  expect(JSON.stringify(fixture.history)).toBe(fixture.original)
}

// Read the marker texts the canvas actually drew under one timeframe.
const drawn = (page: Page, frame: string) => page.evaluate(selected =>
  (window as unknown as CanvasState).__markerDraws.filter(row => row.timeframe === selected).map(row => row.text), frame)

// The chart requests made for the 15m view, in order.
const intradayReads = (fixture: Awaited<ReturnType<typeof install>>) =>
  fixture.reads.filter(read => read.startsWith(`/api/v1/market/${USER}/desk/chart/AAPL?`) && read.includes('timeframe=15m'))

for (const viewport of [{width: 1280, height: 900}, {width: 390, height: 844}]) {
  // The 15m view draws the raw fifteen-minute bars with the decision, its fill time and the real fill marked at the bar they happen on.
  test(`chart shows fifteen-minute bars with the decision and fill times marked at ${viewport.width}px`, async ({page, baseURL}, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await install(page, baseURL!)
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      // The daily view is the default and loads first; the sessions selector belongs to 15m alone.
      await expect(chart).toContainText('6 sessions loaded')
      await expect(chart.getByRole('group', {name: 'Chart sessions'})).toHaveCount(0)
      await chart.getByRole('button', {name: '15m', exact: true}).click()
      // The first 15m read asks for the default ten sessions.
      await expect.poll(() => intradayReads(fixture)).toHaveLength(1)
      expect(intradayReads(fixture)[0]).toContain('sessions=10')
      // The caption names the resolution and the basis line the raw prices.
      const caption = chart.locator('[aria-label="Fifteen-minute chart caption"]')
      await expect(caption).toContainText('fifteen-minute (15m) bars')
      await expect(caption).toContainText('2 complete sessions')
      await expect(caption).toContainText('54 bars')
      await expect(chart.locator('[aria-label="Fifteen-minute price basis"]')).toContainText('raw prices as printed (consolidated SIP)')
      // The decision list stays, now saying when in the session the decision is made.
      const decisions = chart.locator('[aria-label="AAPL decisions"]')
      await expect(decisions).toContainText('Now: Hold 15%')
      const listed = decisions.locator('ul').first().locator('li')
      await expect(listed).toHaveCount(1)
      await expect(listed.nth(0)).toHaveText('Sep 14 · Buy 14% · decided at the close')
      // The redeploy fill is listed as such and the fills switch names its colour.
      await expect(chart.locator('[aria-label="AAPL paper fills"] li')).toHaveText(['Sep 15 · Filled buy 7 @ $225.10 · redeploy', 'Sep 15 · Filled buy 63 @ $224.81'])
      await expect(chart.getByRole('checkbox', {name: 'Paper fills (purple: redeploy)'})).toBeChecked()
      await expect(chart.locator('[aria-label="Policy marker legend"]')).toContainText('Reset sessions from the paper state')
      // The same words reach the real canvas: the decision on the 15:45 bar, where it fills, and the fills themselves.
      await expect.poll(() => drawn(page, '15m')).toEqual(expect.arrayContaining(['Buy 14% decided at the close', 'Buy 14% fills at the open', 'Filled buy 63 @ 224.81', 'Filled buy 7 @ 225.10 (redeploy)']))
      // Grade changes are session readings and are not drawn on the bars.
      expect(await drawn(page, '15m')).not.toEqual(expect.arrayContaining(['Saved grade: A→B']))
      await expect(chart).toContainText('not marked on fifteen-minute bars')
      // The sessions selector re-reads the chart with the chosen count.
      const sessions = chart.getByRole('group', {name: 'Chart sessions'})
      await expect(sessions.getByRole('button', {name: '10', exact: true})).toHaveAttribute('aria-pressed', 'true')
      await sessions.getByRole('button', {name: '20', exact: true}).click()
      await expect.poll(() => intradayReads(fixture)).toHaveLength(2)
      expect(intradayReads(fixture)[1]).toContain('sessions=20')
      await expect(sessions.getByRole('button', {name: '20', exact: true})).toHaveAttribute('aria-pressed', 'true')
      await expect(caption).toContainText('54 bars')
      // The policy switch removes the timed decision markers and nothing else.
      const policyBox = chart.getByRole('checkbox', {name: 'Policy buy/sell'})
      await policyBox.uncheck()
      await page.evaluate(() => {(window as unknown as CanvasState).__markerDraws = []})
      await sessions.getByRole('button', {name: '5', exact: true}).click()
      await expect.poll(() => intradayReads(fixture)).toHaveLength(3)
      await expect.poll(() => drawn(page, '15m')).toContain('Filled buy 63 @ 224.81')
      expect(await drawn(page, '15m')).not.toEqual(expect.arrayContaining(['Buy 14% decided at the close']))
      await expect(decisions).toContainText('Buy 14%')
      // Back on daily the sessions selector goes away and the daily markers return.
      await chart.getByRole('button', {name: 'D', exact: true}).click()
      await expect(chart).toContainText('6 sessions loaded')
      await expect(chart.getByRole('group', {name: 'Chart sessions'})).toHaveCount(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await chart.screenshot({path: testInfo.outputPath('chart-15m.png')})
    } finally {await finish(testInfo, fixture)}
  })
}
