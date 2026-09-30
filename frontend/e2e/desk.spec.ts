import { expect, test, type Page } from '@playwright/test'
import type { DeskForwardEvidence } from '../src/services/api'

// Deterministic browser acceptance for the trading desk page. The desk is the
// operator's own page, so the session is mocked as an operator and every desk
// endpoint is answered from fixture shapes written from the real record — the
// curve, the changes, the per-name history and the autopsy are all read-only
// views of files the nightly run wrote, so the browser never needs a runtime.

const USER = 'ani.mallya'

// Open the optional strategy diagnostics only for cases that inspect their evidence.
async function strategyDetails(page: Page) {
  const details = page.locator('details[aria-label="Strategy details"]')
  if (await details.getAttribute('open') === null) await details.locator(':scope > summary').click()
}

// Historical research is disclosed separately from actual paper-account balances.
async function simulationDetails(page: Page) {
  const details = page.locator('details[aria-label="Historical simulation"]')
  if (await details.getAttribute('open') === null) await details.locator(':scope > summary').click()
  return details
}

// Open a stock's row details (its orders, paper position and grade) without changing anything.
async function stockDetails(page: Page, ticker: string) {
  const toggle = page.getByRole('button', {name: `details for ${ticker}`, exact: true})
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
  return page.getByLabel(`${ticker} details`, {exact: true})
}

// Widen the board from the paper account's book to every graded name.
async function allNames(page: Page) {
  await page.getByRole('group', {name: 'Board view'}).getByRole('button', {name: /All names/}).click()
}

// The paper account's plan for the fixtures: one planned buy of NVDA, the reset 18 sessions out.
const NVDA_PLANNED = {client_order_id: 'NVDA-1', symbol: 'NVDA', side: 'buy', action: 'BUY', qty: 10, price: 130, notional: 1300, weight: 1300 / 104200, leg: 'entry',
  why: 'Grade rose to A', reason: null, timing: 'dip_or_close', decided: '2026-09-08', execute_on: '2026-09-09', open: null, level: null,
  sent_at: null, sent_how: null, filled_qty: null, filled_price: null, filled_at: null,
  state: 'planned', status: 'Planned', when: 'Wed Sep 9 · 15-min close 1% under the open, else at the close'}
const paperPlan = (orders: object[] = [NVDA_PLANNED]) => ({rule: 'dip_or_close', until_rebalance: 18, last_rebalance: '2026-08-12', reason: null, orders})

// Unsupported historical returns stay hidden while the original record remains archived.
test('withholds an unvalidated simulation and explains missing held marks', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const failed: string[] = []
  page.on('requestfailed', request => { if (request.url().includes('/market/')) failed.push(request.url()) })
  await page.route('**/api/v1/conversations/**', route => route.fulfill({json: {messages: [], conversations: []}}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(),
    curve: {backtest: null, backtest_unavailable_reason: 'Historical simulation withheld: this saved curve predates the check for missing prices on held stocks. Its returns need revalidation.'},
  }}))
  await page.goto('/?deskDetails=1#desk')
  await page.locator('summary', {hasText: 'Paper account'}).click()
  await simulationDetails(page)
  await expect(page.getByText('Historical simulation withheld:', {exact: false})).toBeVisible()
  await expect(page.getByText('CAGR', {exact: true})).toHaveCount(0)
  await expect(page.getByRole('img', {name: "The desk's track record against SPY and QQQ"})).toHaveCount(0)
  await expect(page.getByLabel('The desk at a glance')).not.toContainText('vs SPY')
  await expect(page.getByLabel('The desk at a glance')).toContainText('Practice account')
  expect(failed).toEqual([])
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Expanded guidance separates personal allocations from returns and paper accounts.
test('account wording distinguishes allocation from profit and paper from personal', async ({page}, testInfo) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/**', route => route.fulfill({json: {messages: [], conversations: []}}))
  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', {name: 'How to use this page', exact: true}).click()
  await page.locator('summary', {hasText: 'Market risk'}).click()
  await expect(page.getByText('This is not your invested percentage or a claim about available cash;', {exact: false})).toBeVisible()
  await expect(page.getByText('The paper account places exactly these orders. Nothing here touches your own brokerage account.', {exact: false})).toBeVisible()
  await expect(page.getByText(/BUY, SELL and TRIM are the paper account's orders/)).toBeVisible()
  await expect(page.getByText(/HOLD means no order: the position stays/)).toBeVisible()
  await expect(page.getByText('Enter your account size once', {exact: false})).toBeVisible()
  await expect(page.getByText('market-on-close from 3:30 PM ET', {exact: false}).first()).toBeVisible()
  await expect(page.getByRole('button', {name: 'Size', exact: true})).toHaveAttribute('title', /Shares, dollars and share of the paper account/)
  await expect(await stockDetails(page, 'AAPL')).toContainText('Paper position')
  await expect(page.locator('body')).not.toContainText('same whatever you have recorded')
  await expect(page.locator('body')).not.toContainText('24 points a year')
  await page.getByRole('button', {name: 'Research', exact: true}).click()
  await expect(page.getByLabel('What the research accounts are')).toContainText('Personal guidance uses your recorded positions and confirmed cash')
  await page.screenshot({path: testInfo.outputPath('trading-copy-research.png'), fullPage: true})
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Missing index evidence remains visible, and old saved accounting is labelled honestly.
test('benchmark comparison explains unavailable indexes and legacy accounting', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/**', route => route.fulfill({json: {messages: [], conversations: []}}))
  const bench = {
    version: 'strategy-bench/2', sessions: 20, from: '2026-08-01', to: '2026-08-28',
    blocks: [{regime: 'Whole sample', sessions: 20, share: 1, from: '2026-08-01', to: '2026-08-28', rows: [
      {name: 'SPY', total: .02, annual: null, volatility: .15, drawdown: -.01, sharpe: 1},
      {name: 'QQQ', total: null, annual: null, volatility: null, drawdown: null, sharpe: null, unavailable: 'QQQ has a missing adjusted price'},
    ]}],
  }
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest: deskRecord(), strategy_bench: bench}}))
  await page.goto('/#desk')
  await page.getByRole('button', {name: 'Research', exact: true}).click()
  await page.locator('summary', {hasText: 'Strategy benchmarks'}).click()
  await expect(page.getByLabel('Benchmark accounting')).toContainText('funded next-open entry')
  const comparison = page.getByRole('table', {name: 'Whole sample candidates'})
  await expect(comparison).toContainText('Unavailable: QQQ has a missing adjusted price')
  await expect(comparison.getByRole('row').filter({hasText: 'QQQ'})).not.toContainText('0.0%')
  bench.version = 'strategy-bench/1'
  await page.reload()
  await page.getByRole('button', {name: 'Research', exact: true}).click()
  await page.locator('summary', {hasText: 'Strategy benchmarks'}).click()
  await expect(page.getByLabel('Benchmark accounting')).toContainText('Older comparison accounting')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Prospective model accounts are visible separately from the adopted plan and holdings.
test('frozen ML paper comparison shows independent account returns', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET' ? route.fulfill({json: {messages: [], conversations: []}}) : route.fulfill({json: {}}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(), ml_forward: {status: 'Observed frozen policies', session: '2026-09-14',
      observed_at: '2026-09-14T21:00:00Z', accounts: {
        'neural@10bps': {equity: 101000, total_return: .01},
        'SPY@10bps': {equity: 100500, total_return: .005},
      }},
  }}))
  await page.goto('/?deskView=research#desk')
  await page.getByText('ML paper comparison · 2026-09-14', {exact: false}).click()
  const comparison = page.getByLabel('ML forward comparison')
  await expect(comparison).toContainText('no real orders')
  await expect(comparison).toContainText('Updated nightly')
  await expect(comparison).toContainText('known financial/share-unit issues')
  await expect(comparison).toContainText('do not establish superiority over the live strategy')
  await expect(page.getByRole('table', {name: 'ML paper returns'})).toContainText('1.00%')
  await expect(page.getByRole('table', {name: 'ML paper returns'})).toContainText('0.50%')
  await page.evaluate(() => localStorage.removeItem('anios_conversation_id:ani.mallya'))
  await page.reload()
  await page.getByText('ML paper comparison · 2026-09-14', {exact: false}).click()
  await expect(comparison).toContainText('$101,000.00')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// The page says when it is showing an old decision: a record or an ML
// observation missing for the last completed session by the next morning.
test('a late record or observation is named at the top of the page', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET' ? route.fulfill({json: {messages: [], conversations: []}}) : route.fulfill({json: {}}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(), record_status: {expected: '2026-09-14', due_at: '2026-09-15T07:00-04:00',
      record: {session: '2026-09-11', status: 'late'}, ml_forward: {session: null, status: 'late'}},
  }}))
  await page.goto('/#desk')
  const status = page.getByRole('status', {name: 'Record status'})
  await expect(status).toContainText('No decision record for 2026-09-14 yet')
  await expect(status).toContainText('2026-09-11 decision')
  await expect(status).toContainText('quotes and account data have separate timestamps')
  await expect(status).not.toContainText('Everything below')
  await expect(status).toContainText('have not observed 2026-09-14')
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(), record_status: {expected: '2026-09-14', due_at: '2026-09-15T07:00-04:00',
      record: {session: '2026-09-14', status: 'current'}, ml_forward: {session: '2026-09-11', status: 'pending'}},
  }}))
  await page.evaluate(() => localStorage.removeItem('anios_conversation_id:ani.mallya'))
  await page.reload()
  await expect(page.getByRole('table').first()).toBeVisible()
  await expect(page.getByRole('status', {name: 'Record status'})).toHaveCount(0)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A decision whose prose failed is still the decision: the page says the
// briefs and reads are unavailable and shows the deterministic reads.
test('a decision with unavailable prose is shown as the decision', async ({page}) => {
  const latest = {...deskRecord(), prose_state: 'unavailable', prose_status: 'unavailable: brief SNDK: TimeoutError(\'runtime blocked\')'}
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.goto('/#desk')
  const status = page.getByRole('status', {name: 'Record status'})
  await expect(status).toContainText('Model-written briefs and reads')
  await expect(status).toContainText('unavailable')
  await expect(page.getByRole('table').first()).toBeVisible()
})

// The nightly's actual timeout status, when the model kept sending bytes past
// the deadline and the enrichment was terminated, is shown as a warning.
test('a decision whose prose timed out is shown with the timeout status', async ({page}) => {
  const latest = {...deskRecord(), prose_state: 'timed_out', prose_status: 'timed out: timed out after 45 min: 3 of 12 written; the request in flight was terminated'}
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.goto('/#desk')
  const status = page.getByRole('status', {name: 'Record status'})
  await expect(status).toContainText('Model-written briefs and reads')
  await expect(status).toContainText('timed out after 45 min: 3 of 12 written; the request in flight was terminated')
  await expect(status).toContainText('The decision and its deterministic reads stand')
  await expect(page.getByRole('table').first()).toBeVisible()
})

// Prose from an earlier run of the same session - a forced rerun killed after
// the record was saved and before the prose was rewritten - is not this
// decision's. The page must name the reason it was refused, not claim that
// nothing was written.
test('a decision whose stored prose predates it is shown as absent with the reason', async ({page}) => {
  const latest = {...deskRecord(), prose_state: 'absent', prose_status: 'absent: prose on file predates this decision'}
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.goto('/#desk')
  const status = page.getByRole('status', {name: 'Record status'})
  await expect(status).toContainText('Model-written briefs and reads')
  await expect(status).toContainText('prose on file predates this decision')
  await expect(status).toContainText('The decision and its deterministic reads stand')
  await expect(status).not.toContainText('have not been written yet')
  await expect(page.getByRole('table').first()).toBeVisible()
})

// A known empty account holds all its capital in USD while additions are paused.
test('empty paused account shows USD at 100 percent', async ({page}) => {
  await page.route('**/desk/holdings', route => route.fulfill({json: {holdings: []}}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(), event_status: {active: true, stale: false, planning_paused: true},
    board_paper: {version: 'board-paper/1', started_at: new Date().toISOString(), as_of: new Date().toISOString(), initial_capital: 100000, cash: 100000, equity: 100000, sequence: 0, status: 'Started in USD'},
  }}))
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {as_of: '2026-09-08T20:00:00Z', equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], plan: paperPlan([])}}))
  await page.goto('/#desk')
  // The account's money reads above the board: all of it cash, no orders.
  await expect(page.getByLabel('Paper account summary')).toContainText('$100,000 paper account')
  await expect(page.getByLabel('Paper account summary')).toContainText('cash $100,000 (100.0%)')
  await expect(page.getByLabel('Paper account summary')).toContainText('no orders')
  await page.goto('/?deskView=research#desk')
  await expect(page.getByLabel('Board simulation')).toContainText('USD 100.0%')
  await expect(page.getByLabel('Board simulation')).toContainText('0.00% since start')
})

// A ticker exposes original recommendations without confusing stock moves with fills.
test('ticker opens original recommendation timeline before detailed analysis', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/desk/history/AAPL', route => route.fulfill({json: {
    ticker: 'AAPL', rows: [], backtest: null, recommendations: {
      status: 'available', outcomes: {status: 'awaiting_daily_validation'}, invalid_archives: 0,
      older_records_not_shown: false, observations: [
        {id: 'new', recorded_at: '2026-09-14T18:30:24Z', bar: '2026-09-14T18:15:00Z',
          grade: 'A+', allocation: null, allocation_change: null, event_paused: true,
          entry_state: 'dip', price: 110, stock_total_return: null, version: 'policy/2', policy_sha256: 'abcdefgh'},
        {id: 'old', recorded_at: '2026-09-11T18:30:24Z', bar: '2026-09-11T18:15:00Z',
          grade: 'A', allocation: .2, allocation_change: .1, event_paused: false,
          entry_state: 'dip', price: 100, stock_total_return: null, version: 'policy/1', policy_sha256: '12345678'},
      ],
    },
  }}))
  await page.goto('/#desk')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
  const fold = page.locator('details').filter({has: page.locator('summary', {hasText: 'Score, log & backtest'})})
  await expect(fold).not.toHaveAttribute('open', '')
  await fold.locator(':scope > summary').click()
  await expect(fold).toHaveAttribute('open', '')
  const timeline = page.getByRole('region', {name: 'Recorded research readings'})
  await expect(timeline.getByRole('table')).toBeVisible()
  const pausedReading = timeline.locator('tbody tr').first()
  await expect(pausedReading).toContainText('dip')
  await expect(pausedReading).toContainText('Entries paused · FOMC')
  await expect(timeline).toContainText('Dip is a pullback setup, not a Buy instruction.')
  await expect(timeline).toContainText('Personal Buy follows a separate breakout rule with account checks.')
  await expect(timeline).toContainText('A+ is a grade, not entry timing.')
  await expect(timeline).toContainText('20.0%')
  await expect(timeline).toContainText('+10.0 pp')
  await expect(timeline).toContainText('not a prediction accuracy score, a fill, or your profit')
  await expect(timeline).toContainText('policy/1')
  await expect(timeline).toContainText('await validated daily data')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Failed archive reads must remain visible even when there are no readable observations.
test('unreadable research archives remain visible when the timeline is empty', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/desk/history/AAPL', route => route.fulfill({json: {
    ticker: 'AAPL', rows: [], backtest: null, recommendations: {
      status: 'no_recorded_recommendations', outcomes: null, invalid_archives: 2,
      older_records_not_shown: false, observations: [],
    },
  }}))
  await page.goto('/#desk')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
  await page.getByText('Score, log & backtest', {exact: true}).click()
  const timeline = page.getByRole('region', {name: 'Recorded research readings'})
  await expect(timeline).toContainText('No readable archived research readings')
  await expect(timeline).toContainText('Some archive records could not be read.')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// The board reads the paper account's cash beside its orders and refreshes the whole view together.
