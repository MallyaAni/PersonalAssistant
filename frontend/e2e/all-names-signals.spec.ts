import {expect, test, type Page} from '@playwright/test'

const names = ['BUYLOW', 'BUYHIGH', 'SELLLOW', 'SELLHIGH', 'WAIT', 'MISSING']
const session = '2026-10-13'
type Fixture = {phase: string; paper: boolean; lost: boolean; expired: boolean; quoteMissing: boolean; liveReads: number; diagnostics: string[]; simulationPolicy?: string; signalUntil?: string}

// Exercise live signal evidence with deliberately contrary paper allocations and executions.
async function install(page: Page, baseURL: string, state: Fixture) {
  page.on('pageerror', error => state.diagnostics.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) state.diagnostics.push(message.text())})
  page.on('requestfailed', request => state.diagnostics.push(`Failed ${request.url()}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.push(`HTTP ${response.status()} ${response.url()}`)})
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (url.origin !== new URL(baseURL).origin || request.method() !== 'GET') {
      state.diagnostics.push(`Forbidden request ${request.method()} ${url.href}`)
      return route.abort()
    }
    if (!path.startsWith('/api/')) return route.continue()
    const now = Date.now(), at = new Date(now - 100).toISOString(), bar = new Date(now - 16 * 60000).toISOString()
    const until = new Date(state.expired ? now - 1000 : now + 120000).toISOString()
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: 'signals-owner', desk_access: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session, written: `${session}T23:47:45Z`, grades: Object.fromEntries(names.map(ticker => [ticker, {grade: 'B'}])),
      targets: {policy: 'grade-led-learned-sizing/1', weights: {BUYLOW: .99, BUYHIGH: 0, SELLHIGH: 0}}, actions: [], book: [], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: [session]}
    else if (path.endsWith('/live')) {
      state.liveReads++
      json = {as_of: at, decision_session: session, market_status: {phase: state.phase, as_of: at},
        quotes: Object.fromEntries(names.map(ticker => [ticker, {last: 102, bar, as_of: at}])),
        grades_live: Object.fromEntries(names.map(ticker => [ticker, {grade_live: ticker.startsWith('SELL') ? 'C' : 'A', score_live: .5}])),
        grade_valid_until: Object.fromEntries(names.map(ticker => [ticker, until])), technical: {}, technical_detail: {},
        opportunities: {status: 'complete', rows: Object.fromEntries(names.filter(ticker => ticker !== 'MISSING').map(ticker => [ticker, {
          ticker, entry: ticker.startsWith('BUY') ? 'ready' : ticker === 'WAIT' ? 'wait' : 'avoid', exit: ticker.startsWith('SELL') ? 'review' : 'hold',
          entry_priority: ticker === 'BUYLOW' ? 'low' : 'high', exit_priority: ticker === 'SELLLOW' ? 'low' : 'high',
          reason: ticker.startsWith('SELL') ? 'Failed rebounds and broken support warrant a downside review.' : 'Buyers defended support; entry awaits only the stated confirmation.',
          confirmation: 'hold_above', confirmation_ref: 'vwap', invalidation_ref: 'support',
          levels: {vwap: {label: 'session VWAP', price: 100}, support: {label: 'daily support', price: 98}},
          price: 102, bar, generated_at: at, valid_until: state.signalUntil ?? until, status: 'model_assessment',
        }]))}}
    } else if (path.endsWith('/session-prices')) json = {as_of: at, signal_scope: 'regular-session', session: 'regular', quotes: Object.fromEntries(names.map(ticker => [ticker, {
      price: state.lost && ticker === 'BUYHIGH' ? 97 : 102, session: 'regular', status: state.quoteMissing ? 'unavailable' : 'fresh', feed: 'iex', at, valid_until: until}]))}
    else if (path.endsWith('/paper')) json = state.paper ? {reason: 'Paper account unavailable'} : {equity: 100000, cash: 0, positions: [{symbol: 'BUYLOW', qty: 999, market_value: 99900}],
      plan: {orders: [{symbol: 'BUYHIGH', action: 'SELL', qty: 777, state: 'filled', terminal: true, client_order_id: 'contrary-paper'}]},
      model_decisions: {status: 'unavailable', rows: {}}}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.includes('/history/')) json = {rows: [{date: session, grade: 'C', said: true}, {date: '2026-10-14', grade: 'A', said: false}, {date: '2026-10-15', grade: 'B', said: false}], fills: [], backtest: null}
    else if (path.includes('/chart/')) json = {ticker: path.split('/').pop(), timeframe: 'daily', adjusted: true, basis: 'split-adjusted daily candles', bars: [session, '2026-10-14', '2026-10-15'].map(date => ({date, open: 100, high: 105, low: 99, close: 102, volume: 100})), overlays: {}, levels: {}, entries: []}
    else if (path.includes('/live-model-history/')) json = {schema: 'live-model-historical-sizing/1', ticker: path.split('/').pop(), policy: 'grade-led-learned-sizing/1', start: session, through: '2026-10-15', starting_cash: 100000, starting_holdings: {}, counterfactual: true, real_orders: false, decisions: [], trades: [], targets: [], provenance: {cost_bps: 10, original_holding_publication: '2026-10-17T00:00:00Z'}}
    else if (path.includes('/strategy-simulation/')) json = {schema: 'latest-strategy-simulation/1', ticker: path.split('/').pop(), policy: state.simulationPolicy ?? 'earlier-policy',
      start: session, through: '2026-10-15', counterfactual: true, real_orders: false, splits: [], decisions: [],
      trades: [{id: 'sim-buy', date: '2026-10-14', at: '2026-10-14T14:00:00Z', action: 'BUY', qty: 7, price: 101}, {id: 'sim-sell', date: '2026-10-15', at: '2026-10-15T15:00:00Z', action: 'SELL', qty: 5, price: 102}], targets: [], latest_target: .02, latest_holding: 2, provenance: {cost_bps: 10, basis: 'Independent synthetic acceptance portfolio; not actual historical evidence.'}}
    else if (path.includes('/live/read/')) json = {read: 'Buyers defended support.', lines: {short: [], medium: [], long: []}, data_at: bar, read_at: at, stale: false}
    else if (path.includes('/earnings/')) json = {read: null}
    else {
      state.diagnostics.push(`Unspecified ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Unexpected route'}})
    }
    return route.fulfill({json})
  })
}

