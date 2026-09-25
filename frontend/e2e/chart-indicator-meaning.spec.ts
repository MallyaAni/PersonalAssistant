import {expect, test, type Page, type TestInfo} from '@playwright/test'

const USER = 'chart-indicator-meaning-fixture'
type Scenario = {name: string; key?: string; value: number; distance: string; phone?: boolean}
const scenarios: Scenario[] = [
  {name: 'indicator denominator is not the candle price', value: 80, distance: '+25.0%'},
  {name: 'negative distance is not an investment loss', value: 125, distance: '-20.0%'},
  {name: 'zero denominator is unavailable', key: 'band_lower', value: 0, distance: 'unavailable'},
  {name: 'negative band retains its signed denominator', key: 'band_lower', value: -100, distance: '-200.0%', phone: true},
  {name: 'finite inputs with overflowing ratio are unavailable', key: 'band_lower', value: 1e-310, distance: 'unavailable'},
  {name: 'small positive distance rounds without claiming equality', value: 100 / 1.0004, distance: '+0.0%'},
  {name: 'small negative distance retains the negative sign', value: 100 / 0.9996, distance: '-0.0%'},
  {name: 'equal prices use the same rounded-distance convention', value: 100, distance: '+0.0%'},
]

// Isolate the real chart from account/provider traffic and retain its original numerical inputs.
async function install(page: Page, frontendURL: string, scenario: Scenario) {
  const dates = ['2026-09-23', '2026-09-24']
  const source = {
    ticker: 'AAPL', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true,
    basis: 'synthetic adjusted prices', sessions: dates.length, data_status: 'complete',
    quote_bar: '2026-09-24T19:45:00Z', last_bar_complete: false,
    bars: dates.map(date => ({date, open: 99, high: 101, low: 98, close: 100, volume: 1000})),
    overlays: {[scenario.key ?? 'ema9']: dates.map(() => scenario.value)}, levels: {}, entries: [],
  }
  const original = JSON.stringify(source)
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  // Keep console failures visible even if the numerical text renders.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // Reject partial chart rendering after a page exception.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Required network failures cannot be dismissed as a passing fallback.
  page.on('requestfailed', request => diagnostics.failedRequests.push(request.url()))
  // Retain unsuccessful HTTP responses independently of script exceptions.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date('2026-09-25T14:00:00Z')})
  // Stabilize the test theme without changing laptop settings.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Serve only synthetic reads and a non-recording preview; no request reaches a real account.
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), base = `/api/v1/market/${USER}/desk`
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const preview = request.method() === 'POST' && url.pathname === `${base}/mine` && request.postDataJSON()?.record_history === false
    if (request.method() !== 'GET' && !preview) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids account writes'}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest: {session: '2026-09-24', written: '2026-09-24T21:00:00Z', regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: ['2026-09-24']}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/live`) json = {as_of: '2026-09-25T14:00:00Z', quotes: {AAPL: {last: 999, bar: '2026-09-25T13:45:00Z'}}, technical: {}, technical_detail: {}}
    else if (url.pathname === `${base}/session-prices`) json = {as_of: '2026-09-25T14:00:00Z', session: 'regular', signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/mine`) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Waiting'}}}}
    else if (url.pathname === `${base}/history/AAPL`) json = {ticker: 'AAPL', rows: [], recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname === `${base}/chart/AAPL`) json = source
    else if (url.pathname === `${base}/entries` || url.pathname === `${base}/intraday`) json = {rows: [], top_buys: [], changed: []}
    else if (url.pathname === `${base}/paper`) json = {reason: 'unavailable'}
    else if (url.pathname === `${base}/earnings/AAPL` || url.pathname === `${base}/live/read/AAPL`) json = {symbol: 'AAPL', read: null, lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified request'}})
    }
    return route.fulfill({json})
  })
  return {source, original, diagnostics}
}

// Persist strict browser diagnostics and verify rendering never changes its input values or dates.
async function finish(testInfo: TestInfo, fixture: Awaited<ReturnType<typeof install>>) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(fixture.diagnostics, null, 2), contentType: 'application/json'})
  await testInfo.attach('original-chart-source', {body: fixture.original, contentType: 'application/json'})
  for (const [category, errors] of Object.entries(fixture.diagnostics)) expect.soft(errors, category).toEqual([])
  expect(JSON.stringify(fixture.source)).toBe(fixture.original)
}

for (const scenario of scenarios) {
  // Read exact indicator-relative distances from the endpoint candle, not the independent board quote.
  test(`chart distance meaning: ${scenario.name}`, async ({page, baseURL}, testInfo) => {
    if (scenario.phone) await page.setViewportSize({width: 390, height: 844})
    const fixture = await install(page, baseURL!, scenario)
    try {
      await page.goto('/#desk')
      await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
      const chart = page.getByRole('region', {name: 'AAPL price chart'})
      await expect(chart.locator('dl')).toBeVisible()
      await expect(chart.locator('dl')).not.toContainText(/Infinity|NaN/)
      const label = scenario.key === 'band_lower' ? 'Lower Bollinger band' : '9-session EMA'
      const row = chart.locator('dl > div').filter({has: page.getByText(label, {exact: true})})
      await expect(row).toContainText(scenario.distance === 'unavailable' ? /distance unavailable/i : `Price distance ${scenario.distance}`)
      await expect(row).toContainText(`$${scenario.value.toFixed(2)}`)
      await expect(chart).toContainText(/not a return/i)
      await expect(chart).toContainText(/rounded to one decimal/i)
      await expect(chart.locator('dl')).not.toContainText('$999.00')
      await expect(chart).toContainText('Sep 24, 2026, 3:45 PM EDT')
      await expect(chart).not.toContainText(/prices are equal|price equals|live price/i)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      if (scenario.phone) await chart.screenshot({path: testInfo.outputPath('negative-band-distance-phone.png')})
    } finally {await finish(testInfo, fixture)}
  })
}
