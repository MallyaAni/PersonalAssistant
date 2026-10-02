# Learned entry, exit and sizing: measured results

## Decision

Three fixed approaches are implemented and evaluated on
`codex/learned-entry-risk-20261002`: gradient boosting, Ridge and pinned
Chronos-2. Their funded policy chooses entries, trims/exits and position weights
from predicted return, risk, correlations, waiting advantage and costs. It does
not use a 1% execution threshold or equal 9% allocations.

**No live replacement is justified by this experiment.** Chronos is promising
in the recent window; boosting has substantial long-history gains before costs.
Neither establishes superiority over the declared rule control after costs.
The production `/6` policy, broker account and dashboard remain unchanged.

The control is the fixed price/grade component across all 20 reset phases,
using the same funded research ledger. It is **not an exact reconstruction of
the current whole-share live planner**, its historical overlays or broker fills.
A median of phases is a comparison statistic, not an investable combined curve.

## Fixed recent comparison

Fresh NAV1 accounts, 2026-08-17 through 2026-09-30, **32 exchange sessions**.
Every learned method trades only after completed 15-minute bar9; all 20 control
phases and SPY/QQQ are retained. Costs are basis points per side. The benchmark
enters at the first session open; the candidate first observes its declared bar.
This comparison is separate from the continuously carried accounts below.

| Method/reference | Net gain, 0 bp | Net gain, 10 bp | Net gain, 25 bp | Drawdown, 10 bp |
|---|---:|---:|---:|---:|
| Chronos-2 | +3.91% | **+3.79%** | +3.20% | 4.51% |
| Ridge | +2.80% | +1.65% | +0.41% | 8.44% |
| Boosting | −5.53% | −5.83% | −5.71% | 9.41% |
| SPY | −1.50% | −1.60% | −1.75% | 2.95% |
| QQQ | +1.04% | +0.93% | +0.78% | 3.97% |
| Median of 20 controls | +5.79% | **+5.65%** | +5.43% | — |

At 10 bp Chronos beats **8/20** control phases, Ridge **6/20**, boosting **0/20**.
Controls range from −5.04% to +11.89%; selecting a favorable phase would distort
the comparison. Chronos makes 16 fills versus Ridge's 56 and boosting's 41;
one-way turnover is respectively 2.17, 4.28 and 3.31 times contemporaneous NAV.
The declared cost also changes the optimizer's decisions, so cost scenarios
are separate accounts rather than fees subtracted from a single fixed curve.

Coverage is **3,008 requested stock/session opportunities**, 94 stocks × 32
sessions. Boosting and Ridge each provide 2,975 forecasts; Chronos provides
2,411. All missing opportunities remain in the account comparison; it is not
restricted to a favorable common-forecast subset. Chronos refuses 562 invalid
or crossing quantile forecasts, has 33 shared-input gaps and two insufficient
consecutive contexts. Quantiles were not sorted or repaired after seeing results.
Q lacks sufficient long daily history; missing CIEN September 16 breaks the
subsequent Chronos context. These are coverage limits, not proof of safer trading.

Chronos inference used real pinned weights on CPU: **19.7 minutes, 1.12 GB peak
memory**. Revision `95a9710e2596287d08352589f42634fa5abdf0a7` predates this window;
its pretraining data cutoff is undocumented. Marginal-quantile risk and the
terminal regular-close price are approximations. A 32-session result does not
establish a durable edge or broker execution reliability.

## Continuous monthly walk-forward accounts

Common history: **2018-02-01 through 2026-09-30, 2,177 sessions**. Each model has
104 monthly fits. Ten-session label endpoints must precede the fit; September
training ends August 14, before the frozen holdout. Minimum mature history means
there are no learned trades in 2016–17; the requested 2016–20 slice starts in
2018. All 25 regular completed-bar decisions can trade in this evaluation.

| Cost | Policy/reference | Total net gain | CAGR | Max drawdown | Sharpe |
|---|---|---:|---:|---:|---:|
| 0 bp | Boosting | +885.33% | 30.32% | 32.65% | 1.006 |
| 0 bp | Ridge | +499.06% | 23.03% | 41.76% | 0.807 |
| 0 bp | Median control gain | +773.02% | — | — | — |
| 10 bp | Boosting | +600.31% | 25.27% | 35.40% | 0.869 |
| 10 bp | Ridge | +276.17% | 16.57% | 46.53% | 0.634 |
| 10 bp | SPY | +209.52% | 13.97% | 33.72% | 0.782 |
| 10 bp | QQQ | +364.83% | 19.47% | 35.12% | 0.865 |
| 10 bp | Median control gain | +723.38% | — | — | — |
| 25 bp | Boosting | +296.30% | 17.28% | 37.67% | 0.655 |
| 25 bp | Ridge | +217.65% | 14.31% | 50.80% | 0.569 |
| 25 bp | SPY | +209.06% | 13.95% | 33.72% | 0.781 |
| 25 bp | QQQ | +364.13% | 19.44% | 35.12% | 0.865 |
| 25 bp | Median control gain | +654.15% | — | — | — |