// Supply fresh evidence without modifying the wall clock or any real account.
function fixture(): Fixture {
  return {phase: 'open', paper: false, lost: false, expired: false, quoteMissing: false, liveReads: 0, diagnostics: []}
}

// Complete a real refresh before inspecting the new signal state.
async function refresh(page: Page, state: Fixture) {
  const prior = state.liveReads
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect.poll(() => state.liveReads).toBeGreaterThan(prior)
}

// Rank both directions by original model priority without paper sizes or account inputs.
test('All names ranks independent buy and sell signals, with matching details', async ({page, baseURL}) => {
  const state = fixture()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board).toBeVisible({timeout: 5000})
  await board.getByRole('button', {name: 'Best buys', exact: true}).click()
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'BUYHIGH')
  await expect(board.getByLabel('BUYHIGH buy signal', {exact: true})).toContainText('Buy now')
  await expect(board.getByLabel('BUYHIGH signal strength', {exact: true})).toHaveText('High')
  await expect(board).not.toContainText('777 sh')
  await expect(board).not.toContainText('999 sh')
  await board.getByRole('button', {name: 'Best sells', exact: true}).click()
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'SELLHIGH')
  await expect(board.getByLabel('SELLHIGH sell signal', {exact: true})).toContainText('Sell review now')
  await expect(board.getByLabel('SELLHIGH signal strength', {exact: true})).toHaveText('High')
  await board.getByRole('button', {name: 'details for SELLHIGH', exact: true}).click()
  const detail = board.getByLabel('SELLHIGH signal details', {exact: true})
  await expect(detail).toContainText('Failed rebounds and broken support')
  await expect(detail).toContainText('$98.00')
  await expect(detail).toContainText('Not a short-sale signal')
  await expect(detail).toContainText('Valid until')
  state.paper = true
  await refresh(page, state)
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'SELLHIGH')
  await expect(board.getByLabel('SELLHIGH sell signal', {exact: true})).toContainText('Sell review now')
  await page.reload()
  await page.getByRole('region', {name: 'All names signals', exact: true}).getByRole('button', {name: 'Best buys', exact: true}).click()
  await expect(page.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'BUYHIGH')
  expect(state.diagnostics).toEqual([])
})

