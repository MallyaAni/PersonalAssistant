import {expect, test, type Page, type TestInfo} from '@playwright/test'
import {readFileSync} from 'node:fs'

const evidence = JSON.parse(readFileSync(new URL('./fixtures/execution_quotes.json', import.meta.url), 'utf8')) as typeof import('./fixtures/execution_quotes.json')

const USER = 'execution-evidence-fixture'
const ONE_VENUE = 'The available quote covers one venue; the consolidated spread is unverified. Check your broker before crossing.'
const CLOCK = 'Regular-session execution is blocked; the session is closed or its clock is unavailable'
type CaseName = keyof typeof evidence.cases

// Render actual backend-produced rows; only unrelated APIs and optional display midpoints are synthetic.
async function install(page: Page, frontendURL: string, name: CaseName, legacy = false, displaySnapshot?: object) {
  const source = structuredClone(evidence.cases[name])
  if (legacy) delete (source.row.quote as {spread_verified?: boolean}).spread_verified
  const original = JSON.stringify(source)
  const closed = source.regular_clock !== true
  const now = source.now
  const bar = source.snapshot.quotes.S11.bar
  const market = {exchange: 'XNYS', as_of: now, session: '2026-09-14', calendar_known: source.regular_clock !== null, is_session: !closed, open: !closed, phase: closed ? source.regular_clock === null ? 'unknown' : 'closed' : 'open', opens_at: null, closes_at: null}
  const latest = {...evidence.record, grades: {S11: {...evidence.record.grades.S11, side: 'ai', votes: 4}}, regime: {ai_participation: .5, software_participation: .5, participation_percentile: .5, ai_vs_software_correlation: 0, correlation_z: 0, novelty_z: 0, rotation_leader: 'none', rotation_spread: 0, ai_drawdown: .1, selection_confidence: .6, flags: [], ...evidence.record.regime}, briefs: {}, paper: null}
  const live = {...source.snapshot, data_at: bar, market_status: market, stale: closed}
  const mine = {session: latest.session, rows: [], grades_live: {}, grade_valid_until: {}, market_status: market, decisions: {session: latest.session, written: latest.written, as_of: now, rows: {S11: source.row}}}
  const diagnostics = {consoleErrors: [] as string[], pageErrors: [] as string[], failedRequests: [] as string[], badResponses: [] as string[], unexpectedRequests: [] as string[], forbiddenWrites: [] as string[]}
  const reads: string[] = []
  // Preserve browser errors even when the expected text happens to render.
  page.on('console', message => {if (message.type() === 'error') diagnostics.consoleErrors.push(message.text())})
  // A partially mounted page does not prove the workflow.
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message))
  // Required requests must complete rather than silently falling back.
  page.on('requestfailed', request => diagnostics.failedRequests.push(request.url()))
  // Keep HTTP failures visible independently of page assertions.
  page.on('response', response => {if (response.status() >= 400) diagnostics.badResponses.push(`${response.status()} ${response.url()}`)})
  await page.clock.install({time: new Date(now)})
  // Synthetic appearance must not read the operator's browser preferences.
  await page.addInitScript(() => localStorage.setItem('anios.theme', 'light'))
  // Refuse every external request or account write; only a non-recording preview can POST.
  await page.route('**/*', async route => {
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
      return route.fulfill({status: 403, json: {detail: 'Fixture forbids writes'}})
    }
    reads.push(url.pathname)
    let json: unknown
    if (url.pathname === '/api/v1/auth/session') json = {authentication_required: true, user_id: USER, expires_at: '2026-09-28T00:00:00Z', is_admin: false, desk_access: true, desk_write: false}
    else if (url.pathname.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (url.pathname === base) json = {latest, sessions: [latest.session]}
    else if (url.pathname === `${base}/live`) json = live
    else if (url.pathname === `${base}/session-prices`) json = displaySnapshot ?? {session: closed ? 'overnight' : 'regular', as_of: now, signal_scope: 'regular-session', quotes: {S11: closed ? {price: 100, at: now, feed: 'boats', indicative: false, session: 'overnight', status: 'fresh', reason: 'Synthetic dated overnight midpoint.', valid_until: '2026-09-14T01:02:00Z'} : {price: null, at: null, feed: null, indicative: false, status: 'unavailable', reason: 'No optional quote in fixture.', valid_until: null}}}
    else if (url.pathname === `${base}/holdings`) json = {holdings: []}
    else if (url.pathname === `${base}/mine`) json = mine
    else if (url.pathname === `${base}/intraday`) json = {session: latest.session, as_of: now, equity: 100000, rows: [], changed: [], top_buys: []}
    else if (url.pathname === `${base}/paper`) json = {as_of: now, equity: 100000, cash: 100000, day_pl: 0, pl_pct: 0, day_pl_pct: 0, positions: [], orders: [], activity: {complete: true, fills: []}}
    else if (url.pathname === `${base}/entries`) json = {user_id: USER, session: latest.session, rows: []}
    else if (url.pathname === `${base}/history/S11`) json = {ticker: 'S11', asof: latest.session, horizon: 20, backtest: null, rows: [], recommendations: {observations: [], invalid_archives: 0, older_records_not_shown: false}}
    else if (url.pathname === `${base}/earnings/S11`) json = {user_id: USER, symbol: 'S11', read: null}
    else if (url.pathname === `${base}/chart/S11`) json = {user_id: USER, ticker: 'S11', timeframe: 'daily', timeframes: ['daily', 'weekly'], adjusted: true, last_bar_complete: true, basis: 'synthetic fixture', sessions: 0, bars: [], overlays: {}, levels: {}, entries: []}
    else if (url.pathname === `${base}/live/read/S11`) json = {symbol: 'S11', now: null, data_at: bar, read_at: now, stale: closed, read: 'Synthetic technical evidence.', lines: {short: [], medium: [], long: []}}
    else {
      diagnostics.unexpectedRequests.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified request'}})
    }
    return route.fulfill({json})
  })
  return {source, original, diagnostics, reads}
}

