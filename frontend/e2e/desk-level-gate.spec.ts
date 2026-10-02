import {expect, test, type Page} from '@playwright/test'

// The board's clock, as the paper account's orders report it (backend
// `intraday_orders.board_row`): a buy waits for a 15-minute close 1% under
// the day's open, a sell for one 1% over it, otherwise a market order on the
// last 15-minute run before the close (3:45 PM ET). The action cell says BUY / SELL / TRIM with the size
// beside it whatever the stage; the status column says where the order is
// (waiting for its level, level hit, close window, sent); a name whose daily
// rejects the upper band has no buy and says so; the grade column shows the
// record's close grade the orders are based on.

const session = '2026-09-24'
const written = '2026-09-24T00:00:00Z'
const at = '2026-09-24T14:31:00Z'
const POLICY = 'graded-equal-weight/4'
const EQUITY = 100000

// One order as `/desk/paper` lists it: the fields the board prints, worded
// the way `board_row` words them for the given stage.
function order(symbol: string, side: 'buy' | 'sell', action: 'BUY' | 'SELL' | 'TRIM', qty: number, price: number, why: string,
  stage: {state: string; status: string; open?: number; level?: number; sent_at?: string; sent_how?: 'market' | 'moc'}) {
  const level = stage.level ?? null
  const open = stage.open ?? null
  const rule = level !== null && open !== null
    ? `15-min close ${side === 'buy' ? '≤' : '≥'} $${level.toFixed(2)} (1% ${side === 'buy' ? 'under' : 'over'} the $${open.toFixed(2)} open), else at market in the last 15 minutes`
    : `15-min close 1% ${side === 'buy' ? 'under' : 'over'} the open, else at market in the last 15 minutes`
  return {client_order_id: `${symbol}-${side}-1`, symbol, side, action, qty, price, notional: qty * price, weight: qty * price / EQUITY,
    leg: side === 'buy' ? 'entry' : 'exit', why, reason: null, timing: 'dip_or_close', decided: '2026-09-23', execute_on: session,
    open, level, sent_at: stage.sent_at ?? null, sent_how: stage.sent_how ?? null, filled_qty: null, filled_price: null, filled_at: null,
    state: stage.state, status: stage.status, when: `Today · ${rule}`}
}

const WAITING = order('AAPL', 'buy', 'BUY', 51, 178.2, 'Enters the book at 9.1%',
  {state: 'waiting', status: 'Waiting for $178.20, else a market order at 3:45 PM', open: 180, level: 178.2})
const TRIGGERED = order('AAPL', 'buy', 'BUY', 51, 178.05, 'Enters the book at 9.1%',
  {state: 'due', status: 'Level hit: the 10:30 AM close ($178.05) · order due', open: 180, level: 178.2})
const CLOSING = order('AAPL', 'buy', 'BUY', 51, 179, 'Enters the book at 9.1%',
  {state: 'due', status: 'Close window · market order due (3:45 PM run)', open: 180, level: 178.2})
const EXIT = order('AMD', 'sell', 'SELL', 28, 181.9, 'Exit: the grade fell to B',
  {state: 'due', status: 'Level hit: the 10:30 AM close ($181.90) · order due', open: 180, level: 181.8})
const TRIM = order('MSFT', 'sell', 'TRIM', 27, 181.9, 'Trim to its 9.1% target',
  {state: 'due', status: 'Level hit: the 10:30 AM close ($181.90) · order due', open: 180, level: 181.8})