// Expire the model judgment on its original deadline without a refresh or a changed grade/quote.
test('All names expires its own signal receipt without a network update', async ({page, baseURL}) => {
  const state = fixture()
  state.signalUntil = new Date(Date.now() + 7000).toISOString()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const buy = page.getByLabel('BUYHIGH buy signal', {exact: true})
  await expect(buy).toContainText('Buy now')
  await expect(buy).toContainText('Unavailable', {timeout: 10000})
  await expect(page.getByLabel('BUYHIGH displayed grade', {exact: true})).toHaveText('A')
  expect(state.diagnostics).toEqual([])
})

// Display simulated shares and grade changes together only for a matching historical policy.
test('Stock charts show simulated actions, share counts and grade changes together', async ({page, baseURL}, info) => {
  const state = fixture()
  state.simulationPolicy = 'grade-led-learned-sizing/1'
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  await expect(dialog.getByRole('checkbox', {name: 'Grade changes', exact: true})).toBeChecked()
  await expect(dialog.getByRole('checkbox', {name: 'Simulated trades', exact: true})).toBeChecked()
  await expect(dialog.getByLabel('BUYHIGH simulated chart markers', {exact: true})).toContainText('BUY 7 sh')
  await expect(dialog.getByLabel('BUYHIGH simulated chart markers', {exact: true})).toContainText('SELL 5 sh')
  await expect(dialog.getByLabel('BUYHIGH grade signals', {exact: true})).toContainText('2 grade changes marked')
  await dialog.getByRole('checkbox', {name: 'Simulated trades', exact: true}).uncheck()
  await expect(dialog.getByRole('checkbox', {name: 'Grade changes', exact: true})).toBeChecked()
  await dialog.getByRole('checkbox', {name: 'Simulated trades', exact: true}).check()
  await expect(dialog.getByLabel('BUYHIGH signal details', {exact: true})).toContainText('Buy now')
  await expect(dialog.getByRole('region', {name: 'BUYHIGH paper order'})).toHaveCount(0)
  await info.attach('simulated-chart', {body: await page.screenshot(), contentType: 'image/png'})
  expect(state.diagnostics).toEqual([])
})

// Refuse to present an earlier allocator's simulated shares as current-strategy performance.
test('Stock charts withhold an incompatible historical simulation', async ({page, baseURL}) => {
  const state = fixture()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  await expect(dialog).toContainText('The stored simulation belongs to a different policy; its trades are withheld.')
  await expect(dialog.getByLabel('BUYHIGH simulated chart markers', {exact: true})).toHaveCount(0)
  await expect(dialog).not.toContainText('BUY 7 sh')
  await expect(dialog.getByLabel('BUYHIGH grade signals', {exact: true})).toContainText('2 grade changes marked')
  expect(state.diagnostics).toEqual([])
})

// Withhold immediate actions after quote loss, session close or expired source evidence.
test('All names separates waiting, invalidated and unavailable signals', async ({page, baseURL}) => {
  const state = fixture()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board.getByLabel('BUYHIGH buy signal', {exact: true})).toContainText('Buy now', {timeout: 5000})
  await expect(board.getByLabel('WAIT buy signal', {exact: true})).toContainText('Wait')
  await expect(board.getByLabel('MISSING buy signal', {exact: true})).toContainText('Unavailable')
  state.lost = true
  await refresh(page, state)
  await expect(board.getByLabel('BUYHIGH buy signal', {exact: true})).toContainText('Wait')
  await board.getByRole('button', {name: 'Best buys', exact: true}).click()
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'BUYLOW')
  state.quoteMissing = true
  await refresh(page, state)
  await expect(board.getByLabel('BUYLOW buy signal', {exact: true})).toContainText('Wait')
  await expect(board.getByLabel('SELLHIGH sell signal', {exact: true})).toContainText('Wait')
  state.quoteMissing = false; state.phase = 'post-market'
  await refresh(page, state)
  await expect(board).not.toContainText('Buy now')
  await expect(board).not.toContainText('Sell review now')
  state.expired = true
  await refresh(page, state)
  await expect(board.getByLabel('BUYHIGH buy signal', {exact: true})).toContainText('Unavailable')
  await expect(board.getByLabel('SELLHIGH sell signal', {exact: true})).toContainText('Unavailable')
  expect(state.diagnostics).toEqual([])
})