test('single board keeps the paper account’s cash beside its orders', async ({page}) => {
  await page.clock.install({time: new Date('2026-09-09T14:00:10Z')})
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  let next = false
  // Serve compatible completed prices for each observed candle.
  const bar = () => next ? '2026-09-09T14:00:00Z' : '2026-09-09T13:45:00Z'
  await page.route(`**/market/${USER}/desk/live`, route => route.fulfill({json: {
    as_of: bar(), data_at: bar(), quotes: Object.fromEntries(Object.keys(latest.grades).map(ticker => [ticker, {symbol: ticker, last: next ? 110 : 100, bar: bar()}])),
  }}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toHaveCount(1)
  await expect(page.getByLabel('Paper account summary')).toContainText('$104,200 paper account')
  await expect(page.getByLabel('Paper account summary')).toContainText('cash $12,000 (11.5%)')
  await expect(page.getByLabel('Paper account summary')).toContainText('1 order (1 buy, 0 sells)')
  // The book: the order first, then the holding; the rest of the graded names are one click away.
  await expect(board.locator('tbody tr')).toHaveCount(2)
  await expect(board.locator('tbody tr').first()).toContainText('NVDA')
  await expect(board.locator('tbody tr').last()).toContainText('AAPL')
  await allNames(page)
  await expect(board.locator('tbody tr')).toHaveCount(3)
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: 'Plan status'})).toHaveCount(1)
  next = true
  await page.clock.fastForward(15 * 60_000)
  const nvda = board.locator('tbody tr').filter({has: page.getByRole('button', {name: /^NVDA/})})
  await expect(nvda).toContainText('$110.00')
  await expect(page.getByLabel('NVDA size')).toContainText('10 sh')
  await expect(page.getByLabel('NVDA size')).toContainText('$1,300 · 1.2%')
  await page.setViewportSize({width: 390, height: 844})
  // The board's own box pans to reach the right-hand columns on a phone,
  // while the page itself never scrolls sideways.
  await noSidewaysScroll(page, 'board at 390')
  const scroller = board.locator('xpath=ancestor::div[contains(@class,"overflow-auto")]')
  const canPan = await scroller.evaluate(el => el.scrollWidth > el.clientWidth)
  expect(canPan).toBe(true)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// An FOMC pause does not erase the book: the rule line says the FOMC risk rule is in charge,
// the orders say when, and the rows keep their words.
test('single board keeps its orders and holdings during FOMC', async ({page}) => {
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], event_status: {active: true, stale: true, planning_paused: true},
  }}))
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(page.getByLabel('Execution rule')).toContainText('FOMC cycle: the paper account follows the FOMC risk rule; its orders say when.')
  await expect(page.getByLabel('Today')).toContainText('paper FOMC target exposure unavailable')
  await expect(board.getByLabel('NVDA strategy intent')).toHaveText('BUY')
  await expect(board.getByLabel('NVDA order status')).toContainText('Planned')
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('HOLD')
  await expect(board.locator('tbody tr')).toHaveCount(2)
  await page.goto('/?deskDetails=1#desk')
  await expect(page.getByRole('heading', {name: /^Stock rankings/})).toBeVisible()
  await expect(board).toBeVisible()
})

