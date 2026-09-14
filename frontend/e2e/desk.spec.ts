import { expect, test, type Page } from '@playwright/test'

// Deterministic browser acceptance for the trading desk page. The desk is the
// operator's own page, so the session is mocked as an operator and every desk
// endpoint is answered from fixture shapes written from the real record — the
// curve, the changes, the per-name history and the autopsy are all read-only
// views of files the nightly run wrote, so the browser never needs a runtime.

const USER = 'ani.mallya'

// Quote eligibility expires on screen even if polling returns the same older response.
test('plan action expires and preserves its quoted source', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const now = new Date('2026-09-09T14:00:00Z')
  await page.clock.install({time: now})
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk/mine?*`, route => route.fulfill({json: {
    session: latest.session, rows: [], grades_live: {}, decisions: {
      session: latest.session, written: latest.written, equity: 100000, holdings: {AAPL: 60}, as_of: now.toISOString(),
      rows: {AAPL: {action: 'Buy eligible', reason: 'Scheduled addition; confirm cash and broker price', target_weight: .1, current_weight: 0, delta_weight: .1,
        valid_until: '2026-09-09T14:00:30Z', quote: {feed: 'sip', bid: 199.99, ask: 200.01, at: now.toISOString(), eligible: true, valid_until: '2026-09-09T14:00:30Z', reason: 'Quote checks passed'}}},
    },
  }}))
  await page.goto('/#desk')
  const cell = page.getByLabel('AAPL plan action')
  await expect(cell).toContainText('Buy eligible')
  await cell.getByText('Position & quote').click()
  await expect(cell).toContainText('SIP')
  await expect(cell).toContainText('10.0 pp')
  await page.clock.fastForward(31_000)
  await expect(cell).toContainText('Wait')
  await expect(cell).not.toContainText('Buy eligible')
  await expect(cell).toContainText('expired')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Empty forward outcomes never display zero returns or invented confidence.
test('forward evidence distinguishes unobserved outcomes from zero performance', async ({page}) => {
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], forward_evidence: {status: 'collecting_forward_evidence', versions: [{
      version: 'candidate/2', decision_count: 10, pending_daily_validation: 10, corporate_actions_through: '2026-09-08',
      outcomes: [{signal_count: 0, decision_days: 0, cost_bps_per_side: 10, grades: []}],
      portfolios: [{cost_bps: 10, fill_intervals: 0, status: 'insufficient_forward_data', arms: {}}],
    }]},
  }}))
  await page.goto('/#desk')
  await page.getByText('Forward evidence · research', {exact: true}).click()
  const evidence = page.locator('details', {has: page.getByText('Forward evidence · research', {exact: true})})
  await expect(evidence).toContainText('10 decisions awaiting validation')
  await expect(evidence).toContainText('No matured 5/20-session grade outcomes yet')
  await expect(evidence).not.toContainText('0.00%')
})

// A stale observation cannot erase a durable active cycle from the status heading.
test('stale FOMC recovery keeps the active cycle paused', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], event_policy: {enabled: true},
    event_status: {as_of: '2026-09-01T14:00:00Z', stale: true, active: true,
      status: 'reduction settled', pending_orders: 0},
  }}))
  await page.goto('/#desk')
  const banner = page.getByLabel('FOMC exposure policy')
  await expect(banner).toContainText('FOMC · portfolio adjustments paused')
  await expect(banner).toContainText('last known status')
  await expect(banner).not.toContainText('decision missing')
  await expect(banner).toContainText('An event cycle is recorded')
  await expect(banner).not.toContainText('Enabled for the next nightly run')
  await expect(page.getByLabel('Cash exposure')).toContainText('FOMC overrides the scheduled plan')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Current recovery evidence takes priority while the archived nightly decision stays dated.
test('FOMC recovery displays current intent and pauses the portfolio plan', async ({page}) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest, sessions: [latest.session], event_policy: {enabled: true},
    event_status: {as_of: new Date().toISOString(), stale: false, active: true,
      status: 'reduction pending', pending_orders: 2,
      policy: {session: latest.session, factor: .5, calendar_known: true, decision_date: '2026-09-16'}},
  }}))
  await page.goto('/#desk')
  await expect(page.getByLabel('FOMC exposure policy')).toContainText('FOMC · reduction pending')
  await expect(page.getByLabel('FOMC exposure policy')).toContainText('2 event orders awaiting reconciliation')
  await expect(page.getByRole('heading', {name: /^Portfolio plan/})).toContainText('FOMC takes priority')
  await expect(page.getByLabel('Cash exposure')).toContainText('FOMC overrides the scheduled plan')
  await expect(page.getByLabel('FOMC exposure policy')).not.toContainText('decision missing')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Percent allocations need no cash input and disappear at their evidence deadline.
for (const [weight, displayed] of [[.047, '4.7%'], [.0002, '<0.1%']] as const) {
test(`research percentages ${displayed} expire independently of account sizing`, async ({page}) => {
  await page.clock.install({time: new Date('2026-09-09T14:00:00Z')})
  await page.route(`**/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(), sessions: ['2026-09-08'], intraday_research: {
      status: 'available', session: '2026-09-08', bar: '20:00',
      valid_until: '2026-09-09T14:00:30Z', targets: {AAPL: weight, NVDA: 0},
    },
  }}))
  await page.goto('/#desk')
  const rankings = page.locator('section', {has: page.getByRole('heading', {name: 'Stock rankings'})})
  await expect(rankings.locator('tr', {hasText: 'AAPL'})).toContainText(displayed)
  await expect(rankings.locator('tr', {hasText: 'NVDA'})).toContainText('0.0%')
  await expect(page.getByLabel('Available cash to allocate ($)')).not.toBeVisible()
  await page.clock.fastForward(31_000)
  await expect(rankings).not.toContainText(displayed)
  await expect(rankings).not.toContainText('0.0%')
})
}

