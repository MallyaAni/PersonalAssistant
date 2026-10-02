import {expect, test, type Page} from '@playwright/test'

const session = '2026-09-24'
const written = '2026-09-24T00:00:00Z'
const at = '2026-09-24T14:00:00Z'
const EQUITY = 100000
const POLICY = 'graded-equal-weight/4'

type Order = {symbol: string; side: 'buy' | 'sell'; action: 'BUY' | 'SELL' | 'TRIM'; qty: number; price: number; why: string; state: string; status: string; when: string}

// One order as `/desk/paper` lists it, in the backend's own words for its stage.
function order(symbol: string, side: 'buy' | 'sell', action: 'BUY' | 'SELL' | 'TRIM', qty: number, price: number, why: string,
  stage: {state: string; status: string; when?: string} = {state: 'waiting', status: `Waiting for $${(price * (side === 'buy' ? .99 : 1.01)).toFixed(2)} or the close (3:30 PM window)`}): Order {
  return {symbol, side, action, qty, price, why, state: stage.state, status: stage.status,
    when: stage.when ?? `Today · 15-min close 1% ${side === 'buy' ? 'under' : 'over'} the open, else at the close`}
}

// The paper account: its money, its positions and the orders the board lists.
function paper(orders: Order[], held: Record<string, number> = {}, untilReset = 12) {
  return {user_id: 'ani.mallya', as_of: at, equity: EQUITY, cash: 20000, orders: [], activity: {session, complete: true, fills: []},
    positions: Object.entries(held).map(([symbol, qty]) => ({symbol, qty, avg_entry_price: 90, current_price: 100, market_value: qty * 100, unrealized_pl: qty * 10})),
    plan: {rule: 'dip_or_close', rule_text: {buy: '15-min close 1% under the open, else at the close', sell: '15-min close 1% over the open, else at the close'},
      until_rebalance: untilReset, last_rebalance: '2026-09-10', reason: null,
      orders: orders.map((o, i) => ({client_order_id: `${o.symbol}-${i}`, symbol: o.symbol, side: o.side, action: o.action, qty: o.qty, price: o.price,
        notional: o.qty * o.price, weight: o.qty * o.price / EQUITY, leg: o.side === 'buy' ? 'entry' : 'exit', why: o.why, reason: null,
        timing: 'dip_or_close', decided: '2026-09-23', execute_on: session, open: null, level: null, sent_at: null, sent_how: null,
        filled_qty: null, filled_price: null, filled_at: null, state: o.state, status: o.status, when: o.when}))}}
}

// Exercise the complete desk with deterministic record, market and paper-account responses.
async function setup(page: Page, {open = true, paused = false, account, beforeNavigate}: {
  open?: boolean; paused?: boolean; account?: ReturnType<typeof paper>; beforeNavigate?: () => Promise<void>} = {}) {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => errors.push(request.url()))
  await page.clock.install({time: new Date(at)})
  const book = account ?? paper([order('AAPL', 'buy', 'BUY', 20, 100, 'Enters the book at 2.0%')])
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let json: unknown = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: true}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {
      session, written, regime: {exposure: 1, flags: []},
      grades: Object.fromEntries(['AAPL', 'NVDA', 'MSFT'].map(ticker => [ticker, {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}, headline: `${ticker}: trend and growth lead`, reason: '+ Technical: above its 50-day average'}])),
      targets: {policy: POLICY, weights: {AAPL: .0909, NVDA: .0909, MSFT: .0909}},
      book: [{ticker: 'AAPL', weight: .05, grade: 'A'}], actions: ['AAPL', 'NVDA', 'MSFT'].map(ticker => ({ticker, action: 'hold', grade: 'A', last_close: 100})), briefs: {},
    }, sessions: [session], event_policy: paused ? {enabled: true} : undefined,
      event_status: paused ? {planning_paused: true, active: true, stale: false, status: 'reduction pending'} : undefined}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/live')) json = {as_of: at, data_at: at, market_status: {exchange: 'XNYS', as_of: at, session, calendar_known: true, is_session: true, open, phase: open ? 'regular' : 'post-market'}, quotes: {AAPL: {symbol: 'AAPL', last: 100, bar: at, as_of: at}}, technical: {}, technical_detail: {}}
    else if (path.endsWith('/session-prices')) json = {session: open ? 'regular' : 'post-market', as_of: at, signal_scope: 'regular-session', quotes: {}}
    else if (path.endsWith('/paper')) json = book
    else if (path.endsWith('/paper/history')) json = {user_id: 'ani.mallya', rows: []}
    await route.fulfill({json})
  })
  if (beforeNavigate) await beforeNavigate()
  await page.goto('/#desk')
  return {errors}
}

