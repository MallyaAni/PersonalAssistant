# Stage 4: grade-conditional multi-day timing, trained on the turn itself: results (2026-09-29)

Pre-registration: [stage4-plan-2026-09-29.md](stage4-plan-2026-09-29.md),
with Addendum 1 (the build's choices, written before any model or
decision run) and Addendum 2 (a defect found and fixed before any result
was read). The literature behind it is in
[stage4-lit-structure-2026-09-29.md](stage4-lit-structure-2026-09-29.md)
and
[stage4-lit-reversion-2026-09-29.md](stage4-lit-reversion-2026-09-29.md).

## The answer

**Every candidate: RECORD.** No way of waiting beats the board's rule on
either side, so the board keeps `dip_or_close`: buy at the first
15-minute close 1% under tomorrow's open, else at tomorrow's close; sell
at the first 1% pop, else at the close.

- **Buys.** No way of waiting up to five sessions for a better price
  paid:
  - the one-sigma dip lost, whether always or only in calm, no-news
    markets;
  - the operator's structural turn (the first close above the prior high)
    lost;
  - the chart CNN, trained on the gain of waiting itself, lost;
  - the squeeze breakout and the sequence model were flat, within ±0.1 bp
    a session.

  The trees and the sequence model learned not to wait. They held back
  only 5% and 2% of the book's buys.
- **Sells.** Holding a sell a few sessions for a bounce paid +1.6 bp a
  session on 2018-2023, positive at all 20 offsets (+1.1 to +2.0). Almost
  all of it came from names downgraded to B. It is still RECORD:
  - it fell short of the +2 bp floor;
  - a third of it was only the market's drift;
  - it lost 2.2-3.0 bp a session on 2024-2026.

## Run

- **Code.** `research/stage4` at `dabd3f5`. The split fix is `3842c6a`;
  the later commit adds only Addendum 2.
- **The addenda.** Addendum 1 was committed at 13:14Z (`bc1087f`).
  Addendum 2 was committed at 14:07Z (`dabd3f5`) and pushed before
  training started at 14:08Z. Their headers give approximate times.
- **Labels.** `market_stage4_labels` ran on spark1, 14:00-14:05Z. The file
  is `stage4_labels.npz` (sha256 `5e52e1f0`), made from `stage3_s1.npz`
  (`7fa24f7e`). 82,632 of the 88,063 rows are priced on each side; the
  summary is in Addendum 2.
- **Training.** It ran on the RTX desktop from 14:08Z. Every file records
  `registered: true`, and the logs are in `scorecards/stage4/training/`.

  | Model | Hardware | Buy | Sell |
  |---|---|---|---|
  | M1 LightGBM | i9-10900K, 16 threads | 12 min | 11 min |
  | M3 sequence model | RTX 5080 | 86 min | 179 min* |
  | M2 I20 CNN | RTX 5080 | 27 min | 25 min |

  \*The two network chains first shared the 5080. That ran about 30
  times slower (the sell model's first fold took 4,759 s against 141 s
  alone), because GPU memory spilled to system RAM. The buy chain was
  stopped at 15:50Z and rerun after the sell chain finished. The runs are
  deterministic, so sharing changes only the time: all eight of the rerun
  buy model's first-fold configuration scores equal the stopped run's.
- **Forecasts.** Every forecast starts on 2017-12-27, the first test
  block, and each file has one forecast per row.

  | Family | Rows forecast (both sides) | Buy sha256 | Sell sha256 |
  |---|---|---|---|
  | M1 | 76,295 | `489e6f0c` | `5abd1dda` |
  | M2 | 76,281 | `b3504862` | `56483400` |
  | M3 | 75,681 | `2c9e5550` | `091de895` |

- **Decision test.** `market_stage4_decisions` ran on spark1 at 19:27Z in
  388 s, with the six files and the labels over 20 offsets. The payload
  is `scorecards/stage4/decisions/stage4_decisions.json` (sha256
  `34caeced`), with its log beside it.

## Verification before the results were read

