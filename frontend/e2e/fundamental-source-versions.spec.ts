import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'fundamental-source-fixture'
const CURRENT = 'fundamentals-features/2'
const PRIOR = 'fundamentals-features/1'
const POLICY = 'cash-bounded-breakout-rotation/3'
const CURRENT_NOTICE = 'Fundamentals: stored filing versions; margin period dates checked.'
const PRIOR_NOTICE = 'Fundamentals: stored filing versions (earlier margin calculation).'
const LEGACY_NOTICE = 'Fundamentals: frozen EDGAR snapshot (legacy).'
const UNKNOWN_NOTICE = 'Fundamentals: unrecognized recorded data source.'
const ABSENT_NOTICE = 'Fundamentals: data source not tagged.'
type Case = {name: string; record?: string; backtest?: string; notice: string; curveLabel: string; curveNote: string; policy?: string; phone?: boolean}

// Keep the latest recorded input source independent of the immutable historical simulation source.
async function install(page: Page, frontendURL: string, scenario: Case) {
  const latest = {
    session: '2026-09-24', written: '2026-09-24T00:00:00Z', provenance: {data: {fundamentals: scenario.record}},
    regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {},
    curve: {backtest: {label: 'Saved simulation', asof: '2026-09-23', dates: ['2026-09-22', '2026-09-23'], rules: [0, .02], spy: [0, .01], qqq: [0, .015], stats: {cagr: .1, volatility: .2, drawdown: -.01, total: .02}, strategy_policy: scenario.policy ?? POLICY, fundamentals_source: scenario.backtest, funding_model: 'cash-at-fill-v1'}},
  }
  const original = JSON.stringify(latest)
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  const reads: string[] = []
  // Retain console failures even if the expected provenance text renders.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A partial chart render must not conceal a page exception.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Detect required requests that fail before receiving a response.
  page.on('requestfailed', request => diagnostics.failedRequests.push(request.url()))
  // Detect HTTP errors independently of runtime exceptions.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date('2026-09-24T14:00:00Z')})
  // Stabilize appearance without reading the operator's browser preferences.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Serve only named synthetic read boundaries and the explicit non-recording preview.
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
    reads.push(url.pathname)
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, is_admin: false, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [latest.session]}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/live`) json = {as_of: '2026-09-24T14:00:00Z', quotes: {AAPL: {last: 110, bar: '2026-09-24T13:45:00Z'}}, technical: {}, technical_detail: {}}
    else if (url.pathname === `${base}/session-prices`) json = {as_of: '2026-09-24T14:00:00Z', session: 'regular', signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/mine`) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Waiting'}}}}
    else if (url.pathname === `${base}/entries` || url.pathname === `${base}/intraday`) json = {rows: [], top_buys: [], changed: []}
    else if (url.pathname === `${base}/paper`) json = {reason: 'unavailable'}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified request'}})
    }
    return route.fulfill({json})
  })
  return {latest, original, diagnostics, reads}
}

// Record all strict browser boundaries and prove no source tag or historical result was rewritten.
async function finish(testInfo: TestInfo, fixture: Awaited<ReturnType<typeof install>>) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(fixture.diagnostics, null, 2), contentType: 'application/json'})
  await testInfo.attach('source-and-reads', {body: JSON.stringify({latest: fixture.latest, reads: fixture.reads}, null, 2), contentType: 'application/json'})
  for (const [category, errors] of Object.entries(fixture.diagnostics)) expect.soft(errors, category).toEqual([])
  expect(JSON.stringify(fixture.latest)).toBe(fixture.original)
}