// During a settled reduction the Today line names the exposure the desk holds and the
// decision it holds it through; the board's rule line says the FOMC rule is in charge.
test('a settled FOMC reduction names the half exposure and the restore decision', async ({page}) => {
  await page.clock.install({time: new Date('2026-09-09T14:00:10Z')})
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk/live`, route => route.fulfill({json: {
    as_of: '2026-09-09T14:00:00Z',
    quotes: {
      AAPL: {symbol: 'AAPL', last: 100, bar: '2026-09-09T13:45:00Z'},
      NVDA: {symbol: 'NVDA', last: 130, bar: '2026-09-09T13:45:00Z'},
      MSFT: {symbol: 'MSFT', last: 90, bar: '2026-09-09T13:45:00Z'},
    },
  }}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session],
    event_status: {as_of: '2026-09-09T14:00:00Z', status: 'reduction settled', stale: false, active: true, planning_paused: true, pending_orders: 0,
      policy: {enabled: true, session: '2026-09-08', decision_date: '2026-09-16', factor: 0.5, calendar_known: true,
        spy_five_session_return: -0.011, evaluation_since: '2026-06-18'}},
  }}))
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(page.getByLabel('Today')).toContainText('paper FOMC target exposure 50% through the 2026-09-16 decision')
  await expect(page.getByLabel('Execution rule')).toContainText('FOMC cycle: the paper account follows the FOMC risk rule; its orders say when.')
  await expect(board.getByLabel('AAPL strategy intent')).toHaveText('HOLD')
  await expect(board.getByLabel('AAPL size')).toHaveText('—')
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: 'Plan status'})).toContainText('The FOMC cycle takes priority over the scheduled plan.')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// An unreadable plan says so above the board rather than pretending the desk has no orders,
// and an unreachable paper account is named, never shown as an empty book.
test('the board names an unreadable plan and an unreachable account, not a plain empty book', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {
    as_of: '2026-09-08T20:00:00Z', equity: 104200, cash: 12000, positions: [], orders: [],
    plan: {rule: 'dip_or_close', until_rebalance: 18, orders: [], reason: 'the plan file could not be read'},
  }}))
  await page.goto('/#desk')
  await expect(page.getByText('the plan file could not be read; statuses may lag.')).toBeVisible()
  await expect(page.getByLabel('Today')).toContainText('No paper orders.')
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {reason: 'broker unavailable'}}))
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(page.getByLabel('Paper account summary')).toContainText('Paper account unavailable: broker unavailable')
  await expect(page.getByLabel('Today')).toContainText('Paper orders loading.')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Preserve distinct saved-signal, usable-outcome and simulated-account quantities.
function forwardEvidenceRecord(): DeskForwardEvidence {
  return {status: 'collecting_forward_evidence', versions: [{
    version: 'candidate/2', decision_count: 41, pending_daily_validation: 3, corporate_actions_through: '2026-09-08',
    outcomes: [{
      signal_count: 82, decision_days: 21, cost_bps_per_side: 10, missing_or_immature: {'5': 12, '20': 21},
      grades: [
        {grade: 'A', horizon_sessions: 5, observations: 42, nonoverlapping_cohorts: 20, mean_excess_return: .0312, approximate_95_interval: [-.0105, .0729]},
        {grade: 'B', horizon_sessions: 5, observations: 20, nonoverlapping_cohorts: 4, mean_excess_return: -.021, approximate_95_interval: null},
        {grade: 'C', horizon_sessions: 20, observations: 1, nonoverlapping_cohorts: 1, mean_excess_return: 0, approximate_95_interval: null},
        {grade: 'A+', horizon_sessions: 20, observations: 0, nonoverlapping_cohorts: 0, mean_excess_return: null, approximate_95_interval: null},
      ],
      entry_states: [{state: 'wait', horizon_sessions: 5, observations: 12, nonoverlapping_cohorts: 3, mean_excess_return: -.008}],
    }, {
      signal_count: 82, decision_days: 21, cost_bps_per_side: 25, missing_or_immature: {'20': 21}, grades: [],
    }],
    portfolios: [{
      cost_bps: 10, fill_intervals: 40, status: 'observations_available', arms: {
        baseline_targets: {return: .05, drawdown: -.08, traded_dollars: 120000},
        technical_targets: {return: -.02, drawdown: -.10, traded_dollars: 230000},
        targets: {return: 0, drawdown: 0, traded_dollars: 0},
        correlation_targets: {return: .0123, drawdown: -.0456, traded_dollars: 45000},
      },
    }, {
      cost_bps: 25, fill_intervals: 2, status: 'observations_available', arms: {
        baseline_targets: {return: 0, drawdown: 0, traded_dollars: 0},
      },
    }],
  }]}
}

// Open the real research disclosure with a fixture while allowing the old heading in baseline runs.
async function openForwardEvidence(page: Page, evidence?: DeskForwardEvidence) {
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], forward_evidence: evidence,
  }}))
  await page.goto('/?deskView=research#desk')
  const summary = page.getByText(/^(Forward evidence|Results from saved signals) · research$/)
  const panel = page.locator('details', {has: summary})
  if (await panel.getAttribute('open') === null) await summary.click()
  await expect(panel).toHaveAttribute('open', '')
  return panel
}

// Allow the non-recording board preview while rejecting other market mutations and failed responses.
function observeForwardEvidenceRequests(page: Page) {
  const evidence = {failedResponses: [] as string[], marketWrites: [] as string[], deskReads: 0}
  page.on('response', response => {
    if (response.status() >= 400) evidence.failedResponses.push(`${response.status()} ${response.url()}`)
  })
  page.on('request', request => {
    if (!request.url().includes('/market/')) return
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) evidence.marketWrites.push(`${request.method()} ${request.url()}`)
    if (request.url().endsWith(`/market/${USER}/desk`)) evidence.deskReads += 1
  })
  return evidence
}

// Missing outcomes remain unavailable even when their decision date is old.
test('forward evidence distinguishes unusable outcomes from zero performance', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const evidence = await openForwardEvidence(page, {status: 'collecting_forward_evidence', versions: [{
    version: 'candidate/2', decision_count: 10, pending_daily_validation: 0, corporate_actions_through: '2026-09-08',
    outcomes: [{signal_count: 12, decision_days: 1, cost_bps_per_side: 10, missing_or_immature: {'5': 12}, grades: []}],
    portfolios: [{cost_bps: 10, fill_intervals: 0, status: 'insufficient_forward_data', arms: {}}],
  }]})
  await expect(evidence).toContainText('No usable 5-/20-session outcomes')
  await expect(evidence).toContainText('Missing prices, unfinished horizons or no valid entry')
  await expect(evidence).toContainText('Missing or unusable outcomes: 12 at 5 sessions')
  await expect(evidence).toContainText('Insufficient eligible rebalance checks for an account comparison')
  await expect(evidence).not.toContainText('No matured')
  await expect(evidence).not.toContainText('0.00%')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// File metadata cannot be rendered as independent daily-price or corporate-action validation.
test('forward evidence describes reported coverage rather than validation', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const evidence = await openForwardEvidence(page, forwardEvidenceRecord())
  await expect(evidence).toContainText('Reported daily-data coverage through 2026-09-08 · 3 newer decisions not evaluated')
  await expect(evidence).toContainText('Prices and corporate-action adjustments have not been independently verified')
  await expect(evidence).toContainText('reported coverage is only file metadata')
  await expect(evidence).not.toContainText('Daily validation through')
  await expect(evidence).not.toContainText('awaiting validation')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Tracker names identify the saved stock book and both updated grade inputs, not passive indexes.
test('forward evidence names the saved book and updated grade comparisons precisely', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const evidence = await openForwardEvidence(page, forwardEvidenceRecord())
  await expect(evidence.getByRole('cell', {name: 'Saved stock targets', exact: true})).toHaveCount(2)
  await expect(evidence.getByRole('cell', {name: 'Updated grades', exact: true})).toBeVisible()
  await expect(evidence.getByRole('cell', {name: 'Updated grades + economic cap', exact: true})).toBeVisible()
  await expect(evidence.getByRole('cell', {name: 'Updated grades + economic + correlation caps', exact: true})).toBeVisible()
  const method = evidence.getByLabel('How saved-signal results are calculated', {exact: true})
  await method.locator('summary').click()
  await expect(method).toHaveAttribute('open', '')
  await expect(method.getByText('Updated grades use new technical readings and compatible valuation inputs, while retaining other analyst inputs.', {exact: false})).toBeVisible()
  await expect(evidence).toContainText('No passive SPY/QQQ account comparison is shown here')
  await expect(evidence).toContainText('subtract SPY')
  await expect(evidence.getByRole('cell', {name: 'Technical targets', exact: true})).toHaveCount(0)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Saved-price account drops and eligible checks cannot claim continuous drawdown or actual trades.
test('forward evidence limits sampled losses and explains account units', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const evidence = await openForwardEvidence(page, forwardEvidenceRecord())
  await expect(evidence.getByRole('columnheader', {name: 'Largest drop at observed prices', exact: true})).toHaveCount(2)
  await expect(evidence.getByRole('columnheader', {name: 'Simulated return after costs', exact: true})).toHaveCount(2)
  await expect(evidence.getByRole('columnheader', {name: 'Trading / starting balance', exact: true})).toHaveCount(2)
  await expect(evidence).toContainText('Drops are from prior peaks at saved prices; losses between observations can be missed')
  await expect(evidence).toContainText('40 eligible rebalance checks')
  await expect(evidence).toContainText('2 eligible rebalance checks')
  await expect(evidence).toContainText('A check can produce no trade')
  await expect(evidence).toContainText('Trading is buys plus sells, excluding fees, divided by the $100,000 starting balance')
  await expect(evidence).toContainText('Account return is the cumulative change from a $100,000 starting balance; it includes unpaid dividends, is not annualized and assumes no final sale')
  await expect(evidence.getByRole('columnheader', {name: 'Drawdown', exact: true})).toHaveCount(0)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// First-daily signal counts differ from usable stock outcomes and the spaced dates used for means.
test('forward evidence distinguishes tracked signals usable outcomes and spaced days', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const evidence = await openForwardEvidence(page, forwardEvidenceRecord())
  await expect(evidence).toContainText('82 saved stock signals')
  await expect(evidence).toContainText('stock signals come from the first saved decision each day')
  await expect(evidence).toContainText('Signal counts include wait signals and signals without usable outcomes')
  await expect(evidence.getByRole('columnheader', {name: 'Usable outcomes', exact: true})).toHaveCount(2)
  await expect(evidence.getByRole('columnheader', {name: 'Spaced signal days', exact: true})).toBeVisible()
  await expect(evidence).toContainText('The mean first averages usable stock returns within each day, then gives equal weight to selected days')
  await expect(evidence).toContainText('Selected dates are at least 5 or 20 trading sessions apart, matching the return period')
  await expect(evidence).toContainText('Spacing does not establish independence')
  await expect(evidence).toContainText('Approximate 95% intervals require 20 spaced signal days')
  await expect(evidence).not.toContainText('stock observations tracked')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Copy changes preserve every displayed result, missing value, cost case, version and safety limit.
test('forward evidence preserves result values costs histories and limitations', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const record = forwardEvidenceRecord()
  record.versions!.push({version: 'candidate/1', decision_count: 2, outcomes: [], portfolios: []})
  const evidence = await openForwardEvidence(page, record)
  await expect(evidence).toContainText('candidate/2 · 41 recorded decisions · 21 decision days')
  await expect(evidence).toContainText('candidate/1 · 2 recorded decisions · 0 decision days')
  await expect(evidence).toContainText('10 bp per side')
  await expect(evidence).toContainText('25 bp per side')
  await expect(evidence).toContainText('12 at 5 sessions · 21 at 20 sessions')
  const grades = evidence.getByRole('table').first()
  await expect(grades.getByRole('row').filter({has: page.getByRole('cell', {name: 'A', exact: true})}).getByRole('cell')).toHaveText(['A', '5', '42', '20', '3.12%', '-1.05% to 7.29%'])
  await expect(grades.getByRole('row').filter({has: page.getByRole('cell', {name: 'B', exact: true})}).getByRole('cell')).toHaveText(['B', '5', '20', '4', '-2.10%', 'Insufficient evidence'])
  await expect(grades.getByRole('row').filter({has: page.getByRole('cell', {name: 'C', exact: true})}).getByRole('cell')).toHaveText(['C', '20', '1', '1', '0.00%', 'Insufficient evidence'])
  await expect(grades.getByRole('row').filter({has: page.getByRole('cell', {name: 'A+', exact: true})}).getByRole('cell')).toHaveText(['A+', '20', '0', '0', '—', 'Insufficient evidence'])
  await expect(evidence.getByRole('table').nth(1).getByRole('row').last().getByRole('cell')).toHaveText(['wait', '5', '12', '-0.80%'])
  await expect(evidence.getByRole('table').nth(2).getByRole('row').nth(1).getByRole('cell')).toHaveText(['Saved stock targets', '5.00%', '-8.00%', '1.20×'])
  await expect(evidence.getByRole('table').nth(2).getByRole('row').nth(2).getByRole('cell')).toHaveText(['Updated grades', '-2.00%', '-10.00%', '2.30×'])
  await expect(evidence.getByRole('table').nth(2).getByRole('row').nth(3).getByRole('cell')).toHaveText(['Updated grades + economic cap', '0.00%', '0.00%', '0.00×'])
  await expect(evidence.getByRole('table').nth(2).getByRole('row').nth(4).getByRole('cell')).toHaveText(['Updated grades + economic + correlation caps', '1.23%', '-4.56%', '0.45×'])
  await expect(evidence.getByRole('table').nth(3).getByRole('row').last().getByRole('cell')).toHaveText(['Saved stock targets', '0.00%', '0.00%', '0.00×'])
  await expect(evidence).toContainText('Research does not change orders')
  await expect(evidence).toContainText('They are not profit probabilities')
  await expect(evidence).toContainText('First daily signal only')
  await expect(evidence).toContainText('No interval means insufficient evidence for that estimate')
  await expect(evidence).toContainText('separate from the complete scheduled strategy and actual paper fills')
  await expect(evidence).toContainText('Costs are assumptions')
  await expect(evidence).toContainText('modeled fills use later observed prices')
  await expect(evidence).toContainText('Grade outcomes deduct an additive round-trip cost allowance; account costs apply to each dollar bought or sold')
  await expect(evidence).toContainText('Recorded splits adjust shares')
  await expect(evidence).toContainText('dividends accrue as receivables and cannot fund buys because pay dates are unavailable')
  await expect(evidence).toContainText('Other corporate actions are not modeled')
  await expect(evidence).toContainText('Candidates require separate validation before changing the adopted strategy')
  await expect(evidence).toContainText('do not establish optimal entry, exit or FOMC re-entry timing')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Missing report data remains unavailable without invented performance numbers.
test('forward evidence preserves absent report state', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const missing = await openForwardEvidence(page)
  await expect(missing).toContainText('Collecting forward records; performance unavailable')
  await expect(missing.getByRole('table')).toHaveCount(0)
  await expect(missing).not.toContainText('0.00%')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// An explicit unavailable reason is preserved without a fabricated coverage date.
test('forward evidence preserves unavailable report state', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const unavailable = await openForwardEvidence(page, {status: 'unavailable', reason: 'Saved prices unavailable; no performance report.'})
  await expect(unavailable).toContainText('Saved prices unavailable; no performance report')
  await expect(unavailable.getByRole('table')).toHaveCount(0)
  await expect(unavailable).not.toContainText('Reported daily-data coverage through')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

for (const viewport of [{width: 1365, height: 900}, {width: 390, height: 844}]) {
  // The expanded read-only disclosure stays usable on desktop and phone through a reload.
  test(`forward evidence research workflow stays readable at ${viewport.width}px`, async ({page}, testInfo) => {
    await page.setViewportSize(viewport)
    const errors = observeBlockingBrowserErrors(page)
    const requests = observeForwardEvidenceRequests(page)
    const evidence = await openForwardEvidence(page, forwardEvidenceRecord())
    const summary = evidence.locator(':scope > summary')
    await expect(summary).toHaveText('Results from saved signals · research')
    await expect(evidence.getByText('Reported daily-data coverage through', {exact: false})).toBeVisible()
    await expect(evidence.getByRole('cell', {name: 'Updated grades + economic + correlation caps', exact: true})).toBeVisible()
    await expect(evidence).toContainText('not been independently verified')
    const bounds = await evidence.boundingBox()
    expect(bounds).not.toBeNull()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width)
    const pageWidth = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth}))
    expect(pageWidth.scroll).toBeLessThanOrEqual(pageWidth.client)
    const method = evidence.getByLabel('How saved-signal results are calculated', {exact: true})
    await expect(method).not.toHaveAttribute('open', '')
    await method.locator('summary').click()
    await expect(method).toHaveAttribute('open', '')
    await expect(method.getByText('Drops are from prior peaks at saved prices', {exact: false})).toBeVisible()
    await method.locator('summary').click()
    await expect(method).not.toHaveAttribute('open', '')
    await summary.click()
    await expect(evidence).not.toHaveAttribute('open', '')
    await summary.click()
    await expect(evidence).toHaveAttribute('open', '')
    await page.reload()
    await page.getByText('Results from saved signals · research', {exact: true}).click()
    await expect(evidence.getByRole('cell', {name: 'Updated grades', exact: true})).toBeVisible()
    await expect(evidence).toContainText('candidate/2 · 41 recorded decisions · 21 decision days')
    await testInfo.attach('expanded-research', {body: await evidence.screenshot(), contentType: 'image/png'})
    await testInfo.attach('browser-diagnostics', {body: JSON.stringify({...errors, failedResponses: requests.failedResponses, marketWrites: requests.marketWrites}), contentType: 'application/json'})
    await testInfo.attach('layout-and-reads', {body: JSON.stringify({bounds, pageWidth, deskReads: requests.deskReads}), contentType: 'application/json'})
    expect(errors).toEqual({consoleErrors: [], pageErrors: []})
    expect(requests.failedResponses).toEqual([])
    expect(requests.marketWrites).toEqual([])
    expect(requests.deskReads).toBeGreaterThanOrEqual(2)
  })
}

// The FOMC overlay's gate: the counterfactual priced beside the live book
// per meeting, and the pre-registered standing, never an action.
test('the FOMC gate shows each meeting against the book without the overlay', async ({page}) => {
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], fomc_gate: {
      version: 'fomc-gate/1', written: '2026-09-15T21:00:00+00:00', first_meeting: '2026-09-16', cost_bp: 25,
      basis: 'paper account fills and closes',
      meetings: [{decision_date: '2026-09-16', status: 'cycle open', complete: false, window: ['2026-09-11', '2026-09-14'],
        effect: 203.45, effect_pct: 0.002047, effect_after_costs: 154.45, effect_after_costs_pct: 0.001554,
        drawdown_live: -0.01677, drawdown_without: -0.01882}],
      verdict: {standing: 'waiting', completed_meetings: 0, required: 6, effect_after_costs: 0, effect_after_costs_pct: 0,
        meetings_with_deeper_live_drawdown: 0, rule: 'after 6 completed meetings from 2026-09-16: keep when positive after costs'},
    },
  }}))
  await page.goto('/?deskView=research#desk')
  const gate = page.getByLabel('FOMC overlay gate')
  await expect(gate).toContainText('0 of 6 meetings')
  await gate.locator('summary').click()
  await expect(gate).toContainText('waiting for enough meetings')
  const table = page.getByRole('table', {name: 'FOMC meetings'})
  await expect(table).toContainText('2026-09-16')
  await expect(table).toContainText('+$203 (0.20%)')
  await expect(table).toContainText('+$154 (0.16%)')
  await expect(table).toContainText('-1.68%')
  await expect(table).toContainText('-1.88%')
})

// Execution against the decision price is a series on the page, by scope
// and by session, with the sign that makes paying up a cost.
test('execution quality leads with slippage and shows the drift beside it', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  // The real September shape: the restoration buys measured +234 bp against
  // their decision price, of which +243 bp was the overnight gap and -9 bp
  // was the trading. The page must lead with the -9.
  const agg = (fills: number, bps: number, dollars: number, slippage: number | null, drift: number | null) =>
    ({fills, notional: 10000, bps, dollars, measured: slippage === null ? 0 : fills, measured_notional: 10000,
      slippage_bps: slippage, drift_bps: drift})
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], execution_quality: {
      version: 'execution-quality/2', written: '2026-09-17T23:48:48+00:00',
      basis: 'slippage is the benchmark to the fill: what the trading cost',
      all_time: agg(18, 115.3, 454, -6.7, 122.3), recent: {sessions: 2, ...agg(18, 115.3, 454, -6.7, 122.3)},
      by_kind: {rebalance: agg(0, 0, 0, null, null), fomc: agg(18, 115.3, 454, -6.7, 122.3)},
      by_side: {buy: agg(9, 234.1, 464, -8.7, 243.1), sell: agg(9, -4.8, -9, -4.8, 0)},
      series: [{session: '2026-09-17', ...agg(9, 234.1, 464, -8.7, 243.1), cumulative_dollars: 454}],
      worst: [
        {session: '2026-09-17', symbol: 'SNDK', side: 'buy', kind: 'fomc', bps: 388.4, dollars: 59, slippage_bps: 92.7},
        {session: '2026-09-17', symbol: 'AAOI', side: 'buy', kind: 'fomc', bps: 438.6, dollars: 64, slippage_bps: 26.1},
      ],
    },
  }}))
  await page.goto('/?deskView=research#desk')
  const quality = page.getByLabel('Execution quality')
  // The headline is the trading cost, not the overnight move.
  await expect(quality).toContainText('18 fills, -6.7 bp slippage')
  await expect(quality).not.toContainText('18 fills, +115.3 bp')
  await quality.locator('summary').click()
  await expect(quality).toContainText('slippage is the benchmark to the fill')
  const summary = page.getByRole('table', {name: 'Execution summary'})
  await expect(summary.getByRole('columnheader', {name: 'Slippage'})).toBeVisible()
  await expect(summary.getByRole('columnheader', {name: 'Drift'})).toBeVisible()
  await expect(summary.getByRole('columnheader', {name: 'Total'})).toBeVisible()
  // The buys row carries all three: bad-looking total, big drift, small slippage.
  const buys = summary.locator('tbody tr').filter({hasText: 'Buys'})
  await expect(buys).toContainText('-8.7 bp')
  await expect(buys).toContainText('+243.1 bp')
  await expect(buys).toContainText('+234.1 bp')
  // A kind with no split says so rather than showing a zero.
  await expect(summary.locator('tbody tr').filter({hasText: 'Scheduled rebalances'})).toContainText('—')
  const bySession = page.getByRole('table', {name: 'Execution by session'})
  await expect(bySession).toContainText('2026-09-17')
  await expect(bySession).toContainText('+$464')
  // The worst table ranks the worst trading, not the biggest gap.
  const worst = page.getByRole('table', {name: 'Worst fills'})
  await expect(worst.locator('tbody tr').first()).toContainText('SNDK')
  await expect(worst.locator('tbody tr').first()).toContainText('+92.7 bp')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A stale observation cannot erase a durable active cycle from the status heading.
test('stale FOMC recovery keeps the active cycle paused', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], event_policy: {enabled: true},
    event_status: {as_of: '2026-09-01T14:00:00Z', stale: true, active: true, planning_paused: true,
      status: 'reduction settled', pending_orders: 0},
  }}))
  await page.goto('/?deskDetails=1#desk')
  await strategyDetails(page)
  const banner = page.getByLabel('FOMC exposure policy')
  await expect(banner).toContainText('FOMC · portfolio adjustments paused')
  await expect(banner).toContainText('last known status')
  await expect(banner).not.toContainText('decision missing')
  await expect(banner).toContainText('An event cycle is recorded')
  await expect(banner).not.toContainText('Enabled for the next nightly run')
  await strategyDetails(page)
  await expect(page.getByLabel('Your planned cash')).toContainText('FOMC overrides the scheduled plan')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Current recovery evidence takes priority while the archived nightly decision stays dated.
test('FOMC recovery displays current intent and pauses the portfolio plan', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], event_policy: {enabled: true},
    event_status: {as_of: new Date().toISOString(), stale: false, active: true, planning_paused: true,
      status: 'reduction pending', pending_orders: 2,
      policy: {session: latest.session, factor: .5, calendar_known: true, decision_date: '2026-09-16'}},
  }}))
  await page.goto('/?deskDetails=1#desk')
  await strategyDetails(page)
  await expect(page.getByLabel('FOMC exposure policy')).toContainText('FOMC · reduction pending')
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: 'Plan status'})).toContainText('FOMC cycle takes priority')
  await strategyDetails(page)
  await expect(page.getByLabel('Your planned cash')).toContainText('FOMC overrides the scheduled plan')
  await strategyDetails(page)
  await expect(page.getByLabel('FOMC exposure policy')).not.toContainText('decision missing')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// The glance can fall back to the nightly record, but the source and date must stay
// visible so the fallback cannot look like a broker snapshot; the board names the outage.
test('paper fallback is labelled with the saved paper snapshot session', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  latest.paper.session = '2026-09-04'
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest}}))
  await page.route(`**/api/v1/market/${USER}/desk/paper`, route => route.fulfill({json: {reason: 'broker unavailable'}}))
  await page.goto('/#desk')
  await expect(page.getByLabel('Paper account summary')).toContainText('Paper account unavailable: broker unavailable')
  await allNames(page)
  await expect(await stockDetails(page, 'AAPL')).toContainText('Not held')
  await page.locator('summary', {hasText: 'Paper account'}).click()
  await expect(page.getByLabel('The desk at a glance')).toContainText('Saved 2026-09-04 · broker refresh unavailable')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Missing broker and archive evidence must not imply an empty or saved account.
test('missing paper evidence is unavailable rather than a saved snapshot', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest: {...deskRecord(), paper: null}}}))
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {reason: 'broker unavailable'}}))
  await page.goto('/#desk')
  await expect(page.getByLabel('Paper account summary')).toContainText('Paper account unavailable: broker unavailable')
  await expect(page.getByLabel('Today')).toContainText('Paper orders loading.')
  await page.locator('summary', {hasText: 'Paper account'}).click()
  await expect(page.getByLabel('The desk at a glance')).toContainText('Paper account unavailable')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A graded name outside the book has an explicit zero target; a held name the desk does not
// grade has no target evidence, and neither reads as an order.
test('covered names outside the strategy book show an explicit zero target', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  ;(latest as {targets?: object}).targets = {policy: 'graded-equal-weight/4', weights: {AAPL: .06}}
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest}}))
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {
    as_of: '2026-09-08T20:00:00Z', equity: 104200, cash: 12000, orders: [], plan: paperPlan([]),
    positions: [{symbol: 'UNKNOWN', qty: 2, avg_entry_price: 100, current_price: 100, market_value: 200, unrealized_pl: 0}],
  }}))
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('UNKNOWN strategy intent')).toHaveText('HOLD')
  await expect(board.getByLabel('UNKNOWN action status')).toHaveText('Not in the book; no order tonight')
  await expect(board.getByLabel('UNKNOWN size')).toHaveText('—')
  await expect((await stockDetails(page, 'UNKNOWN')).getByLabel('UNKNOWN position')).toContainText('Target — (graded-equal-weight/4)')
  await allNames(page)
  await expect(board.getByLabel('NVDA strategy intent')).toHaveText('—')
  await expect(board.getByLabel('NVDA action status')).toHaveText('Not in the book (grade B)')
  await expect((await stockDetails(page, 'NVDA')).getByLabel('NVDA position')).toContainText('Target 0.0% (graded-equal-weight/4)')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Execution history distinguishes an empty broker response from missing evidence.
test('paper execution distinguishes fills from unavailable history', async ({page}) => {
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {
    orders: [], activity: {session: '2026-09-14', complete: true, fills: []},
  }}))
  await page.goto('/?deskDetails=1#desk')
  await page.locator('summary', { hasText: 'Paper account' }).click()
  const execution = page.getByLabel('Paper execution', {exact: true})
  await expect(execution).toContainText('0 orders open at the broker')
  await expect(execution).toContainText('No fills · 2026-09-14')
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {orders: [], activity: {reason: 'offline'}}}))
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect(execution).toContainText('fill history unavailable')
  await expect(execution).not.toContainText('No fills')
})

// Fail browser acceptance on application exceptions and blocking console errors.
function observeBlockingBrowserErrors(page: Page) {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', error => pageErrors.push(error.message))
  // A request the browser aborted because the page moved on (a navigation,
  // an unmounted component) is not an application error.
  page.on('requestfailed', request => { if (request.failure()?.errorText !== 'net::ERR_ABORTED') consoleErrors.push(`Failed request: ${request.method()} ${request.url()}`) })
  return { consoleErrors, pageErrors }
}

// The desk's latest record, shaped from the real data/market/desk record so
// every section the page can show has something to show.
function deskRecord() {
  return {
    session: '2026-09-08',
    written: '2026-09-08T21:00:00Z',
    regime: {
      ai_participation: 0.31,
      software_participation: 0.52,
      participation_percentile: 0.12,
      ai_vs_software_correlation: 0.05,
      correlation_z: 2.1,
      novelty_z: 0.4,
      rotation_leader: 'none',
      rotation_spread: 0.12,
      ai_drawdown: 0.27,
      selection_confidence: 0.55,
      exposure: 0.8,
      flags: ['participation below its two-year median', 'AI-vs-software co-movement far from its history'],
    },
    grades: {
      AAPL: {
        grade: 'A',
        votes: 3.2,
        stances: { fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: -1 },
        score: 0.92,
        side: 'ai',
        headline: 'growing earnings, steady trend',
        reason: 'F The business keeps growing\nT The trend holds\nS No news against it',
        read: 'The desk sees growing earnings with the trend intact: revenue is up, margins hold, and the daily trend supports the grade.',
        reads: { fundamental: ['revenue is growing'], technical: ['daily trend up'] },
        ranks: { fundamental: 0.9, technical: 0.8, sentiment: 0.6, value: 0.5, rotation: 0.3 },
      },
      NVDA: {
        grade: 'B',
        votes: 2.1,
        stances: { fundamental: 1, technical: 0, sentiment: 1, value: 0, rotation: 1 },
        score: 0.61,
        side: 'ai',
        headline: 'expensive but the group is leading',
        reason: 'F Demand is real\nR The group leads\nV Price is far ahead of value',
        ranks: { fundamental: 0.95, technical: 0.4, sentiment: 0.7, value: 0.2, rotation: 0.8 },
      },
      // A covered name the board does not carry (not in the book, not held):
      // its drill-down must still fetch a live technical read on demand.
      MSFT: {
        grade: 'C',
        votes: 1.8,
        stances: { fundamental: -1, technical: 0, sentiment: 0, value: 1, rotation: 0 },
        score: 0.45,
        side: 'ai',
        headline: 'expensive and the trend is quiet',
        reason: 'F Fundamentals softened\nV Price sits near value',
        ranks: { fundamental: 0.3, technical: 0.5, sentiment: 0.5, value: 0.7, rotation: 0.4 },
      },
    },
    book: [
      { ticker: 'AAPL', grade: 'A', weight: 0.06, engine_weight: 0.05, volatility: 0.18, exposure: 0.8 },
      { ticker: 'NVDA', grade: 'B', weight: 0.0, engine_weight: 0.0, volatility: 0.35, exposure: 0.8 },
    ],
    briefs: {
      AAPL: {
        stance: 'AI',
        verdict: 'a steady AI leader',
        reasoning: 'Earnings keep growing and the trend is intact.',
        risks: 'A broad AI sell-off would take it down with the group.',
        watch: 'The technical rating slipping below A.',
      },
    },
    paper: {
      session: '2026-09-08',
      until_rebalance: 18,
      equity: 104200,
      cash: 12000,
      pl: 4200,
      pl_pct: 0.042,
      plan: 'rebalance',
      positions: [
        { symbol: 'AAPL', qty: 60, market_value: 6120, avg_entry_price: 91.25, current_price: 102, unrealized_pl: 645 },
      ],
      orders: [{ symbol: 'NVDA', side: 'buy', qty: 10, reason: 'grade rose to A' }],
    },
    actions: [
      { ticker: 'AAPL', action: 'add', grade: 'A', rank: 1, score: 0.92, target_weight: 0.06, current_weight: 0.04, delta_weight: 0.02, last_close: 102, entry_price: 91.25, entry: '2026-08-28', until_rebalance: 18, grade_margin: 0.3, leaves_if: 'drops below A', high_20: 105, stops: {}, stances: { fundamental: 1 }, why: 'The desk adds to its best name.', reason: 'F keeps growing\nT trend intact' },
    ],
    curve: {
      backtest: {
        label: 'the rules, walked forward',
        asof: '2026-09-08',
        dates: ['2026-01-02', '2026-03-02', '2026-05-01', '2026-07-01', '2026-09-08'],
        rules: [1.0, 1.06, 1.12, 1.19, 1.27],
        // The point-in-time line the strip reads its number from, far from
        // the stored (hindsight) line so a test cannot pass by reading one
        // figure for the other.
        rules_point_in_time: [0, 0.02, 0.03, 0.05, 0.08],
        stats_point_in_time: { cagr: 0.08, volatility: 0.2, drawdown: -0.12, total: 0.08 },
        spy: [1.0, 1.02, 1.01, 1.05, 1.09],
        qqq: [1.0, 1.03, 1.04, 1.08, 1.13],
        stats: { cagr: 0.31, volatility: 0.22, drawdown: -0.11, total: 0.27 },
      },
      paper: {
        label: 'paper account',
        sessions: ['2026-08-28', '2026-09-08'],
        equity: [100000, 104200],
        pl_pct: [0, 0.042],
      },
    },
  }
}

// Give deterministic tests one server-derived identity and the desk's data.
test.beforeEach(async ({ page }) => {
  // Reloading the desk may also restore its unrelated chat tab; keep that read in the fixture.
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET'
    ? route.fulfill({json: {messages: [], conversations: []}}) : route.fallback())
  // Display-only quotes are independent of the regular bars and must remain offline in fixtures.
  await page.route('**/desk/session-prices', route => route.fulfill({json: {session: 'unknown', as_of: null, signal_scope: 'regular-session', quotes: {}}}))
  // A stock detail can disclose personal history; tests without stored receipts get an empty page.
  await page.route('**/desk/personal-history?*', route => route.fulfill({json: {items: [], next_cursor: null, retention: {acknowledged_days: 90, unacknowledged_hours: 24}, limitations: []}}))
  await page.addInitScript(() => {
    // The clock decides the theme (dark from 19:00 to 06:59), which would
    // flip every assertion with the time of day; an explicit choice is stable.
    localStorage.setItem('anios.theme', 'light')
  })
  // The board reads the entry triggers on every render. A test that is not
  // about entries still needs the request answered, or the browser logs a
  // failed fetch into the console check. Tests about entries override this.
  // Share sizing now answers on arrival rather than waiting for a cash
  // figure, so every desk render asks for it. Tests about sizing override it.
  await page.route('**/desk/funding-preview', route => route.fulfill({json: {
    session: '2026-09-08', calculated_at: new Date().toISOString(),
    estimated_cost: 0, unallocated_cash: 0, cash_limited: false, rows: [], price_times: {},
  }}))
  await page.route('**/desk/entries*', route => route.fulfill({json: {
    user_id: USER, session: '2026-09-08', rows: [],
    reason: 'No live quotes this candle; entries need a current price.',
  }}))
  await page.route('**/api/v1/auth/session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      authentication_required: true,
      user_id: USER,
      expires_at: '2026-09-09T00:00:00Z',
      is_admin: true,
      desk_write: true,
    }),
  }))
  await page.route('**/api/v1/conversations/ani.mallya', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversations: [] }),
    }),
  )
  const record = deskRecord()
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      latest: record,
      summary: { session: '2026-09-08', counts: { A: 1, B: 1 }, gross: 0.8, names: ['AAPL', 'NVDA'], flags: [] },
      changes: {
        since: '2026-09-04',
        upgrades: [{ ticker: 'NVDA', from: 'B', to: 'A' }],
        downgrades: [],
        orders: [{ ticker: 'AAPL', action: 'add', weight_from: 0.04, weight_to: 0.06, grade_from: 'A', grade_to: 'A', reason: 'still the best name' }],
        flags_raised: ['participation below its two-year median'],
        flags_cleared: [],
      },
      sessions: ['2026-09-04', '2026-09-08'],
      curve: record.curve,
    }),
  }))
  await page.route(`**/api/v1/market/${USER}/desk/holdings`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ holdings: [{ ticker: 'AAPL', shares: 60, entry_price: 91.25, entry_date: '2026-08-28' }] }),
  }))
  await page.route(`**/api/v1/market/${USER}/desk/live`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      as_of: '2026-09-08T20:00:00Z',
      market_status: {
        exchange: 'XNYS', as_of: '2026-09-08T20:00:00Z', session: '2026-09-08',
        calendar_known: true, is_session: true, open: false, phase: 'post-market',
        opens_at: '2026-09-08T09:30:00-04:00', closes_at: '2026-09-08T16:00:00-04:00',
      },
      quotes: {
        AAPL: { symbol: 'AAPL', last: 102, open: 101, high: 103, low: 100.5, bar: '20:00', as_of: '2026-09-08T20:00:00Z' },
        NVDA: { symbol: 'NVDA', last: 130, open: 128, high: 132, low: 127, bar: '20:00', as_of: '2026-09-08T20:00:00Z' },
      },
      technical: { AAPL: { now: 0.9, close: 0.8 } },
      technical_detail: {
        AAPL: {
          now: 0.9,
          short: { ema21_distance: 0.126, support_distance: 0.125, support_kind: 3, resistance_distance: 0.15, resistance_kind: 1 },
          medium: { weekly_trend: 1 },
          long: { ema200_distance: 0.023 },
        },
      },
    }),
  }))
  await page.route(`**/api/v1/market/${USER}/desk/paper`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      as_of: '2026-09-08T20:00:00Z',
      equity: 104200,
      cash: 12000,
      day_pl: 312.5,
      pl_pct: 0.042,
      day_pl_pct: 0.003,
      positions: [{ symbol: 'AAPL', qty: 60, market_value: 6120, avg_entry_price: 91.25, current_price: 102, unrealized_pl: 645 }],
      orders: [],
      plan: paperPlan(),
    }),
  }))
  // The drill-down's live technical read: the model's plain words over the
  // analyst's live readings, with the deterministic lines as the fallback.
  await page.route(`**/api/v1/market/${USER}/desk/live/read/*`, route => {
    const symbol = (route.request().url().split('/').pop() ?? '').toUpperCase()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        symbol,
        read: 'Price sits above its rising averages with a bullish stack, support is the 200-day average below, and resistance is a swing high above.',
        lines: {
          short: ['12.6% above the 21-day EMA', '12.5% below nearest support — the 200-day average'],
          medium: ['weekly trend up'],
          long: ['2.3% below the 200-day EMA'],
        },
        now: 0.9,
      }),
    })
  })
  // The drill-down draws the ticker chart on open, so every test that opens a
  // name needs the chart answered or the browser logs a failed fetch into the
  // console check. Tests about the chart itself override this route.
  await page.route(`**/api/v1/market/${USER}/desk/chart/*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: USER, ticker: 'NVDA', timeframe: 'daily', timeframes: ['daily', 'weekly'],
      adjusted: true, last_bar_complete: true, basis: 'test fixture', sessions: 0,
      bars: [], overlays: {}, levels: {}, entries: [],
    }),
  }))
  // The drill-down fetches the newest earnings release read on open. Most
  // fixtures name no read (the block hides); the AAPL-specific route
  // registered below overrides this one for the same-day earnings test.
  await page.route(`**/api/v1/market/${USER}/desk/earnings/*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ user_id: USER, symbol: '', read: null }),
  }))
  await page.route(`**/api/v1/market/${USER}/desk/history/AAPL`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      ticker: 'AAPL',
      asof: '2026-09-08',
      horizon: 20,
      rows: [
        { date: '2026-08-28', grade: 'A', votes: 3.2, stances: { fundamental: 1, technical: 1, value: 0 }, exposure: 0.8, confidence: 0.9, forward: 0.021, forward_residual: 0.012, earnings: false, said: false },
        { date: '2026-09-08', grade: 'A', votes: 3.2, stances: { fundamental: 1, technical: 1, value: 0 }, exposure: 0.8, confidence: 0.9, forward: null, forward_residual: null, earnings: false, said: true },
      ],
      backtest: {
        min_grade: 'A',
        sessions: 60,
        sessions_in: 41,
        switches: 3,
        rule_return: 0.18,
        hold_return: 0.11,
        benchmark_return: 0.09,
        in_annualised: 0.41,
        out_annualised: 0.02,
      },
    }),
  }))
  // The newest earnings release read for AAPL, as the release reader stored
  // it: a same-day 8-K shows its tone and numbers in the drill-down without
  // waiting for the next nightly grade.
  await page.route(`**/api/v1/market/${USER}/desk/earnings/AAPL`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: USER,
      symbol: 'AAPL',
      read: {
        reaction_date: '2026-09-13',
        guidance: 1.0,
        demand: 1.0,
        pricing: 0.0,
        capex: 0.0,
        supply_constrained: 0.0,
        quarter_end: '2026-06-27',
        revenue_usd_m: 109417.0,
        eps_usd: 2.02,
        net_income_usd_m: 29789.0,
        gross_margin_pct: 50.1,
        summary: 'Apple reported record June-quarter revenue and EPS, with double-digit growth across products.',
        prompt_version: 'release_tone/3',
        same_day: true,
      },
    }),
  }))
  await page.route(`**/api/v1/market/${USER}/desk/history/MSFT`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      ticker: 'MSFT',
      asof: '2026-09-08',
      horizon: 20,
      rows: [
        { date: '2026-08-28', grade: 'C', votes: 1.8, stances: {}, exposure: 0.8, confidence: 0.9, forward: 0.011, forward_residual: 0.008, earnings: false },
        { date: '2026-09-08', grade: 'C', votes: 1.8, stances: {}, exposure: 0.8, confidence: 0.9, forward: null, forward_residual: null, earnings: false },
      ],
      backtest: {
        min_grade: 'A',
        sessions: 60,
        sessions_in: 12,
        switches: 2,
        rule_return: 0.09,
        hold_return: 0.12,
        benchmark_return: 0.09,
        in_annualised: 0.2,
        out_annualised: 0.05,
      },
    }),
  }))
  await page.route(`**/api/v1/market/${USER}/trading/autopsy`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      result: {
        patterns: [
          { behaviour: 'You sell into the first green day', evidence: 'three trades closed on a single up day' },
          { behaviour: 'You double down after a loss', evidence: 'the position grew after each drawdown' },
        ],
        costs: [{ what: 'Frequent small exits', amount: '~$240', source: 'trade log' }],
        plan: {
          stop: ['selling into the first green day'],
          start: ['writing the exit rule before entering'],
          keep: ['sizing by grade'],
        },
        unknowns: ['whether the exits were planned or reactive'],
      },
      sources: ['trade log', 'notes 2026-09'],
      passages_used: 3,
    }),
  }))
})

// The page must lead with the numbers a person can trust or act on: the
// practice account, the rules against the market, the exposure, and the
// warnings — not the analysts' tables.
// Keep economic facts distinguishable from bounded model interpretation.
// Keep the decision view compact while leaving detailed explanations accessible.
test('compact decision view keeps rankings above the fold', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.setViewportSize({width: 1440, height: 1000})
  await page.goto('/?deskDetails=1#desk')
  const board = page.getByLabel('Stocks and cash', {exact: true})
  await expect(board).toBeVisible()
  await page.waitForLoadState('networkidle')
  const text = await page.getByRole('main').innerText()
  const box = await board.boundingBox()
  console.log(JSON.stringify({visibleWords: text.trim().split(/\s+/).length, boardY: box?.y}))
  expect(box!.y).toBeLessThan(340)
  expect(text).not.toContain('Set up the board')
  expect(text).not.toContain('Targets for the next rebalance')
  await strategyDetails(page)
  await expect(page.getByLabel('Your planned cash')).toContainText('Legacy planned cash 94.0%')
  await strategyDetails(page)
  await expect(page.getByLabel('Your planned cash')).not.toContainText('Paper cash')
  await page.setViewportSize({width: 390, height: 844})
  await expect(page.getByRole('heading', {name: 'Stock rankings'})).toBeVisible()
  expect(await page.getByRole('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

test('separates dated inflation facts from research-only model judgement', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(), sessions: ['2026-09-08'],
    economics: {
      observed_at: new Date().toISOString(), collection_stale: false, model: 'deepseek-v4-flash',
      assessment: {pressure: 'mixed', evidence_ids: ['CPIAUCSL'], status: 'model_assessment'},
      facts: [{id: 'CPIAUCSL', label: 'CPI', status: 'available', period: '2026-08-01', source: 'https://fred.stlouisfed.org/series/CPIAUCSL', month_change_pct: .23, year_change_pct: 3.45, previous_year_change_pct: null}],
    },
  }}))
  await page.goto('/?deskView=research#desk')
  const context = page.getByLabel('Economic context')
  await page.getByText(/^Inflation ·/).click()
  await expect(context).toContainText('2026-08')
  await expect(context).toContainText('0.23%')
  await expect(context).toContainText('3.45%')
  await expect(context).toContainText('Unavailable')
  await expect(context).toContainText('mixed inflation pressure')
  await expect(context).toContainText('does not change the scheduled trading policy or submit orders')
  await expect(context.getByRole('link', {name: 'CPI', exact: true})).toHaveAttribute('href', 'https://fred.stlouisfed.org/series/CPIAUCSL')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Render recorded account results without inventing an execution policy for an untagged curve.
test('renders the desk at a glance with the track record', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET' ? route.fulfill({json: {messages: [], conversations: []}}) : route.fulfill({json: {}}))
  await page.goto('/?deskDetails=1#desk')
  await expect(page.getByRole('main').getByRole('heading', { level: 2, name: 'Desk' })).toBeVisible()

  // The paper account is its own section under the live plan, labelled as
  // simulated funds; the summary strip and the track record live there.
  await page.locator('summary', { hasText: 'Paper account' }).click()
  const glance = page.getByLabel('The desk at a glance')
  await expect(glance).toBeVisible()
  await expect(glance.getByText('Practice account', { exact: true })).toBeVisible()
  await expect(glance.getByText('$104,200')).toBeVisible()
  // The lifetime and today moves read as percentages, not a bare dollar
  // figure: 0.042 lifetime of the starting equity, 0.003 today. Both sit in
  // one "Today" cell rather than being shown twice, once as a percent in the
  // account cell and once as dollars in their own cell.
  await expect(glance.getByText('4.2%', { exact: false })).toBeVisible()
  await expect(glance.getByText('Change since prior close', { exact: true })).toBeVisible()
  await expect(glance.getByText(/\+\$31[23]/)).toBeVisible()
  await expect(glance.getByText(/\+0\.3%/)).toBeVisible()
  await expect(glance).not.toContainText('CAGR')
  await expect(glance).not.toContainText('SPY')
  const simulation = await simulationDetails(page)
  await expect(simulation.getByText('Policy not recorded', { exact: true })).toBeVisible()
  await expect(simulation.getByText('Strategy policy was not recorded; alignment with the active strategy is unverified.', { exact: false })).toBeVisible()
  // The strip's number is the point-in-time line's total with its CAGR, not
  // the stored hindsight line's (127% here), which stays on the chart.
  await expect(simulation.getByText('+8.0%', { exact: false })).toBeVisible()
  await expect(simulation.getByLabel('Policy simulation CAGR')).toHaveText('CAGR 8.0% · ')
  await expect(glance).not.toContainText('127.0%')
  await expect(simulation.getByText('vs SPY', { exact: false })).toBeVisible()
  await expect(glance.getByText('6% invested')).toBeVisible()  // 6,120 of 104,200 live

  // The trust anchor: the curve and its summary numbers, as an SVG the page
  // draws itself, in the same practice section.
  const record = page.getByRole('heading', {name: 'Historical simulation', exact: true})
  await expect(record).toBeVisible()
  await expect(page.getByRole('img', { name: "The desk's track record against SPY and QQQ" })).toBeVisible()
  await expect(page.getByText('CAGR', { exact: true })).toBeVisible()
  await expect(page.getByText('31.0%', { exact: true })).toBeVisible()

  // The regime leads the board, in plain words, and says what it is doing
  // about it.
  await expect(page.getByRole('note')).toContainText('Market risk')
  await expect(page.getByRole('note')).toContainText('AI trading activity is below its historical median')
  await expect(page.getByRole('note')).toContainText('target-size multiplier to 80%')

  // What moved since the last session, which the page used to throw away.
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: /^What changed/})).toBeVisible()
  await expect(page.getByText('Upgraded: NVDA B→A')).toBeVisible()
  await expect(page.getByText('Changes between recorded strategy target weights, not submitted orders: add AAPL')).toBeVisible()

  // A row reads in plain words first, and the ticker opens the drill-down.
  // The board is not due a rebalance for 18 sessions, and says so.
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: 'Plan status'})).toBeVisible()
  await expect(page.getByLabel('Reading the current picks')).toContainText('not a probability of profit')
  await expect(page.getByRole('columnheader', {name: 'Action'})).toBeVisible()
  await expect(page.getByRole('columnheader', {name: 'When / status'})).toBeVisible()
  await expect(page.getByRole('heading', {name: 'Plan status'})).toContainText('Paper weights reset in 18 sessions')
  await expect(page.getByLabel('Paper account summary')).toContainText('reset in 18 sessions')
  // The grade's evidence lives with the row's details, not in the collapsed row.
  const grade = (await stockDetails(page, 'AAPL')).getByLabel('AAPL grade', {exact: true})
  await expect(grade).toContainText('Grade A · 2026-09-08 close')
  await expect(grade).toContainText('growing earnings, steady trend')
  await expect(grade).toContainText('The business keeps growing')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Reporting-period inputs are named in strategy details and the summary without relabelling legacy curves.
test('names the fundamental data source and flags older fundamental-input curves', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  latest.provenance = { data: { fundamentals: 'fundamentals-features/3' } }
  // The simulation is of the strategy the record says the account runs
  // (`targets.policy`), so it reads as the policy simulation.
  latest.targets = { policy: 'graded-equal-weight/4', weights: { AAPL: 0.06 } }
  latest.curve = {
    ...latest.curve!,
    backtest: {
      ...latest.curve!.backtest,
      strategy_policy: 'graded-equal-weight/4',
      fundamentals_source: 'fundamentals-features/3',
    },
  }
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET' ? route.fulfill({json: {messages: [], conversations: []}}) : route.fulfill({json: {}}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.goto('/?deskDetails=1#desk')

  // The single stock board keeps source provenance in the strategy disclosure.
  const board = page.getByLabel('Ranked stocks and cash')
  await expect(board).toBeVisible()
  await strategyDetails(page)
  await expect(page.getByLabel('Fundamental data source', {exact: true})).toContainText('stored filing versions; reporting-period safeguard applied')

  // Historical source checks live with the simulation, not the actual account values.
  await simulationDetails(page)
  const glance = page.getByLabel('Historical simulation summary')
  await expect(glance.getByText('Policy simulation · names known at the time · live executor', { exact: true })).toBeVisible()

  // Same execution policy version, a record whose analyst read the frozen
  // EDGAR snapshot: the board's label switches to the legacy source and the
  // curve is flagged as older fundamental inputs rather than presented as
  // the corrected simulation.
  latest.provenance = { data: { fundamentals: 'edgar-frozen' } }
  latest.curve = { ...latest.curve!, backtest: { ...latest.curve!.backtest, fundamentals_source: 'edgar-frozen' } }
  await page.evaluate(() => localStorage.removeItem('anios_conversation_id:ani.mallya'))
  await page.reload()
  await strategyDetails(page)
  await expect(page.getByLabel('Fundamental data source', {exact: true})).toContainText('frozen EDGAR snapshot')
  await simulationDetails(page)
  const glance2 = page.getByLabel('Historical simulation summary')
  await expect(glance2.getByText('Policy simulation · names known at the time · live executor · older fundamental inputs', { exact: true })).toBeVisible()
  await expect(glance2).toContainText('frozen EDGAR snapshot')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The `/5` release (2026-09-29; `/4` under a 25% hold cap): a record whose targets are `/5`'s,
// beside its own `/5` simulation, reads as the current policy simulation - never "Unrecognized".
// The same record beside a `/4` simulation reads as the earlier policy, named as such.
test('a /5 record reads its /5 simulation as the policy simulation', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  latest.provenance = { data: { fundamentals: 'fundamentals-features/3' } }
  latest.targets = { policy: 'graded-equal-weight/5', weights: { AAPL: 0.25 } }
  latest.curve = {
    ...latest.curve!,
    backtest: {
      ...latest.curve!.backtest,
      strategy_policy: 'graded-equal-weight/5',
      fundamentals_source: 'fundamentals-features/3',
    },
  }
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET' ? route.fulfill({json: {messages: [], conversations: []}}) : route.fulfill({json: {}}))
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.goto('/?deskDetails=1#desk')
  await simulationDetails(page)
  const glance = page.getByLabel('Historical simulation summary')
  await expect(glance.getByText('Policy simulation · names known at the time · live executor', { exact: true })).toBeVisible()
  await expect(glance).not.toContainText('Unrecognized policy simulation')
  await expect(glance).not.toContainText('Older policy simulation')
  await strategyDetails(page)
  await expect(page.getByLabel('Recorded allocation policy')).toContainText('Allocation policy: graded-equal-weight/5')

  // The same `/5` record beside a `/4` simulation: recognised, and the earlier policy.
  latest.curve = { ...latest.curve!, backtest: { ...latest.curve!.backtest, strategy_policy: 'graded-equal-weight/4' } }
  await page.evaluate(() => localStorage.removeItem('anios_conversation_id:ani.mallya'))
  await page.reload()
  await simulationDetails(page)
  const older = page.getByLabel('Historical simulation summary')
  await expect(older.getByText('Older policy simulation', { exact: true })).toBeVisible()
  await expect(older).toContainText('Uses an earlier recorded strategy policy (graded-equal-weight/4); not the active strategy (graded-equal-weight/5).')
  await expect(older).not.toContainText('Unrecognized policy simulation')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Zero is not an up move: a flat day P/L keeps a neutral mark rather than
// drawing a green up arrow beside +$0.
test('a zero day P/L reads flat, not as an up move', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/api/v1/market/${USER}/desk/paper`, route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
    as_of: '2026-09-08T20:00:00Z', equity: 104200, cash: 12000, day_pl: 0, pl_pct: 0.042, day_pl_pct: 0,
  })}))
  await page.goto('/?deskDetails=1#desk')
  await page.locator('summary', { hasText: 'Paper account' }).click()
  const glance = page.getByLabel('The desk at a glance')
  await expect(glance.getByText('· $0')).toBeVisible()
  await expect(glance.getByText('↑ +$0')).toHaveCount(0)
  await expect(glance.getByText('· 0.0%')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The main stock list owns diagnostics, including on legacy detail links, without a second list.
test('one stock list preserves per-stock diagnostics and legacy detail links', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/market/${USER}/desk/live`, route => route.fulfill({json: {
    as_of: '2026-09-09T14:00:00Z', data_at: '2026-09-09T13:45:00Z',
    quotes: {AAPL: {last: 102, bar: '2026-09-09T13:45:00Z'}},
  }}))
  await page.goto('/?deskDetails=1#desk')
  await expect(page.getByLabel('Every grade in detail', {exact: true})).toHaveCount(0)
  await expect(page.getByRole('heading', {name: /^Stock rankings/})).toHaveCount(1)
  await expect(page.getByRole('button', {name: 'AAPL', exact: true})).toHaveCount(1)
  await strategyDetails(page)
  await expect(page.getByRole('region', {name: 'Desk guide', exact: true})).toBeVisible()
  const aapl = await stockDetails(page, 'AAPL')
  await expect(aapl.getByLabel('AAPL grade', {exact: true})).toContainText('Grade A · 2026-09-08 close')
  await expect(aapl.getByLabel('AAPL position', {exact: true})).toContainText('60 sh · $6,120 · 5.9%')
  await expect(aapl.getByLabel('AAPL position', {exact: true})).toContainText('average cost $91.25')
  await aapl.getByRole('button', {name: 'Chart and full history'}).click()
  const dialog = page.getByRole('dialog', {name: 'AAPL history'})
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Evening analysis · 2026-09-08')
  await expect(dialog).toContainText('F90+')
  await expect(dialog).toContainText('$102.00')
  await expect(dialog).toContainText(/Sep 9, 0?9:45 AM ET/)
  await dialog.getByText('All the evidence', {exact: true}).click()
  await dialog.getByText('Archived model commentary · unverified', {exact: true}).click()
  await expect(dialog).toContainText('a steady AI leader')
  await dialog.getByRole('button', {name: 'Close', exact: true}).click()
  await allNames(page)
  const msft = await stockDetails(page, 'MSFT')
  await expect(msft.getByLabel('MSFT grade', {exact: true})).toContainText('Grade C')
  await expect(msft.getByLabel('MSFT position', {exact: true})).toContainText('Not held')
  await page.screenshot({path: 'test-results/desk-consolidated-desktop.png', fullPage: true})
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// The page used to show the buys twice - once in a standalone "Best buys
// right now" list with its own Buy button and once as the board's buy rows -
// and the broker's live positions twice - once in its own section and once
// again in the behind-the-fold "Practice account" panel. Each thing is shown
// exactly once now: the board owns the buys, and the live positions table
// exists in one place even with the details open.
test('shows each thing once, not twice', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/?deskDetails=1#desk')

  // The board is the single buy list; no standalone best-buys shortlist.
  await expect(page.getByText('Best buys right now')).toHaveCount(0)
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: 'Plan status'})).toBeVisible()

  // The broker's live positions are one table on the page, inside the
  // practice account's own section.
  await page.locator('summary', { hasText: 'Paper account' }).click()
  await expect(page.getByText('Practice positions')).toBeVisible()
  await expect(page.locator('section', {has: page.getByRole('heading', {name: /^Practice positions/})})).toContainText('$91.25')

  // Opening the details must not add a second copy of the same positions:
  // the details' "Practice account" panel keeps its summary but shows the
  // positions table only when the broker is away, because the live section
  // above already shows them.
  await expect(page.getByRole('heading', {name: /^Stock rankings/})).toBeVisible()
  // The book first: the order (NVDA), then the holding (AAPL); every other graded name on request.
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.locator('tbody tr td:nth-child(2) button')).toHaveText(['NVDA', 'AAPL'])
  await allNames(page)
  await expect(board.locator('tbody tr td:nth-child(2) button')).toHaveText(['NVDA', 'AAPL', 'MSFT'])
  const msft = await stockDetails(page, 'MSFT')
  await expect(msft.getByLabel('MSFT grade', {exact: true})).toContainText('Grade C · 2026-09-08 close')
  await expect(msft.getByLabel('MSFT grade', {exact: true})).toContainText('expensive and the trend is quiet')
  await strategyDetails(page)
  await expect(page.getByRole('region', {name: 'Desk guide', exact: true})).toContainText('not individual letter grades or probabilities of profit')
  await page.getByRole('button', {name: 'Research', exact: true}).click()
  await page.getByRole('button', {name: 'Show practice account details', exact: true}).click()
  await expect(page.getByRole('heading', { name: /^Practice account/ })).toBeVisible()
  await expect(page.getByText('Gain so far')).toHaveCount(0)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Clicking a name must open its own history: what the desk said each
// The board opens with the top page of names and pages on request, so a
// ninety-name list is never a wall to scroll through; a search finds any
// ticker directly.
test('the board opens with top names, pages on request, and a search finds a ticker', async ({ page }) => {
  const latest = deskRecord()
  for (let i = 0; i < 30; i += 1) {
    const t = `T${String(i).padStart(2, '0')}`
    latest.grades[t] = {
      grade: i < 8 ? 'A' : 'B', votes: 1, stances: { fundamental: 1, technical: 0, sentiment: 0, value: 0, rotation: 0 },
      score: 1 - i / 40, side: 'ai', headline: `name ${i}`, reason: 'F holds',
    }
  }
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  // The book opens first: the order and the holding.
  await expect(board.locator('tbody tr')).toHaveCount(2)
  await allNames(page)
  await expect(board.locator('tbody tr')).toHaveCount(25)
  await page.getByRole('button', {name: /Show more/}).click()
  await expect(board.locator('tbody tr')).toHaveCount(33)
  await page.getByLabel('Search the stock list').fill('AAPL')
  await expect(board.locator('tbody tr')).toHaveCount(1)
  await expect(board.locator('tbody tr').first()).toContainText('AAPL')
  await page.getByLabel('Search the stock list').fill('nope')
  await expect(page.getByText('No name matches')).toBeVisible()
  await expect(board.locator('tbody tr')).toHaveCount(0)
})

// A held position is on the book view whatever its grade, and ranks above the unheld names on
// the full list; each name's move against its last close reads beside the price.
test("held positions stay past the fold and rows show the day's move", async ({ page }) => {
  await page.route(`**/market/${USER}/desk/live`, route => route.fulfill({json: {
    as_of: '2026-09-09T14:00:00Z', market_status: {open: true, phase: 'open'},
    quotes: {AAPL: {last: 102, bar: '2026-09-09T13:45:00Z'}, HOLDME: {last: 82, bar: '2026-09-09T13:45:00Z'}},
  }}))
  // The board row prints the move beside a current session price, so the row needs one: a
  // regular-session midpoint observed as the page loads (the desk's clock is real time here).
  await page.route(`**/market/${USER}/desk/session-prices`, route => {
    const at = new Date().toISOString()
    return route.fulfill({json: {session: 'regular', as_of: at, signal_scope: 'regular-session', quotes: {
      AAPL: {price: 102, bid: 101.9, ask: 102.1, at, feed: 'iex', indicative: false, session: 'regular', status: 'fresh',
        valid_until: new Date(Date.parse(at) + 60_000).toISOString(), reason: 'Quoted midpoint'},
    }}})
  })
  const latest = deskRecord()
  for (let i = 0; i < 12; i += 1) {
    const t = `T${String(i).padStart(2, '0')}`
    latest.grades[t] = {
      grade: 'A', votes: 1, stances: { fundamental: 1, technical: 0, sentiment: 0, value: 0, rotation: 0 },
      score: 1 - i / 20, side: 'ai', headline: `name ${i}`, reason: 'F holds',
    }
  }
  latest.grades.HOLDME = {
    grade: 'C', votes: 1, stances: { fundamental: -1, technical: 0, sentiment: 0, value: 0, rotation: 0 },
    score: 0.2, side: 'ai', headline: 'weak hold', reason: 'F slips',
  }
  // The day's move is against the record's close for the name.
  latest.actions = latest.actions.map(a => a.ticker === 'AAPL' ? {...a, last_close: 100} : a)
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {
    as_of: '2026-09-09T14:00:00Z', equity: 104200, cash: 12000, orders: [], plan: paperPlan([]),
    positions: [
      {symbol: 'AAPL', qty: 60, avg_entry_price: 91.25, current_price: 102, market_value: 6120, unrealized_pl: 645},
      {symbol: 'HOLDME', qty: 40, avg_entry_price: 80, current_price: 82, market_value: 3280, unrealized_pl: 80},
    ],
  }}))
  await page.goto('/#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  // AAPL (held, quoted at 102 against a 100 close) reads its move beside the price.
  await expect(board.locator('tr', {hasText: 'AAPL'}).first()).toContainText(/\$102\.00\s?regular/)
  await expect(board.locator('tr', {hasText: 'AAPL'}).first()).toContainText('↑ +2.0%')
  // HOLDME is a held C-grade name: on the book view with AAPL, and nothing else there.
  await expect(board.locator('tr', {hasText: 'HOLDME'})).toBeVisible()
  await expect(board.getByLabel('HOLDME strategy intent')).toHaveText('HOLD')
  await expect(board.locator('tbody tr', {hasText: 'NVDA'})).toHaveCount(0)
  await expect(board.locator('tbody tr')).toHaveCount(2)
  // On the full list the held names rank above the unheld ones, whatever their grade.
  await allNames(page)
  await expect(board.locator('tbody tr td:nth-child(2) button').nth(0)).toHaveText('AAPL')
  await expect(board.locator('tbody tr td:nth-child(2) button').nth(1)).toHaveText('HOLDME')
})

// session, what came next, and the name's own backtest against holding it
// and the benchmark.
test('drills into a name’s own history', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()

  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await expect(dialog).toBeVisible()
  await dialog.getByText('Score, log & backtest', {exact: true}).click()
  await expect(dialog.getByText('Annualized mean while an A')).toBeVisible()
  await expect(dialog.getByText('Annualized mean while not')).toBeVisible()
  await expect(dialog.getByText('Sessions it was an A')).toBeVisible()
  await expect(dialog.getByText('41 of 60')).toBeVisible()
  await expect(dialog.getByText('Position changes')).toBeVisible()
  // Recorded evidence leads; unverified historical model claims require opening their archive.
  await dialog.getByText('All the evidence', {exact: true}).click()
  await expect(dialog.getByRole('group', {name: 'All the evidence'}).getByRole('heading', {name: 'Evening analysis · 2026-09-08'})).toBeVisible()
  await expect(dialog.getByText('growing earnings with the trend intact', { exact: false })).not.toBeVisible()
  await dialog.getByText('Archived model commentary · unverified', {exact: true}).click()
  await expect(dialog.getByText('growing earnings with the trend intact', { exact: false })).toBeVisible()
  // The live technical read is the model's plain words over the live tape.
  await expect(dialog.getByText('resistance is a swing high above', { exact: false })).toBeVisible()
  await expect(dialog.getByText('The last 2 sessions')).toBeVisible()
  // Each session shows which analysts voted, and the row the desk actually
  // wrote that night is marked as said.
  await expect(dialog.getByText('F+ T+ V·').first()).toBeVisible()
  await expect(dialog.getByText('published', { exact: true })).toHaveCount(1)
  await expect(dialog.getByText('a steady AI leader')).toBeVisible()
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).not.toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Reaction timing, extracted tone and precise financials must not imply a release date or revision.
test('shows accurately dated earnings evidence in the drill-down', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()

  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await expect(dialog).toBeVisible()
  await dialog.getByText('All the evidence', {exact: true}).click()
  await expect(dialog.getByText('Latest stored earnings read')).toBeVisible()
  await expect(dialog.getByText('Market reaction on or after Sep 13, 2026')).toBeVisible()
  await expect(dialog.getByText('guidance positive · demand positive · pricing neutral or not stated · capex neutral or not stated')).toBeVisible()
  await expect(dialog.getByText('record June-quarter revenue', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/Revenue \$109,417M/)).toBeVisible()
  await expect(dialog.getByText(/EPS \$2\.02/)).toBeVisible()
  await expect(dialog.getByText(/Net income \$29,789M/)).toBeVisible()
  await expect(dialog.getByText(/Gross margin 50\.1%/)).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Older extraction versions must not present financials with known loss-sign defects as usable evidence.
test('withholds legacy earnings figures and retains signed precision after retry', async ({ page }) => {
  let corrected = false
  await page.route(`**/desk/earnings/AAPL`, route => {
    return route.fulfill({ json: { user_id: USER, symbol: 'AAPL', read: {
      reaction_date: '2025-12-20', guidance: 0, demand: 0, pricing: 0, capex: 0,
      supply_constrained: 0, quarter_end: '2025-09-30', revenue_usd_m: 101.234,
      eps_usd: -0.42, net_income_usd_m: -22.8, gross_margin_pct: null,
      summary: null, prompt_version: corrected ? 'release_tone/3' : 'release_tone/2', same_day: false,
    } } })
  })
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await dialog.getByText('All the evidence', {exact: true}).click()
  await expect(dialog.getByText('Financial figures withheld: this older extraction may misreport losses.')).toBeVisible()
  await expect(dialog.getByText(/Net income/)).toHaveCount(0)
  await expect(dialog.getByText(/Market reaction on or after Dec 20, 2025/)).toBeVisible()
  corrected = true
  await dialog.getByRole('button', { name: 'Refresh earnings' }).click()
  await expect(dialog.getByText(/Net income −\$22\.8M/)).toBeVisible()
  await expect(dialog.getByText(/Revenue \$101\.234M/)).toBeVisible()
  await expect(dialog.getByText(/Quarter ending Sep 30, 2025/)).toBeVisible()
  await expect(dialog.getByText(/EPS −\$0\.42/)).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A failed request is recoverable and distinct from a successful response with no stored release.
test('retries an unavailable earnings read without disguising it as no release', async ({ page }) => {
  let available = false
  await page.route(`**/desk/earnings/AAPL`, route => {
    return available ? route.fulfill({ json: { read: null } }) : route.abort('failed')
  })
  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await dialog.getByText('All the evidence', {exact: true}).click()
  await expect(dialog.getByText('Earnings read unavailable.')).toBeVisible()
  available = true
  await dialog.getByRole('button', { name: 'Retry earnings' }).click()
  await expect(dialog.getByText('No earnings read stored for this name.')).toBeVisible()
})

// A covered name that is not in the book is still graded every evening, and
// its drill-down must fetch a live technical read on demand (a fresh quote,
// not the candle's snapshot): the short/medium/long horizons render beside
// the model's prose instead of being hidden behind it.
test('drills into a covered name outside the book and sees its live horizons', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/?deskDetails=1#desk')
  await allNames(page)
  await page.getByLabel('Ranked stocks and cash').getByRole('button', { name: 'MSFT', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'MSFT history' })
  await expect(dialog).toBeVisible()
  // The evening grade is explicit; original prose remains accessible as archived wording.
  const recorded = dialog.getByRole('region', {name: 'Evening analysis', exact: true})
  await expect(recorded).toContainText('Recorded grade C')
  await expect(recorded.getByText('expensive and the trend is quiet', {exact: true})).not.toBeVisible()
  await recorded.getByText('Original recorded wording', {exact: true}).click()
  await expect(recorded.getByText('expensive and the trend is quiet', {exact: true})).toBeVisible()
  // The drill-down shows the same grade as the list: the record's C, dated to its close.
  await expect(dialog.getByRole('region', {name: 'Latest available grade', exact: true}).getByLabel('Latest grade value')).toHaveText('C')
  await expect(dialog.getByRole('region', {name: 'Latest available grade', exact: true})).toContainText('at the 2026-09-08 close')
  await dialog.getByText('All the evidence', {exact: true}).click()
  await expect(dialog.getByText('Technical read')).toBeVisible()
  await dialog.getByText('All readings, by timeframe').click()
  await expect(dialog.getByText('Daily chart', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Weekly chart', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Longer-term reference levels')).toBeVisible()
  await expect(dialog.getByText('resistance is a swing high above', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/Technical rank at the available candle/)).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A holding the desk does not grade is an explicit review state, not a sell: the paper
// account holds it, no order names it, and the row says so without a grade.
test('an uncovered holding is a review state, not a sell', async ({ page }) => {
  await page.route(`**/api/v1/market/${USER}/desk/paper`, route => route.fulfill({json: {
    as_of: '2026-09-08T20:00:00Z', equity: 104200, cash: 12000, orders: [], plan: paperPlan([]),
    positions: [{symbol: 'IREN', qty: 100, avg_entry_price: 35.2, current_price: 40, market_value: 4000, unrealized_pl: 480}],
  }}))
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/?deskDetails=1#desk')
  const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
  await expect(board.getByLabel('IREN strategy intent')).toHaveText('HOLD')
  await expect(board.getByLabel('IREN action status')).toHaveText('Not in the book; no order tonight')
  await expect(board.getByLabel('IREN displayed grade')).toHaveText('—')
  await expect(board.getByLabel('IREN size')).toHaveText('—')
  const details = await stockDetails(page, 'IREN')
  await expect(details.getByLabel('IREN position')).toContainText('100 sh · $4,000 · 3.8%')
  await expect(details.getByLabel('IREN grade')).toContainText('Grade —')
  await expect(page.getByLabel('Today')).toContainText('No paper orders.')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The method panel attributes the learner only when the saved decision identifies its input.
test('explains analyst weights and identifies the recorded expectations model', async ({ page }) => {
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({json: {
    latest: {...deskRecord(), provenance: {rule: {inputs: ['expectations-gap']}}},
  }}))
  await page.goto('/?deskDetails=1#desk')
  await strategyDetails(page)
  await page.getByText('How ranking and sizing work', {exact: true}).click()
  await expect(page.getByText('Current voting rules:')).toContainText('rotation carries half a vote')
  await expect(page.getByText('This evening decision includes the LightGBM expectations gap:')).toContainText('model-estimated revenue growth minus a relative-P/S valuation proxy')
  await expect(page.getByText('This evening decision includes the LightGBM expectations gap:')).toContainText('not a forecast of a future share price')
  await expect(page.getByText('Valuation stays at the evening reading:')).toBeVisible()
})

// A live drill-down must stay coherent as the candle moves: when the
// fifteen-minute bar turns, the price, the technical rank AND the analysis
// all move together. Before the fix the read was fetched once on open and
// never again, so a new candle updated the price and rank while the prose
// and horizon lines described an older price — and the header's "live"
// timestamp was the candle's, not the analysis's. The fetch is keyed on the
// candle's bar, the same identifier the backend's per-candle cache uses.
test('a new candle re-reads the analysis alongside the fresh price', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  // A fake clock so one fifteen-minute candle can be advanced in a test.
  await page.clock.install({ time: new Date('2026-09-08T19:59:00Z') })
  let candle = 0
  await page.route(`**/api/v1/market/${USER}/desk/live`, route => {
    const first = candle === 0
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        as_of: first ? '2026-09-08T20:00:00Z' : '2026-09-08T20:15:00Z',
        quotes: {
          AAPL: { symbol: 'AAPL', last: first ? 102 : 110, open: 101, high: 103, low: 100.5, bar: first ? '20:00' : '20:15', as_of: first ? '2026-09-08T20:00:00Z' : '2026-09-08T20:15:00Z' },
          NVDA: { symbol: 'NVDA', last: 130, open: 128, high: 132, low: 127, bar: first ? '20:00' : '20:15', as_of: '2026-09-08T20:00:00Z' },
        },
        technical_detail: {
          AAPL: { now: first ? 0.9 : 0.2, short: {}, medium: {}, long: {} },
        },
      }),
    })
  })
  let refetchForNewCandle = 0
  await page.route(`**/api/v1/market/${USER}/desk/live/read/*`, route => {
    // The read is served for the candle that is current when the request is
    // made, not for a count of requests: on open the effect may run once or
    // twice (the live state starts empty, so the bar arrives a moment later)
    // and both of those must still be the first candle's read.
    const first = candle === 0
    if (!first) refetchForNewCandle += 1
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        symbol: 'AAPL',
        read: first
          ? 'Support holds beneath the rally.'
          : 'A breakdown has broken support — the rally is over.',
        lines: {
          short: [first ? '12.6% above the 21-day EMA' : '4.1% below the 21-day EMA'],
          medium: [first ? 'weekly trend up' : 'weekly trend down'],
          long: [first ? '2.3% below the 200-day EMA' : '11.2% below the 200-day EMA'],
        },
        now: first ? 0.9 : 0.2,
        data_at: first ? '2026-09-08T19:45:00Z' : '2026-09-08T20:00:00Z',
        stale: false,
        read_at: first ? '2026-09-08T20:03:00Z' : '2026-09-08T20:18:00Z',
      }),
    })
  })

  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).last().click()

  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await expect(dialog).toBeVisible()
  await dialog.getByText('All the evidence', {exact: true}).click()
  const stamp = dialog.locator('h4', { hasText: 'Technical read' })
  await expect(dialog.getByText('Support holds beneath the rally.', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/\$102/).first()).toBeVisible()
  await expect(dialog.getByText(/Technical rank at the available candle/)).toContainText('90')
  await expect(stamp).toContainText('candle from Sep 8')
  await expect(stamp).toContainText('explanation generated')
  const firstTime = (await stamp.textContent() ?? '').match(/\d{1,2}:\d{2}/)?.[0]
  expect(firstTime).toBeTruthy()

  // One candle later: price 110, rank 20, and the analysis itself is
  // re-read — the prose, the horizon lines and the header's timestamp all
  // move, and the read endpoint was called a second time.
  candle = 1
  await page.clock.fastForward('15:00')
  await expect(dialog.getByText('A breakdown has broken support — the rally is over.', { exact: false })).toBeVisible()
  await dialog.getByText('All readings, by timeframe').click()
  await expect(dialog.getByText('4.1% below the 21-day EMA', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/\$110/).first()).toBeVisible()
  await expect(dialog.getByText(/Technical rank at the available candle/)).toContainText('20')
  await expect(stamp).toContainText('candle from Sep 8')
  const secondTime = (await stamp.textContent() ?? '').match(/\d{1,2}:\d{2}/)?.[0]
  expect(secondTime).toBeTruthy()
  expect(secondTime).not.toBe(firstTime)
  expect(refetchForNewCandle).toBe(1)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The autopsy reads the person's own documents: what keeps repeating, what
// it has cost, and the plan. It is one click from the board.
test('analyzes the person’s own trading from their documents', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', { name: 'Analyze my trading' }).click()

  const review = page.getByText('Your trading, in review')
  await expect(review).toBeVisible()
  await expect(page.getByRole('heading', { level: 4, name: 'Patterns' })).toBeVisible()
  await expect(page.getByText('You sell into the first green day', { exact: false })).toBeVisible()
  await expect(page.getByText('What it has cost')).toBeVisible()
  await expect(page.getByText('Frequent small exits', { exact: false })).toBeVisible()
  await expect(page.getByText('selling into the first green day')).toBeVisible()
  await expect(page.getByText('writing the exit rule before entering')).toBeVisible()
  await expect(page.getByText('sizing by grade')).toBeVisible()
  await expect(page.getByText('Read from 3 passages')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A grade must expire while the page is open, even if a cached endpoint repeats it.
// A missing-document response gives one clear next step without duplicated instructions.
test('trading review shows the empty-document response', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/trading/autopsy', route => route.fulfill({json: {result: null, reason: 'Share a statement or journal in chat, then retry.'}}))
  await page.goto('/?deskDetails=1#desk')
  await page.getByRole('button', {name: 'Analyze my trading'}).click()
  await expect(page.getByText('Share a statement or journal in chat, then retry.', {exact: true})).toBeVisible()
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Funding labels follow the stored artifact, never the latest deployed simulator alone.
test('cash-limited performance is distinguished from legacy simulated borrowing', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  const bt = latest.curve!.backtest!
  bt.strategy_policy = 'cash-bounded-breakout-rotation/3'
  bt.fundamentals_source = 'fundamentals-features/2'
  bt.funding_model = 'cash-at-fill-v1'
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({latest, changes: null}),
  }))
  await page.goto('/?deskDetails=1#desk')
  await simulationDetails(page)
  await expect(page.getByLabel('Historical simulation summary')).toContainText('cash capped after costs')
  await expect(page.getByLabel('Historical simulation summary')).not.toContainText('legacy simulation permits borrowing')
  await expect(page.getByText('closing sales cannot fund earlier buys', {exact: false})).toBeVisible()
  await expect(page.getByText('Legacy simulation under review', {exact: false})).not.toBeVisible()
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Actual receipts must expose dated evidence and keep legacy missing fields unknown.
test('execution receipts distinguish decisions, fills and historical submissions', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: {...latest, paper: {...latest.paper, settled: [
        {symbol: 'AAPL', side: 'buy', qty: 10, filled: 10, filled_price: 102, status: 'filled', decision_shortfall_bps: 200,
          execution: {decision_at: '2026-09-07T23:45:29Z', submitted_at: '2026-09-08T08:03:00Z', filled_at: '2026-09-09T13:33:06Z',
            reference_price: 100, reference_session: '2026-09-04', reference_source: 'daily panel close'}},
        {symbol: 'NVDA', side: 'sell', qty: 10, filled: 3, filled_price: 91, status: 'partial'},
      ]}}, sessions: ['2026-09-08'],
    }),
  }))
  await page.route(`**/api/v1/market/${USER}/desk/paper`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({reason: 'unreachable'}),
  }))
  await page.goto('/?deskView=research#desk')
  await page.getByRole('button', {name: 'Show practice account details'}).click()
  const account = page.locator('section', {has: page.getByRole('heading', {name: /^Practice account/})})
  await expect(account).toContainText('Recorded plan:')
  await expect(account).not.toContainText('sizes reset')
  await expect(account).not.toContainText('Orders waiting for the open')
  await account.locator('summary', {hasText: 'Execution receipts'}).click()
  const receipts = account.locator('details')
  await expect(receipts).toContainText('Sep 9, 2026, 09:33:06 AM ET')
  await expect(receipts).toContainText('10 of 10 shares filled at $102.00 average')
  await expect(receipts).toContainText('Decision-price drift: +200.0 bp')
  await expect(receipts).toContainText('3 of 10 shares filled at $91.00 average')
  await expect(receipts).not.toContainText('not recorded')
  await expect(receipts).not.toContainText('unavailable')
  await expect(receipts.locator('li').last()).not.toContainText('Order completion time:')
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A new policy must distinguish enabled automation from a historical execution receipt.
test('FOMC policy explains activation without inventing an executed reduction', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: deskRecord(), sessions: ['2026-09-08'],
      event_policy: {enabled: true, version: 'fomc-3-session-weakness/1', evaluation_since: '2026-06-18'},
    }),
  }))
  await page.goto('/?deskDetails=1#desk')
  await strategyDetails(page)
  const banner = page.getByRole('region', {name: 'FOMC exposure policy'})
  await expect(banner).toContainText('FOMC · decision missing')
  await expect(banner).toContainText('does not confirm any reduction')
  await expect(banner).toContainText('practice account below')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// An active event must not expose ordinary rebalance targets as executable fill rows.
test('FOMC reduction takes priority over regular target execution', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: {...deskRecord(), event_risk: {
        session: '2026-09-11', enabled: true, factor: 0.5, calendar_known: true,
        decision_date: '2026-09-16', execution_pending: true,
      }}, sessions: ['2026-09-11'],
      event_status: {as_of: new Date().toISOString(), stale: false, active: true, planning_paused: true,
        status: 'reduction pending', pending_orders: 0, policy: {session: '2026-09-11', factor: 0.5, calendar_known: true, decision_date: '2026-09-16'}},
      event_policy: {enabled: true, version: 'fomc-3-session-weakness/1', evaluation_since: '2026-06-18'},
    }),
  }))
  await page.goto('/?deskDetails=1#desk')
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: 'Plan status'})).toBeVisible()
  await expect(page.getByRole('button', {name: 'record fill', exact: true})).toHaveCount(0)
  await strategyDetails(page)
  await expect(page.getByRole('region', {name: 'FOMC exposure policy'})).toContainText('reduction triggered or still in force')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The target board must take its content height instead of clipping rows inside a flex item.
test('target rows are not hidden inside a vertically collapsed section', async ({ page }) => {
  await page.goto('/?deskDetails=1#desk')
  await allNames(page)
  const board = page.getByLabel('Stocks and cash', {exact: true})
  await expect(board.locator('tbody tr')).toHaveCount(3)
  const size = await board.evaluate(element => ({height: element.clientHeight, content: element.scrollHeight}))
  expect(size.content).toBeLessThanOrEqual(size.height)
})

// A cash-limited event ending must expose its unbought shares as an outcome.
test('cash-limited FOMC restoration never claims the remainder was filled', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: {...deskRecord(), event_risk: {
        session: '2026-09-17', enabled: true, factor: 1, calendar_known: true,
        decision_date: '2026-09-16', execution_pending: false,
        outcome: {session: '2026-09-17', status: 'cash-limited', unrestored: {AAPL: 5}},
      }}, event_policy: {enabled: true, version: 'fomc-3-session-weakness/2', evaluation_since: '2026-06-18'},
    }),
  }))
  await page.goto('/?deskDetails=1#desk')
  await strategyDetails(page)
  const banner = page.getByRole('region', {name: 'FOMC exposure policy'})
  await expect(banner).toContainText('AAPL 5 shares unbought')
  await expect(banner).toContainText('unfilled quantities, not restored positions')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A brand-new account has no record yet: the page must explain what it is
// and what happens next, not render a blank board.
test('an empty record becomes the getting-started guide', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`**/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      latest: null,
      summary: undefined,
      sessions: [],
    }),
  }))
  await page.goto('/?deskDetails=1#desk')

  await expect(page.getByText('No evening decision is available yet')).toBeVisible()
  await expect(page.getByText('Check after the next trading session.', { exact: false })).toBeVisible()
  await expect(page.getByText('No decision on file yet')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Displaying a hypothetical stop must never turn its breach into a sell instruction.
test('the ticker panel explains the grade move and preserves every recorded recommendation', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  // The same release re-read under a new prompt: named as a data revision.
  ;(latest.grades.AAPL as {revision?: unknown}).revision = {accession: '0001-19', reaction_date: '2026-09-02',
    prompt_version: ['release_tone/1', 'release_tone/2'], fields: {guidance: [1, 0.8], demand: [1, 0.8]}}
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  const observation = (id: string, recorded: string, grade: string, allocation: number) => ({
    id, recorded_at: recorded, bar: '2026-09-08T19:45:00Z', grade, allocation, allocation_change: null, model_weight: 1,
    event_paused: false, entry_state: 'trend', price: 100, version: 'policy/2', policy_sha256: 'abcdefgh', stock_total_return: null,
  })
  await page.route('**/desk/history/AAPL', route => route.fulfill({json: {
    ticker: 'AAPL', horizon: 20, asof: '2026-09-08', backtest: null,
    rows: [
      {date: '2026-09-04', grade: 'B', votes: 1, stances: {fundamental: 1, technical: 0, sentiment: 0, value: 0, rotation: -1}, exposure: 1, confidence: .5, forward: null, forward_residual: null, said: true},
      {date: '2026-09-08', grade: 'A', votes: 3.2, stances: {fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: -1}, exposure: 1, confidence: .5, forward: null, forward_residual: null, said: true},
    ],
    recommendations: {status: 'available', outcomes: {status: 'awaiting_daily_validation'}, invalid_archives: 0, older_records_not_shown: false,
      observations: [
        observation('c', '2026-09-08T18:45:10Z', 'A', .2),
        observation('b', '2026-09-08T18:30:10Z', 'A', .2),
        observation('a', '2026-09-08T18:15:10Z', 'B', .1),
      ]},
  }}))
  await page.route('**/desk/live', route => route.fulfill({json: {as_of: '2026-09-08T20:00:00Z', quotes: {
    AAPL: {symbol: 'AAPL', last: 100, bar: '2026-09-08T19:45:00Z'},
  }, technical_detail: {AAPL: {now: .8, short: {}, medium: {}, long: {}, walls: {
    expiry: '2026-09-18', through: '2026-10-16', fetched_at: '2026-09-16T12:45:00Z',
    put_wall: 95, call_wall: 110, put_wall_oi: 20000, call_wall_oi: 36000, net_gamma: 0, put_wall_distance: -.05, call_wall_distance: .1,
  }}}}}))
  await page.goto('/#desk')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
  const move = page.getByRole('region', {name: 'Why the grade moved'})
  await expect(move).toContainText('Moved in tonight’s decision')
  await expect(move).toContainText('Price trend neutral → for: daily trend up')
  await expect(move).toContainText('Evening votes use a three-session confirmation rule')
  await expect(move).toContainText('the latest readings may differ from those that established a vote')
  await expect(move).toContainText('Recorded vote changes do not establish what caused a price move')
  await expect(move).toContainText('Recorded re-read marker: market reaction on or after 2026-09-02; reader release_tone/2: guidance 1 → 0.8 · demand 1 → 0.8')
  await expect(page.getByRole('dialog', {name: / history$/}).getByLabel('In short')).toContainText('growing earnings, steady trend')
  await page.getByRole('dialog', {name: / history$/}).getByText('All the evidence', {exact: true}).click()
  await expect(move).not.toContainText('Price was not an input')
  const evening = page.getByRole('dialog', {name: / history$/}).locator('div', {hasText: /^Evening analysis/}).first()
  await expect(evening).toContainText('Price trend + for')
  await expect(evening).toContainText('Growth & margins + for')
  const options = page.getByRole('dialog', {name: / history$/}).getByLabel('Stored option OI levels', {exact: true})
  await expect(options).toHaveCount(2)
  await expect(options.first()).toContainText('Calculation provenance unavailable; stored levels withheld')
  await page.getByText('Score, log & backtest', {exact: true}).click()
  const log = page.getByRole('table', {name: 'Recommendation timeline'})
  await expect(log.locator('tbody tr')).toHaveCount(3)
  await expect(log.locator('tbody tr').nth(0)).toContainText('2:45:10 PM')
  await expect(log.locator('tbody tr').nth(1)).toContainText('2:30:10 PM')
  await expect(log.locator('tbody tr').nth(2)).toContainText('2:15:10 PM')
  await expect(page.getByRole('region', {name: 'Recorded research readings'})).toContainText('Personal Buy/Sell decisions and account trades are not recorded in this history.')
  await expect(options.last()).toContainText('Calculation provenance unavailable; stored levels withheld')
  await expect(options.last()).not.toContainText('$95.00')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})


