import {expect, test, type Page, type TestInfo} from '@playwright/test'

// Browser acceptance for the grade parity banner: when the nightly's check
// found the board's grades or targets disagreeing with the point-in-time
// replay, the board says so in red, with the date and the names, and tells
// the operator not to trade from it; when the same rows came from a replay
// on a later checkout or a store that gained partitions since the record
// (`mode: 'drift'`), the banner is amber, names the code pair and the moved
// partitions, and says the board is stale until the next nightly; when the
// check passed, or the record predates the check, nothing is shown. The verdict is a read-only view of
// what the nightly wrote, so every endpoint is answered from fixtures. The
// helpers follow desk-candidate-line.spec.ts, which must stay as it is.
// A drifting name whose own earnings data changed after the record (the
// backend marks its row `explained`) is said in a plain "Data updates" note
// instead, and the banner keeps every other row; a record whose grades moved
// on a data update since the previous record carries the same note.

const USER = 'ani.mallya'
const SESSION = '2026-09-25'
const WRITTEN = '2026-09-25T21:05:00Z'
const NOW = '2026-09-26T15:35:00Z'
const BAR = '2026-09-26T15:15:00Z'
const STANCES = {fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: 0}
const BANNER = 'Grade parity'
const HEADLINE = `Grade parity failed for ${SESSION}: 2 names — do not trade from this board`
const DRIFT_HEADLINE = `Grades have moved since ${SESSION}'s record — 2 names`
const NOTE = 'Data updates'
const STALE = `The board shows ${SESSION}'s grades; the next nightly record re-grades on current code and data.`
const AAPL_LINE = `AAPL: grade recomputed after its earnings releases were read for the first time (data update after the ${SESSION} record)`
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

// The same three rows from a replay two days later on a newer checkout and a
// store that gained two EDGAR partitions since the record: drift, not a
// pipeline failure.
function driftParity(): Parity {
  return {
    ...failedParity(),
    mode: 'drift',
    code: {record: '879abc56', replay: '1325466b'},
    moved_inputs: ['edgar_events/asof=2026-09-26', 'edgar_facts/asof=2026-09-26'],
  }
}

// The drift above with AAPL's grade row explained by a data update after the
// record: the note carries AAPL, the banner keeps MSFT and the store row.
function mixedParity(): Parity {
  const drift = driftParity() as {mismatches: Record<string, unknown>[]}
  return {
    ...drift,
    mismatches: drift.mismatches.map(m => m.ticker === 'AAPL' ? {...m, explained: true} : m),
    data_vintage: {since: SESSION, names: ['AAPL'], lines: [AAPL_LINE]},
  }
}

// A drift in which both names' grade rows coincide with a change in their own
// earnings data and nothing else differs: no banner row is left.
function explainedParity(): Parity {
  return {
    ok: false, date: SESSION, names: 2, mode: 'drift',
    code: {record: '8046f0c9', replay: '8046f0c9'},
    moved_inputs: ['edgar_events/asof=2026-09-26', 'edgar_tone/asof=2026-09-26'],
    mismatches: [
      {kind: 'grade', ticker: 'AAPL', live: 'A', replay: 'B', detail: 'live grade differs from the point-in-time replay', explained: true},
      {kind: 'grade', ticker: 'MSFT', live: 'A+', replay: 'A', detail: 'live grade differs from the point-in-time replay', explained: true},
    ],
    data_vintage: {since: SESSION, names: ['AAPL', 'MSFT'], lines: [`AAPL, MSFT: grades recomputed after their earnings releases were read for the first time (data update after the ${SESSION} record)`]},
  }
}

