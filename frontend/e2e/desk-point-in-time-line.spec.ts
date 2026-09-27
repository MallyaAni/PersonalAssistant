import {expect, test, type Locator, type Page, type TestInfo} from '@playwright/test'

// Browser acceptance for the track record's point-in-time line: the same
// rules replayed on the names the book could have held on each session,
// drawn beside the stored simulation with its own CAGR, and explained in
// words when the nightly could not draw it. The curve is a read-only view
// of what the nightly wrote, so every endpoint is answered from fixtures.

const USER = 'ani.mallya'
const SESSION = '2026-09-25'
const WRITTEN = '2026-09-25T21:05:00Z'
const NOW = '2026-09-26T15:35:00Z'
const BAR = '2026-09-26T15:15:00Z'
const STANCES = {fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: 0}
const DATES = ['2026-01-02', '2026-03-02', '2026-05-01', '2026-07-01', SESSION]
const PUBLISHED_LABEL = 'stored simulation'
const POINT_IN_TIME_LABEL = 'same rules, names known at the time'
const POINT_IN_TIME_NOTE = 'point-in-time line not drawn: sessions differ from the published run'
const CHART_NAME = "The desk's track record against SPY and QQQ"
type Backtest = Record<string, unknown>

// The nightly's backtest block with both lines: the published rules and the
// same rules on the point-in-time book, deliberately far apart so a test
// cannot pass by reading one figure for the other.
function backtestWithPointInTime(): Backtest {
  return {
    label: 'the rules, walked forward', asof: SESSION, dates: DATES,
    funding_model: 'cash-at-fill-v1', strategy_policy: 'cash-bounded-breakout-rotation/3', fundamentals_source: 'fundamentals-features/2',
    rules: [0, .06, .12, .19, .27],
    rules_point_in_time: [0, .02, .03, .05, .08],
    spy: [0, .02, .01, .05, .09],
    qqq: [0, .03, .04, .08, .13],
    stats: {cagr: .31, volatility: .22, drawdown: -.11, total: .27},
    stats_point_in_time: {cagr: .08, volatility: .2, drawdown: -.12, total: .08},
    point_in_time_note: '',
  }
}

// The same block when the nightly could not draw the second line: an empty
// curve, no stats, and the reason in the note.
function backtestWithoutPointInTime(): Backtest {
  return {
    ...backtestWithPointInTime(),
    rules_point_in_time: [],
    stats_point_in_time: {},
    point_in_time_note: POINT_IN_TIME_NOTE,
  }
}

