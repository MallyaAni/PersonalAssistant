import {expect, test, type Page} from '@playwright/test'

const session = '2026-09-24'
const written = '2026-09-24T00:00:00Z'
const at = '2026-09-24T14:00:00Z'
const until = '2026-09-24T14:15:00Z'

// Exercise the complete desk with deterministic account, market and recommendation responses.
async function setup(page: Page, open = true, missingEntry = false, paused = false) {
  const errors: string[] = []
  const requests: Record<string, unknown>[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => errors.push(request.url()))
  await page.clock.install({time: new Date(at)})
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let json: unknown = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: 'ani.mallya', is_admin: true, desk_write: true}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {
      session, written, regime: {exposure: 1, flags: []},
      grades: Object.fromEntries(['AAPL', 'NVDA', 'MSFT'].map(ticker => [ticker, {grade: 'A', score: 1, votes: 3, stances: {}, ranks: {}, headline: '', reason: ''}])),
      book: [{ticker: 'AAPL', weight: .05, grade: 'A'}], actions: [], briefs: {},
    }, sessions: [session], event_policy: paused ? {enabled: true} : undefined,
      event_status: paused ? {planning_paused: true, active: true, stale: false, status: 'reduction pending'} : undefined}
    else if (path.endsWith('/holdings')) json = {holdings: [{ticker: 'NVDA', shares: 10, entry_price: 80, entry_date: session}]}
    else if (path.endsWith('/live')) json = {as_of: at, data_at: at, market_status: {exchange: 'XNYS', as_of: at, session, calendar_known: true, is_session: true, open, phase: open ? 'regular' : 'post-market'}, quotes: {AAPL: {symbol: 'AAPL', last: 100, bar: at, as_of: at}}, technical: {}, technical_detail: {}}
    else if (path.endsWith('/mine')) {
      const body = route.request().postDataJSON() as Record<string, unknown>
      requests.push(body)
      json = {session, rows: [], grades_live: {}, decisions: {session, written, equity: 100000, holdings: {}, rows: {
        AAPL: {action: open ? 'Buy' : 'Hold', strategy_action: 'Buy', executable: open, blocker: open ? null : 'Market closed', reason: 'Support holds within the entry zone', move_weight: open ? .02 : 0, strategy_move_weight: .02, target_weight: .05, current_weight: 0, valid_until: open ? until : null, risk_plan: {status: 'available', basis: 'Same completed bar', entry: 100, reference_support: 95, reference_resistance: 110, risk_pct: 5, reward_pct: 10, reward_risk_ratio: 2, risk_budget_pct: body.risk_budget_pct ?? null, max_add_weight: .1, reason: 'Support and resistance bound the entry scenario'}},
        NVDA: {action: 'Sell', strategy_action: 'Sell', executable: true, reason: 'Exit condition confirmed', move_weight: -.01, strategy_move_weight: -.01, valid_until: until},
        MSFT: {action: 'Hold', strategy_action: 'Hold', executable: false, reason: 'Price is above the entry zone', entry_status: missingEntry ? 'unavailable' : 'available', entry_reason: missingEntry ? 'Entry data unavailable · Missing 20-session reference' : null, move_weight: 0, valid_until: until},
      }}}
    } else if (path.endsWith('/personal-history')) json = {receipts: [], has_more: false}
    else if (path.endsWith('/entries')) json = {session, rows: []}
    else if (path.endsWith('/intraday')) json = {session, rows: [], top_buys: [], changed: []}
    else if (path.endsWith('/paper')) json = {reason: 'unavailable'}
    await route.fulfill({json})
  })
  await page.goto('/#desk')
  return {errors, requests}
}