// Keep the primary board small while preserving the evidence and the paper position on request.
test('visible grades and concise actions expose diagnostics only on request', async ({page}) => {
  const {errors} = await setup(page)
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const headers = board.locator('thead tr').last().getByRole('columnheader')
  await expect(page.locator('details[aria-label="Strategy details"]')).not.toHaveAttribute('open', '')
  await expect(headers).toHaveCount(8)
  await expect(headers).toHaveText([/Details/, /Stock/, /Grade/, /Position/, /Levels/, /Action/, /Size/, /When \/ status/])
  await expect(board.getByLabel('AAPL displayed grade', {exact: true})).toHaveText('A')
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toContainText('20 sh')
  await expect(board.getByLabel('AAPL size')).toContainText('$2,000 · 2.0%')
  await page.getByRole('group', {name: 'Board view'}).getByRole('button', {name: /All names/}).click()
  await expect(board.getByLabel('MSFT size')).toHaveText('—')
  // The grade's evidence and the position are in the details, not on the row.
  await expect(board).not.toContainText('above its 50-day average')
  await expect(board.getByLabel('AAPL grade', {exact: true})).toHaveCount(0)
  await page.getByRole('button', {name: 'details for AAPL', exact: true}).click()
  await expect(board.getByLabel('AAPL grade', {exact: true})).toContainText('Grade A')
  await expect(board.getByLabel('AAPL grade', {exact: true})).toContainText('above its 50-day average')
  await expect(board.getByLabel('AAPL position', {exact: true}).last()).toContainText('Not held')
  await expect(board.getByLabel('AAPL position', {exact: true}).last()).toContainText('Target 9.1% (graded-equal-weight/4)')
  await expect(board.getByLabel('AAPL orders', {exact: true})).toContainText('BUY 20 sh planned · $2,000 · 2.0% of current equity')
  await page.setViewportSize({width: 390, height: 844})
  if (await page.getByRole('button', {name: 'Hide Sidebar'}).isVisible()) await page.mouse.click(380, 500)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await board.scrollIntoViewIfNeeded()
  const why = board.getByLabel('AAPL action status', {exact: true})
  await expect(why).toBeVisible()
  await expect(why).toBeInViewport()
  await expect(why).toContainText('Enters the book at 2.0%')
  await page.screenshot({path: '/tmp/simple-actions-mobile.png', fullPage: true})
  expect(errors).toEqual([])
})

