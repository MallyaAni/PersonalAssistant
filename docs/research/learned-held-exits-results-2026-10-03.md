# Learned holding exits: fixed funded results

The optional research policy permits a forecast-driven retain, trim or exit
for an existing B holding. New buys remain A/A+ only; B cannot be increased
or rebought after exit. C/unknown/membership exits remain mandatory.
Default behavior is unchanged. Production is unchanged.

The band account beats both ETFs at every fixed cost, but trails the daily
rule at0/10bp. At10bp its gain348.61% compares with447.18% for the rule,
253.97% for QQQ and170.73% for SPY. At25bp it gains328.73% versus325.00%
for the rule. The raw account trails the rule at every cost and both ETFs
at10/25bp. No reliable live replacement or favorable-cell adoption.

Protocol b127b106 preceded code/fits. Evaluated source `94130c30afa4b1bcd2db7bf4e5b01674a295b791`.
One fixed model with B/A/A+ feature support; same13 causal features,
one-session arithmetic target,504/756 mature dates, monthly strictD+2
purge, equal total date weights and August17 freeze. Genuine past OOS
residual band, not calibrated probability or confidence. Both training
support and holding permission changed: these gains do not isolate the
holding effect or establish better intraday entry timing.

One fit, six NEW raw/band accounts,27 authenticated saved controls.
No old fits/scoring/replay. All94stocks and both ETFs retained. Common
NAV1 March2,2020 anchor, first open proxy March3, end September30,2026;
1,654 returns. All costs, windows and stock profit components retained.

| Cost | Account | Net gain | CAGR | Drawdown loss | Sharpe | Gross trading / year |
|---|---|---:|---:|---:|---:|---:|
| 0bp | Held direct | 374.92% | 26.79% | 33.24% | 0.97 | 88.06 |
| 0bp | Held band | 397.03% | 27.67% | 36.87% | 0.99 | 42.83 |
| 0bp | Previous independent direct | 894.53% | 41.90% | 35.83% | 1.34 | 88.36 |
| 0bp | Previous independent band | 386.29% | 27.25% | 38.17% | 1.02 | 34.73 |
| 0bp | Earlier direct | 749.92% | 38.55% | 35.83% | 1.26 | 89.20 |
| 0bp | Earlier band | 356.69% | 26.04% | 40.25% | 1.10 | 29.43 |
| 0bp | Affine bridge | 537.66% | 32.61% | 41.17% | 1.01 | 34.04 |
| 0bp | Past mean | 625.74% | 35.25% | 47.68% | 1.06 | 16.53 |
| 0bp | Daily grade equal | 547.68% | 32.93% | 47.50% | 1.01 | 25.75 |
| 0bp | SPY | 171.00% | 16.40% | 28.32% | 0.86 | 0.15 |
| 0bp | QQQ | 254.32% | 21.26% | 35.12% | 0.90 | 0.15 |
| 10bp | Held direct | 101.46% | 11.26% | 39.83% | 0.51 | 65.91 |
| 10bp | Held band | 348.61% | 25.69% | 35.35% | 0.94 | 31.18 |
| 10bp | Previous independent direct | 374.36% | 26.77% | 38.94% | 0.97 | 65.33 |
| 10bp | Previous independent band | 292.49% | 23.16% | 41.39% | 0.90 | 26.19 |
| 10bp | Earlier direct | 296.40% | 23.35% | 38.84% | 0.87 | 66.14 |
| 10bp | Earlier band | 254.99% | 21.29% | 41.95% | 0.93 | 22.30 |
| 10bp | Affine bridge | 186.42% | 17.39% | 36.70% | 0.68 | 13.81 |
| 10bp | Past mean | 134.51% | 13.87% | 30.76% | 0.71 | 8.55 |
| 10bp | Daily grade equal | 447.18% | 29.56% | 48.68% | 0.94 | 25.74 |
| 10bp | SPY | 170.73% | 16.39% | 28.32% | 0.86 | 0.15 |
| 10bp | QQQ | 253.97% | 21.24% | 35.12% | 0.90 | 0.15 |
| 25bp | Held direct | 112.02% | 12.13% | 40.16% | 0.53 | 39.67 |
| 25bp | Held band | 328.73% | 24.83% | 36.22% | 0.91 | 21.07 |
| 25bp | Previous independent direct | 336.59% | 25.18% | 40.27% | 0.92 | 41.16 |
| 25bp | Previous independent band | 251.05% | 21.09% | 36.64% | 0.85 | 16.79 |
| 25bp | Earlier direct | 280.89% | 22.60% | 40.27% | 0.85 | 42.16 |
| 25bp | Earlier band | 210.49% | 18.84% | 40.91% | 0.85 | 14.37 |
| 25bp | Affine bridge | 91.75% | 10.43% | 39.45% | 0.58 | 4.81 |
| 25bp | Past mean | 0.00% | 0.00% | 0.00% | Unavailable | 0.00 |
| 25bp | Daily grade equal | 325.00% | 24.66% | 50.41% | 0.82 | 25.72 |
| 25bp | SPY | 170.32% | 16.36% | 28.32% | 0.86 | 0.15 |
| 25bp | QQQ | 253.44% | 21.21% | 35.12% | 0.90 | 0.15 |

