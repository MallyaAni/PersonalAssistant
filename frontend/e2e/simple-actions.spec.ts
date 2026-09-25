import {expect, test, type Page} from '@playwright/test'

const session = '2026-09-24'
const written = '2026-09-24T00:00:00Z'
const at = '2026-09-24T14:00:00Z'
const until = '2026-09-24T14:15:00Z'

// Exercise the complete desk with deterministic account, market and recommendation responses.
async function setup(page: Page, open = true, missingEntry = false, paused = false, beforeNavigate?: () => Promise<void>) {
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
        MSFT: {action: 'Hold', strategy_action: 'Hold', executable: false, reason: 'Price is above the entry zone', blocker: 'Market closed', entry_status: missingEntry ? 'unavailable' : 'available', entry_reason: missingEntry ? 'Entry data unavailable · Missing 20-session reference' : null, move_weight: 0, valid_until: until},
      }}}
    } else if (path.endsWith('/personal-history')) json = {receipts: [], has_more: false}
    else if (path.endsWith('/entries')) json = {session, rows: []}
    else if (path.endsWith('/intraday')) json = {session, rows: [], top_buys: [], changed: []}
    else if (path.endsWith('/paper')) json = {reason: 'unavailable'}
    await route.fulfill({json})
  })
  if (beforeNavigate) await beforeNavigate()
  await page.goto('/#desk')
  return {errors, requests}
}

// Keep the primary board small while preserving evidence, account separation and the reason for waiting.
test('visible grades and concise actions expose diagnostics only on request', async ({page}) => {
  const {errors} = await setup(page)
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  const headers = board.locator('thead tr').last().getByRole('columnheader')
  await expect(page.locator('details[aria-label="Strategy details"]')).not.toHaveAttribute('open', '')
  await expect(headers).toHaveCount(5)
  await expect(headers).toHaveText(['#', /Stock/, /Grade/, /Action/, /Size/])
  await expect(board.getByLabel('AAPL displayed grade', {exact: true})).toHaveText('AClose')
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toHaveText('2.0% of account')
  await expect(board.getByLabel('MSFT size')).toHaveText('—')
  await expect(board).not.toContainText('Price is above the entry zone')
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
  const reason = board.getByLabel('AAPL decision reason', {exact: true})
  await expect(reason).toBeVisible()
  await expect(reason).toBeInViewport()
  await expect(reason).toContainText('Support holds within the entry zone')
  await page.screenshot({path: '/tmp/simple-actions-mobile.png', fullPage: true})
  expect(errors).toEqual([])
})

// A regular-session restriction retains intent and never implies all venues are closed.
test('regular-session restriction is explicit and cannot advertise a trade size', async ({page}) => {
  const {errors} = await setup(page, false)
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  for (const ticker of ['AAPL', 'NVDA']) {
    const readiness = board.getByLabel(`${ticker} execution readiness`, {exact: true})
    await expect(readiness).toHaveText('Regular-session execution blocked')
    await expect(readiness).toHaveAttribute('title', 'Regular-session execution is blocked; the session is closed or its clock is unavailable')
  }
  await expect(board).not.toContainText('Market closed')
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
  await expect(board).toContainText('Data missing')
  await page.getByRole('button', {name: 'details for MSFT', exact: true}).click()
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
  await expect(board.getByRole('row').filter({has: page.getByRole('button', {name: 'AAPL', exact: true})})).toContainText('FOMC pause')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  await details.locator(':scope > summary').click()
  await expect(page.getByLabel('FOMC exposure policy')).toContainText('reduction pending')
  expect(errors).toEqual([])
})

// Missing exchange observations stay visible without drawing a valid band or changing the action.
test('ticker panels disclose chart gaps and retain the board decision', async ({page}) => {
  const {errors} = await setup(page, true, true)
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
  await page.getByRole('button', {name: 'MSFT', exact: true}).click()
  await expect(page.getByLabel('MSFT decision reason', {exact: true})).toContainText('Entry data unavailable')
  const chart = page.getByLabel('MSFT price chart', {exact: true})
  await expect(chart.getByLabel('Chart data quality')).toContainText('Chart data incomplete · 1 missing session')
  await chart.getByLabel('Chart data quality').locator('summary').click()
  await expect(chart.getByLabel('Chart data quality')).toContainText('2026-09-22')
  await expect(chart).not.toContainText('Band upper')
  await expect(chart).not.toContainText('could not be drawn')
  await chart.getByRole('button', {name: 'W', exact: true}).click()
  await expect(chart).toContainText('incomplete candle')
  await expect(chart).not.toContainText('Weekly overlays include the forming week')
  expect(errors).toEqual([])
})

// Rank valid grades before action and executable size, and revert expired live grades honestly.
test('default ranking follows grade action size and reranks expired intraday grades', async ({page}) => {
  const grades = {
    NVDA: {grade: 'B', score: .99}, AAPL: {grade: 'A+', score: .9},
    MSFT: {grade: 'A+', score: .8}, AMZN: {grade: 'A+', score: .7}, AMD: {grade: 'A', score: 1},
  }
  const {errors} = await setup(page, true, false, false, async () => {
  await page.route('**/desk', route => route.fulfill({json: {latest: {
    session, written, regime: {exposure: 1, flags: []}, grades,
    book: [{ticker: 'AMZN', weight: .9, grade: 'A+'}], actions: [], briefs: {},
  }, sessions: [session]}}))
  await page.route('**/desk/mine', route => route.fulfill({json: {
    session, rows: [], grade_valid_until: {NVDA: until}, grades_live: {NVDA: {grade_live: 'A+', score_live: .95}},
    decisions: {session, written, equity: 100000, holdings: {}, rows: {
      NVDA: {action: 'Buy', strategy_action: 'Buy', executable: true, move_weight: .04, valid_until: until, reason: 'Entry confirmed'},
      AAPL: {action: 'Buy', strategy_action: 'Buy', executable: true, move_weight: .02, valid_until: until, reason: 'Entry confirmed'},
      MSFT: {action: 'Sell', strategy_action: 'Sell', executable: true, move_weight: -.08, valid_until: until, reason: 'Exit confirmed'},
      AMZN: {action: 'Hold', strategy_action: 'Hold', executable: false, move_weight: 0, target_weight: .9, valid_until: until, reason: 'No entry'},
      AMD: {action: 'Buy', strategy_action: 'Buy', executable: true, move_weight: .5, valid_until: until, reason: 'Entry confirmed'},
    }},
  }}))
  })
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  // Read only stock rows so expanded details and the cash footer cannot affect ranking.
  const order = () => board.locator('tbody tr').filter({has: page.getByLabel(/displayed grade$/)}).locator('td:nth-child(2) button').allTextContents()
  await expect(board.getByLabel('NVDA displayed grade', {exact: true})).toHaveText('A+Intraday')
  expect(await order()).toEqual(['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AMD'])
  await board.getByRole('button', {name: 'Size', exact: true}).click()
  expect(await order()).toEqual(['AMD', 'MSFT', 'NVDA', 'AAPL', 'AMZN'])
  await page.getByRole('button', {name: 'Reset ranking', exact: true}).click()
  expect(await order()).toEqual(['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AMD'])
  await page.clock.fastForward(16 * 60 * 1000)
  await expect(board.getByLabel('NVDA displayed grade', {exact: true})).toHaveText('BClose')
  expect(await order()).toEqual(['AAPL', 'MSFT', 'AMZN', 'AMD', 'NVDA'])
  await expect(board.getByLabel('NVDA size', {exact: true})).toHaveText('—')
  expect(errors).toEqual([])
})
