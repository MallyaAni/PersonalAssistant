import {expect, test, type Page} from '@playwright/test'

// The timed `/4` board (backend `decision_view._time_the_board`): the action
// cell shows BUY / SELL / TRIM only when the measured level triggered today
// or in the close window, and Hold otherwise; the size shows only beside a
// trade; the hover carries the planned level, the timing state, the
// executor's band gate and the intraday grade; the grade column shows the
// record's close grade the action is based on.

const session = '2026-09-24'
const written = '2026-09-24T00:00:00Z'
const at = '2026-09-24T14:31:00Z'
const until = '2026-09-24T14:45:00Z'
const POLICY = 'graded-equal-weight/4'
const TARGET = 'Buy to 9.1% target (policy graded-equal-weight/4)'

// One row's timing as the backend writes it (`entry_timing.timing`).
function timing(state: string, reason: string, side: 'buy' | 'sell' = 'buy') {
  return {rule: 'dip_or_close', side, state, level_fraction: .01, session, trading_day: true,
    open: 180, level: side === 'buy' ? 178.2 : 181.8, trigger_bar: state === 'triggered' ? '2026-09-24T14:15:00+00:00' : null,
    trigger_price: state === 'triggered' ? 178.05 : null, close_cutoff: '2026-09-24T15:30:00-04:00',
    moc_deadline: '2026-09-24T15:50:00-04:00', reason}
}

// A decision row on the timed board: the timed action, the kept intent and the evidence.
function row(fields: Record<string, unknown>) {
  return {executable: true, blocker: null, target_weight: .0909, current_weight: 0, valid_until: until,
    structure_gate: 'clear', grade: 'A', grade_intraday: null, strategy_action: 'Buy', strategy_move_weight: .0909,
    quote: {feed: 'sip', at, bid: 99.9, ask: 100.1, spread_verified: true, eligible: true, reason: 'ok', valid_until: until},
    ...fields}
}

const WAITING = row({action: 'Hold', move_weight: 0, grade_intraday: 'B',
  reason: `Buy 9.1% planned: on a 15-minute close at or under $178.20 (1% under today's open $180.00), else at the close; ${TARGET}`,
  timing: timing('waiting', "Waiting for a 15-minute close at or under $178.20 (1% under today's open $180.00); at the close from 3:30 PM ET if none")})
const TRIGGERED = row({action: 'Buy', move_weight: .0909,
  reason: `Buy now: the 10:30 AM ET 15-minute close $178.05 is at or under $178.20 (1% under today's open $180.00); ${TARGET}`,
  timing: timing('triggered', "Triggered: the 10:30 AM ET 15-minute close $178.05 is at or under $178.20 (1% under today's open $180.00)")})
const CLOSING = row({action: 'Buy', move_weight: .0909,
  reason: `Buy at the close: no 15-minute close reached $178.20 today; market-on-close before 3:50 PM ET; ${TARGET}`,
  timing: timing('close', 'At the close: no 15-minute close reached $178.20 today; market-on-close before 3:50 PM ET')})
const BLOCKED = row({action: 'Hold', move_weight: 0, executable: false, blocker: "rejecting its upper band (executor's gate)",
  structure_gate: 'rejecting', reason: `Buy blocked: rejecting its upper band (executor's gate); ${TARGET}`,
  timing: timing('triggered', "Triggered: the 10:30 AM ET 15-minute close $178.05 is at or under $178.20 (1% under today's open $180.00)")})
const EXIT = row({action: 'Sell', strategy_action: 'Sell', move_weight: -.05, strategy_move_weight: -.05, target_weight: 0,
  current_weight: .05, grade: 'B',
  reason: "Sell now: the 10:30 AM ET 15-minute close $181.90 is at or over $181.80 (1% over today's open $180.00); grade below A; close position; sized against your holdings and dated prices",
  timing: timing('triggered', "Triggered: the 10:30 AM ET 15-minute close $181.90 is at or over $181.80 (1% over today's open $180.00)", 'sell')})
