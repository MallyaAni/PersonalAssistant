# Sector flow and the QQQ brake: results — 2026-11-02

**Verdict: all four arms FAIL the pre-registered gate. The flow gate, the QQQ
brake and the joint reduce CAGR. The flow tilt is the only arm that adds CAGR
(+0.392 points all-window, +2.143 in 2024-2026), but its paired mean against
the base is negative at the median offset, its gain is concentrated in the
recent window, and its Sharpe is 0.844, still below the 1.0 gate. The
predeclared signals would not have avoided the recent drawdown: Information
Technology was the leading sector by trailing return on both decision dates,
and the QQQ brake was off throughout the window. The live book's concentration
is a universe/mandate issue, not an overlay issue. No live change; the
252-session forward record remains the arbiter.**

This is the result of `sector-flow-overlay-preregistration-2026-11-02.md`,
run after the note was committed. Research only: no live rule, order, grade,
prompt or risk dial changed, and no live file was written.

## The result

All sessions, 25 bp, medians across the 20 offsets. The paired columns are
arm minus base at the median offset (offset 10), Newey-West t at lag 20 and
the 95% month-block bootstrap (2,000 draws, seed 20261102).

| arm | CAGR | median DD | worst DD | Sharpe | paired bp/day | HAC t | boot 95% | offsets above base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| base (installed joint) | 13.650% | -34.560% | -39.237% | 0.837 | — | — | — | — |
| flow gate | 13.260% | -34.433% | -39.869% | 0.808 | -0.377 | -1.86 | -0.775 .. +0.008 | 2 / 20 |
| flow tilt | **14.042%** | **-33.892%** | **-38.495%** | **0.844** | -0.096 | -0.47 | -0.493 .. +0.310 | **16 / 20** |
| QQQ brake | 12.206% | -34.010% | -39.216% | 0.825 | -0.742 | -1.49 | -1.704 .. +0.279 | 0 / 20 |
| gate + brake (descriptive) | 11.776% | -34.201% | -39.532% | 0.790 | -1.072 | -2.01 | -2.060 .. +0.014 | 0 / 20 |
| SPY | 13.669% | -33.717% | -33.717% | 0.820 | | | | |
| QQQ | 18.476% | -35.119% | -35.119% | 0.884 | | | | |

The tilt's headline is real but does not survive the pre-registered test. It
has the highest CAGR of any arm, the shallowest median and worst drawdowns,
and it is above the base in 16 of 20 offsets (median difference +0.340 CAGR
points). But at the median offset its paired mean is -0.096 bp/day, the HAC t
is -0.47, and the bootstrap crosses zero. The 2016-2023 paired mean is -0.263
bp/day (t -1.15); the 2024-2026 mean is +0.624 bp/day (t 1.22). The gain is a
recent-window, sector-concentration effect, not a robust improvement.

## The gate

| arm | Sharpe >= 1.0 | median DD >= -35% | CAGR > SPY | primary | secondary | turnover | status |
|---|---|---|---|---|---|---|---|
| flow gate | 0.808 — no | -34.433% — yes | 13.260% < 13.669% — no | fail | fail | 8.77 — pass | **FAIL** |
| flow tilt | 0.844 — no | -33.892% — yes | 14.042% > 13.669% — yes | fail (Sharpe) | fail | 8.83 — pass | **FAIL** |
| QQQ brake | 0.825 — no | -34.010% — yes | 12.206% < 13.669% — no | fail | fail | 8.07 — pass | **FAIL** |
| gate + brake | 0.790 — no | -34.201% — yes | 11.776% < 13.669% — no | fail | fail | 8.24 — pass | **FAIL** |

