# Error-informed holding bands: fixed funded comparison

The implemented stock-specific error band reduces changes to
learned holdings. It reduces trading substantially, but loses total gain
against both the direct learner and matched daily rule at every cost.
It is not adopted. Production is unchanged.

Protocol97c3ebed was frozen before these outcomes. Source0e563ccb reuses
the exact saved one-session direct forecasts: no model fitting or scoring.
The monthly stock radius is absolute past residual bias plus its calendar-
month cluster standard error, with multiplier1 and strict mature-label/
August17 freeze. It penalizes target changes; it is not a paid fee, confidence
guarantee or predicted price range. Sparse calibration stays unavailable.

Exactly three new accounts use the common March2,2020 NAV1 anchor and
March3 first official-open proxy. Eighteen saved controls are authenticated
without refitting, replay or repeated account audits. All94stocks, two ETFs,
1,654 returns and every cost/window cell remain in the adjacent JSON.

| Cost | Book | Net gain | CAGR | Drawdown loss | Sharpe | Gross trading / year |
|---|---|---:|---:|---:|---:|---:|
| 0bp | Error band | 356.69% | 26.04% | 40.25% | 1.10 | 29.43 |
| 0bp | Direct learner | 749.92% | 38.55% | 35.83% | 1.26 | 89.20 |
| 0bp | Affine bridge | 537.66% | 32.61% | 41.17% | 1.01 | 34.04 |
| 0bp | Past mean | 625.74% | 35.25% | 47.68% | 1.06 | 16.53 |
| 0bp | Daily grade equal | 547.68% | 32.93% | 47.50% | 1.01 | 25.75 |
| 0bp | SPY | 171.00% | 16.40% | 28.32% | 0.86 | 0.15 |
| 0bp | QQQ | 254.32% | 21.26% | 35.12% | 0.90 | 0.15 |
| 10bp | Error band | 254.99% | 21.29% | 41.95% | 0.93 | 22.30 |
| 10bp | Direct learner | 296.40% | 23.35% | 38.84% | 0.87 | 66.14 |
| 10bp | Affine bridge | 186.42% | 17.39% | 36.70% | 0.68 | 13.81 |
| 10bp | Past mean | 134.51% | 13.87% | 30.76% | 0.71 | 8.55 |
| 10bp | Daily grade equal | 447.18% | 29.56% | 48.68% | 0.94 | 25.74 |
| 10bp | SPY | 170.73% | 16.39% | 28.32% | 0.86 | 0.15 |
| 10bp | QQQ | 253.97% | 21.24% | 35.12% | 0.90 | 0.15 |
| 25bp | Error band | 210.49% | 18.84% | 40.91% | 0.85 | 14.37 |
| 25bp | Direct learner | 280.89% | 22.60% | 40.27% | 0.85 | 42.16 |
| 25bp | Affine bridge | 91.75% | 10.43% | 39.45% | 0.58 | 4.81 |
| 25bp | Past mean | 0.00% | 0.00% | 0.00% | Unavailable | 0.00 |
| 25bp | Daily grade equal | 325.00% | 24.66% | 50.41% | 0.82 | 25.72 |
| 25bp | SPY | 170.32% | 16.36% | 28.32% | 0.86 | 0.15 |
| 25bp | QQQ | 253.44% | 21.21% | 35.12% | 0.90 | 0.15 |

Every declared candidate window follows. Nominal2018–20 begins in March2020;
earlier unavailable support is retained rather than selecting the first trade.
The recent32-session window is reused, not an untouched holdout. Differences
are percentage points of cumulative gain on the same carried dates.