// Keep the primary board small while preserving evidence, account separation and the reason for waiting.
test('five columns show recommendations and expose diagnostics only on request', async ({page}) => {
  const {errors} = await setup(page)
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const headers = board.locator('thead tr').last().getByRole('columnheader')
  await expect(page.locator('details[aria-label="Strategy details"]')).not.toHaveAttribute('open', '')
  await expect(headers).toHaveCount(5)
  await expect(headers).toHaveText(['#', /Stock/, /Action/, 'Size', 'Reason'])
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toHaveText('2.0% of account')
  await expect(board.getByLabel('MSFT size')).toHaveText('—')
  await expect(board).toContainText('Price is above the entry zone')
  await expect(board.getByLabel('AAPL grade', {exact: true})).toHaveCount(0)
  await page.getByRole('button', {name: 'details for AAPL', exact: true}).click()
  await expect(board.getByLabel('AAPL grade', {exact: true})).toContainText('A')
  await expect(board.getByLabel('AAPL risk and reward')).toContainText('2.00:1')
  await expect(board.getByLabel('AAPL risk and reward')).toContainText('not forecasts or guaranteed stops')
  await expect(board.getByLabel('AAPL recorded personal position')).toContainText('None recorded')
  await expect(board.getByLabel('AAPL paper position')).toContainText('Unavailable')
  await page.setViewportSize({width: 390, height: 844})
  if (await page.getByRole('button', {name: 'Hide Sidebar'}).isVisible()) await page.mouse.click(380, 500)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await board.scrollIntoViewIfNeeded()
  const reason = board.getByLabel('AAPL mobile reason', {exact: true})
  await expect(reason).toBeVisible()
  await expect(reason).toBeInViewport()
  await expect(reason).toContainText('Support holds within the entry zone')
  await page.screenshot({path: '/tmp/simple-actions-mobile.png', fullPage: true})
  expect(errors).toEqual([])
})

// A closed market retains the stock recommendation without an executable trade size.
test('closed-market recommendation is explicit and cannot advertise a trade size', async ({page}) => {
  const {errors} = await setup(page, false)
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  await expect(board).toContainText('Market closed')
  expect(errors).toEqual([])
})

// Risk is unset until explicitly confirmed and travels only in the personal planning request body.
test('risk budget is optional and applying it refreshes personal planning', async ({page}) => {
  const {errors, requests} = await setup(page)
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  expect(requests[0]).not.toHaveProperty('risk_budget_pct')
  await page.getByLabel('Risk per position (%)', {exact: true}).fill('0.5')
  await page.getByRole('button', {name: 'Apply', exact: true}).click()
  await expect.poll(() => requests.at(-1)?.risk_budget_pct).toBe(.5)
  await page.getByRole('button', {name: 'details for AAPL', exact: true}).click()
  await expect(page.getByLabel('AAPL risk and reward')).toContainText('Risk budget 0.5%')
  await page.getByLabel('Risk per position (%)', {exact: true}).fill('')
  await page.getByRole('button', {name: 'Apply', exact: true}).click()
  await expect.poll(() => requests.at(-1)?.risk_budget_pct).toBeUndefined()
  expect(errors).toEqual([])
})

// Missing entry evidence is visible as unavailable rather than a confident neutral stock opinion.
test('Hold explains missing entry evidence without manufacturing a buy or size', async ({page}) => {
  const {errors} = await setup(page, true, true)
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('MSFT strategy intent')).toHaveText('Hold')
  await expect(board).toContainText('Entry data unavailable · Missing 20-session reference')
  await expect(board.getByLabel('MSFT size')).toHaveText('—')
  expect(errors).toEqual([])
})

// Collapsing explanatory sections never conceals a current portfolio pause.
test('strategy details start collapsed while active trading restrictions remain visible', async ({page}) => {
  const {errors} = await setup(page, true, false, true)
  const details = page.locator('details[aria-label="Strategy details"]')
  await expect(details).not.toHaveAttribute('open', '')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByRole('row').filter({has: page.getByRole('button', {name: 'AAPL', exact: true})})).toContainText('FOMC cycle: regular trading paused')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  await details.locator(':scope > summary').click()
  await expect(page.getByLabel('FOMC exposure policy')).toContainText('reduction pending')
  expect(errors).toEqual([])
})