// Record all six browser boundaries and prove rendering did not mutate the supplied producer row.
async function finish(testInfo: TestInfo, fixture: Awaited<ReturnType<typeof install>>) {
  await testInfo.attach('browser-diagnostics', {body: JSON.stringify(fixture.diagnostics, null, 2), contentType: 'application/json'})
  await testInfo.attach('source-and-reads', {body: JSON.stringify({source: fixture.source, producer: evidence.producer, sourceHashes: evidence.source_sha256, reads: fixture.reads}, null, 2), contentType: 'application/json'})
  for (const [category, errors] of Object.entries(fixture.diagnostics)) expect.soft(errors, category).toEqual([])
  expect(JSON.stringify(fixture.source)).toBe(fixture.original)
}

for (const name of Object.keys(evidence.cases) as CaseName[]) {
  // Preserve the real eligibility/action/amount contract while distinguishing spread and clock evidence.
  test(`execution evidence preserves the real ${name} decision`, async ({page, baseURL}, testInfo) => {
    const fixture = await install(page, baseURL!, name)
    const {source} = fixture
    try {
      await page.goto('/#desk')
      const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
      const today = page.getByLabel('Today', {exact: true})
      await expect(board.getByLabel('S11 strategy intent', {exact: true})).toHaveText(source.row.strategy_action.toUpperCase())
      await expect(board.getByLabel('S11 size', {exact: true})).toHaveText(source.row.executable ? `${(100 * Math.abs(source.row.move_weight)).toFixed(1)}% of account` : '—')
      await testInfo.attach('collapsed-original-observation', {body: await board.innerText(), contentType: 'text/plain'})
      await board.screenshot({path: testInfo.outputPath(`${name}-collapsed.png`)})
      if (source.row.executable) await expect(today).toContainText('1 executable signal.')
      else await expect(today).not.toContainText('1 executable signal.')
      if (name.endsWith('clock')) {
        const readiness = board.getByLabel('S11 execution readiness', {exact: true})
        await expect(readiness).toHaveText('Regular-session execution blocked')
        await expect(readiness).toHaveAttribute('title', CLOCK)
      }
      if (name === 'wide_iex') {
        const caveat = board.getByLabel('S11 spread verification', {exact: true})
        await expect(caveat).toHaveText('IEX spread unverified')
        await expect(caveat).toBeVisible()
      } else await expect(board.getByLabel('S11 spread verification', {exact: true})).toHaveCount(0)
      await page.getByRole('button', {name: 'details for S11', exact: true}).click()
      const detail = page.getByRole('region', {name: 'S11 decision details', exact: true})
      const intent = detail.getByLabel('S11 strategy intent', {exact: true})
      await expect(intent).toContainText('BUY')
      if (!source.row.executable) await expect(intent).toContainText('Blocked now')
      await expect(board.getByLabel('S11 move', {exact: true})).toHaveText('+3.3%')
      await expect(board.getByLabel('S11 recorded personal position', {exact: true})).toHaveText('None recorded')
      await detail.getByText('Recorded allocation & execution quote', {exact: true}).click()
      if (name === 'wide_iex') {
        await expect(detail.getByLabel('S11 spread verification', {exact: true})).toHaveText('IEX spread unverified')
        await expect(detail).toContainText(ONE_VENUE)
        await expect(detail).not.toContainText('Only one venue is quoting')
        await expect(detail).toContainText('IEX · $95.00 bid / $105.00 ask')
        await expect(detail).toContainText('1000.0 bp spread')
      } else if (name === 'tight_sip' || name === 'tight_iex') {
        await expect(detail).toContainText(`${source.row.quote.feed.toUpperCase()} quote checks passed`)
        await expect(detail).not.toContainText('spread unverified')
        await expect(detail).not.toContainText('consolidated quote checks passed')
      } else if (name === 'wide_sip') {
        await expect(intent).toHaveAttribute('title', 'Spread exceeds the execution limit')
        await expect(detail).toContainText('Spread exceeds the execution limit · 1000.0 bp spread')
      } else if (name.endsWith('clock')) {
        expect(source.row.blocker).toBe('market closed or clock unavailable')
        await expect(intent).toHaveAttribute('title', CLOCK)
        await expect(intent.getByLabel('S11 execution readiness', {exact: true})).toHaveText('Blocked now · Regular-session execution blocked')
        await expect(intent.getByLabel('S11 execution readiness', {exact: true})).toHaveAttribute('title', CLOCK)
        await expect(intent).not.toContainText('market closed or clock unavailable')
        await expect(detail).toContainText(CLOCK)
        await expect(intent).not.toHaveAttribute('title', /Quote unavailable/)
        const midpoint = page.getByLabel('S11 session price', {exact: true}).first()
        await expect(midpoint).toContainText('$100.00')
        await expect(midpoint).toContainText('overnight · BOATS')
        await expect(midpoint).toHaveAttribute('title', /Signal: regular session\. Midpoint is not a trade or guaranteed fill/)
        await expect(midpoint).toHaveAttribute('title', /not proof of venue availability/)
      } else if (name === 'stale_quote') {
        await expect(detail).toContainText('Quote expired')
        await expect(detail).toContainText('expired')
      } else {
        await expect(intent).toHaveAttribute('title', 'Quote unavailable; execution blocked')
        await expect(detail).toContainText('No quote time')
      }
      await testInfo.attach('rendered-detail', {body: JSON.stringify({tooltip: await intent.getAttribute('title'), text: await detail.innerText()}), contentType: 'application/json'})
      await detail.screenshot({path: testInfo.outputPath(`${name}-details.png`)})
    } finally {
      await finish(testInfo, fixture)
    }
  })
}

