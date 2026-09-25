import {expect, test, type Page} from '@playwright/test'

const observations = [
  {id: 'late', recorded_at: '2026-09-15T14:18:21Z', bar: '2026-09-14T19:45:00Z', entry_state: 'dip', grade: 'A'},
  {id: 'change', recorded_at: '2026-09-15T15:18:21Z', bar: '2026-09-15T15:00:00Z', entry_state: 'wait', grade: 'B'},
  {id: 'unknown', recorded_at: '2026-09-17T14:18:21Z', bar: '2026-09-17T14:00:00Z', entry_state: null, grade: 'A+'},
  {id: 'undated', recorded_at: null, bar: null, entry_state: 'breakout', grade: 'C'},
].map(row => ({...row, allocation: .1, allocation_change: null, model_weight: .1, event_paused: false, price: 100, version: 'original/1', policy_sha256: 'immutable-policy', stock_total_return: null}))

// Keep genuine personal actions distinct from blocked strategy intents and research setups.
const saved = (id: string, at: string, action: string, strategy = action) => ({
  id, generated_at: at, acknowledged_at: at, payload: {rows: {AAPL: {action, strategy_action: strategy, grade: 'A'}}},
})

type CandleGap = 'all' | 'open' | 'high' | 'low' | 'close' | 'absent'
type MarkerDraw = {text: string; center: number; timeframe: string | null}
type CanvasWindow = Window & {__chartMarkerDraws: MarkerDraw[]}

// Observe the real marker paint calls without replacing or simulating the chart.
async function observeMarkerCanvas(page: Page) {
  await page.addInitScript(() => {
    const state = window as unknown as CanvasWindow
    state.__chartMarkerDraws = []
    const fillText = CanvasRenderingContext2D.prototype.fillText
    // Retain actual text centers so a correct caption cannot hide a wrong candle.
    CanvasRenderingContext2D.prototype.fillText = function (this: CanvasRenderingContext2D, ...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      const [text, x, y] = args
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]')
        && (text === 'Buy' || text === 'Sell' || text.startsWith('Saved grade:'))) {
        const point = new DOMPoint(x + this.measureText(text).width / 2, y).matrixTransform(this.getTransform())
        const timeframe = this.canvas.closest('section')?.querySelector('[aria-label="Chart timeframe"] [aria-pressed="true"]')?.textContent ?? null
        state.__chartMarkerDraws.push({text, center: point.x * this.canvas.getBoundingClientRect().width / this.canvas.width, timeframe})
      }
      return fillText.apply(this, args)
    }
  })
}

// Read actual marker draws rather than the independently rendered textual history.
const markerDraws = (page: Page) => page.evaluate(() => (window as unknown as CanvasWindow).__chartMarkerDraws)

// Discard earlier frames before checking a newly selected timeframe.
const clearMarkerDraws = (page: Page) => page.evaluate(() => { (window as unknown as CanvasWindow).__chartMarkerDraws = [] })

