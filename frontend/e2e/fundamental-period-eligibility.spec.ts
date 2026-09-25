import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'fundamental-period-fixture'
const SOURCE = 'fundamentals-features/3'
const TARGET = '2026-06-30'
const OLD = '2018-06-30'
const METRICS = ['revenue_yoy', 'revenue_qoq', 'revenue_acceleration', 'gross_margin', 'net_margin', 'capex_to_revenue', 'ocf_to_revenue']
const HEADLINE = 'Original saved wording stays unchanged'
type Eligibility = {revenue_period_end: string; score_available: boolean; vote_reset: boolean; features: Record<string, {status: string; input_period_end: string}>}
type Scenario = {name: string; source?: string; entry?: unknown; eligibility?: unknown; expected?: string; unavailable?: boolean; ignored?: boolean; phone?: boolean}

// Supply a valid mixed result, including a reset despite enough remaining ranked inputs.
function eligibility(): Eligibility {
  return {revenue_period_end: TARGET, score_available: true, vote_reset: true, features: Object.fromEntries(METRICS.map(name => [name,
    name === 'gross_margin' ? {status: 'older_revenue_period', input_period_end: OLD}
      : name === 'capex_to_revenue' || name === 'ocf_to_revenue' ? {status: 'not_computable', input_period_end: ''}
        : {status: 'accepted', input_period_end: TARGET},
  ]))}
}