const TRIM = row({action: 'Sell', strategy_action: 'Sell', move_weight: -.0491, strategy_move_weight: -.0491, current_weight: .14,
  reason: "Trim now: the 10:30 AM ET 15-minute close $181.90 is at or over $181.80 (1% over today's open $180.00); Trim to 9.1% target (policy graded-equal-weight/4); holding 14.0%",
  timing: timing('triggered', "Triggered: the 10:30 AM ET 15-minute close $181.90 is at or over $181.80 (1% over today's open $180.00)", 'sell')})

// Serve the desk, a live candle whose `as_of` can move, and the timed board
// for the given rows; record the order of `/desk/live` and `/desk/mine` reads.
async function setup(page: Page, rows: Record<string, unknown>, liveAsOf: () => string = () => at) {
  const errors: string[] = []
  const log: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => errors.push(request.url()))
  await page.clock.install({time: new Date(at)})
  const names = Object.keys(rows)
  const status = {exchange: 'XNYS', as_of: at, session, calendar_known: true, is_session: true, open: true, phase: 'open',
    opens_at: '2026-09-24T09:30:00-04:00', closes_at: '2026-09-24T16:00:00-04:00'}
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let json: unknown = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: true}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {
      session, written, regime: {exposure: 1, flags: []},
      grades: Object.fromEntries(names.map(ticker => [ticker, {grade: (rows[ticker] as {grade: string}).grade, score: 1, votes: 3, stances: {}, ranks: {}, headline: '', reason: ''}])),
      targets: {policy: POLICY, weights: Object.fromEntries(names.map(ticker => [ticker, .0909]))},
      book: names.map(ticker => ({ticker, weight: .0909, grade: 'A'})), actions: [], briefs: {},
    }, sessions: [session]}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/live')) {
      const asOf = liveAsOf()
      log.push(`live:${asOf}`)
      json = {as_of: asOf, data_at: asOf, market_status: status,
        quotes: Object.fromEntries(names.map(ticker => [ticker, {symbol: ticker, last: 179, open: 180, bar: '2026-09-24T14:15:00Z', as_of: asOf}])),
        technical: {}, technical_detail: {}}
    } else if (path.endsWith('/mine')) {
      log.push('mine')
      json = {session, rows: [], market_status: status, grade_valid_until: {},
        // The candle re-grades every name to B; the timed board still shows the close grade.
        grades_live: Object.fromEntries(names.map(ticker => [ticker, {grade_live: 'B', score_live: .5}])),
        decisions: {session, written, equity: 100000, holdings: {},
          timing: {rule: 'dip_or_close', level: .01, session, close_cutoff: '2026-09-24T15:30:00-04:00', moc_deadline: '2026-09-24T15:50:00-04:00', latched: true},
          rows}}
    } else if (path.endsWith('/personal-history')) json = {receipts: [], has_more: false}
    else if (path.endsWith('/entries')) json = {session, rows: []}
    else if (path.endsWith('/intraday')) json = {session, rows: [], top_buys: [], changed: []}
    else if (path.endsWith('/paper')) json = {reason: 'unavailable'}
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  return {errors, log, board}
}

// The row of the board that holds `ticker`.
function rowOf(page: Page, ticker: string) {
  return page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('row').filter({has: page.getByRole('button', {name: ticker, exact: true})})
}

