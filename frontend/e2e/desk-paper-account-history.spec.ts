import {expect, test, type Page} from '@playwright/test'

const USER = 'ani.mallya'
const SESSION = '2026-09-28'
const WRITTEN = '2026-09-28T23:45:30Z'
const NOW = '2026-09-29T15:35:00Z'
const BAR = '2026-09-29T15:15:00Z'

// Make dated paper history and current personal guidance independently controllable.
async function scenario(page: Page, options: {historyFailure?: boolean; history?: object; decision?: Record<string, unknown> | null; staleContext?: boolean; targets?: object | null; book?: object[]} = {}) {
  const errors: string[] = []
  const writes: string[] = []
  const historyReads: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (message.type() === 'error' && !options.historyFailure) errors.push(message.text())})
  // The desk's required requests must succeed; unrelated chat unmount cancellations are out of scope.
  page.on('requestfailed', request => {if (request.url().includes('/market/')) errors.push(request.url())})
  await page.clock.install({time: new Date(NOW)})
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-29', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: '2026-09-29T13:30:00Z', closes_at: '2026-09-29T20:00:00Z'}
  const latest = {session: SESSION, written: WRITTEN, provenance: {rule: {inputs: []}, data: {}}, targets: {policy: 'graded-equal-weight/4', weights: {AAOI: .1}},
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAOI: {grade: 'A+', votes: 3, stances: {}, ranks: {}, score: .82, side: 'ai', headline: '', reason: '', reads: {}}}, book: options.book ?? [], briefs: {}, paper: null,
    ...(options.targets !== undefined ? {targets: options.targets} : {})}
  const row = {action: 'Hold', strategy_action: 'Buy', executable: true, valid_until: '2026-09-29T15:36:00Z', target_weight: .1, current_weight: 0, delta_weight: .1, move_weight: 0, strategy_move_weight: .1,
    reason: 'Buy setup awaiting its intraday price level.', blocker: null,
    timing: {rule: 'dip_or_close', side: 'buy', state: 'waiting', level: 97, open: 98, level_fraction: .01, session: '2026-09-29', trading_day: true, trigger_bar: null, trigger_price: null, close_cutoff: '15:45', moc_deadline: '15:50', reason: 'Waiting for price level'},
    quote: {feed: 'iex', at: NOW, bid: 98, ask: 98.5, eligible: true, reason: '', valid_until: '2026-09-29T15:36:00Z'}, ...options.decision}
  const history = options.history ?? {user_id: USER, source: 'paper_account_records', total_records: 5, ignored_records: 0, truncated: false, rows: [
    {session: '2026-09-21', recorded_at: '2026-09-21T23:30:00Z', equity: 100000, cash: 20000, equity_change: null, equity_change_pct: null, previous_session: null, missing_sessions: null},
    {session: '2026-09-22', recorded_at: '2026-09-23T14:17:00Z', equity: 101000, cash: 10000, equity_change: 1000, equity_change_pct: .01, previous_session: '2026-09-21', missing_sessions: 0},
    {session: '2026-09-24', recorded_at: '2026-09-24T23:30:00Z', equity: 99000, cash: 0, equity_change: -2000, equity_change_pct: -2000 / 101000, previous_session: '2026-09-22', missing_sessions: 1},
    {session: '2026-09-25', recorded_at: null, equity: null, cash: null, equity_change: null, equity_change_pct: null, previous_session: '2026-09-24', missing_sessions: 0},
    {session: SESSION, recorded_at: WRITTEN, equity: 99341.51, cash: 9341.51, equity_change: null, equity_change_pct: null, previous_session: '2026-09-25', missing_sessions: 0},
  ].map(row => ({...row, chronology_verified: row.previous_session !== null}))}
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const base = `/api/v1/market/${USER}/desk`
    if (request.method() !== 'GET' && !(url.pathname === `${base}/mine` && request.postDataJSON()?.record_history === false)) {
      writes.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-10-01T00:00:00Z', is_admin: true, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION]}
    else if (url.pathname === `${base}/live`) json = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAOI: {symbol: 'AAOI', last: 98.25, open: 98, high: 99, low: 98, bar: BAR, as_of: NOW}}, technical: {}, technical_detail: {}}
    else if (url.pathname === `${base}/session-prices`) json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = {session: SESSION, market_status: market, grade_valid_until: {}, grades_live: {}, rows: [], decisions: {session: options.staleContext ? '2026-09-25' : SESSION, written: WRITTEN, as_of: NOW, equity: 100000, holdings: {}, timing: {rule: 'dip_or_close', level: .01, session: '2026-09-29', close_cutoff: '15:45', moc_deadline: '15:50', latched: true}, rows: options.decision === null ? {} : {AAOI: row}}}
    else if (url.pathname === `${base}/intraday`) json = null
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 105000, cash: 15000, day_pl: 100, pl_pct: .05, day_pl_pct: .001, positions: [], orders: [], activity: {session: '2026-09-29', complete: true, fills: [{symbol: 'AAOI', side: 'buy', qty: 2, price: 98.74, filled_at: '2026-09-29T13:30:18Z'}]}}
    else if (url.pathname === `${base}/paper/history`) {
      historyReads.push(url.searchParams.get('limit') ?? '')
      if (options.historyFailure) return route.fulfill({status: 503, json: {detail: 'Unavailable'}})
      json = history
    } else { errors.push(`Unexpected request ${url.pathname}`); json = {} }
    return route.fulfill({json})
  })
  return {errors, writes, historyReads}
}

