import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'chart-wording-fixture'
const CAPTION = 'Saved grades use nightly records; recalculated grades use historical data. Grade changes are not trades.'
const HELP = 'Dates identify trading sessions, not publication times. A or A+ meets only the grade requirement for entry; other checks still apply.'
type CanvasState = Window & {__gradeDraws: {text: string; timeframe: string | null}[]}

// Build immutable saved and recalculated evidence behind the real chart and inspect its paint calls.
async function install(page: Page, frontendURL: string) {
  const history = {ticker: 'AAPL', rows: [
    {date: '2026-09-14', grade: 'A', said: true},
    {date: '2026-09-15', grade: 'B', said: true},
    {date: '2026-09-17', grade: 'A', said: false},
  ].map(row => ({...row, votes: 3, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, earnings: false})), backtest: null, recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
  const original = JSON.stringify(history)
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  const reads: string[] = []
  // Keep runtime errors visible even when a text assertion passes.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // Fail on exceptions from partially rendered charts.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Record incomplete required requests instead of accepting silent fallbacks.
  page.on('requestfailed', request => diagnostics.failedRequests.push(request.url()))
  // Record unsuccessful responses independently of browser exceptions.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date('2026-09-24T14:00:00Z')})
  // Observe real canvas text without replacing chart rendering or reading private browser settings.
  await page.addInitScript(() => {
    localStorage.setItem('anios.theme', 'light')
    const state = window as unknown as CanvasState
    state.__gradeDraws = []
    const fillText = CanvasRenderingContext2D.prototype.fillText
    // Preserve every production paint call while recording grade marker labels and selected timeframe.
    CanvasRenderingContext2D.prototype.fillText = function (this: CanvasRenderingContext2D, ...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && args[0].includes('→')) {
        const timeframe = this.canvas.closest('section')?.querySelector('[aria-label="Chart timeframe"] [aria-pressed="true"]')?.textContent ?? null
        state.__gradeDraws.push({text: args[0], timeframe})
      }
      return fillText.apply(this, args)
    }
  })
  // Admit only named synthetic reads and the intercepted recommendation request; no request reaches a real account.
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const base = `/api/v1/market/${USER}/desk`
    const recommendation = url.pathname === `${base}/mine` && request.method() === 'POST' && request.postDataJSON()?.record_history === true
    if (request.method() !== 'GET' && !recommendation) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids writes'}})
    }
    reads.push(`${url.pathname}${url.search}`)
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, is_admin: false, desk_access: true, desk_write: true}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest: {session: '2026-09-24', written: '2026-09-24T00:00:00Z', regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: ['2026-09-24']}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/live`) json = {as_of: '2026-09-24T14:00:00Z', quotes: {AAPL: {last: 110, bar: '2026-09-24T13:45:00Z'}}, technical: {}, technical_detail: {}}
    else if (url.pathname === `${base}/session-prices`) json = {as_of: '2026-09-24T14:00:00Z', session: 'regular', signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/mine`) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Waiting'}}}}
    else if (url.pathname === `${base}/personal-history`) json = url.searchParams.has('before')
      ? {items: [{id: 'older', generated_at: '2026-09-14T14:30:00Z', payload: {rows: {AAPL: {action: 'Sell', strategy_action: 'Sell', grade: 'A'}}}}], next_cursor: null}
      : {items: [{id: 'saved', generated_at: '2026-09-15T14:30:00Z', payload: {rows: {AAPL: {action: 'Buy', strategy_action: 'Buy', grade: 'A'}}}}], next_cursor: 'earlier'}
    else if (url.pathname === `${base}/history/AAPL`) json = history
    else if (url.pathname === `${base}/chart/AAPL`) {
      const weekly = url.searchParams.get('timeframe') === 'weekly'
      const dates = weekly ? ['2026-09-11', '2026-09-18', '2026-09-24'] : ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-24']
      json = {ticker: 'AAPL', timeframe: weekly ? 'weekly' : 'daily', adjusted: true, basis: 'synthetic adjusted prices', sessions: dates.length, bars: dates.map(date => ({date, open: 100, high: 120, low: 90, close: 110, volume: 100})), overlays: {}, levels: {}, entries: [], data_status: 'complete'}
    } else if (url.pathname === `${base}/entries` || url.pathname === `${base}/intraday`) json = {rows: [], top_buys: [], changed: []}
    else if (url.pathname === `${base}/paper`) json = {reason: 'unavailable'}
    else if (url.pathname === `${base}/earnings/AAPL`) json = {symbol: 'AAPL', read: null}
    else if (url.pathname === `${base}/live/read/AAPL`) json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified request'}})
    }
    return route.fulfill({json})
  })
  return {history, original, diagnostics, reads}
}

