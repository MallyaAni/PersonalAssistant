# Fill timing inside the session: pre-registration (2026-09-27)

The operator asked why the account rebalances at the close and fills at
the next open instead of "when the price is ideal" - price and structure,
not the clock, should be the trigger. This is the plan for testing that,
written before any rule is run. The book being filled is the graded
equal-weight book (`graded-equal-weight/4`, live on the paper account since
2026-09-27); the question is only *when within the session* its orders
should fill, and *whether a price condition* should gate them.

## What is already measured

- The executor already has price triggers: mid-cycle buys wait for the
  upper-band breakout, unpaid buys are deferred, ordinary sells go to the
  closing auction. On the `/4` book under these conventions: 23.3% a year
  against 27.7% for plain next-open fills on 2016-2023 (NEXT_SESSION
  2026-09-27 addendum). The structure triggers, as built, cost 4.4 points.
- Session anatomy (2026-09-27): the first half-hour's return carries no
  information about the rest of the day (slope +0.02, t 0.2); a 2% dip by
  11:30 is followed by slightly *less* return to the close, not more (t
  -2.5 on 2016-2023, same sign on 2024-2026); the expected difference
  between any two fill windows (open, first-hour VWAP, session VWAP, close,
  closing auction) is 1-4 bp against a 186-235 bp session standard
  deviation.
- Literature: index-level intraday momentum (rest-of-day return predicts
  the last half hour, a hedging-flow effect) is the one intraday return
  pattern with a long out-of-sample record; it lives late in the day and
  at the index level, not in a name's own open.

So the prior is that the *time* of the fill is worth basis points, not
points, and that a *price* gate on the open (waiting for a dip) is worth
less than nothing on this book. The trial exists to measure that on the
actual orders the policy generates, not to assume it.

## The trial

**Question.** For the orders `graded-equal-weight/4` generates on the
point-in-time book, which fill convention earns the most after costs, and
does any price condition beat "fill at the open"?

**Fill conventions, fixed now (one registered trial each):**

1. `next_open` - the incumbent simulator convention; the control.
2. `first_hour_vwap` - filled at the volume-weighted price of the first
   four bars (09:30-10:30) of the next session.
3. `session_vwap` - the whole next session's volume-weighted price.
4. `next_close` - the closing auction print of the next session.
5. `dip_or_close` - a buy fills at the first bar close of the next
   session that is at least 1% below the open, else at the close; sells
   the mirror (first bar 1% above the open, else the close). The
   operator's "buy the dip" as a rule, with a fallback so every order
   fills.
6. `late_day` - fills in the 15:00-15:45 bars (the window where the
   index-level momentum effect lives), at their VWAP.
7. `breakout_gate` - the executor's own band-entry condition: a buy fills
   at the next open only if the daily is not rejecting its upper band,
   otherwise it is deferred one session and re-tested (the live
   convention, isolated).

Costs: 10 bp one way on every fill, the scorecard's convention; VWAP
conventions get the same cost (the store's VWAP is a proxy from bar closes
weighted by bar volume; this is stated in the output).

**Data.** The SIP store's 26 regular bars plus the closing-auction bar
(schema 2) for every fill session, 2016-2023 choosing, 2024-2026 reported.
Orders: the `/4` policy's target changes at each rebalance and rotation,
exactly as `simulate.run` with `policy_v4.allocator` produces them.

**Statistics.** Each convention's daily return series, paired against
`next_open`: mean daily difference in bp with Newey-West t at lag 20;
median CAGR difference across the 20 start offsets; and, because seven
conventions are scored, the ordering of the seven reported with the
deflated Sharpe of the best against seven trials.

**Kill criteria, fixed now.** A convention is ADOPTED for the live
executor only if it beats `next_open` by at least 5 bp a session (about 12
CAGR points a year on a fully invested book, the scale the gate cares
about) with t >= 2.5 on 2016-2023 at 10 bp, and is not worse on
2024-2026. Anything smaller is recorded and not acted on: a 1-3 bp
expected difference is real money over years but is inside the fill
noise of any single day, and changing the executor for it is not free. If
`breakout_gate` loses to `next_open` (the prior, from the 4.4 points), the
band gate is removed from the `/4` executor path as a separate,
already-measured change.

**What would make the prior wrong.** `dip_or_close` or `late_day` beating
`next_open` by 5 bp a session with t >= 2.5. That would say the price on
the day of the fill carries information about the price at the close of
that day for these names, which the anatomy study did not find in the
pooled numbers; it would be tested again on 2024-2026 before anything
moved.

## Not in this trial

Intraday *decisions* (changing what is held during the day) are a
different claim from intraday *fills* (when the nightly decision is
executed) and are not tested here; the 15-minute engine's decision layer
waits on a signal that so far does not exist (stage 1 of the deep plan).
