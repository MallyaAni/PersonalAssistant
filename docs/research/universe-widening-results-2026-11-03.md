# Universe-widening study: results — 2026-11-03

Status: **canonical result** for the universe-widening study (milestone 3).
Research only: this note changes no live rule, order, grade, prompt or risk
dial, and prepares no release. The live mandate stays the AI/software book;
the `/3` forward record continues.

**Verdict: FAIL. No arm passes. The installed `/3` on the honest universe
scores 13.28% CAGR, -34.39% median drawdown, -39.42% worst drawdown and 0.816
Sharpe at 25 bp: it fails the Sharpe objective, fails CAGR against SPY, and
fails the -35% worst-offset mandate. A 50% IT sector cap is exactly inert; a
35% cap changes almost nothing (+0.052 bp/day, Newey-West t 0.84, not
significant) and still fails. A 0.20 volatility target lowers CAGR by 0.57
points, improves median drawdown by 2.69 points, but leaves the worst offset
at -39.04%, still beyond the mandate. The live book's `/3` scores 19.86% CAGR
and 0.935 Sharpe and beats SPY in all 20 offsets, but it fails the Sharpe
objective and the -35% worst-offset mandate (-37.69%); the rule also
underperforms the equal-weight live book in all 20 offsets. Widening the live
book with Utilities improves median drawdown by 4.03 points and worst
drawdown by 2.26 points, but the worst is still -35.43%, beyond the mandate,
and turnover rises from 7.62x to 10.06x. Keep `/3` live, keep the AI/software
mandate, and move to milestone 4 (code and branch hygiene).**

This is the result of
`universe-widening-preregistration-2026-11-03.md`, committed at `11d4e596`
and corrected at `d676f7a0` before the first run.

## What was run

- Store: the read-only 2026-10-30 vintage view
  `/home/animallya96/dsv41/universe/store_2026-10-30`, 2,964 sessions.
- Report: `market_universe_hindsight_research.broad_report(store)`, regraded
  with the installed analyst votes (`value` 3, `fundamental` 1, `technical` 1,
  `sentiment` 1).
- Honest membership: `~/dsv41/universe/sp500_membership_history.csv`.
- Live-book membership: `backend/market/data/membership_history.csv` (110
  intervals across 109 tickers).
- Widened membership: the book history plus the S&P 500 Utilities-sector
  members not already in the book history: 29 names in 30 intervals, 140 rows
  total.
- Costs: 10 and 25 bp; the gate is 25 bp. Offsets: 20. Seed: 20261102.
  Bootstrap: month-block, 2,000 draws, 95%. HAC: Newey-West, lag 20.
- Code revision: `d9f254a0b2f5914712123ac79dc40ffdfb244a83`.
- Payloads: `~/dsv41/universe/universe_widening_<arm>.json`; summary:
  `~/dsv41/universe/universe_widening_summary.json`.
- Script: `~/dsv41/universe/universe_widening.py`.

## Reproducibility

H0's all-window, 25 bp median CAGR is exactly the pre-registered
`0.13275424766467725`. The anchor passed; every arm is interpreted.

## The result

All sessions, 25 bp, medians across the 20 offsets:

| arm | universe | CAGR | median DD | worst DD | Sharpe | turnover | above SPY | above QQQ | above EW PIT |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| H0 | honest S&P 500 PIT | 13.28% | -34.39% | -39.42% | 0.816 | 8.44x | 4/20 | 0/20 | 20/20 |
| H50 | honest S&P 500 PIT | 13.28% | -34.39% | -39.42% | 0.816 | 8.44x | 4/20 | 0/20 | 20/20 |
| H35 | honest S&P 500 PIT | 13.23% | -34.39% | -39.42% | 0.823 | 8.43x | 5/20 | 0/20 | 20/20 |
| HR | honest S&P 500 PIT | 12.71% | -31.70% | -39.04% | 0.817 | 8.36x | 0/20 | 0/20 | 20/20 |
| L0 | live book | 19.86% | -34.18% | -37.69% | 0.935 | 7.62x | 20/20 | 19/20 | 0/20 |
| LU | live book + Utilities | 18.42% | -30.15% | -35.43% | 0.897 | 10.06x | 20/20 | 9/20 | 20/20 |
| SPY | — | 13.67% | -33.72% | -33.72% | 0.820 | — | — | — | — |
| QQQ | — | 18.48% | -35.12% | -35.12% | 0.884 | — | — | — | — |

