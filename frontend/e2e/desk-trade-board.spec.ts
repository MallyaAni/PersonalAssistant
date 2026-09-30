import {readFileSync} from 'node:fs'
import {expect, test, type Page} from '@playwright/test'

// The board is the paper account's own orders, worded once by the backend:
// `fixtures/paper_plan.json` is produced by `intraday_orders.board_orders`
// (`fixtures/paper_plan.py`), so these tests assert the sentences `/desk/paper`
// really sends. What has to hold for a trader: every row says what (BUY, SELL,
// TRIM or HOLD), how big (shares, dollars, share of the account), why, and when
// or what happened; a held name without an order says why it has none; the
// ticker panel and its chart say exactly what the board says.
const fixture = JSON.parse(readFileSync(new URL('./fixtures/paper_plan.json', import.meta.url), 'utf8'))
const USER = 'ani.mallya'
const SESSION = '2026-09-30'
const WRITTEN = '2026-09-30T23:46:00Z'
const THURSDAY = '2026-10-01T14:20:00Z'
const WEDNESDAY = '2026-10-01T00:15:00Z'
const BOOK = ['AAOI', 'COHR', 'HPE', 'LITE', 'MDB', 'MU', 'NTAP', 'SMCI', 'SNDK', 'STX', 'SWKS', 'ALAB']
const OTHER: Record<string, string> = {NVDA: 'B', ANET: 'B', ADBE: 'B', CRM: 'C', SNOW: 'B'}

// The nightly record for the scenario: twelve A/A+ names at 1/12, the rest B or C.
const record = () => {
  const grades: Record<string, object> = {}
  for (const ticker of BOOK) grades[ticker] = {grade: ticker === 'SNDK' || ticker === 'NTAP' ? 'A+' : 'A', votes: 3, stances: {fundamental: 1, technical: 1, sentiment: 1, value: 0, rotation: 0}, ranks: {}, score: 1, side: 'ai', headline: `${ticker}: growth and trend lead the book`, reason: '+ Fundamental: revenue growth top of book\n+ Technical: 6-month momentum high in book', reads: {}}
  for (const [ticker, grade] of Object.entries(OTHER)) grades[ticker] = {grade, votes: 0, stances: {fundamental: 0, technical: -1}, ranks: {}, score: 0, side: 'ai', headline: `${ticker}: trend turned`, reason: '− Technical: below its 50-day average', reads: {}}
  const weights = Object.fromEntries([...BOOK.map(t => [t, 1 / 12]), ...Object.keys(OTHER).map(t => [t, 0])])
  const closes: Record<string, number> = Object.fromEntries(fixture.positions.map((p: {symbol: string; current_price: number}) => [p.symbol, p.current_price]))
  return {
    session: SESSION, written: WRITTEN, provenance: {rule: {inputs: []}, data: {}},
    targets: {policy: 'graded-equal-weight/4', weights},
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades, book: [], briefs: {}, paper: null,
    actions: Object.keys(grades).map(ticker => ({ticker, action: 'hold', grade: (grades[ticker] as {grade: string}).grade, last_close: closes[ticker] ?? 50, rejecting_band: ticker === 'ALAB'})),
  }
}

