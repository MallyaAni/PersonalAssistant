# Grade-B entry timing on the current panel: result (B fails the gate; C stops on coverage)

**Status: B FAILED the pre-registered gate; C STOPPED on coverage. The B extension is
closed and is not retried. The C arm is not scored and is not a live candidate.**
Nothing changes in the live rule, the board, or any prompt. The live rule stays frozen
through the 252-session review.

The answer to "wouldn't the chart help B names?" is no on this sample. When
`trend-vwap-bounce/1` fires on a B entry it buys 20.0 bp worse than the next open on
average, including costs. The registered mean is −4.4 bp only because 45 forced fills
in falling windows averaged +492.4 bp. B is less bad than grade-A (−42.1 bp triggered
vs −20.0 bp) because B windows drift up less, but it is still negative, and the
2021-2026 half is −10.5 bp. Below B is worse: the C book loses 1.46 pp of CAGR and
takes 5.25 pp more drawdown, and the C execution sample stopped at 85.7% coverage.

## What ran

- Pre-registration:
  `docs/research/grade-b-vwap-overlay-preregistration-2026-10-29-current-panel.md`,
  committed `01e120c4` and corrected `225d562b` before either arm was read. The earlier
  note `grade-b-vwap-overlay-preregistration-2026-10-29.md` stopped at its baseline
  reproduction check and is not retried; this run is the new sample on the current
  panel.
- Sample: the current `desk.run` panel (`FUNDAMENTALS_CURRENT`, current deploy code
  `5b54b96e` / `fundamentals-features/6`), truncated to 2026-10-23: 2,970 sessions, 94
  names plus the benchmark. Baseline `Rule()` (`entry_grade=2`, `hold_grade=1`), the
  installed rule; B arm `Rule(entry_grade=1, hold_grade=1)`; C arm
  `Rule(entry_grade=0, hold_grade=0)`. The current baseline is recorded; the old replay
  manifest is not a reproduction target under the current code (the pre-meeting FOMC cut
  was retired and `policy_book.py` changed), as the pre-registration states.
- B sample: every first buy at grade B, decided 2016-02-01 through 2026-10-16: **1,498
  entries across 93 tickers** (mean size 1.86% of equity). The B < 100 stop did not fire.
  C sample: the same at grade C: **14 entries** (mean size 0.99% of equity).
- Bars: Alpaca 15Min, split-adjusted, SIP 04:00-20:00 ET from 2016-01-01 and BOATS
  20:00-04:00 ET from 2024-09-16, merged and labelled as `chartlib.prepare`. The NVDA
  split check passed: 2024-06-07 close 120.87, 2024-06-10 open 120.35, ratio 0.9957.
- Rule `trend-vwap-bounce/1`, unchanged: at a 15-minute bar close, EMA9 > EMA21; the
  previous bar closed above session VWAP; the current bar's low is at or below VWAP and
  its close is above VWAP. The first such bar in the window is the trigger. The fill is
  the open of the first bar starting at or after the trigger bar's end; baseline A is
  the open of the first regular bar of t+1. Costs are 5 bp regular, 15 bp pre-market and
  after-hours, 30 bp overnight; A pays 5 bp.
  `improvement_bp = 1e4 * (ln P_A - ln P_B) - (cost_B - cost_A)`.
- B: 1,431 triggered, 45 forced at the close of t+5; mean bars waited 38.1. Coverage
  98.53% (1,476 of 1,498 scored); 22 unscored, all "no baseline or forced bar" (DELL 3,
  HUT 4, OKLO 3, SMCI 3, VRT 2, WULF 7 — names whose early entries predate their Alpaca
  bars). C: 12 of 14 scored (85.71%) — below the 90% floor, so the C arm **stopped**;
  the two unscored are HUT 2018-07-03 and VST 2017-01-10, both "no baseline or forced
  bar". No model call and no prompt; the rule is fully mechanical.

## Gate (B primary)

| Test | Result | Verdict |
|---|---|---|
| G1 mean improvement vs buying at the next open, after costs | −4.4 bp, median −24.7 bp, 95% CI [−20.1, +10.2] | **FAIL** |
| G2 beats a placebo that permutes trigger offsets across entries | B −4.4 vs placebo median −10.6, 90th pct −4.86 (best draw +1.8) | **PASS** |
| G3 positive in both halves | 2016-20 +3.1 bp (n 660), 2021-26 −10.5 bp (n 816) | **FAIL** |

Two of the three components fail, so the B extension is closed. G2 passes by 0.45 bp:
the trigger beats 90% of random offsets, but the best placebo draw (+1.8 bp) is better
than the B mean, and G2 alone cannot pass the gate.

## The decomposition

The registered mean is −4.4 bp, but the trigger is not what produces it:

- **1,431 triggered entries: mean −20.0 bp, median −27.9 bp, 503 of 1,431 positive.**
  When the rule actually fires, it buys worse than the next open.
- **45 forced entries: mean +492.4 bp, median +470.4 bp, 37 of 45 positive.** These are
  windows where price fell and never bounced off VWAP; the forced fill at the close of
  t+5 bought after the fall. The largest are WULF 2025-08-13 (+2,668.3 bp, overnight
  trigger), BE 2023-09-29 (+1,669.5, forced), TER 2020-03-05 (+1,647.5, forced) and NET
  2022-12-30 (+1,601.9, pre-market trigger). The largest loss is IREN 2023-07-06
  (−1,602.8 bp).
- Excluding the 45 forced entries, the mean is −20.0 bp. The positive contribution is
  the forced fallback in falling windows, which is not a VWAP bounce; the trigger
  itself is negative. This is the same pattern as grade-A, where 648 triggered entries
  averaged −42.1 bp and 18 forced entries averaged +756.9 bp.
- Costs: 1,078 regular, 269 pre-market, 81 overnight and 48 after-hours fills. The 398
  non-regular fills (27.0%) pay 10-25 bp more than A, about 3.5 bp of the −4.4 mean. The
  remaining price term is about −0.9 bp overall, but that is the mix: the triggered
  entries' price term is about −16 bp and the forced entries' about +492 bp.
- The distribution is wide: 10th percentile −223.9 bp, 25th −105.7, median −24.7, 75th
  +37.8, 90th +258.8; 540 of 1,476 entries are positive and 50 are exactly zero.

## By year

| Year | Mean improvement (bp) | n |
|---|---:|---:|
| 2016 | −27.0 | 125 |
| 2017 | +5.8 | 124 |
| 2018 | +39.3 | 128 |
| 2019 | −16.6 | 151 |
| 2020 | +16.4 | 132 |
| 2021 | −12.7 | 131 |
| 2022 | +10.8 | 135 |
| 2023 | −57.1 | 124 |
| 2024 | −16.1 | 126 |
| 2025 | +1.6 | 172 |
| 2026 | +4.0 | 128 |

Six years are positive and five negative; the halves split because 2023 (−57.1 bp) and
2024 (−16.1 bp) dominate the 2021-2026 half. The 2016-2020 half is +3.1 bp; 2018
(+39.3 bp) is the main positive, while 2016 (−27.0 bp) and 2019 (−16.6 bp) are the main
negatives. 2026 is a partial year (through 2026-10-16) and does not change the gate.

## Placebo

The 50 placebo means range −21.0 to +1.8 bp, median −10.6, 90th percentile −4.86. The
trigger is 6.2 bp better than the median random offset and 0.45 bp better than the 90th
percentile, so G2 passes; the best draw (+1.8 bp) is still better than the trigger. The
delay itself is costly in this sample: the B windows drift up less than the grade-A
windows, but the next open is still usually the better price. The placebo pass does not
pass the gate; it only says the trigger is better than a random offset.

## Diagnostics (reported, not gated)

- Trend-only (EMA9 > EMA21 and close > VWAP, without the bounce conditions): −12.1 bp.
- VWAP-limit-in-uptrend (a limit at VWAP for the next bar, re-placed at every bar
  close): −7.2 bp.
- Both are negative; the bounce conditions improve on trend-only by about 5 bp but not
  enough to pass. The grade-A comparators were −16.1 bp and −14.9 bp; the B diagnostics
  are less negative, consistent with B windows drifting up less, but the sign is the
  same.
- Forward returns from A's fill: the 45 forced entries' 20- and 60-session returns are
  −359.4 bp and +32.9 bp; the 1,431 triggered entries' are +200.2 bp and +629.7 bp. The
  trigger fires in rising windows and the forced fallback in falling ones; this is the
  same selection effect as grade-A (never-triggered −724.2/−1,129.6 bp; triggered
  +249.4/+672.6 bp), not evidence that the trigger improves the entry price.

## Selection diagnostic (reported before the execution gate)

The B arm is the installed rule plus B entries; the C arm is an any-grade book with
longer holds (`hold_grade=0`). The book comparison is a selection diagnostic, not a
like-for-like timing test.

| Book | CAGR (all) | Max DD (all) | Sharpe (all) | Total (all) | CAGR (to 2022) | CAGR (from 2023) | Fills | Costs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Current baseline | 33.40% | −28.85% | 1.3252 | +2,675.8% | 17.33% | 73.33% | 6,989 | 52,517.73 |
| B arm | 33.90% | −29.94% | 1.3666 | +2,797.7% | 18.01% | 73.25% | 8,166 | 67,600.66 |
| C arm | 31.94% | −34.09% | 1.2622 | +2,344.8% | 19.91% | 60.37% | 992 | 5,370.29 |

