# Structure rules S1 results: resistance, the first bar's shape, the reference price, the market's dip, selling at the level, and the grade under a falling EMA (2026-09-30)

**RECORD, all seven. The board keeps `dip_or_close` on both sides and the
technical analyst's stance as it is.**

The registered test ([the plan](structure-rules-plan-2026-09-30.md),
committed before any code, with Addendum 1 at `5a4b1ccf` before any run)
was built at `a3041068` and ran on spark1 at `5a4b1ccf` (clean tree) on
2026-10-01 01:23-01:57Z, on the store as of the 2026-09-30 session (2,953
sessions, 94 names with a cube out of 94, cubes from 2016-01-04, SPY cube
2,679 sessions), 20 offsets, statistics at offset 10. The six fill
candidates ran on the executed orders of `ew-redeploy` under
`graded-equal-weight/5` against `dip_or_close` (728 s); S1g ran through
the technical analyst on the T-S1 scorecard, a control run with the flag
off and a notched run with it on. The payloads and logs are under
`docs/research/scorecards/structure-rules/`:

| File | What | sha256 |
|---|---|---|
| `structure_rules.json` | S1a-S1f, per-order rows at the median offset, all six candidates | `a43882d358b9291e53da501fbd19f5f0f4667c4209ed9a6cca33ee94e991c4ab` |
| `notch_control.json` | T-S1 scorecard, incumbent stance (`ew_graded_cap25`) | `0007ece32c814bfa50dfe0d09ab9e4ecce028c464306824ae1ad264f53aa5bb8` |
| `notch.json` | T-S1 scorecard, `ew_graded_cap25 + structure_notch` | `b37c8182b800f7f80fc960031ef6d0642bb34b41bc335b9d9d766f0ff948dbad` |
| `structure_notch_verdict.json` | S1g paired against the control, the gate and the drawdown criterion | `e9f4d3544c8bfde2fbfb39165826cc9d61f6d78944941abb159dc6582d214a31` |

The logs are `structure_rules_run.txt`, `notch_control.txt`, `notch_run.txt`
and `notch_verdict.txt`. The independent script
(`structure_rules_check.py`, committed at `e19a9101` before the run)
recomputed every number the fill verdicts rest on from the payload's
per-order rows - its own Newey-West and clustered t - and matched the
engine on every window, both fill modes, all six candidates
(`structure_rules_check.txt`: "independent check: OK"). The null test for
S1g (`notch_null.txt`) ran the book through the notched code path with
the mask cleared against the plain path: grades and scores equal on all 24
compared lines, "PASS, reproduced to the bit".

## The verdicts

At the median offset, model window 2018-01-02..2023-12-29 (1,509 decision
sessions, 1,107 buys: 635 graded A+, 472 A; 246 entries, 531 adds, 330
retries; 17 unpriced; 374 sells: 240 rotation exits, 115 trims, 19 reset
exits; 8 unpriced), then 2024-2026 (688 sessions, 397 buys, 140 sells).
The floor is +2.0 bp of equity a session at Newey-West t ≥ 2 (lag 20).
Drift for S1b's wait: +7.98 bp a session over 9,709 A/A+ name-days on the
model window, +18.37 over 3,431 on 2024-2026.