// Waiting for the level: Hold with no size, the planned level on hover, the
// close grade in the column and the intraday reading only on hover.
test('a /4 buy waiting for its level is a Hold with the level on hover', async ({page}) => {
  const {errors, board} = await setup(page, {AAPL: WAITING})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('Hold')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  const title = rowOf(page, 'AAPL')
  await expect(title).toHaveAttribute('title', /^Hold: Buy 9\.1% planned: on a 15-minute close at or under \$178\.20 \(1% under today's open \$180\.00\), else at the close/)
  await expect(title).toHaveAttribute('title', /Timing · waiting for the level: Waiting for a 15-minute close at or under \$178\.20/)
  await expect(title).toHaveAttribute('title', /Structure · not rejecting its upper band \(executor's gate\)/)
  await expect(title).toHaveAttribute('title', /Grade A at the 2026-09-24 close \(the one the action uses\) · intraday reading B/)
  await expect(board.getByLabel('AAPL displayed grade', {exact: true})).toHaveText('AClose')
  await expect(board.getByLabel('AAPL displayed grade', {exact: true})).toHaveAttribute('title', /intraday reading B/)
  await expect(page.getByLabel('Today', {exact: true})).not.toContainText('executable signal.')
  expect(errors).toEqual([])
})

// A 15-minute close reached the level: BUY with its size.
test('a triggered /4 buy is BUY 9.1%', async ({page}) => {
  const {errors, board} = await setup(page, {AAPL: TRIGGERED})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toHaveText('9.1% of account')
  await expect(rowOf(page, 'AAPL')).toHaveAttribute('title', /^BUY: Buy now: the 10:30 AM ET 15-minute close \$178\.05/)
  await expect(rowOf(page, 'AAPL')).toHaveAttribute('title', /Timing · level reached today/)
  await expect(page.getByLabel('Today', {exact: true})).toContainText('1 executable signal.')
  expect(errors).toEqual([])
})

// The close window with no trigger: BUY at the close, market-on-close.
test('the close window is BUY at the close', async ({page}) => {
  const {errors, board} = await setup(page, {AAPL: CLOSING})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toHaveText('9.1% of account')
  await expect(rowOf(page, 'AAPL')).toHaveAttribute('title', /market-on-close before 3:50 PM ET/)
  await expect(rowOf(page, 'AAPL')).toHaveAttribute('title', /Timing · close window/)
  expect(errors).toEqual([])
})

// A downgrade exit on a 1% pop is SELL of the whole position; a trim on its
// level is TRIM; a band-rejecting buy is a Hold that names the gate.
test('a downgrade on a pop is SELL, a trim is TRIM, a band-blocked buy is Hold', async ({page}) => {
  const {errors, board} = await setup(page, {AMD: EXIT, MSFT: TRIM, NVDA: BLOCKED})
  await expect(board.getByLabel('AMD strategy intent')).toHaveText('SELL')
  await expect(board.getByLabel('AMD size')).toHaveText('5.0% of account')
  await expect(rowOf(page, 'AMD')).toHaveAttribute('title', /^SELL: Sell now: the 10:30 AM ET 15-minute close \$181\.90 is at or over \$181\.80/)
  await expect(board.getByLabel('MSFT strategy intent')).toHaveText('TRIM')
  await expect(board.getByLabel('MSFT size')).toHaveText('4.9% of account')
  await expect(board.getByLabel('NVDA strategy intent')).toHaveText('Hold')
  await expect(board.getByLabel('NVDA size')).toHaveText('—')
  await expect(rowOf(page, 'NVDA')).toHaveAttribute('title', /^Hold: Buy blocked: rejecting its upper band \(executor's gate\)/)
  await expect(rowOf(page, 'NVDA')).toHaveAttribute('title', /Structure · rejecting its upper band \(executor's gate\): no buy today/)
  await expect(page.getByLabel('Today', {exact: true})).toContainText('2 executable signals.')
  expect(errors).toEqual([])
})

// Real time: the plan is re-read within a minute, and a new `/desk/live`
// `as_of` (a new balancer candle) is followed by a fresh plan.
test('the timed plan refreshes within a minute and after every new candle', async ({page}) => {
  let candle = at
  const next = '2026-09-24T14:46:00Z'
  const {errors, log, board} = await setup(page, {AAPL: WAITING}, () => candle)
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('Hold')
  // Let the page's start-up reads finish before counting.
  await expect.poll(async () => {
    const seen = log.length
    await page.waitForTimeout(400)
    return log.length === seen
  }).toBe(true)
  // How many times the page has asked for the personal plan so far.
  const mines = () => log.filter(entry => entry === 'mine').length
  const before = mines()
  const from = log.length
  // The balancer writes a new candle; within a minute the page reads it and
  // then the plan built on it.
  candle = next
  await page.clock.fastForward(60_000)
  await expect.poll(mines).toBeGreaterThan(before)
  await expect.poll(() => log.slice(from).includes(`live:${next}`)).toBe(true)
  await expect.poll(() => log.slice(log.indexOf(`live:${next}`)).includes('mine')).toBe(true)
  expect(errors).toEqual([])
})