// Serve the desk, a live candle whose `as_of` can move, and the paper
// account with the given orders and holdings; record the order of
// `/desk/live` and `/desk/paper` reads.
async function setup(page: Page, {orders, held = {}, blocked = []}: {orders: ReturnType<typeof order>[]; held?: Record<string, number>; blocked?: string[]},
  liveAsOf: () => string = () => at) {
  const errors: string[] = []
  const log: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => errors.push(request.url()))
  await page.clock.install({time: new Date(at)})
  const names = [...new Set([...orders.map(o => o.symbol), ...Object.keys(held), ...blocked])]
  const grade = (ticker: string) => orders.find(o => o.symbol === ticker)?.action === 'SELL' ? 'B' : 'A'
  const status = {exchange: 'XNYS', as_of: at, session, calendar_known: true, is_session: true, open: true, phase: 'open',
    opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
  const positions = Object.entries(held).map(([symbol, qty]) => ({symbol, qty, avg_entry_price: 170, current_price: 179, market_value: qty * 179, unrealized_pl: qty * 9}))
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let json: unknown = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: true}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {
      session, written, regime: {exposure: 1, flags: []},
      grades: Object.fromEntries(names.map(ticker => [ticker, {grade: grade(ticker), score: 1, votes: 3, stances: {}, ranks: {}, headline: '', reason: ''}])),
      targets: {policy: POLICY, weights: Object.fromEntries(names.map(ticker => [ticker, grade(ticker) === 'A' ? .0909 : 0]))},
      book: names.map(ticker => ({ticker, weight: .0909, grade: 'A'})),
      actions: names.map(ticker => ({ticker, action: 'hold', grade: grade(ticker), last_close: 179, rejecting_band: blocked.includes(ticker)})), briefs: {},
    }, sessions: [session]}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/live')) {
      const asOf = liveAsOf()
      log.push(`live:${asOf}`)
      json = {as_of: asOf, data_at: asOf, market_status: status,
        quotes: Object.fromEntries(names.map(ticker => [ticker, {symbol: ticker, last: 179, open: 180, bar: '2026-09-24T14:15:00Z', as_of: asOf}])),
        technical: {}, technical_detail: {}}
    } else if (path.endsWith('/session-prices')) json = {session: 'regular', as_of: at, signal_scope: 'regular-session', quotes: {}}
    else if (path.endsWith('/paper')) {
      log.push('paper')
      json = {user_id: 'ani.mallya', as_of: liveAsOf(), equity: EQUITY, cash: 20000, positions, orders: [], activity: {session, complete: true, fills: []},
        plan: {rule: 'dip_or_close', rule_text: {buy: '15-min close 1% under the open, else at market in the last 15 minutes', sell: '15-min close 1% over the open, else at market in the last 15 minutes'},
          orders, until_rebalance: 12, last_rebalance: '2026-09-10', reason: null}}
    } else if (path.endsWith('/paper/history')) json = {user_id: 'ani.mallya', rows: []}
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  return {errors, log, board}
}

// Waiting for the level: BUY with its size, the level and the close window in
// the status, the rule for the session under it, the close grade in the column.
test('a /4 buy waiting for its level shows BUY with the level it waits for', async ({page}) => {
  const {errors, board} = await setup(page, {orders: [WAITING]})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL action status')).toHaveText('Enters the book at 9.1%')
  await expect(board.getByLabel('AAPL size')).toContainText('51 sh')
  await expect(board.getByLabel('AAPL size')).toContainText('$9,088 · 9.1%')
  await expect(board.getByLabel('AAPL order status')).toContainText('Waiting for $178.20, else a market order at 3:45 PM')
  await expect(board.getByLabel('AAPL order status')).toContainText('Today · 15-min close ≤ $178.20 (1% under the $180.00 open), else at market in the last 15 minutes')
  await expect(board.getByLabel('AAPL displayed grade', {exact: true})).toHaveText('A')
  await expect(page.getByLabel('Today', {exact: true})).toContainText('Paper orders: 1 waiting for their level.')
  expect(errors).toEqual([])
})

// A 15-minute close reached the level: the order is due, not confirmed sent.
test('a triggered /4 buy is BUY at its level', async ({page}) => {
  const {errors, board} = await setup(page, {orders: [TRIGGERED]})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toContainText('51 sh')
  await expect(board.getByLabel('AAPL order status')).toContainText('Level hit: the 10:30 AM close ($178.05) · order due')
  await expect(page.getByLabel('Today', {exact: true})).toContainText('Paper orders: 1 due.')
  expect(errors).toEqual([])
})