// Render saved history and changing quotes with optional missing daily or weekly candle evidence.
async function setup(page: Page, personal = true, gap?: CandleGap) {
  const errors: string[] = []
  const writes: string[] = []
  let last = 110
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => errors.push(request.url()))
  page.on('response', response => { if (response.status() >= 400) errors.push(`HTTP ${response.status()}: ${response.url()}`) })
  await page.clock.install({time: new Date('2026-09-24T14:00:00Z')})
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (['PUT', 'PATCH', 'DELETE'].includes(request.method()) || request.method() === 'POST' && !path.endsWith('/mine')) writes.push(path)
    let json: unknown = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: personal}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session: '2026-09-24', written: '2026-09-24T00:00:00Z', regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: last === 110 ? 'A' : 'C', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: ['2026-09-24']}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/live')) json = {as_of: '2026-09-24T14:00:00Z', quotes: {AAPL: {last, bar: '2026-09-24T13:45:00Z'}}, technical: {}, technical_detail: {}}
    else if (path.endsWith('/mine')) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Waiting'}}}}
    else if (path.endsWith('/personal-history')) json = new URL(request.url()).searchParams.has('before')
      ? {items: [saved('older', '2026-09-14T14:30:00Z', 'Sell')], next_cursor: null}
      : {items: [saved('hold', '2026-09-24T13:55:00Z', 'Hold'), saved('sell-repeat', '2026-09-17T15:00:00Z', 'Sell'), saved('sell', '2026-09-17T14:30:00Z', 'Sell'), saved('blocked', '2026-09-16T14:30:00Z', 'Hold', 'Buy'), saved('buy-repeat', '2026-09-15T15:00:00Z', 'Buy'), saved('buy', '2026-09-15T14:30:00Z', 'Buy')], next_cursor: 'earlier'}
    else if (path.endsWith('/history/AAPL')) json = {ticker: 'AAPL', rows: [{date: '2026-09-14', grade: 'A', said: true}, {date: '2026-09-15', grade: 'B', said: true}].map(row => ({...row, votes: 3, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, earnings: false})), backtest: null, recommendations: {observations, invalid_archives: 0, older_records_not_shown: false}}
    else if (path.endsWith('/chart/AAPL')) {
      const weekly = new URL(request.url()).searchParams.get('timeframe') === 'weekly'
      const dates = weekly ? ['2026-09-11', '2026-09-18', '2026-09-24'] : ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-24']
      const missingDate = weekly ? '2026-09-18' : '2026-09-15'
      const bars = dates.filter(date => gap !== 'absent' || date !== missingDate).map(date => ({
        date,
        open: date === missingDate && (gap === 'all' || gap === 'open') ? null : 100,
        high: date === missingDate && (gap === 'all' || gap === 'high') ? null : Math.max(120, last),
        low: date === missingDate && (gap === 'all' || gap === 'low') ? null : 90,
        close: date === missingDate && (gap === 'all' || gap === 'close') ? null : last,
        volume: 100,
      }))
      json = {ticker: 'AAPL', timeframe: weekly ? 'weekly' : 'daily', adjusted: true, basis: 'adjusted prices', sessions: weekly ? 260 : dates.length, bars, overlays: {}, levels: {}, entries: weekly ? [] : ['2026-09-15'], data_status: gap ? 'incomplete' : 'complete', missing_sessions: gap ? ['2026-09-15'] : [], data_reason: gap ? 'Missing price evidence; affected candles are unavailable.' : null}
    } else if (path.endsWith('/entries') || path.endsWith('/intraday')) json = {rows: [], top_buys: [], changed: []}
    else if (path.endsWith('/paper')) json = {reason: 'unavailable'}
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  await expect(chart.getByLabel('Research publication groups')).toContainText(gap === 'absent' ? '2026-09-17: Not recorded · 1' : '2026-09-15: Dip→Wait · 2')
  return {chart, errors, writes, changeQuote: () => { last = 150 }}
}

