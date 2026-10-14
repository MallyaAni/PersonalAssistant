import {expect, test, type Page} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {gunzipSync} from 'node:zlib'
import {createHash} from 'node:crypto'

type Stock = {ticker: string; trades: {date: string; at: string; action: string; qty: number}[]; [key: string]: any}
const root = process.env.STRATEGY_PROJECTION_ROOT
const capture = process.env.STRATEGY_CHART_CAPTURE
const captured = capture ? JSON.parse(gunzipSync(readFileSync(capture)).toString()) : null
const manifest = root ? JSON.parse(readFileSync(`${root}/manifest.json`, 'utf8')) : null

// Authenticate the actual published stock views before browser fixtures may use them.
const projected = (name: string) => {
  const bytes = readFileSync(`${root}/${manifest.version}/${name}.json`)
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(manifest.files[name])
  return JSON.parse(bytes.toString())
}

const basic = {schema: 'latest-strategy-simulation/1', policy: 'joint-stock-risk-funded/6-retained-holdings-probability-timing-research', start: '2019-03-01', through: '2026-10-09', counterfactual: true, real_orders: false, provenance: {cost_bps: 10}, latest_target: .2, latest_holding: 60, targets: [], decisions: [], splits: [], trades: [
  {id: 'entry', date: '2026-10-06', at: '2026-10-06T13:45:00Z', action: 'BUY', qty: 71, price: 100, weight: .071},
  {id: 'trim', date: '2026-10-07', at: '2026-10-07T14:00:00Z', action: 'TRIM', qty: 11, price: 101, weight: .01111},
  {id: 'exit', date: '2026-10-08', at: '2026-10-08T13:30:00Z', action: 'SELL', qty: 60, price: 102, weight: .0612},
]}
const stocks: Stock[] = captured ? Object.keys(captured.stocks).sort().map(name => projected(name)) : ['ORCL', 'AAOI'].map(ticker => ({...basic, ticker}))
const summary = root ? projected('summary') : {...basic, starting_equity: 100000, ending_equity: 101000, ending_cash: 80000, ending_holdings: {ORCL: 60, AAOI: 60}, latest_decisions: [], curve: [], stock_overview: Object.fromEntries(stocks.map(stock => [stock.ticker, {target: .2, holding: 60, last_trade: stock.trades.at(-1), trades: 3}]))}

// Supply small ordinary candles when the full authenticated cohort is not requested.
const controlChart = (ticker: string, frame: string) => {
  const dates = ['2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']
  const bars = frame === 'weekly' ? [{date: dates.at(-1), open: 99, high: 103, low: 98, close: 102, volume: 100}] : frame === 'daily' ? dates.map(date => ({date, open: 99, high: 103, low: 98, close: 102, volume: 100})) : dates.flatMap(date => Array.from({length: 27}, (_, index) => ({date, time: `${date}T${String(13 + Math.floor((30 + index * 15) / 60)).padStart(2, '0')}:${String((30 + index * 15) % 60).padStart(2, '0')}:00Z`, open: 99, high: 103, low: 98, close: 102, volume: 100})))
  return {ticker, timeframe: frame, sessions: dates.length, adjusted: frame !== '15m', basis: 'controlled price fixture', bars, overlays: {}, levels: {}, entries: [], data_status: 'complete'}
}