// Details is two views. Plan holds the rankings, the plan rows and what
// changed; Research holds the gate, execution quality, forward evidence,
// the ML shadow and the practice account. The simple page carries neither
// the ML comparison nor the board simulation any more.
test('details splits into plan and research and the simple page carries only decisions', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET' ? route.fulfill({json: {messages: [], conversations: []}}) : route.fulfill({json: {}}))
  await page.goto('/#desk')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  // The first line says what the desk is doing and whether there is anything to do.
  const today = page.getByLabel('Today')
  await expect(today).toContainText(/XNYS (regular session scheduled open|regular session closed|closed by schedule)|Before XNYS regular session/)
  await expect(today).toContainText('Paper orders: 1 planned.')
  await expect(page.getByLabel('ML forward comparison')).toHaveCount(0)
  await expect(page.getByLabel('Board simulation')).toHaveCount(0)
  // A row opens in place with the name's orders, position and grade.
  const details = await stockDetails(page, 'AAPL')
  await expect(details.getByRole('button', {name: 'Chart and full history'})).toBeVisible()
  await expect(details.getByLabel('AAPL grade', {exact: true})).toContainText('Grade A · 2026-09-08 close')
  await expect(details.getByLabel('AAPL grade', {exact: true})).toContainText('growing earnings, steady trend')
  await page.goto('/?deskDetails=1#desk')
  await expect(page.getByRole('heading', {name: /^Stock rankings/})).toBeVisible()
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: /^What changed/})).toBeVisible()
  await strategyDetails(page)
  await expect(page.getByRole('heading', {name: 'Plan status'})).toBeVisible()
  await expect(page.locator('summary', { hasText: 'Paper account' })).toBeVisible()
  await page.getByRole('button', {name: 'Research', exact: true}).click()
  await expect(page.getByRole('button', {name: 'Show practice account details', exact: true})).toBeVisible()
  await expect(page.getByLabel('What the research accounts are')).toContainText('Simulated accounts, separate from your portfolio')
  await expect(page.getByRole('heading', {name: /^Stock rankings/})).toHaveCount(0)
  await page.getByRole('button', {name: 'Back to the desk', exact: true}).click()
  await expect(page.getByRole('heading', {name: /^Stock rankings/})).toBeVisible()
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})


