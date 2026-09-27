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