// Execution history distinguishes an empty broker response from missing evidence.
test('paper execution distinguishes fills from unavailable history', async ({page}) => {
  await page.route(`**/market/${USER}/desk/paper`, route => route.fulfill({json: {
    orders: [], activity: {session: '2026-09-14', complete: true, fills: []},
  }}))
  await page.goto('/#desk')
  const execution = page.getByLabel('Paper execution', {exact: true})
  await expect(execution).toContainText('0 open orders')
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
  page.on('requestfailed', request => consoleErrors.push(`Failed request: ${request.method()} ${request.url()}`))
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
  await page.addInitScript(() => {
    // The clock decides the theme (dark from 19:00 to 06:59), which would
    // flip every assertion with the time of day; an explicit choice is stable.
    localStorage.setItem('anios.theme', 'light')
  })
  await page.route('http://localhost:8000/api/v1/auth/session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      authentication_required: true,
      user_id: USER,
      expires_at: '2026-09-09T00:00:00Z',
      is_admin: true,
    }),
  }))
  await page.route('http://localhost:8000/api/v1/conversations/ani.mallya', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversations: [] }),
    }),
  )
  const record = deskRecord()
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/holdings`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ holdings: [{ ticker: 'AAPL', shares: 60, entry_price: 91.25, entry_date: '2026-08-28' }] }),
  }))
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/live`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      as_of: '2026-09-08T20:00:00Z',
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
  // The intraday re-read: nothing new on the candle, so the board is the
  // record's; the route must answer or the page logs a connection error.
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/intraday*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      as_of: '2026-09-08T20:00:00Z',
      session: '2026-09-08',
      equity: 104200,
      top_buys: [],
      rows: [],
      changed: [],
    }),
  }))
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/paper`, route => route.fulfill({
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
    }),
  }))
  // The drill-down's live technical read: the model's plain words over the
  // analyst's live readings, with the deterministic lines as the fallback.
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/live/read/*`, route => {
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
  // The drill-down fetches the newest earnings release read on open. Most
  // fixtures name no read (the block hides); the AAPL-specific route
  // registered below overrides this one for the same-day earnings test.
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/earnings/*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ user_id: USER, symbol: '', read: null }),
  }))
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/mine*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      // MSFT is C at the close but its live read lifts it to B: the full
      // list must show the live grade and order it above nothing lower.
      session: '2026-09-08',
      grade_valid_until: Object.fromEntries(['MSFT', 'AAPL', 'NVDA'].map(ticker => [ticker, new Date(Date.now() + 15 * 60 * 1000).toISOString()])),
      grades_live: {
        MSFT: { grade_live: 'B', score_live: 0.5, technical_now: 0.85, technical_close: 0.5,
          stances_live: { fundamental: -1, technical: 1, sentiment: 0, value: 1, rotation: 0 },
          ranks_live: { fundamental: 0.3, technical: 0.85, sentiment: 0.5, value: 0.7, rotation: 0.4 } },
      },
      rows: [
        {
          ticker: 'AAPL',
          action: 'add',
          in_book: true,
          grade: 'A',
          grade_live: 'A',
          score_live: 0.92,
          technical_now: 0.9,
          technical_close: 0.8,
          rank: 1,
          score: 0.92,
          stances: { fundamental: 1, technical: 1 },
          ranks: { fundamental: 0.9, technical: 0.8 },
          why: 'The desk adds to its best name.',
          reason: 'F The business keeps growing\nT The trend holds',
          target_weight: 0.06,
          current_weight: 0.04,
          delta_weight: 0.02,
          shares: 60,
          entry_price: 91.25,
          entry_date: '2026-08-28',
          last: 102,
          pl_pct: 0.117,
          last_close: 102,
          high_20: 105,
          grade_margin: 0.3,
          leaves_if: 'drops below A',
          until_rebalance: 18,
          rebalance_due: false,
        },
        {
          ticker: 'NVDA',
          action: 'buy',
          in_book: false,
          grade: 'A',
          grade_live: 'A',
          score_live: 0.61,
          technical_now: null,
          technical_close: null,
          rank: 2,
          score: 0.61,
          stances: { fundamental: 1, rotation: 1 },
          ranks: { fundamental: 0.95, rotation: 0.8 },
          why: 'A new A-grade name to open.',
          reason: 'F Demand is real\nR The group leads',
          target_weight: 0.05,
          current_weight: 0,
          delta_weight: 0.05,
          shares: 0,
          entry_price: null,
          entry_date: null,
          last: 130,
          pl_pct: null,
          last_close: 130,
          high_20: 135,
          grade_margin: 0.1,
          leaves_if: 'drops below A',
          until_rebalance: 18,
          rebalance_due: false,
        },
      ],
    }),
  }))
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/history/AAPL`, route => route.fulfill({
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/earnings/AAPL`, route => route.fulfill({
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/history/MSFT`, route => route.fulfill({
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/trading/autopsy`, route => route.fulfill({
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
  await page.goto('/#desk')
  const heading = page.getByRole('heading', {name: /^(Stock rankings|Every grade)$/})
  await expect(heading).toBeVisible()
  await page.waitForLoadState('networkidle')
  const text = await page.getByRole('main').innerText()
  const box = await heading.boundingBox()
  console.log(JSON.stringify({visibleWords: text.trim().split(/\s+/).length, rankingsY: box?.y}))
  await page.screenshot({path: `/private/tmp/desk-density-${new URL(page.url()).port}.png`, fullPage: true})
  expect(box!.y).toBeLessThan(340)
  expect(text).not.toContain('Set up the board')
  expect(text).not.toContain('Targets for the next rebalance')
  expect(text.trim().split(/\s+/).length).toBeLessThan(450)
  await expect(page.getByLabel('Cash exposure')).toContainText('Paper cash 11.5%')
  await expect(page.getByLabel('Cash exposure')).toContainText('Planned cash 94.0%')
  await page.setViewportSize({width: 390, height: 844})
  await expect(page.getByRole('heading', {name: 'Stock rankings'})).toBeVisible()
  expect(await page.getByRole('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

test('separates dated inflation facts from research-only model judgement', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({json: {
    latest: deskRecord(), sessions: ['2026-09-08'],
    economics: {
      observed_at: new Date().toISOString(), collection_stale: false, model: 'deepseek-v4-flash',
      assessment: {pressure: 'mixed', evidence_ids: ['CPIAUCSL'], status: 'model_assessment'},
      facts: [{id: 'CPIAUCSL', label: 'CPI', status: 'available', period: '2026-08-01', source: 'https://fred.stlouisfed.org/series/CPIAUCSL', month_change_pct: .23, year_change_pct: 3.45, previous_year_change_pct: null}],
    },
  }}))
  await page.goto('/#desk')
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

// Confirm cash explicitly and discard the preview whenever the budget changes.
test('previews one confirmed cash budget and clears changed inputs', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/conversations/ani.mallya/*', route => route.fulfill({json: {messages: []}}))
  await page.route('**/desk/funding-preview', route => {
    expect(route.request().postDataJSON()).toEqual({ equity: 100000, available_cash: 200 })
    return route.fulfill({json: {
      session: '2026-09-08', calculated_at: new Date().toISOString(), estimated_cost: 190,
      unallocated_cash: 10, cash_limited: true, price_times: {},
      rows: [{ticker: 'AAPL', reference_price: 190, held_shares: 0, target_total_shares: 31, additional_shares: 1, estimated_cost: 190}],
    }})
  })
  await page.goto('/#desk')
  const cash = page.getByLabel('Available cash to allocate ($)')
  await page.getByText('Calculate shares with available cash', {exact: true}).click()
  await cash.fill('200')
  await page.getByRole('button', {name: 'Confirm cash and preview'}).click()
  await expect(page.getByText('Additions reduced together to fit cash.', {exact: false})).toBeVisible()
  await expect(page.getByRole('columnheader', {name: 'Additional shares', exact: true})).toBeVisible()
  await cash.fill('100')
  await expect(page.getByRole('columnheader', {name: 'Additional shares', exact: true})).toHaveCount(0)
  await page.waitForLoadState('networkidle')
  // This fixture has no saved conversation; leave every desk storage key intact.
  await page.evaluate(() => localStorage.removeItem('anios_conversation_id:ani.mallya'))
  await page.reload()
  await page.getByText('Calculate shares with available cash', {exact: true}).click()
  await expect(cash).toHaveValue('')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Keep experimental allocations explicit and clear their results on policy changes.
