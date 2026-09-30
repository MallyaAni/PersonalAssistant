# Stage 5 results: buying at the decision day's close (2026-09-30)

**RECORD. The board keeps buying in the next session.**

The registered test ([the plan](stage5-plan-2026-09-29.md), Addendum 1)
ran on spark1 at `c395c45` on 2026-09-30 00:31-00:42Z, on the store as of
the 2026-09-29 session, 20 offsets, statistics at offset 10. The payload is
`docs/research/scorecards/stage5/stage5_close.json` (sha256 `3a576b2d`),
the log `stage5_close_run.txt`. An independent script recomputed every
number the verdict rests on from the payload's per-buy rows and matched
the engine (`stage5_check.py`; the one difference it found was its own
convention for an unpriced next-open fill on a missed buy).

## The verdict

| Criterion | Reads | Result |
|---|---|---|
| 1. Deciding window (2016-01-04..2017-12-26): per-buy g > 0 with clustered t ≥ 2, and the session mean > 0 | g **+11.7 bp** a buy, t **+1.20**, 418 buys; +0.56 bp of equity a session (NW t +1.66) | **fails** (the t) |
| 2. 2018-2023 and 2024-2026 per-buy g > 0 | +24.3 bp (t +2.50, 1,059 buys); +9.9 bp (t +0.52, 370 buys) | holds |
| 3. Deciding window against the `next_open` control, g > 0 | +15.1 bp (t +2.39) | holds |
| 4. The null test | 0 report cells differ over 2,699 sessions; 0 of 53,780 journal decisions differ over 20 offsets | holds |

The cumulative trial count is 452.

## What the numbers say

- **The direction is positive everywhere.** The per-buy gain is above zero at
  20 of 20 offsets in each window (medians +13.8, +19.0 and +18.8 bp). On
  the unexamined window it is +11.7 bp a buy, about half the diagnostic's
  +22 bp on 2018-2023, and it does not reach the registered strength.
- **Most of it is drift.** Buying at the close is being invested one
  session earlier. Taking the window's own A/A+ drift off each matched buy
  (14.2 bp a session on 2016-2017, 7.9 on 2018-2023, 18.4 on 2024-2026)
  leaves **−2.2 bp** (t −0.22) on the deciding window, +16.6 (t 1.71) on
  2018-2023 and −7.4 (t −0.39) on 2024-2026. The literature memo said a
  third or more would be drift; here it is nearly all of it outside
  2018-2023.
- **At the book's size, 2024-2026 loses.** The notional-weighted per-buy
  gain is **−23.3 bp** there (unweighted +9.9): the large buys, which are
  what moves equity, filled worse at the close than in the next session.
  The session series is −0.91 bp of equity a session (NW t −1.58). On
  2018-2023 it is +0.74 (t 1.79) and on the deciding window +0.56 (t
  1.66), which is the +0.9 to +1.0 bp the memo expected from the size-
  weighted diagnostic.
- **The 15:30 decision itself is not the problem.** 98.3%, 98.5% and 95.3%
  of eligible notional is the same order at 15:30 (the audit's figures on
  `/4` were 98.3%, 97.9% and 98.0% at 15:45). Of 424 eligible buys on the
  deciding window, 238 matched in full, 179 in part (the partial matches
  are almost all above 98% of the size: the 15:30 price sizes the order a
  little differently) and 7 were missed. Only 4 of the 186 differences
  come from the grade, the blocker or the band; the rest are sizes.
- **Extras cost money, as registered.** The 15:30 plan buys 207 small
  round trips on the deciding window that the 19:30 plan does not want
  (1.0% of eligible notional; 4.6% and 5.7% on the later windows), each
  losing about 36-44 bp after the two 25 bp costs (gross +10.6 bp). 882 of
  the 922 extras across all windows are size differences near the trade
  floor, not decisions; 20 are grade misreads. They enter the session
  series and are the reason the session mean is below the per-buy mean.
- **By leg, deciding window** (reported): reset +57.1 bp (67 buys),
  redeploy +23.5 (143), band entry +13.1 (18), retry −9.9 (127), rotation
  −20.3 (63). The reset's buys gain the most because they are the largest
  and follow a day the book was already invested; the retry and rotation
  legs buy names that were just sold from or deferred.
- **15:45 instead of 15:30** (reported, decides nothing): +12.6 bp a buy
  on the deciding window (t 1.28), +23.0 and +8.6 later. It changes
  nothing.
- **The full ledger walk** (the candidate executor as an account, the
  simulator's own fills): +0.42 bp of equity a session on the deciding
  window (t 1.64), CAGR 31.9% against 30.6%; +0.40 (t 0.79) on 2018-2023;
  **−0.02 (t −0.05) on 2024-2026**, 61.2% against 61.6%. Without buys at
  the close the walk reproduces the simulator to the bit.
- **Coverage.** All 95 names have cubes; 98.6% of member-days have the
  15:15-15:30 bar. Not eligible: 15 buys on early closes, 9 no-bar buys, 9
  FOMC restorations (2026). Three releases fell in the tone cutoff window
  over ten years.

## What it means for the board

- The overnight rise the diagnostic measured is real, but on this book it
  is the names' own drift, not a mispricing the close captures. Owning a
  graded name a session earlier earns a session of its return, on average,
  and pays a session of its risk; that is not an execution edge.
- In the period that matters most for the live book (2024-2026), the
  change would have lost about a basis point of equity a session at the
  book's size. The 25% cap makes the large buys larger, so this reading is
  the relevant one.
- The board's rule stands: a BUY fills in the next session by
  `dip_or_close`. No change is proposed.

## The forward shadow

The plan registered a no-trade shadow of the 15:30 decisions. With a
RECORD it is not needed for a live change; it would only be worth running
if the operator wants a forward reading of the drift-adjusted gain, which
this test puts near zero. It is not installed.

## Disclosed

- The build's choices are in the plan's Addendum 1, written and pushed at
  00:10Z before any fill was read; the run started at 00:31Z after the
  night's SIP append.
- Every eligible buy, its matched share, leg, cause and gains, and every
  extra, is in the payload's `rows` block, so any figure above can be
  recomputed.