// The close window's last run with no trigger: BUY near the close, at market.
test('the close window is BUY at the close', async ({page}) => {
  const {errors, board} = await setup(page, {orders: [CLOSING]})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toContainText('51 sh')
  await expect(board.getByLabel('AAPL order status')).toContainText('Close window · market order due (3:45 PM run)')
  await expect(board.getByLabel('AAPL order status')).toContainText('else at market in the last 15 minutes')
  expect(errors).toEqual([])
})

// A downgrade exit on a 1% pop is SELL of the whole position; a trim on its
// level is TRIM; a name whose daily rejects the upper band has no buy and
// says why, rather than reading as a hold.
test('a downgrade on a pop is SELL, a trim is TRIM, a band-blocked buy says so', async ({page}) => {
  const {errors, board} = await setup(page, {orders: [EXIT, TRIM], held: {AMD: 28, MSFT: 77}, blocked: ['NVDA']})
  await expect(board.getByLabel('AMD strategy intent')).toHaveText('SELL')
  await expect(board.getByLabel('AMD action status')).toHaveText('Exit: the grade fell to B')
  await expect(board.getByLabel('AMD size')).toContainText('28 sh')
  await expect(board.getByLabel('AMD size')).toContainText('$5,093 · 5.1%')
  await expect(board.getByLabel('AMD order status')).toContainText('Level hit: the 10:30 AM close ($181.90) · order due')
  await expect(board.getByLabel('AMD order status')).toContainText('Today · 15-min close ≥ $181.80 (1% over the $180.00 open), else at market in the last 15 minutes')
  await expect(board.getByLabel('AMD displayed grade', {exact: true})).toHaveText('B')
  await expect(board.getByLabel('MSFT strategy intent')).toHaveText('TRIM')
  await expect(board.getByLabel('MSFT action status')).toHaveText('Trim to its 9.1% target')
  await expect(board.getByLabel('MSFT size')).toContainText('27 sh')
  // A name the account neither holds nor trades is on the All names view.
  await page.getByRole('group', {name: 'Board view'}).getByRole('button', {name: /All names/}).click()
  await expect(board.getByLabel('NVDA strategy intent')).toHaveText('—')
  await expect(board.getByLabel('NVDA action status')).toHaveText('In the book · no buy while its daily rejects the upper band')
  await expect(board.getByLabel('NVDA size')).toHaveText('—')
  await expect(page.getByLabel('Today', {exact: true})).toContainText('Paper orders: 2 due.')
  expect(errors).toEqual([])
})

// Real time: the orders are re-read within a minute, and a new `/desk/live`
// `as_of` (a new balancer candle) is followed by a fresh read of the orders.
test('the paper orders refresh within a minute and after every new candle', async ({page}) => {
  let candle = at
  const next = '2026-09-24T14:46:00Z'
  const {errors, log, board} = await setup(page, {orders: [WAITING]}, () => candle)
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  // Let the page's start-up reads finish before counting.
  await expect.poll(async () => {
    const seen = log.length
    await page.waitForTimeout(400)
    return log.length === seen
  }).toBe(true)
  // How many times the page has asked for the paper account's orders so far.
  const papers = () => log.filter(entry => entry === 'paper').length
  const before = papers()
  const from = log.length
  // The balancer writes a new candle; within a minute the page reads it and
  // then the orders built on it.
  candle = next
  await page.clock.fastForward(60_000)
  await expect.poll(papers).toBeGreaterThan(before)
  await expect.poll(() => log.slice(from).includes(`live:${next}`)).toBe(true)
  await expect.poll(() => log.slice(log.indexOf(`live:${next}`)).includes('paper')).toBe(true)
  expect(errors).toEqual([])
})
