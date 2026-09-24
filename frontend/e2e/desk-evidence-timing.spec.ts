import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'ani.mallya'
const SESSION = '2026-09-23'
const WRITTEN = '2026-09-23T21:05:00Z'
const NOW = '2026-09-24T15:35:00Z'
const BAR = '2026-09-24T15:15:00Z'
const HEADLINE = 'Own: 3 analysts for, none against'
const REASON = '+ Fundamental: revenue growth high in book\n+ Sentiment: upbeat on guidance; upbeat on demand\n+ Value: relative valuation high in book'
const STANCES = {fundamental: 1, technical: 0, sentiment: 1, value: 1, rotation: 0}
const RANKS = {fundamental: .875, technical: .293, sentiment: .881, value: .786, rotation: .5}
type EvidenceState = 'current' | 'expired' | 'missing'

// Supply the same recorded decision with a current, expired or missing intraday update.
function evidenceFixture(withRow: boolean, state: EvidenceState) {
  const latest = {
    session: SESSION, written: WRITTEN,
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAOI: {grade: 'A+', votes: 3, stances: STANCES, ranks: RANKS, score: .82, side: 'ai', headline: HEADLINE, reason: REASON}},
    book: [], briefs: {}, paper: null,
  }
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-24', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
  const current = {grade_live: 'B', score_live: .4, technical_now: .2, technical_close: .293, stances_live: {...STANCES, technical: -1}, ranks_live: {...RANKS, technical: .2}}
  const mine = {
    session: SESSION, market_status: market,
    grade_valid_until: state === 'missing' ? {} : {AAOI: state === 'expired' ? '2026-09-24T15:30:00Z' : '2026-09-24T15:45:00Z'},
    grades_live: state === 'missing' ? {} : {AAOI: current},
    rows: withRow ? [{ticker: 'AAOI', ...current, grade: 'A+', grade_source: 'intraday', action: 'hold', in_book: false, score: .82, rank: 1, stances: STANCES, ranks: RANKS, target_weight: 0, current_weight: 0, delta_weight: 0, shares: 0, entry_price: null, entry_date: null, last: 98.25, last_close: 101, pl_pct: null, until_rebalance: null, rebalance_due: false}] : [],
    decisions: {session: SESSION, written: WRITTEN, as_of: NOW, rows: {AAOI: {action: 'Hold', strategy_action: 'Hold', executable: false, reason: 'No entry instruction.', valid_until: '2026-09-24T15:45:00Z', target_weight: 0, current_weight: 0, move_weight: 0}}},
  }
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAOI: {symbol: 'AAOI', last: 98.25, open: 101, high: 102, low: 98, bar: BAR, as_of: NOW}}, technical: {AAOI: {now: .2, close: .293}}, technical_detail: {AAOI: {now: .2, short: {}, medium: {}, long: {}}}}
  return {latest, mine, live}
}

// Keep the complete browser journey local and fail on errors, unhandled requests or writes.
async function installEvidenceFixture(page: Page, withRow: boolean, state: EvidenceState, frontendURL: string) {
  const fixture = evidenceFixture(withRow, state)
  const frontendOrigin = new URL(frontendURL).origin
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  // Record browser failures independently of the rendered-content assertions.
  page.on('console', message => { if (message.type() === 'error') diagnostics.consoleErrors.push(message.text()) })
  // Page exceptions must fail even if another part of the panel still renders.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Every required request in this bounded fixture must complete successfully.
  page.on('requestfailed', request => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  // HTTP failures must not be hidden behind a successful page navigation.
  page.on('response', response => { if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`) })
  await page.clock.install({time: new Date(NOW)})
  // Keep appearance independent of the machine's clock and saved preferences.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Fulfill all API calls without a backend and reject any persistence request.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === frontendOrigin) return route.continue()
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
    else if (url.pathname === base) json = {latest: fixture.latest, sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = fixture.live
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = fixture.mine
    else if (url.pathname === `${base}/intraday`) json = {session: SESSION, as_of: NOW, equity: 100000, rows: [], changed: [], top_buys: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/entries`) json = {user_id: USER, session: SESSION, rows: []}
    else if (url.pathname === `${base}/history/AAOI`) json = {ticker: 'AAOI', asof: SESSION, horizon: 20, backtest: null, rows: [], recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname === `${base}/earnings/AAOI`) json = {user_id: USER, symbol: 'AAOI', read: null}
    else if (url.pathname === `${base}/chart/AAOI`) json = {user_id: USER, ticker: 'AAOI', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'deterministic fixture', sessions: 0, bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname === `${base}/live/read/AAOI`) json = {symbol: 'AAOI', now: .2, data_at: BAR, read_at: NOW, stale: false, read: 'Dated technical evidence.', lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    return route.fulfill({json})
  })
  return {fixture, diagnostics}
}

// Check the same dated separation and preserved original headline in both detail surfaces.
async function expectSeparatedEvidence(surface: ReturnType<Page['getByRole']>, current: boolean) {
  const latest = surface.getByRole('region', {name: 'Latest available grade', exact: true})
  const evening = surface.getByRole('region', {name: 'Evening analysis', exact: true})
  await expect(latest.getByLabel('Latest grade value', {exact: true})).toHaveText(current ? 'B' : 'A+')
  await expect(latest).toContainText(current ? 'intraday' : `at the ${SESSION} close`)
  await expect(latest).not.toContainText(HEADLINE)
  await expect(evening).toContainText(`Evening analysis · ${SESSION}`)
  await expect(evening).toContainText('Recorded grade A+')
  await expect(evening).toContainText('F+ T· S+ V+ R·')
  await expect(evening).toContainText('Not a current trade instruction.')
  for (const line of REASON.split('\n')) await expect(evening).toContainText(line)
  await expect(evening.getByText(HEADLINE, {exact: true})).not.toBeVisible()
  await evening.getByText('Original recorded wording', {exact: true}).click()
  await expect(evening.getByText(HEADLINE, {exact: true})).toHaveText(HEADLINE)
  await expect(evening.getByText(HEADLINE, {exact: true})).toBeVisible()
  await evening.getByText('Original recorded wording', {exact: true}).click()
  if (current) await expect(latest).toContainText('Since evening: T no view → against.')
  else await expect(latest).not.toContainText('Since evening:')
}

// Retain page diagnostics even when a rendered-content regression fails first.
async function recordDiagnostics(testInfo: TestInfo, diagnostics: object) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json'})
  for (const errors of Object.values(diagnostics)) expect(errors).toEqual([])
}

