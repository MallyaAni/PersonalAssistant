import { expect, test, type Page } from '@playwright/test'

// Deterministic browser acceptance for the trading desk page. The desk is the
// operator's own page, so the session is mocked as an operator and every desk
// endpoint is answered from fixture shapes written from the real record — the
// curve, the changes, the per-name history and the autopsy are all read-only
// views of files the nightly run wrote, so the browser never needs a runtime.

const USER = 'ani.mallya'

function observeBlockingBrowserErrors(page: Page) {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', error => pageErrors.push(error.message))
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
  await page.route(`http://localhost:8000/api/v1/market/${USER}/desk/mine*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
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
        { date: '2026-08-28', grade: 'A', votes: 3.2, stances: {}, exposure: 0.8, confidence: 0.9, forward: 0.021, forward_residual: 0.012, earnings: false },
        { date: '2026-09-08', grade: 'A', votes: 3.2, stances: {}, exposure: 0.8, confidence: 0.9, forward: null, forward_residual: null, earnings: false },
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
test('renders the desk at a glance with the track record', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await expect(page.getByRole('main').getByRole('heading', { level: 2, name: 'Desk' })).toBeVisible()

  const glance = page.getByLabel('The desk at a glance')
  await expect(glance).toBeVisible()
  await expect(glance.getByText('Practice account')).toBeVisible()
  await expect(glance.getByText('$104,200')).toBeVisible()
  // The lifetime and today moves read as percentages, not a bare dollar
  // figure: 0.042 lifetime of the starting equity, 0.003 today. Both sit in
  // one "Today" cell rather than being shown twice, once as a percent in the
  // account cell and once as dollars in their own cell.
  await expect(glance.getByText('4.2%', { exact: false })).toBeVisible()
  await expect(glance.getByText('Today', { exact: true })).toBeVisible()
  await expect(glance.getByText(/\+\$31[23]/)).toBeVisible()
  await expect(glance.getByText(/\+0\.3%/)).toBeVisible()
  await expect(glance.getByText('The rules, backtest')).toBeVisible()
  await expect(glance.getByText('not a record', { exact: false })).toBeVisible()
  await expect(glance.getByText('vs SPY', { exact: false })).toBeVisible()
  await expect(glance.getByText('6% invested')).toBeVisible()  // 6,120 of 104,200 live

  // The regime leads the board, in plain words, and says what it is doing
  // about it.
  await expect(page.getByRole('note')).toContainText('The desk is being careful right now')
  await expect(page.getByRole('note')).toContainText('fewer AI names are rising than usual')
  await expect(page.getByRole('note')).toContainText('80% of its usual book')

  // What moved since the last session, which the page used to throw away.
  await expect(page.getByText('What changed since the last session')).toBeVisible()
  await expect(page.getByText('Upgraded: NVDA B→A')).toBeVisible()
  await expect(page.getByText('Orders at the next open: add AAPL')).toBeVisible()

  // The trust anchor: the curve and its summary numbers, as an SVG the page
  // draws itself.
  const record = page.getByText('The desk’s track record')
  await expect(record).toBeVisible()
  await expect(page.getByRole('img', { name: "The desk's track record against SPY and QQQ" })).toBeVisible()
  await expect(page.getByText('CAGR')).toBeVisible()
  await expect(page.getByText('31.0%', { exact: true })).toBeVisible()

// A row reads in plain words first, and the ticker opens the drill-down.
  await expect(page.getByText('What to do at the next open')).toBeVisible()
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
  await expect(page.getByText('What to do at the next open')).toBeVisible()

  // The broker's live positions are one table on the page.
  await expect(page.getByText('Live positions')).toBeVisible()

  // Opening the details must not add a second copy of the same positions:
  // the details' "Practice account" panel keeps its summary but shows the
  // positions table only when the broker is away, because the live section
  // above already shows them.
  await page.getByRole('button', { name: 'Show the details: practice account and every grade' }).click()
  await expect(page.getByText('Every grade')).toBeVisible()
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
  await page.getByRole('button', { name: 'AAPL', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'AAPL history' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('Return while it was an A')).toBeVisible()
  await expect(dialog.getByText('Return while it was not')).toBeVisible()
  await expect(dialog.getByText('Sessions it was an A')).toBeVisible()
  await expect(dialog.getByText('41 of 60')).toBeVisible()
  await expect(dialog.getByText('Crossed the A line')).toBeVisible()
  // The desk's whole evidence, read out loud by the model.
  await expect(dialog.getByText('What the desk read')).toBeVisible()
  await expect(dialog.getByText('growing earnings with the trend intact', { exact: false })).toBeVisible()
  // The live technical read is the model's plain words over the live tape.
  await expect(dialog.getByText('resistance is a swing high above', { exact: false })).toBeVisible()
  await expect(dialog.getByText('The last 2 sessions')).toBeVisible()
  await expect(dialog.getByText('a steady AI leader')).toBeVisible()
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).not.toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A covered name that is not in the book is still graded every evening, and
// its drill-down must fetch a live technical read on demand (a fresh quote,
// not the candle's snapshot): the short/medium/long horizons render beside
// the model's prose instead of being hidden behind it.
test('drills into a covered name outside the book and sees its live horizons', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.goto('/#desk')
  await page.getByRole('button', { name: 'Show the details: practice account and every grade' }).click()
  await page.getByRole('button', { name: 'MSFT', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'MSFT history' })
  await expect(dialog).toBeVisible()
  // The evening grade chip renders even though the name is not a board row.
  await expect(dialog.getByText('expensive and the trend is quiet')).toBeVisible()
  await expect(dialog.getByText('Technical read')).toBeVisible()
  await expect(dialog.getByText('Short term · next week (daily chart)')).toBeVisible()
  await expect(dialog.getByText('Medium term · 1–3 weeks (weekly chart)')).toBeVisible()
  await expect(dialog.getByText('Long term · beyond (monthly chart)')).toBeVisible()
  await expect(dialog.getByText('resistance is a swing high above', { exact: false })).toBeVisible()
  await expect(dialog.getByText(/Where the technical analyst would rank it/)).toBeVisible()
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

  await expect(page.getByText('The desk starts tonight')).toBeVisible()
  await expect(page.getByText('Every evening', { exact: true })).toBeVisible()
  await expect(page.getByText('No decision on file yet')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})
