import {expect, test, type Page, type TestInfo} from '@playwright/test'

// Browser acceptance for the grade parity banner: when the nightly's check
// found the board's grades or targets disagreeing with the point-in-time
// replay, the board says so in red, with the date and the names, and tells
// the operator not to trade from it; when the check passed, or the record
// predates the check, nothing is shown. The verdict is a read-only view of
// what the nightly wrote, so every endpoint is answered from fixtures. The
// helpers follow desk-candidate-line.spec.ts, which must stay as it is.

const USER = 'ani.mallya'
const SESSION = '2026-09-25'
const WRITTEN = '2026-09-25T21:05:00Z'
const NOW = '2026-09-26T15:35:00Z'
const BAR = '2026-09-26T15:15:00Z'
const STANCES = {fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: 0}
const BANNER = 'Grade parity'
const HEADLINE = `Grade parity failed for ${SESSION}: 2 names — do not trade from this board`
type Parity = Record<string, unknown> | null

// A failed verdict: one grade flip, one name the membership history does
// not have, and the store having moved on - three rows, two names.
function failedParity(): Parity {
  return {
    ok: false, date: SESSION, names: 1,
    mismatches: [
      {kind: 'grade', ticker: 'AAPL', live: 'A', replay: 'B', detail: 'live grade differs from the point-in-time replay'},
      {kind: 'membership', ticker: 'MSFT', live: 'A+', replay: 'C', detail: `on the board, not a member of the point-in-time book on ${SESSION} (membership_history.csv)`},
      {kind: 'session', detail: 'the rebuilt report ends 2026-09-26, not 2026-09-25: the store moved on since the record; targets not compared'},
    ],
  }
}

// Answer every desk endpoint locally with the given parity verdict and refuse any provider request or persisted write.
async function installParity(page: Page, frontendURL: string, parity: Parity) {
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-26', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: null, closes_at: null}
  const latest = {
    session: SESSION, written: WRITTEN, provenance: {rule: {inputs: ['expectations-gap']}, data: {fundamentals: 'fundamentals-features/3'}},
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {
      AAPL: {grade: 'A', votes: 3, stances: STANCES, ranks: {}, score: .82, side: 'ai', headline: 'Recorded headline.', reason: 'Recorded reason.', reads: {}},
      MSFT: {grade: 'A+', votes: 4, stances: STANCES, ranks: {}, score: .9, side: 'software', headline: 'Recorded headline.', reason: 'Recorded reason.', reads: {}},
    },
    book: [], briefs: {}, paper: null,
  }
  const mine = {session: SESSION, market_status: market, grade_valid_until: {}, grades_live: {}, rows: [],
    decisions: {session: SESSION, written: WRITTEN, as_of: NOW, rows: {}}}
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {}, technical: {}, technical_detail: {}}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  // Treat browser errors independently from the semantic assertions.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A partially rendered board must not hide a JavaScript exception.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Every required request must complete successfully.
  page.on('requestfailed', request => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  // Record HTTP failures even when the component recovers visually.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(NOW)})
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
    else if (url.pathname === base) json = {latest, sessions: [SESSION], grade_parity: parity}
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

// Open the desk and wait for the board's grades to be on the page.
async function openBoard(page: Page) {
  await page.goto('/#desk')
  await expect(page.getByRole('heading', {name: 'Desk', exact: true})).toBeVisible()
  await expect(page.getByText('AAPL', {exact: true}).first()).toBeVisible()
}

// A failed verdict paints a red alert above the board with the date, the count of names, both grades per name, the store note and the instruction not to trade.
test('shows the red banner with the names when parity failed', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installParity(page, baseURL!, failedParity())
  try {
    await openBoard(page)
    const banner = page.getByRole('alert', {name: BANNER, exact: true})
    await expect(banner).toBeVisible()
    await expect(banner).toContainText(HEADLINE)
    await expect(banner).toContainText('AAPL (grade: live A, replay B)')
    await expect(banner).toContainText('MSFT (membership: live A+, replay C)')
    await expect(banner).toContainText('session: the rebuilt report ends 2026-09-26')
    await banner.screenshot({path: testInfo.outputPath('grade-parity-failed.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// A passing verdict, or a record from before the check, shows nothing.
for (const [label, parity] of [['passed', {ok: true, date: SESSION, names: 2, mismatches: []}], ['absent', null]] as const) {
  test(`hides the banner when parity ${label}`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installParity(page, baseURL!, parity)
    try {
      await openBoard(page)
      await expect(page.getByRole('alert', {name: BANNER, exact: true})).toHaveCount(0)
      await expect(page.getByText('do not trade from this board')).toHaveCount(0)
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}
