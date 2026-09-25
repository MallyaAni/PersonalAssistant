import {expect, test, type Page} from '@playwright/test'

const observations = [
  {id: 'late', recorded_at: '2026-09-15T14:18:21Z', bar: '2026-09-14T19:45:00Z', entry_state: 'dip', grade: 'A'},
  {id: 'change', recorded_at: '2026-09-15T15:18:21Z', bar: '2026-09-15T15:00:00Z', entry_state: 'wait', grade: 'B'},
  {id: 'unknown', recorded_at: '2026-09-17T14:18:21Z', bar: '2026-09-17T14:00:00Z', entry_state: null, grade: 'A+'},
  {id: 'undated', recorded_at: null, bar: null, entry_state: 'breakout', grade: 'C'},
].map(row => ({...row, allocation: .1, allocation_change: null, model_weight: .1, event_paused: false, price: 100, version: 'original/1', policy_sha256: 'immutable-policy', stock_total_return: null}))

// Render the actual stock modal against saved history and a separately changing current quote.
async function setup(page: Page) {
  const errors: string[] = []
  const writes: string[] = []
  let last = 110
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => errors.push(request.url()))
  await page.clock.install({time: new Date('2026-09-24T14:00:00Z')})
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (['PUT', 'PATCH', 'DELETE'].includes(request.method()) || request.method() === 'POST' && (!path.endsWith('/mine') || request.postDataJSON()?.record_history === true)) writes.push(path)
    let json: unknown = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session: '2026-09-24', written: '2026-09-24T00:00:00Z', regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: last === 110 ? 'A' : 'C', score: 1, votes: 3, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: ['2026-09-24']}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/live')) json = {as_of: '2026-09-24T14:00:00Z', quotes: {AAPL: {last, bar: '2026-09-24T13:45:00Z'}}, technical: {}, technical_detail: {}}
    else if (path.endsWith('/mine')) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Waiting'}}}}
    else if (path.endsWith('/history/AAPL')) json = {ticker: 'AAPL', rows: [{date: '2026-09-14', grade: 'A', said: true}, {date: '2026-09-15', grade: 'B', said: true}].map(row => ({...row, votes: 3, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, earnings: false})), backtest: null, recommendations: {observations, invalid_archives: 0, older_records_not_shown: false}}
    else if (path.endsWith('/chart/AAPL')) {
      const weekly = new URL(request.url()).searchParams.get('timeframe') === 'weekly'
      const dates = weekly ? ['2026-09-11', '2026-09-18', '2026-09-24'] : ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-24']
      json = {ticker: 'AAPL', timeframe: weekly ? 'weekly' : 'daily', adjusted: true, basis: 'adjusted prices', sessions: weekly ? 260 : dates.length, bars: dates.map(date => ({date, open: 100, high: Math.max(120, last), low: 90, close: last, volume: 100})), overlays: {}, levels: {}, entries: weekly ? [] : ['2026-09-15'], data_status: 'complete'}
    } else if (path.endsWith('/entries') || path.endsWith('/intraday')) json = {rows: [], top_buys: [], changed: []}
    else if (path.endsWith('/paper')) json = {reason: 'unavailable'}
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  await expect(chart.getByLabel('Recorded setup markers')).toContainText('2026-09-15: Dip→Wait · 2')
  return {chart, errors, writes, changeQuote: () => { last = 150 }}
}

// Publication dating retains intraday changes, missing states and every original row without writes.
test('recorded setups preserve original publication and all source readings', async ({page}) => {
  const {chart, errors, writes} = await setup(page)
  await expect(chart.getByRole('checkbox', {name: 'Recorded setups · research'})).toBeChecked()
  await expect(chart.getByRole('button', {name: 'Recent', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await expect(chart).toContainText('6 sessions loaded; pan or zoom for history.')
  await chart.getByRole('button', {name: 'Full history', exact: true}).click()
  await expect(chart.getByRole('button', {name: 'Full history', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await chart.getByRole('button', {name: 'Recent', exact: true}).click()
  const markers = chart.getByLabel('Recorded setup markers')
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
  await chart.getByRole('checkbox', {name: 'Show signal history'}).check()
  await expect(chart).toContainText('snapshot · below A · A→B')
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
  const original = await chart.getByLabel('Recorded setup markers').textContent()
  changeQuote()
  await page.clock.fastForward(61_000)
  await expect(chart).toContainText('$150.00')
  await expect(chart.getByLabel('Recorded setup markers')).toHaveText(original!)
  await chart.getByRole('button', {name: 'W', exact: true}).click()
  await expect(chart.getByLabel('Recorded setup markers')).toContainText('2026-09-18: Dip→Wait→Not recorded · 3')
  await expect(chart.getByLabel('Recorded setup markers')).not.toContainText('2026-09-11:')
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
  await expect(chart.getByLabel('Recorded setup markers')).toContainText('2026-09-15: Dip→Wait · 2')
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})
