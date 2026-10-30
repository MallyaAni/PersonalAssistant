# Pre-registration: C5 sector-rotation sleeve on the honest PIT universe

Written 2026-10-29 before any run of the sleeve. This is C5 from
`top-tier-algorithms-2026-10-28.md`, the separate mandate the owner has now opted
into for research. It is **not** a change to `grade-led-leader-weight/1`: the
sleeve is a separate account, its returns are never spliced into the live book,
and nothing here touches the live rule, the board, or any prompt. The live rule
stays frozen through the 252-session review.

## Question

Does intermediate-term sector momentum, implemented as a separate sleeve on the
honest PIT universe, add a diversifying return to the live book? The sleeve is
the honest answer to "oil versus tech": rank the sectors, hold the leaders, stay
in cash when the leaders are not positive. It is not expected to beat QQQ on its
own; the test is whether the 80/20 combination improves the live book.

## Data

- PIT cache: `~/dsv41/pit2/cache.npz`, 532 tickers, 2,970 sessions
  2015-01-02..2026-10-23. `member` is the session-level membership; `sector` is
  the sector label; `adj_close` is the split-adjusted close; `benchmark` is SPY.
- Sectors: the 11 labels Energy, Materials, Industrials, Consumer Discretionary,
  Consumer Staples, Health Care, Financials, Information Technology,
  Communication Services, Utilities, Real Estate. The empty label is excluded.
- Sector baskets: at each month-end t (the last cache session of the month), the
  equal-weight of the sector's PIT members at t with a finite `adj_close` at t.
  The members are fixed for the next month; the basket's daily return is the mean
  of those members' `adj_close[s]/adj_close[s-1] - 1` over the names priced at
  both sessions; the basket index compounds them. The monthly return is the
  index's return over the next month. The prior 6-month signal is the index's
  return over the prior 126 sessions; the 12-month diagnostic is 252 sessions.
  Coverage check: every sector has at least 12 priced PIT members at every
  month-end (the minimum is Communication Services at 12; the median is 17-68
  across sectors), so the baskets are not thin.
- Live book: the current `desk.run` panel (current deploy code, `FUNDAMENTALS_CURRENT`,
  the 95 names, 2,970 sessions, truncated to 2026-10-23), the installed `Rule()`
  at 10 bp. The baseline must reproduce the recorded current-panel baseline
  (`grade_bc_policy.json`: all CAGR 33.4031%, max drawdown −28.8465%, Sharpe
  1.3252, 6,989 fills, costs 52,517.73) within 1e-6; if it does not, the live-book
  leg is invalid and the study stops before the gate.
- SPY: the cache's benchmark, the comparison index. Equal-weight sectors: the
  monthly-rebalanced equal weight of the 11 sector baskets, the sector control.
- Costs: 10 and 25 bp on the sleeve's one-way turnover. The live book keeps its
  installed 10 bp. The gate is read at 25 bp.

## Sleeve

- At each month-end t, rank the 11 sector baskets by their prior 126-session
  index return. Hold the top 2 equal-weight (50% each of the invested equity).
  If fewer than 2 sectors have a positive prior 126-session return, hold cash for
  the month (return 0, turnover to cash, cost paid).
- Volatility target: 10% annualized. The scale is `min(1, 0.10 / vol)` where
  `vol` is the annualized standard deviation (sqrt(252)) of the sleeve's unscaled
  daily returns over the prior 60 sessions; the invested fraction is the scale,
  the cash fraction is `1 - scale`, and the sector weights stay 50/50 of the
  invested part. The scale is recomputed at each month-end.
- Rebalance monthly at the month-end close; the next month's returns are the
  basket returns. The one-way turnover is `0.5 * sum(|w_new - w_old|)` across the
  sectors and cash; the cost is `turnover * cost_bps`, deducted at the rebalance.
  The sector cap is the 50% top-2 weight.
- Start offsets: the sleeve is run from each of the first 20 sessions of January
  2016, with the first rebalance at the first month-end after the start. The
  primary statistic is the mean across the 20 runs; the range is reported. This
  is the pre-registered "20 start offsets" and it is not a parameter search.
