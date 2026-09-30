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

// Supply the recorded decision with a live candle beside it. The board reads no intraday grade
// since the redesign, so the latest available grade is the recorded one, dated to its close.
function evidenceFixture() {
  const latest = {
    session: SESSION, written: WRITTEN,
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAOI: {grade: 'A+', votes: 3, stances: STANCES, ranks: RANKS, score: .82, side: 'ai', headline: HEADLINE, reason: REASON}},
    book: [], briefs: {}, paper: null,
  }
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-24', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAOI: {symbol: 'AAOI', last: 98.25, open: 101, high: 102, low: 98, bar: BAR, as_of: NOW}}, technical: {AAOI: {now: .2, close: .293}}, technical_detail: {AAOI: {now: .2, short: {}, medium: {}, long: {}}}}
  return {latest, live}
}

// Keep the complete browser journey local and fail on errors, unhandled requests or writes.
async function installEvidenceFixture(page: Page, frontendURL: string) {
  const fixture = evidenceFixture()
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
    if (request.method() !== 'GET') {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids persistence'}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-25T00:00:00Z', is_admin: true, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest: fixture.latest, sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = fixture.live
    else if (url.pathname === `${base}/session-prices`) json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {AAOI: {
      price: null, at: null, feed: null, indicative: false, status: 'unavailable', reason: 'No optional session-price evidence in this fixture.', valid_until: null,
    }}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}, plan: {rule: 'dip_or_close', orders: [], until_rebalance: 7}}
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

// The latest available grade is dated to its close and never repeats the recorded headline; the
// evening analysis keeps the recorded grade, votes and reasons, with the original wording folded.
async function expectSeparatedEvidence(dialog: ReturnType<Page['getByRole']>) {
  const latest = dialog.getByRole('region', {name: 'Latest available grade', exact: true})
  const evening = dialog.getByRole('region', {name: 'Evening analysis', exact: true})
  await expect(latest.getByLabel('Latest grade value', {exact: true})).toHaveText('A+')
  await expect(latest).toContainText(`at the ${SESSION} close`)
  await expect(latest).not.toContainText(HEADLINE)
  await expect(latest).not.toContainText('Since evening:')
  await expect(evening).toContainText(`Evening analysis · ${SESSION}`)
  await expect(evening).toContainText('Recorded grade A+')
  await expect(evening).toContainText('F+ T· S+ V+ R·')
  for (const line of REASON.split('\n')) await expect(evening).toContainText(line)
  await expect(evening.getByText(HEADLINE, {exact: true})).not.toBeVisible()
  await evening.getByText('Original recorded wording', {exact: true}).click()
  await expect(evening.getByText(HEADLINE, {exact: true})).toHaveText(HEADLINE)
  await expect(evening.getByText(HEADLINE, {exact: true})).toBeVisible()
  await evening.getByText('Original recorded wording', {exact: true}).click()
}

// The row's details carry the recorded grade and its reasons; the full panel opens from them.
async function openPanelFromRow(page: Page) {
  await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
  const grade = page.getByRole('region', {name: 'AAOI grade', exact: true})
  await expect(grade).toContainText(`Grade A+ · ${SESSION} close`)
  await expect(grade).toContainText(HEADLINE)
  for (const line of REASON.split('\n')) await expect(grade).toContainText(line)
  await grade.getByRole('button', {name: 'Chart and full history'}).click()
  return page.getByRole('dialog', {name: 'AAOI history'})
}

// Fail on every browser-error category without replacing an earlier content assertion failure.
async function recordDiagnostics(testInfo: TestInfo, diagnostics: object) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json'})
  for (const [category, errors] of Object.entries(diagnostics)) expect.soft(errors, `Browser ${category}`).toEqual([])
}

