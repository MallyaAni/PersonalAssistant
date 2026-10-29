# 15-minute trend + VWAP-bounce overlay: result (fails the pre-registered gate)

**Status: FAILED the pre-registered gate. `trend-vwap-bounce/1` is closed and is not
retried.** This is the result of `vwap-bounce-overlay-preregistration-2026-10-28.md`,
run after the note was committed (`39d2de03`). Nothing changes in the live rule, the
board, or any prompt. The live rule stays frozen through the 252-session review.

## What ran

- 666 grade-A entries of the installed rule, 2016-02 to 2026-10; 666 scored (100%
  coverage), no unscored entries. The sample is exactly the one the chart-judgment
  study scored (`~/dsv41/vision/main.jsonl`); the 30-entry pilot and the 4 entries
  with no Alpaca bars at the time are excluded, and no new entries were added.
- Bars: Alpaca 15Min, split-adjusted, SIP 04:00-20:00 ET from 2016-01-01 and BOATS
  20:00-04:00 ET from 2024-09-16, merged and labelled as `chartlib.prepare`. The NVDA
  split check passed: 2024-06-07 close 120.87, 2024-06-10 open 120.35, ratio 0.9957.
- Rule `trend-vwap-bounce/1`: at a 15-minute bar close, EMA9 > EMA21; the previous bar
  closed above session VWAP; the current bar's low is at or below VWAP and its close
  is above VWAP. The first such bar in the window is the trigger. The fill is the open
  of the first bar starting at or after the trigger bar's end; baseline A is the open
  of the first regular bar of t+1. Costs are 5 bp regular, 15 bp pre-market and
  after-hours, 30 bp overnight; A pays 5 bp.
  `improvement_bp = 1e4 * (ln P_A - ln P_B) - (cost_B - cost_A)`.
- 648 entries triggered (97.3%); 18 were forced at the close of t+5. Mean bars waited:
  37.4. No model call and no prompt; the rule is fully mechanical.

## Gate

| Test | Result | Verdict |
|---|---|---|
| G1 mean improvement vs buying at the next open, after costs | −20.5 bp, median −32.2 bp, 95% CI [−43.9, +4.0] | **FAIL** |
| G2 beats a placebo that permutes trigger offsets across entries | B −20.5 vs placebo median −24.1, 90th pct −15.1 (best draw −6.0) | **FAIL** |
| G3 positive in both halves | 2016-20 −21.1 bp (n 295), 2021-26 −20.0 bp (n 371) | **FAIL** |

All three components fail, so the rule is closed.

## The decomposition

The registered mean is −20.5 bp, but the trigger is not what produces it:

- **648 triggered entries: mean −42.1 bp, median −34.2 bp, 198 of 648 positive.** When
  the rule actually fires, it buys worse than the next open.
- **18 forced entries: mean +756.9 bp, median +746.6 bp, 14 of 18 positive.** These are
  windows where price fell and never bounced off VWAP; the forced fill at the close of
  t+5 bought after the fall. The largest are PANW 2022-05-02 (+2,181.7 bp), NET
  2026-02-13 (+1,968.3 bp), WULF 2020-03-09 (+1,813.0 bp), COHR 2017-03-28 (+1,514.1
  bp), NET 2025-02-18 (+1,492.6 bp) and VRT 2024-07-31 (+1,474.2 bp).
- Excluding the 18 forced entries, the mean is −42.1 bp. The positive contribution is
  the forced fallback in falling windows, which is not a VWAP bounce; the trigger
  itself is negative.
- Costs: 499 regular, 120 pre-market, 25 overnight and 22 after-hours fills. The
  non-regular fills pay 10-25 bp more than A, about 3.1 bp of the −20.5 mean; the
  remaining roughly 17.4 bp is the price difference.
- The distribution is wide: 10th percentile −233.0 bp, 25th −106.3, median −32.2, 75th
  +29.8, 90th +200.4; 212 of 666 entries are positive and 13 are exactly zero. The
  trimmed mean dropping 1% from each tail is −25.3 bp.

## By year