test('research sizing displays reductions and clears the previous policy', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/desk/funding-preview', route => {
    expect(route.request().postDataJSON().mode).toBe('intraday_research')
    return route.fulfill({json: {
      mode: 'intraday_research', session: '2026-09-08', calculated_at: new Date().toISOString(),
      valid_until: new Date(Date.now() + 600000).toISOString(), macro: {exposure: .5, defensive: true},
      estimated_cost: 0, unallocated_cash: 0, rows: [], price_times: {},
      reductions: [{ticker: 'AAPL', held_shares: 20, target_total_shares: 10, reduction_shares: 10}],
    }})
  })
  await page.goto('/#desk')
  await page.getByText('Calculate shares with available cash', {exact: true}).click()
  await page.getByLabel('Sizing policy').selectOption('intraday_research')
  await expect(page.getByText('Research only · current technical sizing', {exact: false})).toBeVisible()
  await page.getByLabel('Available cash to allocate ($)').fill('0')
  await page.getByRole('button', {name: 'Confirm cash and preview'}).click()
  await expect(page.getByText('defensive macro condition active', {exact: false})).toBeVisible()
  await expect(page.getByText('AAPL: 20 held → 10 target shares · reduction 10')).toBeVisible()
  await page.getByLabel('Sizing policy').selectOption('evening')
  await expect(page.getByText('AAPL: 20 held → 10 target shares · reduction 10')).toHaveCount(0)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

