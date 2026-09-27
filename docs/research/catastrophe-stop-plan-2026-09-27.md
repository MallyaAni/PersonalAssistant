# A single-name catastrophe stop on the `/4` book: pre-registration (2026-09-27)

Written before the run. Nothing in this note is a result.

## Question

Does a per-name stop - sell a held name on its first close 40, 50 or 60%
below where the book bought it, or below its best close since - pay for
itself on the graded equal-weight book (`policy_v4.allocator(mask)`, about
twelve names at about 8.3% each, live on the paper account), and if it
costs, what does the insurance buy?

## Why now

The operator asked how the book avoids a Lucid-type collapse, a name that
falls 90% or more. Today two things bound that loss: the grade rotation,
which drops a name when its grade goes (and only at a rebalance, so late),
and the equal-weight cap, which bounds the position at about a twelfth of
equity. Neither acts between rebalances, and neither is a rule about the
name's own price. The execution ablation
([execution-ablation-plan-2026-09-27.md](execution-ablation-plan-2026-09-27.md))
deliberately left the catastrophe case to a separate trial so that a live
convention could be judged on its cost and a stop on its tail protection
with both numbers in front of the operator. This is that trial.

## The rule

`backend/market/catastrophe_stop.CatastropheStop` wraps the policy's
allocator and hooks into `simulate.run` through a new optional
`weight_filter(t, target, prices)` hook (the allocator is only called on
rebalance sessions, so a rule that reads the price path between rebalances
cannot live inside it). With the hook None every existing run is
byte-identical; the test proves it on the pit fixture under the plain and
the live option sets.

- Entry: the decision session on which a name's target weight first
  becomes positive; the entry price is that session's adjusted close (the
  price the planner sizes at; the fill is the next open).
- "entry" mode: sell when the adjusted close is below
  `entry * (1 - threshold)`. "peak" mode: the same threshold below the
  running maximum adjusted close since entry (a trailing high-water mark).
- The sale is an ordinary next-open order; the proceeds are held as cash
  until the next rebalance (`redeploy=False`), because the trial is about
  what one name's collapse costs, not about re-risking.
- Cooldown: a stopped name is forced to zero at every rebalance until the
  allocator's mask has excluded it at one (a full cycle not held); the next
  rebalance that wants it may have it, and it is tracked afresh. This stops
  the same grade re-buying the same name at the very next reset. A name the
  grade never drops stays out for as long as that is true, and the idle
  twelfth of equity is part of the stop's cost.
- Every trigger records ticker, entry date and price, peak price, trigger
  date and price, the drawdown the rule read, and the drawdown from entry
  and from peak; afterwards whether the name closed back above the trigger
  price within 60 sessions (the "false alarm" reading; unresolved when the
  panel ends first).

## Variants, fixed now (one registered trial each; seven in all)

`none` (control: plain next-open fills, `use_exits=False`, the live reset
cadence, no stop), `entry-40`, `entry-50`, `entry-60`, `peak-40`,
`peak-50`, `peak-60`. Every variant runs under the plain execution
options - this trial is about the stop, not about the live conventions.

## Statistics, fixed now

The pit scorecard's 20 start offsets, costs 10 and 25 bp one way, windows
2016-2023 (choosing), 2024-2026 (reported) and all. Per variant and window:
median CAGR and median worst drawdown across offsets; the worst single-name
day (the smallest weight-times-return over names, the weight being the
target decided at the previous close and the return that session's
close-to-close move; minimum over the window, median across offsets);
triggers a year (median across offsets); the false-alarm rate (pooled
across offsets over the triggers whose 60-session window the panel
covers); the paired daily difference against `none` at the median offset
with a Newey-West t at lag 20; and the count of offsets above the control.

## Kill criteria, fixed now

A stop is **ADOPT (registered)** only if, on 2016-2023 at 25 bp, it is not
worse than the control by more than 0.5 CAGR points, AND it cuts the median
worst drawdown by at least 3 points OR the worst single-name day by at
least 25%, AND it is not worse on 2024-2026 by paired bp a day against the
control. Anything else is **RECORD**: the number goes in the note and the
book keeps its two existing defences. The insurance premium - CAGR points
given up per point of drawdown saved - is reported for every stop
whatever the decision, so a stop that fails the floors is still priced for
the operator's judgement.

ADOPT authorises a registered change to the executor, built with tests and
gated, not a same-night edit; the paper account runs no stop until then.

## The prior, and what would make it wrong

The prior is that a stop on an equal-weight twelve-name book costs 0.5-2
CAGR points a year and cuts the worst single-name day, because the grade
rotation already exits most losers - late, but before the loss is total -
so the stop mostly sells names that go on to recover (a high false-alarm
rate) and adds value only in the tail. Under that prior the tighter stops
(40%) fail the cost floor, the looser ones (60%) rarely fire and save
little, and no stop is adopted; the note then records the premium and the
operator decides whether the tail is worth it.

The prior is wrong if a stop costs less than half a point and cuts the
drawdown by three points or more - which would mean these names' large
falls are not, on the whole, followed by recoveries the book participates
in, and a stop is cheap insurance. It is also wrong in the other direction
if a stop costs more than two points, which would mean the book's return
lives in names that halve and then recover, and any stop is a tax on the
strategy's own mechanism. Either finding is recorded as it lands.

## Command

    python -m backend.cli.market_catastrophe_stop --root data/market --offsets 20 --costs 10 25

Writes `<root>/desk/catastrophe_stop.json`; prints the table, the verdict
and the twenty deepest triggers. Seven variants x 20 offsets x 2 costs is
280 simulator runs.
