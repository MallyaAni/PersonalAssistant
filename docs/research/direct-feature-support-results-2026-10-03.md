# Direct feature support: fixed funded comparison

The implemented learner now uses available causal stock features directly.
It no longer waits for an older ten-session predictor before accumulating
its own training history. It retains the same fixed model, one-session
arithmetic label, monthly purge, funding constraints and account anchor.
There is no fixed percentage entry or profit-taking trigger in this candidate.

The raw arm improves full-period gain over the preceding direct learner at
all three costs and beats both SPY and QQQ. Its zero-cost gain is894.53%
versus the matched daily rule547.68%. At25bp it gains336.59% versus325.00%.
At10bp it still trails the rule374.36% versus447.18%, and trading remains
high. The band reduces trading but trails the rule at all costs. These
results do not establish a reliable full live replacement; no adoption.

Protocolf77b244e was frozen before fits/outcomes; evaluated source
`de7a0059ceaa4ff0c4d6bccd360061f34db1c64d`. Original thirteen float32 causal features, fixed64-iteration
boosting configuration,504/756 distinct-date support, equal total weight
per date, strictD+2 maturity and August17 freeze are unchanged. Eligibility
is explicit validity/current grade/membership/completed-close support,
never old prediction or future-label availability. First score2018-02-01;
104 numeric monthly heads,141 receipts. Opportunities16,691 versus original
13,070;3,621 added. The band uses genuine prior OOS residuals and the unchanged
bias-plus-cluster-SE formula, coefficient1. It is not calibrated confidence.

All94stocks and both ETFs remain. Every account starts NAV1 on March2,2020,
first official-open proxy March3, end September30,2026:1,654 return sessions.
Earlier training contributes no earlier account returns. Exactly six NEW
raw/band books were run at0/10/25bp;21 saved control books are authenticated
and reused without old fits, scoring, account replay or repeated audits.

| Cost | Book | Net gain | CAGR | Drawdown loss | Sharpe | Gross trading / year |
|---|---|---:|---:|---:|---:|---:|
| 0bp | Independent direct | 894.53% | 41.90% | 35.83% | 1.34 | 88.36 |
| 0bp | Independent band | 386.29% | 27.25% | 38.17% | 1.02 | 34.73 |
| 0bp | Earlier direct | 749.92% | 38.55% | 35.83% | 1.26 | 89.20 |
| 0bp | Earlier band | 356.69% | 26.04% | 40.25% | 1.10 | 29.43 |
| 0bp | Affine bridge | 537.66% | 32.61% | 41.17% | 1.01 | 34.04 |
| 0bp | Past mean | 625.74% | 35.25% | 47.68% | 1.06 | 16.53 |
| 0bp | Daily grade equal | 547.68% | 32.93% | 47.50% | 1.01 | 25.75 |
| 0bp | SPY | 171.00% | 16.40% | 28.32% | 0.86 | 0.15 |
| 0bp | QQQ | 254.32% | 21.26% | 35.12% | 0.90 | 0.15 |
| 10bp | Independent direct | 374.36% | 26.77% | 38.94% | 0.97 | 65.33 |
| 10bp | Independent band | 292.49% | 23.16% | 41.39% | 0.90 | 26.19 |
| 10bp | Earlier direct | 296.40% | 23.35% | 38.84% | 0.87 | 66.14 |
| 10bp | Earlier band | 254.99% | 21.29% | 41.95% | 0.93 | 22.30 |
| 10bp | Affine bridge | 186.42% | 17.39% | 36.70% | 0.68 | 13.81 |
| 10bp | Past mean | 134.51% | 13.87% | 30.76% | 0.71 | 8.55 |
| 10bp | Daily grade equal | 447.18% | 29.56% | 48.68% | 0.94 | 25.74 |
| 10bp | SPY | 170.73% | 16.39% | 28.32% | 0.86 | 0.15 |
| 10bp | QQQ | 253.97% | 21.24% | 35.12% | 0.90 | 0.15 |
| 25bp | Independent direct | 336.59% | 25.18% | 40.27% | 0.92 | 41.16 |
| 25bp | Independent band | 251.05% | 21.09% | 36.64% | 0.85 | 16.79 |
| 25bp | Earlier direct | 280.89% | 22.60% | 40.27% | 0.85 | 42.16 |
| 25bp | Earlier band | 210.49% | 18.84% | 40.91% | 0.85 | 14.37 |
| 25bp | Affine bridge | 91.75% | 10.43% | 39.45% | 0.58 | 4.81 |
| 25bp | Past mean | 0.00% | 0.00% | 0.00% | Unavailable | 0.00 |
| 25bp | Daily grade equal | 325.00% | 24.66% | 50.41% | 0.82 | 25.72 |
| 25bp | SPY | 170.32% | 16.36% | 28.32% | 0.86 | 0.15 |
| 25bp | QQQ | 253.44% | 21.21% | 35.12% | 0.90 | 0.15 |

