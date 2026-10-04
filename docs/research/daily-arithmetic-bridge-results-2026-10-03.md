# Daily arithmetic decisions: fixed funded comparison

The implemented candidate uses calibrated arithmetic forecasts, per-stock risk,
covered holdings and available cash for daily buy, hold, trim and exit decisions.
It does not use a distance-from-open entry or a percentage-profit exit trigger.
It retains grade eligibility and operator exposure limits. This implementation
does not establish a better live strategy: it loses total net gain to the matched
daily grade-equal rule at every declared cost, including zero.

At 10bp the candidate gains 186.42%, versus 447.18% for the grade-equal rule,
253.97% for QQQ and 170.73% for SPY. Its full-period drawdown is lower than the
rule's, but maximizing compounded gain was the primary objective. The zero-cost
candidate gains 537.66%, versus 547.68% for the rule. No cost assumption is needed
to establish that the candidate failed this total-gain comparison.

Protocol d7e6d016 was frozen before new fits and outcomes. Evaluated source is
d339aebea05d28a034ff89a78c36791ecf400fef. The only new fits are monthly affine
calibration of already saved OOS forecasts; no original model or study was rerun.
All 94 stocks plus SPY and QQQ are retained. This deliberately retargets a
ten-session log forecast to one-session arithmetic returns; it is not a directly
trained daily model.

The common completed-close anchor is 2020-03-02; the first official-open proxy
fill is 2020-03-03. The final valuation is 2026-09-30. There are 1,654 measured
return sessions. The warmup excludes 522 original forecast decision sessions,
or 1,298 sessions of the full input panel. Earlier requested dates are unavailable,
not discarded poor returns. Each book starts NAV1, carries cash and shares,
earns zero cash yield and uses adjusted synthetic fractional units. Purchases
cannot use proceeds from the same plan's sales.

| Cost per side | Book | Net gain | CAGR | Drawdown loss | Sharpe | Gross trading / year |
|---|---|---:|---:|---:|---:|---:|
| 0bp | Calibrated | 537.66% | 32.61% | 41.17% | 1.01 | 34.04 |
| 0bp | Past mean | 625.74% | 35.25% | 47.68% | 1.06 | 16.53 |
| 0bp | Grade equal | 547.68% | 32.93% | 47.50% | 1.01 | 25.75 |
| 0bp | SPY | 171.00% | 16.40% | 28.32% | 0.86 | 0.15 |
| 0bp | QQQ | 254.32% | 21.26% | 35.12% | 0.90 | 0.15 |
| 10bp | Calibrated | 186.42% | 17.39% | 36.70% | 0.68 | 13.81 |
| 10bp | Past mean | 134.51% | 13.87% | 30.76% | 0.71 | 8.55 |
| 10bp | Grade equal | 447.18% | 29.56% | 48.68% | 0.94 | 25.74 |
| 10bp | SPY | 170.73% | 16.39% | 28.32% | 0.86 | 0.15 |
| 10bp | QQQ | 253.97% | 21.24% | 35.12% | 0.90 | 0.15 |
| 25bp | Calibrated | 91.75% | 10.43% | 39.45% | 0.58 | 4.81 |
| 25bp | Past mean | 0.00% | 0.00% | 0.00% | Unavailable | 0.00 |
| 25bp | Grade equal | 325.00% | 24.66% | 50.41% | 0.82 | 25.72 |
| 25bp | SPY | 170.32% | 16.36% | 28.32% | 0.86 | 0.15 |
| 25bp | QQQ | 253.44% | 21.21% | 35.12% | 0.90 | 0.15 |

Costs change the optimized targets as well as deducted fees. Differences between
zero-cost and positive-cost books are not an isolated fee-drag estimate. At 25bp
the past-mean arm stays in cash: zero orders, zero exposure, zero gain and an
unavailable Sharpe because returns have no variance. No return was imputed.

All fixed candidate windows are shown below. Differences are percentage points
of cumulative gain on matched dates and carried starting wealth. The nominal
2018–20 window has support only from March 2020. The recent window was reused;
its annualized metrics do not establish persistent performance.

