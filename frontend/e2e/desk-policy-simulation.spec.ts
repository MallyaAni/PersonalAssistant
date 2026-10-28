import {expect, test, type Locator, type Page, type TestInfo} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {CHART_NAME, EXPECTED_CELLS, EXPECTED_PERIOD, EXPECTED_WINDOWS, MANIFEST, POLICY_SIMULATION, missingSimulation} from './fixtures/policySimulation'

// Browser acceptance for the Paper account view's "Historical simulation" box
// and the plan check banner. The box draws the installed rule's own account
// simulation - the 20:40 replay's `book` and its curve beside SPY - and never
// the curve the nightly record used to carry from the older daily-price
// simulator (its hindsight, point-in-time and candidate /4 lines). When the
// replay for the record is missing it says so and draws nothing else. These
// tests succeed the point-in-time line and candidate line specs, which pinned
// the old box. Every endpoint is answered from fixtures.

const USER = 'ani.mallya'
const SESSION = '2026-09-25'
const WRITTEN = '2026-09-25T21:05:00Z'
const NOW = '2026-09-26T15:35:00Z'
const BAR = '2026-09-26T15:15:00Z'
const STANCES = {fundamental: 1, technical: 1, sentiment: 0, value: 0, rotation: 0}
const DATES = ['2026-01-02', '2026-03-02', '2026-05-01', '2026-07-01', SESSION]

// The old record's curve block with every line the old box drew, so a test
// can prove none of them reaches the page.
const RECORD_CURVE = {
  backtest: {
    label: 'the rules, walked forward', asof: SESSION, dates: DATES,
    funding_model: 'cash-at-fill-v1', strategy_policy: 'graded-equal-weight/5', fundamentals_source: 'fundamentals-features/2',
    rules: [0, .06, .12, .19, .27],
    rules_point_in_time: [0, .02, .03, .05, .08],
    candidate_point_in_time: [0, .04, .09, .14, .22],
    spy: [0, .02, .01, .05, .09],
    qqq: [0, .03, .04, .08, .13],
    stats: {cagr: .31, volatility: .22, drawdown: -.11, total: .27},
    stats_point_in_time: {cagr: .08, volatility: .2, drawdown: -.12, total: .08},
    stats_candidate: {cagr: .22, volatility: .21, drawdown: -.1, total: .22},
    candidate_label: 'candidate /4: every A/A+ name at equal weight, 20% cap, names known at the time; plain next-open fills, not the live executor',
    point_in_time_note: '', candidate_note: '',
  },
  paper: {label: 'paper account', sessions: ['2026-07-01', SESSION], equity: [100000, 101000], pl_pct: [0, .01]},
}
const OLD_WORDS = ['stored simulation', 'names known at the time', 'candidate /4', 'QQQ', '31.0%', '8.0%', '22.0%', 'practice account (recorded equity)']