Every registered new window follows. Nominal2018–20 begins in March2020;
the recent32 sessions are reused, not an untouched holdout. Differences are
percentage points of cumulative gain on matching carried dates. The JSON
also preserves all remaining control contrasts, fees, exposure, intent/fill/
cash/missing/unavailable counts and all individual stock profit components.

| Cost | Arm | Window | Net gain | vs earlier direct | vs rule | vs SPY | vs QQQ |
|---|---|---|---:|---:|---:|---:|---:|
| 0bp | Independent direct | all | 894.53% | 144.61pp | 346.86pp | 723.54pp | 640.21pp |
| 0bp | Independent direct | 2018_2020 | 49.14% | 15.78pp | 0.78pp | 26.09pp | 3.81pp |
| 0bp | Independent direct | 2021_2026 | 566.82% | 29.51pp | 230.27pp | 446.60pp | 423.02pp |
| 0bp | Independent direct | reused_2026_08_17_09_30 | 16.64% | 0.00pp | 9.60pp | 18.16pp | 15.35pp |
| 0bp | Independent band | all | 386.29% | -363.63pp | -161.39pp | 215.29pp | 131.97pp |
| 0bp | Independent band | 2018_2020 | 25.71% | -7.65pp | -22.65pp | 2.65pp | -19.62pp |
| 0bp | Independent band | 2021_2026 | 286.83% | -250.48pp | -49.72pp | 166.61pp | 143.03pp |
| 0bp | Independent band | reused_2026_08_17_09_30 | 6.07% | -10.58pp | -0.98pp | 7.59pp | 4.77pp |
| 10bp | Independent direct | all | 374.36% | 77.96pp | -72.82pp | 203.64pp | 120.40pp |
| 10bp | Independent direct | 2018_2020 | 23.30% | 11.36pp | -21.42pp | 0.37pp | -21.89pp |
| 10bp | Independent direct | 2021_2026 | 284.72% | 30.59pp | 6.63pp | 164.50pp | 140.92pp |
| 10bp | Independent direct | reused_2026_08_17_09_30 | 15.87% | -0.26pp | 9.36pp | 17.39pp | 14.57pp |
| 10bp | Independent band | all | 292.49% | -3.91pp | -154.68pp | 121.77pp | 38.53pp |
| 10bp | Independent band | 2018_2020 | 24.52% | 12.59pp | -20.20pp | 1.59pp | -20.66pp |
| 10bp | Independent band | 2021_2026 | 215.20% | -38.93pp | -62.89pp | 94.98pp | 71.40pp |
| 10bp | Independent band | reused_2026_08_17_09_30 | 4.55% | -11.58pp | -1.96pp | 6.07pp | 3.26pp |
| 25bp | Independent direct | all | 336.59% | 55.70pp | 11.58pp | 166.27pp | 83.15pp |
| 25bp | Independent direct | 2018_2020 | 24.30% | 13.41pp | -15.13pp | 1.55pp | -20.67pp |
| 25bp | Independent direct | 2021_2026 | 251.24% | 7.75pp | 46.43pp | 131.02pp | 107.43pp |
| 25bp | Independent direct | reused_2026_08_17_09_30 | 15.21% | 0.30pp | 9.49pp | 16.73pp | 13.92pp |
| 25bp | Independent band | all | 251.05% | -29.84pp | -73.95pp | 80.73pp | -2.39pp |
| 25bp | Independent band | 2018_2020 | 23.66% | 12.77pp | -15.77pp | 0.91pp | -21.31pp |
| 25bp | Independent band | 2021_2026 | 183.88% | -59.61pp | -20.93pp | 63.66pp | 40.07pp |
| 25bp | Independent band | reused_2026_08_17_09_30 | 3.92% | -10.99pp | -1.80pp | 5.44pp | 2.63pp |

