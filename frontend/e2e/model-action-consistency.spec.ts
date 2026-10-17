import {expect, test} from '@playwright/test'

// Keep current actions, sizes and timing bound to recorded plans while chart evidence changes.
test('chart judgments cannot invent funded actions or turn absent orders into HOLD', async ({page}) => {
  const errors: string[] = [], writes: string[] = []
  let chartEntry = 'ready', chartGrade = 'A+', unavailable = false
  let projection: any = null
  const now = Date.now(), at = new Date(now).toISOString()
  await page.clock.install({time: new Date(now)})
  const bar = new Date(now - 16 * 60000).toISOString(), until = new Date(now + 600000).toISOString()
  const session = '2026-10-13', names = ['READY', 'HELD', 'EXITED', 'BUYING', 'TRIMMING', 'ZERO']
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) errors.push(message.text())})
  page.on('requestfailed', request => errors.push(request.url()))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    let json: any = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'consistency-owner', desk_access: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session, grades: Object.fromEntries(names.map(ticker => [ticker, {grade: ticker === 'HELD' || ticker === 'EXITED' ? 'C' : 'A+'}])), targets: {policy: 'grade-led-learned-sizing/1', weights: {READY: .2, HELD: 0, ZERO: 0}}, paper: {joint_funded: {policy: 'grade-led-learned-sizing/1', as_of: session, receipt: {status: 'available'}}}, book: [], actions: [], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: [session]}
    else if (path.endsWith('/live')) json = {as_of: at, decision_session: session, market_status: {phase: 'open'}, quotes: Object.fromEntries(names.map(ticker => [ticker, {last: 102, open: 100, bar, as_of: at}])), grades_live: Object.fromEntries(names.map(ticker => [ticker, {grade_live: chartGrade, score_live: .9}])), grade_valid_until: Object.fromEntries(names.map(ticker => [ticker, until])), opportunities: {status: 'complete', rows: Object.fromEntries(names.map(ticker => [ticker, {ticker, entry: chartEntry, exit: 'review', entry_priority: 'high', exit_priority: 'high', reason: 'The measured chart setup is ready for review.', confirmation: 'hold_above', confirmation_ref: 'vwap', invalidation_ref: 'support', price: 102, bar, generated_at: at, valid_until: until, status: 'model_assessment', levels: {vwap: {label: 'session VWAP', price: 100}, support: {label: 'daily support', price: 98}}}]))}}
    else if (path.endsWith('/session-prices')) json = {session: 'regular', signal_scope: 'regular-session', as_of: at, quotes: Object.fromEntries(names.map(ticker => [ticker, {price: 102, status: 'fresh', session: 'regular', feed: 'iex', at, valid_until: until}]))}
    else if (path.endsWith('/paper')) json = unavailable ? {reason: 'Broker unavailable'} : {model_decisions: projection, as_of: at, equity: 100000, cash: 50000, positions: [{symbol: 'HELD', qty: 10, market_value: 1020}, {symbol: 'TRIMMING', qty: 20, market_value: 2040}], plan: {policy: 'grade-led-learned-sizing/1', rule: 'next_open', orders: [
      {client_order_id: 'recorded-buy', symbol: 'BUYING', action: 'BUY', side: 'buy', qty: 5, price: 100, notional: 500, weight: .005, decided: session, execute_on: '2026-10-14', state: 'queued', status: 'Queued', when: 'Wed Oct 14 · next open', why: 'Recorded funded entry', quantity_basis: 'submitted'},
      {client_order_id: 'recorded-trim', symbol: 'TRIMMING', action: 'TRIM', side: 'sell', qty: 2, price: 100, notional: 200, weight: .002, decided: session, execute_on: '2026-10-14', state: 'waiting', status: 'Waiting for the learned timing decision', when: 'Wed Oct 14 · learned timing', why: 'Recorded funded trim', quantity_basis: 'planned'},
      {client_order_id: 'old-filled-exit', symbol: 'EXITED', action: 'SELL', side: 'sell', qty: 12, price: 100, notional: 1200, state: 'queued', terminal: true, filled_qty: 12, filled_at: '2026-10-14T13:32:46Z', status: 'Filled'},
    ]}}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.includes('/history/')) json = {rows: [], fills: [], backtest: null}
    else if (path.includes('/chart/')) json = {ticker: 'BUYING', timeframe: 'daily', bars: [{date: session, open: 100, high: 104, low: 99, close: 102, volume: 100}], overlays: {}, levels: {}, entries: []}
    else if (path.includes('/live/read/') || path.includes('/earnings/')) json = {read: null}
    else if (path.includes('/strategy-simulation/')) json = {ticker: 'BUYING', counterfactual: true, real_orders: false, decisions: [], trades: [], targets: [], provenance: {cost_bps: 10}}
    else errors.push(`Unexpected endpoint ${path}`)
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  const table = page.getByRole('table', {name: 'Ranked stocks and cash'})
  for (const ticker of names) {
    await expect(table.getByLabel(`${ticker} strategy intent`, {exact: true})).toHaveText('—')
    await expect(table.getByLabel(`${ticker} size`, {exact: true})).toHaveText('—')
    await expect(table.getByLabel(`${ticker} order status`, {exact: true})).toContainText('Awaiting model plan')
  }
  await expect(table.getByLabel('HELD position', {exact: true})).toContainText('10 sh')
  // Actual paper orders remain inspectable but never stand in for a missing numeric decision.
  await page.getByRole('button', {name: 'details for BUYING', exact: true}).click()
  await expect(page.getByLabel('BUYING orders', {exact: true})).toContainText('5 sh submitted')
  await expect(page.getByLabel('BUYING orders', {exact: true})).toContainText('Wed Oct 14 · next open')
  await page.getByRole('button', {name: 'details for READY', exact: true}).click()
  await expect(page.getByLabel('READY chart judgment', {exact: true})).toContainText('measured chart setup')
  await expect(page.getByLabel('READY details', {exact: true})).toContainText('current numeric decision')
  projection = {version: 'live-model-decisions/1', status: 'available', session, observed_at: at, valid_until: until, policy: 'grade-led-learned-sizing/1', record_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), rows: {
    BUYING: {grade: 'A', signal_session: session, action: 'buy', qty: 3, status: 'planned', reason: 'Accepted whole-share funded entry', decided: session, execute_on: '2026-10-14', when: 'Wed Oct 14 · next open'},
    TRIMMING: {grade: 'A+', signal_session: session, action: 'trim', qty: 2, status: 'planned', reason: 'Accepted partial trim retains eligible shares', decided: session, execute_on: '2026-10-14', when: 'Wed Oct 14 · learned timing'},
    HELD: {grade: 'A', signal_session: session, action: 'hold', qty: 0, status: 'no_new_order', reason: 'Authenticated policy retention of the existing holding', when: null},
    READY: {grade: 'A+', signal_session: session, action: 'buy', qty: 0, status: 'blocked', reason: 'No whole shares funded after cash and risk constraints', when: null},
    EXITED: {action: 'sell', qty: 12, status: 'complete', reason: 'Original dated exit is already complete', when: 'Original Oct 14 execution'},
    ZERO: {action: null, qty: null, status: 'no_position', reason: 'Accepted plan has no position or new entry', when: null},
  }}
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('BUYING strategy intent', {exact: true})).toHaveText('BUY')
  await expect(table.getByLabel('BUYING size', {exact: true})).toHaveText('3 sh funded')
  await expect(table.getByLabel('BUYING order status', {exact: true})).toContainText('Wed Oct 14 · next open')
  await expect(table.getByLabel('TRIMMING strategy intent', {exact: true})).toHaveText('TRIM')
  await expect(table.getByLabel('TRIMMING size', {exact: true})).toHaveText('2 sh funded')
  await expect(table.getByLabel('HELD strategy intent', {exact: true})).toHaveText('HOLD')
  await expect(table.getByLabel('READY strategy intent', {exact: true})).toHaveText('BUY')
  await expect(table.getByLabel('READY size', {exact: true})).toHaveText('0 sh funded')
  await expect(table.getByLabel('READY order status', {exact: true})).toContainText('No whole shares funded after cash and risk constraints')
  await expect(table.getByLabel('EXITED strategy intent', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('EXITED size', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('EXITED order status', {exact: true})).not.toContainText('Original Oct 14 execution')
  await page.getByRole('button', {name: 'BUYING', exact: true}).click()
  const card = page.getByRole('region', {name: 'BUYING paper order', exact: true})
  await expect(card).toContainText('3 sh funded')
  await expect(card).toContainText('Recorded paper: BUY 5 sh submitted')
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  chartEntry = 'avoid'
  chartGrade = 'C'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('READY chart judgment', {exact: true})).toContainText('Chart assessment C')
  await expect(table.getByLabel('READY displayed grade', {exact: true})).toContainText('A+')
  await expect(table.getByLabel('BUYING displayed grade', {exact: true})).toContainText('2026-10-13 plan')
  await expect(table.getByLabel('HELD strategy intent', {exact: true})).toHaveText('HOLD')
  await expect(table.getByLabel('BUYING strategy intent', {exact: true})).toHaveText('BUY')
  await expect(table.getByLabel('TRIMMING strategy intent', {exact: true})).toHaveText('TRIM')
  // The client expires the full decision without waiting for an account refresh.
  projection.valid_until = new Date(await page.evaluate(() => Date.now()) + 10000).toISOString()
  projection.rows.BUYING.reason = 'Accepted entry in the expiring numeric receipt'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await page.getByRole('button', {name: 'details for BUYING', exact: true}).click()
  await expect(page.getByLabel('BUYING details', {exact: true})).toContainText('Accepted entry in the expiring numeric receipt')
  await page.clock.runFor(10001)
  await expect(table.getByLabel('BUYING strategy intent', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('BUYING size', {exact: true})).toHaveText('—')
  projection.valid_until = until
  projection.status = 'stale'
  projection.reason = 'The recorded account basis belongs to an earlier session'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('BUYING strategy intent', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('BUYING size', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('BUYING order status', {exact: true})).not.toContainText('Wed Oct 14')
  projection.status = 'available'
  projection.valid_until = '2020-01-01T00:00:00Z'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('HELD strategy intent', {exact: true})).toHaveText('—')
  projection.valid_until = until
  projection.session = '2026-10-12'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('READY strategy intent', {exact: true})).toHaveText('—')
  projection.session = session
  projection.rows.BUYING.when = null
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('BUYING strategy intent', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('BUYING size', {exact: true})).toHaveText('—')
  unavailable = true
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('HELD order status', {exact: true})).toContainText('Account unavailable')
  await expect(table.getByLabel('HELD strategy intent', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('HELD position', {exact: true})).toHaveText('unavailable')
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