// Personal entry permission is separate from the paper order already shown on the main board.
test('a recovered personal entry shows Hold and retains its grade', async ({page}) => {
  const limitReason = 'SIP ask $106.01 exceeds $99.00 entry limit'
  let ask = 106.01
  let quoteAt = at
  let expires = '2026-09-24T14:00:30Z'
  let delayed: Promise<void> | null = null
  let releaseOlder!: () => void
  let olderStarted = false
  const {errors} = await setup(page, {beforeNavigate: async () => {
    // This test previews advice and refuses history or position persistence.
    await page.route('**/api/v1/auth/session', route => route.fulfill({json: {
      authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: false,
    }}))
    // Answer the read-only personal preview without saving advice or positions.
    await page.route('**/desk/mine', async route => {
      const body = route.request().postDataJSON()
      expect(body.record_history).toBe(false)
      const funded = body.available_cash > 0
      const allowed = ask <= 99
      const blocker = !funded ? body.available_cash === 0 ? 'no available cash' : 'available cash is unknown' : allowed ? null : limitReason
      const payload = {session, rows: [], decisions: {
        session, written, as_of: quoteAt, equity: EQUITY, holdings: {},
        timing: {rule: 'dip_or_close', level: .01, session, latched: true},
        rows: {AAPL: {
          action: funded && allowed ? 'Buy' : 'Hold', move_weight: funded && allowed ? .0909 : 0,
          strategy_action: 'Buy', strategy_move_weight: .0909,
          target_weight: .0909, current_weight: 0, delta_weight: .0909,
          executable: funded && allowed, blocker, reason: blocker ?? 'Buy limit $99.00', grade: 'A',
          valid_until: expires, entry_status: 'available',
          quote: {eligible: true, spread_verified: true, feed: 'sip', ask, at: quoteAt, valid_until: expires},
          timing: {rule: 'dip_or_close', state: 'triggered', side: 'buy', session,
            open: 100, level: 99, trigger_bar: '2026-09-24T13:30:00Z', trigger_price: 98.9,
            reason: 'Recorded dip at $98.90'},
          entry_guard: {policy: 'current-dip-limit/1', allowed, limit_price: 99,
            ask, quote_at: quoteAt, valid_until: expires, feed: 'sip', reason: allowed ? 'Buy limit $99.00' : limitReason},
        }},
      }}
      if (delayed) {
        const pending = delayed
        delayed = null
        olderStarted = true
        await pending
      }
      await route.fulfill({json: payload})
    })
  }})
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('AAPL strategy intent', {exact: true})).toHaveText('BUY')
  await expect(page.getByLabel('AAPL displayed grade', {exact: true})).toHaveText('A')
  await page.getByLabel('Personal portfolio', {exact: true}).locator(':scope > summary').click()
  await page.getByRole('button', {name: 'details for AAPL', exact: true}).click()
  const personal = page.getByRole('region', {name: 'AAPL personal guidance', exact: true})
  await expect(personal).toContainText('Cash needed')
  await page.getByLabel('Personal available cash', {exact: true}).fill('10000')
  await page.getByRole('button', {name: 'Apply', exact: true}).click()
  await expect(personal).toContainText('Hold')
  await expect(personal).toContainText('Entry limit')
  await expect(personal.getByLabel('AAPL strategy intent', {exact: true})).toHaveAttribute('title', limitReason)
  await page.clock.runFor(31000)
  await expect(personal).toContainText('Unavailable')
  await expect(personal).not.toContainText('Entry limit')
  ask = 98.99
  quoteAt = '2026-09-24T14:00:31Z'
  expires = '2026-09-24T14:01:01Z'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(personal.getByLabel('AAPL personal trade size')).toHaveText('9.1% of account')
  await expect(personal.getByLabel('AAPL personal entry limit')).toHaveText('Limit $99.00')
  await expect(personal.getByLabel('AAPL strategy intent', {exact: true})).toContainText('BUY')
  await expect(board.getByLabel('AAPL displayed grade', {exact: true})).toHaveText('A')
  // Complete an older funded reply only after the person confirms zero cash.
  delayed = new Promise<void>(resolve => {releaseOlder = resolve})
  const olderResponse = page.waitForResponse(response => response.url().includes('/desk/mine')
    && response.request().postDataJSON()?.available_cash === 10000)
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect.poll(() => olderStarted).toBe(true)
  await page.getByLabel('Personal available cash', {exact: true}).fill('0')
  await page.getByRole('button', {name: 'Apply', exact: true}).click()
  await expect(personal).toContainText('Blocked')
  releaseOlder()
  await (await olderResponse).finished()
  await page.clock.runFor(50)
  await expect(personal).toContainText('Blocked')
  await expect(personal.getByLabel('AAPL personal trade size')).toHaveCount(0)
  expect(errors).toEqual([])
})

// With the market shut the order is planned for the next session: the word and the size stay,
// the status says so, and the row never claims every venue is closed.
test('a planned order with the market closed keeps its word and size', async ({page}) => {
  const {errors} = await setup(page, {open: false, account: paper([
    order('AAPL', 'buy', 'BUY', 20, 100, 'Enters the book at 2.0%', {state: 'planned', status: 'Planned', when: 'Thu Sep 25 · 15-min close 1% under the open, else at the close'}),
    order('NVDA', 'sell', 'SELL', 10, 100, 'Exit: the grade fell to B', {state: 'planned', status: 'Planned', when: 'Thu Sep 25 · 15-min close 1% over the open, else at the close'}),
  ], {NVDA: 10})})
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toContainText('20 sh')
  await expect(board.getByLabel('AAPL order status')).toContainText('Planned')
  await expect(board.getByLabel('AAPL order status')).toContainText('Thu Sep 25 · 15-min close 1% under the open, else at the close')
  await expect(board.getByLabel('NVDA strategy intent')).toHaveText('SELL')
  await expect(board.getByLabel('NVDA order status')).toContainText('Thu Sep 25 · 15-min close 1% over the open, else at the close')
  await expect(page.getByLabel('Today', {exact: true})).toContainText('Paper orders: 2 planned.')
  await expect(board).not.toContainText('Market closed')
  expect(errors).toEqual([])
})

// Collapsing explanatory sections never conceals a current portfolio pause.
test('strategy details start collapsed while active trading restrictions remain visible', async ({page}) => {
  const {errors} = await setup(page, {paused: true})
  const details = page.locator('details[aria-label="Strategy details"]')
  await expect(details).not.toHaveAttribute('open', '')
  await expect(page.getByLabel('Execution rule')).toContainText('FOMC cycle: the paper account follows the FOMC risk rule; its orders say when.')
  await details.locator(':scope > summary').click()
  await expect(page.getByLabel('FOMC exposure policy')).toContainText('reduction pending')
  expect(errors).toEqual([])
})