// The page must work on a phone: at 400px nothing scrolls sideways on
// the board, with its stock diagnostics or guide open, on the research page, or
// with a name panel open. Tables may scroll inside their own box.
const noSidewaysScroll = async (page: Page, where: string) => {
  const widths = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
    main: (document.querySelector('main') as HTMLElement | null)?.scrollWidth ?? 0}))
  expect(widths.scroll, `${where}: page`).toBeLessThanOrEqual(widths.client + 1)
  expect(widths.main, `${where}: main`).toBeLessThanOrEqual(widths.client + 1)
}
test('the desk fits a phone without sideways scrolling', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/**', route => route.request().method() === 'GET' ? route.fulfill({json: {messages: [], conversations: []}}) : route.fulfill({json: {}}))
  await page.setViewportSize({width: 400, height: 800})
  await page.goto('/#desk')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await noSidewaysScroll(page, 'stocks')
  // Reasons remain available on expansion without cluttering every stock row.
  const scroller = page.getByRole('table', {name: 'Ranked stocks and cash'}).locator('xpath=ancestor::div[contains(@class,"overflow-auto")]')
  await scroller.evaluate(el => el.scrollTo(0, 0))
  await expect(page.getByLabel('AAPL grade', {exact: true})).toHaveCount(0)
  await page.getByRole('button', {name: 'details for AAPL', exact: true}).click()
  await expect(page.getByLabel('AAPL grade', {exact: true})).toBeVisible()
  await expect(page.getByText('Chart and full history')).toBeVisible()
  await noSidewaysScroll(page, 'row open')
  await page.screenshot({path: 'test-results/desk-consolidated-mobile.png', fullPage: true})
  await page.goto('/?deskDetails=1#desk')
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await noSidewaysScroll(page, 'details open')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
  const dialog = page.getByRole('dialog', {name: 'AAPL history'})
  await expect(dialog).toBeVisible()
  await noSidewaysScroll(page, 'name panel')
  await page.getByRole('button', {name: 'Close', exact: true}).click()
  await page.getByRole('button', {name: 'Research', exact: true}).click()
  await expect(page.getByRole('button', {name: 'Show practice account details', exact: true})).toBeVisible()
  await page.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true }))
  await noSidewaysScroll(page, 'research')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// An allowlisted account that is not the admin still gets the Desk icon in
// the sidebar (the page was granted via desk_access but the icon was gated
// on is_admin alone); a plain guest sees neither the icon nor the admin.
test('the Desk icon appears for an allowlisted account and stays hidden for a guest', async ({page}) => {
  const record = deskRecord()
  const deskBody = JSON.stringify({
    latest: record, summary: {session: record.session, counts: {A: 1, B: 1}, gross: 0.8, names: ['AAPL', 'NVDA'], flags: []},
    changes: {since: '2026-09-04', upgrades: [], downgrades: [], orders: [], flags_raised: [], flags_cleared: []},
    sessions: [record.session],
  })
  await page.route('**/api/v1/auth/session', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({authentication_required: true, user_id: 'vjmallya', expires_at: '2026-09-09T00:00:00Z', is_admin: false, desk_access: true}),
  }))
  await page.route('**/api/v1/conversations/vjmallya', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({conversations: []}),
  }))
  await page.route('**/api/v1/market/vjmallya/desk', route => route.fulfill({
    status: 200, contentType: 'application/json', body: deskBody,
  }))
  await page.goto('/')
  await expect(page.getByRole('button', {name: 'Desk', exact: true})).toBeVisible()
  await page.getByRole('button', {name: 'Desk', exact: true}).click()
  await expect(page.getByRole('table', {name: 'Ranked stocks and cash'})).toBeVisible()
  await page.evaluate(() => localStorage.removeItem('anios_conversation_id:vjmallya'))
  await page.route('**/api/v1/auth/session', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({authentication_required: true, user_id: 'a.guest', expires_at: '2026-09-09T00:00:00Z', is_admin: false}),
  }))
  await page.reload()
  await expect(page.getByRole('button', {name: 'Desk', exact: true})).toHaveCount(0)
})