// Answer every desk endpoint locally with the given curve and refuse any provider request or persisted write.
async function installCurve(page: Page, frontendURL: string, backtest: Backtest) {
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-26', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: null, closes_at: null}
  const latest = {
    session: SESSION, written: WRITTEN, provenance: {rule: {inputs: ['expectations-gap']}, data: {fundamentals: 'fundamentals-features/2'}},
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAPL: {grade: 'A', votes: 3, stances: STANCES, ranks: {}, score: .82, side: 'ai', headline: 'Recorded headline.', reason: 'Recorded reason.', reads: {}}},
    book: [], briefs: {}, paper: null,
  }
  // The paper sessions sit on backtest dates so every backtest series stays
  // one unbroken run; a paper-only date would split each line at the gap.
  const curve = {
    backtest,
    paper: {label: 'paper account', sessions: ['2026-07-01', SESSION], equity: [100000, 101000], pl_pct: [0, .01]},
  }
  const mine = {session: SESSION, market_status: market, grade_valid_until: {}, grades_live: {}, rows: [],
    decisions: {session: SESSION, written: WRITTEN, as_of: NOW, rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', executable: false, blocker: 'No entry instruction.', reason: 'No entry instruction.', valid_until: null, target_weight: 0, current_weight: .1, move_weight: 0, strategy_move_weight: 0,
      quote: {feed: 'iex', at: NOW, bid: 98, ask: 98.5, reason: 'No entry instruction.', eligible: false}}}}}
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAPL: {symbol: 'AAPL', last: 98.25, open: 101, high: 102, low: 98, bar: BAR, as_of: NOW}}, technical: {}, technical_detail: {}}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  // Treat browser errors independently from the semantic assertions.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A partially rendered chart must not hide a JavaScript exception.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Every required request must complete successfully.
  page.on('requestfailed', request => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  // Record HTTP failures even when the component recovers visually.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(NOW)})
  // Keep the chart's colours independent of the operator's appearance preference.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Only the existing non-recording decision preview may use POST; every external request is refused.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const base = `/api/v1/market/${USER}/desk`
    const preview = url.pathname === `${base}/mine` && request.method() === 'POST' && request.postDataJSON()?.record_history === false
    if (request.method() !== 'GET' && !preview) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids persistence'}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-27T00:00:00Z', is_admin: true, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION], curve}
    else if (url.pathname === `${base}/live`) json = live
    else if (url.pathname === `${base}/session-prices`) json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = mine
    else if (url.pathname === `${base}/intraday`) json = {session: SESSION, as_of: NOW, equity: 101000, rows: [], changed: [], top_buys: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 101000, cash: 101000, day_pl: 0, pl_pct: .01, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/entries`) json = {user_id: USER, session: SESSION, rows: []}
    else if (url.pathname === `${base}/personal-history`) json = {rows: [], receipts: []}
    else if (url.pathname.startsWith(`${base}/history/`)) json = {ticker: 'AAPL', asof: SESSION, horizon: 20, backtest: null, rows: [], recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname.startsWith(`${base}/earnings/`)) json = {user_id: USER, symbol: 'AAPL', read: null}
    else if (url.pathname.startsWith(`${base}/chart/`)) json = {user_id: USER, ticker: 'AAPL', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'deterministic fixture', sessions: 0, bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname.startsWith(`${base}/live/read/`)) json = {symbol: 'AAPL', now: null, data_at: BAR, read_at: NOW, stale: false, read: 'Dated technical evidence.', lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    return route.fulfill({json})
  })
  return diagnostics
}

// Keep all diagnostics even when an earlier content assertion fails.
async function recordDiagnostics(testInfo: TestInfo, diagnostics: object) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json'})
  for (const [category, failures] of Object.entries(diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
}

// Open the practice account and return the track-record section with its chart.
async function openTrackRecord(page: Page) {
  await page.goto('/#desk')
  const account = page.locator('details[aria-label="Practice account"]')
  if ((await account.getAttribute('open')) === null) await account.locator(':scope > summary').click()
  const record = account.locator('section', {has: page.getByRole('heading', {name: /track record$/})})
  const chart = record.getByRole('img', {name: CHART_NAME, exact: true})
  await expect(chart).toBeVisible()
  return {record, chart}
}

// One stats cell's value, found by its label the way the cells are laid out.
function statCell(record: Locator, label: string) {
  return record.getByText(label, {exact: true}).locator('..')
}

// A recorded point-in-time curve draws as its own line and reports its own CAGR beside the published one.
test('draws the point-in-time line beside the stored simulation with its own CAGR', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installCurve(page, baseURL!, backtestWithPointInTime())
  try {
    const {record, chart} = await openTrackRecord(page)
    await expect(chart).toContainText(PUBLISHED_LABEL)
    await expect(chart).toContainText(POINT_IN_TIME_LABEL)
    await expect(chart).toContainText('SPY')
    // Each series is one polyline in its own colour; the label alone would
    // pass with a legend entry and no line.
    await expect(chart.locator('polyline[stroke="#1e7a3a"]')).toHaveCount(1)
    await expect(chart.locator('polyline[stroke="#b45309"]')).toHaveCount(1)
    await expect(statCell(record, 'CAGR')).toContainText('31.0%')
    await expect(statCell(record, 'CAGR, names known at the time')).toContainText('8.0%')
    await expect(statCell(record, 'CAGR, names known at the time')).not.toContainText('31.0%')
    await expect(record).not.toContainText('point-in-time line not drawn')
    await record.screenshot({path: testInfo.outputPath('point-in-time-line.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// An empty point-in-time curve leaves the published line intact, shows a dash for its CAGR, and says why.
test('keeps the published line and explains an absent point-in-time line', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installCurve(page, baseURL!, backtestWithoutPointInTime())
  try {
    const {record, chart} = await openTrackRecord(page)
    await expect(chart).toContainText(PUBLISHED_LABEL)
    await expect(chart).toContainText('SPY')
    await expect(chart).not.toContainText(POINT_IN_TIME_LABEL)
    await expect(chart.locator('polyline[stroke="#1e7a3a"]')).toHaveCount(1)
    await expect(chart.locator('polyline[stroke="#b45309"]')).toHaveCount(0)
    await expect(statCell(record, 'CAGR')).toContainText('31.0%')
    await expect(statCell(record, 'CAGR, names known at the time')).toContainText('—')
    await expect(statCell(record, 'CAGR, names known at the time')).not.toContainText('%')
    await expect(record.getByLabel('Point-in-time note', {exact: true})).toHaveText(POINT_IN_TIME_NOTE)
    await record.screenshot({path: testInfo.outputPath('point-in-time-line-absent.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})
