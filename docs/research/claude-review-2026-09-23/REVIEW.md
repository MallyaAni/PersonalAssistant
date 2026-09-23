# Trading desk review — 2026-09-23 (Claude)

Scope: GPT's commits `535bda22..30afe7db` (funded `vol`/`vol_trend` allocation,
funded execution, paper allocation, 15-minute intraday entry research, personal
board), plus the live incumbent `cash-bounded-breakout-rotation/2` it would replace.
No repo files were modified.

## Verdict

- **Look-ahead: clean.** Decisions use close t, fills at the t+1 open, and every window is sliced at t. The intraday replay drops unfinished bars and respects publication times.
- **The new `vol` / `vol_trend` policies should not be adopted.**
  - They scale the book down to min(SPY, QQQ) volatility, which is effectively SPY's, so average equity exposure falls to about 40–55%.
  - That roughly halves CAGR and falls short of QQQ's return in the objective the system itself set.
  - GPT's own evaluation: incumbent 43.6% / 34.2% max drawdown → `vol` 22.0% / 24.6%, with the margin over QQQ at 25bp costs only about 0.08 pt/yr.
- **None of the new code is live.** `market_daily.py` calls `paper.plan` without `allocation_context`, and the intraday modules are imported only by tests. The dashboard's `portfolio_allocation` field always reads "unavailable".
- **The biggest caveat is the universe itself.** The 94 names are today's winners, hand-picked with hindsight (CRWV, IREN, NBIS, OKLO, VST, …).
  - Simply equal-weighting the whole book returns 38% CAGR since 2016 (this repo's own notes: 40.9%).
  - That beats every selection and sizing rule tested. "Beats QQQ on this universe" is not evidence of edge.

## Independent backtest (price-only proxy of selection; allocation code is GPT's own `allocation.decide`)

Next-open fills, 10bp per side, T-bill yield on cash. Data: Yahoo adjusted daily
prices through 2026-09-21. Selection is a price-only momentum/range proxy of the
technical analyst, because fundamentals and tone are not available offline. Absolute
levels therefore differ from the desk's; the *relative* effects are what matter.

| Strategy | CAGR 2016–26 | Max drawdown | Sharpe | Avg exposure | CAGR 2016–20 | CAGR 2021–26 |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 15.3% | 33.7% | 0.89 | 100% | 15.4% | 15.5% |
| QQQ | 20.4% | 35.1% | 0.95 | 100% | 24.4% | 17.4% |
| A: live-like (hold 20, sells at close, no recycling) | 26.3% | 33.7% | 1.20 | 62% | 21.2% | 32.1% |
| A1: A + next-day buy of idle cash | 31.6% | 42.6% | 1.15 | 82% | 25.2% | 32.9% |
| A3: A1 + QQQ 200-day trend overlay with hysteresis (0.97 / 1.02, half exposure) | 29.9% | 31.6% | 1.18 | 75% | 22.0% | 32.5% |
| GPT `vol` (as built) | 17.2% | 33.6% | 1.03 | 51% | 15.5% | 18.0% |
| GPT `vol_trend` (as built) | 14.8% | 23.5% | 1.14 | 40% | 12.2% | 16.9% |

Survivor-biased and in-sample; this is one 10-year path. A3's bands were chosen, not
fitted, but it should still run as a shadow before any adoption.

## Findings, by severity

1. **High: the volatility budget caps returns.** It is set by SPY-level volatility (`allocation.py`, around lines 369–404). This is the main reason `vol` and `vol_trend` lose to QQQ on return.
2. **High (live today): the personal board repeats "Buy" on every refresh.**
   - `decision_view._personal_midcycle_orders` has no same-day memory, no cooldown and no pending-order check.
   - A breakout name can show a new 1.8–7% buy every 15 minutes until it hits the 15% cap.
3. **High (latent): the whole-share funded path churns.**
   - Whenever any constraint binds, `risk_cut=True` rounds sells up. The volatility budget binds almost every day, so it sells a share today and buys it back tomorrow.
   - A reproduction showed 608 reversals in 250 sessions (`funded_execution.py:470`, around line 642).
4. **Medium: idle cash in the live incumbent.**
   - Rebalance buys are bounded by the cash already on hand, because sells fill at the close (`paper.bound_orders`).
   - The proceeds then sit idle until an entry or the next rebalance, which costs about 5 CAGR points in the proxy.
   - It also holds drawdown at SPY's level. Decide which you want deliberately; A3 keeps the return and the drawdown control.
5. **Medium: sell and buy thresholds are lopsided.**
   - Buys need a 0.5% minimum trade; sells have none (`funded_execution.py:383`).
   - Result: 0.886 average exposure against a 0.90 target, and about 45% more turnover.
6. **Medium: GPT's comparison isn't like for like.**
   - The incumbent comes from a precomputed reference file, not the same ledger.
   - The recorded runs made SPY eligible as a residual, while the paper default does not.
   - Cash earns zero.
   - Stock volatility is targeted twice: the 30% book target, then the SPY/QQQ budget.
7. **Medium: live quotes can lag a full bar.** A fetch before the provider publishes the bar is cached for 15 minutes (`live_quotes.py:118`).
8. **Medium (latent): early closes are hard-coded to 16:00** in `intraday_entry.py`.
9. **Low: the `vol_trend` 200-day ceiling has no hysteresis**, so it whipsaws between 1, 0.5 and 0.
10. **Low: B-graded names take top-decile slots and then get zero weight** (`risk.py:158`), which silently lowers gross exposure.
11. **Low: the intraday research doesn't answer its question.**
    - There's no next-open baseline, only 6 names, and 5 plus 1 entries.
    - An earlier study found the open as good as any first-hour print.
    - Don't build intraday timing into the account.
12. **Redundancy (vibe-coded):**
    - About 22k new lines (about half tests) for code that is not wired in.
    - `apply_account_plan` is used only by tests.
    - Several docstrings contradict the code (grade weights, "no mid-cycle trades", entry size at the trigger).
    - `simulate.run` defaults (`use_exits=True`, no `LIVE_POLICY`) differ from live.

## Recommended order

1. Fix the personal board's repeated Buy: record today's entries per name and skip names with a pending order.
2. Keep the incumbent live. Shelve `vol` and `vol_trend`, or re-register them with a QQQ-relative budget and hysteresis.
3. Run two shadows beside the incumbent:
   - deploying idle cash the next session;
   - a QQQ 200-day overlay with hysteresis.
4. Start logging point-in-time membership and add names by rule, not hindsight. Until then, measure every result against the equal-weighted book, not only SPY and QQQ.
5. Delete or archive the unwired research modules, and fix the docstrings that contradict the code.

Files: `engine.py` (backtester), `run3.py` (the experiments), `run3.csv` (results).
