import { expect, test, type Page } from '@playwright/test'
import type { NeuralStudyEvidence, NeuralStudyScorecard } from '../src/services/api'

const USER = 'ani.mallya'

// Supply distinct cost/year outcomes so a stale selection cannot accidentally pass.
const scorecard = (cost: number, total: number): NeuralStudyScorecard => ({
  first_session: '2025-01-02', last_session: '2026-09-21', cost_bps: cost,
  rows: {
    candidate: {total_return: total, cagr: total / 2, max_drawdown: -.2, sharpe_zero_risk_free: 0, annual_traded_notional_over_mean_nav: 0},
    incumbent: {total_return: .15, cagr: .08, max_drawdown: -.12, sharpe_zero_risk_free: 1.2, annual_traded_notional_over_mean_nav: 2.5},
    equal_weight: {total_return: .1, cagr: .05, max_drawdown: -.1, sharpe_zero_risk_free: .9, annual_traded_notional_over_mean_nav: 1},
    SPY: {total_return: .08, cagr: .04, max_drawdown: -.09, sharpe_zero_risk_free: .8, annual_traded_notional_over_mean_nav: .5},
    QQQ: {total_return: null, cagr: null, max_drawdown: null, sharpe_zero_risk_free: null, annual_traded_notional_over_mean_nav: null},
  },
})

// Keep research fixtures separate from personal recommendation or trading writes.
const studyFixture = (): NeuralStudyEvidence => {
  const low = scorecard(10, .1)
  low.calendar_years = {'2025': {...scorecard(10, .04), last_session: '2025-12-31'}}
  return {
    policy: 'research-only', title: 'Price-only neural ranking test', status: 'completed',
    decision: 'Retain the incumbent; this test does not support adoption.',
    limitations: ['Price features only; fundamental units are unverified.', 'Reconstructed grades are not archived live decisions.'],
    tables: {'10': low, '25': scorecard(25, -.03)},
  }
}

// Exercise the real Research route with deterministic read-only API responses.
const prepare = async (page: Page, study?: NeuralStudyEvidence) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => { if (request.url().includes('/api/')) errors.push(request.url()) })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let json: object = {}
    if (path.endsWith('/auth/session')) json = {authentication_required: true, user_id: USER, is_admin: true, expires_at: '2030-01-01T00:00:00Z'}
    else if (path.endsWith('/desk')) json = {latest: null, sessions: [], neural_study: study}
    else if (path.endsWith('/desk/live')) json = {quotes: {}, technical: {}, technical_detail: {}, stale: true, as_of: null}
    else if (path.endsWith('/desk/holdings')) json = {holdings: []}
    else if (path.endsWith('/desk/mine')) json = {rows: [], grades_live: {}}
    else if (path.endsWith('/desk/paper')) json = {positions: [], orders: [], equity: 0, cash: 0}
    else if (path.endsWith('/desk/intraday')) json = {rows: [], top_buys: [], changed: []}
    else if (path.includes('/conversations')) json = {conversations: [], messages: []}
    return route.fulfill({json})
  })
  await page.goto('/?deskView=research#desk')
  return errors
}

// Costs and periods change actual rows while zero, negative and missing values stay distinct.
test('research neural study switches costs and years without implying adoption', async ({page}) => {
  const errors = await prepare(page, studyFixture())
  const card = page.getByRole('region', {name: 'Price-only neural ranking test'})
  const table = card.getByRole('table', {name: 'Neural ranking study results'})
  const candidate = table.getByRole('row').filter({hasText: 'Neural ranking candidate'})
  await expect(card).toContainText('separate from the frozen nightly neural model · not adopted')
  await expect(card.getByLabel('Neural study decision')).toHaveText('Retain the incumbent; this test does not support adoption.')
  await expect(candidate).toContainText('10.0%')
  await expect(candidate).toContainText('−20.0%')
  await expect(candidate.getByRole('cell').nth(3)).toHaveText('0.00')
  await expect(candidate).toContainText('0.00×')
  await expect(table.getByRole('row').filter({hasText: /^QQQ/})).toContainText('—')
  await expect(table.getByRole('row').filter({hasText: /^QQQ/})).not.toContainText('0.0%')
  await card.getByLabel('Neural study period').selectOption('2025')
  await expect(candidate).toContainText('4.0%')
  await expect(card).toContainText('2025-01-02 to 2025-12-31')
  await card.getByLabel('Neural study trading cost').selectOption('25')
  await expect(card.getByLabel('Neural study period')).toHaveValue('full')
  await expect(candidate).toContainText('−3.0%')
  await expect(card).toContainText('25 bp per traded dollar')
  await expect(card).toContainText('does not change live recommendations or submit orders')
  await expect(card).not.toContainText('neural is live')
  await expect(card.getByLabel('Neural study limitations')).toContainText('fundamental units are unverified')
  await card.screenshot({path: 'test-results/neural-study-research.png'})
  expect(errors).toEqual([])
})

// An absent optional study adds neither an empty card nor fabricated results.
test('research neural study is absent when evidence is not published', async ({page}) => {
  const errors = await prepare(page)
  await expect(page.getByRole('heading', {name: 'Desk', exact: true})).toBeVisible()
  await expect(page.getByRole('region', {name: 'Price-only neural ranking test'})).toHaveCount(0)
  expect(errors).toEqual([])
})

// Missing cost evidence must not reuse the other cost's attractive results.
test('research neural study shows unavailable cost evidence explicitly', async ({page}) => {
  const study = studyFixture()
  delete study.tables['25']
  const errors = await prepare(page, study)
  const card = page.getByRole('region', {name: 'Price-only neural ranking test'})
  await card.getByLabel('Neural study trading cost').selectOption('25')
  await expect(card).toContainText('Results unavailable for this cost and period.')
  await expect(card.getByRole('table')).toHaveCount(0)
  expect(errors).toEqual([])
})