for (const withRow of [false, true]) {
  for (const state of ['current', 'expired', 'missing'] as const) {
    // Neither a personal row nor missing fresh evidence may disguise the evening recommendation.
    test(`separates ${state} grade from recorded wording ${withRow ? 'with' : 'without'} a personal row`, async ({page, baseURL}, testInfo) => {
      const {fixture, diagnostics} = await installEvidenceFixture(page, withRow, state, baseURL!)
      try {
        await page.goto('/#desk')
        await expect(page.getByLabel('AAOI grade', {exact: true})).toContainText(state === 'current' ? 'B' : 'A+')
        await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
        const expansion = page.getByRole('region', {name: 'AAOI decision details', exact: true})
        await expectSeparatedEvidence(expansion, state === 'current')
        await expect(expansion).toContainText('F88+')
        await expect(expansion).toContainText('S88+')
        await expansion.getByRole('button', {name: 'Open the full panel'}).click()
        const dialog = page.getByRole('dialog', {name: 'AAOI history'})
        await expectSeparatedEvidence(dialog, state === 'current')
        await expect(dialog.getByRole('region', {name: 'Latest available grade', exact: true})).toContainText('Sep 24, 11:15 AM ET')
        await expect(dialog.getByRole('region', {name: 'Evening analysis', exact: true})).not.toContainText('$98.25')
        await page.screenshot({path: testInfo.outputPath('dated-detail.png'), fullPage: true})
        expect(fixture.latest.grades.AAOI.headline).toBe(HEADLINE)
        expect(fixture.latest.grades.AAOI.grade).toBe('A+')
      } finally {
        await recordDiagnostics(testInfo, diagnostics)
      }
    })
  }

  // The existing expiry clock must remove live vote changes while the dialog remains open.
  test(`expires live detail without rewriting evening evidence ${withRow ? 'with' : 'without'} a personal row`, async ({page, baseURL}, testInfo) => {
    const {diagnostics} = await installEvidenceFixture(page, withRow, 'current', baseURL!)
    try {
      await page.goto('/#desk')
      await page.getByRole('button', {name: 'AAOI', exact: true}).click()
      const dialog = page.getByRole('dialog', {name: 'AAOI history'})
      await expectSeparatedEvidence(dialog, true)
      await page.clock.fastForward('11:00')
      await expectSeparatedEvidence(dialog, false)
      await dialog.getByRole('button', {name: 'Close', exact: true}).click()
      await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
      await expectSeparatedEvidence(page.getByRole('region', {name: 'AAOI decision details', exact: true}), false)
    } finally {
      await recordDiagnostics(testInfo, diagnostics)
    }
  })
}

// Dated grade sections and the original-wording controls remain usable without mobile panning.
test('dated evening and intraday details fit a phone with usable archive controls', async ({page, baseURL}, testInfo) => {
  const {diagnostics} = await installEvidenceFixture(page, false, 'current', baseURL!)
  try {
    await page.setViewportSize({width: 390, height: 844})
    await page.goto('/#desk')
    if (await page.getByRole('button', {name: 'Hide Sidebar'}).isVisible()) await page.mouse.click(380, 500)
    await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
    const expansion = page.getByRole('region', {name: 'AAOI decision details', exact: true})
    await expectSeparatedEvidence(expansion, true)
    // The expanded board must not make the document wider than the phone.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await expansion.scrollIntoViewIfNeeded()
    await page.screenshot({path: testInfo.outputPath('mobile-expansion.png'), fullPage: true})
    await expansion.getByRole('button', {name: 'Open the full panel'}).click()
    const dialog = page.getByRole('dialog', {name: 'AAOI history'})
    await expectSeparatedEvidence(dialog, true)
    // Check the actual dialog's horizontal content, not only the document width.
    expect(await dialog.evaluate(element => element.scrollWidth <= window.innerWidth)).toBe(true)
    await dialog.getByRole('heading', {name: 'AAOI', exact: true}).scrollIntoViewIfNeeded()
    await page.screenshot({path: testInfo.outputPath('mobile-detail.png'), fullPage: true})
    const evening = dialog.getByRole('region', {name: 'Evening analysis', exact: true})
    await evening.scrollIntoViewIfNeeded()
    await expect(evening).toBeInViewport({ratio: 1})
    await expect(dialog.getByRole('region', {name: 'Latest available grade', exact: true})).toBeInViewport({ratio: 1})
    await page.screenshot({path: testInfo.outputPath('mobile-detail-evidence.png'), fullPage: true})
    await dialog.getByRole('button', {name: 'Close', exact: true}).click()
    await expect(dialog).not.toBeVisible()
    await expect(expansion.getByRole('button', {name: 'Open the full panel'})).toBeVisible()
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})
