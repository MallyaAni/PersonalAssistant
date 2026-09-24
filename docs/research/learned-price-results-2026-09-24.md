# Learned price study and nightly neural audit — 2026-09-24

## Decision

Keep the live rule. The new gradient-boosted ranker is not promoted: it underperformed the fixed momentum comparator, suffered deeper drawdowns and traded roughly twice as much. The learned brake reduced drawdown modestly but also reduced return. No retuning on this study.

This is a conditional retrospective price study of the September 23 current book, not a historical reconstruction of the live strategy. Survivor selection and later price vintages limit the large reported returns. Grades, earnings tone and historical membership are unavailable; the full live incumbent remains UNVERIFIED.

## Provenance and failure retained

Models were fit once at source `8f36135` with the protocol frozen before outcomes. September 23 cached histories omit September 22 for 52 of the 96 selected stock/ETF names. The full-window run FAILED and remains preserved. Before stock metrics were emitted, amendment `1753a6e` declared a mechanical cutoff at the first missing source session; the complete common prefix ends September 21. No names were removed and no prices, models or forecasts were refetched, refit or repaired.

Minimum training history delays the common start to March 26, 2019. Thus the requested 2016–20 split has only March 2019–December 2020 evidence. The August 3–September 21 holdout contains 35 return intervals; every label ending on/after August 3 was withheld, including at later refits. Both holdout monthly rank fits have the same training digest. These recent dates appeared in prior research, so this is not a pristine unseen holdout.

All paths use NAV1, zero cash yield, next-open execution, a common calendar, 20-session composition cadence and the existing funded execution engine. Sale proceeds cannot finance another purchase at the same open; one next-session retry is allowed. Costs below are one-way basis points, not Schwab commissions. Turnover is annual traded dollars/NAV. Rolling wins compare 252-session windows. These conventions do not prove midpoint fills.

Artifacts: `/home/animallya96/anios/data/market/research/learned-price-20260924/` contains the original failed report, source hashes, frozen arrays, fits and `valid-prefix/results.json`. The companion checked-in JSON preserves every metric and missing-symbol name.

## Complete common prefix — 10 bp

| Policy | CAGR | Max drawdown | Sharpe | Turnover/year | Rolling wins SPY / QQQ | Holdout return |
|---|---:|---:|---:|---:|---:|---:|
| momentum120 | 70.5% | -46.6% | 1.35 | 9.33 | 82.6% / 82.2% | 28.8% |
| learned_rank | 48.7% | -57.9% | 1.10 | 19.48 | 75.2% / 73.5% | 6.0% |
| momentum120_learned_brake | 68.9% | -44.6% | 1.38 | 9.50 | 84.5% / 80.4% | 17.3% |
| learned_rank_learned_brake | 47.7% | -53.1% | 1.12 | 18.88 | 75.2% / 70.0% | -1.6% |
| momentum120_fixed_brake | 63.1% | -44.7% | 1.32 | 8.86 | 81.8% / 78.8% | 28.8% |
| equal | 39.5% | -38.6% | 1.27 | 0.50 | 82.1% / 83.0% | 9.9% |
| SPY | 16.2% | -33.7% | 0.87 | 0.13 | 0.0% / 30.2% | 3.8% |
| QQQ | 21.7% | -35.1% | 0.94 | 0.13 | 69.8% / 0.0% | 7.9% |

| Policy | 2016–20 available CAGR / DD / Sharpe | 2021–26 CAGR / DD / Sharpe |
|---|---:|---:|
| momentum120 | 42.4% / -37.8% / 1.12 | 80.4% / -46.6% / 1.42 |
| learned_rank | 40.1% / -49.1% / 1.13 | 51.5% / -57.9% / 1.10 |
| momentum120_learned_brake | 35.1% / -37.8% / 1.01 | 81.0% / -44.6% / 1.48 |
| learned_rank_learned_brake | 38.1% / -49.1% / 1.10 | 50.9% / -53.1% / 1.13 |
| momentum120_fixed_brake | 39.0% / -32.0% / 1.14 | 71.4% / -44.7% / 1.37 |
| equal | 44.6% / -35.1% / 1.34 | 37.9% / -38.6% / 1.25 |
| SPY | 19.6% / -33.7% / 0.81 | 15.2% / -24.5% / 0.93 |
| QQQ | 37.9% / -28.6% / 1.27 | 17.0% / -35.1% / 0.81 |

## Complete common prefix — 25 bp