for (const name of ['tight_iex', 'tight_sip'] as const) {
  // Omit only the newer flag from a real eligible row to exercise the legacy wire contract.
  test(`execution evidence does not verify a legacy ${name} spread`, async ({page, baseURL}, testInfo) => {
    const fixture = await install(page, baseURL!, name, true)
    try {
      await page.goto('/#desk')
      const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
      await expect(board.getByLabel('S11 strategy intent', {exact: true})).toHaveText('BUY')
      await expect(board.getByLabel('S11 size', {exact: true})).toHaveText('3.3% of account')
      await expect(board.getByLabel('S11 spread verification', {exact: true})).toHaveText('Spread verification unrecorded')
      await page.getByRole('button', {name: 'details for S11', exact: true}).click()
      const detail = page.getByRole('region', {name: 'S11 decision details', exact: true})
      await expect(detail.getByLabel('S11 spread verification', {exact: true})).toHaveText('Spread verification unrecorded')
      await expect(detail).not.toContainText('spread verified')
    } finally {
      await finish(testInfo, fixture)
    }
  })
}

// Both decision displays, refresh and reload retain the warning without refreshing evidence timestamps.
test('execution caveat survives full-panel navigation, refresh and reload', async ({page, baseURL}, testInfo) => {
  const fixture = await install(page, baseURL!, 'wide_iex')
  try {
    await page.goto('/#desk')
    const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
    await expect(board.getByLabel('S11 spread verification', {exact: true})).toHaveText('IEX spread unverified')
    await page.getByRole('button', {name: 'S11', exact: true}).click()
    const dialog = page.getByRole('dialog', {name: 'S11 history'})
    await expect(dialog.getByLabel('S11 spread verification', {exact: true})).toHaveText('IEX spread unverified')
    await dialog.screenshot({path: testInfo.outputPath('wide-iex-full-panel.png')})
    await page.getByRole('button', {name: 'Close', exact: true}).click()
    const before = fixture.reads.filter(path => path.endsWith('/mine')).length
    await page.getByRole('button', {name: 'Refresh', exact: true}).click()
    await expect.poll(() => fixture.reads.filter(path => path.endsWith('/mine')).length).toBeGreaterThan(before)
    await expect(board.getByLabel('S11 spread verification', {exact: true})).toHaveText('IEX spread unverified')
    await expect(board.getByLabel('S11 size', {exact: true})).toHaveText('3.3% of account')
    await page.reload()
    await expect(board.getByLabel('S11 spread verification', {exact: true})).toHaveText('IEX spread unverified')
    await expect(board.getByLabel('S11 strategy intent', {exact: true})).toHaveText('BUY')
    await expect(board.getByLabel('S11 size', {exact: true})).toHaveText('3.3% of account')
    await page.getByRole('button', {name: 'details for S11', exact: true}).click()
    const detail = page.getByRole('region', {name: 'S11 decision details', exact: true})
    await detail.getByText('Recorded allocation & execution quote', {exact: true}).click()
    await expect(detail).toContainText('Sep 14, 2026, 10:01:00 AM ET')
    await expect(detail).toContainText('Expires Sep 14, 2026, 10:01:30 AM ET')
  } finally {
    await finish(testInfo, fixture)
  }
})