// A live candle beside the recorded decision may not disguise the evening recommendation.
test('separates the latest grade from the recorded wording', async ({page, baseURL}, testInfo) => {
  const {fixture, diagnostics} = await installEvidenceFixture(page, baseURL!)
  try {
    await page.goto('/#desk')
    await expect(page.getByLabel('AAOI displayed grade', {exact: true})).toHaveText('A+')
    const dialog = await openPanelFromRow(page)
    await expectSeparatedEvidence(dialog)
    const latest = dialog.getByRole('region', {name: 'Latest available grade', exact: true})
    await expect(latest).toContainText('F88+')
    await expect(latest).toContainText('S88+')
    await expect(latest).toContainText('Sep 24, 11:15 AM ET')
    await expect(dialog.getByRole('region', {name: 'Evening analysis', exact: true})).not.toContainText('$98.25')
    await page.screenshot({path: testInfo.outputPath('dated-detail.png'), fullPage: true})
    expect(fixture.latest.grades.AAOI.headline).toBe(HEADLINE)
    expect(fixture.latest.grades.AAOI.grade).toBe('A+')
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// Center both measured grade regions in their native scrollport without changing fit criteria.
async function alignGradeEvidenceInScrollport(dialog: ReturnType<Page['getByRole']>) {
  await dialog.evaluate(element => {
    const first = element.querySelector('[aria-label="Latest available grade"]')
    const last = element.querySelector('[aria-label="Evening analysis"]')
    if (!first || !last) throw new Error('Both grade regions must be present')
    let scrollport = first.parentElement
    while (scrollport && !(scrollport.scrollHeight > scrollport.clientHeight && ['auto', 'scroll'].includes(getComputedStyle(scrollport).overflowY))) {
      scrollport = scrollport.parentElement
    }
    if (!scrollport) throw new Error('No native vertical evidence scrollport')
    const firstRect = first.getBoundingClientRect()
    const lastRect = last.getBoundingClientRect()
    const unionTop = Math.min(firstRect.top, lastRect.top)
    const unionBottom = Math.max(firstRect.bottom, lastRect.bottom)
    if (unionBottom - unionTop > scrollport.clientHeight) throw new Error('Both grade regions must fit the actual scrollport')
    const portTop = scrollport.getBoundingClientRect().top + scrollport.clientTop
    scrollport.scrollBy({top: (unionTop + unionBottom) / 2 - (portTop + scrollport.clientHeight / 2), behavior: 'instant'})
  })
}

// Dated grade sections and the original-wording controls remain usable without mobile panning.
test('dated evening details fit a phone with usable archive controls', async ({page, baseURL}, testInfo) => {
  const {diagnostics} = await installEvidenceFixture(page, baseURL!)
  try {
    await page.setViewportSize({width: 390, height: 844})
    await page.goto('/#desk')
    if (await page.getByRole('button', {name: 'Hide Sidebar'}).isVisible()) await page.mouse.click(380, 500)
    await page.getByRole('button', {name: 'details for AAOI', exact: true}).click()
    const grade = page.getByRole('region', {name: 'AAOI grade', exact: true})
    await expect(grade).toContainText(HEADLINE)
    // The expanded board must not make the document wider than the phone.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await grade.scrollIntoViewIfNeeded()
    await page.screenshot({path: testInfo.outputPath('mobile-expansion.png'), fullPage: true})
    await grade.getByRole('button', {name: 'Chart and full history'}).click()
    const dialog = page.getByRole('dialog', {name: 'AAOI history'})
    await expectSeparatedEvidence(dialog)
    // Check the actual dialog's horizontal content, not only the document width.
    expect(await dialog.evaluate(element => element.scrollWidth <= window.innerWidth)).toBe(true)
    await dialog.getByRole('heading', {name: /^AAOI/}).scrollIntoViewIfNeeded()
    await page.screenshot({path: testInfo.outputPath('mobile-detail.png'), fullPage: true})
    const evening = dialog.getByRole('region', {name: 'Evening analysis', exact: true})
    await evening.scrollIntoViewIfNeeded()
    await alignGradeEvidenceInScrollport(dialog)
    await expect(evening).toBeInViewport({ratio: 1})
    await expect(dialog.getByRole('region', {name: 'Latest available grade', exact: true})).toBeInViewport({ratio: 1})
    await page.screenshot({path: testInfo.outputPath('mobile-detail-evidence.png'), fullPage: true})
    await dialog.getByRole('button', {name: 'Close', exact: true}).click()
    await expect(dialog).not.toBeVisible()
    await expect(grade.getByRole('button', {name: 'Chart and full history'})).toBeVisible()
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})