// Persist strict browser diagnostics and confirm rendering never rewrote original grade evidence.
async function finish(testInfo: TestInfo, fixture: Awaited<ReturnType<typeof install>>) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(fixture.diagnostics, null, 2), contentType: 'application/json'})
  await testInfo.attach('source-and-reads', {body: JSON.stringify({history: fixture.history, reads: fixture.reads}, null, 2), contentType: 'application/json'})
  for (const [category, errors] of Object.entries(fixture.diagnostics)) expect.soft(errors, category).toEqual([])
  expect(JSON.stringify(fixture.history)).toBe(fixture.original)
}

for (const viewport of [{width: 1280, height: 900}, {width: 390, height: 844}]) {
  // Human source names must reach the real canvas and survive timeframe and visibility controls.
  test(`chart explains saved and recalculated grades at ${viewport.width}px`, async ({page, baseURL}, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await install(page, baseURL!)
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      await expect(chart).toContainText('Saved grade: A→B')
      await expect(chart).toContainText('Recalculated grade: B→A')
      await expect(chart.getByText(CAPTION, {exact: true})).toHaveAttribute('title', HELP)
      await expect(chart).not.toContainText('snapshot')
      await expect(chart).not.toContainText('replay')
      await expect(chart).not.toContainText('below A')
      await expect.poll(() => page.evaluate(() => (window as unknown as CanvasState).__gradeDraws.filter(row => row.timeframe === 'D').map(row => row.text))).toEqual(expect.arrayContaining(['Saved grade: A→B', 'Recalculated grade: B→A']))
      await chart.getByRole('button', {name: 'W', exact: true}).click()
      await expect(chart).toContainText('3 weeks loaded')
      await expect.poll(() => page.evaluate(() => (window as unknown as CanvasState).__gradeDraws.filter(row => row.timeframe === 'W').map(row => row.text))).toEqual(expect.arrayContaining(['Saved grade: A→B', 'Recalculated grade: B→A']))
      await chart.getByRole('checkbox', {name: 'Grade changes'}).uncheck()
      await expect(chart.getByText(CAPTION, {exact: true})).toHaveCount(0)
      await expect(chart).not.toContainText('Saved grade:')
      await chart.getByRole('checkbox', {name: 'Grade changes'}).check()
      await expect(chart.getByText(CAPTION, {exact: true})).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await chart.screenshot({path: testInfo.outputPath('human-grade-labels.png')})
    } finally {await finish(testInfo, fixture)}
  })

  // Saved-record wording must keep pagination, original actions and incomplete-history warnings intact.
  test(`chart explains saved recommendation records at ${viewport.width}px`, async ({page, baseURL}, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await install(page, baseURL!)
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      await expect(chart.getByText('Saved recommendations (1 saved record)', {exact: true})).toBeVisible()
      await chart.getByText('Saved recommendations (1 saved record)', {exact: true}).click()
      await expect(chart).toContainText('Personal recommendations at generation time, not fills.')
      await expect(chart).toContainText('Partial history. Load earlier saved records to extend coverage.')
      await expect(chart).toContainText('Loaded saved records may omit receipts from other sessions or retain receipts since deleted or expired. Reload to read current stored history. Older unsaved decisions cannot be reconstructed.')
      const table = chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'})
      await expect(table.locator('tbody tr')).toHaveCount(1)
      await expect(table.locator('tbody tr').first()).toContainText('Buy')
      await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
      await expect(chart.getByText('Saved recommendations (2 saved records)', {exact: true})).toBeVisible()
      await expect(table.locator('tbody tr')).toHaveCount(2)
      await expect(table.locator('tbody tr').first()).toContainText('Sell')
      await expect(chart).toContainText('No earlier saved records were reported by the last history page.')
      await expect(chart).not.toContainText('snapshots')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await chart.screenshot({path: testInfo.outputPath('saved-records.png')})
    } finally {await finish(testInfo, fixture)}
  })
}
