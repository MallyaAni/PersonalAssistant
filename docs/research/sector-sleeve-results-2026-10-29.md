# C5 sector-rotation sleeve: failed gate on the honest PIT universe (2026-10-29)

**Status: FAILED and closed.** The pre-registered gate fails on G1, G2 and G4;
G3 and G5 pass. The sleeve is not added to the live book, no separate mandate is
opened, and the arm is closed. The live rule stays frozen through the
252-session review; nothing here is a live change.

## What ran

- Pre-registration:
  `docs/research/sector-sleeve-preregistration-2026-10-29-current-baseline.md`,
  committed `7cc9855a`, before the first run. It is the same C5 as `7ebe6acb`
  with the live-book baseline reference moved to the current panel's
  installed-rule baseline (`sector-sleeve-baseline-stop-2026-10-29.md`,
  committed `7c1e2f98`); the sleeve, costs, starts, placebo and gate are
  unchanged.
- Runner: `~/dsv41/pit2/sector_sleeve.py`; payload
  `~/dsv41/pit2/sector_sleeve.json`; log `~/dsv41/pit2/sector_sleeve.log`.
- PIT cache: `~/dsv41/pit2/cache.npz`, 532 tickers, 2,970 sessions
  2015-01-02..2026-10-23. Coverage passed: 142 month-ends, minimum priced
  members 12 (Communication Services), zero thin months in every sector.
- Live book: the current `desk.run` panel, 95 names, the installed `Rule()` at
  10 bp. The baseline reproduces the current-panel reference in
  `~/dsv41/pit2/sector_sleeve_stop_2026-10-29.json` exactly (maximum
  difference 0.0).
- Starts: 19, 2016-01-04..2016-01-29. January 2016 has 19 cache sessions, so
  the pre-registered 20 start offsets are the 19 January sessions; the first
  rebalance is 2016-01-29.

## The gate

| Gate | Test | Result |
|---|---|---|
| G1 | combined 80/20 Sharpe > live-book Sharpe at 25 bp, both windows | **fail** (1.1014 vs 1.1418 choosing; 1.3940 vs 1.4403 reported) |
| G2 | sleeve/live monthly correlation < 0.5, both windows | **fail** (0.6739 choosing, 96 months; 0.5652 reported, 130 months) |
| G3 | sleeve max drawdown no deeper than SPY, both windows | pass (−32.45% vs −33.72%) |
| G4 | sleeve Sharpe at 25 bp, 2016-2023 > 95th percentile of 200 placebo sleeves | **fail** (0.4555 vs 0.6775; placebo median 0.4403, best 0.7809) |
| G5 | sleeve CAGR at 25 bp > 0, both windows | pass (4.79%, 5.41%) |

Any failure records the result and stops the arm; three of the five failed.

## Results

| Series | 2016-2023 CAGR | DD | Sharpe | Total | 2016-2026 CAGR | DD | Sharpe | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sleeve 25 bp | 4.79% | −32.45% | 0.4555 | +45.05% | 5.41% | −32.45% | 0.5072 | +76.21% |
| Sleeve 10 bp | 5.43% | −31.49% | 0.5072 | +52.23% | 6.03% | −31.49% | 0.5567 | +87.56% |
| SPY | 13.37% | −33.72% | 0.7748 | +172.25% | 14.96% | −33.72% | 0.8775 | +349.55% |
| Equal-weight sectors | 14.42% | −38.94% | 0.8044 | +193.08% | 14.48% | −38.94% | 0.8533 | +329.57% |
| Live book | 25.57% | −28.02% | 1.1418 | +515.27% | 37.40% | −28.02% | 1.4403 | +2,975.41% |
| Combined 80/20 | 21.38% | −24.63% | 1.1014 | +369.44% | 30.71% | −24.63% | 1.3940 | +1,694.49% |

The start-offset range at 25 bp is 4.67-4.82% CAGR and 0.4454-0.4570 Sharpe
choosing, 5.32-5.44% and 0.4999-0.5084 reported. The 80/20 combination lowers
the drawdown by 3.4 pp in both windows but lowers the Sharpe, so it does not
improve the live book.

## Why

- On its own the sleeve is weak: 0.4555 Sharpe at 25 bp against SPY's 0.7748 and
  the equal-weight sectors' 0.8044. The 10% volatility target holds a mean scale
  of 0.653 (min 0.175), so it sits in cash much of the time and still draws down
  −32.45%, barely better than SPY's −33.72%.