| Policy | CAGR | Max drawdown | Sharpe | Turnover/year | Rolling wins SPY / QQQ | Holdout return |
|---|---:|---:|---:|---:|---:|---:|
| momentum120 | 68.2% | -47.0% | 1.32 | 9.32 | 82.1% / 80.1% | 28.6% |
| learned_rank | 44.4% | -58.6% | 1.04 | 19.47 | 73.6% / 70.0% | 5.5% |
| momentum120_learned_brake | 66.5% | -44.8% | 1.35 | 9.49 | 83.1% / 78.4% | 17.1% |
| learned_rank_learned_brake | 43.6% | -53.9% | 1.05 | 18.88 | 72.8% / 66.5% | -2.1% |
| momentum120_fixed_brake | 60.9% | -45.0% | 1.29 | 8.85 | 80.9% / 76.8% | 28.6% |
| equal | 39.5% | -38.8% | 1.27 | 0.50 | 82.0% / 82.4% | 10.1% |
| SPY | 16.2% | -33.7% | 0.87 | 0.13 | 0.0% / 30.2% | 3.8% |
| QQQ | 21.6% | -35.1% | 0.93 | 0.13 | 69.8% / 0.0% | 7.9% |

| Policy | 2016–20 available CAGR / DD / Sharpe | 2021–26 CAGR / DD / Sharpe |
|---|---:|---:|
| momentum120 | 40.4% / -37.8% / 1.08 | 77.9% / -47.0% / 1.39 |
| learned_rank | 36.0% / -49.2% / 1.04 | 47.1% / -58.6% / 1.04 |
| momentum120_learned_brake | 33.0% / -37.8% / 0.96 | 78.6% / -44.8% / 1.45 |
| learned_rank_learned_brake | 34.0% / -49.2% / 1.02 | 46.7% / -53.9% / 1.07 |
| momentum120_fixed_brake | 36.9% / -32.2% / 1.09 | 69.2% / -45.0% / 1.34 |
| equal | 44.4% / -35.1% / 1.34 | 38.0% / -38.8% / 1.25 |
| SPY | 19.5% / -33.7% / 0.81 | 15.2% / -24.5% / 0.93 |
| QQQ | 37.8% / -28.6% / 1.26 | 17.0% / -35.1% / 0.81 |

## Separate frozen neural nightly experiment

The existing frozen neural network is different from the new gradient-boosted ranker. Its saved September 15 decision filled at the September 16 close; September 22 is its latest mark. Six saved input hashes and prediction arrays reproduce exactly, and all ten accounts (five policies at 10/30 bp) replay exactly from the immutable journal. Every original journal hash remained unchanged. This proves arithmetic and recorded inference, not external price accuracy or future profitability.

| Existing shadow | Return at 10 bp | Return at 30 bp |
|---|---:|---:|
| Neural | 15.84% | 15.60% |
| Valuation rule | 12.01% | 11.78% |
| Momentum20 | -0.20% | -0.40% |
| SPY | 2.46% | 2.26% |
| Cash | 0% | 0% |

These are one basket and four post-fill daily return intervals, not a matured 20-session forecast or an annualized result. Neural gains span all ten names; ARM contributes 3.65 percentage points, followed by GLXY 2.20 and CRDO 1.92. The portfolio remains concentrated in related growth exposures. The neural and momentum20 baskets share no names at this decision, which shows different selections but does not establish independent risk or a better blend.

The September 23 nightly log explicitly stopped this experiment at its code-identity guard, before appending a row. The already-deployed migration declares that unchanged-model continuation; this audit does not manufacture the missed observation. Separately, missing September 22 source bars can prevent marking a held position. The new snapshot guard reproduces the ACN omission from stored bytes, retries once, rejects it and leaves source bytes unchanged.

## Combination decision

Do not fit a scenario selector from four daily returns, switch to the recent winner, or change the frozen neural experiment. A fixed 50/50 neural/momentum blend is the appropriate control before a learned selector: weights must be declared before a new forward observation, with a separate ledger and the same execution assumptions. It is not implemented or recommended live by this audit. Scenario selection needs multiple matured, non-overlapping decision cohorts and purged training with only then-known regime features; compare it to both component policies, the fixed blend, SPY and QQQ at equal exposure and costs. The full live incumbent must also be recorded on the same decision clock before claiming live improvement.

VERIFIED: saved inference/accounting replay, conditional model comparison, purged holdout boundary and snapshot rejection. FAILED: full requested history completeness. UNVERIFIED: superior live policy, scenario selector, actual fills and the next ordinary nightly continuation.