for (const [name, targets, expected] of [
  ['active fully invested targets', {policy: 'graded-equal-weight/4', weights: {AAOI: 1}}, 'Planned cash 0.0%'],
  ['missing active weights', {policy: 'graded-equal-weight/4'}, 'Planned cash Unavailable'],
  ['invalid active weights', {policy: 'graded-equal-weight/4', weights: {AAOI: -1}}, 'Planned cash Unavailable'],
  ['legacy record', null, 'Legacy planned cash 80.0%'],
] as const) {
  // A legacy book must not silently replace active targets or conceal malformed target data.
  test(`planned cash uses ${name}`, async ({page}) => {
    const diagnostics = await scenario(page, {targets, book: [{ticker: 'AAOI', weight: .2, grade: 'A+'}]})
    await page.goto('/#desk')
    await page.locator('details[aria-label="Strategy details"] > summary').click()
    await expect(page.getByLabel('Your planned cash', {exact: true})).toContainText(expected)
    expect(diagnostics.writes).toEqual([])
    expect(diagnostics.errors).toEqual([])
  })
}

// Actual recorded balances keep their own dates and gaps, independent of today's broker value.
test('shows saved daily account history without manufacturing returns or closing prices', async ({page}, testInfo) => {
  const diagnostics = await scenario(page)
  await page.goto('/#desk')
  expect(diagnostics.historyReads).toEqual([])
  await page.locator('summary', {hasText: 'Practice account'}).click()
  await expect(page.locator('details[aria-label="Practice account"]')).not.toContainText('CAGR')
  await expect(page.locator('details[aria-label="Historical simulation"]')).not.toHaveAttribute('open')
  await page.getByRole('button', {name: /Daily account history/}).click()
  const history = page.getByRole('region', {name: 'Paper account history', exact: true})
  const table = history.getByRole('table', {name: 'Daily paper account values'})
  await expect(table).toBeVisible()
  await expect(table.getByRole('row').nth(1)).toContainText('2026-09-28')
  await expect(table.getByRole('row').nth(1)).toContainText('$99,341.51')
  await expect(table).not.toContainText('$105,000')
  const late = table.getByRole('row').filter({hasText: '2026-09-22'})
  await expect(late).toContainText('Sep 23, 2026, 10:17 AM ET')
  await expect(late).toContainText('+$1,000.00')
  await expect(late).toContainText('+1.00%')
  await expect(table.getByRole('row').filter({hasText: '2026-09-24'})).toContainText('1 missing session')
  await expect(table.getByRole('row').filter({hasText: '2026-09-25'}).getByRole('cell').nth(1)).toHaveText('—')
  await expect(table.getByRole('row').last().getByRole('cell').last()).toHaveText('—')
  await expect(history).toContainText('not adjusted for deposits, withdrawals or account resets')
  await expect(history.locator('svg polyline')).toHaveCount(1)
  await expect(history.locator('svg circle')).toHaveCount(4)
  await history.screenshot({path: testInfo.outputPath('paper-account-history.png')})
  await page.waitForLoadState('networkidle')
  await page.reload()
  await page.locator('summary', {hasText: 'Practice account'}).click()
  await page.getByRole('button', {name: /Daily account history/}).click()
  await expect(page.getByRole('table', {name: 'Daily paper account values'})).toContainText('$99,341.51')
  expect(diagnostics.historyReads).toEqual(['90', '90'])
  expect(diagnostics.writes).toEqual([])
  expect(diagnostics.errors).toEqual([])
})

