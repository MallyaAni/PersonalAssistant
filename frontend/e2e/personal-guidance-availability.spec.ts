import {expect, test, type Page, type Request} from '@playwright/test'

const OWNER = 'personal-guidance-availability-owner'
const DESK = `/api/v1/market/${OWNER}/desk`
const SESSION = '2026-10-13'
const WRITTEN = `${SESSION}T23:47:45Z`
type Mode = 'unavailable guidance' | 'genuine hold' | 'blocked buy' | 'timing wait'
type State = {mode: Mode; mine: number; requests: Map<Request, boolean>; errors: string[]; observed: string[]}

test.setTimeout(45000)

// Preserve actual learned-response failure fields while keeping valid holds and timing distinct.
function decision(mode: Mode) {
  const at = new Date().toISOString(), deadline = new Date(Date.now() + 120000).toISOString()
  const ordinary = mode === 'blocked buy' || mode === 'timing wait'
  const row = {action: mode === 'blocked buy' ? 'Buy' : 'Hold', strategy_action: ordinary ? 'Buy' : 'Hold',
    executable: false, move_weight: 0, strategy_move_weight: ordinary ? 0.02 : 0,
    blocker: mode === 'unavailable guidance' ? 'Exact approved learned plan required'
      : mode === 'blocked buy' ? 'Personal buy pending' : mode === 'timing wait' ? 'Learned timing waiting' : null,
    reason: mode === 'genuine hold' ? 'At learned target' : 'Guidance evidence is not executable',
    current_weight: 0, target_weight: ordinary ? 0.02 : 0, delta_weight: ordinary ? 0.02 : 0,
    valid_until: ordinary ? deadline : null,
    quote: {feed: 'iex', at, bid: 99.99, ask: 100.01, spread_verified: true, eligible: true, reason: 'Observed quote', valid_until: deadline},
    ...(mode === 'timing wait' ? {timing: {rule: 'live-probability-timing/1-research'},
      learned_timing: {policy: 'live-probability-timing/1-research', state: 'wait', at, reason: 'Awaiting timing'}} : {})}
  return {version: 'learned-personal-guidance/1', as_of: at, session: SESSION, written: WRITTEN,
    equity: 100000, holdings: {}, rows: {AAOI: row},
    ...(mode === 'timing wait' ? {timing: {rule: 'live-probability-timing/1-research'}} : {})}
}

// Isolate the actual app from accounts and providers, allowing only an explicit read-only guidance POST.
async function install(page: Page, state: State, baseURL: string) {
  page.on('pageerror', error => state.errors.push(error.message))
  page.on('console', message => {if (message.type() === 'error' || message.type() === 'warning') state.errors.push(message.text())})
  page.on('requestfinished', request => {if (state.requests.has(request)) state.requests.set(request, true)})
  page.on('requestfailed', request => state.errors.push(`Failed: ${request.method()} ${request.url()}`))
  page.on('response', response => {if (response.status() >= 400) state.errors.push(`HTTP ${response.status()} ${response.url()}`)})
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (url.origin !== new URL(baseURL).origin) {
      state.errors.push(`External request: ${url.origin}`)
      return route.abort('blockedbyclient')
    }
    if (!path.startsWith('/api/')) return route.continue()
    state.requests.set(request, false)
    if (request.method() !== 'GET' && !(request.method() === 'POST' && path === `${DESK}/mine`)) {
      state.errors.push(`Forbidden write: ${request.method()} ${path}`)
      return route.fulfill({status: 418, json: {detail: 'No mutation route'}})
    }
    const at = new Date().toISOString()
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: OWNER, is_admin: false, desk_access: true, desk_write: false}
    else if (path.startsWith('/api/v1/conversations/')) json = {conversations: [], messages: []}
    else if (path === DESK) json = {latest: {session: SESSION, written: WRITTEN,
      grades: {AAOI: {grade: 'A'}}, targets: {policy: 'grade-led-learned-sizing/1', weights: {AAOI: 0.02}},
      actions: [], book: [], briefs: {}, regime: {exposure: 1, flags: []}, event_risk: {}}, sessions: [SESSION]}
    else if (path === `${DESK}/live`) json = {as_of: at, decision_session: SESSION, quotes: {}, technical: {}, technical_detail: {}, market_status: {phase: 'closed'}}
    else if (path === `${DESK}/session-prices`) json = {session: 'closed', signal_scope: 'regular-session', as_of: at, quotes: {}}
    else if (path === `${DESK}/holdings`) json = {holdings: []}
    else if (path === `${DESK}/paper`) json = {as_of: at, equity: 100000, cash: 100000, positions: [], orders: [], recorded_fills: [],
      activity: {session: SESSION, complete: true, fills: []}, plan: {policy: 'grade-led-learned-sizing/1', orders: []}}
    else if (path === `${DESK}/paper/history`) json = {source: 'paper_account_records', rows: []}
    else if (path === `${DESK}/mine`) {
      const inputs = request.postDataJSON()
      expect(inputs.record_history).toBe(false)
      expect(inputs.equity).toBe(100000)
      state.mine++
      json = {session: SESSION, rows: [], grades_live: {}, decisions: decision(state.mode)}
    } else {
      state.errors.push(`Unspecified request: ${request.method()} ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Unspecified fixture route'}})
    }
    return route.fulfill({json})
  })
}

// Exercise the real personal preview twice while verifying failure reasons and neighboring valid states.
for (const mode of ['unavailable guidance', 'genuine hold', 'blocked buy', 'timing wait'] as Mode[]) {
  test(`Personal preview distinguishes ${mode}`, async ({page, baseURL}, info) => {
    const state: State = {mode, mine: 0, requests: new Map(), errors: [], observed: []}
    await install(page, state, baseURL!)
    await page.goto('/?deskView=paper#desk')
    await page.locator('details[aria-label="Personal portfolio"] > summary').click()
    const preview = page.getByLabel('Personal action preview', {exact: true})
    const intent = preview.getByLabel('AAOI strategy intent', {exact: true})
    await expect.poll(() => state.mine).toBeGreaterThan(0)
    for (let pass = 0; pass < 2; pass++) {
      if (pass) {
        const prior = state.mine
        await page.getByRole('button', {name: 'Refresh', exact: true}).click()
        await expect.poll(() => state.mine).toBeGreaterThan(prior)
      }
      if (mode === 'unavailable guidance') {
        await expect(intent).toContainText('Unavailable')
        await expect(intent).toContainText('Exact approved learned plan required')
        await expect(intent).not.toContainText('Hold')
      } else if (mode === 'genuine hold') {
        await expect(intent).toContainText('Hold')
        await expect(intent).not.toContainText('Unavailable')
      } else if (mode === 'blocked buy') {
        await expect(intent).toContainText('BUY')
        await expect(intent).toContainText('Blocked now')
        await expect(intent).toContainText('Personal buy pending')
      } else {
        await expect(intent).toContainText('Wait')
        await expect(intent).not.toContainText('Unavailable')
      }
      await expect(preview.getByLabel('AAOI personal trade size', {exact: true})).toHaveCount(0)
      await expect(preview.getByLabel('AAOI personal entry limit', {exact: true})).toHaveCount(0)
      state.observed.push(await intent.innerText())
    }
    await expect.poll(() => [...state.requests.values()].every(Boolean)).toBe(true)
    expect(state.errors).toEqual([])
    await info.attach('personal-guidance-observations', {body: JSON.stringify({mode, mine: state.mine, observed: state.observed, diagnostics: state.errors, requests: state.requests.size}, null, 2), contentType: 'application/json'})
  })
}
