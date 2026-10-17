import {expect, test} from '@playwright/test'

// Reconciled journal fills stay historical and visible after pending orders have been removed.
test('settled fills survive reconciliation without becoming actions or inflating today', async ({page}) => {
  const errors: string[] = [], writes: string[] = []
  const at = '2026-10-17T14:00:00Z', session = '2026-10-13'
  const originals = [
    {client_order_id: 'anios-2026-10-13-sell-stx-135', symbol: 'STX', side: 'sell', qty: 12, price: 739.236667, filled_at: '2026-10-14T13:32:46.922719Z', session, created_at: '2026-10-13T23:46:44Z', reconciled_at: at},
    {client_order_id: 'anios-2026-10-13-sell-swks-136', symbol: 'SWKS', side: 'sell', qty: 130, price: 76.181923, filled_at: '2026-10-14T13:33:32.086665Z', session, created_at: '2026-10-13T23:46:44Z', reconciled_at: at},
  ]
  const distinct = ['first', 'second'].map(id => ({client_order_id: id, symbol: 'SAME', side: 'buy', qty: 2, price: 100, filled_at: '2026-10-17T13:45:00Z', session: '2026-10-16', created_at: '2026-10-16T23:46:44Z', reconciled_at: at}))
  const recorded = [originals[0], originals[0], originals[1], ...distinct,
    {...originals[0], client_order_id: 'invalid-zero', qty: 0},
    {...originals[0], client_order_id: 'invalid-future', qty: 999, filled_at: '2026-10-18T13:30:00Z'},
  ]
  await page.clock.install({time: new Date(at)})
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) errors.push(message.text())})
  page.on('requestfailed', request => errors.push(request.url()))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    let json: any = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'settled-owner', desk_access: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session, written: `${session}T23:47:45Z`, grades: {STX: {grade: 'C'}, SWKS: {grade: 'C'}, SAME: {grade: 'A+'}}, targets: {policy: 'grade-led-learned-sizing/1', weights: {}}, actions: [], book: [], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: [session]}
    else if (path.endsWith('/live')) json = {as_of: at, decision_session: session, quotes: {}, technical: {}, technical_detail: {}, market_status: {phase: 'closed'}}
    else if (path.endsWith('/session-prices')) json = {session: 'closed', signal_scope: 'regular-session', as_of: at, quotes: {}}
    else if (path.endsWith('/paper')) json = {as_of: at, equity: 100000, cash: 50000, positions: [], orders: [], recorded_fills: recorded, activity: {session: '2026-10-17', complete: true, fills: distinct}, plan: {policy: 'grade-led-learned-sizing/1', rule: 'next_open', orders: []}}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.endsWith('/paper/history')) json = {rows: []}
    else if (path.includes('/history/')) {
      const ticker = path.split('/').at(-1)
      const fills = ticker === 'STX' ? [0, 1].map(() => ({client_order_id: originals[0].client_order_id, date: '2026-10-14', side: 'sell', qty: 12, price: 739.236667}))
        : ticker === 'SAME' ? distinct.map(fill => ({date: '2026-10-17', side: fill.side, qty: fill.qty, price: fill.price})) : []
      json = {ticker, rows: [], fills, backtest: null}
    }
    else if (path.includes('/chart/')) json = {ticker: path.split('/').at(-1), timeframe: 'daily', bars: ['2026-10-13', '2026-10-14', '2026-10-17'].map(date => ({date, open: 100, high: 800, low: 70, close: 100, volume: 100})), overlays: {}, levels: {}, entries: []}
    else if (path.includes('/live/read/') || path.includes('/earnings/')) json = {read: null}
    else if (path.includes('/strategy-simulation/')) json = {ticker: path.split('/').at(-1), counterfactual: true, real_orders: false, decisions: [], trades: [], targets: [], provenance: {cost_bps: 10}}
    else errors.push(`Unexpected endpoint ${path}`)
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  const table = page.getByRole('table', {name: 'Ranked stocks and cash'})
  for (const ticker of ['STX', 'SWKS', 'SAME']) {
    await expect(table.getByLabel(`${ticker} strategy intent`, {exact: true})).toHaveText('—')
    await expect(table.getByLabel(`${ticker} size`, {exact: true})).toHaveText('—')
  }
  await page.getByRole('button', {name: 'Paper account', exact: true}).click()
  await page.locator('details[aria-label="Paper account"] > summary').click()
  const executions = page.getByRole('region', {name: 'Paper execution', exact: true})
  await expect(executions).toContainText('2 fills · 2026-10-17')
  await expect(executions.locator('[data-client-order-id="anios-2026-10-13-sell-stx-135"]')).toHaveCount(1)
  await expect(executions.locator('[data-client-order-id="anios-2026-10-13-sell-stx-135"]')).toContainText('Sold 12 STX @ $739.24')
  await expect(executions.locator('[data-client-order-id="anios-2026-10-13-sell-stx-135"] time')).toHaveAttribute('datetime', originals[0].filled_at)
  await expect(executions.locator('[data-client-order-id="anios-2026-10-13-sell-swks-136"]')).toContainText('Sold 130 SWKS @ $76.18')
  await expect(executions.locator('[data-client-order-id="first"]')).toHaveCount(1)
  await expect(executions.locator('[data-client-order-id="second"]')).toHaveCount(1)
  await expect(executions.locator('[data-client-order-id^="invalid-"]')).toHaveCount(0)
  await page.getByRole('button', {name: 'Stocks', exact: true}).click()
  for (const ticker of ['STX', 'SWKS', 'SAME']) {
    await page.getByRole('button', {name: ticker, exact: true}).click()
    const chart = page.getByRole('region', {name: `${ticker} price chart`, exact: true})
    await chart.getByRole('checkbox', {name: 'Actual paper executions', exact: true}).check()
    const list = chart.getByLabel(`${ticker} actual paper executions`, {exact: true})
    await expect(list.locator('li')).toHaveCount(ticker === 'SAME' ? 2 : 1)
    if (ticker !== 'SAME') await expect(list.locator('time')).toHaveAttribute('datetime', originals.find(fill => fill.symbol === ticker)!.filled_at)
    await expect(chart.getByRole('checkbox', {name: 'Model-only research fills', exact: true})).not.toBeChecked()
    await page.getByRole('button', {name: 'Close', exact: true}).click()
    await expect(table.getByLabel(`${ticker} strategy intent`, {exact: true})).toHaveText('—')
  }
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