// A failed read must not masquerade as a valid account with no recorded history.
test('distinguishes unavailable paper history from an empty record set', async ({page}) => {
  const diagnostics = await scenario(page, {historyFailure: true})
  await page.goto('/#desk')
  await page.locator('summary', {hasText: 'Practice account'}).click()
  await page.getByRole('button', {name: /Daily account history/}).click()
  await expect(page.getByRole('alert')).toContainText('Account history unavailable')
  await expect(page.getByText('No saved paper-account values yet.')).toHaveCount(0)
  expect(diagnostics.writes).toEqual([])
  expect(diagnostics.errors).toEqual([])
})

for (const [name, decision, staleContext, word, detail] of [
  ['waiting buy', {}, false, 'Wait', 'Strategy: buy'],
  ['missing decision', null, false, 'Unavailable', 'Refresh guidance'],
  ['mismatched decision', {}, true, 'Unavailable', 'Refresh guidance'],
  ['blocked quote', {executable: false, blocker: 'Quote unavailable'}, false, 'Blocked', 'Strategy: buy'],
  ['unknown cash', {executable: false, blocker: 'available cash is unknown'}, false, 'Cash needed', 'Confirm available cash'],
  ['expired evidence', {action: 'Buy', move_weight: .1, valid_until: '2026-09-29T15:34:00Z'}, false, 'Unavailable', 'Refresh price check'],
  ['genuine hold', {strategy_action: 'Hold', action: 'Hold'}, false, 'Hold', null],
  ['current buy', {action: 'Buy', move_weight: .1}, false, 'BUY', null],
] as const) {
  // Identical paper fills must never overwrite the current personal decision's readiness.
  test(`current action distinguishes ${name} from the paper account's opening buy`, async ({page}) => {
    const diagnostics = await scenario(page, {decision, staleContext})
    await page.goto('/#desk')
    const board = page.getByRole('region', {name: 'Stocks and cash', exact: true})
    await expect(board.getByLabel('AAOI strategy intent', {exact: true})).toHaveText(word)
    if (detail) await expect(board.getByLabel('AAOI action status', {exact: true})).toHaveText(detail)
    await expect(board.getByLabel('AAOI size', {exact: true})).toHaveText(word === 'BUY' ? '10.0% of account' : '—')
    await page.locator('summary', {hasText: 'Practice account'}).click()
    await expect(page.getByLabel('Paper execution', {exact: true})).toContainText('buy 2 AAOI')
    await expect(page.getByLabel('Paper account execution timing')).toContainText('Scheduled paper buys: next open')
    await expect(board.getByLabel('AAOI strategy intent', {exact: true})).toHaveText(word)
    expect(diagnostics.writes).toEqual([])
    expect(diagnostics.errors).toEqual([])
  })
}