Every arm fails the primary gate on Sharpe, which is below 1.0 in all four
cases. The gate and brake also fail the CAGR condition. The tilt passes the
drawdown and CAGR conditions and fails only Sharpe; it is not a PARTIAL
because the pre-registered rule calls a primary failure FAIL, not PARTIAL.
No arm passes the secondary test: no arm has a positive all-window paired
mean, none reaches a HAC t of 2.0, and none has a positive bootstrap lower
bound. The tilt is the only arm above the base in at least 15 of 20 offsets
(16); the tilt and the gate are positive in 2024-2026, but both are negative
in 2016-2023, so the two-window condition fails for every arm.

Note on the summary's verdict field: `verdict_for` checked `worst_drawdown`
(the worst across offsets) for the drawdown condition, while the
pre-registration specifies the **median** worst drawdown across offsets
(`median_drawdown`, the column the render prints as maxDD). Under the stricter
worst-across-offsets reading every arm fails drawdown as well (-38.495% to
-39.869%). No status changes, because every arm fails Sharpe in both readings;
the table above uses the pre-registered median reading.

## The windows

25 bp, medians across offsets:

| arm | 2016-2023 CAGR / Sharpe / median DD | 2024-2026 CAGR / Sharpe / median DD |
|---|---:|---:|
| base | 11.730% / 0.721 / -34.560% | 23.220% / 1.391 / -20.755% |
| flow gate | 11.019% / 0.678 / -34.433% | 23.342% / 1.330 / -21.897% |
| flow tilt | 11.707% / 0.715 / -33.892% | **25.363% / 1.390 / -21.362%** |
| QQQ brake | 9.813% / 0.677 / -34.010% | 22.498% / **1.451** / **-15.981%** |
| gate + brake | 9.187% / 0.630 / -34.201% | 22.637% / 1.391 / -16.818% |

Paired arm minus base, bp/day and HAC t:

| arm | 2016-2023 | 2024-2026 | all |
|---|---:|---:|---:|
| flow gate | -0.598 / -2.54 | +0.411 / 0.87 | -0.377 / -1.86 |
| flow tilt | -0.263 / -1.15 | +0.624 / 1.22 | -0.096 / -0.47 |
| QQQ brake | -0.961 / -1.40 | -0.374 / -0.51 | -0.742 / -1.49 |
| gate + brake | -1.467 / -2.01 | -0.026 / -0.03 | -1.072 / -2.01 |

The gate is significantly worse than the base in 2016-2023 (t -2.54) and
slightly better in 2024-2026 (not significant). The tilt is negative in
2016-2023 and positive in 2024-2026, neither significantly. The brake is
negative in both windows. The joint is negative in both.

The arms' recent-window records against QQQ are not representative of the
full sample. The tilt beats QQQ in 20 of 20 offsets in 2024-2026 (25.363% vs
21.0%), but in 0 of 20 over all sessions (14.042% vs 18.476%). The base beats
QQQ in 18 of 20 offsets in 2024-2026 and 0 of 20 over all sessions. No arm
closes the full-sample gap to QQQ.

## Turnover

Executed turnover at the median offset, 25 bp, from the simulator's own
`turnover` metric (notional traded per year over the average account):

| arm | turnover / year | vs base | candidacy limit |
|---|---:|---:|---|
| base | 8.61 | — | — |
| flow gate | 8.77 | +0.16 | pass |
| flow tilt | 8.83 | +0.22 | pass |
| QQQ brake | 8.07 | -0.54 | pass |
| gate + brake | 8.24 | -0.37 | pass |

All arms pass the pre-registered candidacy limit (base + 1.0x/year). The
brake lowers turnover because halving exposure halves the notional traded;
the gate and tilt raise it slightly through redistribution.

The base's own turnover is **8.61x/year, 4.3 times the program's about-2x/year
target**. That is a property of the scorecard simulation, not of the overlays.
The live paper account's first 37 sessions show 430,776.63 of filled notional
over an average equity of 97,239.94 in 0.1468 years, or about 30.2x/year
gross (15.1x one-way) annualized — with the caveats that the window is short,
it includes the initial build from cash and the crash rebalancing, and
annualizing 37 sessions is noisy. Neither measurement meets the about-2x/year
target. The turnover gap is a separate concern and deserves its own
pre-registered study; it is not caused by, and is not fixed by, these overlays.

