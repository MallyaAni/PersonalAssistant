# SUE rank-IC study on the honest PIT universe: result (failed)

**Status: FAILED the pre-registered gate at both horizons.** The SUE arm is closed;
no selection overlay is pre-registered and no live change follows. The study was
pre-registered in `sue-rank-ic-preregistration-2026-10-29.md` (committed `9a2d9f04`)
before the first run. This is an association result, not a trading result: no costs,
no portfolio, no live use.

## What ran

- PIT cache: `~/dsv41/pit2/cache.npz`, 532 tickers, 2,970 sessions
  2015-01-02..2026-10-23. The `member` matrix is the session-level membership;
  `adj_close` is the split-adjusted close; `grades` is the installed rule's grade,
  used only for a diagnostic; `sector` is the sector label.
- Filings: the store's `edgar_facts_versions` frames, read with
  `fundamentals_asof.versions_from_frame`. Primary `net_income`; diagnostic `eps`.
  The five foreign private issuers (ASML, FDXF, NBIS, SIMO, TSM) are excluded from
  the primary sample and stay in the denominator; SPY is the benchmark and has no
  frame. Net income produced 25,395 SUE observations across 521 names; EPS produced
  23,801 across 510. The zero/non-finite standard-deviation share was 0.0% for net
  income and 0.004% for EPS, far below the 10% stop.
- Signal: the earliest filing per period end, quarter spans only; the seasonal change
  `E_q - E_{q-4}`; the SUE is that change divided by the sample standard deviation
  (ddof=1) of the prior four seasonal changes. The decision date is the first cache
  session at or after `Version.available`; the SUE is usable from that session.
- Monthly cross-section: the last cache session of each month, January 2016 through
  October 2026. PIT members with a SUE whose decision date is within the prior 60
  sessions and a finite `adj_close` at the signal date and at `t+h`. If a name has
  more than one SUE in the window, the latest period end wins. Forward return
  `adj_close[t+h]/adj_close[t] - 1`, h = 20 and 60. Rank IC is the Spearman
  correlation across the cross-section; months below 50 names are excluded from the
  mean (none were).
- Placebo: 200 permutations of the SUE values across names within each month's
  cross-section, seeds from RNG 20261029. Block bootstrap: 2,000 draws resampling
  calendar months. Perturbation: 100 sampled (name, signal date) pairs.

## Gate

| Horizon | G1 pooled mean IC (95% CI) | G2 placebo 95th (median) | G3 positive years | Verdict |
|---|---|---|---|---|
| 20 sessions | **−0.0071** [−0.0286, +0.0119] | +0.0104 (+0.0003) | **3 of 8** | **FAIL** |
| 60 sessions | **−0.0168** [−0.0408, +0.0057] | +0.0105 (+0.0002) | **3 of 8** | **FAIL** |

The pooled mean is negative at both horizons and its interval spans zero, so G1 fails.
The real mean is below the placebo median at both horizons, so G2 fails: a shuffle of
the SUE values across names does at least as well. Only 2017, 2018 and 2019 are
positive at 20 sessions (2017, 2019 and 2023 at 60), so G3 fails. The 2016-2026
reported window does not change the picture: −0.0030 [−0.0205, +0.0140] at 20 and
−0.0101 [−0.0303, +0.0091] at 60.

## Yearly mean monthly IC

| Year | 20 sessions | 60 sessions | Months |
|---|---:|---:|---:|
| 2016 | −0.0497 | −0.0877 | 12 |
| 2017 | +0.0187 | +0.0366 | 12 |
| 2018 | +0.0129 | −0.0041 | 12 |
| 2019 | +0.0097 | +0.0191 | 12 |
| 2020 | −0.0187 | −0.1249 | 12 |
| 2021 | −0.0156 | −0.0031 | 12 |
| 2022 | −0.0134 | −0.0167 | 12 |
| 2023 | −0.0011 | +0.0462 | 12 |
| 2024 | +0.0282 | +0.0469 | 12 |
| 2025 | +0.0122 | −0.0227 | 12 |
| 2026 | −0.0223 | +0.0095 | 8 / 6 |

The positive years do not persist: after the 2017-2019 run, 2020-2022 are negative at
both horizons and 2023 is negative at 20 and positive at 60; 2024-2025 turn positive
again after the gate window. That is the pattern of a signal that is not stable, not
one that is merely noisy.