| Year | Mean improvement (bp) | n |
|---|---:|---:|
| 2016 | −25.8 | 44 |
| 2017 | −21.6 | 42 |
| 2018 | −27.3 | 56 |
| 2019 | −2.4 | 57 |
| 2020 | −26.2 | 96 |
| 2021 | −64.5 | 58 |
| 2022 | −26.0 | 78 |
| 2023 | −62.3 | 73 |
| 2024 | −19.1 | 68 |
| 2025 | −21.9 | 52 |
| 2026 | +126.7 | 42 |

Ten of eleven years are negative. The 2026 cell is outlier-driven: median 0.0, 20 of
42 positive, and the forced NET entry contributes +1,968 bp; excluding 2026 the mean is
−30.4 bp. The pre-registration called 2026 informational; it does not change the gate.

## Placebo

The 50 placebo means are all negative (range −56.6 to −6.0, median −24.1, 90th
percentile −15.1). The trigger is about 3.6 bp better than the median random offset but
5.4 bp worse than the 90th percentile and 14.5 bp worse than the best draw. The
chart-specific trigger adds some information relative to a random offset, but not
enough to beat the top decile. The delay itself is costly in this sample: the grade-A
windows drift up, so the next open is usually the better price.

## Diagnostics (reported, not gated)

- Trend-only (EMA9 > EMA21 and close > VWAP, without the bounce conditions): −16.1 bp.
- VWAP-limit-in-uptrend (a limit at VWAP for the next bar, re-placed at every bar
  close): −14.9 bp.
- The chart-judgment mechanical comparators were +5.0 bp (limit at session VWAP) and
  +5.2 bp (hourly EMA21), and the model scored +3.0 bp. Those comparators used the
  chart-judgment checkpoint schedule and limit rule; the diagnostic here re-places a
  limit at VWAP at every 15-minute bar in an uptrend, so it is not the same rule. It
  is reported as registered, and it is worse.
- B-veto: the 18 never-triggered entries' 20- and 60-session forward returns from A's
  fill are −724.2 bp and −1,129.6 bp; the triggered entries' are +249.4 bp and
  +672.6 bp. The trigger fires in rising windows and the forced fallback in falling
  ones; this is a selection effect, not evidence that the trigger improves the entry
  price.

## Look-ahead controls

- Perturbation: 100 sampled triggers, 100 unchanged after multiplying every bar
  starting at or after the trigger bar's end by a random factor in [0.95, 1.05]; 100
  changed after a +1% close edit; 0 reproduction failures.
- Visibility: the indicator at bar i reads only bars with `end <= end(i)`; the fill
  reads only bars starting at or after `end(i)`; the forced fill reads only bars in
  the window.
- Split check passed as above. The bars were fetched fresh from Alpaca with
  `adjustment=split` for this run; the deploy bar stores were not used because they
  are unadjusted and split regular/extended.

## What this closes

`trend-vwap-bounce/1` is closed. The pre-registration forbids retrying with a
different EMA length, VWAP anchor, bounce definition, trigger frequency or window
without a new pre-registration saying what changed and why. No such retry is
registered. The chart-judgment study already tested the model's multi-timeframe
judgment on the same entries and failed (+3.0 bp, confidence interval spanning zero);
this closes the mechanical version of the same family on the same sample. The next
open remains the entry for the installed rule. A different question — using the
trend/VWAP read to skip entries rather than time them, or applying it to a different
universe — would need a new pre-registration; it is not a retry of this rule.

## Artifacts

- Pre-registration: `docs/research/vwap-bounce-overlay-preregistration-2026-10-28.md`,
  committed `39d2de03`.
- Runner: `~/dsv41/vision/vwap_bounce.py`; payload `~/dsv41/vision/vwap_bounce.json`;
  per-entry diagnostic `~/dsv41/vision/vwap_rows.py`.
- Bars: `~/dsv41/vision/bars_ext/{sip,boats}` (90 tickers, SIP 2016-01-01.., BOATS
  2024-09-01.., split-adjusted); fetcher `~/dsv41/vision/fetch_bars.py`.
- Placebo seeds 50 (RNG 11); bootstrap 2,000 month-block draws; perturbation sample
  100; runtime 84 s.

## The one number

The rule triggered on 648 of 666 entries and bought 42.1 bp worse than the next open on
average, including costs. The registered mean is −20.5 bp only because 18 forced fills
in falling windows averaged +756.9 bp. The gate fails on all three components. The next
open remains the entry.