## Why the flow arms did not help

The predeclared flow signals followed the money into the sector that crashed.

- On 2026-09-04, Information Technology had the highest trailing
  126-session mean return of the 11 GICS sectors, +40.66%. On 2026-09-30 it
  was still the top sector, +47.04%. A flow tilt would have added IT, not
  reduced it; a flow gate would only have refused new money to the bottom
  three sectors, which were not where the losses were.
- The gate's long-window cost is significant: -0.598 bp/day in 2016-2023,
  HAC t -2.54, and only 2 of 20 offsets above the base over all sessions.
  That is consistent with refusing new entries in lagging sectors that later
  rebounded.
- The tilt's gain is concentrated in 2024-2026, when IT was the leading
  sector. It is the opposite of diversification: it sends more money to the
  leading sector, which in this sample was the sector the live book is
  already concentrated in.
- The honest universe is already diversified: IT plus Communication Services
  average 16.48% of the point-in-time book, maximum 39.67% (the prior static
  sector-cap study). The overlays failed on signal value, not on a lack of
  sectors to allocate to.

## Why the QQQ brake did not help

The predeclared brake is a 200-session QQQ trend state machine: risk-off when
QQQ closes below 0.97 of its trailing mean, risk-on above 1.02, hysteresis in
between, first 200 sessions risk-on.

- In 2026 the brake was risk-off for 9 sessions only, 2026-03-26 through
  2026-04-08. It was risk-off for **none** of the 2026-09-04..2026-10-30
  window. QQQ fell 3.86% over that window while the live paper account fell
  15.83%. The brake would not have known.
- On 2026-10-30 QQQ closed at 1.0179 times its 200-session mean, between the
  0.97 entry and 1.02 exit thresholds, so the state machine held its previous
  risk-on state. The recent drawdown was sector-specific, not a QQQ trend
  break.
- Historically the brake halves exposure during risk-off episodes. It avoids
  some drawdown but misses rebounds: 2016-2023 CAGR 9.813% vs the base's
  11.730%, and 0 of 20 offsets above the base. The 2024-2026 window is the
  exception — 22.498% CAGR but a higher Sharpe of 1.451 and a much shallower
  median drawdown of -15.981% — but the full-sample cost dominates and the
  paired mean is negative in both sub-periods.

## The live book is the constraint

- The live universe is 94 names: 80 Information Technology, 9 Industrials,
  2 Utilities, 2 Communication Services, 1 Consumer Discretionary. **All 8
  A/A+ names are IT.** The latest desk target is 46.75% IT and 3.25%
  Industrials at 50% gross. There are no Financials, Health Care, Energy,
  Materials, Real Estate or Consumer Staples names.
- A sector overlay on this book cannot diversify it. The flow tilt would add
  IT when IT leads; the flow gate would either do nothing (no lagging-sector
  names to block) or block IT if IT were lagging. Neither creates exposure to
  the missing sectors.
- The recent paper account is the concentration, not the regime: 11
  concentrated AI-hardware positions, -15.83% over 37 sessions against QQQ's
  -3.86%, with a -21.36% maximum drawdown. The policy is /1; the /2 forward
  record has zero completed sessions.
- The prior widening measurement is the evidence to weigh: restoring all
  nineteen regulated utilities measured 38.45% CAGR, 1.247 Sharpe and -42.05%
  worst drawdown against 34.12%, 1.178 and -42.19% over twenty start phases.
  That measurement's -42% drawdown is deeper than the program's -35% limit,
  so it is evidence about return and Sharpe, not a passing configuration. The
  book was deliberately kept AI/software; widening it is an owner decision,
  not a research overlay.

## What this means

- **No live change.** No arm passed; there is no forward shadow and no
  candidate for the next release. The installed rule and the /2 forward record
  continue unchanged.