- The momentum ranking adds almost nothing. The real Sharpe is +0.015 above the
  placebo median and 0.22 below the placebo 95th percentile; random sector
  selection with the same scale, cash and cost mechanics performs about as well.
  Most of the sleeve's return is the sector beta and the cash/scale timing, not
  the ranking.
- The sleeve correlates 0.6739 (choosing) and 0.5652 (reported) with the live
  book, above the 0.5 bar. It is another long-equity, tech-heavy exposure, not a
  diversifier.
- The 80/20 combination buys a shallower drawdown but not a better Sharpe, so
  G1 fails in both windows.

## Diagnostics (reported, not gated)

- Cash months: 2. Scale: mean 0.653, min 0.175, max 1.0. Turnover: mean 0.320,
  total 41.55. Cost at 25 bp: mean 0.0799% per month, total 10.39% of capital
  over the run.
- Yearly returns (mean sleeve path): 2016 +14.77%, 2017 +21.17%, 2018 −6.62%,
  2019 −1.32%, 2020 −3.07%, 2021 +14.67%, 2022 −5.14%, 2023 +7.37%, 2024
  +9.84%, 2025 +1.10%, 2026 +9.40%.
- 12-month signal: 6.13% CAGR, −23.70% drawdown, 0.5595 Sharpe, +60.38% total
  choosing; 8.54%, −23.70%, 0.7594, +141.26% reported. Better than the 6-month
  sleeve but still below SPY (0.7748/0.8775); it is a diagnostic, not gated.
- Top-3: 4.28% CAGR, −30.94% drawdown, 0.4140 Sharpe, +39.52% total choosing;
  5.20%, −30.94%, 0.4909, +72.38% reported. Worse than top-2, so more names did
  not help.
- The sector basket returns and momentum ranks at each month-end are in the
  payload.
- Perturbation: 100/100 momentum values identical, 100/100 top-2 selections
  identical, 98/98 forward returns changed where a next month-end exists,
  100/100 selections changed when one sector's momentum is raised by +1; the
  look-ahead control passes.

## The 12-month diagnostic bug and the re-run

The first run's 12-month diagnostic returned all zeros. The 12-month signal's
first valid month-end is 2016-02-29, after the first rebalance 2016-01-29, and
the equity path was initialized to cash only through the first rebalance, so the
first record read NaN and the whole path stayed NaN. The fix starts the path at
the later of the first rebalance and the first valid month-end. The primary
sleeve and the gate are unchanged: the corrected re-run reproduces the primary
choosing metrics exactly (4.7928% CAGR, −32.4462% drawdown, 0.45548 Sharpe,
0.450516 total) and the same gate. This is a diagnostic-path fix, not a
parameter change; the pre-registration is unchanged.

## What this does not change

- The live rule stays frozen through the 252-session review; no live change, no
  order, no position, no prompt.
- The sleeve's returns are never spliced into the live book's record; the 80/20
  was a portfolio diagnostic only.
- The C5 arm is closed. It is not retried with a different signal length,
  top-N, volatility target, sector cap, universe, rebalance frequency or cost
  without a new pre-registration saying what changed and why.
- The PIT sector baskets and their coverage remain valid and can be reused by a
  future pre-registration.
- The owner's decision on a separate sector mandate is not bought.

## Artifacts

- Pre-registration: `docs/research/sector-sleeve-preregistration-2026-10-29-current-baseline.md`,
  committed `7cc9855a`; original `docs/research/sector-sleeve-preregistration-2026-10-29.md`,
  committed `7ebe6acb`; stop note
  `docs/research/sector-sleeve-baseline-stop-2026-10-29.md`, committed `7c1e2f98`.
- Runner: `~/dsv41/pit2/sector_sleeve.py`; payload
  `~/dsv41/pit2/sector_sleeve.json`; log `~/dsv41/pit2/sector_sleeve.log`.
- Reference baseline: `~/dsv41/pit2/sector_sleeve_stop_2026-10-29.json`.
- Runtime: 250.8 s (corrected re-run); the first run was 265.5 s.

## The one number

The real sleeve's 25 bp Sharpe is **0.4555** against a placebo median of
**0.4403** and a 95th percentile of **0.6775**, and the combined 80/20 Sharpe is
**1.1014 / 1.3940** against the live book's **1.1418 / 1.4403**. The sleeve
fails.
