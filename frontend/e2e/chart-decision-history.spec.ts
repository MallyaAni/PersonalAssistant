import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'chart-decisions-fixture'
const POLICY = 'graded-equal-weight/4'
const NOTE = 'decisions at the close, filled at the next open; sizes are % of equity'
type CanvasState = Window & {__markerDraws: {text: string; timeframe: string | null}[]}
const REBALANCE_NOTE = 'reset sessions from the paper state\'s rebalance clock and the nightly records; add/trim markers only on those, target drift between resets is not traded'
type DecisionRow = {date: string; grade: string; action?: string; target_weight?: number; delta_weight?: number; rebalance?: boolean}

// The equal-weight policy's replayed decisions in one name, as the nightly
// classifies them: it enters the A/A+ book (a buy at 1/11), its target drifts
// with the count of A/A+ names on a session that is not a reset (a hold, not an
// add), the reset brings it to 12.5% (a rebalance of +2.5 points), it is
// downgraded and leaves the book (a sell), then nothing. The paper account's
// two real fills come a session after the entry and the exit.
const ROWS: DecisionRow[] = [
  {date: '2026-09-14', grade: 'A+', action: 'buy', target_weight: 0.0909, delta_weight: 0.0909, rebalance: false},
  {date: '2026-09-15', grade: 'A+', action: 'hold', target_weight: 0.1, delta_weight: 0.0091, rebalance: false},
  {date: '2026-09-16', grade: 'A+', action: 'add', target_weight: 0.125, delta_weight: 0.025, rebalance: true},
  {date: '2026-09-17', grade: 'B', action: 'sell', target_weight: 0, delta_weight: -0.125, rebalance: false},
  {date: '2026-09-18', grade: 'B', action: 'hold', target_weight: 0, delta_weight: 0, rebalance: false},
]
// A sizing policy's decisions (the /3 reading): every target move is an order,
// so the add on Sep 16 is written as the level it leads to.
const SIZING_ROWS: DecisionRow[] = [
  {date: '2026-09-14', grade: 'A', action: 'buy', target_weight: 0.14, delta_weight: 0.14},
  {date: '2026-09-15', grade: 'A', action: 'hold', target_weight: 0.14, delta_weight: 0},
  {date: '2026-09-16', grade: 'A', action: 'add', target_weight: 0.2, delta_weight: 0.06},
  {date: '2026-09-17', grade: 'B', action: 'sell', target_weight: 0, delta_weight: -0.2},
  {date: '2026-09-18', grade: 'B', action: 'hold', target_weight: 0, delta_weight: 0},
]
const FILLS = [
  {date: '2026-09-15', side: 'buy', qty: 63, price: 224.81},
  {date: '2026-09-18', side: 'sell', qty: 63, price: 230.5},
]

