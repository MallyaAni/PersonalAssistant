# Fixed retrospective price-only study — 2026-09-24

This specification is frozen before this candidate's historical outcome run.
It is a rejection/feasibility study, not permission to adopt a live policy.

Use only the existing 2026-09-23 daily bar partition and the 94 stock names
in that day's saved desk grades, plus SPY and QQQ. Keep newly listed names
unavailable until their trailing features exist; retain missing prices.
No downloads, future-period completeness screen, universe substitution or
reuse of the mixed-provider intraday cache. Record every input hash.
The cohort was selected today: survivorship and thematic-selection bias remain.

Compute price features from one snapshot: adjusted-close returns at 5/20/60/120
sessions, 20-session volatility, distance from 20/60-session means, and the
20-session adjusted high-low span. Preserve raw market-wide features instead
of cross-sectionally ranking them: SPY and QQQ momentum/volatility/trend,
current cohort breadth and QQQ trailing drawdown. Exclude fundamentals,
earnings tone, historical grades and proprietary live entry rules.
Feature availability dates in this mode are reconstruction assumptions;
the actual snapshot date is recorded separately. Retrospective forecasts are
rejected by the desk's target adapter.

Reuse the canonical fixed learner: SPY-relative next-open to t+11-open log
label, monthly HGB fits, 750 valid training sessions, strict label-end purge.
Reuse the 20-session QQQ drawdown logistic brake, 1000 training sessions,
63-session refits, and its existing 0.45/0.30 probability hysteresis and
half-exposure state. No feature, threshold, model or window search.

Final holdout: 2026-08-03 through 2026-09-23. Remove every training outcome
whose endpoint is on/after 2026-08-03 from all fits, including later monthly
refits. This freezes training data before the holdout. The dates were part
of earlier unrelated research, so this is not a pristine unseen sample.
Run it once after synthetic acceptance; do not tune to its result.

Stock policies: fixed 120-session momentum; learned ranking; each with the
learned brake; momentum with the existing QQQ trend brake. Controls: SPY,
QQQ and equal-weight available cohort. Top ten stock baskets, 10% entry cap,
composition updated every 20 sessions, zero cash yield, NAV 1, next-open fills,
10 and 25 bp one-way cost. Reuse the simulator's shared close-sized planner
and cash-funded ledger. Same-open sales cannot finance buys; one next-session
retry may deploy their proceeds. Brake state changes may adjust exposure
between composition dates; otherwise shares stay held. A missing held mark
or required execution price invalidates the path, never becomes zero return.
Buy-and-hold controls use the same initial close-sized next-open convention.

The common scoring start is the first session on/after 2016-01-04 with both
fitted models available; never count the pre-fit cash period as performance.
Report actual coverage, CAGR, negative max drawdown, annualized daily Sharpe
(zero risk-free rate), turnover, and 252-session win fractions against both
SPY and QQQ. Report the continuous account split into requested 2016–20 and
2021–26 segments and the recent holdout; do not reset accounts at boundaries.
An incomplete 2016–20 interval must state its actual first scoring date.

The full live incumbent is explicitly unavailable: its historical desk
grades, tone and entry states are not reconstructed by this experiment.
Momentum is a named price-only control, not a claimed live-strategy backtest.
No outcome can promote this study to live automatically. A weak conditional
result stops this candidate; a useful one justifies a separately declared
forward comparison or a sourced historical universe study.

## Data-failure amendment, before valid-prefix stock outcomes

The first full-window run failed all six stock paths at 2026-09-22: 52
previously observed names have no bar that day in the 2026-09-23 Yahoo
snapshot. All 96 names have bars on 2026-09-21 and 2026-09-23; older stored
2026-09-22 history proves at least ACN's bar existed then. The original
failed results remain intact; no stock-strategy metrics were emitted.

Report the mechanically complete prefix: stop immediately before the first
missing OHLC field after a symbol's first observed bar, on the common scoring
calendar. This rule selects 2026-09-21 without inspecting stock returns.
Use saved inputs and forecasts unchanged; no refit, new data, dropped name
or changed parameter. Apply the same cutoff to both benchmarks. Label the
full requested interval FAILED and the shorter holdout partial. Keep the
original fit/inputs hashes and the standalone evaluation script with results.