| Candidate | 1. Model window | 2. Next-bar | 3. 2024-2026 | 4. DSR at N=7 | 5. Drift-adj. | 6. Offsets > 0 | Per re-timed order | Verdict |
|---|---|---|---|---|---|---|---|---|
| S1a resistance guard, defer (buy) | **−0.03 bp** (t −0.64) | −0.03 (t −0.66) | +0.20 (t +1.44) | 0.07 | −0.03 (t −0.64) | 5 of 20 | −7.5 bp (t −0.25), 75 of 1,107 | **RECORD** |
| S1b resistance guard, skip (buy) | **+0.01 bp** (t +0.11) | +0.01 (t +0.08) | −0.63 (t −0.67) | 0.21 | +0.04 (t +0.52) | 18 of 20 | −10.8 bp (t −0.59), 177 of 1,107 | **RECORD** |
| S1c hold-the-dip (buy) | **−0.07 bp** (t −1.25) | −0.07 (t −1.12) | −0.06 (t −0.51) | 0.02 | −0.07 (t −1.25) | 0 of 20 | −3.2 bp (t −0.84), 468 of 1,107 | **RECORD** |
| S1d decision-price reference (buy) | **−0.04 bp** (t −0.53) | −0.04 (t −0.54) | +0.20 (t +1.89) | 0.08 | −0.04 (t −0.53) | 2 of 20 | −12.9 bp (t −1.03), 217 of 1,107 | **RECORD** |
| S1e market-relative dip (buy) | **−0.01 bp** (t −0.16) | −0.01 (t −0.17) | −0.08 (t −0.71) | 0.14 | −0.01 (t −0.16) | 15 of 20 | −4.9 bp (t −0.61), 281 of 1,107 | **RECORD** |
| S1f sell at the tag (sell) | **−0.11 bp** (t −1.80) | −0.11 (t −1.83) | +0.16 (t +1.39) | 0.00 | −0.11 (t −1.80) | 0 of 20 | −21.7 bp (t −1.12), 42 of 374 | **RECORD** |