An independent check ran twice on the real data, with its own code.

**The first round found one defect** (Addendum 2). Raw SIP cube prices
were scaled by `adj_close / close`, a dividend-only factor, so before a
split a raw bar met an adjusted level. The fix, in `3842c6a`, uses stage
3's session scale; three new tests fail on the old code.

**The second round confirmed the fix and everything else:**

- **Labels.** All 88,063 rows were recomputed on the session-scale basis;
  the largest difference is 0.0002 bp. No split artifact remains on the
  ten split names. The largest label next to a split is a real move:
  KLAC, t = 2026-06-05, +1,885 bp on a 32% rally.
- **Orders.** At offset 10 the extracted orders match the simulator's own
  fills one for one: 2,523 orders (1,873 buys, 650 sells). Units, side,
  weight, grade, kind and detail are exact. The journal is passive, and
  the run's returns are bit-identical without it.
- **Fills.** Every grid cell matches: the control, D0's level, D2's turn
  and D3's squeeze, in both bar-close and next-bar modes. So does every
  order's gain, wait, action and oracle, on all 2,523 orders. The largest
  gain difference is 0.0 bp.
- **D1's inputs.** The VIX is t's close: 2,688 sessions match t only and
  none t−1 only. Every earnings flag was known by t's close.
- **Forecasts** land on their own (date, ticker) cells, for all 88,063
  rows.
- **The walk-forward.** Every label ends at least 7 sessions before the
  next validation or test block. The target scaling reads the fit units
  only, and forecasts are scaled back to bp.
- **A sensitivity, not a defect.** Anchoring each session's cube to the
  store's close can move a fill across the level. On the ten split names
  31 buy and 36 sell rows differ by more than 100 bp from a split-ratio
  basis; the median difference is 0.0003 bp.

## The orders and the drift

These are the live executor's own executed orders at offset 10 of 20:

| Window | Orders | Buys | Sells | Sessions | Orders a session | Mean weight |
|---|---|---|---|---|---|---|
| Model (2017-12-27 to 2023-12-29) | 1,433 | 1,058 | 375 | 1,512 | 0.95 | 5.9% of equity |
| 2024-2026 | 551 | 392 | 159 | 686 | 0.80 | 7.5% |

What the orders are, in the model window:

- **Buys:** 491 adds to held names, 255 entries and 312 retries of
  deferred buys.
- **Sells:** 247 rotation exits (downgrades between resets), 108 trims
  and 20 reset exits.

The A/A+ drift μ is +8.07 bp a session in the model window and +17.69 in
2024-2026.

## The verdicts

**How to read the table:**

- Figures are bp of equity a session at the median offset, with the
  Newey-West t at lag 20.
- "Re-timed" orders are those whose fill differs from the control's, with
  the t clustered by date.
- "Offsets > 0" counts the offsets whose model-window mean is positive.