| Cost | Window | Net gain | vs direct | vs rule | vs SPY | vs QQQ |
|---|---|---:|---:|---:|---:|---:|
| 0bp | all | 356.69% | -393.23pp | -190.98pp | 185.70pp | 102.37pp |
| 0bp | 2018_2020 | 10.86% | -22.50pp | -37.50pp | -12.20pp | -34.47pp |
| 0bp | 2021_2026 | 311.97% | -225.34pp | -24.59pp | 191.75pp | 168.16pp |
| 0bp | reused_2026_08_17_09_30 | 6.07% | -10.58pp | -0.98pp | 7.59pp | 4.77pp |
| 10bp | all | 254.99% | -41.42pp | -192.19pp | 84.26pp | 1.02pp |
| 10bp | 2018_2020 | 10.05% | -1.89pp | -34.67pp | -12.88pp | -35.13pp |
| 10bp | 2021_2026 | 222.56% | -31.57pp | -55.53pp | 102.34pp | 78.76pp |
| 10bp | reused_2026_08_17_09_30 | 4.55% | -11.58pp | -1.96pp | 6.07pp | 3.26pp |
| 25bp | all | 210.49% | -70.39pp | -114.51pp | 40.17pp | -42.95pp |
| 25bp | 2018_2020 | 10.32% | -0.57pp | -29.11pp | -12.43pp | -34.65pp |
| 25bp | 2021_2026 | 181.44% | -62.04pp | -23.36pp | 61.22pp | 37.64pp |
| 25bp | reused_2026_08_17_09_30 | 3.92% | -10.99pp | -1.80pp | 5.44pp | 2.63pp |

| Cost | Rolling wins vs direct | vs rule | vs SPY | vs QQQ | Windows |
|---|---:|---:|---:|---:|---:|
| 0bp | 25.02% | 49.04% | 64.22% | 66.14% | 1403 |
| 10bp | 43.41% | 47.83% | 58.37% | 55.95% | 1403 |
| 25bp | 39.27% | 41.13% | 41.55% | 45.97% | 1403 |

VERIFIED:129 native and129 pinned-image implementation checks, no skips;
12 additional exact default target/receipt comparisons in both runtimes.
The independent saved-only verifier passes34 native and34 image corruption
cases. Actual proof checks141 monthly receipts, all stock error statistics/
radius hashes, causal covariance, actual-fee funding, global objective
certificates and new journal/score arithmetic. It does not refit, predict,
replay the strategy or repeat old account audits. Plans4,965; intents7,425;
full fills6,758; cash-limited667; missing opens0; unavailable allocators167.
Daily stock scoring opportunities13,070: radius available8,868 and unavailable4,202.

FAILED: full-period gain advantage over the direct learner and rule at all
three costs; at25bp it also trails QQQ. Lower trading alone is insufficient.
Do not tune the radius, multiplier, period, regime or stock selection from
these outcomes. Costs change decisions and paths, not only paid fees.

UNVERIFIED: reliable full live replacement, historical point-in-time grade
publication, broker fills and intraday timing. Historical eligibility uses
current-vintage reconstruction; the rule is its daily target component.
Adjusted fractional units, official-open proxies, zero cash yield, operator
caps and approximate one-session risk remain explicit. Production policy,
UI, data and model services remain unchanged. No research-only deployment.

Report SHA256: `98d29a64cfb2703fb79c06b76a1d1cc74307ea1d86dcb1650981778cd935f3c0`.
Proof SHA256: `ea673e3e4555ac853eafd6c713b61739d54872928b2f9cde4361cfa2f3cc7b09`.
Source: `0e563ccb9756814c7493aa777e61b28ed8a2eb0b`.
Source manifest: `2bb2fab628fec9895ace486c3186ba2a3d1afe8ebd9b006288fad17d6d0ced7c`.
Verifier: `c46a330ee34db0160a51eff9c7754bd24a46f86fac173ae0b4c7da65de53c7cb`.
Producer6369e11c and proof1e23138d both exited0; never restart them.
Study: `/home/animallya96/scratch/direct-error-band-results-20261003-0e563ccb/study`.
Proof: `/home/animallya96/scratch/direct-error-band-verification-20261003-0e563ccb/proof/proof.json`.
Diagram impact NONE within existing research/accounting/artifact boundaries.