Criterion by criterion: S1a passes 3 only; S1b passes 6 only; S1c passes
nothing; S1d passes 3 only; S1e passes 6 only; S1f passes 3 only. No
candidate is "real but immaterial" (that needs a clustered t of 3 on the
re-timed orders; the largest in magnitude is S1f's −1.12). Deflated Sharpe
at the cumulative 464 trials: 0.01, 0.03, 0.00, 0.01, 0.02, 0.00. The
cumulative trial count is 464.

S1g on the T-S1 scorecard at 25 bp, the notched book paired against the
incumbent at every offset:

| | 2016-2023 | 2024-2026 |
|---|---|---|
| Paired return, notch minus control | −0.19 bp a session (t −0.91, 2,012 sessions) | −0.01 bp (t −0.88, 689) |
| Above the control | 10 of 20 offsets | |
| Deflated Sharpe at 464 | 0.00 | |
| Median worst drawdown, notch / control | −42.9% / −42.9% (−0.0 points) | −24.5% / −24.5% (−0.0 points) |
| Median CAGR, notch / control | +28.0% / +28.5% (−0.4 points) | +44.6% / +46.8% (−2.2 points) |
| Return gate (+2 bp, t ≥ 2, not negative 2024-2026, 15 of 20, DSR ≥ 0.95) | fails on all four | |
| Drawdown criterion (−3 points on both windows, CAGR inside ±1) | fails: drawdown unchanged on both | |

The verdict lines, verbatim from the runs:

```
RECORD: no fill candidate clears every criterion; the board keeps dip_or_close on both sides
  S1a (resistance_defer, buy): model window -0.0 bp/session (t -0.64); next-bar -0.0 (t -0.66) fails; 2024-2026 +0.2 bp/session; deflated Sharpe +0.07 at N = 7 (+0.01 at 464); drift-adjusted -0.0 (t -0.64); positive at 5 of 20 offsets; per re-timed order -7.5 bp (t -0.25) over 75 of 1107 orders; fired 16%; tagged 28%; level reached 36%; oracle capture -0% - RECORD
  S1b (resistance_skip, buy): model window +0.0 bp/session (t +0.11); next-bar +0.0 (t +0.08) fails; 2024-2026 -0.6 bp/session; deflated Sharpe +0.21 at N = 7 (+0.03 at 464); drift-adjusted +0.0 (t +0.52); positive at 18 of 20 offsets; per re-timed order -10.8 bp (t -0.59) over 177 of 1107 orders; waited 16%; fired 16%; tagged 28%; level reached 42%; oracle capture -2% - RECORD
  S1c (hold_the_dip, buy): model window -0.1 bp/session (t -1.25); next-bar -0.1 (t -1.12) fails; 2024-2026 -0.1 bp/session; deflated Sharpe +0.02 at N = 7 (+0.00 at 464); drift-adjusted -0.1 (t -1.25); positive at 0 of 20 offsets; per re-timed order -3.2 bp (t -0.84) over 468 of 1107 orders; fired 43%; tagged 0%; level reached 41%; oracle capture -1% - RECORD
  S1d (decision_reference, buy): model window -0.0 bp/session (t -0.53); next-bar -0.0 (t -0.54) fails; 2024-2026 +0.2 bp/session; deflated Sharpe +0.08 at N = 7 (+0.01 at 464); drift-adjusted -0.0 (t -0.53); positive at 2 of 20 offsets; per re-timed order -12.9 bp (t -1.03) over 217 of 1107 orders; fired 57%; tagged 0%; level reached 32%; oracle capture -2% - RECORD
  S1e (market_relative, buy): model window -0.0 bp/session (t -0.16); next-bar -0.0 (t -0.17) fails; 2024-2026 -0.1 bp/session; deflated Sharpe +0.14 at N = 7 (+0.02 at 464); drift-adjusted -0.0 (t -0.16); positive at 15 of 20 offsets; per re-timed order -4.9 bp (t -0.61) over 281 of 1107 orders; fired 100%; tagged 0%; level reached 36%; oracle capture -1% - RECORD
  S1f (sell_at_level, sell): model window -0.1 bp/session (t -1.80); next-bar -0.1 (t -1.83) fails; 2024-2026 +0.2 bp/session; deflated Sharpe +0.00 at N = 7 (+0.00 at 464); drift-adjusted -0.1 (t -1.80); positive at 0 of 20 offsets; per re-timed order -21.7 bp (t -1.12) over 42 of 374 orders; fired 100%; tagged 19%; level reached 52%; oracle capture -2% - RECORD
```

```
S1g (structure notch): paired 2016-2023 -0.2 bp/session (t -0.91) over 2012 sessions; 2024-2026 -0.0 bp/session (t -0.88); above the control at 10 of 20 offsets; deflated Sharpe +0.00 at 464
  2016-2023: median worst drawdown -42.9% against -42.9% (-0.0 points); CAGR +28.0% against +28.5% (-0.4 points)
  2024-2026: median worst drawdown -24.5% against -24.5% (-0.0 points); CAGR +44.6% against +46.8% (-2.2 points)
  RECORD (neither the return gate nor drawdown)
```

## What the numbers say

The per-order figures below are read from the payload's `rows` block at
the median offset: every priced order, the control's fill and each
candidate's fill. A "re-timed" order is one where the candidate's fill
differs from the control's; "helped" is a lower fill for a buy, a higher
one for a sell.

- **The resistance guard rarely fires, and when it fires the close is
  not usually lower.** A level (the nearer of EMA21 and H20 above the
  decision close) exists for most buys; the first bar tags it on 28% of
  the model window's 1,090 priced buys (302), and the tag is rejected on
  16% (179). On 104 of those 179 the control had not reached its 1% dip
  either, so both filled at the close and nothing changed. On the 75 that
  differ, S1a's fill is the close instead of the control's dip bar, and
  the close is *higher* than the control's fill on 43 of them (57%):
  mean +9.8 bp above the control's fill, median +7.9 bp, so g = −7.5 bp a
  re-timed buy on average, with a wide spread (10th/90th percentile −191
  and +239 bp, worst −706, best +617). The tape the operator read on
  09-30 (rejected at the level, then lower all day) is the 43% case on
  the model window, not the usual one. On 2024-2026 it is the other way:
  27 re-timed buys, the close lower on 15 (56%), +19.7 bp a buy, positive
  at all 20 offsets (+0.06 to +0.45 bp a session) - but 27 buys over
  33 months, t 0.66, and the model window had already failed.
  By leg, the deferral hurts the entries most (−51.9 bp a buy over 14)
  and is flat on adds (+11.7 over 33).
- **Skipping the session (S1b) moves the fill to t+2 and the overnight
  gap decides it.** 178 buys waited (16%); 177 re-timed. The t+2 fill is
  under the control's on 93 of 177 (53%), median −6.5 bp, but the mean is
  +13.0 bp above it because the losers gap: 10th percentile −253 bp of g,
  worst −999 (a 10% overnight gap-up). That is −10.8 bp a re-timed buy,
  +0.01 bp a session before drift (+0.04 after the one-session drift
  credit the plan allows, t 0.52), positive at 18 of 20 offsets by +0.05
  bp a session at the median - a hundredth of the floor, the same handful
  of buys in every offset's book. On 2024-2026 it is −0.63 bp a session
  (t −0.67), negative at 12 of 20 offsets (median −0.48), the worst
  2024-2026 reading in the batch: the entries it skipped there cost
  −59 bp a buy over 22. It fails criteria 1, 2, 3, 4 and 5.
- **Hold-the-dip (S1c) is a tax on the fills it touches.** It fires on
  43% of buys (474; 468 re-timed, by far the most of any rule) because it
  re-times *every* dip the control reaches: the control buys the dip bar,
  S1c buys the next bar that closes above the dip bar's low. That bar is
  higher on 277 of 468 (59%): mean +3.5 bp above the control's fill,
  median +7.1, g = −3.2 bp a buy, and the spread is the tightest in the
  batch (10th/90th −66 / +66 bp) because it is the same session one bar
  later. Negative at all 20 offsets on the model window (−0.19 to −0.03
  bp a session) and at 13 of 20 on 2024-2026. The dip bar's low holding
  on the next bar carries no information about the rest of the session
  on this book; the bars just drift up a few basis points from a
  flush.
- **The decision-price reference (S1d) fires on 57% of buys and mostly
  changes nothing.** The lower reference (min of the open and the
  decision close) applies whenever the name gapped up (622 of 1,090
  buys); on 405 of those the control's 1% dip was not reached either, so
  both filled at the close. On the 217 that differ the tighter level is
  reached later or not at all: 126 of the 217 went to the close (slot
  −1) where the control had bought a dip bar. The S1d fill is under the
  control's on 120 of 217 (55%), median −12.9 bp, but the mean is +13.9
  bp above it: g = −12.9 bp a buy, −0.04 bp a session, positive at 2 of
  20 offsets. On 2024-2026 it is +0.20 bp a session (t 1.89, positive at
  all 20 offsets, +19.4 bp a buy over 85, helped on 64%), the best
  2024-2026 reading in the batch and the one that comes nearest to a
  criterion - but the plan's gates are the model window first, and
  there it loses. The gap guard inside S1d (open above the decision
  close by more than σ) did not fire on any of the 09-30 names and is
  not separately counted in the payload.
- **The market-relative dip (S1e) is evaluated on every buy (SPY bar
  present on 1,089 of 1,090) and re-times 281.** Subtracting SPY's bar
  return makes the trigger easier on red-market days and harder on green
  ones. The two movements cancel almost exactly: the S1e fill is under
  the control's on 142 of 281 (51%), median −0.8 bp, mean +5.5 bp above
  it, g = −4.9 bp a buy, −0.01 bp a session, 15 of 20 offsets positive
  on the model window by +0.01 bp at the median (criterion 6 passes;
  nothing else does), 12 of 20 on 2024-2026 where it is −0.08 bp a
  session.
- **Selling at the level (S1f) gives up the run.** Every sell is
  evaluated (366 priced on the model window); the first bar reaches L
  from below on 19% (69) and 42 of those re-time against the control's
  1%-over-the-open-else-close. The limit at L fills *below* the control's
  fill on 32 of 42 (76%): mean −21.1 bp, median −31.2, because a bar that
  trades through the level usually closes above it, and the control sells
  at that bar's close (21 of the 42 re-timed sells are in bar 1, where
  the control's 1% pop and the level were both in play). It is negative
  at all 20 offsets on the model window (−0.14 to −0.01 bp a session),
  the lowest deflated Sharpe in the batch (0.00), and the most negative
  per-order figure (−21.7 bp a sell, t −1.12, below the immaterial bar).
  On 2024-2026 it helped on 7 of 10 (+46 bp a sell), ten sells.
- **By grade and by leg** (reported, deciding nothing): on the model
  window S1a is −16.1 bp a re-timed buy on A (32) and −1.2 on A+ (43);
  S1b −19.8 on A (78), −3.7 on A+ (99); S1c −2.7 / −3.6; S1d −11.7 /
  −13.9; S1e −8.6 / −2.0. The loss concentrates in the entries for every
  rule that defers (S1a −51.9, S1b −32.2, S1d −36.2, S1e −9.3 bp an
  entry), adds are flat to slightly positive, retries in between; a new
  position is the buy a deferral most often leaves to a worse print.
- **Where the fills land.** S1a's fills by bar on the model window are
  front-loaded like the control's (105 at the first bar, 51, 39, 26,
  26); S1c's are the same shape shifted one bar (0, 92, 62, 50, 36) by
  construction; S1f's sells are 66 at the first bar, 29, 23.