Boosting beats **17/20, 3/20, 0/20** controls at 0/10/25 bp; Ridge beats none at
any cost. At 10 bp boosting trades 282.82 NAV turns with 6,089 fills; Ridge
374.86 with 12,333 fills. Their 252-session overlapping win rates versus QQQ
are **61.16%** and **38.53%**, versus SPY **70.40%** and **41.74%**. Overlapping
windows are dependent observations, not thousands of independent trials.

| Continuously carried window, 10 bp | Boosting gain | Ridge gain |
|---|---:|---:|
| 2018-02-01..2020-12-31, 735 sessions | +78.53% | +2.81% |
| 2021-01-04..2026-09-30, 1,442 sessions | +292.25% | +265.87% |
| Frozen holdout, 32 sessions | **−5.33%** | +2.48% |

The carried holdout benchmark returns are SPY −1.52%, QQQ +1.30%. Different
opening accounts explain why these differ from the fresh-account comparison;
the two evaluations must not be spliced together. Chronos has no comparable
long-history evaluation in this experiment.

At 10 bp, MU contributes 3.19 initial-NAV units to boosting's 6.00-unit total
gain; NVDA contributes 1.09. This concentration weakens a claim of generality
across stock structures. Prior-only regime diagnostics show boosting's median
phase-specific mean daily excess of +0.68 bp in downtrend/quiet (101 sessions),
+2.47 bp downtrend/high volatility (300), −1.25 bp uptrend/quiet (1,370), and
+0.63 bp uptrend/high volatility (406). At 25 bp all four are negative. These
diagnostics do not authorize selecting a regime switch from the tested outcomes.

## Verification and limits

**VERIFIED:** source-image acceptance 72 passed, one optional pinned-model skip;
separate real Chronos CPU acceptance 19 passed, zero skips. Final comparison
acceptance 8 passed and Ruff clean. Independent reviewers authenticate original
input/forecast bytes, monthly maturity and every saved funded curve, recomputing
gain, drawdown, costs, cash, exposure, turnover, rolling rates and stock wealth
without refitting or resimulating. Code tests establish accounting and causality,
not profitability.

The first Ridge replay exposed a genuine numerical boundary: SLSQP rejected an
actual constrained optimum with a tiny holding. Exact convex optimality
certificates corrected it without changing model parameters or acceptance
assertions. The interrupted run has no completed score. Training source remains
`ee13b97fc005431c358cd60c8b335d9530bff3be`; corrected execution source is
`9bec943b1f8138d3b7f52ac7269fc49b46502b97`. The final comparison's exact script
hash is `faa73d7b97b1d5b697725f2620821231ab66f8b069ad8bc0d9d657e053afb009`.
No fits or completed backtests were repeated to improve results.

**FAILED:** evidence for unconditional live replacement or reliable superiority
over the declared control. **UNVERIFIED:** live broker/midpoint fills, historical
point-in-time fundamentals/earnings, exact historical live-policy parity and
durability beyond this conditional stock universe. Membership/grades are
current-vintage reconstructions; early-close and missing inputs remain explicit;
the funded ledger is fractional NAV1. There is no new production integration.

Full artifacts are retained privately on Spark at
`/home/animallya96/scratch/learned-entry-results-20261002/{boosting,ridge,common-clock,chronos}`.
The [machine-readable summary](learned-entry-results-2026-10-02.json) records
original report, forecast and independent-proof hashes. Primary report SHA256:

- Boosting: `f340f1329ec67645ba4f534eb9c34afde5cee5e47d85ce88dab7de87ab72f608`.
- Ridge: `a52433cf4f658254b428c9f0622a27d5589e4d1e070d1ede7f329b97da86c27f`.
- Common clock: `3875b43a91b6508251cc662bd0ebb7ce8f7ca495ca4bad9ba8e9ad5c2b0dc7ee`.

Next adoption evidence would require a separately frozen prospective evaluation
of Chronos coverage and funded execution, plus a carried whole-share account
using actual policy selection and broker receipts. This completed window cannot
become a fresh holdout after choosing Chronos from its results. No automatic
strategy promotion or new experiment is scheduled by this report.