| Candidate | Model window (t) | Next bar (t) | 2024-2026 (t) | DSR | Drift-adjusted (t) | Per re-timed order, bp (t), of orders | Waited, mean sessions | Offsets > 0 (range) | Oracle captured |
|---|---|---|---|---|---|---|---|---|---|
| D0 buy | −0.90 (−1.54) | −0.90 (−1.54) | +0.55 (+0.47) | 0.00 | −0.34 (−0.60) | −39.7 (−1.83), 932 of 1,058 | 73%, 3.2 | 0 (−1.15 to −0.05) | −11% |
| D0 sell | +1.64 (+2.04) | +1.64 (+2.04) | −2.92 (−1.90) | 0.32 | +1.07 (+1.33) | +63.6 (+1.98), 351 of 375 | 83%, 3.0 | 20 (+1.11 to +1.97) | 16% |
| D1 buy | −0.66 (−1.41) | −0.65 (−1.40) | +0.64 (+0.60) | 0.00 | −0.27 (−0.59) | −18.5 (−1.12), 648 of 1,058 | 50%, 3.2 | 0 (−1.07 to −0.15) | −3% |
| D1 sell | +1.58 (+2.06) | +1.58 (+2.06) | −3.00 (−1.96) | 0.34 | +1.10 (+1.42) | +75.3 (+2.20), 310 of 375 | 75%, 3.0 | 20 (+0.87 to +1.83) | 17% |
| D2 buy | −0.34 (−1.04) | −0.34 (−1.04) | −1.37 (−2.20) | 0.00 | −0.20 (−0.61) | −44.9 (−1.19), 319 of 1,058 | 28%, 2.6 | 0 (−0.90 to −0.34) | −4% |
| D2 sell | +0.42 (+0.84) | +0.42 (+0.84) | −0.66 (−0.75) | 0.03 | +0.17 (+0.35) | +16.2 (+0.49), 160 of 375 | 40%, 2.8 | 20 (+0.07 to +0.59) | 2% |
| D3 buy | +0.09 (+0.44) | +0.09 (+0.44) | −0.45 (−0.66) | 0.01 | +0.16 (+0.80) | +35.2 (+0.66), 85 of 1,058 | 8%, 3.7 | 15 (−0.07 to +0.24) | 1% |
| D3 sell | −0.09 (−0.38) | −0.09 (−0.39) | −0.57 (−0.96) | 0.00 | −0.16 (−0.72) | −24.0 (−0.32), 37 of 375 | 10%, 3.6 | 0 (−0.28 to −0.06) | −1% |
| D4 M1 buy | −0.06 (−0.85) | −0.06 (−0.87) | +0.22 (+0.53) | 0.00 | −0.03 (−0.45) | −56.3 (−0.97), 55 of 1,058 | 5%, 3.4 | 0 (−0.27 to −0.03) | −1% |
| D4 M1 sell | +1.62 (+2.02) | +1.62 (+2.01) | −2.26 (−1.69) | 0.33 | +1.07 (+1.33) | +68.2 (+2.07), 334 of 375 | 79%, 3.0 | 20 (+1.05 to +1.90) | 16% |
| D5 M2 buy | −0.40 (−1.23) | −0.39 (−1.20) | +0.18 (+0.26) | 0.00 | −0.16 (−0.52) | −43.9 (−2.01), 368 of 1,058 | 28%, 3.2 | 5 (−0.50 to +0.19) | −5% |
| D5 M2 sell | +0.86 (+1.38) | +0.86 (+1.38) | −2.21 (−1.75) | 0.12 | +0.47 (+0.74) | +65.8 (+1.82), 244 of 375 | 57%, 3.1 | 20 (+0.25 to +1.07) | 11% |
| D6 M3 buy | +0.06 (+1.68) | +0.06 (+1.68) | −0.11 (−0.35) | 0.09 | +0.06 (+1.86) | +86.4 (+0.86), 23 of 1,058 | 2%, 3.2 | 18 (−0.02 to +0.09) | 1% |
| D6 M3 sell | +1.48 (+1.82) | +1.47 (+1.81) | −3.01 (−1.95) | 0.26 | +0.94 (+1.15) | +58.5 (+1.73), 332 of 375 | 78%, 3.0 | 20 (+0.99 to +1.84) | 14% |

**Every candidate fails criteria 1, 2, 4 and 6:**

- the +2.0 bp floor, in both the default and the next-bar run;
- the deflated Sharpe: the best is 0.34 against the 0.95 gate;
- the drift-adjusted floor: the best is +1.10 bp at t 1.42.

The best t, 2.06 (D1 sell), is only modestly above the 1.74 that the best
of fourteen null candidates would reach by chance.

Ten of the fourteen, including every sell candidate, also fail criterion
3: they are negative on 2024-2026.
No candidate is "real but immaterial": the best per-re-timed-order t is
2.20 (D1 sell), below the 3.0 that label needs. Every model is
seed-stable: D4 buy has one sign change, the others none. The oracle, the
best 15-minute bar close within five sessions, is worth +354 bp a buy and
+399 bp a sell. No candidate captured more than about a sixth of it:
the most is D1 sell, at 16.5% unweighted, and D0 sell, at 16.7% weighted by
order size.