| Cost | Candidate window | Net gain | vs grade equal | vs past mean | vs SPY | vs QQQ |
|---|---|---:|---:|---:|---:|---:|
| 0bp | all | 537.66% | -10.01pp | -88.08pp | 366.67pp | 283.34pp |
| 0bp | 2018_2020 | 35.05% | -13.31pp | -2.92pp | 11.99pp | -10.28pp |
| 0bp | 2021_2026 | 372.17% | 35.61pp | -53.83pp | 251.95pp | 228.37pp |
| 0bp | reused_2026_08_17_09_30 | 9.57% | 2.53pp | -0.10pp | 11.10pp | 8.28pp |
| 10bp | all | 186.42% | -260.76pp | 51.91pp | 15.70pp | -67.54pp |
| 10bp | 2018_2020 | 8.68% | -36.04pp | 7.39pp | -14.25pp | -36.50pp |
| 10bp | 2021_2026 | 163.54% | -114.55pp | 32.03pp | 43.32pp | 19.74pp |
| 10bp | reused_2026_08_17_09_30 | 9.41% | 2.90pp | 1.64pp | 10.94pp | 8.12pp |
| 25bp | all | 91.75% | -233.26pp | 91.75pp | -78.58pp | -161.69pp |
| 25bp | 2018_2020 | 7.55% | -31.88pp | 7.55pp | -15.20pp | -37.42pp |
| 25bp | 2021_2026 | 78.28% | -126.52pp | 78.28pp | -41.94pp | -65.52pp |
| 25bp | reused_2026_08_17_09_30 | 8.52% | 2.80pp | 8.52pp | 10.04pp | 7.22pp |

| Cost | Candidate rolling 252-session wins vs rule | vs SPY | vs QQQ | Windows |
|---|---:|---:|---:|---:|
| 0bp | 46.90% | 67.50% | 63.93% | 1403 |
| 10bp | 29.44% | 37.56% | 44.12% | 1403 |
| 25bp | 32.43% | 20.46% | 29.08% | 1403 |

The adjacent JSON preserves every fixed book/window, fees, exposure, intent
counts, all 94 stock profit contributions and independent proof. No stock,
regime, cost or window was selected to promote the candidate. Rolling windows
overlap and are not independent trials.

VERIFIED: 100 native and 100 pinned-image implementation checks, 28 native and
28 pinned-image verifier checks, no skips, and twelve exact historical default
target/receipt comparisons. The actual saved-only verifier independently checked
141 monthly receipts, nine stock books, six ETF books and all fifteen score sets.
All books contain 14,901 plans and 54,037 intents: 33,908 fully filled,
20,129 cash-limited, zero missing-open intents; 27 plans have an explicit allocator
unavailable state. Cash-limited includes partially filled and unfunded requests.
The proof checks cash, covered shares, basis, realized/unrealized profit,
prior-close quantities, fees, eligibility, risk moments and global convex
certificates. It performs no model fitting or strategy/account replay.
It authenticates recorded targets, not the optimizer's unsaved iteration path.

FAILED: adoption evidence for this calibrated daily candidate against the rule's
total net gain. UNVERIFIED: exact full live-policy improvement or broker fills.
The comparator is the grade-equal target rule at a daily cadence, not the full
live rotation/FOMC/intraday policy. Historical grades and universe are
current-vintage reconstruction; the recent data was already used. Daily opens
are fill proxies. One-session log covariance is a declared approximation to
arithmetic conditional risk. These component results cannot authorize promotion.
Production policy, UI, data and model services remain unchanged.

The next controlled correction is to train the same fixed boosting family
directly on the one-session arithmetic target using the original thirteen daily
features. Keep identical training support, score masks, clocks, account start
and controls; do not search families, thresholds or favorable subsets. Freeze
that protocol before fitting. This candidate's calibrated compression of a
ten-session output does not test that direct learner.

Report SHA256: `1e3dc8fc1e74049e7945f198d0b18ab5fcffebed3f6a077c1b85fa42fe15f9df`.
Independent proof SHA256: `cf4132bd2e51c3a6420eac17dd121ce6fb09637bc79d2cac899a5f2373d502c2`.
Source manifest SHA256: `efdca8d6e9219cd1558290f883d9bbe08a4acf0603b721e617e39ac0a2a5bdc2`.
Verifier SHA256: `1c9610a170a4534fe114ed1509ed2f2ffb8336d224e7a20ac4656312eb976276`.
Published JSON SHA256: `5f30b8492f9536473f5a7fd98dd13d9f843cb0c3e2cb0dd6d655d37b6b357f18`.
Proof container3ef67ae94ff2dfe7ed4fb3bce4935d15a2391911b797ff7f0336d15921f8c79c
exited0. Producer6507ce4d3e44d02fae97004bebb14f2f4fc3e083f0d6b8c240d1fa662343d508
exited0. Never restart either or repeat the original studies.

Proof path:
`/home/animallya96/scratch/daily-arithmetic-bridge-verification-20261003-d339aebe/proof/proof.json`.
Diagram impact: NONE; these methods remain within the existing research,
carried-account and artifact-verification boundary.
