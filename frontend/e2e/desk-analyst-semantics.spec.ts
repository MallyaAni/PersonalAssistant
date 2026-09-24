import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'ani.mallya'
const SESSION = '2026-09-23'
const WRITTEN = '2026-09-23T21:05:00Z'
const NOW = '2026-09-24T15:35:00Z'
const BAR = '2026-09-24T15:15:00Z'
const HEADLINE = 'Own: 3 analysts for, none against'
const REASON = '+ Fundamental: revenue growth high in book\n+ Sentiment: upbeat on guidance; upbeat on demand\n+ Value: relative valuation high in book'
const READ = 'Recorded commentary: Fundamental and Sentiment contributed to the evening grade.'
const STANCES = {fundamental: 1, technical: 0, sentiment: 1, value: 1, rotation: 0}
const RANKS = {fundamental: .875, technical: .293, sentiment: .881, value: .786, rotation: .5}
const PERIODS = {revenue_yoy: '2026-06-30', revenue_qoq: '2026-06-30', revenue_acceleration: '2026-06-30', gross_margin: '2026-03-31', net_margin: '', capex_to_revenue: '2026-03-31'}
const NO_SOURCE_LINK = 'No source-release link is recorded for the S vote.'
const VOTE_CONTEXT = 'Evening votes use a three-session confirmation rule; the latest readings may differ from those that established a vote.'
type Scenario = {withRow?: boolean; periods?: Record<string, string> | null; source?: string; ranks?: Record<string, number | null>; stances?: Record<string, number>; history?: {date: string; grade: string; stances: Record<string, number>}[]; revision?: boolean; oldEarnings?: boolean}