The `above EW PIT` column is membership-specific: the equal-weight hurdle is
computed on the same membership history as the arm. L0's 0/20 means the rule
underperforms the equal-weight live book in every offset; LU's 20/20 means it
beats the equal-weight book-plus-Utilities hurdle in every offset. The two
hurdles are different books and are not comparable to each other.

At 10 bp the ordering is the same: H0 is 14.73% CAGR, -34.27% median
drawdown, -39.34% worst drawdown and 0.893 Sharpe; H35 is 14.69%, -34.27%,
-39.34% and 0.900; HR is 14.13%, -31.49%, -38.88% and 0.895; L0 is 21.05%,
-33.49%, -37.03% and 0.981; LU is 20.11%, -29.57%, -35.37% and 0.964. The
gate is 25 bp.

## The honest arms

**H0 fails the objective.** Median Sharpe 0.816 against 1.0, median CAGR
13.28% against SPY's 13.67%, and the worst offset -39.42% against the -35%
mandate. The median drawdown -34.39% is inside the research gate; the worst
offset is not. This is the installed `/3` on the honest universe, so the rule
itself is the binding failure, not the mandate.

**H50 is exactly inert.** The 50% IT cap reproduces H0's metrics to floating
point: 2016-2023 is exactly 0.0 bp/day, 2024-2026 is +0.073 bp/day, and the
all-window paired mean is +0.018 bp/day with a Newey-West t of 0.68. The
installed rule's actual IT weight never reaches 50% of the invested book on
the honest universe. This is the measured answer to the memo's open question:
the A/A+ equal-weight count (IT 31.0%) understates the rule's actual IT
weight, but the actual weight still stays below 50%.

**H35 binds only slightly.** The 35% cap is exactly inert in 2016-2023 and
binds in 2024-2026; the all-window paired mean is +0.052 bp/day, Newey-West
t 0.84, bootstrap -0.087..+0.260, not significant. It improves Sharpe from
0.816 to 0.823 and lowers CAGR from 13.28% to 13.23%; median and worst
drawdown are unchanged. It still fails the Sharpe objective, CAGR against
SPY and the worst-offset mandate. The cap is a concentration control, not a
fix for the rule's failure.

**HR costs return and does not fix the worst offset.** The 0.20 volatility
target lowers CAGR by 0.57 points, raises Sharpe by 0.001, improves median
drawdown by 2.69 points and worst drawdown by 0.38 points. The worst offset
is still -39.04%, beyond the mandate. The paired mean is -0.261 bp/day with a
Newey-West t of -2.03; the bootstrap interval -0.572..+0.041 includes zero,
so it does not meet the pre-registered significance bar, but the point
estimate is negative and the t is at the bar. The risk variant is a measured
cost, not a passing configuration.

## The live arms

**L0 is a mandate bet, not a passing rule.** The installed `/3` on the live
book scores 19.86% CAGR, 0.935 Sharpe, -34.18% median drawdown, -37.69% worst
drawdown and 7.62x turnover. It beats SPY in all 20 offsets and QQQ in 19 of
20, but it fails the Sharpe objective (0.935 < 1.0) and the -35% worst-offset
mandate (-37.69%). It also underperforms the equal-weight live book in all 20
offsets. The live book's higher CAGR is a concentrated AI/software bet, not
the rule's selection working better: the rule's leader tilt and volatility
target do worse than equal weight on the same narrow book. The live book is
the mandate, and the mandate itself does not pass the objective.

**LU improves drawdown but not enough, and costs turnover.** Widening the
live book with the 29 Utilities names lowers CAGR by 1.44 points (19.86% to
18.42%), lowers Sharpe by 0.038 (0.935 to 0.897), improves median drawdown by
4.03 points (-34.18% to -30.15%) and worst drawdown by 2.26 points (-37.69%
to -35.43%). The worst offset is still 0.43 points beyond the -35% mandate.
Turnover rises from 7.62x to 10.06x, an increase of 2.45x/year, which
violates the pre-registered turnover constraint. The paired mean against L0 is -0.777
bp/day with a Newey-West t of -0.95 and a bootstrap interval of -2.304..+0.802:
the return cost is not statistically distinguishable, but the drawdown
improvement is real and still insufficient. LU is a partial widening, not the
honest universe; it does not make the rule pass.