// Missing exchange observations stay visible without drawing a valid band or changing the board's word.
test('ticker panels disclose chart gaps and retain the board decision', async ({page}) => {
  const {errors} = await setup(page)
  await page.route('**/desk/history/MSFT', route => route.fulfill({json: {rows: [], ticker: 'MSFT', recommendations: {observations: []}}}))
  await page.route('**/desk/chart/MSFT*', route => {
    const weekly = new URL(route.request().url()).searchParams.get('timeframe') === 'weekly'
    const dates = weekly ? ['2026-09-18', '2026-09-24'] : ['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24']
    return route.fulfill({json: {
      ticker: 'MSFT', timeframe: weekly ? 'weekly' : 'daily', timeframes: ['daily', 'weekly'], adjusted: true,
      basis: 'adjusted prices', last_bar_complete: !weekly, sessions: dates.length, quote_bar: at,
      data_status: 'incomplete', data_reason: 'Missing exchange sessions; affected indicators unavailable.', missing_sessions: ['2026-09-22'],
      bars: dates.map((date, i) => ({date, open: i === 1 ? null : 99, high: i === 1 ? null : 101, low: i === 1 ? null : 98, close: i === 1 ? null : 100, volume: i === 1 ? null : 1000})),
      overlays: {band_upper: dates.map(() => null), band_lower: dates.map(() => null)}, levels: {}, entries: [],
    }})
  })
  await page.getByRole('group', {name: 'Board view'}).getByRole('button', {name: /All names/}).click()
  await expect(page.getByLabel('MSFT action status', {exact: true})).toHaveText('In the book at 9.1% · no order tonight')
  await page.getByRole('button', {name: 'MSFT', exact: true}).click()
  const card = page.getByRole('region', {name: 'MSFT paper order'})
  await expect(card).toContainText('In the book at 9.1% · no order tonight')
  await expect(card).toContainText('Position none · target 9.1%')
  const chart = page.getByLabel('MSFT price chart', {exact: true})
  await expect(chart.getByLabel('Chart data quality')).toContainText('Chart data incomplete · 1 missing session')
  await chart.getByLabel('Chart data quality').locator('summary').click()
  await expect(chart.getByLabel('Chart data quality')).toContainText('2026-09-22')
  await expect(chart.locator('dl')).not.toContainText('Upper Bollinger band')
  await expect(chart.locator('dl')).not.toContainText('Lower Bollinger band')
  await expect(chart).not.toContainText('could not be drawn')
  await chart.getByRole('button', {name: 'W', exact: true}).click()
  await expect(chart).toContainText('incomplete candle')
  await expect(chart.locator('dl dt')).toHaveText(['Newest stored candle price'])
  await expect(chart.locator('dl dd')).toHaveText(['—'])
  await expect(chart).not.toContainText('(forming candle)')
  expect(errors).toEqual([])
})

// The default ranking: orders still to happen first (biggest first), then orders done today,
// then holdings by weight, then the other graded names by grade; the Size heading re-sorts.
test('default ranking follows order stage, size, position and grade', async ({page}) => {
  const grades = {
    NVDA: {grade: 'B', score: .99}, AAPL: {grade: 'A+', score: .9},
    MSFT: {grade: 'A+', score: .8}, AMZN: {grade: 'A+', score: .7}, AMD: {grade: 'A', score: 1},
  }
  const {errors} = await setup(page, {account: paper([
    order('NVDA', 'buy', 'BUY', 40, 100, 'Enters the book at 4.0%'),
    order('AAPL', 'buy', 'BUY', 20, 100, 'Enters the book at 2.0%'),
    order('MSFT', 'sell', 'SELL', 80, 100, 'Exit: the grade fell to B', {state: 'filled', status: 'Sold 80 @ $100.00 · 9:46 AM'}),
  ], {MSFT: 80, AMZN: 900}), beforeNavigate: async () => {
    await page.route('**/desk', route => route.fulfill({json: {latest: {
      session, written, regime: {exposure: 1, flags: []}, grades,
      targets: {policy: POLICY, weights: {AAPL: .0909, MSFT: .0909, AMZN: .0909, AMD: .0909}},
      book: [{ticker: 'AMZN', weight: .9, grade: 'A+'}], actions: [], briefs: {},
    }, sessions: [session]}}))
  }})
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  // Read only stock rows so expanded details cannot affect ranking.
  const order_ = () => board.locator('tbody tr').filter({has: page.getByLabel(/displayed grade$/)}).locator('td:nth-child(2) button').allTextContents()
  await expect(board.getByLabel('NVDA displayed grade', {exact: true})).toHaveText('B')
  // The board opens on the portfolio: the orders and the holdings.
  await expect.poll(order_).toEqual(['NVDA', 'AAPL', 'MSFT', 'AMZN'])
  await page.getByRole('group', {name: 'Board view'}).getByRole('button', {name: /All names/}).click()
  await expect.poll(order_).toEqual(['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AMD'])
  await board.getByRole('button', {name: 'Size', exact: true}).click()
  await expect.poll(order_).toEqual(['MSFT', 'NVDA', 'AAPL', 'AMZN', 'AMD'])
  await board.getByRole('button', {name: 'Size', exact: true}).click()
  await expect.poll(order_).toEqual(['AMZN', 'AMD', 'AAPL', 'NVDA', 'MSFT'])
  await board.getByRole('button', {name: 'Size', exact: true}).click()
  await expect.poll(order_).toEqual(['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AMD'])
  await expect(board.getByLabel('NVDA size', {exact: true})).toContainText('$4,000 · 4.0%')
  expect(errors).toEqual([])
})