test('renders the desk at a glance with the track record', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await page.getByText('Performance & practice account', {exact: true}).click()
  await expect(page.getByRole('main').getByRole('heading', { level: 2, name: 'Desk' })).toBeVisible()

  const glance = page.getByLabel('The desk at a glance')
  await expect(glance).toBeVisible()
  await expect(glance.getByText('Practice account', { exact: true })).toBeVisible()
  await expect(glance.getByText('$104,200')).toBeVisible()
  // The lifetime and today moves read as percentages, not a bare dollar
  // figure: 0.042 lifetime of the starting equity, 0.003 today. Both sit in
  // one "Today" cell rather than being shown twice, once as a percent in the
  // account cell and once as dollars in their own cell.
  await expect(glance.getByText('4.2%', { exact: false })).toBeVisible()
  await expect(glance.getByText('Broker day P/L', { exact: true })).toBeVisible()
  await expect(glance.getByText(/\+\$31[23]/)).toBeVisible()
  await expect(glance.getByText(/\+0\.3%/)).toBeVisible()
  await expect(glance.getByText('Stored simulation · under review')).toBeVisible()
  await expect(glance.getByText('borrowing without financing costs', { exact: false })).toBeVisible()
  await expect(glance.getByText('vs SPY', { exact: false })).toBeVisible()
  await expect(glance.getByText('6% invested')).toBeVisible()  // 6,120 of 104,200 live

  // The regime leads the board, in plain words, and says what it is doing
  // about it.
  await expect(page.getByRole('note')).toContainText('Market risk')
  await expect(page.getByRole('note')).toContainText('AI trading activity is below its historical median')
  await expect(page.getByRole('note')).toContainText('target-size multiplier is 80%')

  // What moved since the last session, which the page used to throw away.
  await expect(page.getByText('What changed since the last session')).toBeVisible()
  await expect(page.getByText('Upgraded: NVDA B→A')).toBeVisible()
  await expect(page.getByText('Changes in target weights at the next rebalance: add AAPL')).toBeVisible()

  // The trust anchor: the curve and its summary numbers, as an SVG the page
  // draws itself.
  const record = page.getByText('The desk’s track record')
  await expect(record).toBeVisible()
  await expect(page.getByRole('img', { name: "The desk's track record against SPY and QQQ" })).toBeVisible()
  await expect(page.getByText('CAGR')).toBeVisible()
  await expect(page.getByText('31.0%', { exact: true })).toBeVisible()

// A row reads in plain words first, and the ticker opens the drill-down.
  // The board is not due a rebalance for 18 sessions, so it says "targets
  // for the next rebalance" rather than teaching a daily trading cadence.
  await expect(page.getByRole('heading', {name: /^Portfolio plan/})).toBeVisible()
  await expect(page.getByLabel('Reading the current picks')).toContainText('not a probability of profit')
  await expect(page.getByRole('columnheader', {name: 'Target move', exact: true})).toBeVisible()
  await expect(page.getByText('not scheduled yet', {exact: true}).first()).toBeVisible()
  await expect(page.getByRole('columnheader', {name: 'broker mark', exact: true})).toBeVisible()
  await expect(page.getByText('in 18 trading days', { exact: true })).toBeVisible()
  // No trade is scheduled before the rebalance, so no row carries a "done"
  // button: the targets read as targets, not as instructions to buy now.
  await expect(page.getByRole('button', { name: 'record fill', exact: true })).not.toBeVisible()
  await expect(page.getByText('The desk adds to its best name.', { exact: false })).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The page used to show the buys twice - once in a standalone "Best buys
// right now" list with its own Buy button and once as the board's buy rows -
// and the broker's live positions twice - once in its own section and once
// again in the behind-the-fold "Practice account" panel. Each thing is shown
// exactly once now: the board owns the buys, and the live positions table
// exists in one place even with the details open.
test('shows each thing once, not twice', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')

  // The board is the single buy list; no standalone best-buys shortlist.
  await expect(page.getByText('Best buys right now')).toHaveCount(0)
  await expect(page.getByRole('heading', {name: /^Portfolio plan/})).toBeVisible()

  // The broker's live positions are one table on the page.
  await expect(page.getByText('Practice positions')).toBeVisible()
  await expect(page.locator('section', {has: page.getByRole('heading', {name: /^Practice positions/})})).toContainText('$91.25')

  // Opening the details must not add a second copy of the same positions:
  // the details' "Practice account" panel keeps its summary but shows the
  // positions table only when the broker is away, because the live section
  // above already shows them.
  await page.getByRole('button', { name: 'Show practice account details' }).click()
  await expect(page.getByText('Stock rankings')).toBeVisible()
  // Ordered by grade, best first: AAPL (A), then NVDA (B) and MSFT (lifted
  // to B by its live read), and MSFT shows the live grade, not the close's.
  const everyGrade = page.locator('section', { has: page.getByRole('heading', { name: 'Stock rankings' }) })
  await expect(everyGrade.locator('tbody tr td:first-child')).toHaveText(['AAPL', 'NVDA', 'MSFT'])
  await expect(everyGrade.locator('tbody tr').last().locator('td').nth(2).locator('span')).toHaveText('B')
  await expect(everyGrade.locator('tbody tr').last()).toContainText('intraday')
  await expect(everyGrade.locator('tbody tr').last()).toContainText('Since evening: T no view → for')
  await expect(everyGrade.getByRole('columnheader', {name: 'Analysis · 2026-09-08 close'})).toBeVisible()
  await expect(everyGrade).not.toContainText('no change in comparable analyst votes')
  await expect(everyGrade).toContainText('not probability of profit')
  await page.getByText('Performance & practice account', {exact: true}).click()
  await expect(page.getByText('Practice account', { exact: true })).toBeVisible()
  await expect(page.getByText('Gain so far')).toHaveCount(0)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Clicking a name must open its own history: what the desk said each
// session, what came next, and the name's own backtest against holding it
// and the benchmark.
test('drills into a name’s own history', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()

  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('Annualized mean while an A')).toBeVisible()
  await expect(dialog.getByText('Annualized mean while not')).toBeVisible()
  await expect(dialog.getByText('Sessions it was an A')).toBeVisible()
  await expect(dialog.getByText('41 of 60')).toBeVisible()
  await expect(dialog.getByText('Position changes')).toBeVisible()
  // Recorded evidence leads; unverified historical model claims require opening their archive.
  await expect(dialog.getByRole('heading', {name: 'Evening analysis · 2026-09-08'})).toBeVisible()
  await expect(dialog.getByText('growing earnings with the trend intact', { exact: false })).not.toBeVisible()
  await dialog.getByText('Archived model commentary · unverified', {exact: true}).click()
  await expect(dialog.getByText('growing earnings with the trend intact', { exact: false })).toBeVisible()
  // The live technical read is the model's plain words over the live tape.
  await expect(dialog.getByText('resistance is a swing high above', { exact: false })).toBeVisible()
  await expect(dialog.getByText('The last 2 sessions')).toBeVisible()
  // Each session shows which analysts voted, and the row the desk actually
  // wrote that night is marked as said.
  await expect(dialog.getByText('F+ T+ V·').first()).toBeVisible()
  await expect(dialog.getByText('said', { exact: true })).toHaveCount(1)
  await expect(dialog.getByText('a steady AI leader')).toBeVisible()
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).not.toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Reaction timing, extracted tone and precise financials must not imply a release date or revision.
test('shows accurately dated earnings evidence in the drill-down', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()

  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await expect(dialog).toBeVisible()
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
  await page.goto('/#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
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
  await page.goto('/#desk')
  await page.getByRole('button', { name: 'AAPL', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
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
  await page.goto('/#desk')
  await page.getByRole('button', { name: 'Show practice account details' }).click()
  await page.getByRole('button', { name: 'MSFT', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'MSFT history' })
  await expect(dialog).toBeVisible()
  // The evening grade chip renders even though the name is not a board row.
  await expect(dialog.getByText('expensive and the trend is quiet')).toBeVisible()
  // The drill-down shows the same live grade as the list: MSFT is B at the
  // candle even though the evening record says C.
  await expect(dialog.getByText('Bindicative intraday grade', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Technical read')).toBeVisible()
  await expect(dialog.getByText('Daily chart', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Weekly chart', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Longer-term reference levels')).toBeVisible()
  await expect(dialog.getByText('resistance is a swing high above', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/Technical rank at the available candle/)).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A holding the desk does not rate is an explicit review state, not a sell
// instruction: no trade was instructed, so the row carries no "done" button
// and the person's own shares stay visible.
test('an uncovered holding is a review state, not a sell', async ({ page }) => {
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/mine*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      grades_live: {},
      rows: [
        {
          ticker: 'IREN',
          action: 'uncovered',
          in_book: false,
          grade: '',
          grade_live: '',
          score_live: null,
          technical_now: null,
          technical_close: null,
          rank: null,
          score: null,
          stances: {},
          why: 'the desk does not cover this name, so it has no view on it',
          reason: '',
          target_weight: 0,
          current_weight: 0.03,
          delta_weight: 0,
          shares: 100,
          entry_price: 35.2,
          entry_date: '2026-08-28',
          last: 40,
          pl_pct: 0.13,
          last_close: 39,
          high_20: 41,
          grade_margin: null,
          until_rebalance: null,
          rebalance_due: true,
          leaves_if: 'your call: the desk does not cover it',
        },
      ],
    }),
  }))
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await expect(page.getByText('uncovered', { exact: true })).toBeVisible()
  await expect(page.getByText('100 shares held')).toBeVisible()
  await expect(page.getByRole('button', { name: 'record fill', exact: true })).not.toBeVisible()
  // A fresh book with no rebalance clock: the next session is the first
  // decision, so the board shows the next scheduled trades.
  await expect(page.getByText('scheduled trades due', {exact: true})).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The board names scheduled trades only when the paper
// book is actually due a rebalance; otherwise the rows are targets for a
// later one, and the countdown is named.
for (const action of ['add', 'sell']) {
// A confirmed partial fill persists its actual size and cost; opening the form writes nothing.
test(`records a confirmed ${action} fill and reads the position back after reload`, async ({ page }) => {
  let stored = [{ ticker: 'AAPL', shares: 60, entry_price: 91.25, entry_date: '2026-08-28' }]
  let writes = 0
  await page.route(`**/desk/holdings`, route => {
    if (route.request().method() === 'PUT') {
      stored = route.request().postDataJSON()
      writes += 1
    }
    return route.fulfill({ json: { holdings: stored } })
  })
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/mine*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      grades_live: {},
      rows: [
        {
          ticker: 'AAPL',
          action,
          in_book: true,
          grade: 'A',
          grade_live: 'A',
          score_live: 0.92,
          technical_now: null,
          technical_close: null,
          rank: 1,
          score: 0.92,
          stances: {},
          why: 'The desk adds to its best name.',
          reason: '',
          target_weight: 0.06,
          current_weight: 0.04,
          delta_weight: 0.02,
          shares: 0,
          entry_price: null,
          entry_date: null,
          last: null,
          pl_pct: null,
          last_close: 102,
          high_20: 105,
          grade_margin: 0.3,
          until_rebalance: 1,
          rebalance_due: true,
          leaves_if: 'drops below A',
        },
      ],
    }),
  }))
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await expect(page.getByText('scheduled trades due', {exact: true})).toBeVisible()
  await expect(page.getByText('in 1 trading days')).toBeVisible()
  await page.getByRole('button', { name: 'record fill', exact: true }).click()
  expect(writes).toBe(0)
  const form = page.getByRole('form', { name: 'Record AAPL fill' })
  await expect(form.getByLabel('Filled shares')).toHaveValue('')
  await expect(form.getByLabel('Average fill price')).toHaveValue('')
  await form.getByLabel('Filled shares').fill('6.5')
  await form.getByLabel('Average fill price').fill('98.76')
  if (action === 'sell') {
    await form.getByLabel('Filled shares').fill('80')
    await form.getByRole('button', { name: 'Save confirmed fill' }).click()
    await expect(page.getByText('Filled shares exceed the recorded position. Reconcile your positions first.')).toBeVisible()
    expect(writes).toBe(0)
    await form.getByLabel('Filled shares').fill('6.5')
  }
  await form.getByRole('button', { name: 'Save confirmed fill' }).click()
  await expect(form).not.toBeVisible()
  expect(writes).toBe(1)
  const expectedShares = action === 'add' ? 66.5 : 53.5
  expect(stored[0].shares).toBe(expectedShares)
  expect(stored[0].entry_price).toBeCloseTo(action === 'add' ? (60 * 91.25 + 6.5 * 98.76) / 66.5 : 91.25, 6)
  // The shell's unrelated draft conversation is ephemeral; only the holdings persist here.
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await page.getByRole('button', { name: 'edit my positions' }).click()
  await expect(page.locator(`input[value="${expectedShares}"]`)).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})
}

