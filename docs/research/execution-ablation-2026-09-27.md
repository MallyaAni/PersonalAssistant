# Live execution conventions on the `/4` book, one at a time: results (2026-09-27)

Pre-registration: [execution-ablation-plan-2026-09-27.md](execution-ablation-plan-2026-09-27.md).
Run on spark1 from `01a661de` (`python -m backend.cli.market_execution_ablation
--root data/market --offsets 20 --costs 10 25`), payload
`docs/research/scorecards/execution_ablation.json`. Ten registered variants,
400 simulator runs, about 40 minutes on one core.

## The table (25 bp; median CAGR and median worst drawdown across 20 offsets; bp/d and t are the paired daily difference at the median offset, Newey-West lag 20)

| variant | 2016-2023 CAGR | maxDD | vs live bp/d (t) | 2024-2026 CAGR | maxDD | vs live bp/d (t) |
|---|---|---|---|---|---|---|
| plain (control) | 27.5% | -42.2% | +0.9 (+0.9) | 46.2% | -23.6% | -1.9 (-0.7) |
| live | 23.2% | -36.0% | — | 52.6% | -17.2% | — |
| live-block_overbought | 23.3% | -36.1% | +0.0 (+0.1) | 54.7% | -17.2% | +0.2 (+0.2) |
| live-exit_at_close (and deferred_buys) | 22.4% | -37.2% | -0.5 (-1.8) | 52.5% | -18.5% | -0.6 (-1.2) |
| live-green_day_skip | 22.9% | -36.3% | -0.4 (-0.9) | 44.3% | -17.3% | -2.3 (-2.4) |
| live-live_midcycle | 27.8% | -43.3% | +0.6 (+0.5) | 47.7% | -27.7% | -1.4 (-0.5) |
| live-deferred_buys | 23.2% | -35.3% | +0.1 (+0.2) | 51.9% | -17.5% | +0.1 (+0.9) |
| live-event | 23.2% | -36.0% | +0.0 | 52.9% | -19.5% | -0.4 (-1.3) |
| plain+exit_at_close | 23.0% | -34.7% | -1.5 (-1.6) | 41.5% | -20.9% | -1.5 (-0.6) |
| plain+event | 27.5% | -42.2% | +0.9 (+0.9) | 47.6% | -22.7% | -1.5 (-0.6) |

The 10 bp table has the same shape (plain 29.2% / live 25.2% on
2016-2023; 48.0% / 55.0% on 2024-2026). Reconstruction: the six single
removals sum to +3.4 points against the +4.3-point plain-minus-live gap
(interaction +0.9).

**Verdict: every option KEEP.** No removal earns 1.0 CAGR point against
`live` with t >= 2.0 on the choosing window while not worse on 2024-2026.
Nothing changes on the executor.

## Reading it

1. **The whole gap is the mid-cycle band entries.** Removing
   `live_midcycle` alone takes the book from 23.2% to 27.8% on 2016-2023 -
   the full 4.3 points and a little more - and every other option moves
   it by less than a point. But its paired t is 0.5: the daily difference
   between the two books is enormous in both directions, because mid-cycle
   entries change *what is held*, not when it is filled. A 4.5-point CAGR
   difference with t 0.5 is a difference of paths, not a measured edge, and
   the registered floor is right to refuse it.
2. **On 2024-2026 the same option runs the other way.** With mid-cycle
   entries the live book earns 52.6% against 46.2% plain and its worst
   drawdown is 17% against 24%; removing them costs 5 points and puts the
   drawdown back to 28%. Across both windows the live conventions cost
   about a point a year (27.4% against 29.0% on the full span) and buy six
   points of drawdown (-36% against -42%). That is a trade the operator may
   reasonably take, and the equity curve on the board shows both lines.
3. **`green_day_skip` earns its place in the recent window** (removing it:
   -2.3 bp/d, t -2.4 on 2024-2026) and is a wash before. **`exit_at_close`**
   hurts when added to the plain book (-2.4 points, t -2.9) but helps
   inside the live set (removing it, and the deferred-buy leg that depends
   on it, costs 0.5 bp/d, t -1.8): the conventions interact, which is what
   the reconstruction's +0.9 says. **`block_overbought`, `deferred_buys`
   and the event path** are within noise of zero everywhere, kept because
   there is no case for touching them, not because they earn anything.
4. So the operator's earlier question - are the live conventions costing
   money on the new book - has its answer: on the choosing window yes,
   4 points, all of it one option; on the recent window no, they earn 6;
   and in neither is the difference statistically distinguishable from
   path luck. The executor stays as validated. The mid-cycle entry rule
   is the one candidate for a redesign *for this book* (it was built to
   size concentrated `/3` positions), and that is a new claim with its own
   pre-registration, not a removal.
