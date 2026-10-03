# Stock-specific fifteen-minute timing: completed evidence

Implemented on `codex/learned-entry-risk-20261002`; live is unchanged.
The candidate combines a stock-conditioned price forecast with a forecast of
the same fifteen-minute waiting risk. It compares the expected benefit of
waiting with the funded order's risk, replacing the universal 1% timing trigger
in this research controller. Existing grades, stock selection and v5 target
plans remain fixed; this does not change allocation sizing. Those v5 targets
are equal weights across eligible A/A+ names, capped at 25% per name, not a
hard-coded 9%. A target near 9% results when eleven names qualify.

Both waiting means and risk now train only on actual fifteen-minute outcomes.
The original fixed estimator settings, monthly refits, mature prior-only
training, universe and all twenty account phases remain unchanged. The
[protocol](fifteen-minute-execution-plan-2026-10-02.md) was frozen before fitting.
One fit and one comparison completed; no original baseline was rerun.

Risk calibration improved materially: predicted/observed second moment is
1.053 across 3,812,089 known ordinary stock observations. Clock 22's ratio fell
from about 40 to 1.372; clock 0 is 0.875 and clock 19 is 1.289. This is an average
diagnostic, not proof of calibrated uncertainty for every stock. Negative
forecasts remain explicit: 138 in the saved grid, 135 scored ordinary stock rows.
Invalid moments are refused rather than clipped to fabricate confidence.

The price forecast still has no demonstrated edge. Log-price RMSE is 0.004833
for boosting and 0.004824 for Ridge; predicting zero on the same observations
has RMSE 0.004815. Better risk calibration did **not** improve portfolio returns.

All figures below are medians across the twenty declared carried-account
phases, 2018-02-01 through 2026-09-30, 2,177 sessions. Paired differences compare
each account with its matching control; they are not differences of medians.
These phase accounts are sensitivity tests, not one compounded portfolio.

| Cost per side | Mean forecast | Total gain | CAGR | Drawdown loss | Paired gain difference | Wins vs control |
|---|---|---:|---:|---:|---:|---:|
| 0 bp | Boosting | 759.81% | 28.28% | 37.62% | −8.04 pp | 8/20 |
| 0 bp | Ridge | 750.45% | 28.12% | 37.23% | −11.55 pp | 7/20 |
| 10 bp | Boosting | 713.63% | 27.46% | 38.03% | −6.28 pp | 8/20 |
| 10 bp | Ridge | 703.74% | 27.28% | 37.58% | −9.87 pp | 7/20 |
| 25 bp | Boosting | 648.97% | 26.25% | 38.64% | −3.94 pp | 9/20 |
| 25 bp | Ridge | 638.47% | 26.04% | 38.11% | −7.63 pp | 7/20 |

At 10 bp the control median is 723.38% gain/27.64% CAGR/37.26% drawdown loss.
SPY is 209.52%/13.97%/33.72%; QQQ is 364.83%/19.47%/35.12%. The book's large
benchmark excess already exists in selection; this timing model reduces it.
Current-vintage grades/universe prevent treating these numbers as exact live
historical performance. The first split actually begins in 2018, not 2016.
The JSON retains every phase, both historical splits, rolling 252 comparisons,
declared regime diagnostics, all costs and benchmarks.

The already-observed Aug 17–Sep 30 period is reused, not a new untouched holdout.
At 10 bp boosting gains 0.884%, Ridge 1.146%, control median 2.179%, QQQ 1.295%,
SPY −1.522%. Paired candidate differences are −0.979/−0.678 pp, wins 5/20 and 7/20.
Both methods trail the control on median paired full/recent results at every
declared cost. Do not select a favorable phase, regime or method for promotion.

At 10 bp the twenty boosting accounts sum to 17,382 intents: 7,808 completed,
8,732 partial and 842 unfilled. There are 16,540 fills, 4,148 at the separate
closing deadline. Ridge totals 17,273 intents: 8,457 completed, 7,052 partial,
1,764 unfilled; 15,509 fills, 2,736 closing fills. Missing observations and
expired partials remain explicit. These sums are not unique market events.

VERIFIED: exact execution source `21ee02e9bbb2024c79e202c614168a681a6322f9`,
native 60/source-image 60 checks, unchanged independent acceptance, 104 monthly
three-head fits/312 model artifacts, original private 96-cube hashes, maturity,
forecast dtypes and hashes, all Ridge certificates, 120 candidate/66 reused
reference curves, cash/fees/turnover, compounded metrics, rolling 252 windows,
stock accounting and lifecycle counts. Independent verification never loaded
model pickles, refitted or resimulated. All 17 executed/shared source hashes
also match exact Git objects; shared accounting matches original source.

FAILED: evidence for superior entry/exit timing from these price forecasts.
UNVERIFIED: future edge, broker/midpoint fills, exact live `/6` reconstruction
and historical fundamentals/news. Other limits include fractional NAV1,
bar-open/observed-auction proxies, incomplete/early-close coverage, a one-step
utility approximation, absent portfolio covariance and no serialized per-intent
plan trace. The deadline is lifecycle completion, not a learned sell signal.
No new variant, parameter tuning or live promotion follows from this result.

Private artifacts:
`/home/animallya96/scratch/fifteen-minute-moments-results-20261002-21ee02e9`;
independent proofs in
`/home/animallya96/scratch/fifteen-minute-independent-20261002`.
Report SHA256 `8789004debeaf28207f2ccfab7e7ed9801a746c811587498ac68742d9e604cf8`;
forecast `b797bc49c33c23b70c75b5217aa052ad99f2bdae86df722e6badd12ece40917a`;
full independent proof
`acfce242c26b57d04442bd448ead524feeef113d705bc9b9e6443ed0ab223147`.
[Machine-readable evidence](fifteen-minute-execution-results-2026-10-02.json).
