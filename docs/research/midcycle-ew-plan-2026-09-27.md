# The mid-cycle rule redesigned for the `/4` book: pre-registration (2026-09-27)

Written before the run. The execution ablation
([execution-ablation-2026-09-27.md](execution-ablation-2026-09-27.md)) found
that the whole 4.3-point gap between plain fills and the live execution
policy on the graded equal-weight book is one option, `live_midcycle`:
23.2% with it against 27.8% without on 2016-2023 at 25 bp, at paired t 0.5,
while on 2024-2026 the same option earns 5 points and 10 points of drawdown
(52.6% / -17% against 47.7% / -28%). Every option was KEEP, and the note
named the one candidate: a redesign of the mid-cycle rule *for this book*,
since the rule was built to size concentrated `/3` positions. This is that
trial. It changes nothing on the executor.

## What the rule does on this book (read from the code, not measured)

`simulate._live_midcycle` replays `paper.midcycle_orders` on every session
between rebalances, from the cash on hand, with sells filled at the next
close and buys at the next open:

1. **Rotation.** A held name whose grade falls below A is sold in full. Its
   proceeds are planned pro rata into the other held names (not blocked,
   under the paper's 15% name cap) - but planned from tonight's cash, which
   on a book that holds every A/A+ member at about 9% is nothing, so the
   redeploy is carried as a deferred remainder and retried once, a session
   later, from the proceeds the close delivered. A retry a gate refuses
   (the taker now rejects its band, or is itself downgraded) is dropped and
   the cash waits for a breakout or the reset. With fewer than seven
   members the policy's weight exceeds the paper's 15% cap, so there is no
   taker at all and a downgrade's proceeds sit in cash until the reset.
2. **Entries.** Every A/A+ name whose 20-day band reading is at least
   `ENTRY_BAND_Z` (2.2 sigma), held or not, buys `entry_size(band)` of
   equity - 1.8% at the trigger, more on a stronger reading, up to the 15%
   cap - from the cash left after the retry. An unheld name the rebalance
   would open at 9% enters at 1.8% and is brought to weight at the reset;
   a held name at 9% is topped up toward 15%. Entries and the rotation's
   redeploy compete for the same cash and are scaled down together.
3. **What it is, then.** On the `/3` book this rule financed concentrated
   entries from a real cash reserve. On the `/4` book it is (i) a fast exit
   on a downgrade, ten sessions earlier on average than the reset; (ii) a
   small momentum tilt into whichever held names break out while cash
   exists; (iii) entries into newly graded names at a fifth of the size the
   reset will give them. The cash it works from is almost entirely what
   rotation exits free.

Which of these costs on 2016-2023 and which earns the 2024-2026 drawdown
cannot be told from the ablation, which switched them off together. The
diagnostics below and the variants are built to separate them. The
hypothesis I hold going in: (i) is what buys the drawdown (downgraded names
leave before they fall further, and in 2024-2026 they did fall), (ii) and
(iii) are what cost on 2016-2023 - undersized entries into names that then
run, cash idle between the sell and the retry, turnover in names the reset
would have held anyway.

## Diagnostics (read off every run; medians across offsets; in the payload and the table)

A passive ledger on the simulator's journal hook records each decision's
kind (rebalance, mid-cycle, event) and each session's closing cash, shares
and NAV. From it, per window: mid-cycle turnover and rebalance turnover
(notional over mean NAV a year, by the kind that traded); the mean cash
share, overall and after mid-cycle decisions; mid-cycle entries a year (a
name opened on a mid-cycle fill) and the weight an entry takes; the share
of entries still held at the next rebalance decision; mid-cycle exits a
year and the share of exits the next rebalance buys back (grade flicker).

## Variants, fixed now (one registered trial each; six in all)

All six are the full live execution policy
(`market_pit_scorecard._live_options`: block_overbought, exit_at_close,
green_day_skip, live_midcycle, deferred_buys, FOMC path and lifecycle) on
`policy_v4.allocator(mask)`, the point-in-time book. Only the mid-cycle
rule differs, through two new `simulate.run` options whose defaults are
byte-identical to the live rule (`midcycle_entries="breakout"`,
`midcycle_sweep=False`, tested).

| variant | what changes | how |
|---|---|---|
| `mc-off` | `live_midcycle=False` | the ablation's number, kept as the anchor |
| `live` | nothing | control |
| `mc-target-size` | entries sized to the policy's own weight for the name that session, less what is held, instead of `entry_size(band)`; same band trigger, same gates, same cash bound | `midcycle_entries="target"`: the allocator is asked for row t's weights on the mid-cycle session |
| `mc-no-idle-cash` | the live rule plus a sweep: cash the plan would leave beyond the policy's own idle share (1 - sum of today's target weights) goes pro rata into the held A/A+ names each session, capped at the larger of the paper cap and the name's target | `midcycle_sweep=True` |
| `mc-new-grades-only` | no band trigger: only a name the policy would hold today that it did not hold at the last rebalance, and the book does not hold, enters - at its target weight | `midcycle_entries="new-grade"` |
| `mc-exit-only` | no mid-cycle entries; rotation exits and their pro-rata redeploy unchanged | `midcycle_entries="none"` |

