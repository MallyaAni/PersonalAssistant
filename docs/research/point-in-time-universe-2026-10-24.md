# The installed rule on the S&P 500 as it stood each day (2026-10-24)

The book's 94 names were chosen in 2026 knowing how they did, so every book
backtest (37.6% a year for the installed rule) mixes the rule's skill with that
hindsight. This runs the installed rule on the account simulator
(`policy_book.simulate`, `eligible=` the index's dated membership) over the
S&P 500 as it stood on each session, with the nightly's grades (current
fundamentals mode, split-corrected), the P/E tilt, band block and FOMC cycle.
Script: `~/dsv41/pit2/build.py`, `run.py`; results `~/dsv41/pit2/results.json`.

Limit: the store holds bars only for names in today's universe, so of the ~503
members in 2015 only 328 can be held (377 in 2018, 415 in 2021, 456 in 2024).
Members that later failed are mostly missing. The equal-weight controls share
the same bias, so rule-against-equal-weight is the fair comparison; against SPY
the rule is flattered.

| Universe | Rule | CAGR | Worst drawdown | Sharpe | 2015-22 | 2023-26 |
|---|---|---|---|---|---|---|
| S&P 500, point in time | installed (10 bp) | 14.8% | -34.7% | 0.90 | 11.0% | 22.9% |
| | installed (25 bp) | 14.2% | -33.3% | 0.88 | 10.1% | 23.2% |
| | old B rule | 13.5% | -35.6% | 0.87 | 11.4% | 17.7% |
| | equal weight, no costs | 13.9% | -38.5% | 0.82 | 12.8% | 16.3% |
| S&P 500 Information Technology, point in time | installed (10 bp) | 20.4% | -34.5% | 0.97 | 11.2% | 41.5% |
| | installed (25 bp) | 17.9% | -35.4% | 0.87 | 8.7% | 39.1% |
| | old B rule | 19.0% | -33.9% | 0.93 | 11.5% | 35.7% |
| | equal weight, no costs | 22.6% | -34.7% | 0.96 | 17.6% | 33.4% |
| S&P 500 IT + Communication | installed (10 bp) | 19.5% | -35.7% | 0.96 | 9.6% | 42.6% |
| | equal weight, no costs | 19.9% | -34.4% | 0.93 | 15.2% | 30.2% |
| SPY | | 13.8% | -33.7% | 0.82 | 10.2% | 21.3% |
| Today's book (hindsight) | installed | 37.6% | -27.7% | 1.46 | 21.2% | 78.1% |

## Reading

- Most of the book's record is the choice of names: the same rule on the
  stocks that were actually available earns 15-20% a year, not 37.6%.
- The rule's own selection is small and recent. On the whole index it beats
  equal weight by about one point a year with a better Sharpe (0.90 against
  0.82), all of it after 2022. Inside the technology sector it trails simply
  owning every tech member equally (20.4% against 22.6%; to 2022 11.2% against
  17.6%) and leads only since 2023 (41.5% against 33.4%).
- The new rule (A entry, B hold, 1% trade floor, P/E tilt) beats the old B rule
  on every universe, so the install stands; but the grading is the weak part.
  The work that would move the system is a better selection signal, measured on
  this universe, not on the book.

Correction (same day): the first run froze the whole book when a held name
left the research universe (PSKY from 2026-08-11), because the simulator
treated a non-member like an unpriceable holding. A name leaving the universe
is now sold at the next open; only a held name the price window cannot value
freezes the night. Figures above are from the corrected run (IT+Comm 19.5%
instead of 19.6%; the old B rule on the whole index 13.3% at -25.6% instead
of 13.5% at -35.6%); the readings are unchanged.
