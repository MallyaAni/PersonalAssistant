# Stock-conditioned execution risk: measured results

Implemented and tested on research branch `codex/learned-entry-risk-20261002`.
Live policy is unchanged. The controller replaces the 1% distance trigger with
the forecast price benefit of waiting minus the funded order's waiting risk.
The shared model conditions on each stock's volatility/structure and market
context; it does not fit 94 separate models. Grading and v5 target plans stay
fixed. Plan quantities still depend on each account's carried wealth.

The fixed comparison completed once: 94 stock names, 104 monthly risk fits,
2018-02-01 through 2026-09-30, 2,177 sessions, two original waiting forecasts,
20 reset phases and three cost levels. Original controls/SPY/QQQ curves were
reused, not resimulated. All rows below are medians across the declared phases;
they are sensitivity results, not compounded independent accounts.

| Cost per side | Waiting mean | Total gain | CAGR | Drawdown loss | Wins vs matched 1% control |
|---|---|---:|---:|---:|---:|
| 0 bp | HGB | 802.26% | 29.00% | 37.23% | 12/20 |
| 0 bp | Ridge | 798.04% | 28.93% | 36.75% | 10/20 |
| 10 bp | HGB | 751.03% | 28.13% | 37.61% | 12/20 |
| 10 bp | Ridge | 745.71% | 28.04% | 37.12% | 10/20 |
| 25 bp | HGB | 679.24% | 26.83% | 38.15% | 12/20 |
| 25 bp | Ridge | 672.86% | 26.71% | 37.68% | 10/20 |

Control median gain/CAGR: 773.02%/28.51% at 0 bp,
723.38%/27.64% at 10 bp, 654.15%/26.35% at 25 bp.
At 10 bp, SPY gained 209.52%, QQQ 364.83%. Much of the book's return already
exists in the grading/selection control; it is not a gain created by this
timing model. HGB adds about 0.49 percentage point to median annual return,
with a slightly worse median drawdown. Its median **paired** total-gain
advantage is 18.85 percentage points; Ridge's is −2.80 points. Differences
between unpaired medians are a different statistic.

The already-observed Aug17–Sep30 period is a reused diagnostic, not a new
untouched holdout. At 10 bp HGB's median gain is 1.27%, its matched-control
difference −0.87 point, winning 6/20 phases. Ridge gains 1.45%, trails by
1.01 points, winning 9/20. Neither supports live replacement.

Risk calibration exposed a specific limitation. Across ordinary clocks, the
predicted waiting second moment averages 5.93e−5 versus 2.32e−5 observed.
At clock22, immediately before the closing-window deadline, it averages about
40 times the observed value. The first ordinary clock is underestimated
(ratio0.67). Negative forecasts remain explicit: 2,346 over the saved full
grid, including 2,326 in the ordinary scored stock rows; no clipping to zero.

Training includes clock24's overnight wait alongside 15-minute outcomes.
`session_time` can distinguish clocks, but there is no explicit duration
feature and tree leaves can pool late intraday observations with overnight
outcomes. This is a material calibration limitation, not label leakage or
proof that stock-conditioned volatility cannot help. The next focused
correction is [duration-matched forecasts](fifteen-minute-execution-plan-2026-10-02.md):
train both waiting means and risk only on actual 15-minute targets, preserving
the fixed settings and comparison. No threshold/window tuning from these
outcomes and no claim of exact optimal stopping.

At 10 bp, summing diagnostic HGB phase counts gives 17,419 intents: 7,511
completed, 9,274 partial and 634 unfilled. Of 16,785 fills, 4,618 are separate
closing-lifecycle fills. Ridge has 17,177 intents: 9,044 completed, 5,890
partial and 2,243 unfilled; 2,581 of 14,934 fills occur at the deadline.
These sums describe 20 separately carried accounts, not one compounded book.
Same-day sale proceeds cannot fund buys. First chosen attempts are locked
before seeing their price; missing/partial attempts are not retried later.

VERIFIED: exact implementation checkpoint
`a0622b054cbb40db77ab5fc43a16f9f6daf6177a`, native41 and source-image41 checks,
including unchanged independent9-case acceptance and real numerical fits.
Independent artifact verification checked104 monthly models/receipts and
all120 candidate/66 reused reference curves, input/source hashes, actual fit
dates and maturity, saved forecast agreement, cash/exposure, fees/turnover,
compounded metrics, rolling252 windows and intent/stock reconciliation. No
refit, resimulation or model-pickle loading. Source-reviewed target/reset
equality has no independently serialized per-intent plan trace; causal regime
and clock grouping are diagnostics, not certified adoption gates.

FAILED: evidence for robust recent-period superiority and calibrated late
intraday risk. UNVERIFIED: exact live `/6` policy reconstruction, dated
fundamentals/earnings history, future edge, broker/midpoint fills. The universe
and grades are reconstructed/current-vintage; accounting uses fractional NAV1,
next-bar-open and observed-auction proxies. Incomplete/early-close coverage,
one-step utility and absent portfolio covariance are retained limitations.
No live orders, production-data writes, dashboard or inference-service changes.

Original private artifacts on Spark:
`/home/animallya96/scratch/learned-execution-risk-results-20261002-a0622b05`.
Report SHA256 `b878bd3d7a44d071358f20ecf11e2617489f9b8cd1245e6592549ad7f409ad8e`;
risk forecasts `12f873ea3acb46d59203818e2e53506d8b050afaf7ff8bce1b645cefc8bb323b`;
independent proof `49b7fe5ddb52b28ae9e6920587bd136c70f517464726ce08e859c4b41746eac9`.
[Machine-readable summary](learned-execution-risk-results-2026-10-02.json)
contains every fixed phase's metrics, counts, benchmarks and source identities.