// This drill-down test checks accessible readings; recorded-chart.spec.ts also
// observes the real canvas. Only the desk's daily and weekly timeframes are offered.
test('the ticker chart draws the desk’s own timeframes and mirrors its readings in text', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  // A retained quote must disclose its original time rather than claim to be live today.
  await page.clock.install({time: new Date('2026-09-24T14:00:00Z')})
  // Some browser environments expose a POSIX locale tag that Intl rejects;
  // the chart must format its axis without throwing in that environment.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'language', {value: 'en-US@posix', configurable: true})
  })
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {latest, sessions: [latest.session]}}))
  await page.route('**/desk/history/AAPL', route => route.fulfill({json: {
    ticker: 'AAPL', horizon: 20, asof: '2026-09-08', backtest: null,
    // Every expected marker needs an actual fixture candle; gap rejection is tested separately.
    rows: [
      {date: '2026-07-06', grade: 'C', votes: -1, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, said: true},
      {date: '2026-07-07', grade: 'B', votes: 1, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, said: true},
      {date: '2026-07-08', grade: 'A', votes: 3.2, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, said: false},
      {date: '2026-07-09', grade: 'B', votes: 1, stances: {}, exposure: 1, confidence: .5, forward: null, forward_residual: null, said: false},
    ],
    recommendations: {status: 'available', outcomes: {status: 'awaiting_daily_validation'}, invalid_archives: 0, older_records_not_shown: false, observations: []},
  }}))
  // Thirty sessions of a gentle rise, with every line the daily view draws.
  const days: string[] = []
  for (let cursor = new Date(Date.UTC(2026, 6, 6)); days.length < 30; cursor.setUTCDate(cursor.getUTCDate() + 1)) {
    if (cursor.getUTCDay() !== 0 && cursor.getUTCDay() !== 6) days.push(cursor.toISOString().slice(0, 10))
  }
  days[days.length - 1] = '2026-09-08'
  const at = (base: number) => days.map((_, i) => Number((base + i * 0.5).toFixed(2)))
  let includeQuoteTime = true
  let lastClose = 115
  let delayNextChart = false
  let releaseChart: (() => void) | undefined
  // Keep candle and overlay snapshots together while simulating independently polled quotes.
  const chartBody = (timeframe: string) => ({
    user_id: USER, ticker: 'AAPL', timeframe, timeframes: ['daily', 'weekly'], adjusted: true,
    quote_bar: includeQuoteTime ? '2026-09-08T19:45:00Z' : null,
    last_bar_complete: timeframe === 'daily',
    basis: 'adjusted for splits and dividends, the basis the desk grades on',
    sessions: days.length,
    bars: days.map((date, i) => ({date, open: 100 + i * 0.5, high: Math.max(101 + i * 0.5, i === days.length - 1 ? lastClose : 0), low: 99 + i * 0.5, close: i === days.length - 1 ? lastClose : 100.5 + i * 0.5, volume: 1000})),
    overlays: timeframe === 'weekly'
      ? {ema9: at(99), ema21: at(98)}
      : {ema9: at(100), ema21: at(99), ema50: at(97), ema200: at(94), sma200: at(93), band_lower: at(96), band_middle: at(100), band_upper: at(104)},
    levels: {swing_low: at(95), swing_high: at(110), high_52w: at(120), low_52w: at(80), range60_high: at(115), range60_low: at(90)},
  })
  await page.route('**/desk/chart/AAPL*', async route => {
    const timeframe = new URL(route.request().url()).searchParams.get('timeframe') ?? 'daily'
    const payload = chartBody(timeframe)
    if (delayNextChart) {
      delayNextChart = false
      await new Promise<void>(resolve => { releaseChart = resolve })
    }
    return route.fulfill({json: payload})
  })
  await page.route('**/desk/live', route => route.fulfill({json: {as_of: '2026-09-08T20:00:00Z', quotes: {
    AAPL: {symbol: 'AAPL', last: 100, bar: '2026-09-08T19:30:00Z'},
  }}}))
  await page.goto('/#desk')
  await page.getByRole('table', {name: 'Ranked stocks and cash'}).getByRole('button', {name: /^AAPL/}).click()
  await expect(page.getByRole('dialog', {name: 'AAPL history'})).toBeVisible()

  // The chart leads the panel: visible without opening anything, and ahead
  // of the written reasoning in the document, so a phone shows it first.
  const chart = page.getByRole('region', {name: 'AAPL price chart'})
  await expect(chart).toBeVisible()
  const order = await page.evaluate(() => {
    const c = document.querySelector('[aria-label$="price chart"]')
    const why = document.querySelector('[aria-label="Why the grade moved"]')
    if (!c || !why) return 'missing'
    return c.compareDocumentPosition(why) & Node.DOCUMENT_POSITION_FOLLOWING ? 'chart first' : 'chart later'
  })
  expect(order).toBe('chart first')
  await expect(chart.getByTestId('ticker-chart-canvas').locator('canvas').first()).toBeVisible()

  // The two scored timeframes plus the fifteen-minute view are on offer.
  const frames = chart.getByRole('group', {name: 'Chart timeframe'})
  await expect(frames.getByRole('button')).toHaveCount(3)
  await expect(frames.getByRole('button', {name: 'D'})).toHaveAttribute('aria-pressed', 'true')
  await expect(chart).toContainText('30 sessions loaded; pan or zoom for history.')

  // The daily readings are mirrored in text, with distance from price.
  await expect(chart).toContainText('21-session EMA')
  await expect(chart).toContainText('200-session EMA')
  await expect(chart).toContainText('Upper Bollinger band')
  await expect(chart).toContainText('252-session high')
  await expect(chart).toContainText('15-minute bar starting Sep 8, 2026, 3:45 PM EDT')
  await expect(chart).toContainText('15-minute bar close')
  // An older board quote cannot overwrite the newer chart snapshot or its distances.
  await expect(chart.locator('dl > div').filter({has: page.locator('dt', {hasText: '15-minute bar close'})})).toContainText('$115.00')
  await expect(chart.locator('dl > div').filter({has: page.locator('dt', {hasText: '21-session EMA'})})).toContainText('$113.50Price distance +1.3%')
  await expect(chart).not.toContainText('today, still moving')
  await expect(chart).not.toContainText('Price now')
  await expect(chart).not.toContainText('Last close')

  // Both grade changes are named, and the published one is distinguished.
  const showSignals = chart.getByRole('checkbox', {name: 'Grade changes', exact: true})
  await expect(showSignals).toBeChecked()
  await expect(chart).toContainText('3 grade changes marked')
  await expect(chart).toContainText('Saved grade C→B')
  await expect(chart).toContainText('Grade B (saved)→A (recalculated)')
  await expect(chart).toContainText('Recalculated grade A→B')
  await expect(chart).not.toContainText('sell ·')
  await expect(chart.locator('[aria-label="Chart legend"]')).toContainText('Arrows are grade changes (up green, down red).')
  await showSignals.uncheck()
  await expect(chart).not.toContainText('3 grade changes marked')
  await expect(chart).not.toContainText('Recalculated grade A→B')

  // Weekly re-reads and swaps to the lines the weekly legs are built from.
  await frames.getByRole('button', {name: 'W'}).click()
  await expect(frames.getByRole('button', {name: 'W'})).toHaveAttribute('aria-pressed', 'true')
  await expect(chart).toContainText('21-week EMA')
  await expect(chart).not.toContainText('200-session EMA')
  await expect(chart).toContainText('weeks loaded; pan or zoom for history.')
  await expect(chart).toContainText('15-minute bar starting Sep 8, 2026, 3:45 PM EDT')
  await chart.getByText('Original readings (0)', {exact: true}).click()
  await expect(chart.getByText(/Indicators can update during a session; weekly overlays/)).toBeVisible()

  // Missing provenance stays explicitly stored; an unfinished week is not called completed.
  includeQuoteTime = false
  await page.clock.fastForward('01:01')
  await expect(chart).toContainText('Newest stored week: 2026-09-08 (forming candle)')
  await expect(chart).toContainText('Newest stored candle price')
  await expect(chart).not.toContainText('15-minute bar close')

  // A delayed poll cannot roll back the complete snapshot from a later poll.
  delayNextChart = true
  await page.clock.fastForward('01:01')
  await expect.poll(() => Boolean(releaseChart)).toBe(true)
  lastClose = 120
  await page.clock.fastForward('01:01')
  const storedClose = chart.locator('dl > div').filter({has: page.locator('dt', {hasText: 'Newest stored candle price'})})
  await expect(storedClose).toContainText('$120.00')
  const delayedResponse = page.waitForResponse(response => response.url().includes('/desk/chart/AAPL'))
  releaseChart!()
  await (await delayedResponse).finished()
  await page.clock.runFor(50)
  await expect(storedClose).toContainText('$120.00')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})



// Backend-authored exchange status honours the 13:00 holiday close; a local
// weekday clock would incorrectly call 14:00 on this date open.
test('day-after-Thanksgiving early close is shown as closed at 14:00 ET', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.clock.setFixedTime(new Date('2026-11-27T19:00:00Z'))
  const marketStatus = {
    exchange: 'XNYS', as_of: '2026-11-27T19:00:00Z', session: '2026-11-27',
    calendar_known: true, is_session: true, open: false, phase: 'post-market',
    opens_at: '2026-11-27T09:30:00-05:00', closes_at: '2026-11-27T13:00:00-05:00',
  }
  await page.route('**/desk/live', route => route.fulfill({ json: {
    as_of: '2026-11-27T18:00:00Z', data_at: '2026-11-27T18:00:00Z', quotes: {}, market_status: marketStatus,
  } }))
  await page.goto('/#desk')
  await expect(page.getByLabel('Today')).toContainText('XNYS regular session closed · scheduled close 1:00 PM ET')
  await strategyDetails(page)
  await expect(page.getByRole('heading', { name: 'Plan status' })).toContainText('XNYS regular session closed · scheduled close 1:00 PM ET')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})