// Answer every desk endpoint locally and refuse any provider request or persisted write.
async function install(page: Page, frontendURL: string, served: {policy_simulation?: unknown; plan_parity?: unknown}) {
  const market = {exchange: 'XNYS', as_of: NOW, session: '2026-09-26', calendar_known: true, is_session: true, open: true, phase: 'open', opens_at: null, closes_at: null}
  const latest = {
    session: SESSION, written: WRITTEN, provenance: {rule: {inputs: ['expectations-gap']}, data: {fundamentals: 'fundamentals-features/2'}},
    regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, exposure: 1, flags: []},
    grades: {AAPL: {grade: 'A', votes: 3, stances: STANCES, ranks: {}, score: .82, side: 'ai', headline: 'Recorded headline.', reason: 'Recorded reason.', reads: {}}},
    targets: {policy: MANIFEST.policy, weights: {AAPL: .1}},
    book: [], briefs: {}, paper: null, curve: RECORD_CURVE,
  }
  const mine = {session: SESSION, market_status: market, grade_valid_until: {}, grades_live: {}, rows: [],
    decisions: {session: SESSION, written: WRITTEN, as_of: NOW, rows: {AAPL: {action: 'Hold', strategy_action: 'Hold', executable: false, blocker: 'No entry instruction.', reason: 'No entry instruction.', valid_until: null, target_weight: 0, current_weight: .1, move_weight: 0, strategy_move_weight: 0,
      quote: {feed: 'iex', at: NOW, bid: 98, ask: 98.5, reason: 'No entry instruction.', eligible: false}}}}}
  const live = {as_of: NOW, data_at: BAR, stale: false, market_status: market, quotes: {AAPL: {symbol: 'AAPL', last: 98.25, open: 101, high: 102, low: 98, bar: BAR, as_of: NOW}}, technical: {}, technical_detail: {}}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  page.on('requestfailed', request => request.failure()?.errorText === 'net::ERR_ABORTED' ? undefined : diagnostics.failedRequests.push(`${request.method()} ${request.url()}`))
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(NOW)})
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  await page.route('**/*', async route => {
    if (route.request().method() === 'GET' && new URL(route.request().url()).pathname.endsWith('/desk/model-allocation')) return route.fulfill({status: 204})
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(frontendURL).origin) return route.continue()
      diagnostics.unexpectedRequests.push(request.url())
      return route.abort('blockedbyclient')
    }
    const base = `/api/v1/market/${USER}/desk`
    const preview = url.pathname === `${base}/mine` && request.method() === 'POST' && request.postDataJSON()?.record_history === false
    if (request.method() !== 'GET' && !preview) {
      diagnostics.forbiddenWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids persistence'}})
    }
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-27T00:00:00Z', is_admin: true, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [SESSION], ...served}
    else if (url.pathname === `${base}/live`) json = live
    else if (url.pathname === `${base}/session-prices`) json = {session: 'regular', as_of: NOW, signal_scope: 'regular-session', quotes: {}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = mine
    else if (url.pathname === `${base}/paper`) json = {as_of: NOW, equity: 101000, cash: 101000, day_pl: 0, pl_pct: .01, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/paper/history`) json = {user_id: USER, rows: []}
    else if (url.pathname === `${base}/personal-history`) json = {rows: [], receipts: []}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture request'}})
    }
    return route.fulfill({json})
  })
  return diagnostics
}

async function recordDiagnostics(testInfo: TestInfo, diagnostics: object) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(diagnostics, null, 2), contentType: 'application/json'})
  for (const [category, failures] of Object.entries(diagnostics)) expect.soft(failures, `Browser ${category}`).toEqual([])
}

// Open the Historical simulation box and return it.
async function openBox(page: Page): Promise<Locator> {
  await page.goto('/?deskView=paper#desk')
  const details = page.locator('details[aria-label="Historical simulation"]')
  if ((await details.getAttribute('open')) === null) await details.locator(':scope > summary').click()
  const box = details.getByLabel('Historical simulation summary', {exact: true})
  await expect(box).toBeVisible()
  return box
}

// The box shows the replay manifest's own numbers, the rule's name, the
// replay's record date and period, and draws exactly two lines: the
// simulated account and SPY. None of the record's old lines appear.
test('draws the installed rule\'s simulated account beside SPY with the replay manifest\'s numbers', async ({page, baseURL}, testInfo) => {
  const diagnostics = await install(page, baseURL!, {policy_simulation: POLICY_SIMULATION})
  try {
    const box = await openBox(page)
    await expect(box.getByLabel('Simulated rule', {exact: true})).toHaveText(`${MANIFEST.policy} · replay of the ${MANIFEST.through} record`)
    await expect(box.getByLabel('Simulation period', {exact: true})).toHaveText(EXPECTED_PERIOD)
    for (const [label, value] of Object.entries(EXPECTED_CELLS)) {
      await expect(box.getByLabel(label, {exact: true})).toHaveText(`${label}${value}`)
    }
    await expect(box.getByLabel('Simulation windows', {exact: true})).toHaveText(EXPECTED_WINDOWS)
    await expect(box.getByLabel('Simulation note', {exact: true})).toHaveText(MANIFEST.note)
    const chart = box.getByRole('img', {name: CHART_NAME, exact: true})
    await expect(chart).toBeVisible()
    await expect(chart.locator('polyline[stroke="#1e7a3a"]')).toHaveCount(1)
    await expect(chart.locator('polyline[stroke="#9ca3af"]')).toHaveCount(1)
    await expect(chart.locator('polyline')).toHaveCount(2)
    await expect(chart).toContainText(`${MANIFEST.policy} (simulated account)`)
    await expect(chart).toContainText('SPY (adjusted close held from the first session, no costs)')
    for (const word of OLD_WORDS) await expect(box).not.toContainText(word)
    await box.screenshot({path: testInfo.outputPath('policy-simulation.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// A missing replay is said in words; the record's stored curve is not drawn in its place.
test('says the replay is missing and draws no other simulation', async ({page, baseURL}, testInfo) => {
  const missing = missingSimulation(SESSION)
  const diagnostics = await install(page, baseURL!, {policy_simulation: missing})
  try {
    const box = await openBox(page)
    await expect(box.getByRole('status')).toHaveText(missing.reason)
    await expect(box.getByRole('img')).toHaveCount(0)
    await expect(box).not.toContainText('CAGR')
    for (const word of OLD_WORDS) await expect(box).not.toContainText(word)
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// A desk answer with no simulation block at all (an API from before the box
// read the replay) still never falls back to the record's curve.
test('never falls back to the record\'s stored curve', async ({page, baseURL}, testInfo) => {
  const diagnostics = await install(page, baseURL!, {})
  try {
    const box = await openBox(page)
    await expect(box).toContainText('No historical simulation available.')
    await expect(box.getByRole('img')).toHaveCount(0)
    for (const word of OLD_WORDS) await expect(box).not.toContainText(word)
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// The plan check's rows, as the 20:40 job wrote them when replayed on the
// 2026-10-21 record (a mismatch: that night ran an earlier revision of the
// rule) and the 2026-10-27 record (OK, the FOMC restoration).
const PLAN_ROWS = JSON.parse(readFileSync(new URL('./fixtures/plan-parity-2026-10-21-and-27.json', import.meta.url), 'utf8'))

// A mismatch is a red banner naming every differing name, one line per row
// of the check, each with the row's own detail.
test('the plan check banner names every differing name from the check\'s rows', async ({page, baseURL}, testInfo) => {
  const row = PLAN_ROWS.mismatch
  const diagnostics = await install(page, baseURL!, {policy_simulation: POLICY_SIMULATION, plan_parity: row})
  try {
    await page.goto('/?deskView=paper#desk')
    const banner = page.getByRole('alert', {name: 'Plan check'})
    await expect(banner).toBeVisible()
    const names = [...new Set(row.mismatches.map((m: {ticker?: string}) => m.ticker).filter(Boolean))].sort()
    await expect(banner.locator('p').first()).toHaveText(`The ${row.date} paper plan differs from the account simulator: ${names.length} names (${names.join(', ')})`)
    await expect(banner.locator('p')).toHaveCount(1 + row.mismatches.length)
    for (const [i, m] of row.mismatches.entries()) {
      const line = banner.locator('p').nth(i + 1)
      await expect(line).toContainText(`${m.ticker} (`)
      await expect(line).toContainText(m.detail)
    }
    await banner.screenshot({path: testInfo.outputPath('plan-check-mismatch.png')})
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// A passed check draws nothing.
test('no plan check banner when the plans agree', async ({page, baseURL}, testInfo) => {
  const diagnostics = await install(page, baseURL!, {policy_simulation: POLICY_SIMULATION, plan_parity: PLAN_ROWS.ok})
  try {
    await page.goto('/?deskView=paper#desk')
    await expect(page.getByLabel('Ranked stocks and cash')).toBeVisible()
    await expect(page.getByLabel('Plan check')).toHaveCount(0)
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})

// A check that could not run says so, so a broken check is not read as a pass.
test('an unavailable plan check is shown, not read as a pass', async ({page, baseURL}, testInfo) => {
  const row = {version: 'plan-parity/1', date: SESSION, verdict: 'unavailable', ok: false, mismatches: [], note: 'ValueError: the report ends on 2026-09-26, not the record\'s 2026-09-25'}
  const diagnostics = await install(page, baseURL!, {policy_simulation: POLICY_SIMULATION, plan_parity: row})
  try {
    await page.goto('/?deskView=paper#desk')
    const line = page.getByRole('status', {name: 'Plan check'})
    await expect(line).toHaveText(`The check of the ${SESSION} paper plan against the simulator could not run: ${row.note}.`)
    await expect(page.getByRole('alert', {name: 'Plan check'})).toHaveCount(0)
  } finally {
    await recordDiagnostics(testInfo, diagnostics)
  }
})