Everything else is the scorecard's: 20 start offsets, 10 and 25 bp one way,
windows 2016-2023 (choosing) and 2024-2026 (reported), median CAGR and
median worst drawdown across offsets, paired daily difference at the
median offset with Newey-West t at lag 20 - against `live` and against
`mc-off` - and offsets above `live`.

Two limits of the implementation, stated now. The deferred retry is the
paper planner's own and caps a retried buy at its 15% name cap, so a
target-size entry above 15% (fewer than seven members) that goes unpaid
tonight is retried only to 15%. And none of the variants funds an entry by
trimming the held names the way a reset would; every entry is paid from
cash on hand, as the live rule is, so on a fully invested book an entry
fills only when a rotation exit has freed cash. A funded ("trim the others
to make room") entry is a different rule and a later trial if this one
points at it.

## Prior

`mc-target-size` recovers 1-3 of the 4.3 points on 2016-2023 while keeping
most of the 2024-2026 drawdown benefit, because the rotation exit is
untouched and the entries stop being a fifth of their size.
`mc-exit-only` lands near `mc-off` on return and near `live` on drawdown
if the exit is what buys the drawdown; if it lands near `live` on both,
the drawdown is in the entries (the momentum tilt) and hypothesis (i) is
wrong. `mc-new-grades-only` is the cleanest version of "hold what the
policy would hold" and I expect it between `mc-off` and `live` on both
windows, with entries held at the next rebalance near 100%.
`mc-no-idle-cash` I expect to be a small positive on return everywhere
and nothing on drawdown, unless the diagnostics show the live book holds
more than 3-4% cash mid-cycle, in which case it matters more.

## Kill criteria, fixed now

A variant is **ADOPT (registered)** only if, at 25 bp, it earns at least
1.0 CAGR point against `live` on 2016-2023 with paired Newey-West t >= 2.0
against `live`, is not worse than `live` on 2024-2026 by paired mean bp/d
(>= 0), and its median worst drawdown is within 3 points of `live`'s on
both windows. Anything else is **RECORD**. `mc-off` is read against the
same floors as the anchor; an ADOPT there would only repeat the ablation's
removal question, which the ablation answered KEEP at t 0.5.

## What would make the prior wrong

If `mc-exit-only` matches `live` on 2016-2023 return, the cost is not in
the entries at all and the redesign of the entry leg is the wrong target;
the exit rule (sell on the first B) is then the candidate, and that is a
separate pre-registration. If `mc-target-size` earns the points on
2016-2023 but gives back the 2024-2026 drawdown, the two windows want
different rules and nothing is adopted - the live rule is a drawdown
device that costs return, which the operator may choose with both numbers
in front of him. If the paired t against `live` stays below 1 for every
variant, as it did for the removal, the mid-cycle rule moves *which names
are held* rather than how well they are filled, and no variant of it will
clear a t floor on a book of eleven names: the note records that and the
question closes.

An ADOPT authorises a registered change to the executor, built with tests
and gated, not a same-night edit.

## Addendum, 2026-09-27, after the first six had run: trials 7-10

Written after seeing the six results on the store, and stated as such:
these four are a follow-on, not part of the pre-registration above, and
are counted as trials 7-10. The six rows already run are kept unchanged
in `VARIANTS` and in the payload so the two runs compare row for row.

### What the first run found (2016-2023, 25 bp, medians over 20 offsets)

| variant | CAGR | maxDD | vs live bp/d (t) | cash |
|---|---|---|---|---|
| `mc-off` | 27.8% | -43.3% | +0.6 (0.50) | 7.1% |
| `live` | 23.2% | -36.0% | - | 22.3% |
| `mc-target-size` | 23.3% | -37.8% | -0.4 (-1.31) | 19.9% |
| `mc-no-idle-cash` | 25.3% | -36.9% | +0.2 (0.66) | 18.3% |
| `mc-new-grades-only` | 23.5% | -41.4% | -0.2 | 12.0% |
| `mc-exit-only` | 23.0% | -35.8% | -0.1 | 23.8% |

2024-2026: `mc-off` 47.7% / -27.7% at 11.6% cash; `live` 52.6% / -17.2%
at 32.4%; `mc-no-idle-cash` 56.4% / -17.7% at 28.1%; `mc-exit-only`
52.7% / -17.6% at 33.8%. Every variant RECORD. Diagnostics: live makes
9.5 entries a year at 2.6% weight and 32.7 exits a year, 22.7% of them
bought back at the next reset.

The lead is the cash. The live book holds 22% of equity in cash on
2016-2023 and 32% on 2024-2026 against 7% and 12% for `mc-off`, and
`mc-exit-only` holds the most of all: the mid-cycle exits (32 a year) put
their proceeds in cash, the pro-rata redeploy is planned from tonight's
cash (nothing) and retried once, and after that the cash waits for a band
breakout that mostly never comes before the reset. The sweep
(`mc-no-idle-cash`) lifted both windows and was above live on 20/20 and
18/20 offsets, but its paired daily t was 0.66 and it still held 18%,
because it goes through the same cash-bounded, band-gated buy path with
the one deferred retry. The prior above was wrong in its target: the
entry leg's *size* (`mc-target-size`) recovered nothing; what the book
lacks is exposure, not selection.

### Where `mc-off`'s 7% comes from (read from the code, checked on the synthetic book)

The FOMC path is 1.0 before 2026-06-18 (`event_risk.live_path`), so none
of it is the event ceiling on 2016-2023. Part is the policy's own:
`policy_v4` caps a name at 20%, so with four or fewer A/A+ names the
allocator itself leaves 20% or more idle (the new `idle_target_share` /
`idle_target_at_reset` diagnostics measure exactly this). The rest is the
reset's mechanics, three channels:

1. Buys fill at the next open and are paid from the cash on hand at that
   open; the trims and sells of the same reset fill at the close
   (`exit_at_close`). On a fully invested book every reset's buys
   therefore go unpaid and depend on the one deferred retry
   (`deferred_buys`, `paper._deferred_orders`) the session after.
2. That retry is the *mid-cycle entry's* gate set, not the reset's: a
   name rejecting its band (`block_overbought`) is skipped, a name is
   filled only to `paper.ENTRY_NAME_CAP` (15%), below the policy's 20%
   `HOLD_CAP`, and a remainder under `MIN_TRADE` is dropped. With six or
   fewer A/A+ names the 15% cap means a held name can never be topped up
   at all. Seen on the synthetic book: at one reset the book had 0 cash,
   trimmed two names at the close, bought nothing at the open, and the
   retry placed nothing because every under-weight name was already above
   15%; the 5.5% of proceeds sat for the whole cycle. Whatever the retry
   refuses waits nineteen sessions.
3. `_gated_targets` at the reset: a name rejecting its band is not bought
   at all, and there is no retry for a buy that was never planned.

So it is a mechanical leak of the executor's conventions, not the cap
alone, and `reset-full-invest` is added to measure it. A fourth
convention cuts the other way: `green_day_skip` holds back a sell on a
green open and `mc-off` never re-issues it until the next reset, so a
downgraded name can stay held a full cycle (also seen on the synthetic
book).

### The four variants added

| variant | `simulate.run` | what it does |
|---|---|---|
| `mc-redeploy` | `midcycle_redeploy=True`, `redeploy_buffer=0.02` | the live rule (rotation exits, retry, breakout entries) plus the reset's own buy semantics whenever cash accumulates: on every mid-cycle session, cash beyond a 2% buffer goes to the allocator's row-t targets pro rata to each name's shortfall, over the held A/A+ names and any name graded in since the reset, each up to its own target (HOLD_CAP is inside the target); no band gate, nothing deferred or dropped; sells unchanged |
| `mc-redeploy-nobuffer` | `redeploy_buffer=0.0` | the same with no buffer: the buffer's cost |
| `mc-redeploy-no-exits` | `midcycle_exits=False` | the redeploy on, the rotation sells off: no name leaves between resets, only the reset rotates (the grade still gates every buy). Against `mc-redeploy` this separates what the exits earn in drawdown from what the idle cash costs |
| `reset-full-invest` | `live_midcycle=False`, `reset_topup=True`, `redeploy_buffer=0.0` | `mc-off` with the reset completing itself: on the session after a rebalance, once the deferred retry has placed what its gates allow, the rest of the cash the reset's sells delivered goes back to today's targets through the same redeploy |

All four defaults are byte-identical to the live rule with or without a
journal (tested). The redeploy is `simulate._redeploy_orders`; the top-up
is `simulate._topup_leg`, and its session is recorded as `topup` in the
ledger so its turnover counts with the rebalance's and never as a
mid-cycle entry or exit.

### The second reading, fixed before this run

The floors above are unchanged. Because the claim being tested is "the
book is under-invested" - exposure, not selection - each variant also
carries, at 25 bp on 2016-2023:

* the exposure-adjusted comparison: live's CAGR scaled to the variant's
  mean invested fraction (1 - cash share), `23.2% x invested_variant /
  invested_live`, and the variant's CAGR less that. Near zero means the
  gain is exposure alone; positive means the redeployed cash earned more
  than live's book did per unit invested; negative, less.
* the per-offset sign test: offsets whose CAGR beats live's out of 20. A
  RECORD that is above live on at least 18 of 20 (`CONSISTENT_SHARE`
  0.9) with a CAGR gain of at least 2 points (`CONSISTENT_POINTS`) is
  read as **CONSISTENT, floor not cleared by daily t**, and is stated
  exactly that way - a reading, never an adoption. The daily t on a book
  of eleven names moved by exposure is not expected to clear 2.0
  (`mc-no-idle-cash` was +2.1 pt on 20/20 offsets at t 0.66), and this
  says so in advance rather than after.

Prior for these four: `mc-redeploy` lands between `mc-no-idle-cash` and
`mc-off` on return (25.5-27.5%) with cash near the buffer plus the cap's
idle share, and keeps most of live's 2024-2026 drawdown because the
exits are untouched; `mc-redeploy-no-exits` lands near `mc-off` on both
return and drawdown, which is the test of "the exits are worth 10 points
of drawdown"; `reset-full-invest` earns 1-2 points over `mc-off` on
2016-2023 and more on 2024-2026 where its cash was 11.6%. If
`mc-redeploy` does not beat `mc-no-idle-cash`, the sweep's remaining 18%
was not the gated buy path but the exits' own timing, and the redeploy
is not the fix.

Run: `--only mc-redeploy mc-redeploy-nobuffer mc-redeploy-no-exits
reset-full-invest --merge <root>/desk/midcycle_ew.json` prices the four
and the two anchors on the same offsets and costs and folds them into the
first run's payload, keeping its six rows.