Nominal2018–20 starts in March2020. The recent32 sessions were reused,
not an untouched holdout. Excess values are cumulative percentage points.

| Cost | Account | Window | Gain | vs previous raw | vs previous band | vs rule | vs SPY | vs QQQ |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 0bp | Held direct | all | 374.92% | -519.62pp | -11.37pp | -172.76pp | 203.92pp | 120.60pp |
| 0bp | Held direct | 2018_2020 | 15.23% | -33.92pp | -10.48pp | -33.13pp | -7.83pp | -30.10pp |
| 0bp | Held direct | 2021_2026 | 312.16% | -254.67pp | 25.32pp | -24.40pp | 191.94pp | 168.35pp |
| 0bp | Held direct | reused_2026_08_17_09_30 | 10.23% | -6.42pp | 4.16pp | 3.18pp | 11.75pp | 8.93pp |
| 0bp | Held band | all | 397.03% | -497.50pp | 10.74pp | -150.65pp | 226.03pp | 142.71pp |
| 0bp | Held band | 2018_2020 | 5.32% | -43.83pp | -20.39pp | -43.04pp | -17.74pp | -40.01pp |
| 0bp | Held band | 2021_2026 | 371.93% | -194.90pp | 85.09pp | 35.37pp | 251.71pp | 228.12pp |
| 0bp | Held band | reused_2026_08_17_09_30 | 6.52% | -10.12pp | 0.45pp | -0.53pp | 8.04pp | 5.22pp |
| 10bp | Held direct | all | 101.46% | -272.90pp | -191.03pp | -345.72pp | -69.26pp | -152.50pp |
| 10bp | Held direct | 2018_2020 | 10.10% | -13.20pp | -14.43pp | -34.62pp | -12.84pp | -35.09pp |
| 10bp | Held direct | 2021_2026 | 82.99% | -201.74pp | -132.21pp | -195.11pp | -37.23pp | -60.82pp |
| 10bp | Held direct | reused_2026_08_17_09_30 | 7.17% | -8.70pp | 2.62pp | 0.66pp | 8.70pp | 5.88pp |
| 10bp | Held band | all | 348.61% | -25.75pp | 56.11pp | -98.57pp | 177.88pp | 94.64pp |
| 10bp | Held band | 2018_2020 | 9.99% | -13.31pp | -14.53pp | -34.73pp | -12.94pp | -35.19pp |
| 10bp | Held band | 2021_2026 | 307.86% | 23.14pp | 92.66pp | 29.77pp | 187.64pp | 164.06pp |
| 10bp | Held band | reused_2026_08_17_09_30 | -0.55% | -16.42pp | -5.10pp | -7.06pp | 0.97pp | -1.84pp |
| 25bp | Held direct | all | 112.02% | -224.56pp | -139.03pp | -212.98pp | -58.30pp | -141.41pp |
| 25bp | Held direct | 2018_2020 | 17.42% | -6.87pp | -6.24pp | -22.01pp | -5.33pp | -27.54pp |
| 25bp | Held direct | 2021_2026 | 80.56% | -170.68pp | -103.31pp | -124.25pp | -39.66pp | -63.24pp |
| 25bp | Held direct | reused_2026_08_17_09_30 | 1.70% | -13.51pp | -2.22pp | -4.02pp | 3.22pp | 0.40pp |
| 25bp | Held band | all | 328.73% | -7.86pp | 77.68pp | 3.72pp | 158.41pp | 75.29pp |
| 25bp | Held band | 2018_2020 | 13.97% | -10.33pp | -9.69pp | -25.47pp | -8.78pp | -31.00pp |
| 25bp | Held band | 2021_2026 | 276.18% | 24.94pp | 92.31pp | 71.37pp | 155.96pp | 132.38pp |
| 25bp | Held band | reused_2026_08_17_09_30 | -1.12% | -16.33pp | -5.04pp | -6.84pp | 0.40pp | -2.42pp |

