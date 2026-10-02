import {expect, test, type Page, type TestInfo} from '@playwright/test'

// Browser acceptance for the tone-expiry note: since A5-hard went live
// (2026-10-01) a book name's earnings release reading that is older than the
// name's usual gap allows no longer counts, and the nightly writes one plain
// line per such name - the reading's date and age, the usual gap, and the
// grade given against the grade with the reading counted - plus a line for
// any other name whose letter moved with them. The board shows those lines
// in grey in the data-health strip, never as an alert and never with a word
// of advice; when nothing expired, with the expiry off, when the block is
// null, or on a record from before the expiry, nothing is shown. The note is
// a read-only view of what the nightly wrote, so every endpoint is answered
// from fixtures, as in desk-release-coverage.spec.ts.

const USER = 'ani.mallya'
const SESSION = '2026-09-30'
const WRITTEN = '2026-09-30T23:45:00Z'
const NOW = '2026-10-01T15:35:00Z'
const BAR = '2026-10-01T15:15:00Z'
const STANCES = {fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: 0}
const NOTE = 'Earnings tone expired'
const LINES = [
  'Earnings tone expired: OKLO (last release read 2025-03-25, 555 days ago, usually every 91 days across the book); the reading no longer counts, graded C either way',
  'Earnings tone expiry elsewhere in the book: AAPL graded A; B with the expired readings counted (its reading still counts)',
]
const ADVICE = ['trade', 'buy', 'sell', 'should', 'avoid', 'safe', 'consider', 'recommend', 'wait']

// The tone-expiry block the nightly writes, with the given lines (the
// per-name detail follows them; the board reads only the lines).
function expiry(lines: string[], mode: 'hard' | null = 'hard'): Record<string, unknown> {
  return {
    mode,
    expired: lines.length > 0 ? {OKLO: {last_read: '2025-03-25', days_since: 555, cadence_days: 91, cadence_from: 'book', weight: 0, grade: 'C', grade_if_counted: 'C'}} : {},
    also_moved: lines.length > 0 ? {AAPL: {grade: 'A', grade_if_counted: 'B'}} : {},
    lines,
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

// Expired: one grey line per name, in the backend's words and order, as a
// status note rather than an alert, with no word of advice.
test('shows the tone expiry lines in grey when a reading expired', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installRecord(page, baseURL!, {tone_expiry: expiry(LINES)})
  try {
    await openBoard(page)
    const note = page.getByRole('status', {name: NOTE, exact: true})
    await expect(note).toBeVisible()
    await expect(note.locator('p')).toHaveText(LINES)
    await expect(note).toHaveCSS('color', 'rgb(110, 110, 115)')
    await expect(page.getByRole('alert', {name: NOTE})).toHaveCount(0)
    const text = (await note.innerText()).toLowerCase()
    for (const word of ADVICE) expect(text).not.toMatch(new RegExp(`\\b${word}\\b`))
    await note.screenshot({path: testInfo.outputPath('tone-expiry-expired.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// Nothing to explain: no reading expired (no lines), the expiry off, a
// block that is null, or a record from before the expiry - nothing is shown.
for (const [label, recorded] of [
  ['no reading expired', {tone_expiry: expiry([])}],
  ['the expiry is off', {tone_expiry: expiry([], null)}],
  ['the block is null', {tone_expiry: null}],
  ['the record predates the expiry', {}],
] as const) {
  test(`shows no tone expiry note when ${label}`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installRecord(page, baseURL!, recorded)
    try {
      await openBoard(page)
      await expect(page.getByRole('status', {name: NOTE, exact: true})).toHaveCount(0)
      await expect(page.getByText('Earnings tone expired')).toHaveCount(0)
      await expect(page.getByText('Earnings tone expiry elsewhere')).toHaveCount(0)
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}