// Freeze the browser's data transport while rendering the real compiled dashboard.
async function install(page: Page, stock: Stock, failure = false, current = {done: false}) {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (message.type() === 'error') errors.push(message.text())})
  page.on('requestfailed', request => {
    // Reload may abort the unrelated chat read; every failed desk request remains a failure.
    if (!(request.url().includes('/conversations/') && request.failure()?.errorText === 'net::ERR_ABORTED')) errors.push(request.url())
  })
  await page.addInitScript(() => {
    localStorage.setItem('anios.theme', 'light')
    ;(window as any).__strategyPaint = []
    ;(window as any).__gradePaint = []
    const original = CanvasRenderingContext2D.prototype.fillText
    // Retain the real marker text and canvas bounds, without replacing chart layout.
    CanvasRenderingContext2D.prototype.fillText = function (...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && /^(BUY|SELL|TRIM) .+ sh$/.test(args[0])) {
        const point = new DOMPoint(args[1], args[2]).matrixTransform(this.getTransform())
        const width = this.measureText(args[0]).width * this.getTransform().a
        ;(window as any).__strategyPaint.push({text: args[0], x: point.x, y: point.y, width, canvasWidth: this.canvas.width, canvasHeight: this.canvas.height})
      }
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && /^(BUY|SELL) · (A\+?|B|C)$/.test(args[0])) {
        ;(window as any).__gradePaint.push(args[0])
      }
      return original.apply(this, args)
    }
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (request.method() !== 'GET' && !(path.endsWith('/mine') && request.postDataJSON()?.record_history === false)) errors.push(`Unexpected write: ${path}`)
    let json: any = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'cohort-reader', is_admin: false, desk_access: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session: '2026-10-09', written: '2026-10-09T20:30:00Z', grades: Object.fromEntries(stocks.map(row => [row.ticker, {grade: 'A', votes: 3, score: .8, stances: {}, ranks: {}}])), book: [], actions: [], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: ['2026-10-09']}
    else if (path.endsWith('/live')) {
      const now = new Date(), at = now.toISOString(), bar = new Date(+now - 16 * 60000).toISOString(), until = new Date(+now + 10 * 60000).toISOString()
      json = {as_of: at, decision_session: '2026-10-09',
        quotes: Object.fromEntries(stocks.map(row => [row.ticker, {last: 100, bar, as_of: at}])),
        grades_live: Object.fromEntries(stocks.map(row => [row.ticker, {grade_live: 'A', score_live: .8}])),
        grade_valid_until: Object.fromEntries(stocks.map(row => [row.ticker, until])),
        opportunities: {status: 'complete', rows: Object.fromEntries(stocks.map(row => [row.ticker, {ticker: row.ticker, status: 'model_assessment', entry: 'ready', exit: 'hold', entry_priority: 'high', exit_priority: 'low', reason: 'The supported pullback held its reference.', confirmation: 'none', confirmation_ref: 'none', invalidation_ref: 'none', levels: {}, price: 100, bar, generated_at: at, valid_until: until}]))}, technical: {}, technical_detail: {}}
    }
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/paper')) json = {equity: 100000, cash: 99000, positions: [{symbol: stocks[0].ticker, qty: 4, market_value: 400, avg_entry_price: 100, current_price: 100, unrealized_pl: 0, unrealized_plpc: 0}], plan: {orders: [
      {symbol: stocks[0].ticker, client_order_id: 'current-buy', action: 'BUY', side: 'buy', state: current.done ? 'filled' : 'waiting', terminal: current.done, status: current.done ? 'Bought 3 today' : 'Waiting for the model timing', qty: 3, quantity_basis: current.done ? 'filled' : 'planned', notional: 300, weight: .003, price: 100, why: 'Recorded current plan', when: 'Next completed bar'},
      {symbol: stocks.at(-1)!.ticker, client_order_id: 'old-sell', action: 'SELL', side: 'sell', state: 'filled', terminal: true, status: 'Sold 5 yesterday', qty: 5, filled_qty: 5, quantity_basis: 'filled', notional: 500, weight: .005, price: 100, why: 'Completed old order', when: 'Yesterday'},
    ]}}
    else if (path.endsWith('/paper/history')) json = {rows: []}
    else if (path.endsWith('/strategy-simulation')) {errors.push('Overview requested historical simulation'); json = summary}
    else if (path.includes('/strategy-simulation/')) {
      if (failure) return route.fulfill({status: 503, json: {detail: 'Unavailable'}})
      json = stock
    } else if (path.includes('/history/')) json = captured?.stocks[stock.ticker].history ?? {ticker: stock.ticker, asof: '2026-10-09', rows: [
      {date: '2026-10-05', grade: 'B', said: true},
      {date: '2026-10-06', grade: 'A+', said: true},
      {date: '2026-10-07', grade: 'A', said: false},
      {date: '2026-10-08', grade: 'B', said: false},
    ], fills: [{date: '2026-10-07', filled_at: '2026-10-07T15:00:00Z', side: 'buy', qty: 3, price: 101}], backtest: null}
    else if (path.includes('/chart/')) {
      const frame = url.searchParams.get('timeframe') ?? 'daily'
      json = captured ? captured.stocks[stock.ticker][frame === '15m' ? `15m-${url.searchParams.get('sessions')}` : frame] : controlChart(stock.ticker, frame)
      if (!json) return route.fulfill({status: 404, json: {detail: 'No stored bars'}})
    } else if (path.includes('/earnings/')) json = {symbol: stock.ticker, read: null}
    else if (path.includes('/live/read/')) json = {symbol: stock.ticker, now: null, read: '', lines: {short: [], medium: [], long: []}}
    else if (path.endsWith('/personal-history')) json = {items: [], next_cursor: null}
    else if (path.endsWith('/mine')) json = {rows: [], decisions: {rows: {}}, grades_live: {}}
    else if (path.endsWith('/session-prices')) {
      const now = new Date(), at = now.toISOString(), until = new Date(+now + 60000).toISOString()
      json = {session: 'regular', signal_scope: 'regular-session', as_of: at, quotes: Object.fromEntries(stocks.map(row => [row.ticker, {price: 100, status: 'fresh', session: 'regular', feed: 'iex', at, valid_until: until}]))}
    }
    else if (path.endsWith('/entries')) json = {rows: []}
    else if (path.endsWith('/intraday')) json = {rows: [], changed: [], top_buys: []}
    else errors.push(`Unspecified endpoint: ${path}`)
    return route.fulfill({json})
  })
  await page.goto('/#desk')
  await page.getByRole('searchbox', {name: 'Search the stock list'}).fill(stock.ticker)
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: stock.ticker, exact: true}).click()
  return errors
}