// Route every desk read to the scenario at `now`; any write or unknown read fails the test.
async function scenario(page: Page, {now, plan}: {now: string; plan: 'thursday' | 'wednesday'}) {
  const errors: string[] = []
  const writes: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (message.type() === 'error') errors.push(message.text())})
  page.on('requestfailed', request => {if (request.url().includes('/market/')) errors.push(request.url())})
  await page.clock.install({time: new Date(now)})
  const open = plan === 'thursday'
  const market = {exchange: 'XNYS', as_of: now, session: open ? '2026-10-01' : '2026-09-30', calendar_known: true, is_session: true, open, phase: open ? 'open' : 'post-market', opens_at: open ? '2026-10-01T13:30:00Z' : '2026-09-30T13:30:00Z', closes_at: open ? '2026-10-01T20:00:00Z' : '2026-09-30T20:00:00Z'}
  const bar = open ? '2026-10-01T14:00:00Z' : '2026-09-30T19:45:00Z'
  const quotes = Object.fromEntries(fixture.positions.map((p: {symbol: string; current_price: number}) => [p.symbol, {symbol: p.symbol, last: p.current_price, open: p.current_price, high: p.current_price, low: p.current_price, bar, as_of: now}]))
  // The balancer's structure beside the quotes: the levels the operator reads
  // and what the session's first bar did at them. The bar's close is the
  // price's instant; the age is against the balancer's own clock.
  const priced = open ? '2026-10-01T14:15:00Z' : '2026-09-30T20:00:00Z'
  const structure = {
    // A name under both levels, its 21-EMA falling, no tag today.
    NVDA: {ema_21: 238.7, ema_21_slope_5: -0.031, high_20: 266.5, level_tag: null, price_as_of: priced, price_age_seconds: 300},
    // The first bar reached the 21-EMA from below and closed back under it, the third session at it.
    AAOI: {ema_21: 104.4, ema_21_slope_5: 0.012, high_20: 116.9, level_tag: {level: 'ema_21', price: 104.4, first_bar_high: 104.1, first_bar_close: 102.8, rejected: true, consecutive_sessions: 3}, price_as_of: priced, price_age_seconds: 300},
    // The first bar went through the 20-day high and held above it: no flag.
    HPE: {ema_21: 58.2, ema_21_slope_5: 0.004, high_20: 61.3, level_tag: {level: 'high_20', price: 61.3, first_bar_high: 61.9, first_bar_close: 61.6, rejected: false, consecutive_sessions: 1}, price_as_of: priced, price_age_seconds: 300},
    // A name the store could not read: no levels, only the price's age.
    SMCI: {ema_21: null, ema_21_slope_5: null, high_20: null, level_tag: null, price_as_of: priced, price_age_seconds: 300},
  }
  const paper = {user_id: USER, as_of: now, equity: fixture.equity, cash: fixture.cash, day_pl: 864, day_pl_pct: .0087, pl_pct: .0002, positions: fixture.positions, orders: [], activity: {session: '2026-10-01', complete: true, fills: []}, plan: fixture[plan]}
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const base = `/api/v1/market/${USER}/desk`
    if (request.method() !== 'GET') {
      writes.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-10-02T00:00:00Z', is_admin: true, desk_access: true, desk_write: true}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest: record(), sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = {as_of: now, data_at: bar, stale: false, market_status: market, quotes, technical: {}, technical_detail: {}, structure}
    else if (url.pathname === `${base}/session-prices`) json = {session: open ? 'regular' : 'post-market', as_of: now, signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/paper`) json = paper
    else if (url.pathname === `${base}/paper/history`) json = {user_id: USER, rows: []}
    else if (url.pathname.startsWith(`${base}/history/`)) json = {user_id: USER, ticker: url.pathname.split('/').pop(), asof: SESSION, horizon: 20, policy: 'graded-equal-weight/4', rows: [], fills: [], backtest: null}
    else if (url.pathname.startsWith(`${base}/chart/`)) json = {ticker: url.pathname.split('/').pop(), timeframe: 'daily', bars: [], overlays: {}, levels: {}}
    else if (url.pathname.startsWith(`${base}/live/read/`) || url.pathname.startsWith(`${base}/earnings/`)) json = {read: null}
    else { errors.push(`Unexpected request ${url.pathname}`); json = {} }
    return route.fulfill({json})
  })
  return {errors, writes}
}

// The row for one name, found by its ticker button.
const rowOf = (page: Page, ticker: string) =>
  page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('row').filter({has: page.getByRole('button', {name: ticker, exact: true})})

// In the session, every order reads what, how big, why and where it is, in the
// backend's own words; a name with two orders adds them up.
test('the board shows the paper account’s orders mid-session', async ({page}, testInfo) => {
  await page.setViewportSize({width: 1440, height: 1000})
  const diagnostics = await scenario(page, {now: THURSDAY, plan: 'thursday'})
  await page.goto('/#desk')
  const board = page.getByRole('region', {name: 'Stocks and cash'})
  await expect(board).toContainText('the paper account’s orders')
  await expect(page.getByLabel('Paper account summary')).toContainText('$100,018 paper account')
  await expect(page.getByLabel('Paper account summary')).toContainText('10 orders (8 buys, 2 sells)')
  await expect(page.getByLabel('Execution rule')).toContainText('The paper account sends exactly the orders below.')
  // An exit waiting for its pop.
  await expect(page.getByLabel('NVDA strategy intent')).toHaveText('SELL')
  await expect(page.getByLabel('NVDA action status')).toHaveText('Exit: the grade fell to B')
  await expect(page.getByLabel('NVDA size')).toContainText('67 sh')
  await expect(page.getByLabel('NVDA size')).toContainText('$15,350 · 15.3%')
  await expect(page.getByLabel('NVDA order status')).toContainText('Waiting for $232.30 or the close (3:30 PM window)')
  await expect(page.getByLabel('NVDA order status')).toContainText('Today · 15-min close ≥ $232.30 (1% over the $230.00 open), else at the close')
  // A buy whose level was reached on this candle.
  await expect(page.getByLabel('AAOI strategy intent')).toHaveText('BUY')
  await expect(page.getByLabel('AAOI order status')).toContainText('Level hit: the 10:15 AM close ($99.60) · sending now')
  // Two orders on one name add up.
  await expect(page.getByLabel('HPE size')).toContainText('9 sh')
  await expect(page.getByLabel('HPE action status')).toHaveText('Finish last session’s buy (cash was short) + Reinvest an exit’s proceeds'.replaceAll('’', "'"))
  await expect(page.getByLabel('HPE order status')).toContainText('Sent 10:16 AM · market order')
  // A filled exit.
  await expect(page.getByLabel('ANET order status')).toContainText('Sold 32 @ $205.10 · 9:46 AM')
  // A held name with no order says why.
  await expect(page.getByLabel('NTAP strategy intent')).toHaveText('HOLD')
  await expect(page.getByLabel('NTAP action status')).toHaveText('Above its 8.3% target · trimmed at the reset in 18 sessions')
  await expect(page.getByLabel('NTAP position')).toContainText('78 sh · 16.5%')
  await expect(page.getByLabel('NTAP size')).toHaveText('—')
  // No personal-planner words anywhere on the board.
  for (const word of ['Blocked', 'Strategy: buy', 'Cash needed', 'Unavailable']) await expect(board).not.toContainText(word)
  await board.screenshot({path: testInfo.outputPath('board-thursday.png')})
  await page.screenshot({path: testInfo.outputPath('page-thursday.png'), fullPage: true})
  expect(diagnostics.writes).toEqual([])
  expect(diagnostics.errors).toEqual([])
})

// After the nightly, every order is planned for the next session with its rule.
test('the evening board shows tomorrow’s orders as planned', async ({page}, testInfo) => {
  await page.setViewportSize({width: 1440, height: 1000})
  const diagnostics = await scenario(page, {now: WEDNESDAY, plan: 'wednesday'})
  await page.goto('/#desk')
  await expect(page.getByLabel('SMCI strategy intent')).toHaveText('BUY')
  await expect(page.getByLabel('SMCI order status')).toContainText('Planned')
  await expect(page.getByLabel('SMCI order status')).toContainText('Thu Oct 1 · 15-min close 1% under the open, else at the close')
  await expect(page.getByLabel('NVDA order status')).toContainText('Thu Oct 1 · 15-min close 1% over the open, else at the close')
  await expect(page.getByLabel('Today')).toContainText('Paper orders: 10 planned.')
  await page.getByRole('region', {name: 'Stocks and cash'}).screenshot({path: testInfo.outputPath('board-wednesday.png')})
  expect(diagnostics.writes).toEqual([])
  expect(diagnostics.errors).toEqual([])
})

// The views narrow the board to the orders or widen it to every graded name,
// and an A name the account does not hold says why it has no order.
test('views, search and your account size', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 1000})
  const diagnostics = await scenario(page, {now: THURSDAY, plan: 'thursday'})
  await page.goto('/#desk')
  const view = page.getByRole('group', {name: 'Board view'})
  await expect(view.getByRole('button', {name: /Orders 8/})).toBeVisible()
  await expect(view.getByRole('button', {name: /Portfolio 13/})).toHaveAttribute('aria-pressed', 'true')
  await view.getByRole('button', {name: /Orders/}).click()
  await expect(rowOf(page, 'NTAP')).toHaveCount(0)
  await expect(rowOf(page, 'SMCI')).toHaveCount(1)
  await view.getByRole('button', {name: /All names/}).click()
  await expect(page.getByLabel('ALAB action status')).toHaveText('In the book · no buy while its daily rejects the upper band')
  await expect(page.getByLabel('CRM action status')).toHaveText('Not in the book (grade C)')
  await page.getByLabel('Search the stock list').fill('sw')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('row')).toHaveCount(2)
  await page.getByLabel('Search the stock list').fill('')
  // Your account at $50,000: NVDA's 15.3% is 33 shares at $229.10.
  await page.getByLabel('Your account size').fill('50000')
  await page.getByLabel('Your account size').press('Enter')
  await expect(page.getByLabel('NVDA size')).toContainText('you 33 sh')
  expect(diagnostics.writes).toEqual([])
  expect(diagnostics.errors).toEqual([])
})

// The details under a row and the full panel say exactly what the row says.
test('the row details and the ticker panel repeat the board’s words', async ({page}, testInfo) => {
  await page.setViewportSize({width: 1440, height: 1000})
  const diagnostics = await scenario(page, {now: THURSDAY, plan: 'thursday'})
  await page.goto('/#desk')
  await page.getByRole('button', {name: 'details for HPE'}).click()
  const orders = page.getByRole('region', {name: 'HPE orders'})
  await expect(orders).toContainText('BUY 6 sh')
  await expect(orders).toContainText('BUY 3 sh')
  await expect(orders).toContainText("Finish last session's buy (cash was short)")
  await expect(page.getByRole('region', {name: 'HPE position'})).toContainText('61 sh')
  await expect(page.getByRole('region', {name: 'HPE grade'})).toContainText('Grade A')
  await page.getByRole('region', {name: 'Stocks and cash'}).screenshot({path: testInfo.outputPath('board-details.png')})
  await page.getByRole('button', {name: 'HPE', exact: true}).click()
  const panel = page.getByRole('dialog', {name: 'HPE history'})
  const card = panel.getByRole('region', {name: 'HPE paper order'})
  await expect(card).toContainText('BUY')
  await expect(card).toContainText('9 sh')
  await expect(card).toContainText('Sent 10:16 AM · market order')
  await panel.screenshot({path: testInfo.outputPath('panel-hpe.png')})
  expect(diagnostics.writes).toEqual([])
  expect(diagnostics.errors).toEqual([])
})

// The Levels column is the structure the desk does not act on: each row names
// the 21-EMA and the 20-day high with the distance from the last price and
// the EMA's slope; a first bar that reached a level from below and closed
// back under it is flagged in plain words with the count of sessions at the
// level; a tag that held is not flagged; a name without levels shows a dash;
// the action cell says how old the price behind the row is; and the ticker
// panel names the same levels its chart draws. No word of it is an
// instruction, and the paper account's order beside it is unchanged.
test('the levels and a rejected first bar are shown, not acted on', async ({page}, testInfo) => {
  await page.setViewportSize({width: 1440, height: 1000})
  const diagnostics = await scenario(page, {now: THURSDAY, plan: 'thursday'})
  await page.goto('/#desk')
  await expect(page.getByLabel('NVDA levels')).toContainText('21-EMA 238.7 (−4.4%) ↓')
  await expect(page.getByLabel('NVDA levels')).toContainText('20-day high 266.5 (−14%)')
  await expect(page.getByLabel('NVDA levels')).not.toContainText('Rejected')
  await expect(page.getByLabel('AAOI levels')).toContainText('21-EMA 104.4 (−3.0%) ↑')
  await expect(page.getByLabel('AAOI levels')).toContainText('20-day high 116.9 (−13%)')
  await expect(page.getByLabel('AAOI level flag')).toHaveText('Rejected at 21-EMA 104.4 · 3rd day')
  await expect(page.getByLabel('HPE levels')).toContainText('21-EMA 58.2 (+6.0%) ↑')
  await expect(page.getByLabel('HPE levels')).toContainText('20-day high 61.3 (+0.7%)')
  await expect(page.getByLabel('HPE level flag')).toHaveCount(0)
  await expect(page.getByLabel('SMCI levels')).toHaveText('—')
  await expect(page.getByLabel('AAOI price age')).toHaveText('as of 10:15 AM, 5 min ago')
  await expect(page.getByLabel('NTAP price age')).toHaveCount(0)
  // The flag is a description, not an instruction, and the order stands as it was.
  expect(await page.getByLabel('AAOI level flag').textContent()).not.toMatch(/buy|sell|trim|hold/i)
  await expect(page.getByLabel('AAOI strategy intent')).toHaveText('BUY')
  await expect(page.getByLabel('AAOI order status')).toContainText('Level hit: the 10:15 AM close ($99.60) · sending now')
  await page.getByRole('region', {name: 'Stocks and cash'}).screenshot({path: testInfo.outputPath('board-levels.png')})
  await page.getByRole('button', {name: 'AAOI', exact: true}).click()
  const panel = page.getByRole('dialog', {name: 'AAOI history'})
  await expect(panel.getByLabel('AAOI board levels')).toHaveText('Dashed lines are the board’s levels: 21-EMA 104.4 · 20-day high 116.9.')
  expect(diagnostics.writes).toEqual([])
  expect(diagnostics.errors).toEqual([])
})

// On a phone the board keeps its words and scrolls inside itself, not the page.
test('the board on a phone', async ({page}, testInfo) => {
  await page.setViewportSize({width: 390, height: 844})
  const diagnostics = await scenario(page, {now: THURSDAY, plan: 'thursday'})
  await page.goto('/#desk')
  await expect(page.getByLabel('NVDA strategy intent')).toHaveText('SELL')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({path: testInfo.outputPath('phone-thursday.png'), fullPage: false})
  expect(diagnostics.errors).toEqual([])
})