// Supply dated evening evidence and a separately newer earnings read without contacting a backend.
async function installScenario(page: Page, frontendURL: string, options: Scenario = {}) {
  const ranks = options.ranks ?? RANKS
  const stances = options.stances ?? STANCES
  const latest = {
    session: SESSION, written: WRITTEN, provenance: {rule: {inputs: ['expectations-gap']}, data: {fundamentals: options.source ?? 'fundamentals-features/1'}},
    ...(options.periods === null ? {} : {fundamental: {source: options.source ?? 'fundamentals-features/1', dates: {AAOI: options.periods ?? PERIODS}}}),
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAOI: {grade: 'A+', votes: 3, stances, ranks, score: .82, side: 'ai', headline: HEADLINE, reason: REASON, read: READ, reads: {fundamental: ['Revenue grew 32%.'], sentiment: ['Guidance tone positive.'], value: ['Recorded value context remains unchanged.']},
      revision: options.revision ? {accession: 'fixture-accession', reaction_date: '2026-09-12', prompt_version: ['release_tone/2', 'release_tone/3'], fields: {guidance: [.2, .8]}} : null}},
    book: [], briefs: {}, paper: null,
  }
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-24', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
  const current = {grade_live: 'B', score_live: .4, technical_now: .2, technical_close: .293, stances_live: {...stances, technical: -1}, ranks_live: options.ranks ?? {...RANKS, technical: .2}}
  const opportunity = {version: 'analyst-opportunity/1', score: 7.1, last_score: 7.1, price: 98.25, bar: BAR, valid_until: '2026-09-24T15:45:00Z', valuation_current: false, missing: [], parts: [
    {analyst: 'fundamental', score: 8.7, weight: 1, basis: SESSION, evidence: ['Revenue grew 32%.']},
    {analyst: 'sentiment', score: 8.8, weight: 1, basis: SESSION, evidence: ['Guidance tone positive.']},
    {analyst: 'value', score: 7.8, weight: 1, basis: SESSION, evidence: ['Recorded value context remains unchanged.']},
  ]}
  const mine = {session: SESSION, market_status: market, grade_valid_until: {AAOI: '2026-09-24T15:45:00Z'}, grades_live: {AAOI: current},
    rows: options.withRow ? [{ticker: 'AAOI', ...current, grade: 'A+', grade_source: 'intraday', action: 'hold', in_book: false, score: .82, rank: 1, stances, ranks, target_weight: 0, current_weight: 0, delta_weight: 0, shares: 0, entry_price: null, entry_date: null, last: 98.25, last_close: 101, pl_pct: null, until_rebalance: null, rebalance_due: false}] : [],
    decisions: {session: SESSION, written: WRITTEN, as_of: NOW, rows: {AAOI: {action: 'Hold', strategy_action: 'Hold', executable: false, reason: 'No entry instruction.', valid_until: '2026-09-24T15:45:00Z', target_weight: 0, current_weight: 0, move_weight: 0, opportunity}}}}
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAOI: {symbol: 'AAOI', last: 98.25, open: 101, high: 102, low: 98, bar: BAR, as_of: NOW}}, technical: {AAOI: {now: .2, close: .293}}, technical_detail: {AAOI: {now: .2, short: {}, medium: {}, long: {}}}}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  // Record browser exceptions independently of content assertions.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A page exception must fail even if part of the panel still renders.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // No required request in this local fixture may fail silently.
  page.on('requestfailed', request => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  // An HTTP failure must not be concealed by a successful navigation.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(NOW)})
  // Stabilize the appearance independently of local browser preferences.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // All API traffic is local; only the explicit non-recording preview POST is allowed.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const base = `/api/v1/market/${USER}/desk`
    const readOnlyPost = url.pathname === `${base}/mine` && request.method() === 'POST' && request.postDataJSON()?.record_history === false
    if (request.method() !== 'GET' && !readOnlyPost) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids persistence'}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-25T00:00:00Z', is_admin: true, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = live
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = mine
    else if (url.pathname === `${base}/intraday`) json = {session: SESSION, as_of: NOW, equity: 100000, rows: [], changed: [], top_buys: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/entries`) json = {user_id: USER, session: SESSION, rows: []}
    else if (url.pathname === `${base}/history/AAOI`) json = {ticker: 'AAOI', asof: SESSION, horizon: 20, backtest: null, rows: options.history ?? [], recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname === `${base}/earnings/AAOI`) json = {user_id: USER, symbol: 'AAOI', read: {reaction_date: '2026-09-24', quarter_end: '2026-08-31', guidance: 1, demand: 1, pricing: 0, capex: 1, supply_constrained: 0, revenue_usd_m: 250, eps_usd: -.25, net_income_usd_m: -25, gross_margin_pct: 32, summary: 'A separately stored earnings extraction.', prompt_version: options.oldEarnings ? 'release_tone/2' : 'release_tone/3', same_day: true}}
    else if (url.pathname === `${base}/chart/AAOI`) json = {user_id: USER, ticker: 'AAOI', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'deterministic fixture', sessions: 0, bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname === `${base}/live/read/AAOI`) json = {symbol: 'AAOI', now: .2, data_at: BAR, read_at: NOW, stale: false, read: 'Dated technical evidence.', lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    return route.fulfill({json})
  })
  return diagnostics
}

// Retain error/write diagnostics even when a content assertion fails first.
async function recordDiagnostics(testInfo: TestInfo, diagnostics: object) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json'})
  for (const failures of Object.values(diagnostics)) expect(failures).toEqual([])
}

// Check the compact parts without converting their ranks or votes into individual letter grades.
async function expectMeanings(surface: ReturnType<Page['getByRole']>) {
  await expect(surface).toContainText('F growth & margins')
  await expect(surface).toContainText('S earnings-release tone')
  await expect(surface).toContainText('V relative valuation, not intrinsic fair value')
  const current = surface.getByRole('region', {name: 'Latest available grade', exact: true})
  await expect(current.getByLabel('Latest grade value', {exact: true})).toHaveText('B')
  await expect(current).toContainText('Analyst percentiles and votes')
  await expect(current).toContainText('F88+')
  await expect(current).toContainText('S88+')
  await expect(current).toContainText('not individual letter grades')
  await expect(current).toContainText(VOTE_CONTEXT)
  const evening = surface.getByRole('region', {name: 'Evening analysis', exact: true})
  await expect(evening).toContainText('Recorded grade A+')
  await expect(evening).toContainText('Combined analyst grade')
  await expect(evening).toContainText('Stored readings are not a causal breakdown of the votes.')
  await expect(evening).toContainText(VOTE_CONTEXT)
  for (const line of REASON.split('\n')) await expect(evening).toContainText(line)
  await evening.getByText('Original recorded wording', {exact: true}).click()
  await expect(evening.getByText(HEADLINE, {exact: true})).toHaveText(HEADLINE)
  await evening.getByText('Original recorded wording', {exact: true}).click()
}

for (const withRow of [false, true]) {
  // A newer earnings quarter must not replace the stored grade's mixed metric-specific fiscal dates.
  test(`defines analyst parts and dates each stored metric ${withRow ? 'with' : 'without'} a personal row`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installScenario(page, baseURL!, {withRow})
    try {
      await page.goto('/#desk')
      await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
      const expansion = page.getByRole('region', {name: 'AAOI decision details', exact: true})
      await expectMeanings(expansion)
      await expansion.getByText('Archived model commentary · unverified', {exact: true}).click()
      await expect(expansion.getByText(READ, {exact: true})).toHaveText(READ)
      await expect(expansion.getByText(READ, {exact: true})).toBeVisible()
      await expansion.getByText('Archived model commentary · unverified', {exact: true}).click()
      await expansion.getByText('Evidence dates for this decision', {exact: true}).click()
      const dates = expansion.getByRole('region', {name: 'Recorded analyst evidence dates', exact: true})
      await expect(dates.getByRole('row', {name: 'Revenue growth, year over year 2026-06-30'})).toBeVisible()
      await expect(dates.getByRole('row', {name: 'Gross margin 2026-03-31'})).toBeVisible()
      await expect(dates.getByRole('row', {name: 'Net margin Unavailable'})).toBeVisible()
      await expect(dates).toContainText(NO_SOURCE_LINK)
      await expect(dates).toContainText('not filing or release dates')
      await expect(dates).toContainText('recorded evidence, not necessarily the readings that established a persisted vote')
      await expansion.getByRole('button', {name: 'Open the full panel'}).click()
      const dialog = page.getByRole('dialog', {name: 'AAOI history'})
      await expectMeanings(dialog)
      await dialog.getByText('Evidence dates for this decision', {exact: true}).click()
      const recorded = dialog.getByRole('region', {name: 'Recorded analyst evidence dates', exact: true})
      await expect(recorded.getByRole('row', {name: 'Revenue growth, quarter over quarter 2026-06-30'})).toBeVisible()
      await expect(recorded.getByRole('row', {name: 'Gross margin 2026-03-31'})).toBeVisible()
      await dialog.getByText('All the evidence', {exact: true}).click()
      const earnings = dialog.getByRole('region', {name: 'Earnings evidence', exact: true})
      await expect(earnings).toContainText('Aug 31, 2026')
      await expect(earnings).toContainText('Market reaction on or after Sep 24, 2026')
      await expect(earnings).toContainText('not confirm that the displayed grade includes it')
      await expect(recorded).not.toContainText('2026-08-31')
      await expect(recorded).not.toContainText('Aug 31')
      await expect(recorded).toContainText(NO_SOURCE_LINK)
      await page.screenshot({path: testInfo.outputPath('metric-dates-and-separate-earnings.png'), fullPage: true})
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}

for (const [name, periods] of [['older absent block', null], ['empty date map', {}], ['invalid date values', {gross_margin: '2026-02-30', revenue_yoy: 'NaT', revenue_qoq: ''}]] as const) {
  // Missing dates are unknown metadata, never a fabricated quarter or absence of a business score.
  test(`keeps fiscal dates unknown for ${name}`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installScenario(page, baseURL!, {periods, source: 'edgar-frozen'})
    try {
      await page.goto('/#desk')
      await page.getByRole('button', {name: 'AAOI', exact: true}).click()
      const dialog = page.getByRole('dialog', {name: 'AAOI history'})
      await dialog.getByText('Evidence dates for this decision', {exact: true}).click()
      const dates = dialog.getByRole('region', {name: 'Recorded analyst evidence dates', exact: true})
      await expect(dates).toContainText('F fiscal period dates are unavailable for this name.')
      await expect(dates).toContainText(NO_SOURCE_LINK)
      await expect(dates).not.toContainText('Invalid Date')
      await expect(dates).not.toContainText('2026-03-02')
      await expect(dialog.getByRole('region', {name: 'Evening analysis', exact: true})).toContainText('Recorded grade A+')
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}

// An old record without percentiles preserves the votes and marks the numbers unavailable.
test('keeps missing percentiles distinct from zero and individual grades', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installScenario(page, baseURL!, {ranks: {}})
  try {
    await page.goto('/#desk')
    await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
    const expansion = page.getByRole('region', {name: 'AAOI decision details', exact: true})
    const current = expansion.getByRole('region', {name: 'Latest available grade', exact: true})
    await expect(current).toContainText('F+ T− S+ V+ R·')
    await expect(current).toContainText('No number means no valid percentile is available.')
    await expect(current).not.toContainText('F0+')
    await expect(current).not.toContainText('F A+')
    await expect(current.getByLabel('Latest grade value', {exact: true})).toHaveText('B')
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// Invalid percentiles and unsupported or absent votes stay unknown, while a valid zero remains zero.
test('distinguishes invalid analyst parts from a valid zero percentile', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installScenario(page, baseURL!, {
    ranks: {fundamental: -.2, technical: 1.5, sentiment: 0, value: null, rotation: .5},
    stances: {fundamental: 1, technical: 0, sentiment: 2, value: 1},
  })
  try {
    await page.goto('/#desk')
    await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
    const expansion = page.getByRole('region', {name: 'AAOI decision details', exact: true})
    const current = expansion.getByRole('region', {name: 'Latest available grade', exact: true})
    await expect(current).toContainText('F+ T− S0? V+ R50?')
    await expect(current).toContainText('No number means no valid percentile is available.')
    await expect(current).toContainText('? means the vote is missing or invalid.')
    await expect(current).not.toContainText('F0+')
    await expect(current).not.toContainText('T150')
    await expansion.getByRole('button', {name: 'Open the full panel'}).click()
    const dialog = page.getByRole('dialog', {name: 'AAOI history'})
    const detail = dialog.getByRole('region', {name: 'Latest available grade', exact: true})
    await expect(detail).toContainText('F+ T− S0? V+ R50?')
    await expect(detail).toContainText('? means the vote is missing or invalid.')
    await dialog.getByText('All the evidence', {exact: true}).click()
    await expect(dialog.getByText('Earnings-release tone vote missing or invalid', {exact: true})).toBeVisible()
    await expect(dialog).not.toContainText('Earnings-release tone vote not recorded')
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

for (const valueChanged of [true, false]) {
  // Recorded vote differences must not invent either price independence or a continuous-score grade boundary.
  test(`does not invent a grade-move cause for ${valueChanged ? 'a Value-only flip' : 'unchanged votes'}`, async ({page, baseURL}, testInfo) => {
    const diagnostics = await installScenario(page, baseURL!, {history: [
      {date: '2026-09-22', grade: 'B', stances: {...STANCES, value: valueChanged ? 0 : 1}},
      {date: SESSION, grade: 'A+', stances: STANCES},
    ]})
    try {
      await page.goto('/#desk')
      await page.getByRole('button', {name: 'AAOI', exact: true}).click()
      const dialog = page.getByRole('dialog', {name: 'AAOI history'})
      const move = dialog.getByRole('region', {name: 'Why the grade moved', exact: true})
      if (valueChanged) {
        await expect(move).toContainText('Relative valuation neutral → for')
        await expect(move).not.toContainText('Price was not an input')
        await expect(move).toContainText('Recorded vote changes do not establish what caused a price move.')
        await expect(move).toContainText(VOTE_CONTEXT)
      } else {
        await expect(move).not.toContainText('the score crossed a grade line')
        await expect(move).toContainText('No analyst vote change is recorded in this comparison; cause not recorded.')
      }
      const evening = dialog.getByRole('region', {name: 'Evening analysis', exact: true})
      for (const line of REASON.split('\n')) await expect(evening).toContainText(line)
      await evening.getByText('Original recorded wording', {exact: true}).click()
      await expect(evening.getByText(HEADLINE, {exact: true})).toHaveText(HEADLINE)
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}

// A re-read marker, relative valuation proxy and intraday grade must not acquire stronger meanings in prose.
test('qualifies reaction dates valuation proxy and evening vote persistence', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installScenario(page, baseURL!, {revision: true})
  try {
    await page.goto('/?deskDetails=1#desk')
    await page.getByText('How ranking and sizing work', {exact: true}).click()
    const guide = page.getByRole('region', {name: 'Desk guide', exact: true})
    await expect(guide).toContainText('model-estimated revenue growth minus a relative-P/S valuation proxy')
    await expect(guide).toContainText('quarterly revenue × 4')
    await expect(guide).toContainText('not trailing-twelve-month revenue')
    await expect(guide).toContainText('not intrinsic fair value')
    await page.getByRole('button', {name: 'AAOI', exact: true}).click()
    const dialog = page.getByRole('dialog', {name: 'AAOI history'})
    const revision = dialog.getByRole('region', {name: 'Why the grade moved'})
    await expect(revision).toContainText('market reaction on or after 2026-09-12')
    await expect(revision).not.toContainText('the 2026-09-12 release')
    await dialog.getByText('Score, log & backtest', {exact: true}).click()
    const opportunity = dialog.getByRole('region', {name: 'Opportunity score'})
    await expect(opportunity).toContainText(VOTE_CONTEXT)
    await expect(opportunity).toContainText('Intraday price-sensitive votes can update without that wait.')
    await expect(opportunity.getByText('Growth & margins', {exact: true})).toBeVisible()
    await expect(opportunity.getByText('Earnings-release tone', {exact: true})).toBeVisible()
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// Older extractions retain their financial withholding and cannot supply a fiscal quarter for the grade.
test('preserves older earnings withholding independently of recorded fiscal dates', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installScenario(page, baseURL!, {oldEarnings: true})
  try {
    await page.goto('/#desk')
    await page.getByRole('button', {name: 'AAOI', exact: true}).click()
    const dialog = page.getByRole('dialog', {name: 'AAOI history'})
    await dialog.getByText('All the evidence', {exact: true}).click()
    const earnings = dialog.getByRole('region', {name: 'Earnings evidence', exact: true})
    await expect(earnings).toContainText('Financial figures withheld')
    await expect(earnings).not.toContainText('Quarter ending')
    await dialog.getByText('Evidence dates for this decision', {exact: true}).click()
    const dates = dialog.getByRole('region', {name: 'Recorded analyst evidence dates', exact: true})
    await expect(dates.getByRole('row', {name: 'Gross margin 2026-03-31'})).toBeVisible()
    await expect(dates).toContainText(NO_SOURCE_LINK)
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// The new explanations and per-metric dates remain usable on a phone without horizontal panning.
test('fits analyst meanings and mixed fiscal dates on a phone', async ({page, baseURL}, testInfo) => {
  const diagnostics = await installScenario(page, baseURL!)
  try {
    await page.setViewportSize({width: 390, height: 844})
    await page.goto('/#desk')
    if (await page.getByRole('button', {name: 'Hide Sidebar'}).isVisible()) await page.mouse.click(380, 500)
    await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
    const expansion = page.getByRole('region', {name: 'AAOI decision details', exact: true})
    await expectMeanings(expansion)
    await expansion.getByText('Evidence dates for this decision', {exact: true}).click()
    await expect(expansion.getByRole('row', {name: 'Gross margin 2026-03-31'})).toBeVisible()
    // The actual document width must remain inside the mobile viewport.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await expansion.getByRole('button', {name: 'Open the full panel'}).click()
    const dialog = page.getByRole('dialog', {name: 'AAOI history'})
    await expectMeanings(dialog)
    await dialog.getByText('Evidence dates for this decision', {exact: true}).click()
    const dates = dialog.getByRole('region', {name: 'Recorded analyst evidence dates', exact: true})
    // Center the date block rather than leaving its last pixel against the viewport edge.
    await dates.evaluate(element => element.scrollIntoView({block: 'center'}))
    // The open date block and the dialog must not create horizontal scrolling.
    expect(await dialog.evaluate(element => element.scrollWidth <= window.innerWidth)).toBe(true)
    await expect(dates).toBeInViewport({ratio: 1})
    await page.screenshot({path: testInfo.outputPath('mobile-analyst-dates.png'), fullPage: true})
    await dialog.getByRole('button', {name: 'Close', exact: true}).click()
    await expect(dialog).not.toBeVisible()
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})