// A valid-candle control proves both daily and same-week marker painting remain available.
test('real canvas draws saved actions and grade changes on their available candles', async ({page}) => {
  await observeMarkerCanvas(page)
  const {chart, errors, writes} = await setup(page)
  await expect.poll(async () => (await markerDraws(page)).map(row => row.text)).toContain('Sell')
  const daily = await markerDraws(page)
  expect(daily.map(row => row.text)).toContain('Buy')
  expect(daily.map(row => row.text)).toContain('Saved grade: A→B')
  await clearMarkerDraws(page)
  await chart.getByRole('button', {name: 'W', exact: true}).click()
  await expect(chart).toContainText('3 weeks loaded')
  await expect.poll(async () => (await markerDraws(page)).map(row => row.text)).toContain('Sell')
  const weekly = await markerDraws(page)
  const buy = weekly.findLast(row => row.text === 'Buy')!
  const sell = weekly.findLast(row => row.text === 'Sell')!
  const grade = weekly.findLast(row => row.text === 'Saved grade: A→B')!
  expect(buy).toBeDefined()
  expect(grade).toBeDefined()
  expect(Math.abs(buy.center - sell.center)).toBeLessThan(1)
  expect(Math.abs(grade.center - sell.center)).toBeLessThan(1)
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

for (const gap of ['all', 'open', 'high', 'low', 'close', 'absent'] as const) {
  // Missing prices may suppress a drawing, never backdate it or erase its original receipt.
  test(`daily ${gap} candle gap never backdates a saved Buy or grade`, async ({page}) => {
    await observeMarkerCanvas(page)
    const {chart, errors, writes} = await setup(page, true, gap)
    await expect.poll(async () => (await markerDraws(page)).map(row => row.text)).toContain('Sell')
    const drawn = (await markerDraws(page)).map(row => row.text)
    expect(drawn).not.toContain('Buy')
    expect(drawn).not.toContain('Saved grade: A→B')
    await expect(chart.getByLabel('Buy and Sell markers')).not.toContainText('Buy ·')
    await expect(chart).toContainText('No grade change marked on these candles.')
    await expect(chart.getByLabel('Chart data quality')).toContainText('Chart data incomplete · 1 missing session')
    await chart.getByText('Saved recommendations (6 saved records)', {exact: true}).click()
    const table = chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'})
    await expect(table.locator('tbody tr')).toHaveCount(2)
    await expect(table.locator('tbody tr').first()).toContainText('Sep 15, 2026')
    await expect(table.locator('tbody tr').first().locator('td').nth(1)).toHaveText('Buy')
    await expect(chart).not.toContainText('could not be drawn')
    expect(errors).toEqual([])
    expect(writes).toEqual([])
  })
}

for (const gap of ['all', 'absent'] as const) {
  // An unavailable publication week cannot move either action onto the previous week's candle.
  test(`weekly ${gap} candle gap retains dated receipts without substitute markers`, async ({page}) => {
    await observeMarkerCanvas(page)
    const {chart, errors, writes} = await setup(page, true, gap)
    await expect.poll(async () => (await markerDraws(page)).map(row => row.text)).toContain('Sell')
    await clearMarkerDraws(page)
    await chart.getByRole('button', {name: 'W', exact: true}).click()
    await expect(chart).toContainText(`${gap === 'absent' ? 2 : 3} weeks loaded`)
    await page.clock.runFor(200)
    // Ignore a final daily repaint before the click, but retain every draw after W is selected.
    expect((await markerDraws(page)).filter(row => row.timeframe === 'W')).toEqual([])
    await expect(chart.getByLabel('Buy and Sell markers')).toContainText('No saved Buy/Sell on these candles')
    await expect(chart.getByLabel('Chart data quality')).toContainText('1 missing session')
    await chart.getByText('Saved recommendations (6 saved records)', {exact: true}).click()
    const table = chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'})
    await expect(table.locator('tbody tr')).toHaveCount(2)
    await expect(table.locator('tbody tr').first()).toContainText('Sep 15, 2026')
    await expect(table.locator('tbody tr').last()).toContainText('Sep 17, 2026')
    await expect(chart).not.toContainText('could not be drawn')
    expect(errors).toEqual([])
    expect(writes).toEqual([])
  })
}

// Publication dating retains intraday changes, missing states and every original row without writes.
test('recorded setups preserve original publication and all source readings', async ({page}) => {
  const {chart, errors, writes} = await setup(page)
  await expect(chart.getByRole('checkbox', {name: 'Buy / Sell'})).toBeChecked()
  await expect(chart.getByRole('checkbox', {name: 'Recorded setups · research'})).toHaveCount(0)
  await expect(chart.getByRole('button', {name: 'Recent', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await expect(chart).toContainText('6 sessions loaded; pan or zoom for history.')
  await chart.getByRole('button', {name: 'Full history', exact: true}).click()
  await expect(chart.getByRole('button', {name: 'Full history', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await chart.getByRole('button', {name: 'Recent', exact: true}).click()
  const markers = chart.getByLabel('Research publication groups')
  await expect(markers).not.toContainText('2026-09-14:')
  await expect(markers).not.toContainText('2026-09-16:')
  await expect(markers).toContainText('2026-09-17: Not recorded · 1')
  await chart.getByText('Original readings (4)', {exact: true}).click()
  const table = chart.getByRole('table', {name: 'Original chart setup readings'})
  await expect(table.locator('tbody tr')).toHaveCount(4)
  await expect(table.locator('tbody tr').first()).toContainText('Sep 15, 2026')
  await expect(table.locator('tbody tr').first()).toContainText('Sep 14, 2026')
  await expect(table.locator('tbody tr').first().locator('td').nth(2)).toHaveText('$100.00')
  await expect(table.getByRole('columnheader', {name: 'Bar price'})).toHaveAttribute('title', 'Original unadjusted reference price; chart prices are adjusted.')
  await expect(table.locator('tbody tr').last()).toContainText('Not recorded')
  await expect(table.locator('tbody tr').first()).toContainText('original/1 · immutabl')
  await expect(table.locator('tbody tr').first().getByTitle('immutable-policy')).toHaveText('immutabl')
  await expect(chart.getByRole('checkbox', {name: 'Grade changes'})).toBeChecked()
  await expect(chart).toContainText('Saved grade: A→B')
  await expect(chart).toContainText('not a Buy instruction')
  await expect(chart).not.toContainText('The chart could not be drawn')
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

// Weekly grouping cannot backdate publications, and current quote changes cannot rewrite archived setups.
test('weekly recorded setups aggregate without changing original evidence', async ({page}) => {
  const {chart, errors, writes, changeQuote} = await setup(page)
  const original = await chart.getByLabel('Research publication groups').textContent()
  changeQuote()
  await page.clock.fastForward(61_000)
  await expect(chart).toContainText('$150.00')
  await expect(chart.getByLabel('Research publication groups')).toHaveText(original!)
  await chart.getByRole('button', {name: 'W', exact: true}).click()
  await expect(chart.getByLabel('Research publication groups')).toContainText('2026-09-18: Dip→Wait→Not recorded · 3')
  await expect(chart.getByLabel('Research publication groups')).not.toContainText('2026-09-11:')
  // The daily source-window count is not the number of aggregated weekly candles.
  await expect(chart).toContainText('3 weeks loaded; pan or zoom for history.')
  await expect(chart).not.toContainText('260 weeks')
  await chart.getByText('Original readings (4)', {exact: true}).click()
  await expect(chart.getByRole('table', {name: 'Original chart setup readings'}).locator('tbody tr')).toHaveCount(4)
  await expect(chart).not.toContainText('The chart could not be drawn')
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

// A newly loaded current grade cannot overwrite the original grades in archived observations.
test('current grade changes leave archived grades unchanged', async ({page}) => {
  const {changeQuote, errors, writes} = await setup(page)
  changeQuote()
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('AAPL displayed grade', {exact: true})).toContainText('C')
  await board.getByRole('button', {name: /^AAPL/}).click()
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  await chart.getByText('Original readings (4)', {exact: true}).click()
  const table = chart.getByRole('table', {name: 'Original chart setup readings'})
  await expect(table.locator('tbody tr').first().locator('td').nth(4)).toHaveText('A')
  await expect(table.locator('tbody tr').first().locator('td').nth(2)).toHaveText('$100.00')
  await expect(chart.getByLabel('Research publication groups')).toContainText('2026-09-15: Dip→Wait · 2')
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

// Retain paged saved actions without claiming that the last page proves complete current coverage.
test('chart recommendations use saved actions, dedupe repeats and load earlier evidence', async ({page}) => {
  const {chart, errors, writes} = await setup(page)
  const markers = chart.getByLabel('Buy and Sell markers')
  await expect(markers).toContainText('Buy · Sep 15, 2026')
  await expect(markers).toContainText('Sell · Sep 17, 2026')
  await expect(markers).not.toContainText('Sep 16')
  await expect(markers).not.toContainText('Wait')
  await expect(markers).not.toContainText('breakout')
  await chart.getByText('Saved recommendations (6 saved records)', {exact: true}).click()
  const table = chart.getByRole('table', {name: 'Saved Buy and Sell recommendations'})
  await expect(table.locator('tbody tr')).toHaveCount(2)
  await expect(chart).toContainText('Partial history')
  await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
  await expect(table.locator('tbody tr')).toHaveCount(3)
  await expect(markers).toContainText('Sell · Sep 14, 2026')
  await expect(chart).toContainText('No earlier saved records were reported by the last history page.')
  await expect(chart).toContainText('Loaded saved records may omit receipts from other sessions or retain receipts since deleted or expired.')
  await expect(chart).not.toContainText('All available snapshots loaded.')
  await chart.getByRole('button', {name: 'W', exact: true}).click()
  await expect(markers).toContainText('Buy · Sep 15, 2026')
  await expect(markers).toContainText('Sell · Sep 17, 2026')
  await expect(chart).not.toContainText('The chart could not be drawn')
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

// A missing receipt service cannot turn research setups into advice or claim complete history.
test('missing recommendation history leaves grade evidence available', async ({page}) => {
  const {chart, errors, writes} = await setup(page)
  await page.route('**/desk/personal-history?*', route => route.fulfill({json: {}}))
  await chart.getByText('Saved recommendations (6 saved records)', {exact: true}).click()
  await chart.getByRole('button', {name: 'Load earlier recommendations'}).click()
  await expect(chart.getByRole('status')).toHaveText('Recommendation history unavailable.')
  await expect(chart).not.toContainText('All available snapshots loaded.')
  await expect(chart).toContainText('Saved grade: A→B')
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

// Read-only accounts retain public grade evidence without requesting the owner's private receipts.
test('read-only chart does not request personal recommendation history', async ({page}) => {
  const requests: string[] = []
  page.on('request', request => { if (request.url().includes('/personal-history')) requests.push(request.url()) })
  const {chart, errors, writes} = await setup(page, false)
  await expect(chart.getByRole('checkbox', {name: 'Buy / Sell'})).toHaveCount(0)
  await expect(chart.getByRole('checkbox', {name: 'Grade changes'})).toBeChecked()
  expect(requests).toEqual([])
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})