| Cost | Arm | Rolling wins vs earlier direct | vs rule | vs SPY | vs QQQ | Windows |
|---|---|---:|---:|---:|---:|---:|
| 0bp | Independent direct | 87.60% | 59.59% | 81.25% | 79.62% | 1403 |
| 0bp | Independent band | 25.66% | 45.05% | 64.01% | 57.95% | 1403 |
| 10bp | Independent direct | 55.45% | 43.83% | 58.80% | 58.23% | 1403 |
| 10bp | Independent band | 38.28% | 42.48% | 57.73% | 47.33% | 1403 |
| 25bp | Independent direct | 62.08% | 53.60% | 53.03% | 53.96% | 1403 |
| 25bp | Independent band | 48.04% | 41.34% | 43.48% | 49.61% | 1403 |

VERIFIED:113 applicable native and113 pinned-image implementation checks,
no skips. Independent acceptance reproduces the old-forecast exclusion and
checks strict maturity/freeze/future-prefix/early-close/invalid outputs. A
forged fitted warmup receipt initially passed calibration; the unchanged
case was reproduced and fixed before actual outcomes. Calibration now
reconstructs admitted dated support rather than trusting a fitted status.

The saved-only proof verifies source/input/control bytes, dated training
rows and numeric tree predictions without estimator.predict or fitting,
genuine OOS residual bands, global target certificates, funding and every
new journal/metric. Exact totals and missing calibration evidence are in
the adjacent original proof. It never reruns the strategy or old models.

Verifier corruption acceptance:33 native and33 image cases, no skips.
Actual proof:9,930 plans;29,667 intents;26,516 full fills;3,151 cash-limited;
zero missing-open intents;78 explicit allocator unavailable plans. Daily
stock scoring opportunities16,691:11,822 radii available and4,869 unavailable.

FAILED: raw full-period rule advantage at10bp and band rule advantage at
all costs. Raw trading88.36/65.33/41.16NAV/year remains excessive for the
intended low-turnover personal portfolio. Band trading34.73/26.19/16.79
reduces activity but sacrifices gain. Do not choose a favorable cost/arm/
window/regime or tune the band from these outcomes. Cost changes also alter
optimized targets and paths; cross-cost differences are not isolated fee drag.

UNVERIFIED: full live-policy and intraday/FOMC parity, historical grade
publication, broker or midpoint fills, reliable future excess gain. The
universe and grades are current-vintage reconstruction; rule comparison is
its daily target component. Adjusted fractional units, official-open proxies,
approximate one-session risk and zero cash yield stay explicit. Overlapping
rolling windows are not independent trials. Production policy/UI/data/models
remain unchanged. No automatic adoption or research-only deployment.

Report SHA256: `491d90d52414ef6af25d7bf0c60dc4a84c042993fbaa47052d0280a2e7425929`.
Proof SHA256: `87ecc525f2fe0642cd5d558fd79ccc05741fd97bd178f7b5f7d6306bbae3f60d`.
Source manifest: `5e3ed548b9d9ba3c2b1588c3797b49100be0a483fb2aa8a4266d614708737df5`.
Producer7b0fe0b3 exited0; never restart/refit/rescore completed studies.
Study: `/home/animallya96/scratch/direct-feature-results-20261003-de7a0059/study`.
Diagram impact NONE within existing research/accounting/artifact boundaries.