The prior utilities measurement in `backend/market/universe.py`'s
`book_sides` docstring (38.45% CAGR / 1.247 Sharpe / -42.05% worst drawdown
against 34.12% / 1.178 / -42.19%) is **not reproduced** on current code. The
current L0 is 19.86% / 0.935 / -37.69%, far below the prior book baseline.
The prior measurement used a different rule version, vote set, panel or cost
basis; it is prior evidence, not a like-for-like baseline. The current L0 and
LU are the canonical current-code measurements for this study. The memo's
citation of the prior measurement stands as prior evidence; it is not a
reproduction.

## Paired tests (25 bp, median offset)

| comparison | mean bp/day | Newey-West t | bootstrap 95% | PSR |
|---|---:|---:|---|---:|
| H50 minus H0 | +0.018 | 0.68 | -0.052 .. +0.108 | 0.709 |
| H35 minus H0 | +0.052 | 0.84 | -0.087 .. +0.260 | 0.677 |
| HR minus H0 | -0.261 | -2.03 | -0.572 .. +0.041 | 0.029 |
| LU minus L0 | -0.777 | -0.95 | -2.304 .. +0.802 | 0.201 |

Only HR's t reaches the |2.0| bar, and its bootstrap interval includes zero,
so none of the four paired differences is significant under the
pre-registered bar. The cap arms are small positive point estimates; the risk
variant is a negative point estimate; the utilities widening is a negative
point estimate with a wide interval.

## Decision

No honest rule arm passed the program objective, the -35% worst-offset
mandate and the turnover constraint. The verdict is **FAIL**.

- Keep `/3` live and keep the AI/software mandate.
- Do not install a sector cap, the 0.20 volatility target, or the Utilities
  widening on this evidence. The caps do not fix the rule; the risk variant
  costs return and still fails the worst offset; the utilities widening
  improves drawdown but remains beyond the mandate and raises turnover.
- The 252-session forward record under `/3` continues as the arbiter.
- Move to milestone 4: code and branch hygiene.

The study does not install anything. Any future install remains a release
ceremony under the owner's explicit authorization.

## Limitations

- GICS sector labels are current, not point-in-time, the same limitation as
  the prior sector studies.
- The live book's history is the mandate's membership, not the S&P 500 PIT
  membership. L0 and LU are mandate backtests, not honest-universe results.
- L0 is a broad-panel reproduction of the live mandate, not a rerun of the
  desk book backtest. The 27 book names outside the S&P 500 are in the broad
  panel through the overlay.
- The widening set is the current Utilities sector (29 names in 30 intervals
  not already in the book history), not the memo's nineteen regulated
  utilities. The prior measurement is prior evidence and is not reproduced.
- The sector cap scales the IT group down and leaves cash; it does not
  reallocate to other sectors. The 50% cap never binds; the 35% cap binds only
  in 2024-2026.
- The risk variant is one fixed strengthening (target 0.20), not a search. A
  failure does not prove no risk overlay can pass; it proves this one does not.
- The `above EW PIT` hurdle is membership-specific. L0's 0/20 and LU's 20/20
  are not comparable to each other or to H0's 20/20.
- The study reports performance, not a time series of portfolio sector
  weights. The cap-binding result is the evidence about the actual IT weight,
  not a direct weight measurement.
- This is a backtest on a 2026-10-30 vintage, not live evidence.

## Ledger entry

| date | question | verdict | live change | evidence |
|---|---|---|---|---|
| 2026-11-03 | Does widening the universe, an IT sector cap, or a stronger volatility target pass the objective and the -35% mandate? | **FAIL**: no arm passes; H50 inert, H35 marginal and insignificant, HR costs return and still fails the worst offset, L0 fails Sharpe and the worst offset, LU improves drawdown but remains beyond the mandate and raises turnover | none | this note |

## Change log

- **2026-11-03:** created after the run. Records the six-arm result, the
  exact H0 anchor, the paired tests, the decision and the limitations. No
  live change.
