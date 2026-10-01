import {expect, test, type Page, type TestInfo} from '@playwright/test'

// Browser acceptance for the earnings coverage note: when the nightly's
// coverage check flagged book names (no earnings reading at all, a filing the
// reader left unread, a reading older than the name's usual gap allows), the
// board shows the lines the backend wrote, plainly and in grey, in the
// data-health strip above the board - never as an alert and never with a
// word of advice; when no name is flagged, when the check could not run, or
// on a record from before the check existed, nothing is shown. The note is a
// read-only view of what the nightly wrote, so every endpoint is answered
// from fixtures, as in desk-grade-parity.spec.ts.

const USER = 'ani.mallya'
const SESSION = '2026-09-30'
const WRITTEN = '2026-09-30T23:45:00Z'
const NOW = '2026-10-01T15:35:00Z'
const BAR = '2026-10-01T15:15:00Z'
const STANCES = {fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: 0}
const NOTE = 'Earnings coverage'
const LINES = [
  'No earnings reading: NBIS (no earnings filing on file)',
  'Earnings filing not read: WDAY (filed 2026-09-29, no release text found in it; last release read 2026-08-28)',
  'Earnings reading overdue: OKLO (last release read 2025-03-25, usually every 91 days across the book)',
]
const ADVICE = ['trade', 'buy', 'sell', 'should', 'avoid', 'safe', 'consider', 'recommend']

// The coverage block the nightly writes, with the given lines (flagged names
// follow from them; the per-name detail is not what the board reads).
function coverage(lines: string[]): Record<string, unknown> {
  return {
    session: SESSION, tolerance: 1.5, book_cadence_days: 91, read_lag_days: 0, read_lag_releases: 3, checked: 2,
    flagged: lines.length > 0 ? ['NBIS', 'OKLO', 'WDAY'] : [], lines,
  }
}

// Answer every desk endpoint locally with a record carrying `recorded`, and refuse any provider request or persisted write.
async function installRecord(page: Page, frontendURL: string, recorded: Record<string, unknown>) {
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-10-01', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: null, closes_at: null}
  const latest = {
    ...recorded,
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
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-10-02T00:00:00Z', is_admin: true, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION], grade_parity: {ok: true, date: SESSION, names: 2, mismatches: []}}
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

// Flagged: one grey line per flagged kind, in the backend's words and order,
// as a status note rather than an alert, with no word of advice.
test('shows the earnings coverage lines in grey when names are flagged', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installRecord(page, baseURL!, {release_coverage: coverage(LINES)})
  try {
    await openBoard(page)
    const note = page.getByRole('status', {name: NOTE, exact: true})
    await expect(note).toBeVisible()
    await expect(note.locator('p')).toHaveText(LINES)
    await expect(note).toHaveCSS('color', 'rgb(110, 110, 115)')
    await expect(page.getByRole('alert', {name: NOTE})).toHaveCount(0)
    const text = (await note.innerText()).toLowerCase()
    for (const word of ADVICE) expect(text).not.toContain(word)
    await note.screenshot({path: testInfo.outputPath('release-coverage-flagged.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// Not flagged: every name read as usual (no lines), a check that could not
// run (null), or a record from before the check (absent) - nothing is shown.
for (const [label, recorded] of [
  ['no name is flagged', {release_coverage: coverage([])}],
  ['the check could not run', {release_coverage: null}],
  ['the record predates the check', {}],
] as const) {
  test(`shows no earnings coverage note when ${label}`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installRecord(page, baseURL!, recorded)
    try {
      await openBoard(page)
      await expect(page.getByRole('status', {name: NOTE, exact: true})).toHaveCount(0)
      await expect(page.getByText('Earnings reading overdue')).toHaveCount(0)
      await expect(page.getByText('No earnings reading')).toHaveCount(0)
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}
