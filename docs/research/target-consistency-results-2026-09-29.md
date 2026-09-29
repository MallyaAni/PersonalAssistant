# Target-consistent breakout entries: do not promote

The registered comparison completed all 200 stock-account simulations and
80 matching SPY/QQQ accounts at code `b8b54df`. Requiring new breakout buys
to have a positive allocator target does **not** rescue the existing M3
selection overlay. Keep the live strategy unchanged; stop this candidate.

Protocol: [target-consistency-2026-09-29.md](target-consistency-2026-09-29.md).
Twenty reset offsets, 10 and 25 bp one-way costs, existing `/4` execution,
fixed M3 forecasts, no new selection-model fitting. These dates and the
laggard idea had already been examined; this is not independent validation.

## Primary result

M3 with the entry gate minus `/4` with the same gate, at offset 10:

| Window | Cost | Net bp/session | Newey–West t (lag 20) |
| --- | ---: | ---: | ---: |
| 2017-12-27 through 2023 | 10 bp | +0.381 | 0.827 |
| 2017-12-27 through 2023 | 25 bp | +0.379 | 0.817 |
| 2024 through 2026-09-28 | 25 bp | −0.006 | −0.010 |

The required +2 bp/session and t ≥ 2 both fail. The later window also
fails the nonnegative floor, albeit by an economically tiny amount.
Model-window compounded wealth wins on 20/20 offsets and median drawdown
improves by 2.23 percentage points, but those do not override the failures.

The gate alone changes nothing in the baseline `/4` accounts. Adding it to
the ML overlay adds only +0.044 bp/session (t 1.068) through 2023 and
+0.017 bp/session (t 0.402) in 2024–2026, at 25 bp and offset 10. Most of
the overlay's already-small effect is not caused by this entry restriction.
Excluded names remain held on 51.91% of observed post-reset sessions versus
53.16% without the gate; mean residual weight stays about 7.35%. This gate
only prevents new ineligible breakouts, not every route to retained exposure.

## Benchmark scorecard

Medians across 20 offsets at 25 bp, 2017-12-27 through 2026-09-28.
Each statistic is independently medianed; median wealth does not necessarily
equal the product of separately medianed subwindows. Cash earns zero.

| Account | Ending wealth per $1 | CAGR | Maximum drawdown | Mean cash share |
| --- | ---: | ---: | ---: | ---: |
| Current `/4` | 9.779 | 29.86% | −45.52% | 12.56% |
| `/4` + entry gate | 9.779 | 29.86% | −45.52% | 12.56% |
| Existing M3 overlay | 10.624 | 31.10% | −43.41% | 12.66% |
| M3 + entry gate | 10.624 | 31.10% | −43.29% | 12.70% |
| Membership equal-weight targets, same executor | 4.567 | 19.01% | −33.94% | 37.11% |
| SPY buy and hold | 3.272 | 14.55% | −33.72% | — |
| QQQ buy and hold | 4.975 | 20.19% | −35.12% | — |

Historical outperformance is not a promise of future gains. Missing exited
names, retrospective sector/grade inputs, adjusted prices and prior model
selection remain material limitations. The equity control is not passive
equal weight: the existing execution rules also govern its funding/trades.

## Regimes

Descriptive conditional daily means at 25 bp, offset 10. The regime uses
only the prior SPY close versus its preceding 200-session average. A down
*trend* is not a red-day forecast, and positive means here include rebounds.
Accounts stay continuous; these are not CAGRs over disconnected days.

| Prior SPY trend | Sessions | `/4` | M3 + gate | SPY | QQQ |
| --- | ---: | ---: | ---: | ---: | ---: |
| Up | 1,798 | 11.44 bp | 11.33 bp | 5.33 bp | 7.55 bp |
| Down | 401 | 19.24 bp | 21.13 bp | 9.59 bp | 12.35 bp |

## Evidence and next step

Raw result on Spark:
`/home/animallya96/scratch/target-consistency-b8b54df.json`.
SHA-256: `9f70165daea2e0113bdd03836fd5047931c47d5b11563c5744a6006c90127684`.
It records code, protocol, forecast, membership and report-array identities,
all offsets/windows/pairs and offset-10 daily returns.

Independent recomputation from the daily arrays checked 1,118 wealth,
CAGR, initial-capital drawdown, paired-mean and HAC-t values (all passed).
The implementation checkpoint passed 225 focused tests locally and the
14 new tests in Spark's research environment. No live strategy, order,
schedule or dashboard behavior changed for this experiment.

Do not merge an unused strategy option into production based on this result.
The immediate useful work is the requested dashboard/account reconciliation:
show actual paper history separately from simulations and distinguish the
manual board's intraday timing from the paper executor's next-open fills.
Do not launch another tuned variant of this failed experiment.

Diagram impact: NONE — a completed comparison of existing execution paths.