## Buys: waiting for a better price costs more than it saves

- **The plain one-sigma dip (D0).** It waited on 73% of buys, a mean of
  3.2 sessions. It lost 0.90 bp a session, and it was negative at every
  one of the 20 offsets. The dip comes only about half the time: the level
  was reached on 53% of all graded name-days. Meanwhile the price drifts
  up, +8 bp a session for A/A+ names in 2018-2023.
- **Grade gating does not rescue it.**

  | D0 buys by grade (2018-2023) | bp/session (t) | Orders | Per re-timed order (t) |
  |---|---|---|---|
  | A+ | −0.73 (−1.95) | 596 | −26.7 (−0.96) |
  | A | −0.17 (−0.43) | 462 | −56.1 (−2.36) |

  Both are about +0.3 in 2024-2026, which is noise.
- **The literature's condition (D1)** waits only in calm, no-news markets.
  It cuts the loss to −0.66, but does not turn it.
- **The structural turn (D2)** waits after a pullback for the first close
  above the prior session's high.
  - It lost 0.34 a session in 2018-2023, negative at all 20 offsets.
  - It lost 1.37 in 2024-2026 (t −2.20), −169 bp per re-timed buy
    (t −3.45).
  - On A+ names in 2024-2026 it lost 235 bp per re-timed buy (t −3.18).
    When a strong name turns up, it has already moved.
- **The squeeze breakout (D3)** waited on 8% of buys and was flat.
- **The chart CNN (M2)** waited on 28% of buys, and lost 44 bp per
  re-timed buy (t −2.01).
- **The trees and the sequence model learned not to wait.**
  - M1's forecast said wait on 6.5% of buy orders, and 4.7% waited past
    the next session.
  - M3's said wait on 2.5%, and 1.6% waited.
  - Both are flat.

## Sells: holding a downgraded name for a bounce paid until 2023, then did not

- **The size.** D0, D1 and the M1 and M3 models all hold a sell about
  three sessions for a one-sigma pop, and all gain about +1.5 to +1.6 bp a
  session in 2018-2023, positive at all 20 offsets. The models are almost
  the rule:
  - their forecasts said wait on 94% of the book's sells, where D0 always
    does;
  - 79% of sells then waited past the next session under M1, and 83%
    under D0;
  - across all graded name-days M1 and M3 say wait 93-95% of the time;
  - their hit rate equals the base rate (60%).

  They learned that sell labels are positive more often than not, not
  which sells to hold.
- **Where it came from.** Rotation exits, above all names downgraded to
  B, and sells made in stressed markets:

  | D0 sells (2018-2023) | bp/session (t) | Orders | Per re-timed order (t) | 2024-2026 bp/session |
  |---|---|---|---|---|
  | Rotation exits | +1.61 (+2.68) | 247 | +81.3 (+3.10) | −2.13 |
  | Downgraded to B | +1.69 (+2.70) | 201 | +95.8 (+3.11) | −1.65 |
  | Downgraded to C | −0.06 (−0.20) | 66 | +3.1 (+0.06) | −1.04 |
  | Trims (still A/A+) | +0.01 (+0.04) | 108 | +41.7 (+0.53) | −0.16 |
  | VIX ≥ 25 at t | +1.14 (+2.56) | 75 | +213.6 (+3.26) | +0.02 (6 orders) |
  | VIX < 25 | +0.50 (+0.70) | 300 | +23.5 (+0.67) | −2.93 (t −1.95) |

  This is the stress rebound the literature describes (Nagel 2012):
  names sold into a fall bounced. The path diagnostic had already shown
  this pattern on overlapping data, so this is not an independent
  confirmation.
- **Why it does not pass.**
  - **Drift.** A third of the gain is holding a rising stock longer: +1.64
    falls to +1.07 (t 1.33) once the drift is removed.
  - **2024-2026.** That period was calm: 38 stress sessions, against
    327 in 2018-2023. In calm markets, holding sells for a bounce lost
    about 3 bp a session, because the names kept falling.
  - **The split is not tradable.** The stress split is a reported
    reading, not a registered rule, and it rests on 75 orders.

