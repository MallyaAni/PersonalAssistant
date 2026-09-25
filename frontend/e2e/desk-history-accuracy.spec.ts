import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'ani.mallya'
const SESSION = '2026-09-24'
const WRITTEN = '2026-09-24T21:05:00Z'
const STANCES = {fundamental: 1, technical: 0, sentiment: 1, value: 1, rotation: 0}
type HistoryRow = {date: string; grade: string; stances: Record<string, number | null>; forward: number | null; votes?: number | null}
type Scenario = {history?: HistoryRow[]; overnight?: boolean}

// Exercise the real desk against dated synthetic API evidence without provider or persistence access.
async function installScenario(page: Page, frontendURL: string, options: Scenario = {}) {
  const now = options.overnight ? '2026-09-25T01:35:00Z' : '2026-09-25T15:35:00Z'
  const bar = options.overnight ? '2026-09-24T19:45:00Z' : '2026-09-25T15:15:00Z'
  const market = {exchange: 'XNYS', as_of: now, session: '2026-09-25', calendar_known: !options.overnight, is_session: !options.overnight, open: !options.overnight, phase: options.overnight ? 'unknown' : 'open', opens_at: null, closes_at: null}
  const latest = {
    session: SESSION, written: WRITTEN, provenance: {rule: {inputs: ['expectations-gap']}, data: {fundamentals: 'fundamentals-features/1'}},
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAOI: {grade: 'A+', votes: 3, stances: STANCES, ranks: {}, score: .82, side: 'ai', headline: 'Recorded headline.', reason: 'Recorded reason.', reads: {}}},
    book: [], briefs: {}, paper: null,
  }
  const reason = options.overnight ? 'Market closed or clock unavailable' : 'No entry instruction.'
  const mine = {session: SESSION, market_status: market, grade_valid_until: {}, grades_live: {}, rows: [],
    decisions: {session: SESSION, written: WRITTEN, as_of: now, rows: {AAOI: {action: 'Hold', strategy_action: options.overnight ? 'Sell' : 'Hold', executable: false, blocker: reason, reason: options.overnight ? `Exit not executable: ${reason}` : reason, valid_until: null, target_weight: 0, current_weight: .1, move_weight: 0, strategy_move_weight: options.overnight ? -.1 : 0,
      quote: {feed: 'iex', at: now, bid: 98, ask: 98.5, reason, eligible: false}}}}}
  const live = {as_of: now, data_at: bar, stale: Boolean(options.overnight), market_status: market, quotes: {AAOI: {symbol: 'AAOI', last: 98.25, open: 101, high: 102, low: 98, bar, as_of: now}}, technical: {}, technical_detail: {}}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  // Treat browser errors independently from the semantic assertions.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A partially rendered view must not hide a JavaScript exception.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Every required request must complete successfully.
  page.on('requestfailed', request => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  // Record HTTP failures even when the component recovers visually.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(now)})
  // Keep screenshots independent of the operator's appearance preference.
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
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-26T00:00:00Z', is_admin: true, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = live
    else if (url.pathname === `${base}/session-prices`) json = {session: options.overnight ? 'overnight' : 'regular', as_of: now, signal_scope: 'regular-session', quotes: {AAOI: options.overnight
      ? {price: 99.5, at: now, feed: 'boats', indicative: false, session: 'overnight', status: 'fresh', reason: 'Dated overnight quote.', valid_until: '2026-09-25T01:36:00Z'}
      : {price: null, at: null, feed: null, indicative: false, status: 'unavailable', reason: 'No optional quote in this fixture.', valid_until: null}}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = mine
    else if (url.pathname === `${base}/intraday`) json = {session: SESSION, as_of: now, equity: 100000, rows: [], changed: [], top_buys: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: now, equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/entries`) json = {user_id: USER, session: SESSION, rows: []}
    else if (url.pathname === `${base}/history/AAOI`) json = {ticker: 'AAOI', asof: SESSION, horizon: 20,
      backtest: {min_grade: 'A', sessions: 60, sessions_in: 41, switches: 3, in_annualised: .41, out_annualised: -.2},
      rows: (options.history ?? []).map(row => ({votes: 3, exposure: 1, confidence: 1, forward_residual: null, earnings: false, said: true, ...row})),
      recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname === `${base}/earnings/AAOI`) json = {user_id: USER, symbol: 'AAOI', read: null}
    else if (url.pathname === `${base}/chart/AAOI`) json = {user_id: USER, ticker: 'AAOI', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'deterministic fixture', sessions: 0, bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname === `${base}/live/read/AAOI`) json = {symbol: 'AAOI', now: null, data_at: bar, read_at: now, stale: Boolean(options.overnight), read: 'Dated technical evidence.', lines: {short: [], medium: [], long: []}}
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

// Open the actual stock history and disclose its dated statistics.
async function openHistory(page: Page) {
  await page.goto('/#desk')
  await page.getByRole('button', {name: 'AAOI', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'AAOI history'})
  const details = dialog.getByLabel('Score, log and backtest', {exact: true})
  if ((await details.getAttribute('open')) === null) await details.getByText('Score, log & backtest', {exact: true}).click()
  return {dialog, details}
}

for (const [name, forward, expected] of [['doubling', Math.log(2), '+100.0%'], ['halving', Math.log(.5), '-50.0%'], ['unchanged', 0, '0.0%'], ['unknown', null, '—'], ['overflowing conversion', 1000, '—']] as const) {
  // Ordinary percentage change must invert the stored log return without manufacturing missing data.
  test(`history shows adjusted-close percentage change for ${name}`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installScenario(page, baseURL!, {history: [{date: '2026-08-20', grade: 'A', stances: STANCES, forward}]})
    try {
      const {details} = await openHistory(page)
      const row = details.getByRole('row').filter({hasText: 'Aug 20'})
      await expect(details.getByRole('heading', {name: 'The last 1 session', exact: true})).toBeVisible()
      await expect(row.getByRole('cell').last()).toContainText(expected)
      await expect(details).toContainText('Adjusted-close percentage change over the next 20 sessions')
      await expect(details).toContainText('not a funded trade return or your P/L')
      await expect(details.getByText('Annualized mean while an A', {exact: true}).locator('..')).toContainText('41% a year')
      await expect(details.getByText('Annualized mean while not', {exact: true}).locator('..')).toContainText('-20% a year')
      await expect(details).toContainText('Annualized daily log-return means')
      if (name === 'doubling') await details.screenshot({path: testInfo.outputPath('adjusted-close-history.png')})
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}

for (const [name, before, after, transition] of [
  ['missing prior vote', {}, {fundamental: 1}, 'unknown → for'],
  ['partial prior panel', {technical: 0}, {technical: 0, fundamental: 1}, 'unknown → for'],
  ['observed zero', {fundamental: 0}, {fundamental: 1}, 'neutral → for'],
  ['missing later vote', {fundamental: 1}, {}, 'for → unknown'],
  ['invalid prior vote', {fundamental: 2}, {fundamental: 1}, 'unknown → for'],
  ['invalid later vote', {fundamental: 1}, {fundamental: 2}, 'for → unknown'],
  ['null prior vote', {fundamental: null}, {fundamental: 1}, 'unknown → for'],
  ['null later vote', {fundamental: 1}, {fundamental: null}, 'for → unknown'],
] as const) {
  // A recorded zero is neutral; absent historical evidence is unknown on both change displays.
  test(`historical vote comparison preserves ${name}`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installScenario(page, baseURL!, {history: [
      {date: '2026-09-23', grade: 'B', stances: before, forward: null},
      {date: SESSION, grade: 'A+', stances: after, forward: null},
    ]})
    try {
      const {dialog, details} = await openHistory(page)
      await expect(dialog.getByRole('region', {name: 'Why the grade moved'})).toContainText(`Growth & margins ${transition}`)
      await expect(details).toContainText(`fundamental ${transition}`)
      if (name !== 'observed zero') {
        await expect(dialog.getByRole('region', {name: 'Why the grade moved'})).not.toContainText('neutral → for')
        await expect(details).toContainText('Unknown means the vote was not recorded or was invalid')
      }
      if (name.startsWith('invalid') || name.startsWith('null')) {
        const date = name.includes('prior') ? 'Sep 23' : 'Sep 24'
        const marks = details.getByRole('row').filter({hasText: date}).getByRole('cell').nth(2)
        await expect(marks).toHaveText('F?')
        await expect(marks).not.toContainText('undefined')
        await expect(details.getByRole('columnheader', {name: 'Analysts', exact: true})).toHaveAttribute('title', /\? missing or invalid vote/)
      }
      if (name === 'partial prior panel') await dialog.screenshot({path: testInfo.outputPath('unknown-vote-history.png')})
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}

// A fresh overnight display quote cannot resolve an unknown regular-session execution clock.
test('keeps clock uncertainty and blocked Sell alongside a fresh overnight quote', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installScenario(page, baseURL!, {overnight: true})
  try {
    await page.goto('/#desk')
    const quote = page.getByLabel('AAOI session price', {exact: true}).first()
    await expect(quote).toContainText('$99.50')
    await expect(quote).toContainText('overnight')
    await expect(quote).toContainText('BOATS')
    await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
    const expansion = page.getByRole('region', {name: 'AAOI decision details', exact: true})
    const intent = expansion.getByLabel('AAOI strategy intent', {exact: true})
    await expect(intent).toContainText('SELL')
    await expect(intent).toContainText('Blocked now')
    await expect(intent).toHaveAttribute('title', /Regular-session execution is blocked; the session is closed or its clock is unavailable/)
    await expect(intent).not.toHaveAttribute('title', /no executable quote until the open/)
    await expansion.getByText('Recorded allocation & execution quote', {exact: true}).click()
    await expect(expansion).toContainText('Regular-session execution is blocked; the session is closed or its clock is unavailable')
    await expect(expansion).not.toContainText('no executable quote until the open')
    await expect(quote).toContainText('$99.50')
    await page.screenshot({path: testInfo.outputPath('overnight-quote-clock-unknown.png'), fullPage: true})
    const clockExplanation = expansion.getByText('Regular-session execution is blocked; the session is closed or its clock is unavailable', {exact: true})
    await clockExplanation.scrollIntoViewIfNeeded()
    await expect(clockExplanation).toBeVisible()
    await clockExplanation.screenshot({path: testInfo.outputPath('clock-explanation-visible.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

for (const [name, votes, expected] of [['unrecorded', null, 'Votes not recorded'], ['observed zero', 0, '0.0 votes']] as const) {
  // Legacy missing totals must remain readable while a genuine aggregate zero stays an observation.
  test(`keeps a published history row readable with ${name} aggregate votes`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installScenario(page, baseURL!, {history: [{date: '2026-08-20', grade: 'A', stances: {}, votes, forward: Math.log(2)}]})
    try {
      const {details} = await openHistory(page)
      const row = details.getByRole('row').filter({hasText: 'Aug 20'})
      await expect(row).toContainText(expected)
      if (votes === null) await expect(row).not.toContainText('0.0 votes')
      await expect(row.getByRole('cell').last()).toContainText('+100.0%')
      await expect(row).toContainText('published')
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}
