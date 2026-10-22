# The leader rule on the whole S&P 500, point in time — 2026-10-22

## Why

The book is AI and software by decision, and the decision was made in 2026
knowing how those names did since 2015. Every scorecard the installed policy
was judged on runs inside that book, so none of them can say how much of the
record is the theme and how much is the rule's own selection. The owner asked
for a test with no such hindsight: the same grading and the same allocator on
every S&P 500 member as of each session, with the index's own dated additions
and removals, against the broad market.

Runner: `backend/cli/market_universe_hindsight_research.py` (its docstring
has the method in full). Payloads and the reconstructed membership file:
`data/market/research/universe-hindsight/`.

## What was held fixed and what changed

Fixed: the analysts, the grading, the expectations-gap model (already fitted
on the full universe and projected onto whatever book it is asked for), the
regime analyst (it keeps reading the AI-against-software spread of the book
names, exactly as the live desk does), the scorecard's costs (25 bp), offsets
(20 start phases) and windows. Changed: the valuation analyst's peer groups
are GICS sectors instead of the two book sides; the point-in-time mask is the
index's membership, reconstructed from today's constituent list and the dated
change table (503 members at the window start, 504 today, 756 intervals over
748 names).

Three limits, all stated on the payloads:

1. **Survivorship in the panel.** The store holds bars only for today's
   universe, so of the 503 members at the 2015 start only 327 can be held,
   376 of 506 in 2018, 414 in 2021, 454 in 2024, 497 today. Names that left
   the index by failing are mostly missing, which flatters every line that
   picks from the panel. SPY is the only control free of it.
2. **The equal-weight control is empty on this panel.** 1/414 of equity is
   under the simulator's 0.5% trade floor, so the "equal weight / point in
   time" line never buys; its row and the `>EW` column mean nothing here.
3. **Two renames** (WBD→PSKY, FISV's one-session hole) are handled as the
   docstring says; the rule's exposure to them is nil.

## Results (25 bp, median of 20 offsets)

| line | window | CAGR | worst DD | Sharpe | offsets above QQQ |
|---|---|---|---|---|---|
| installed rule (A cut), S&P 500 PIT | 2016–2023 | 13.1% | −37.3% | 0.78 | 0 |
| | 2024–2026 | 23.8% | −21.0% | 1.33 | 13 |
| | all | **15.3%** | −37.3% | **0.91** | 0 |
| B cut (`leader_ewma_minB`), S&P 500 PIT | 2016–2023 | 13.3% | −38.4% | 0.77 | 0 |
| | 2024–2026 | 18.7% | −17.8% | 1.31 | 0 |
| | all | **13.9%** | −38.4% | **0.84** | 0 |
| SPY | 2016–2023 | 13.2% | −33.7% | 0.76 | |
| | 2024–2026 | 20.4% | −18.8% | 1.28 | |
| | all | **13.9%** | −33.7% | **0.83** | |
| QQQ | all | 19.0% | −35.1% | 0.91 | |

For comparison, the same two arms on the book (pit_*_20261021 payloads):
installed 22.0% / −34.2% / 0.99, B cut 26.0% / −34.3% / 1.11, equal-weight
book 24.8% / −38.3% / 1.00.

Paired daily differences of the installed rule against QQQ on the broad
universe: −1.9 bp/day, HAC t −1.27 (all); −0.8 bp/day, t −0.28 (2024–2026).

## Reading

- **Before 2024 the grading selected nothing on the broad market.** 13.1%
  against SPY's 13.2% over 2016–2023, at a deeper drawdown, on a panel that
  flatters the rule. The 23.6% the same rule earned on the book in those years
  was the theme.
- **Since 2024 the A cut shows a modest selection edge**: 23.8% against SPY's
  20.4% at a higher Sharpe (1.33 against 1.28) and a shallower median drawdown
  (−20% against −19% worst). This is the only window and the only cut where the
  grading beats its own universe. Survivorship means even this is an upper
  bound.
- **The B cut's gain is book-specific.** On the book it adds four points of
  CAGR and 0.12 of Sharpe; on the broad market it takes the rule from 15.3% to
  13.9% and from 0.91 to 0.84, below SPY on Sharpe-adjusted terms in every
  window, and in 2024–2026 it falls to 18.7% against SPY's 20.4%. B-graded
  names carry no information outside the theme; inside it they add theme
  exposure, which 2016–2026 rewarded.
- Taken together with the signal audit (entries 51–56% hit, exits that sell
  too soon, chasing entries that lose): the installed system's return is the
  AI-and-software mandate first, the vol target and leader tilt second (they
  buy drawdown and Sharpe, not return — the equal-weight book made more), and
  the grading a distant third.

## What this changes

1. The B-cut install scheduled for 16:05 ET is a bet on the theme's breadth,
   not on the grading. It is still the better line on the mandate the owner
   set, and it widens the book; but it should be installed as that, and the
   owner should know before it goes in (told in the session at 08:50 ET).
2. The grading engine, not the allocator, is where the work is. A selection
   signal that holds on 400 names would be worth more than any allocator
   parameter; the A cut since 2024 is the thread to pull (what changed in the
   inputs in 2024 — the expectations gap? the tone reader?).
3. A broad-universe scorecard needs a working control: an equal-weight line
   capped at the trade floor (hold the top-N by score, or weight 1/min(N, 200))
   before any broad-market arm is compared to "its universe".