// A failed holdings read must not masquerade as an empty account that can be overwritten.
test('withholds position editing when existing holdings cannot be loaded', async ({ page }) => {
  await page.route('**/desk/holdings', route => route.fulfill({ status: 503, json: { detail: 'unavailable' } }))
  await page.goto('/#desk')
  await expect(page.getByRole('alert')).toContainText('Your positions could not be loaded.')
  await expect(page.getByRole('button', { name: 'edit my positions' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'record fill', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Record buy', exact: true })).toHaveCount(0)
})

// An off-schedule purchase outside the target book persists only after its actual fill is confirmed.
test('records a discretionary buy from rankings and reloads its actual shares and cost', async ({ page }) => {
  let stored = [{ticker: 'AAPL', shares: 5, entry_price: 100, entry_date: '2026-09-01'}]
  let writes = 0
  await page.route('**/desk/holdings', route => {
    if (route.request().method() === 'PUT') {
      writes += 1
      stored = route.request().postDataJSON()
    }
    return route.fulfill({json: {holdings: stored}})
  })
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await expect(page.getByRole('heading', {name: /^Portfolio plan/})).toBeVisible()
  const rankings = page.locator('section', {has: page.getByRole('heading', {name: 'Stock rankings', exact: true})})
  const row = rankings.getByRole('row').filter({has: page.getByRole('button', {name: 'MSFT', exact: true})})
  await row.getByRole('button', {name: 'Record buy', exact: true}).click()
  const form = row.getByRole('form', {name: 'Record MSFT buy'})
  await expect(form.getByLabel('Filled shares')).toHaveValue('')
  await expect(form.getByLabel('Average fill price')).toHaveValue('')
  expect(writes).toBe(0)
  await row.getByRole('button', {name: 'Cancel buy record'}).click()
  expect(writes).toBe(0)
  await row.getByRole('button', {name: 'Record buy', exact: true}).click()
  await form.getByLabel('Filled shares').fill('2.5')
  await form.getByLabel('Average fill price').fill('411.23')
  await form.getByLabel('Fill date').fill('2026-09-10')
  await form.getByRole('button', {name: 'Save confirmed buy'}).click()
  await expect(form).not.toBeVisible()
  expect(writes).toBe(1)
  expect(stored).toEqual([
    {ticker: 'AAPL', shares: 5, entry_price: 100, entry_date: '2026-09-01'},
    {ticker: 'MSFT', shares: 2.5, entry_price: 411.23, entry_date: '2026-09-10'},
  ])
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await expect(row).toContainText('2.5 shares recorded')
  expect(writes).toBe(1)
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// The method panel attributes the learner only when the saved decision identifies its input.
test('explains analyst weights and identifies the recorded expectations model', async ({ page }) => {
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({json: {
    latest: {...deskRecord(), provenance: {rule: {inputs: ['expectations-gap']}}},
  }}))
  await page.goto('/#desk')
  await page.getByText('How ranking and sizing work', {exact: true}).click()
  await expect(page.getByText('Current voting rules:')).toContainText('rotation carries half a vote')
  await expect(page.getByText('This evening decision includes the LightGBM expectations gap:')).toContainText('estimated revenue growth minus price-implied growth')
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/live`, route => {
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/live/read/*`, route => {
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

  await page.goto('/#desk')
  await page.getByRole('button', { name: 'Show practice account details' }).click()
  await page.getByRole('button', { name: 'AAPL', exact: true }).last().click()

  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await expect(dialog).toBeVisible()
  const stamp = dialog.locator('h4', { hasText: 'Technical read' })
  await expect(dialog.getByText('Support holds beneath the rally.', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/\$102/)).toBeVisible()
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
  await expect(dialog.getByText('4.1% below the 21-day EMA', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/\$110/)).toBeVisible()
  await expect(dialog.getByText(/Technical rank at the available candle/)).toContainText('20')
  await expect(stamp).toContainText('candle from Sep 8')
  const secondTime = (await stamp.textContent() ?? '').match(/\d{1,2}:\d{2}/)?.[0]
  expect(secondTime).toBeTruthy()
  expect(secondTime).not.toBe(firstTime)
  expect(refetchForNewCandle).toBe(1)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Old evidence stays visibly dated even when its explanation is newly generated.
test('dates old candles separately from explanations and labels indicative grades', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/live/read/*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      symbol: 'MSFT', read: 'The available candle is below the moving average.',
      now: .4, lines: { short: [], medium: [], long: [] },
      data_at: '2026-09-08T19:45:00Z', read_at: '2026-09-12T14:00:00Z', stale: true,
    }),
  }))
  await page.goto('/#desk')
  await expect(page.getByText('last known data · not current')).toBeVisible()
  await page.getByRole('button', { name: 'Show practice account details' }).click()
  await expect(page.getByText('intraday', {exact: true})).toBeVisible()
  await page.getByRole('button', { name: 'MSFT', exact: true }).last().click()
  const dialog = page.getByRole('dialog', { name: 'MSFT history' })
  const stamp = dialog.locator('h4', { hasText: 'Technical read' })
  await expect(stamp).toContainText('candle from Sep 8')
  await expect(stamp).toContainText('last known data')
  await expect(stamp).toContainText('explanation generated Sep 12')
  await expect(stamp).not.toContainText('live,')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The autopsy reads the person's own documents: what keeps repeating, what
// it has cost, and the plan. It is one click from the board.
test('analyzes the person’s own trading from their documents', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await page.getByRole('button', { name: 'analyze my trading' }).click()

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
  await page.goto('/#desk')
  await page.getByRole('button', {name: 'analyze my trading'}).click()
  await expect(page.getByText('Share a statement or journal in chat, then retry.', {exact: true})).toBeVisible()
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A grade must expire while the page is open, even if a cached endpoint repeats it.
test('an intraday grade expires without requiring a page reload', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.clock.install({time: new Date('2026-09-09T14:00:00Z')})
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/mine*`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      session: '2026-09-08', rows: [],
      grade_valid_until: {MSFT: '2026-09-09T14:01:00Z'},
      grades_live: {MSFT: {grade_live: 'B', score_live: 0.5}},
    }),
  }))
  await page.goto('/#desk')
  await page.getByRole('button', {name: 'Show practice account details'}).click()
  const grades = page.locator('section', {has: page.getByRole('heading', {name: 'Stock rankings', exact: true})})
  const msft = grades.locator('tbody tr').filter({has: page.getByRole('button', {name: 'MSFT', exact: true})})
  await expect(msft.locator('td').nth(2)).toContainText('B')
  await page.clock.fastForward('01:01')
  await expect(msft.locator('td').nth(2)).toContainText('C')
  await expect(msft).not.toContainText('indicative intraday grade')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A later decision must not inherit either targets or grades from an older snapshot.
test('a mismatched decision cannot display the previous intraday targets or grades', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/mine*`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      session: '2026-09-07', rows: [],
      grade_valid_until: {MSFT: new Date(Date.now() + 900000).toISOString()},
      grades_live: {MSFT: {grade_live: 'A+', score_live: 1}},
    }),
  }))
  await page.goto('/#desk')
  await page.getByRole('button', {name: 'Show practice account details'}).click()
  const grades = page.locator('section', {has: page.getByRole('heading', {name: 'Stock rankings', exact: true})})
  const msft = grades.locator('tbody tr').filter({has: page.getByRole('button', {name: 'MSFT', exact: true})})
  await expect(msft.locator('td').nth(2)).toContainText('C')
  await expect(msft).not.toContainText('indicative intraday grade')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Funding labels follow the stored artifact, never the latest deployed simulator alone.
test('cash-limited performance is distinguished from legacy simulated borrowing', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  latest.curve!.backtest!.funding_model = 'cash-at-fill-v1'
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({latest, changes: null}),
  }))
  await page.goto('/#desk')
  await page.getByText('Performance & practice account', {exact: true}).click()
  await expect(page.getByLabel('The desk at a glance')).toContainText('Cash-limited simulation')
  await expect(page.getByText('closing sales cannot fund earlier buys', {exact: false})).toBeVisible()
  await expect(page.getByText('Legacy simulation under review', {exact: false})).not.toBeVisible()
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// Actual receipts must expose dated evidence and keep legacy missing fields unknown.
test('execution receipts distinguish decisions, fills and historical submissions', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const latest = deskRecord()
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: {...latest, paper: {...latest.paper, settled: [
        {symbol: 'AAPL', side: 'buy', qty: 10, filled: 10, filled_price: 102, status: 'filled', decision_shortfall_bps: 200,
          execution: {decision_at: '2026-09-07T23:45:29Z', submitted_at: '2026-09-08T08:03:00Z', filled_at: '2026-09-09T13:33:06Z',
            reference_price: 100, reference_session: '2026-09-04', reference_source: 'daily panel close'}},
        {symbol: 'NVDA', side: 'sell', qty: 10, filled: 3, filled_price: 91, status: 'partial'},
      ]}}, sessions: ['2026-09-08'],
    }),
  }))
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/paper`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({reason: 'unreachable'}),
  }))
  await page.goto('/#desk')
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: deskRecord(), sessions: ['2026-09-08'],
      event_policy: {enabled: true, version: 'fomc-3-session-weakness/1', evaluation_since: '2026-06-18'},
    }),
  }))
  await page.goto('/#desk')
  const banner = page.getByRole('region', {name: 'FOMC exposure policy'})
  await expect(banner).toContainText('FOMC · decision missing')
  await expect(banner).toContainText('does not confirm any reduction')
  await expect(banner).toContainText('Paper account only')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// An active event must not expose ordinary rebalance targets as executable fill rows.
test('FOMC reduction takes priority over regular target execution', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: {...deskRecord(), event_risk: {
        session: '2026-09-11', enabled: true, factor: 0.5, calendar_known: true,
        decision_date: '2026-09-16', execution_pending: true,
      }}, sessions: ['2026-09-11'],
      event_policy: {enabled: true, version: 'fomc-3-session-weakness/1', evaluation_since: '2026-06-18'},
    }),
  }))
  await page.goto('/#desk')
  await expect(page.getByRole('heading', {name: /^Portfolio plan.*FOMC takes priority/})).toBeVisible()
  await expect(page.getByRole('button', {name: 'record fill', exact: true})).toHaveCount(0)
  await expect(page.getByRole('region', {name: 'FOMC exposure policy'})).toContainText('reduction triggered or still in force')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// The target board must take its content height instead of clipping rows inside a flex item.
test('target rows are not hidden inside a vertically collapsed section', async ({ page }) => {
  await page.goto('/#desk')
  const board = page.locator('section', {has: page.getByRole('columnheader', {name: 'Target move', exact: true})})
  await expect(board.locator('tbody tr')).toHaveCount(2)
  const size = await board.evaluate(element => ({height: element.clientHeight, content: element.scrollHeight}))
  expect(size.content).toBeLessThanOrEqual(size.height)
})

// A cash-limited event ending must expose its unbought shares as an outcome.
test('cash-limited FOMC restoration never claims the remainder was filled', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      latest: {...deskRecord(), event_risk: {
        session: '2026-09-17', enabled: true, factor: 1, calendar_known: true,
        decision_date: '2026-09-16', execution_pending: false,
        outcome: {session: '2026-09-17', status: 'cash-limited', unrestored: {AAPL: 5}},
      }}, event_policy: {enabled: true, version: 'fomc-3-session-weakness/2', evaluation_since: '2026-06-18'},
    }),
  }))
  await page.goto('/#desk')
  const banner = page.getByRole('region', {name: 'FOMC exposure policy'})
  await expect(banner).toContainText('AAPL 5 shares unbought')
  await expect(banner).toContainText('unfilled quantities, not restored positions')
  expect(errors).toEqual({consoleErrors: [], pageErrors: []})
})

// A brand-new account has no record yet: the page must explain what it is
// and what happens next, not render a blank board.
test('an empty record becomes the getting-started guide', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      latest: null,
      summary: undefined,
      sessions: [],
    }),
  }))
  await page.goto('/#desk')

  await expect(page.getByText('No evening decision is available yet')).toBeVisible()
  await expect(page.getByText('Check after the next trading session.', { exact: false })).toBeVisible()
  await expect(page.getByText('No decision on file yet')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Displaying a hypothetical stop must never turn its breach into a sell instruction.
test('a hypothetical stop remains a reference after price crosses it', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/live`, route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({as_of: '2026-09-08T20:00:00Z', stale: true, quotes: {
      AAPL: {symbol: 'AAPL', last: 80, high: 105, low: 80, open: 102, bar: '2026-09-08T19:45:00Z'},
    }}),
  }))
  await page.goto('/#desk')
  await page.getByRole('checkbox', {name: 'show hypothetical stops'}).check()
  await expect(page.getByText('hypothetical stop breached — not an active exit rule')).toBeVisible()
  await expect(page.getByText('below the stop: sell')).toHaveCount(0)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})