- B vs baseline: all CAGR +0.50 pp, Sharpe +0.0414, total +121.9 pp, but max drawdown
  1.09 pp deeper and from_2023 CAGR −0.08 pp (total −1.4 pp). The B book is not a clear
  improvement: it buys more names, pays 15,082.93 more in costs, and takes a deeper
  drawdown; the recent period is no better.
- C vs baseline: all CAGR −1.46 pp, max drawdown 5.25 pp deeper, Sharpe −0.0630, total
  −331.0 pp; to_2022 is better (19.91% vs 17.33%, total +62.9 pp), but from_2023 is much
  worse (60.37% vs 73.33%, total −205.7 pp). The C book is worse on the full period and
  the recent period; it is not a live candidate.
- Counts and sizes: 1,498 B first entries (mean 1.86% of equity), 14 C first entries
  (mean 0.99%). The B arm has 1,177 more fills than the baseline; the C arm has 5,997
  fewer because it holds through C and rarely exits.
- Forward returns: the B forced/triggered split is above; the C forward returns were
  not computed because the C arm stopped at the coverage floor before scoring. The C
  book metrics are the selection diagnostic for C.

## The C arm

The C arm stopped on the pre-registered coverage floor: 12 of 14 entries scored
(85.71%) < 90%. The two unscored are HUT 2018-07-03 and VST 2017-01-10 ("no baseline or
forced bar"). No C execution result exists; the C gate was not read. The C book is worse
on every full-period metric and much worse from 2023, so the C extension is not a live
candidate regardless of execution. A pass would only have been a candidate for a new
pre-registration, not a promotion; the stop means there is nothing to promote.

## Look-ahead controls

- Perturbation: 100 sampled B triggers, 100 unchanged after multiplying every bar
  starting at or after the trigger bar's end by a random factor in [0.95, 1.05]; 100
  changed after a +1% close edit; 0 reproduction failures.
- Visibility: the indicator at bar i reads only bars with `end <= end(i)`; the fill
  reads only bars starting at or after `end(i)`; the forced fill reads only bars in the
  window.
- Split check passed as above. The policy engine reads only data up to each close; the
  B and C samples are the engine's own trades, not a hand-picked list.

## What this closes

- The B extension is closed by the pre-registration: the gate failed on G1 and G3. It
  is not retried with a different grade cut, EMA length, VWAP anchor, bounce definition,
  trigger frequency or window without a new pre-registration saying what changed and
  why.
- The C arm stopped on coverage; it is not scored and not a live candidate. No retry is
  registered.
- The answer to the B question is no on this sample: the chart timing does not help B
  entries. The trigger buys 20.0 bp worse than the next open when it fires; the overall
  −4.4 bp is the forced fill in falling windows. B is less bad than grade-A (−42.1 bp
  triggered vs −20.0 bp) because B windows drift up less, but it is still negative, and
  the 2021-2026 half is −10.5 bp.
- Selection is separate. Even if execution had passed, buying B or C names needs a
  point-in-time-universe selection pre-registration. The B book's deeper drawdown and
  the C book's worse full-period and recent metrics say the selection is not obviously
  better; the B extension is not a live candidate on this result.
- No live change follows. The live rule stays frozen through the 252-session review;
  the next open remains the entry for the installed rule.

## Artifacts

- Pre-registration:
  `docs/research/grade-b-vwap-overlay-preregistration-2026-10-29-current-panel.md`,
  committed `01e120c4`, corrected `225d562b`.
- Runner: `~/dsv41/vision/vwap_bounce.py`; B payload `~/dsv41/vision/grade_b_vwap.json`;
  C payload `~/dsv41/vision/grade_c_vwap.json` (stopped); samples
  `grade_b_entries.jsonl` / `grade_c_entries.jsonl`; policy books
  `grade_bc_policy.json`; report `bc_report.py`; per-entry decomposition
  `vwap_rows.py` / `grade_b_rows.log`.
- Bars: `~/dsv41/vision/bars_ext/{sip,boats}` (split-adjusted, SIP 2016-01-01.., BOATS
  2024-09-16..); fetcher `~/dsv41/vision/fetch_bars.py`.
- Placebo seeds 50 (RNG 11); bootstrap 2,000 month-block draws; perturbation sample
  100; B runtime 123 s.

## The one number

The B trigger fired on 1,431 of 1,476 scored entries and bought 20.0 bp worse than the
next open on average, including costs. The registered mean is −4.4 bp only because 45
forced fills in falling windows averaged +492.4 bp. B fails G1 and G3; the C arm stopped
at 85.7% coverage. The B and C extensions are closed; the next open remains the entry,
and the live rule stays frozen through the 252-session review.
