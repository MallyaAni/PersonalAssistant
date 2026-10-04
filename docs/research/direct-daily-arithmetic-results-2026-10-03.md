# Direct learned daily decisions: fixed funded comparison

The implemented model learns each stock’s next-session arithmetic return.
Its forecast and stock covariance determine funded buy, hold, trim and exit
targets. There is no fixed percentage entry or profit-taking trigger in
this candidate. Grade eligibility, covered holdings, cash and the operator
name cap remain constraints. Production is unchanged.

This is a material improvement over the affine forecast bridge. At zero
added cost it gains 749.92%, versus 547.68% for the matched daily grade-equal
rule, with lower drawdown. It beats SPY and QQQ at all three declared costs.
It does not establish a reliable live replacement: at 10bp and 25bp its
full-period net gain is below the rule, and trading is excessive. Turnover
is the concrete remaining decision-model weakness, alongside live parity
and historical eligibility limitations.

Protocol e2c44a56 was frozen before direct fits or outcomes. Evaluated source
e093cd51b9207899bfee6c46f4f578b1e7fd1d97 uses one fixed 64-iteration boosting
configuration and the original thirteen causal features. The label is
adjusted_open[t+2]/adjusted_open[t+1]-1. Every dated training row, date-balanced
weight, 504/756-session support, monthly purge, scoring mask and August 17
freeze matches the prior bridge. This corrects the target directly rather
than converting a ten-session log forecast. No model family, threshold,
stock, regime or favorable cost/window was selected from outcomes.

All 94 stocks and both ETFs are retained. The common completed-close anchor
is March 2, 2020; first official-open proxy fills are March 3. Final valuation
is September 30, 2026, with 1,654 measured return sessions. Each new book
starts NAV1 and carries funded cash, shares, basis and profit. No same-plan
sale proceeds fund buys. Prices and fractional shares are adjusted synthetic
units. Cash yield is zero. Exactly three new books were run; fifteen saved
bridge/past-mean/rule/ETF controls were authenticated and reused without
refitting their models or replaying their accounts.

| Cost per side | Book | Net gain | CAGR | Drawdown loss | Sharpe | Gross trading / year |
|---|---|---:|---:|---:|---:|---:|
| 0bp | Direct learned | 749.92% | 38.55% | 35.83% | 1.26 | 89.20 |
| 0bp | Affine bridge | 537.66% | 32.61% | 41.17% | 1.01 | 34.04 |
| 0bp | Past mean | 625.74% | 35.25% | 47.68% | 1.06 | 16.53 |
| 0bp | Grade equal | 547.68% | 32.93% | 47.50% | 1.01 | 25.75 |
| 0bp | SPY | 171.00% | 16.40% | 28.32% | 0.86 | 0.15 |
| 0bp | QQQ | 254.32% | 21.26% | 35.12% | 0.90 | 0.15 |
| 10bp | Direct learned | 296.40% | 23.35% | 38.84% | 0.87 | 66.14 |
| 10bp | Affine bridge | 186.42% | 17.39% | 36.70% | 0.68 | 13.81 |
| 10bp | Past mean | 134.51% | 13.87% | 30.76% | 0.71 | 8.55 |
| 10bp | Grade equal | 447.18% | 29.56% | 48.68% | 0.94 | 25.74 |
| 10bp | SPY | 170.73% | 16.39% | 28.32% | 0.86 | 0.15 |
| 10bp | QQQ | 253.97% | 21.24% | 35.12% | 0.90 | 0.15 |
| 25bp | Direct learned | 280.89% | 22.60% | 40.27% | 0.85 | 42.16 |
| 25bp | Affine bridge | 91.75% | 10.43% | 39.45% | 0.58 | 4.81 |
| 25bp | Past mean | 0.00% | 0.00% | 0.00% | Unavailable | 0.00 |
| 25bp | Grade equal | 325.00% | 24.66% | 50.41% | 0.82 | 25.72 |
| 25bp | SPY | 170.32% | 16.36% | 28.32% | 0.86 | 0.15 |
| 25bp | QQQ | 253.44% | 21.21% | 35.12% | 0.90 | 0.15 |

Costs affect optimized targets as well as paid fees. Differences between
cost books are not isolated fee drag. Gross trading is total buys plus sells
divided by contemporaneous NAV, annualized by 252 sessions. The direct
zero-cost book trades 89.20 times NAV per year versus the rule’s 25.75.
This conflicts with the intended low-turnover personal portfolio use.

Every predeclared direct window follows. Differences are percentage points
of cumulative gain on matched dates and carried starting wealth. The nominal
2018–20 window starts in March 2020; earlier support is unavailable. The
recent 32-session window was reused, not an untouched holdout.

