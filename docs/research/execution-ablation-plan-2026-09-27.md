# Live execution conventions on the `/4` book, one at a time: pre-registration (2026-09-27)

Written before the run. The fill-timing trial
([execution-timing-2026-09-27.md](execution-timing-2026-09-27.md)) found the
band gate on buys is neutral in isolation (+0.08 bp/d, t 1.2), so the 4.4
CAGR points the full live execution policy costs the graded equal-weight
book (27.7% plain next-open fills against 23.3% live, 2016-2023, 25 bp,
point-in-time book; NEXT_SESSION 2026-09-27 addendum) come from the other
conventions. This trial locates them. The conventions were designed for the
concentrated `/3` book; whether each still earns its place on a twelve-name
equal-weight book is the question.

## Variants, fixed now (one registered trial each; ten in all)

`plain` (control: next-open fills, no exits, 20-session rebalance) and
`live` (`market_pit_scorecard._live_options`: block_overbought,
exit_at_close, green_day_skip, live_midcycle, deferred_buys, event
exposure path and event lifecycle); then the live set with exactly one
option removed - `live-block_overbought`, `live-exit_at_close` (this also
drops deferred_buys, which the simulator refuses without exit_at_close;
the variant's note says so), `live-green_day_skip`, `live-live_midcycle`,
`live-deferred_buys`, `live-event`; and two additive checks from the
control, `plain+exit_at_close` and `plain+event`, so that an option's
effect can be read from both ends.

Everything else is the scorecard's: `policy_v4.allocator` on the
point-in-time mask, 20 start offsets, 10 and 25 bp one way, windows
2016-2023 choosing and 2024-2026 reported, median CAGR across offsets,
paired daily difference at the median offset with Newey-West t at lag 20 -
against `plain` and against `live`.

## Kill criteria, fixed now

An option is **REMOVE (registered)** from the `/4` executor path only if
removing it earns at least 1.0 CAGR point against `live` on 2016-2023 at
25 bp, with paired t >= 2.0 against `live`, and is not worse on 2024-2026
(paired mean bp/d against `live` >= 0). Anything else is **KEEP**: the
option is either earning its place, or costing less than a point, which
on this evidence is not worth a change to the executor the shadow ledger
has validated.

The reconstruction check is reported alongside: the sum of the six
single-removal effects against the `plain`-minus-`live` gap. If the sum is
far from the gap the options interact and no single removal is acted on
without a second, registered run of the specific combination.

## What is not decided here

Removing an option from the executor changes the live path the paper
account runs. A REMOVE verdict authorises a registered change, built with
tests and gated, not a same-night edit; and the decision about which
options protect against the catastrophe case (a single name collapsing)
is a separate, already-queued trial - a convention that costs a point a
year and buys nothing in that trial is removed, one that costs a point
and cuts the worst single-name day is a judgement the operator makes with
both numbers in front of him.