// Independently bucket original simulated executions by calendar or quarter-hour interval.
const expectedLabels = (stock: Stock, bars: any[], frame: string) => {
  const totals = new Map<string, {action: string; qty: number}>()
  for (const trade of stock.trades) {
    const instant = Date.parse(trade.at)
    const day = new Date(`${trade.date}T00:00:00Z`)
    const monday = +day - ((day.getUTCDay() + 6) % 7) * 86400000
    const bar = bars.find(bar => frame === '15m' ? Date.parse(bar.time) <= instant && instant < Date.parse(bar.time) + 900000 : frame === 'daily' ? bar.date === trade.date : Date.parse(`${bar.date}T00:00:00Z`) >= monday && Date.parse(`${bar.date}T00:00:00Z`) < monday + 7 * 86400000)
    if (!bar || !['open', 'high', 'low', 'close'].every(field => typeof bar[field] === 'number' && Number.isFinite(bar[field]))) continue
    const key = `${bar.time ?? bar.date}:${trade.action}`
    let quantity = trade.qty
    if (frame === 'weekly') for (const event of stock.splits ?? []) {
      if (event.date > trade.date && event.date <= bar.date) quantity *= event.ratio
    }
    totals.set(key, {action: trade.action, qty: (totals.get(key)?.qty ?? 0) + quantity})
  }
  return [...totals.values()].map(row => `${row.action} ${row.qty.toLocaleString('en-US', {maximumFractionDigits: 6})} sh`)
}