// Under the `/4` policy a held name with no order says where it stands against its target and
// when the reset moves it; a name in the book with no order says so; the plan is in the details.
test('a held name without an order says where it stands against its target', async ({page}) => {
  const {errors} = await setup(page, {open: false, account: paper([], {NVDA: 91, MSFT: 140}, 5)})
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('NVDA strategy intent')).toHaveText('HOLD')
  await expect(board.getByLabel('NVDA action status')).toHaveText('Near its 9.1% target')
  await expect(board.getByLabel('NVDA size')).toHaveText('—')
  await expect(board.getByLabel('NVDA position', {exact: true})).toContainText('91 sh · 9.1%')
  await expect(board.getByLabel('MSFT strategy intent')).toHaveText('HOLD')
  await expect(board.getByLabel('MSFT action status')).toHaveText('Above its 9.1% target · trimmed at the reset in 5 sessions')
  await expect(board.getByLabel('MSFT size')).toHaveText('—')
  await page.getByRole('group', {name: 'Board view'}).getByRole('button', {name: /All names/}).click()
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('—')
  await expect(board.getByLabel('AAPL action status')).toHaveText('In the book at 9.1% · no order tonight')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  await expect(page.getByLabel('Today', {exact: true})).toContainText('No paper orders.')
  await page.getByRole('button', {name: 'details for MSFT', exact: true}).click()
  await expect(board.getByLabel('MSFT orders', {exact: true})).toContainText('No order')
  await expect(board.getByLabel('MSFT orders', {exact: true})).toContainText('trimmed at the reset in 5 sessions')
  await expect(board.getByLabel('MSFT position', {exact: true}).last()).toContainText('140 sh · $14,000 · 14.0%')
  await expect(board.getByLabel('MSFT position', {exact: true}).last()).toContainText('Target 9.1%')
  expect(errors).toEqual([])
})

// A sell that keeps a positive target is a trim, and the row says so: the word is TRIM, the
// size is the reduction, the reason reads under the word. A sell to zero stays SELL.
test('a trim reads as TRIM with its reason, an exit stays SELL', async ({page}) => {
  const {errors} = await setup(page, {account: paper([
    order('MSFT', 'sell', 'TRIM', 49, 100, 'Trim to its 9.1% target'),
    order('NVDA', 'sell', 'SELL', 50, 100, 'Exit: the grade fell to B'),
  ], {MSFT: 140, NVDA: 50})})
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('MSFT strategy intent')).toHaveText('TRIM')
  await expect(board.getByLabel('MSFT action status')).toHaveText('Trim to its 9.1% target')
  await expect(board.getByLabel('MSFT size')).toContainText('49 sh')
  await expect(board.getByLabel('MSFT size')).toContainText('$4,900 · 4.9%')
  await expect(board.getByLabel('NVDA strategy intent')).toHaveText('SELL')
  await expect(board.getByLabel('NVDA action status')).toHaveText('Exit: the grade fell to B')
  await page.getByRole('button', {name: 'details for MSFT', exact: true}).click()
  await expect(board.getByLabel('MSFT orders', {exact: true})).toContainText('TRIM 49 sh planned · $4,900 · 4.9% of current equity')
  await expect(board.getByLabel('MSFT orders', {exact: true})).toContainText('Trim to its 9.1% target')
  expect(errors).toEqual([])
})