## Event-based diagnostic (reported, not gated)

For each SUE observation, the event name's percentile rank of its SUE among the
same 60-session cross-section, against the forward return from the event date's close:
11,124 events in 2016-2023 give an IC of −0.0076 at 20 sessions and −0.0053 at 60;
15,011 / 14,722 events in 2016-2026 give −0.0033 and −0.0002. The direct PEAD event
test is flat, with the same slightly negative sign. It cannot rescue the monthly gate.

## Diagnostics (reported, not gated)

- **EPS-based SUE:** pooled 2016-2023 −0.0037 [−0.0234, +0.0139] at 20 and −0.0162
  [−0.0392, +0.0059] at 60; the yearly pattern is similar to net income. The
  secondary measure does not add a positive result.
- **Sector-neutral IC:** −0.0062 at 20 and −0.0063 at 60. Within sectors the
  association is negative, so the raw result is not hiding a sector-level edge.
- **Momentum control:** the mean Spearman correlation between the SUE and the prior
  120-session momentum is +0.1401 at 20 and +0.1387 at 60; within momentum terciles
  the mean IC is −0.0007 and −0.0116. The SUE is partly a momentum proxy, and once
  momentum is held fixed it has no positive association.
- **Grade diagnostic:** the mean correlation between the SUE and the installed grade
  is +0.0587 / +0.0579; among names graded A/A+ (where the live rule buys) the mean IC
  is −0.0036 / −0.0025. No edge in the live entry set.
- **Cross-section size:** median 337 names at 20 and 335.5 at 60; minimum 101; no
  month below 50 (0/128 and 0/126). The fail is not a coverage artifact.
- **Staleness:** median 33.5 sessions, maximum 60. The signal is fresh.
- **Placebo:** 200 pooled means, median +0.0003 / +0.0002, 95th percentile +0.0104 /
  +0.0105, best draw +0.0179 / +0.0161.

## Look-ahead controls

- The SUE at a signal date uses only filings whose decision date is on or before the
  signal date; the forward return uses only prices after the signal date; membership
  is the PIT matrix at the signal date.
- Perturbation: 100 sampled (name, signal date) pairs; multiplying every `adj_close`
  after the signal date by a factor in [0.95, 1.05] leaves the SUE values and the
  cross-sectional SUE ranks identical (100/100); changing one SUE value by +1 changes
  the IC (100/100). The perturbation is ok.
- The study reads no live book, no order, no position, and no prompt.

## What this closes

- The C4 SUE rank-IC arm is closed. The gate failed at both horizons, so there is no
  selection-overlay pre-registration and no forward shadow.
- The arm is not retried with a different standard-deviation length, staleness limit,
  horizon, universe, earnings measure or cross-section definition without a new
  pre-registration saying what changed and why. The pre-registration's stop condition
  is explicit on this point.
- The result is a failure to demonstrate a positive association, not proof of a
  negative edge: both intervals span zero. But the gate asked for a positive,
  stable, placebo-beating association, and the data did not show one.
- The live rule stays frozen through the 252-session review. The C5 sector sleeve
  remains an owner decision; the P5 multi-class share-count gap is separate and
  unchanged.

## Artifacts

- Pre-registration: `docs/research/sue-rank-ic-preregistration-2026-10-29.md`,
  committed `9a2d9f04`.
- Runner: `~/dsv41/pit2/sue_rank_ic.py`; payload `~/dsv41/pit2/sue_rank_ic.json`;
  log `~/dsv41/pit2/sue_rank_ic.log`.
- Cache: `~/dsv41/pit2/cache.npz`; filings:
  `~/deploy/anios/data/market/edgar_facts_versions`.
- Spot checks: the manual AAPL SUE matches the runner exactly (59 observations, same
  values); the 2023-06-30 cross-section reproduces 427 names and IC −0.05968.

## The one number

Over 2016-2023 the SUE's mean monthly rank IC is **−0.0071 at 20 sessions and
−0.0168 at 60**, both 95% intervals spanning zero; the shuffle's median is +0.0003,
and only 3 of 8 choosing years are positive at either horizon. The SUE arm fails G1,
G2 and G3 and is closed.
