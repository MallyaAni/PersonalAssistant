import {expect, test} from '@playwright/test'

// Exercise live ranking, current holdings and matching chart judgments through the compiled app.
test('current opportunities rerank and completed exits do not reappear', async ({page}) => {
  const errors: string[] = [], writes: string[] = []
  let stage = 'initial'
  const now = new Date(), at = now.toISOString()
  const bar = new Date(+now - 16 * 60000).toISOString(), until = new Date(+now + 10 * 60000).toISOString()
  const previous = '2026-10-13'
  const names = ['READY', 'WAITING', 'EXITED', 'HELD']
  const old = (grade: string) => ({grade, score: -.5, stances: {fundamental: 1, technical: -1, sentiment: 1}, ranks: {fundamental: .9, technical: .1, sentiment: .8}})
  const grades = {READY: old('B'), WAITING: old('A+'), EXITED: old('C'), HELD: old('B')}
  // Supply a dated judgment independently of saved allocations and broker fills.
  const setup = (ticker: string, entry: string, reason: string) => ({ticker, entry, exit: ticker === 'WAITING' || ticker === 'HELD' ? 'review' : 'hold', entry_priority: 'high', exit_priority: 'high', reason, confirmation: 'hold_above', confirmation_ref: 'vwap', invalidation_ref: 'support', price: 102.125, bar, generated_at: at, valid_until: until, status: 'model_assessment', levels: {vwap: {label: 'session VWAP', price: 100}, support: {label: 'daily support', price: 98}}})
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (message.type() === 'error' || message.type() === 'warning') errors.push(message.text())})
  page.on('requestfailed', request => errors.push(request.url()))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    let json: any = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'rank-owner', is_admin: false, desk_access: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session: previous, grades, targets: {policy: 'grade-led-learned-sizing/1', weights: {READY: 0, WAITING: .8, HELD: .15, EXITED: 0}}, actions: names.map(ticker => ({ticker, grade_signal: ticker === 'EXITED' || ticker === 'HELD' ? 'sell' : 'buy', last_close: 101})), book: [], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: [previous]}
    else if (path.endsWith('/live')) json = {as_of: at, decision_session: previous, market_status: {phase: stage === 'closed' ? 'post' : 'open', as_of: at},
      quotes: Object.fromEntries(names.map(ticker => [ticker, {last: 102.125, open: 103, high: 104, low: 99, bar, as_of: at}])),
      grades_live: Object.fromEntries(names.map(ticker => [ticker, {grade_live: ticker === 'EXITED' ? 'C' : ticker === 'HELD' ? stage === 'review-held' ? 'A' : 'B' : 'A+', score_live: ticker === 'WAITING' ? .9 : .8}])),
      grade_valid_until: Object.fromEntries(names.map(ticker => [ticker, stage === 'expired' ? '2020-01-01T00:00:00Z' : until])),
      opportunities: {status: 'complete', rows: {READY: setup('READY', stage === 'swapped' ? 'wait' : 'ready', stage === 'swapped' ? 'The bounce failed; buyers need to regain control.' : 'Buyers defended the pullback and held the retest.'), WAITING: setup('WAITING', stage === 'swapped' ? 'ready' : 'wait', 'Wait for buyers to reclaim the session reference.'), HELD: setup('HELD', 'wait', 'The eligible holding needs a downside review.'), EXITED: setup('EXITED', 'avoid', 'Failed rebounds argue against a new entry.')}}, technical_detail: {}}
    else if (path.endsWith('/session-prices')) {
      const observed = new Date().toISOString()
      json = {session: 'regular', signal_scope: 'regular-session', as_of: observed, quotes: Object.fromEntries(names.map(ticker => [ticker, {price: stage === 'invalidated' && ticker === 'READY' ? 97 : 102, status: 'fresh', session: 'regular', feed: 'iex', at: observed, valid_until: stage === 'quote-expired' ? '2020-01-01T00:00:00Z' : until}]))}
    }
    else if (path.endsWith('/paper')) json = {equity: 100000, cash: 50000, positions: [{symbol: 'HELD', qty: stage === 'sold' ? 0 : 10, market_value: 1020, avg_entry_price: 100, unrealized_pl: 20}], plan: {orders: [{symbol: 'EXITED', side: 'sell', action: 'SELL', qty: 12, state: 'filled', terminal: true, client_order_id: 'original-exit', filled_at: at, status: 'Filled', price: 102, notional: 1224, weight: .01224}]}}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.includes('/history/')) json = {rows: [], fills: [], backtest: null}
    else if (path.includes('/chart/')) json = {ticker: 'READY', timeframe: 'daily', bars: [{date: previous, open: 100, high: 105, low: 99, close: 102, volume: 100}], overlays: {}, levels: {}, entries: []}
    else if (path.includes('/live/read/')) json = {read: 'The measured pullback held support.', lines: {short: [], medium: [], long: []}, data_at: bar, read_at: at, stale: false}
    else if (path.includes('/earnings/')) json = {read: null}
    else if (path.includes('/live-model-history/')) json = {schema: 'live-model-historical-sizing/1', policy: 'grade-led-learned-sizing/1', ticker: path.split('/').at(-1), start: '2019-03-01', through: previous, starting_cash: 100000, starting_holdings: {}, counterfactual: true, real_orders: false, provenance: {cost_bps: 10}, decisions: [], trades: [], targets: []}
    else if (path.includes('/strategy-simulation/')) json = {ticker: 'READY', counterfactual: true, real_orders: false, decisions: [], trades: [], targets: [], provenance: {cost_bps: 10}}
    else errors.push(`Unexpected endpoint ${path}`)
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  const table = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(table).toContainText('Current signal: AVOID')
  await expect(page.getByLabel('EXITED strategy intent', {exact: true})).toHaveText('—')
  await expect(page.getByLabel('HELD strategy intent', {exact: true})).toHaveText('SELL')
  await expect(page.getByLabel('READY strategy intent', {exact: true})).toHaveText('BUY')
  await expect(page.getByLabel('WAITING strategy intent', {exact: true})).toHaveText('WAIT')
  await expect(page.getByLabel('WAITING latest quote check', {exact: true})).toContainText('above the $100.00 confirmation reference; entry remains WAIT')
  await expect(table.getByRole('row').nth(2)).toContainText('READY')
  stage = 'review-held'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('HELD strategy intent', {exact: true})).toHaveText('REVIEW')
  await expect(page.getByLabel('HELD grade signal', {exact: true})).toContainText('Current signal: REVIEW')
  await page.getByRole('button', {name: 'READY', exact: true}).click()
  const judgment = page.getByRole('region', {name: 'Current chart judgment', exact: true})
  await expect(judgment).toContainText('Buyers defended the pullback')
  await expect(judgment).toContainText('$100.00')
  await expect(judgment).toContainText('$98.00')
  await expect(judgment).toContainText('Read at $102.13')
  await expect(page.getByRole('region', {name: 'Current assessment', exact: true})).toContainText('At $102.13')
  await expect(judgment.getByLabel('READY latest quote check', {exact: true})).toContainText('Latest quote $102.00')
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  await page.getByRole('button', {name: 'WAITING', exact: true}).click()
  await expect(judgment).toContainText('Existing holding: review downside risk')
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  stage = 'swapped'
  // An unattended price/assessment poll must update ranking without a refresh click.
  await expect(table.getByRole('row').nth(2)).toContainText('WAITING', {timeout: 30000})
  await expect(page.getByLabel('READY strategy intent', {exact: true})).toHaveText('WAIT')
  stage = 'invalidated'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('READY strategy intent', {exact: true})).toHaveText('WAIT')
  await expect(page.getByLabel('READY chart judgment', {exact: true})).toContainText('latest quote lost')
  await expect(page.getByLabel('READY chart judgment', {exact: true})).toContainText('Reassessment reference:')
  await expect(page.getByLabel('READY latest quote check', {exact: true})).toContainText('below the $100.00 confirmation reference')
  stage = 'quote-expired'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('READY strategy intent', {exact: true})).toHaveText('WAIT')
  await expect(page.getByLabel('READY chart judgment', {exact: true})).toContainText('fresh regular-session quote')
  stage = 'closed'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('READY strategy intent', {exact: true})).toHaveText('WAIT')
  stage = 'sold'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('HELD strategy intent', {exact: true})).not.toHaveText('SELL')
  stage = 'expired'
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('READY strategy intent', {exact: true})).not.toHaveText('BUY')
  await expect(page.getByLabel('READY displayed grade', {exact: true})).toContainText('fresh assessment unavailable')
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