## What the models learned

Population skill is out of sample on every graded name-day, at the
first forecast date or later:

- **Spearman:** the pooled Spearman of the forecast with the label.
- **Hit:** the share of the rows the model would make wait whose label is
  positive. The base rate beside it is the share of all rows whose label
  is positive.

| Model | Spearman 2018-2023 | Spearman 2024-2026 | Would wait, all name-days (2018-2023) | Hit vs base |
|---|---|---|---|---|
| M1 buy | −0.019 | +0.021 | 5% | 45% vs 53% |
| M1 sell | +0.046 | +0.008 | 95% | 60% vs 60% |
| M2 buy | +0.004 | +0.007 | 38% | 53% vs 53% |
| M2 sell | −0.002 | +0.006 | 69% | 60% vs 60% |
| M3 buy | −0.038 | −0.014 | 5% | 52% vs 53% |
| M3 sell | +0.033 | +0.018 | 93% | 60% vs 60% |

- **No model tells a good wait from a bad one.** On all rows, no hit rate
  beats its base rate by more than 0.3 points: M2 buy is 53.4% against
  53.1%, and the others are at or below.
- **By grade, the gaps are small either way.** 10 of the 24 cells are
  above their base rate. The largest is M3 buy on A names: 57.8% against
  52.4%, on the 3% of those rows it made wait (the payload's
  `population_skill`).
- **Only the M1 and M3 sell Spearmans (+0.046 and +0.033) sit in the
  prior's range.** They rank sells whose labels are positive 60% of the
  time in a rising market, and they fade in 2024-2026. M2's sell
  Spearman is −0.002, and the buy Spearmans run from −0.038 to +0.004.
- **Validation overstated test skill for M1 and M3, as in stage 3.**
  M2's validation scores were near zero, like its tests. The table covers
  the folds whose test blocks lie in 2018-2023.

  | Model | Mean chosen validation score | Test Spearman, 2018-2023 |
  |---|---|---|
  | M1 buy | +0.050 | −0.019 |
  | M1 sell | +0.117 | +0.046 |
  | M3 buy | +0.035 | −0.038 |
  | M3 sell | +0.077 | +0.033 |
  | M2 buy | +0.002 | +0.004 |
  | M2 sell | +0.013 | −0.002 |

## Against the prior

| Stated before the run | Outcome |
|---|---|
| Any REPLACE, about 5% | None |
| A "real but immaterial" reading, about 15% | None (the best clustered t is 2.20) |
| A sell-side candidate better than a buy-side one on the raw gain, 60% | Yes: +1.6 against −0.9. Criterion 6 then showed a third of it is drift |
| A model's population Spearman of 0.02-0.06 | Only the M1 and M3 sells (+0.046, +0.033). M2 sell −0.002; buys −0.038 to +0.004 |

## What changes

**Nothing on the board or in the account.** The board's rule stands on
both sides. A BUY is acted on in the next session at the first 1% dip or
at the close, and a SELL at the first 1% pop or at the close. Waiting days
for a deeper dip, a turn or a bounce did not pay on this book.

**The stages so far point the same way:**

- **Timing.** No model or rule tested has beaten the same-session 1% rule
  (stage 3's T-I and this note), though a perfect timer would still be
  worth +354 bp a buy.
- **Selection.** No model has improved which graded names to hold
  (stage 3's T-S1).
- **The return comes from the grades, and from holding the whole graded
  book fully invested.**

**The cumulative trial count is 451.**

## What this does not test

- **Timing is measured on the executor's orders.** It is not a change to
  which names are held.
- **Waiting is limited to five sessions.** A buy that never gets its dip
  fills at the fifth session's close.
- **Sells are timed only within five sessions of the decision to sell.**
  The decision itself (a downgrade, a trim or a reset) is untouched.