// The spread caveat never bypasses the existing deadline guard or extends a quote's life.
test('execution quote expiration still withholds size with an unverified spread', async ({page, baseURL}, testInfo) => {
  const fixture = await install(page, baseURL!, 'wide_iex')
  try {
    await page.goto('/#desk')
    const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
    await expect(board.getByLabel('S11 size', {exact: true})).toHaveText('3.3% of account')
    await page.clock.runFor(31_000)
    await expect(board.getByLabel('S11 size', {exact: true})).toHaveText('—')
    await expect(board.getByLabel('S11 strategy intent', {exact: true})).toHaveText('BUY')
    await expect(board.getByLabel('S11 spread verification', {exact: true})).toHaveText('IEX spread unverified')
    await expect(page.getByLabel('Today', {exact: true})).not.toContainText('1 executable signal.')
  } finally {
    await finish(testInfo, fixture)
  }
})

for (const failure of ['generic unavailable', 'missing envelope', 'missing quote', 'malformed quote', 'specific recorded reason'] as const) {
  // Display-snapshot failure is independent of a real eligible execution quote on both UI surfaces.
  test(`display snapshot ${failure} does not deny separate IEX execution evidence`, async ({page, baseURL}, testInfo) => {
    const at = evidence.cases.wide_iex.now
    const rawQuote = {price: null, at: null, feed: 'iex', indicative: false, session: 'unknown', status: 'unavailable',
      reason: failure === 'specific recorded reason' ? 'Missing or future quote timestamp' : 'No fresh quote from available feeds', valid_until: null}
    const displaySnapshot = failure === 'missing envelope' ? {} : {session: 'regular', as_of: at, signal_scope: 'regular-session',
      quotes: failure === 'missing quote' ? {} : {S11: failure === 'malformed quote'
        ? {...rawQuote, price: -1, at, status: 'fresh', valid_until: '2026-09-14T14:02:00Z'} : rawQuote}}
    const originalDisplay = JSON.stringify(displaySnapshot)
    const fixture = await install(page, baseURL!, 'wide_iex', false, displaySnapshot)
    try {
      await page.goto('/#desk')
      const board = page.getByRole('table', {name: 'Ranked stocks and cash'})
      await expect(board.getByLabel('S11 strategy intent', {exact: true})).toHaveText('BUY')
      await expect(board.getByLabel('S11 size', {exact: true})).toHaveText('3.3% of account')
      await page.getByRole('button', {name: 'S11', exact: true}).click()
      const panel = page.getByRole('dialog', {name: 'S11 history'})
      const readings = [board.getByLabel('S11 session price', {exact: true}), panel.getByLabel('S11 session price', {exact: true})]
      await testInfo.attach('display-and-execution-before-assertions', {body: JSON.stringify({displaySnapshot, execution: fixture.source.row.quote,
        readings: await Promise.all(readings.map(reading => reading.innerText()))}, null, 2), contentType: 'application/json'})
      for (const reading of readings) {
        await expect(reading).toContainText('No recent quote to display')
        await expect(reading).not.toContainText('No fresh quote from available feeds')
        await expect(reading).toHaveAttribute('title', /For display only; execution checks are separate/)
        await expect(reading).toHaveAttribute('title', /Midpoint is not a trade or guaranteed fill/)
      }
      await expect(readings[0]).toContainText('Regular bar $108.96')
      await expect(readings[1]).toContainText('Price signals use regular-session candles.')
      if (failure === 'generic unavailable') await expect(readings[1]).toHaveAttribute('title', /No usable bid\/ask midpoint was returned for this display\./)
      if (failure === 'specific recorded reason') await expect(readings[1]).toHaveAttribute('title', /Price-data detail: Missing or future quote timestamp/)
      await expect(panel.getByLabel('S11 strategy intent', {exact: true})).toContainText('BUY')
      await expect(panel.getByLabel('S11 spread verification', {exact: true})).toHaveText('IEX spread unverified')
      if (failure === 'generic unavailable') await panel.screenshot({path: testInfo.outputPath('display-unavailable-execution-eligible-panel.png')})
      await panel.getByRole('button', {name: 'Close', exact: true}).click()
      if (failure === 'generic unavailable') await board.screenshot({path: testInfo.outputPath('display-unavailable-execution-eligible-board.png')})
      await page.reload()
      await expect(board.getByLabel('S11 session price', {exact: true})).toContainText('No recent quote to display')
      await expect(board.getByLabel('S11 strategy intent', {exact: true})).toHaveText('BUY')
      await expect(board.getByLabel('S11 size', {exact: true})).toHaveText('3.3% of account')
      await page.getByRole('button', {name: 'details for S11', exact: true}).click()
      const detail = page.getByRole('region', {name: 'S11 decision details', exact: true})
      await detail.getByText('Recorded allocation & execution quote', {exact: true}).click()
      await expect(detail).toContainText('IEX · $95.00 bid / $105.00 ask')
      await expect(detail).toContainText('Sep 14, 2026, 10:01:00 AM ET')
      expect(JSON.stringify(displaySnapshot)).toBe(originalDisplay)
    } finally {
      await finish(testInfo, fixture)
    }
  })
}