// Serve one name's history with replayed decisions and paper fills behind the real chart, and record its paint calls.
async function install(page: Page, frontendURL: string, options: {fills?: (typeof FILLS[number] & {kind?: string})[]; policy?: string; rows?: DecisionRow[]; rebalanceNote?: string | null} = {}) {
  const rebalanceNote = options.rebalanceNote === undefined ? REBALANCE_NOTE : options.rebalanceNote
  const history = {
    ticker: 'AAPL', asof: '2026-09-18', horizon: 20,
    policy: options.policy ?? POLICY, decision_note: NOTE,
    ...(rebalanceNote === null ? {} : {rebalance_note: rebalanceNote, reset_sessions: ['2026-09-16']}),
    rows: (options.rows ?? ROWS).map(row => ({...row, said: true, votes: 3, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, earnings: false})),
    fills: options.fills ?? FILLS,
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
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && /^(Buy |Add |Trim |Rebalance |Sell$|Filled |Saved grade)/.test(args[0])) {
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
    else if (url.pathname === `${base}/mine`) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Waiting'}}}}
    else if (url.pathname === `${base}/personal-history`) json = {items: [], next_cursor: null}
    else if (url.pathname === `${base}/history/AAPL`) json = history
    else if (url.pathname === `${base}/chart/AAPL`) {
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

for (const viewport of [{width: 1280, height: 900}, {width: 390, height: 844}]) {
  // Under the equal-weight policy the markers show what the executor does: the entry as a buy at its
  // target, the reset as a rebalance of the move it places, the downgrade as a sell; the target drift on
  // a session that is not a reset draws nothing. The fills are drawn beside them and the legend says so.
  test(`chart lists and draws the policy decisions and paper fills at ${viewport.width}px`, async ({page, baseURL}, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await install(page, baseURL!)
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      const decisions = chart.locator('[aria-label="AAPL decisions"]')
      // The stance today comes first, from the newest row, then the trades newest first with the close they were decided at.
      await expect(decisions).toContainText('Now: Hold 0%')
      const items = decisions.locator('ul').first().locator('li')
      await expect(items).toHaveCount(3)
      await expect(items.nth(0)).toHaveText('Sep 17 · Sell · close $110.00')
      await expect(items.nth(1)).toHaveText('Sep 16 · Rebalance +2.5% · close $110.00')
      await expect(items.nth(2)).toHaveText('Sep 14 · Buy 9.1% · close $110.00')
      await expect(decisions).toContainText('Buy 9.1%')
      await expect(decisions).toContainText('Sell')
      // The drift on Sep 15 is not an add, and the words add/trim do not appear.
      await expect(decisions).not.toContainText('Sep 15')
      await expect(decisions).not.toContainText('Add')
      await expect(decisions).not.toContainText('Trim')
      // The fills are listed likewise, newest first.
      const fills = chart.locator('[aria-label="AAPL paper fills"] li')
      await expect(fills).toHaveCount(2)
      await expect(fills.nth(0)).toHaveText('Sep 18 · Filled sell 63 @ $230.50')
      await expect(fills.nth(1)).toHaveText('Sep 15 · Filled buy 63 @ $224.81')
      // The caption names the policy and dates the decision to the close and the fill to the next open,
      // and the legend says what a marker means and how the reset sessions were found.
      await expect(chart.locator('[aria-label="Policy decision note"]')).toHaveText(`${POLICY}: ${NOTE}`)
      const legend = chart.locator('[aria-label="Policy marker legend"]')
      await expect(legend).toContainText('Buy = enters the A/A+ book')
      await expect(legend).toContainText('Rebalance ±% = the reset trades it')
      await expect(legend).toContainText('drift between resets is not traded')
      await expect(legend).toContainText('Reset sessions from the paper state')
      // The same words reach the real canvas as markers, beside the grade change; no add or trim is drawn.
      await expect.poll(() => drawn(page, 'D')).toEqual(expect.arrayContaining(['Buy 9.1%', 'Rebalance +2.5%', 'Sell', 'Filled 63 @ 224.81', 'Filled 63 @ 230.50', 'Saved grade: A+→B']))
      expect((await drawn(page, 'D')).filter(text => /^(Add|Trim) /.test(text))).toEqual([])
      // Both layers have their own switch, on by default.
      const policyBox = chart.getByRole('checkbox', {name: 'Policy buy/sell'})
      const fillBox = chart.getByRole('checkbox', {name: 'Paper fills'})
      await expect(policyBox).toBeChecked()
      await expect(fillBox).toBeChecked()
      // Unchecking removes the markers and nothing else: the list is the decisions, not the markers.
      await policyBox.uncheck()
      await fillBox.uncheck()
      await page.evaluate(() => {(window as unknown as CanvasState).__markerDraws = []})
      await chart.getByRole('button', {name: 'W', exact: true}).click()
      await expect(chart).toContainText('3 weeks loaded')
      await expect.poll(() => drawn(page, 'W')).toContain('Saved grade: A→B')
      expect(await drawn(page, 'W')).not.toEqual(expect.arrayContaining(['Buy 9.1%']))
      expect(await drawn(page, 'W')).not.toEqual(expect.arrayContaining(['Filled 63 @ 224.81']))
      await expect(decisions).toContainText('Now: Hold 0%')
      await expect(decisions).toContainText('Buy 9.1%')
      await expect(decisions).toContainText('Sell')
      await expect(chart.locator('[aria-label="AAPL paper fills"] li')).toHaveCount(2)
      // The close is a daily reading; a weekly candle is not the decision's close, so it is not claimed.
      await expect(items.nth(2)).toHaveText('Sep 14 · Buy 9.1%')
      // Checking again draws them on the weekly candles too.
      await policyBox.check()
      await expect.poll(() => drawn(page, 'W')).toEqual(expect.arrayContaining(['Buy 9.1%', 'Sell']))
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await chart.screenshot({path: testInfo.outputPath('decision-history.png')})
    } finally {await finish(testInfo, fixture)}
  })

  // Without fills there is no fill switch and no fill list; the decisions still show.
  test(`chart hides the paper fills switch when the account has none at ${viewport.width}px`, async ({page, baseURL}, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await install(page, baseURL!, {fills: []})
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      await expect(chart.getByRole('checkbox', {name: 'Policy buy/sell'})).toBeChecked()
      await expect(chart.getByRole('checkbox', {name: 'Paper fills'})).toHaveCount(0)
      await expect(chart.locator('[aria-label="AAPL paper fills"]')).toHaveCount(0)
      await expect(chart.locator('[aria-label="AAPL decisions"]')).toContainText('Buy 9.1%')
      await expect(chart).not.toContainText('Filled')
    } finally {await finish(testInfo, fixture)}
  })

  // A history replayed under a sizing policy keeps the weight-move reading: the add is the level it
  // leads to, and there is no equal-weight legend to mislead about resets.
  test(`chart keeps the sizing reading for another policy's history at ${viewport.width}px`, async ({page, baseURL}, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await install(page, baseURL!, {policy: 'inverse-volatility/3', rows: SIZING_ROWS, rebalanceNote: null})
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      const items = chart.locator('[aria-label="AAPL decisions"] ul').first().locator('li')
      await expect(items).toHaveCount(3)
      await expect(items.nth(0)).toHaveText('Sep 17 · Sell · close $110.00')
      await expect(items.nth(1)).toHaveText('Sep 16 · Add →20% · close $110.00')
      await expect(items.nth(2)).toHaveText('Sep 14 · Buy 14% · close $110.00')
      await expect(chart.locator('[aria-label="Policy decision note"]')).toHaveText(`inverse-volatility/3: ${NOTE}`)
      await expect(chart.locator('[aria-label="Policy marker legend"]')).toHaveCount(0)
      await expect.poll(() => drawn(page, 'D')).toEqual(expect.arrayContaining(['Buy 14%', 'Add →20%', 'Sell']))
      expect((await drawn(page, 'D')).filter(text => text.startsWith('Rebalance'))).toEqual([])
    } finally {await finish(testInfo, fixture)}
  })

  // A redeploy fill (idle cash sent back to the targets) is listed and drawn as such, and the fills
  // switch says the colour that tells it apart; a history with no clock on file says no reset is known.
  test(`chart tells a redeploy fill apart and says when no reset is known at ${viewport.width}px`, async ({page, baseURL}, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await install(page, baseURL!, {
      fills: [...FILLS, {date: '2026-09-16', side: 'buy', qty: 7, price: 91, kind: 'redeploy'}],
      rebalanceNote: 'no rebalance clock on file: no session is marked as a reset, so the series shows entries and exits only',
    })
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      await expect(chart.getByRole('checkbox', {name: 'Paper fills (purple: redeploy)'})).toBeChecked()
      const fills = chart.locator('[aria-label="AAPL paper fills"] li')
      await expect(fills).toHaveCount(3)
      await expect(fills.nth(1)).toHaveText('Sep 16 · Filled buy 7 @ $91.00 · redeploy')
      await expect(fills.nth(2)).toHaveText('Sep 15 · Filled buy 63 @ $224.81')
      await expect(chart.locator('[aria-label="Policy marker legend"]')).toContainText('No rebalance clock on file')
      await expect.poll(() => drawn(page, 'D')).toEqual(expect.arrayContaining(['Filled 7 @ 91.00 (redeploy)', 'Filled 63 @ 224.81']))
    } finally {await finish(testInfo, fixture)}
  })
}