| Cost | Window | Net gain | vs rule | vs bridge | vs past mean | vs SPY | vs QQQ |
|---|---|---:|---:|---:|---:|---:|---:|
| 0bp | all | 749.92% | 202.24pp | 212.26pp | 124.18pp | 578.92pp | 495.60pp |
| 0bp | 2018_2020 | 33.36% | -15.00pp | -1.69pp | -4.61pp | 10.30pp | -11.97pp |
| 0bp | 2021_2026 | 537.31% | 200.76pp | 165.14pp | 111.31pp | 417.09pp | 393.51pp |
| 0bp | reused_2026_08_17_09_30 | 16.64% | 9.60pp | 7.07pp | 6.97pp | 18.16pp | 15.35pp |
| 10bp | all | 296.40% | -150.78pp | 109.98pp | 161.89pp | 125.68pp | 42.44pp |
| 10bp | 2018_2020 | 11.94% | -32.78pp | 3.26pp | 10.65pp | -11.00pp | -33.25pp |
| 10bp | 2021_2026 | 254.13% | -23.96pp | 90.59pp | 122.61pp | 133.91pp | 110.33pp |
| 10bp | reused_2026_08_17_09_30 | 16.13% | 9.61pp | 6.71pp | 8.36pp | 17.65pp | 14.83pp |
| 25bp | all | 280.89% | -44.12pp | 189.14pp | 280.89pp | 110.56pp | 27.45pp |
| 25bp | 2018_2020 | 10.89% | -28.55pp | 3.34pp | 10.89pp | -11.86pp | -34.08pp |
| 25bp | 2021_2026 | 243.49% | 38.68pp | 165.20pp | 243.49pp | 123.27pp | 99.68pp |
| 25bp | reused_2026_08_17_09_30 | 14.91% | 9.19pp | 6.39pp | 14.91pp | 16.43pp | 13.61pp |

| Cost | Rolling 252-session wins vs rule | vs SPY | vs QQQ | Windows |
|---|---:|---:|---:|---:|
| 0bp | 57.88% | 79.69% | 77.41% | 1403 |
| 10bp | 44.55% | 58.16% | 57.80% | 1403 |
| 25bp | 54.10% | 52.46% | 53.74% | 1403 |

The adjacent JSON preserves the original full report and independent proof:
all fixed cost/window cells, fees, exposure, counts, all 94 stock profit
contributions and unchanged saved control identities. Overlapping rolling
windows are not independent trials. Neither the favorable zero-cost result
nor the stronger 2021–26 period justifies selecting a production regime.

VERIFIED: 39 native and 39 pinned-image source checks at 925ab0e9; after the
metadata-envelope correction, all six CLI checks pass natively and in the
pinned image at e093cd51. Exact manifest comparison confirms the other 33
model checks exercise unchanged source. There are no skips. The independent
saved-only verifier passed 23 native and 23 image corruption/acceptance cases.
It checked 141 monthly receipts, 79 numeric model heads and their exact
prediction bytes without estimator.predict or fitting. All three new books
and their complete scores reconcile: 4,965 plans, 21,045 intents, 18,696 fully
filled, 2,349 cash-limited, zero missing-open intents and 30 explicit allocator
unavailable plans. Cash-limited includes partial or unfunded requests.
Cash, covered quantities, fees, basis, realized/unrealized profit, NAV,
eligibility, moments and global convex certificates are checked. The verifier
authenticates fifteen old controls without repeating their account audits
or replay. It verifies recorded targets, not the unsaved solver iteration path.

FAILED: a total-gain advantage over the daily rule at both positive costs.
UNVERIFIED: a reliable full live-policy replacement, actual broker fills or
precise intraday execution. Historical grades and universe are current-vintage
reconstruction. The rule comparator is its daily target component, not the
full live rotation/FOMC/intraday path. Official opens are proxies; the recent
window was already inspected in prior research. One-session log covariance
is a declared approximation to arithmetic conditional risk. Production policy,
UI, data and model services remain unchanged.

The next bounded implementation should address forecast uncertainty and
unnecessary rebalancing, with a frozen causal protocol and all original
cost/control cells retained. Do not repeat completed fits/accounts, tune a
percentage barrier from these outcomes or promote the candidate automatically.

The first 925ab0e9 producer failed before fitting/output creation because the
original metadata stores features under identity.features. The real envelope
was reproduced in the fixture and only that loader boundary was corrected.
Failed source/container/log are preserved separately. Corrected model, target,
configuration and support remain unchanged.

Report SHA256: `764e8e6489325bf84d515ae2acc000bdebe41a2b539e59df1dce274950e8fc0a`.
Independent proof SHA256: `8c8bbe09871d4e1ae3a87ecf306d135f80c330a111edee4bb1664d3b2ecb7017`.
Source manifest SHA256: `afec6a579e835989f99d914c30955f88c28678c91186fc835b66e7a93ac9b8a3`.
Verifier SHA256: `b3325dbf5b067fad815202aaf55949bb221abbbca747ef9e5e88160b82b252d6`.
Published JSON SHA256: `a0c27074af91b18f75e29ae3735758fd4038f874c9dd3ee8912d3b987c1ec87c`.

Producer2812602f005eb6ae5cee4e19392b31e9fb40f6b5cde3846c690ec4b0a365595d
and proofaa60f618374fa756013cc820c434187f8a7b6c251df292bf89f3db3cf7855d4b
both exited0. Never restart either.

Study: `/home/animallya96/scratch/direct-daily-arithmetic-results-20261003-e093cd51/study`.
Proof: `/home/animallya96/scratch/direct-daily-arithmetic-verification-20261003-e093cd51/proof/proof.json`.
Diagram impact: NONE; the methods remain within existing research,
carried-account and artifact-verification boundaries.
