# The installed rule on the account-faithful simulator (2026-10-24)

## Why a new engine

The strategy charts, the scorecard and the live account disagreed:

- The scorecard graded with the research fundamentals mode (`corrected`); the
  nightly grades with `current`. They differ in 17,201 of 282,150 name-sessions,
  8,264 of them across the B line.
- The scorecard arm caps before the volatility scale and reads 250 returns for
  its EWMA; the live `leader_weights` caps after and reads 63.
- Neither modelled the band buy block, the FOMC cycle, whole shares or the
  funded planner's rule that buys are paid from the cash on hand before the
  day's sells.

`backend/market/policy_book.py` runs the policy as the paper account does, and
the strategy charts now draw its fills, so the backtest, the chart and the live
rule are one calculation. Variants are `Rule` parameters.

## Method

Desk report in the nightly's mode over today's 94 names, 2015-01-02 to
2026-10-23; $100,000 start; a name is sizable from its first 64-close window.
Rules were compared on 2015-2022 and checked on 2023-2026; a candidate had to
lead in both and keep its worst drawdown no deeper than the installed rule's
scorecard figure (about -34%). Scripts: `~/dsv41/book/run.py`, `cache.py`,
results `~/dsv41/book/out_*.json`, `final.json`.

## Results (10 bp unless noted)

These figures are on the grades as first computed. A look-ahead in the share
counts behind the valuation inputs was found and fixed the same day
(`docs/research/pe-history-tilt-2026-10-24.md`); on corrected grades, with the
simulator's rounding matched to the live planner, the chosen rule earns 34.9%
a year at -28.3% (to 2022 19.0%, after 74.2%) against 31.5% at -30.0% for the
B rule (16.4%, 68.7%), still ahead in both windows.

| Rule | CAGR | Worst drawdown | Sharpe | 2015-22 | 2023-26 | Fills |
|---|---|---|---|---|---|---|
| Installed: enter and hold at B | 34.0% | -29.5% | 1.39 | 19.8% | 68.5% | 82,446 |
| B, 0.5% minimum trade | 34.7% | -29.3% | 1.41 | 20.4% | 69.3% | 16,039 |
| B, exit after 2 sessions below B | 33.0% | -30.1% | 1.36 | 18.6% | 68.3% | 85,427 |
| B, no band block | 34.5% | -29.7% | 1.40 | 19.6% | 70.8% | 85,370 |
| Enter and hold at A | 37.1% | -31.6% | 1.44 | 23.1% | 70.8% | 34,829 |
| Enter at A+, hold at A | 39.3% | -30.8% | 1.49 | 21.1% | 85.2% | 16,424 |
| Enter at A, hold at B | 37.9% | -27.9% | 1.48 | 24.3% | 70.4% | 54,751 |
| **Enter at A, hold at B, 1% minimum trade** | **39.4%** | **-26.9%** | **1.51** | **25.0%** | **74.4%** | **6,703** |
| same, 0.25% / 0.5% / 2% minimum trade | 38.2-39.6% | -27.6 to -29.5% | 1.48-1.49 | 24.4-24.6% | 71.4-76.4% | 3,073-24,483 |
| same, floor 0.65 (0.5% trade) | 40.0% | -27.8% | 1.48 | 25.1% | 75.9% | 13,632 |
| A, volatility target 0.30 | 39.3% | -35.7% | 1.41 | 24.2% | 76.3% | 34,665 |
| Installed at 25 bp | 29.9% | -31.1% | 1.25 | 16.0% | 63.7% | 81,489 |
| **Chosen at 25 bp** | **37.6%** | **-27.7%** | **1.46** | **22.9%** | **73.2%** | 6,658 |
| SPY | 13.8% | -33.7% | | | 21.3% | |

By year, chosen against installed: 2016 10.7 / 12.1, 2017 44.9 / 38.7,
2018 30.6 / 10.3, 2019 37.0 / 30.3, 2020 48.3 / 42.5, 2021 45.5 / 51.5,
2022 -15.6 / -21.5, 2023 71.2 / 78.4, 2024 81.2 / 69.6, 2025 65.0 / 66.2,
2026 61.0 / 44.1.

The book holds 20 names on average (7 to 33) against 31, makes about 63
entries a year against 184, and stays 85% invested, the same as before: the
B entries it gives up were mostly short round trips that lost money.

## Caveats

In-sample: today's names, chosen partly because they rose; grading weights
(value at three votes) chosen on this history. The return figures are
optimistic in level; the comparison between rules on the same names is the
evidence. The minimum-trade level and the floor sit on a flat plateau, so the
choice among them is not a fit.
