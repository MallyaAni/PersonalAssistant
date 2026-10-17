import {expect, test} from '@playwright/test'

// Drive the compiled Stocks view through changing candle evidence without account writes.
test('Stocks and chart details refresh assessments without personal guidance', async ({page}) => {
  const errors: string[] = []
  const writes: string[] = []
  let fresh = true
  let grade = 'A+'
  const now = new Date()
  const session = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(now)
  const previous = '2026-10-13'
  const at = now.toISOString()
  const bar = new Date(+now - 16 * 60000).toISOString()
  const until = new Date(+now + 15 * 60000).toISOString()
  const old = {grade: 'C', score: -.8, stances: {fundamental: 1, technical: -1, sentiment: -1}, ranks: {fundamental: .9, technical: .1, sentiment: .1}}
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (message.type() === 'error') errors.push(message.text())})
  page.on('requestfailed', request => errors.push(request.url()))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (request.method() !== 'GET') writes.push(path)
    let json: any = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'assessment-owner', is_admin: false, desk_access: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session: previous, written: `${previous}T23:47:45Z`, grades: {CRWV: old}, targets: {policy: 'grade-led-learned-sizing/1', weights: {CRWV: 0}}, book: [], actions: [{ticker: 'CRWV', grade_signal: 'avoid', signal_reason: 'Grade below A; no entry', last_close: 77.81}], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: [previous]}
    else if (path.endsWith('/live')) json = {as_of: at, decision_session: previous, quotes: {CRWV: {last: 66, open: 72, high: 72.4, low: 65.55, bar, as_of: at}}, technical: {CRWV: {now: .28, close: .1}}, technical_detail: {}, grades_live: {CRWV: {grade_live: grade, ranks_live: {fundamental: .9, technical: .28, sentiment: .1}, stances_live: {fundamental: 1, technical: -1, sentiment: -1}}}, grade_valid_until: {CRWV: fresh ? until : '2020-01-01T00:00:00Z'}}
    else if (path.endsWith('/session-prices')) json = {as_of: at, quotes: {}, market_status: {open: true, session}}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/paper')) json = {equity: 100000, cash: 100000, positions: [], plan: {orders: []}}
    else if (path.includes('/history/')) json = {ticker: 'CRWV', rows: [{date: previous, grade: 'C', said: true}], fills: [], backtest: null}
    else if (path.includes('/chart/')) json = {ticker: 'CRWV', timeframe: 'daily', adjusted: true, bars: [{date: previous, open: 78, high: 79, low: 76, close: 77.81, volume: 100}, {date: session, open: 72, high: 72.4, low: 65.55, close: 66, volume: 100}], overlays: {}, levels: {}, entries: []}
    else if (path.includes('/live/read/')) json = {symbol: 'CRWV', now: .28, read: 'The current price is below falling averages. Support is 0.9% below; resistance is 29.7% above.', lines: {short: ['23.8% below the 21-day average'], medium: ['weekly trend down'], long: ['33.1% below the 200-day average']}, data_at: bar, read_at: at, stale: false}
    else if (path.includes('/earnings/')) json = {symbol: 'CRWV', read: null}
    else if (path.includes('/strategy-simulation/')) json = {schema: 'latest-strategy-simulation/1', ticker: 'CRWV', counterfactual: true, real_orders: false, decisions: [], trades: [], targets: [], provenance: {cost_bps: 10}}
    else errors.push(`Unexpected endpoint ${path}`)
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  await page.getByRole('searchbox', {name: 'Search the stock list'}).fill('CRWV')
  const cell = page.getByRole('cell', {name: 'CRWV displayed grade'})
  await expect(cell).toContainText('—')
  await expect(page.getByLabel('Strategy plan status', {exact: true})).toHaveCount(1)
  await expect(page.getByLabel('Strategy plan status', {exact: true})).toContainText('Latest saved decision: 2026-10-13')
  await expect(page.getByLabel('CRWV size', {exact: true})).toHaveText('—')
  await page.getByRole('button', {name: 'CRWV', exact: true}).click()
  const assessment = page.getByRole('region', {name: 'Current assessment', exact: true})
  await expect(assessment).not.toBeVisible()
  await page.getByRole('dialog').getByLabel('All the evidence', {exact: true}).locator(':scope > summary').click()
  await expect(assessment).toBeVisible()
  await expect(assessment).toContainText('A+ · Entry eligible')
  await expect(assessment).toContainText('At $66.00')
  await expect(assessment).toContainText('completed 15-minute candle')
  await expect(assessment.getByText('The current price is below falling averages.', {exact: false})).not.toBeVisible()
  await assessment.getByText('Technical evidence', {exact: true}).click()
  await expect(assessment).toContainText('below falling averages')
  await expect(assessment.getByText('The current price is below falling averages.', {exact: false})).toBeVisible()
  await expect(page.getByRole('region', {name: 'Saved assessment', exact: true})).toContainText('Grade C')
  await expect(page.getByRole('region', {name: 'CRWV paper order'})).toContainText('Saved target 0.0%')
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  fresh = false
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(cell).toHaveText('—')
  await page.getByRole('button', {name: 'CRWV', exact: true}).click()
  await expect(assessment).not.toBeVisible()
  await page.getByRole('dialog').getByLabel('All the evidence', {exact: true}).locator(':scope > summary').click()
  await expect(assessment).toBeVisible()
  await expect(assessment).toContainText('Fresh assessment unavailable')
  await expect(assessment).not.toContainText('A+ · Entry eligible')
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  fresh = true
  grade = 'C'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(cell).toHaveText('—')
  await page.getByRole('button', {name: 'CRWV', exact: true}).click()
  await expect(assessment).not.toBeVisible()
  await page.getByRole('dialog').getByLabel('All the evidence', {exact: true}).locator(':scope > summary').click()
  await expect(assessment).toBeVisible()
  await expect(assessment).toContainText('C · Avoid new entry')
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