const cases: Case[] = [
  {name: 'current record and simulation', record: CURRENT, backtest: CURRENT, notice: CURRENT_NOTICE, curveLabel: 'Current policy simulation', curveNote: 'cash capped after costs'},
  {name: 'prior record and simulation', record: PRIOR, backtest: PRIOR, notice: PRIOR_NOTICE, curveLabel: 'Current policy, older fundamental inputs', curveNote: 'Uses the earlier stored-filing calculation, before margin period dates were checked.'},
  {name: 'legacy record and simulation', record: 'edgar-frozen', backtest: 'edgar-frozen', notice: LEGACY_NOTICE, curveLabel: 'Current policy, older fundamental inputs', curveNote: 'Uses the frozen EDGAR snapshot, not the current stored-filing calculation.'},
  {name: 'unrecognized record and simulation', record: 'fundamentals-features/3', backtest: 'fundamentals-features/3', notice: UNKNOWN_NOTICE, curveLabel: 'Current policy, fundamental inputs unverified', curveNote: 'The recorded fundamental source is not recognized; its inputs cannot be verified.'},
  {name: 'absent record and simulation source', notice: ABSENT_NOTICE, curveLabel: 'Current policy, fundamental inputs unverified', curveNote: 'The simulation did not record its fundamental data source; its inputs cannot be verified.'},
  {name: 'current record retains prior simulation', record: CURRENT, backtest: PRIOR, notice: CURRENT_NOTICE, curveLabel: 'Current policy, older fundamental inputs', curveNote: 'Uses the earlier stored-filing calculation, before margin period dates were checked.'},
  {name: 'prior record beside current simulation', record: PRIOR, backtest: CURRENT, notice: PRIOR_NOTICE, curveLabel: 'Current policy simulation', curveNote: 'cash capped after costs'},
  {name: 'current record retains legacy simulation', record: CURRENT, backtest: 'edgar-frozen', notice: CURRENT_NOTICE, curveLabel: 'Current policy, older fundamental inputs', curveNote: 'Uses the frozen EDGAR snapshot, not the current stored-filing calculation.'},
  {name: 'current record does not identify unknown simulation', record: CURRENT, backtest: 'other-source', notice: CURRENT_NOTICE, curveLabel: 'Current policy, fundamental inputs unverified', curveNote: 'The recorded fundamental source is not recognized; its inputs cannot be verified.'},
  {name: 'current record does not supply missing simulation source', record: CURRENT, notice: CURRENT_NOTICE, curveLabel: 'Current policy, fundamental inputs unverified', curveNote: 'The simulation did not record its fundamental data source; its inputs cannot be verified.'},
  {name: 'current fundamentals cannot upgrade old execution policy', record: CURRENT, backtest: CURRENT, policy: 'cash-bounded-breakout-rotation/2', notice: CURRENT_NOTICE, curveLabel: 'Older policy simulation', curveNote: 'Predates the shared strategy rules; awaiting a new nightly simulation.'},
  {name: 'phone keeps prior simulation distinct after reload', record: CURRENT, backtest: PRIOR, notice: CURRENT_NOTICE, curveLabel: 'Current policy, older fundamental inputs', curveNote: 'Uses the earlier stored-filing calculation, before margin period dates were checked.', phone: true},
]

for (const scenario of cases) {
  // Exercise both rendered provenance locations and reload while retaining independent original tags.
  test(`fundamental provenance: ${scenario.name}`, async ({page, baseURL}, testInfo) => {
    if (scenario.phone) await page.setViewportSize({width: 390, height: 844})
    const fixture = await install(page, baseURL!, scenario)
    try {
      await page.goto('/?deskDetails=1#desk')
      for (const reloaded of [false, true]) {
        if (reloaded) await page.reload()
        await page.getByRole('group', {name: 'Strategy details'}).locator(':scope > summary').click()
        const detailSource = page.getByLabel('Fundamental data source', {exact: true})
        await expect(detailSource).toHaveText(scenario.notice)
        await expect(detailSource).toHaveAttribute('title', `Recorded fundamental source: ${scenario.record || 'not recorded'}.`)
        await page.locator('summary', {hasText: 'Practice account'}).click()
        const glance = page.getByLabel('The desk at a glance')
        await expect(glance.getByLabel('Summary fundamental data source')).toHaveText(scenario.notice)
        await expect(glance.getByLabel('Summary fundamental data source')).toHaveAttribute('title', `Recorded fundamental source: ${scenario.record || 'not recorded'}.`)
        const curve = glance.getByText(scenario.curveLabel, {exact: true})
        await expect(curve).toBeVisible()
        await expect(curve).toHaveAttribute('title', `Recorded simulation fundamental source: ${scenario.backtest || 'not recorded'}.`)
        await expect(glance).toContainText(scenario.curveNote)
        await expect(glance).toContainText('+2.0%')
        await expect(glance).toContainText('vs SPY ↑ +1.0%')
        await expect(glance).toContainText('QQQ ↑ +1.5%')
        if (scenario.curveLabel !== 'Current policy simulation') await expect(glance.getByText('Current policy simulation', {exact: true})).toHaveCount(0)
        if (scenario.record !== 'edgar-frozen' && scenario.backtest !== 'edgar-frozen') await expect(glance).not.toContainText('frozen EDGAR snapshot')
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      if (scenario.phone || scenario.name === 'current record and simulation') {
        await page.screenshot({path: testInfo.outputPath('fundamental-provenance.png'), fullPage: true})
        await page.getByLabel('The desk at a glance').screenshot({path: testInfo.outputPath('simulation-provenance.png')})
      }
    } finally {await finish(testInfo, fixture)}
  })
}