| Cost | Account | Rolling wins vs previous raw | vs previous band | vs rule | vs SPY | vs QQQ | Windows |
|---|---|---:|---:|---:|---:|---:|---:|
| 0bp | Held direct | 25.80% | 58.59% | 44.90% | 64.36% | 65.79% | 1403 |
| 0bp | Held band | 26.37% | 66.93% | 46.97% | 75.91% | 76.12% | 1403 |
| 10bp | Held direct | 32.72% | 36.35% | 24.09% | 23.16% | 27.01% | 1403 |
| 10bp | Held band | 60.37% | 71.92% | 45.05% | 70.56% | 66.86% | 1403 |
| 25bp | Held direct | 38.85% | 47.04% | 31.36% | 35.57% | 39.06% | 1403 |
| 25bp | Held band | 50.18% | 73.77% | 55.74% | 68.57% | 61.51% | 1403 |

VERIFIED:190 applicable native and190 pinned-image implementation cases,
no skips,12 exact default comparisons against authenticated old source
per runtime. Independent tests caught infinitesimal retained ownership,
unnecessary trims and zero-cash additions. Exact boundary candidates now
require the same global feasibility/optimality certificate; no epsilon
clipping and no changed assertions.42 verifier corruption cases pass in
both runtimes. Saved proof validates every training row, numeric tree,
past-OOS band, holding bound, funding constraint, journal and score.

Actual proof: 141 monthly receipts, 104 numeric heads.
Counts: {"allocator_unavailable": 81, "cash_limited": 3324, "filled_intents": 24466, "intents": 27790, "missing_open": 0, "plans": 9930}.
Support: {"added_opportunities": 20209, "feature_opportunities": 33279, "original_bridge_opportunities": 13070}.
Calibration: {"available": 25445, "opportunities": 33279, "unavailable": 7834}.

FAILED: advantage over the daily rule at every cost; excessive trading
remains. Lower drawdown or selected-window gains are not adoption proof.
UNVERIFIED: full live/intraday/FOMC parity, historical grade publication,
calibrated probabilities, broker/midpoint fills and future excess gain.
Current-vintage eligibility, adjusted fractional units, daily open proxies,
approximate one-session risk and zero cash yield remain explicit.
Daily studies cannot establish how an evolving AAOI15-minute decline
would be handled. No hindsight-low entry or strategy promotion.

Report SHA256 `50150fe3a40a475e88d0fa9cc65f7c418676a9c5d8d22af6d1e73d9eda5c82f6`; proof `bdc6efef13bd67be525e43fe3c077724300e315e5d589703c9225f779b3538c3`.
Manifest `14a41d177bc0d9f9ae2d9930664fee8f00d4d5f22a8d80579a2dcd893780f512`.
Producer22aad560 and proofb6a7282c exited0. Never restart/refit/rescore.
Study `/home/animallya96/scratch/learned-held-results-20261003-94130c30/study`.
Models/data/UI/account state unchanged; no research-only deploy. DiagramNONE.