- The installed joint rule's honest-universe scorecard remains 13.650% CAGR,
  0.837 Sharpe, -34.560% median drawdown and -39.237% worst drawdown. It
  fails the program objective on Sharpe and, by 0.018 points, on CAGR against
  SPY; the median drawdown passes -35% under the pre-registered reading, but
  the worst drawdown is -39.24%.
- The owner's hypothesis — that the system should have known from QQQ or from
  sector flow — is **not supported by the predeclared signals**. The crash
  was in the leading sector, so a flow-following rule would have stayed in
  it; the predeclared QQQ brake was off. The live book's concentration is a
  universe/mandate issue.
- The failure is recorded. Do not retry it with a different window, strength,
  sector count or brake threshold without a new pre-registration saying what
  changed and why.
- The next question is the universe/mandate, not another overlay. The prior
  utilities measurement is the evidence to weigh. The 252-session forward
  record remains the out-of-sample arbiter, and the B hold remains the
  fallback at that review.
- Turnover is a separate concern: the base's scorecard turnover is 8.61x/year
  and the live paper's first 37 sessions annualize to about 30.2x/year gross
  (15.1x one-way), both far above the about-2x/year target. The overlays do
  not fix it. It needs its own pre-registration.
- Positive-shock drift remains owner-blocked.

## Look-ahead and multiplicity

- The sector mean reads only trailing 126 closes through t; the gate's "new
  entry" reads the previous session's actual book target, not future prices;
  the tilt reads only trailing closes; the brake reads only QQQ closes through
  t. All causal by construction.
- Three primary arms plus one descriptive joint, parameters fixed before the
  run. No search over window, strength, bottom count, sector set or brake
  threshold. The 126-session window and 0.5 strength are the prior sector
  study's registered variants; the brake thresholds are predeclared in
  `trend_brake.py`.
- Current GICS labels are not point-in-time; a name's sector could have
  changed historically. The prior sector studies share this limitation; the
  study does not claim historical sector membership.
- The deflated-Sharpe hurdle is descriptive, with the trial count from the
  program of record, not used to rescue a failed gate.

## Data and reproducibility

- The base is re-scored in the same process as the overlays. Its all-window
  25 bp median CAGR is 0.13650402269141293, identical to the installed-joint
  payload's value; the reproducibility check passed.
- 2,964 sessions in the all window, 2,012 in 2016-2023, 711 in 2024-2026; 20
  offsets; costs 10 and 25 bp; the gate is read at 25 bp.
- Report: `market_universe_hindsight_research.broad_report(store)` over
  `/home/animallya96/deploy/anios/data/market`, regraded with the installed
  analyst votes (`value` 3, `fundamental` 1, `technical` 1, `sentiment` 1),
  restricted to the dated S&P 500 membership
  `~/dsv41/universe/sp500_membership_history.csv`.
- Script: `~/dsv41/universe/sector_flow.py`. Payloads:
  `sector_flow_leader_ewma_minA_floor50_pe.json`, `sector_flow_gate.json`,
  `sector_flow_tilt.json`, `sector_flow_brake.json`, `sector_flow_joint.json`
  and summary `sector_flow_summary.json`, all under `~/dsv41/universe/`.
- Run as of 2026-10-30, the store's last complete session. The sector
  momentum diagnostics read the cache through 2026-10-23; the dates cited
  (2026-09-04 and 2026-09-30) are inside that coverage.
- Limitation: the equal-weight lines in these payloads render 0.0% CAGR and
  NaN Sharpe, a pre-existing scorecard artifact; the study's comparisons are
  arm versus base, SPY and QQQ, not versus equal weight.
- Limitation: the summary's `verdict_for` used the worst-across-offsets
  drawdown for the drawdown condition; the pre-registration specifies the
  median across offsets. No verdict status changes, because every arm fails
  Sharpe in both readings. See the gate section.