// Keep the source-tagged record immutable while intercepting every browser API request.
async function install(page: Page, frontendURL: string, scenario: Scenario) {
  const entry = scenario.entry as Eligibility | undefined
  const dates = Object.fromEntries(METRICS.map(name => [name, entry?.features?.[name]?.status === 'accepted' ? TARGET : '']))
  const fundamental = {source: scenario.source, dates: {AAPL: scenario.ignored ? {gross_margin: OLD} : dates},
    ...(scenario.eligibility !== undefined ? {eligibility: scenario.eligibility} : scenario.entry !== undefined ? {eligibility: {AAPL: scenario.entry}} : {})}
  const latest = {session: '2026-09-24', written: '2026-09-24T21:05:00Z', fundamental,
    provenance: {data: {fundamentals: scenario.source}}, regime: {exposure: 1, flags: []},
    grades: {AAPL: {grade: 'C', score: 0, votes: 0, stances: {fundamental: 0}, ranks: {}, headline: HEADLINE, reason: 'Original recorded explanation.'}}, book: [], actions: [], briefs: {}}
  const original = JSON.stringify(latest)
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  // Retain console errors even when the evidence table renders.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A rendered fragment must not conceal a page exception.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Track required requests that fail before a response arrives.
  page.on('requestfailed', request => diagnostics.failedRequests.push(request.url()))
  // Refuse successful validation when a required endpoint returns an error.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date('2026-09-25T14:00:00Z')})
  // Stabilize the fixture without reading the operator's preferences.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Serve only named synthetic reads and the explicit non-recording preview.
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), base = `/api/v1/market/${USER}/desk`
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const preview = url.pathname === `${base}/mine` && request.method() === 'POST' && request.postDataJSON()?.record_history === false
    if (request.method() !== 'GET' && !preview) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids persistence'}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [latest.session]}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/live`) json = {as_of: '2026-09-25T14:00:00Z', quotes: {AAPL: {last: 110, bar: '2026-09-25T13:45:00Z'}}, technical: {}, technical_detail: {}}
    else if (url.pathname === `${base}/session-prices`) json = {as_of: '2026-09-25T14:00:00Z', session: 'regular', signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/mine`) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Waiting'}}}}
    else if (url.pathname === `${base}/entries` || url.pathname === `${base}/intraday`) json = {rows: [], top_buys: [], changed: []}
    else if (url.pathname === `${base}/paper`) json = {reason: 'unavailable'}
    else if (url.pathname === `${base}/history/AAPL`) json = {ticker: 'AAPL', rows: [], recommendations: {observations: []}}
    else if (url.pathname === `${base}/chart/AAPL`) json = {ticker: 'AAPL', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'synthetic fixture', bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname === `${base}/earnings/AAPL` || url.pathname === `${base}/live/read/AAPL`) json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified request'}})
    }
    return route.fulfill({json})
  })
  return {latest, original, diagnostics}
}

// Check metadata where users open evening evidence, without upgrading older source versions.
async function check(surface: ReturnType<Page['getByRole']>, scenario: Scenario) {
  const evidence = surface.getByRole('region', {name: 'Recorded analyst evidence dates', exact: true})
  await evidence.getByText('Evidence dates for this decision', {exact: true}).click()
  await expect(evidence).toContainText(`F fiscal-date metadata source: ${scenario.source || 'not recorded'}.`)
  if (scenario.ignored) {
    await expect(evidence).toContainText(OLD)
    await expect(evidence).not.toContainText('Passed reporting-period check')
    await expect(evidence).not.toContainText('any previously held vote was cleared')
    await expect(evidence.getByRole('table', {name: 'Fundamental reporting-period checks'})).toHaveCount(0)
  } else if (scenario.unavailable) {
    await expect(evidence).toContainText('Reporting-period check details are unavailable for this name.')
    await expect(evidence).not.toContainText('Passed reporting-period check')
    await expect(evidence).not.toContainText('A fundamental score was available.')
    await expect(evidence).not.toContainText('any previously held vote was cleared')
  } else {
    await expect(evidence.getByRole('table', {name: 'Fundamental reporting-period checks'}).locator('tbody tr')).toHaveCount(7)
    await expect(evidence).toContainText(scenario.expected!)
    await expect(evidence).toContainText('This check does not establish data freshness, financial completeness or fair value.')
    await expect(evidence).toContainText('Other metrics are context only.')
    const entry = scenario.entry as Eligibility
    await expect(evidence).toContainText(entry.score_available ? 'A fundamental score was available.' : 'Not enough eligible ranked inputs for a fundamental score; the fundamental vote is neutral.')
    if (entry.vote_reset) await expect(evidence).toContainText('The fundamental vote is neutral; any previously held vote was cleared. A new vote requires confirmation.')
    else await expect(evidence).not.toContainText('any previously held vote was cleared')
    const rows = evidence.getByRole('table', {name: 'Fundamental reporting-period checks'}).locator('tbody tr')
    for (const [index, name] of METRICS.entries()) {
      await expect(rows.nth(index)).toContainText(`Input period end: ${entry.features[name].input_period_end || 'Unavailable'}`)
      await expect(rows.nth(index)).toContainText(`Revenue reference end: ${entry.revenue_period_end || 'Unavailable'}`)
    }
  }
  await expect(surface).toContainText('Original recorded explanation.')
  await surface.getByText('Original recorded wording', {exact: true}).click()
  await expect(surface.getByText(HEADLINE, {exact: true})).toBeVisible()
}

const unscored = eligibility()
unscored.score_available = false
for (const name of METRICS.slice(0, 4)) unscored.features[name] = {status: 'older_revenue_period', input_period_end: OLD}
const noRevenue = eligibility()
noRevenue.revenue_period_end = ''
noRevenue.score_available = false
for (const name of METRICS) noRevenue.features[name] = {status: 'no_revenue_period', input_period_end: ''}
const mismatch = eligibility()
mismatch.vote_reset = false
mismatch.features.gross_margin = {status: 'period_mismatch', input_period_end: '2026-09-30'}
const badStatus = eligibility()
badStatus.features.gross_margin.status = 'future_status'
const badInput = eligibility()
badInput.features.gross_margin.input_period_end = '2026-02-30'
const wrongAccepted = eligibility()
wrongAccepted.features.revenue_yoy.input_period_end = OLD
const missingMetric = eligibility()
delete missingMetric.features.gross_margin
const scenarios: Scenario[] = [
  {name: 'accepted and excluded metrics with a finite score reset', source: SOURCE, entry: eligibility(), expected: 'Passed reporting-period check'},
  {name: 'unscored name retains exclusion evidence', source: SOURCE, entry: unscored, expected: 'Excluded: input predates the latest reported revenue period.'},
  {name: 'phone retains unscored name and original dates', source: SOURCE, entry: unscored, expected: 'Excluded: input predates the latest reported revenue period.', phone: true},
  {name: 'missing revenue period is not invented', source: SOURCE, entry: noRevenue, expected: 'Unavailable: no eligible reported revenue period was recorded.'},
  {name: 'period mismatch does not assert a vote reset', source: SOURCE, entry: mismatch, expected: 'Excluded: input period does not match the reported revenue period.'},
  {name: 'absent eligibility', source: SOURCE, unavailable: true},
  {name: 'another ticker cannot supply eligibility', source: SOURCE, eligibility: {MSFT: eligibility()}, unavailable: true},
  {name: 'unknown status fails closed', source: SOURCE, entry: badStatus, unavailable: true},
  {name: 'invalid input calendar date fails closed', source: SOURCE, entry: badInput, unavailable: true},
  {name: 'invalid reference calendar date fails closed', source: SOURCE, entry: {...eligibility(), revenue_period_end: '2026-13-30'}, unavailable: true},
  {name: 'accepted input must equal reference period', source: SOURCE, entry: wrongAccepted, unavailable: true},
  {name: 'Boolean flags are not coerced', source: SOURCE, entry: {...eligibility(), score_available: 'true', vote_reset: 1}, unavailable: true},
  {name: 'missing score cannot claim no vote reset', source: SOURCE, entry: {...unscored, vote_reset: false}, unavailable: true},
  {name: 'context-only acceptance cannot establish a score', source: SOURCE, entry: {...unscored, score_available: true}, unavailable: true},
  {name: 'array cannot supply eligibility', source: SOURCE, entry: [], unavailable: true},
  {name: 'missing metric fails closed', source: SOURCE, entry: missingMetric, unavailable: true},
  ...['fundamentals-features/2', 'fundamentals-features/1', 'edgar-frozen', 'fundamentals-features/99', undefined].map(source => ({name: `${source ?? 'absent source'} ignores foreign eligibility`, source, entry: eligibility(), ignored: true})),
]

for (const scenario of scenarios) {
  // Walk both the expanded board and full ticker panel, preserving the saved record and errors.
  test(`reporting-period evidence: ${scenario.name}`, async ({page, baseURL}, testInfo: TestInfo) => {
    if (scenario.phone) await page.setViewportSize({width: 390, height: 844})
    const fixture = await install(page, baseURL!, scenario)
    try {
      await page.goto('/#desk')
      await page.getByRole('button', {name: 'details for AAPL', exact: true}).click()
      const expansion = page.getByRole('region', {name: 'AAPL decision details', exact: true})
      await check(expansion, scenario)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await expansion.getByRole('button', {name: 'Open the full panel'}).click()
      const dialog = page.getByRole('dialog', {name: 'AAPL history'})
      await check(dialog, scenario)
      expect(await dialog.evaluate(element => element.scrollWidth <= innerWidth)).toBe(true)
      if (scenario.phone || scenario.name === 'accepted and excluded metrics with a finite score reset') {
        await dialog.getByRole('region', {name: 'Recorded analyst evidence dates'}).screenshot({path: testInfo.outputPath('reporting-period-evidence.png')})
      }
      await dialog.getByRole('button', {name: 'Close', exact: true}).click()
      await page.reload()
      await page.getByRole('button', {name: 'details for AAPL', exact: true}).click()
      await check(page.getByRole('region', {name: 'AAPL decision details', exact: true}), scenario)
      expect(JSON.stringify(fixture.latest)).toBe(fixture.original)
    } finally {
      await testInfo.attach('browser-diagnostics', {body: JSON.stringify(fixture.diagnostics, null, 2), contentType: 'application/json'})
      for (const [category, errors] of Object.entries(fixture.diagnostics)) expect.soft(errors, category).toEqual([])
    }
  })
}