- The 12-month signal and the top-3 variant are diagnostics, not gated; they are
  reported beside the primary 6-month/top-2 sleeve.

## Comparison and live-book combination

- The sleeve, SPY and the equal-weight sectors are reported over 2016-2023
  (choosing) and 2016-2026 (reported) with CAGR, maximum drawdown, Sharpe and
  total return, at 10 and 25 bp for the sleeve.
- The live book's monthly returns come from its baseline equity curve. The
  correlation is the Pearson correlation of the sleeve's and the live book's
  monthly returns over the same window.
- The combined 80/20 is the daily-rebalanced 80% live book + 20% sleeve; its
  CAGR, drawdown and Sharpe are reported for both windows. The sleeve is never
  spliced into the live book's own return series; the combination is a portfolio
  diagnostic only.

## Gate

The sleeve passes only if all five hold:

- **G1:** the combined 80/20 Sharpe is greater than the live book's Sharpe at
  25 bp in 2016-2023 and in 2016-2026.
- **G2:** the correlation between the sleeve's and the live book's monthly
  returns is below 0.5 in both windows.
- **G3:** the sleeve's maximum drawdown is no deeper than SPY's maximum drawdown
  in both windows.
- **G4:** the real sleeve's Sharpe at 25 bp over 2016-2023 is greater than the
  95th percentile of 200 placebo sleeve Sharpes, where each placebo permutes the
  sector momentum ranks across the 11 sectors within each month (seeds from RNG
  20261029) and runs the same sleeve, costs and scale.
- **G5:** the sleeve's CAGR at 25 bp is greater than 0 in both windows.

Any failure records the result and stops the arm. The 12-month signal, the top-3
variant, the equal-weight control and the 10 bp results are reported and do not
gate. A pass buys only the owner's decision on the separate mandate, not a live
change.

## Diagnostics (reported, not gated)

- The sleeve's yearly returns, the number of cash months, the scale distribution,
  the turnover and the cost drag.
- The sector basket returns and the sector momentum ranks at each month-end.
- The 12-month signal and the top-3 variant, with the same metrics.
- The 20 start-offset range.
- The equal-weight sectors and SPY, the sector and index controls.
- The live book's baseline metrics and the combined 80/20 metrics.
- The placebo: the 200 sleeve Sharpes, their median, 95th percentile and best.

## Look-ahead controls

- The sleeve's signal at a month-end uses only the basket index through that
  session; the membership is the PIT matrix at that session; the next month's
  returns use only prices after it. The live book's replay uses the current code
  and the current panel.
- Perturbation: for 100 sampled (sector, month-end) pairs, multiply every
  `adj_close` after the signal date by a factor in [0.95, 1.05]; the sector
  momentum values and the top-2 selection at that month-end must be identical,
  while the sleeve's forward returns may change. Change one sector's momentum by
  +1 and the selection must change. Report the counts.
- The study reads no live book, no order, no position, and no prompt.

## Stop conditions

- If any sector has fewer than 5 priced PIT members in more than 20% of the
  months, stop and report before the sleeve.
- If the live-book baseline does not reproduce the recorded current-panel
  baseline within 1e-6, stop and report; the correlation and the combination
  would be invalid.
- If the gate fails, record it and stop. The arm is not retried with a different
  signal length, top-N, volatility target, sector cap, universe, rebalance
  frequency or cost without a new pre-registration saying what changed and why.
- The sleeve is a separate mandate. No result here changes the live rule.

## What passing buys

Only the owner's decision on whether to run the sector sleeve as a separate
account. A pass would make it a forward-shadow candidate, not a live change. The
live rule stays frozen through the 252-session review, and the sleeve's returns
are never spliced into the live book's record.

## Clarifications

- This is C5, the separate mandate from the program note. It is not a retry of
  C1-C4 and does not reopen timing, learned rankers or the failed overlays.
- The store has no sector-ETF bars, so the PIT sector baskets are the primary
  implementation. The ETFs would be the tradable wrapper; that fetch is a
  separate follow-up, not part of this test.
- Sector momentum has weakened since the original samples; the gate is set to
  require a combined improvement and a placebo beat, not a standalone QQQ win.
- No model call and no prompt; the sleeve is fully mechanical.