// Answer every desk endpoint locally with the given parity verdict and refuse any provider request or persisted write.
async function installParity(page: Page, frontendURL: string, parity: Parity, recorded: Record<string, unknown> = {}) {
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-26', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: null, closes_at: null}
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

// A drift verdict paints an amber notice with the date, the count of names, the code pair, the moved partitions and both grades per name, and says the board is stale rather than not to trade.
test('shows the amber drift banner with the code pair and moved inputs', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installParity(page, baseURL!, driftParity())
  try {
    await openBoard(page)
    const banner = page.getByRole('alert', {name: BANNER, exact: true})
    await expect(banner).toBeVisible()
    await expect(banner).toContainText(DRIFT_HEADLINE)
    await expect(banner).toContainText('code 879abc56 → 1325466b; inputs moved: edgar_events/asof=2026-09-26, edgar_facts/asof=2026-09-26')
    await expect(banner).toContainText('AAPL (grade: live A, replay B)')
    await expect(banner).toContainText('MSFT (membership: live A+, replay C)')
    await expect(banner).toContainText(`The board shows ${SESSION}'s grades; the next nightly record re-grades on current code and data.`)
    await expect(banner).not.toContainText('do not trade')
    await expect(banner).toHaveCSS('background-color', 'rgb(255, 251, 235)')
    await banner.screenshot({path: testInfo.outputPath('grade-parity-drift.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// Mixed: AAPL's drift coincides with a data update, so it is said in the
// plain note; MSFT's membership row and the store row stay in the amber
// banner, which counts one name and no longer lists AAPL.
test('explains the drift of a name whose earnings data changed and keeps the banner for the rest', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installParity(page, baseURL!, mixedParity())
  try {
    await openBoard(page)
    const note = page.getByRole('status', {name: NOTE, exact: true})
    await expect(note).toBeVisible()
    await expect(note).toContainText(AAPL_LINE)
    const banner = page.getByRole('alert', {name: BANNER, exact: true})
    await expect(banner).toBeVisible()
    await expect(banner).toContainText(`Grades have moved since ${SESSION}'s record — 1 name`)
    await expect(banner).toContainText('MSFT (membership: live A+, replay C)')
    await expect(banner).toContainText('session: the rebuilt report ends 2026-09-26')
    await expect(banner).not.toContainText('AAPL')
    await expect(banner).toHaveCSS('background-color', 'rgb(255, 251, 235)')
    await note.screenshot({path: testInfo.outputPath('grade-parity-explained-mixed.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// Every drifting row explained by a data update: no alert at all, the plain
// note with its line and the sentence that the board still shows the
// record's grades until the next nightly.
test('shows only the plain data-update note when every drift is explained', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installParity(page, baseURL!, explainedParity())
  try {
    await openBoard(page)
    const note = page.getByRole('status', {name: NOTE, exact: true})
    await expect(note).toBeVisible()
    await expect(note).toContainText(`AAPL, MSFT: grades recomputed after their earnings releases were read for the first time (data update after the ${SESSION} record)`)
    await expect(note).toContainText(STALE)
    await expect(page.getByRole('alert', {name: BANNER, exact: true})).toHaveCount(0)
    await expect(page.getByText('do not trade from this board')).toHaveCount(0)
    await note.screenshot({path: testInfo.outputPath('grade-parity-explained.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// The nightly path: parity passed, and the record says AAPL's grade moved
// since the previous record while its earnings releases were read for the
// first time in between. The note shows; no banner does.
test('shows the record data-update note when a grade moved on a data update', async ({page, baseURL}, testInfo) => {
  const line = 'AAPL: grade recomputed after its earnings releases were read for the first time (data update after the 2026-09-24 record)'
  const recorded = {data_vintage: {since: '2026-09-24', names: ['AAPL'], lines: [line]}}
  const diagnostics = await installParity(page, baseURL!, {ok: true, date: SESSION, names: 2, mismatches: []}, recorded)
  try {
    await openBoard(page)
    const note = page.getByRole('status', {name: NOTE, exact: true})
    await expect(note).toBeVisible()
    await expect(note).toHaveText(line)
    await expect(page.getByRole('alert', {name: BANNER, exact: true})).toHaveCount(0)
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
