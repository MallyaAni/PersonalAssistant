import {expect, test} from '@playwright/test'

// Keep current actions, sizes and timing bound to recorded plans while chart evidence changes.
test('chart judgments cannot invent funded actions or turn absent orders into HOLD', async ({page}) => {
  const errors: string[] = [], writes: string[] = []
  let chartEntry = 'ready', chartGrade = 'A+', unavailable = false
  const now = Date.now(), at = new Date(now).toISOString()
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
    else if (path.endsWith('/paper')) json = unavailable ? {reason: 'Broker unavailable'} : {as_of: at, equity: 100000, cash: 50000, positions: [{symbol: 'HELD', qty: 10, market_value: 1020}, {symbol: 'TRIMMING', qty: 20, market_value: 2040}], plan: {policy: 'grade-led-learned-sizing/1', rule: 'next_open', orders: [
      {client_order_id: 'recorded-buy', symbol: 'BUYING', action: 'BUY', side: 'buy', qty: 5, price: 100, notional: 500, weight: .005, decided: session, execute_on: '2026-10-14', state: 'queued', status: 'Queued', when: 'Wed Oct 14 · next open', why: 'Recorded funded entry', quantity_basis: 'submitted'},
      {client_order_id: 'recorded-trim', symbol: 'TRIMMING', action: 'TRIM', side: 'sell', qty: 2, price: 100, notional: 200, weight: .002, decided: session, execute_on: '2026-10-14', state: 'waiting', status: 'Waiting for the learned timing decision', when: 'Wed Oct 14 · learned timing', why: 'Recorded funded trim', quantity_basis: 'planned'},
      {client_order_id: 'old-filled-exit', symbol: 'EXITED', action: 'SELL', side: 'sell', qty: 12, price: 100, notional: 1200, state: 'queued', terminal: true, filled_qty: 12, filled_at: '2026-10-14T13:32:46Z', status: 'Filled'},
    ]}}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else errors.push(`Unexpected endpoint ${path}`)
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  const table = page.getByRole('table', {name: 'Ranked stocks and cash'})
  for (const ticker of ['READY', 'HELD', 'EXITED', 'ZERO']) {
    await expect(table.getByLabel(`${ticker} strategy intent`, {exact: true})).toHaveText('—')
    await expect(table.getByLabel(`${ticker} size`, {exact: true})).toHaveText('—')
    await expect(table.getByLabel(`${ticker} order status`, {exact: true})).toContainText('Awaiting model plan')
  }
  await expect(table.getByLabel('HELD position', {exact: true})).toContainText('10 sh')
  await expect(table.getByLabel('BUYING strategy intent', {exact: true})).toHaveText('BUY')
  await expect(table.getByLabel('BUYING size', {exact: true})).toContainText('5 sh submitted')
  await expect(table.getByLabel('BUYING order status', {exact: true})).toContainText('Wed Oct 14 · next open')
  await expect(table.getByLabel('TRIMMING strategy intent', {exact: true})).toHaveText('TRIM')
  await expect(table.getByLabel('TRIMMING size', {exact: true})).toContainText('2 sh planned')
  await page.getByRole('button', {name: 'details for READY', exact: true}).click()
  await expect(page.getByLabel('READY chart judgment', {exact: true})).toContainText('measured chart setup')
  await expect(page.getByLabel('READY details', {exact: true})).toContainText('current numeric decision')
  chartEntry = 'avoid'
  chartGrade = 'C'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('READY displayed grade', {exact: true})).toContainText('C')
  await expect(table.getByLabel('HELD strategy intent', {exact: true})).toHaveText('—')
  await expect(table.getByLabel('BUYING strategy intent', {exact: true})).toHaveText('BUY')
  await expect(table.getByLabel('TRIMMING strategy intent', {exact: true})).toHaveText('TRIM')
  unavailable = true
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(table.getByLabel('HELD order status', {exact: true})).toContainText('Account unavailable')
  await expect(table.getByLabel('HELD strategy intent', {exact: true})).toHaveText('—')
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
