import {expect, test, type Page} from '@playwright/test'

const clock = '2026-09-24T22:00:00Z'
const regularBar = '2026-09-24T19:45:00Z'

// Render the actual desk with independent session quotes and immutable regular-session inputs.
async function setup(page: Page, session = 'post-market', transition = false) {
  const errors: string[] = []
  const writes: string[] = []
  let time = transition ? '2026-09-25T13:29:50Z' : clock
  let envelope: unknown = {session, as_of: time, signal_scope: 'regular-session', quotes: {AAPL: {
    price: 102, bid: 101.9, ask: 102.1, at: transition ? '2026-09-25T13:29:45Z' : '2026-09-24T21:59:59Z', feed: session === 'overnight' ? 'overnight' : 'iex', indicative: session === 'overnight', status: 'fresh', reason: 'Current quote', valid_until: transition ? '2026-09-25T13:30:45Z' : '2026-09-24T22:00:20Z',
  }}}
  let open = false
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => errors.push(request.url()))
  await page.clock.install({time: new Date(time)})
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (['PUT', 'PATCH', 'DELETE'].includes(request.method()) || request.method() === 'POST' && (!path.endsWith('/mine') || request.postDataJSON()?.record_history === true)) writes.push(path)
    let json: unknown = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session: '2026-09-24', written: '2026-09-24T20:30:00Z', regime: {exposure: 1, flags: []}, grades: {AAPL: {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}}, MSFT: {grade: 'B', score: .5, votes: 2, stances: {}, ranks: {}}}, book: [], actions: [], briefs: {}}, sessions: ['2026-09-24']}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/live')) json = {as_of: time, market_status: {open, phase: open ? 'open' : session, session: time.slice(0, 10), as_of: time}, quotes: {AAPL: {last: 100, open: 99, high: 101, low: 98, bar: regularBar}}, technical: {}, technical_detail: {}}
    else if (path.endsWith('/session-prices')) json = envelope
    else if (path.endsWith('/mine')) json = {rows: [], grades_live: {}, decisions: {rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', move_weight: 0, reason: 'Regular-session rule unchanged'}}}}
    else if (path.endsWith('/history/AAPL')) json = {ticker: 'AAPL', rows: [], backtest: null}
    else if (path.endsWith('/chart/AAPL')) json = {ticker: 'AAPL', timeframe: 'daily', adjusted: true, basis: 'adjusted prices', sessions: 2, quote_bar: regularBar, bars: ['2026-09-23', '2026-09-24'].map(date => ({date, open: 99, high: 101, low: 98, close: 100, volume: 100})), overlays: {ema9: [99, 99]}, levels: {}, entries: [], data_status: 'complete'}
    else if (path.endsWith('/entries') || path.endsWith('/intraday')) json = {rows: [], top_buys: [], changed: []}
    else if (path.endsWith('/paper')) json = {reason: 'unavailable'}
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('AAPL session price')).toContainText('$102.00')
  return {board, errors, writes, replace: (value: unknown) => { envelope = value }, regular: () => { open = true; if (transition) time = '2026-09-25T13:30:10Z' }}
}

// Current session midpoints never replace regular chart candles, grades or trade sizes.
test('extended midpoint is separate from regular signal price on board and chart', async ({page}) => {
  const {board, errors, writes} = await setup(page)
  await expect(board.getByLabel('AAPL session price')).toContainText('post-market · IEX')
  await expect(board.getByLabel('AAPL session price')).toHaveAttribute('title', /Regular-session bar \$100\.00.*Signal: regular session/)
  await expect(board.getByLabel('AAPL displayed grade')).toContainText('A')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  await expect(board.getByLabel('MSFT session price')).toContainText('Display midpoint unavailable')
  await board.getByRole('button', {name: 'AAPL', exact: true}).click()
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  await expect(chart.getByLabel('AAPL session price')).toContainText('$102.00')
  await expect(chart.getByLabel('AAPL session price')).toContainText('Signal: regular session')
  await expect(chart.locator('dl')).toContainText('$100.00')
  await expect(chart.locator('dl')).not.toContainText('$102.00')
  await page.clock.fastForward(21_000)
  await expect(chart.getByLabel('AAPL session price')).toContainText('stale')
  await expect(chart.getByLabel('AAPL session price')).not.toContainText('$102.00')
  await expect(board.getByLabel('AAPL session price')).toContainText('stale')
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

// Optional feed failure clears the old midpoint while regular data remains available.
test('failed optional feed does not preserve its previous session price', async ({page}) => {
  const {board, errors, writes, replace} = await setup(page, 'overnight')
  await expect(board.getByLabel('AAPL session price')).toContainText('Indicative')
  replace({})
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(board.getByLabel('AAPL session price')).toContainText('Display midpoint unavailable')
  await expect(board.getByLabel('AAPL session price')).not.toContainText('$102.00')
  await expect(board.getByLabel('AAPL displayed grade')).toContainText('A')
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})

// A still-fresh legacy observation crossing the open keeps its original timestamp and phase, never a fabricated new quote.
test('regular transition qualifies rather than relabels a fresh legacy premarket observation', async ({page}) => {
  const {board, errors, writes, regular} = await setup(page, 'pre-market', true)
  regular()
  await page.clock.setFixedTime(new Date('2026-09-25T13:30:10Z'))
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  const reading = board.getByLabel('AAPL session price')
  await expect(reading).toContainText('$102.00')
  await expect(reading).toContainText('pre-market · IEX · 9:29:45 AM ET')
  await expect(reading).toContainText('previous-session observation')
  await expect(reading).not.toContainText('regular · IEX')
  await expect(reading).not.toContainText('9:30:10 AM')
  await expect(reading).toHaveAttribute('title', /Regular-session bar \$100\.00.*2026-09-25T13:29:45Z/)
  expect(errors).toEqual([])
  expect(writes).toEqual([])
})