- **The oracle.** The lowest bar close of t+1 is 116 bp below the
  control fill on average (129 on 2024-2026). No candidate captures any
  of it: −0%, −2%, −1%, −2%, −1%, −2%.
- **Next-bar** (the robustness run, fills at the following bar's open)
  changes nothing: −0.03, +0.01, −0.07, −0.04, −0.01 and −0.11 bp a
  session.
- **Drift.** Only S1b waits past t+1 (16% of buys, one session each);
  the drift adjustment moves it from +0.009 to +0.041 bp a session on
  the model window and from −0.63 to −0.55 on 2024-2026. The other
  five have a wait of 0 and criterion 5 reads as criterion 1.

## S1g, the structure notch

- **How often it fires.** The notch (close under a falling EMA21 with
  lower highs) applies to 8,334 of 58,794 eligible name-sessions on
  2016-2023 (14.2%), 4,538 of 29,457 on 2024-2026 (15.4%), 12,872 of
  88,251 over the whole panel (14.6%). It is not rare: one name-day in
  seven loses its technical vote.
- **What it does to the book: almost nothing.** The paired difference
  is −0.19 bp a session on 2016-2023 and −0.01 on 2024-2026; the notched
  book is above the control at exactly 10 of 20 offsets. The median worst
  drawdown is unchanged to the decimal on both windows (−42.9% and
  −24.5%; the 2024-2026 difference is 2e-15). CAGR is 0.4 points lower on
  2016-2023 and 2.2 lower on 2024-2026. The rule the plan allowed to win
  on drawdown moved drawdown by nothing, because (Addendum 1) withdrawing
  the technical vote rarely changes a grade: A+ needs two bullish votes
  and fundamental, sentiment and value supply them without the technical
  analyst, and the A-or-better set the `/5` allocator buys from barely
  moves.
- **The scorecard's rank IC** (reported): h20 0.0473 (t 3.33) notched
  against 0.0479 (t 3.39) incumbent; h60 0.0677 (t 2.73) against 0.0655
  (t 2.64). Net Sharpe 0.82 / 0.84 against 0.82 / 0.79. Within noise of
  each other on both horizons.
- **The names notched in 2026.** The payload lists every (session, name)
  cell notched in 2026: 1,486 cells over 177 sessions and 78 names
  (through 2026-09-30). The most notched: FSLR 52 sessions, INTU 51, PTC
  51, TYL 47, CDNS 42, TRMB 41, FICO 40, GEN 40, SNPS 40, ADSK 39, PLTR
  39, QCOM 39, ADBE 39, ORCL 38, MSI 37, NOW 36, WDAY 36, CSCO 36, MSFT
  35, DDOG 34 - the 2026 software and semi-equipment drawdowns, as a
  falling-EMA rule would pick. AAOI was notched on 6 sessions in 2026
  (09-10, 09-11, 09-14, 09-15, 09-16, 09-24), COHR on 2 (09-10, 09-15),
  SMCI on none. On 2026-09-30 the notched cells were CIFR, CORZ, FICO,
  HUT, IBM, IREN, MSI, TRMB, VRT and WULF.
- **What the payload does not have.** `notch.json` carries the per-window
  counts and the 2026 cell list (date, ticker) but no per-cell grade
  under each arm, so "how many notched sessions kept A+ on the other
  analysts" (the figure Addendum 1 asked for) cannot be read from it, and
  the control payload carries no notch block at all (its arm is the
  plain `ew_graded_cap25`). The book-level evidence above - the same
  drawdown, 10 of 20 offsets, −0.2 bp a session - says the grade rarely
  changed, but the count itself was not recorded and is not claimed here.

## The 09-30 case

What each rule would have done with the three buys that morning, from the
rules' definitions, the daily bars as of 2026-09-29 and the first bars
the scenario note recorded (AAOI open 101.39, high 103.96, close 99.27;
COHR 295.13 / 298.94 / 285.77; SMCI 42.18 / 42.67 / 41.57). The later bars
and the closes are from the SIP 15-minute cube for 2026-09-30, whose
first bars differ slightly from the note's (AAOI 101.90 / 104.25 / 99.32).
Levels on the adjusted basis through 09-29: AAOI close 100.67, EMA21
104.43 (107.07 five sessions earlier: falling), H20 116.90, σ 4.2%, so
L = 104.43; COHR close 292.21, EMA21 295.01 (falling from 296.91), H20
332.86, σ 5.0%, L = 295.01; SMCI close 41.02, EMA21 39.50 (rising from
38.11, and under the close so not a level), H20 43.76, σ 4.3%, L = 43.76.

| Rule | AAOI (control 99.27) | COHR (control 285.77) | SMCI (control 41.57) |
|---|---|---|---|
| S1a defer | Tag (103.96 ≥ 103.91) rejected under 104.43: fills at the close, 99.20 (+7 bp) | Tag rejected under 295.01: close 286.70 (−33 bp) | No tag (42.67 < 43.54): control's bar |
| S1b skip | Rejected: no buy on 09-30, re-planned for 10-01 | Same | Control's bar |
| S1c hold the dip | Bar 2 closes 99.10 above bar 1's low 97.90: fills 99.10 (+17 bp) | Bar 2 closes 286.38 above 284.05: fills 286.38 (−21 bp) | Bar 2 closes 41.01 under bar 1's low 41.16, keeps watching; bar 3 closes 40.90, 1% under the open and above bar 2's low 40.65: fills 40.90 (+164 bp) |
| S1d decision reference | Level min(101.39, 100.67) × 0.99 = 99.66; bar 1 closes under it: control's bar. No σ gap (open +0.7% over the close) | Level 289.29: control's bar (open +1.0%, no σ gap) | Level 40.61; bar 1 (41.57) does not reach it; the first bar close at or under 40.61 is the ninth, 40.56 at 11:30 ET: fills 40.56 (+250 bp). Open +2.8% over the close, under σ |
| S1e market-relative | SPY bar 1 +0.03%: AAOI −2.1% in excess, control's bar | −3.2% in excess: control's bar | −1.5% in excess: control's bar |
| S1f sell at the tag | No sells that morning | | |
| S1g notch | Under a falling EMA21 but no lower highs (daily highs 105.03, 102.43, 103.83; 102.43 is 1.9% under the EMA): not notched; A+ stands. Last notched 09-24 | Under a falling EMA21, highs 301.77, 299.37, 302.72: not notched. Last notched 09-15 | EMA21 rising: not notched |

AAOI's "rejected under the EMA for the third session" does not meet the
registered lower-highs condition: the daily highs of 09-25, 09-28 and
09-29 (105.03, 102.43, 103.83) are neither descending nor all within 1%
of the EMA, so S1g would have left all three grades alone on 09-30 (it
had notched AAOI on six September sessions through 09-24). Only the
resistance guard and hold-the-dip would have changed the AAOI fill, by
7 and 17 bp; neither gets near the 97.4 print at 11:30, which no rule in
the batch reaches (the lowest bar close was 97.25 at 11:15). On COHR both
would have paid more. On SMCI the two rules that wait for a deeper print
(S1c, S1d) would have bought 1.6-2.5% lower - and across the ten years
those same rules lose on the buys they re-time. The three fills were a
case, as the plan said; the batch measured the rules on 1,107 buys and
374 sells and the case is on the wrong side of each rule's average.

## What it means for the board

- The board's fill rule stands on both sides: a BUY fills in the next
  session by `dip_or_close` at the fixed 1%, a SELL at 1% over the open
  else the close. The technical stance stands as it is. No change is
  proposed.
- The operator's reading of the 09-30 tape - rejected at the 21-day EMA
  with lower highs, so do not buy the first dip - is a real pattern on
  that day and a coin flip on the book: 43% / 56% of the time the close
  was lower, the average deferral cost 7.5 bp on the model window and
  earned 19.7 on 2024-2026, and at 16% of buys it moves the book by a
  few hundredths of a basis point a session either way.
- The one rule with a plausible mechanism that did not lose on
  2024-2026, the decision-price reference (S1d: +0.20 bp a session, t
  1.89, 20 of 20 offsets, +19.4 bp a buy), lost on the model window at
  2 of 20 offsets. It could be re-registered as a 2024-2026-first study
  if the operator believes the gap-up regime of the last three years
  persists; on the registered criteria it is RECORD and nothing is
  carried forward from it.
- Structure (a falling EMA, lower highs) does not change the grade
  often enough to change the book, and when it does the book is the
  same to the decimal on drawdown. The stage-4 literature memo's reading
  (trend filters mostly help drawdown, not return) is not borne out here
  either: on this book they do neither.

## Disclosed

- The plan was committed before any code; Addendum 1 (the notch
  withdraws the technical vote; the build conventions for H20 and the
  adjusted basis) was committed at `5a4b1ccf` before any run. The build
  is `a3041068` (the fill candidates, the structure levels shared with
  the board's `structure.py`, the T-S1 `--structure-notch` and
  `--null-test` paths, the check script at `e19a9101`). The run's payload
  records revision `5a4b1ccf`, `dirty: False`.
- The run was 2026-10-01 01:23-01:57Z on spark1 (fills 01:23-01:35Z, 728
  s; the T-S1 null test, control and notched run 01:35-01:57Z), niced on
  CPU, while the deploy gate was also running on the machine. No number
  was read before the run; nothing was tuned after it; the verdicts above
  are the ones the run printed.
- The fill study runs with `SECRET_KEY` set to a research-only value in
  the environment, because the CLI imports the application settings
  module, which requires one. It is not the deployment's key and nothing
  in the study reads it.
- The six fill candidates were priced on the executed orders of the
  same executor and policy as the adaptive-entry study (`ew-redeploy`
  under `graded-equal-weight/5`, 20 offsets) on a store one session
  newer (1,107 model-window buys against 1,091); sells are priced here
  for the first time (S1f), and the sell-side control is the board's
  rule as written (1% over the open, else the close).
- The levels are computed on the panel's adjusted basis; the board
  compares an adjusted EMA with raw quotes (a dividend factor apart,
  Addendum 1). H20 needs a full 20-session window; younger names have no
  H20 level and S1a/S1b/S1f fall back to EMA21 or to no level.
- S1g's per-cell list in the payload covers 2026 only, by design (the
  plan asked for "the names and sessions it notched in 2026"); the
  per-window counts cover the whole panel. The "kept A+ on the other
  analysts" count from Addendum 1 was not recorded and is reported above
  as missing.
- The 09-30 case uses the scenario note's first-bar prices and the SIP
  cube's later bars; the two feeds differ by a few cents on the first
  bar, which does not change any rule's action that morning.
- Every order at the median offset, its date, name, weight, detail and
  grade, the control fill, and per candidate its fill, g (bar-close and
  next-bar), wait, reached, acted, unpriced and slot, is in the
  payload's `rows` block, so any figure above can be recomputed;
  `structure_rules_check.py` recomputes the verdict figures and the
  per-order means and medians in this note were read from the same rows.