for (const stock of stocks) {
  // Every covered stock exercises D/W, every 15m window, ranges, original sizes and phone recovery.
  test(`${captured ? 'actual 94-stock cohort' : 'control'} ${stock.ticker} strategy chart and sizing`, async ({page}) => {
    test.setTimeout(90000)
    const errors = await install(page, stock)
    const chart = page.getByRole('region', {name: `${stock.ticker} price chart`})
    await expect(chart.getByRole('checkbox', {name: 'Model-only research fills'})).not.toBeChecked()
    await chart.getByRole('checkbox', {name: 'Model-only research fills'}).check()
    await chart.getByText('Model-only strategy research', {exact: true}).click()
    await expect(chart.getByRole('checkbox', {name: 'Policy replay'})).toHaveCount(0)
    await expect(chart.getByRole('checkbox', {name: 'Grade signals'})).not.toBeChecked()
    await expect(chart.getByRole('checkbox', {name: 'Saved recommendations'})).toHaveCount(0)
    await expect(chart.getByLabel('Recorded setup history')).toHaveCount(0)
    await expect(chart).toContainText(stock.through)
    for (const [frame, button, count] of [['daily', 'D', 2000], ['weekly', 'W', 2000], ...[5, 10, 20, 60].map(count => ['15m', '15m', count])] as [string, string, number][]) {
      await chart.getByRole('button', {name: button, exact: true}).click()
      if (frame === '15m') await chart.getByRole('group', {name: 'Chart sessions'}).getByRole('button', {name: String(count), exact: true}).click()
      const chartData = captured ? captured.stocks[stock.ticker][frame === '15m' ? `15m-${count}` : frame] : controlChart(stock.ticker, frame)
      expect(chartData, `${stock.ticker} ${frame} actual bars unavailable`).toBeTruthy()
      await expect(chart.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-chart-timeframe', frame)
      await expect(chart.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-bar-count', String(chartData.bars.length))
      await chart.getByRole('button', {name: 'Full history', exact: true}).click()
      await page.evaluate(() => {(window as any).__strategyPaint = []})
      await chart.getByRole('checkbox', {name: 'Model-only research fills'}).uncheck()
      await chart.getByRole('checkbox', {name: 'Model-only research fills'}).check()
      const bars = chartData.bars
      const expected = expectedLabels(stock, bars, frame)
      if (expected.length) await expect.poll(() => page.evaluate(() => (window as any).__strategyPaint.length)).toBeGreaterThan(0)
      const painted = await page.evaluate(() => (window as any).__strategyPaint as {text: string; x: number; y: number; canvasWidth: number; canvasHeight: number}[])
      for (const row of painted) {
        expect(expected, `${stock.ticker} ${frame} invented size ${row.text}`).toContain(row.text)
        expect(row.y).toBeGreaterThanOrEqual(0)
        expect(row.y).toBeLessThanOrEqual(row.canvasHeight)
      }
      for (const label of new Set(expected)) expect(painted.map(row => row.text), `${stock.ticker} ${frame} omitted ${label}`).toContain(label)
      await chart.getByRole('button', {name: 'Recent', exact: true}).click()
    }
    await page.setViewportSize({width: 390, height: 844})
    await chart.getByRole('button', {name: 'W', exact: true}).click()
    if (stock.ticker === 'ORCL' || stock.ticker === 'AAOI' || stock.ticker === 'ANET' || stock.ticker === 'KLAC') {
      await chart.getByRole('button', {name: 'Go to last trade', exact: true}).click()
      await chart.screenshot({path: test.info().outputPath(`${stock.ticker}-weekly-last-action.png`)})
    }
    await expect(chart).not.toContainText('NaN')
    await expect(chart).not.toContainText('The chart could not be drawn')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}

// Missing research never hides the primary grade layer or fabricates model-only fills.
test('unavailable strategy history stays explicit without predecessor trades', async ({page}) => {
  await install(page, stocks[0], true)
  await page.getByText('Model-only strategy research', {exact: true}).click()
  await expect(page.getByRole('alert')).toContainText('Latest-strategy simulation unavailable for this stock')
  await expect(page.getByRole('checkbox', {name: 'Policy replay'})).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).__strategyPaint)).toEqual([])
})

// Refresh removes a settled action from the live list while its historical chart remains separate.
test('current overview refresh removes completed actions without inventing sizes', async ({page}) => {
  const current = {done: false}
  const errors = await install(page, stocks[0], false, current)
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  const table = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const row = table.getByRole('row').filter({has: page.getByRole('button', {name: stocks[0].ticker, exact: true})})
  await expect(row).toContainText('3 sh planned')
  current.done = true
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(row.getByLabel(`${stocks[0].ticker} strategy intent`, {exact: true})).toHaveText('ADD')
  await expect(row.getByLabel(`${stocks[0].ticker} size`)).toHaveText('—')
  await expect(table).not.toContainText('Bought 3 today')
  expect(errors).toEqual([])
})

// The main board filters current plans and never borrows historical simulated holdings or sizes.
test('current overview filters sorting and phone recovery preserve current sizes', async ({page}) => {
  const errors = await install(page, stocks[0])
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  const section = page.getByRole('region', {name: 'Stocks and cash'})
  const table = section.getByRole('table')
  await section.getByRole('searchbox').fill('')
  await expect(table.locator('tbody tr')).toHaveCount(Math.min(stocks.length, 25))
  await table.getByRole('button', {name: 'Stock', exact: true}).click()
  await expect(table.locator('tbody tr').first()).toContainText([...stocks].sort((a, b) => a.ticker.localeCompare(b.ticker))[0].ticker)
  await table.getByRole('button', {name: 'Action', exact: true}).click()
  for (const action of ['SELL', 'TRIM', 'HOLD', 'No order']) await section.getByRole('checkbox', {name: `Show ${action} rows`, exact: true}).uncheck()
  await expect(table.locator('tbody tr')).toHaveCount(stocks.length)
  await expect(table).toContainText('3 sh planned')
  await expect(table).toContainText('4 sh')
  await expect(table).toContainText('The supported pullback held its reference.')
  await page.getByRole('button', {name: 'Hide Sidebar', exact: true}).click()
  await page.setViewportSize({width: 390, height: 844})
  await table.getByRole('button', {name: 'Action', exact: true}).click()
  await section.getByRole('checkbox', {name: 'Show BUY rows', exact: true}).uncheck()
  await expect(table.locator('tbody tr')).toHaveCount(0)
  await section.getByRole('group', {name: 'Show actions'}).getByRole('button', {name: 'Show all', exact: true}).click()
  await expect(table.locator('tbody tr')).toHaveCount(Math.min(stocks.length, 25))
  await page.keyboard.press('Escape')
  await expect(table.getByRole('button', {name: 'Action', exact: true})).toBeFocused()
  await section.getByRole('searchbox').fill('NONEXISTENT')
  await expect(table.locator('tbody tr')).toHaveCount(0)
  await section.getByRole('searchbox').fill('')
  await expect(table.locator('tbody tr')).toHaveCount(Math.min(stocks.length, 25))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

// Current actions stay on the overview and completed orders stay in the separate account view.
test('current stocks and separate paper view survive reload without mixed history', async ({page}) => {
  const errors = await install(page, stocks[0])
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  await page.getByRole('searchbox', {name: 'Search the stock list'}).fill('')
  const overview = page.getByRole('region', {name: 'Stocks and cash'})
  await expect(overview).not.toContainText('Sold 5 yesterday')
  await expect(overview).not.toContainText('Last simulated trade')
  await expect(overview).not.toContainText('Simulated value')
  await expect(overview).not.toContainText('None in replay')
  await expect(overview.getByRole('button', {name: `All names ${stocks.length}`, exact: true})).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', {name: 'How to use this page'}).click()
  await expect(page.getByRole('region', {name: 'Strategy guide'})).toContainText('A/A+ gives entry permission')
  await expect(page.getByRole('region', {name: 'Strategy guide'})).not.toContainText('A+ buys')
  await page.getByRole('button', {name: 'Paper account', exact: true}).click()
  await expect(page.getByRole('region', {name: 'Stocks and cash'})).toContainText('Sold 5 yesterday')
  await expect(page).toHaveURL(/deskView=paper/)
  await page.reload()
  await expect(page.getByRole('button', {name: 'Paper account', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('region', {name: 'Latest-strategy simulation'})).toHaveCount(0)
  await page.getByRole('button', {name: 'Stocks', exact: true}).click()
  await page.reload()
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'}).locator('tbody tr')).toHaveCount(Math.min(stocks.length, 25))
  await expect(page.getByRole('region', {name: 'Stocks and cash'})).not.toContainText('Sold 5 yesterday')
  expect(errors).toEqual([])
})

// Grades remain primary on both calendar views; research sizes and intraday clocks stay separate.
test('grade direction survives a zero research target with dated provenance', async ({page}) => {
  const errors = await install(page, {...stocks[0], latest_target: 0})
  const chart = page.getByRole('region', {name: `${stocks[0].ticker} price chart`})
  await expect(chart.getByRole('checkbox', {name: 'Grade signals'})).toBeChecked()
  await expect(chart.getByRole('checkbox', {name: 'Model-only research fills'})).not.toBeChecked()
  for (const button of ['D', 'W']) {
    await chart.getByRole('button', {name: button, exact: true}).click()
    await expect(chart.getByLabel(`${stocks[0].ticker} grade signals`, {exact: true})).toContainText('2026-10-06 · BUY signal · Saved grade B→A+')
    await expect(chart.getByLabel(`${stocks[0].ticker} grade signals`, {exact: true})).toContainText('2026-10-08 · SELL signal · Recalculated grade A→B')
    await expect.poll(() => page.evaluate(() => (window as any).__gradePaint)).toEqual(expect.arrayContaining(['BUY · A+', 'SELL · B']))
  }
  await page.evaluate(() => {(window as any).__gradePaint = []})
  await chart.getByRole('button', {name: '15m', exact: true}).click()
  await expect(chart.getByLabel(`${stocks[0].ticker} grade signals`, {exact: true})).toContainText('not marked on fifteen-minute bars')
  expect(await page.evaluate(() => (window as any).__strategyPaint)).toEqual([])
  expect(await page.evaluate(() => (window as any).__gradePaint)).toEqual([])
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  await page.getByRole('searchbox', {name: 'Search the stock list'}).fill(stocks.at(-1)!.ticker)
  const row = page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('row').filter({has: page.getByRole('button', {name: stocks.at(-1)!.ticker, exact: true})})
  await expect(row.getByLabel(`${stocks.at(-1)!.ticker} strategy intent`)).toHaveText('BUY')
  await expect(row.getByLabel(`${stocks.at(-1)!.ticker} size`)).toHaveText('—')
  await expect(row).toContainText('The supported pullback held its reference.')
  await row.getByRole('button', {name: stocks.at(-1)!.ticker, exact: true}).click()
  await expect(page.getByLabel(`${stocks.at(-1)!.ticker} paper order`, {exact: true})).toContainText('Grade signal · no paper order')
  await expect(page.getByLabel(`${stocks.at(-1)!.ticker} signal status`, {exact: true})).toContainText('awaiting a fresh grade-led sizing plan')
  expect(errors).toEqual([])
})

// Confirmed account executions retain their quantity and clock instead of borrowing research trades.
test('actual paper execution chart mode stays separate from grade and model research', async ({page}) => {
  const errors = await install(page, stocks[0])
  const chart = page.getByRole('region', {name: `${stocks[0].ticker} price chart`})
  await chart.getByRole('checkbox', {name: 'Actual paper executions', exact: true}).check()
  await expect(chart.getByRole('checkbox', {name: 'Grade signals'})).not.toBeChecked()
  await expect(chart.getByRole('checkbox', {name: 'Model-only research fills'})).not.toBeChecked()
  await expect(chart.getByLabel(`${stocks[0].ticker} actual paper executions`, {exact: true})).toContainText('2026-10-07 · 11:00 AM ET · BUY 3 @ $101.00')
  await chart.getByRole('button', {name: '15m', exact: true}).click()
  await expect(chart.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-chart-timeframe', '15m')
  await expect.poll(() => page.evaluate(() => (window as any).__strategyPaint)).toEqual(expect.arrayContaining([expect.objectContaining({text: 'BUY 3 sh'})]))
  await chart.getByRole('checkbox', {name: 'Grade signals'}).check()
  await expect(chart.getByRole('checkbox', {name: 'Actual paper executions'})).not.toBeChecked()
  expect(errors).toEqual([])
})
