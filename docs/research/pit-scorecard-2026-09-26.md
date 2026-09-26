# Point-in-time scorecard, first run, and the signed-rotation arm's verdict

Run on the Spark on 2026-09-26 from `39175f37` with
`python -m backend.cli.market_pit_scorecard --root data/market` (frozen
rule) and the same with `--signed-rotation` (arm). Outputs:
`data/market/desk/pit_scorecard.json` and
`data/market/desk/pit_scorecard_signed_rotation.json`. The headline figures
below are as reported from that run (CAGR / worst drawdown / Sharpe, medians
across the 20 offsets); the full six-line tables are in the JSON files and
should be copied beside this note.

## The number the project has been missing

| line | 10 bp, all | 25 bp, all |
|---|---|---|
| rule / today's book | 42.3% / -38.5% / 1.32 | 39.6% / -38.9% / 1.25 |
| rule / point-in-time | 18.8% / -24.3% / 1.16 | 17.9% / -24.7% / 1.11 |

Paired daily differences at the median offset, 10 bp, all sessions:

| pair | bp/day | Newey-West t |
|---|---|---|
| rule point-in-time minus equal-weight point-in-time | -2.9 | -1.80 |
| rule point-in-time minus QQQ | -0.4 | -0.28 |
| rule today's book minus QQQ | +7.8 | +3.33 |

Read plainly: on the names the desk could actually have known about, the
rule earns what QQQ earns (t -0.28) and trails the equal-weight book of the
same names by about 7 CAGR points a year (t -1.80). The 23-point gap between
the two rule lines is the choice of names, made with hindsight; that is
the only line that beats QQQ with any confidence. This confirms what
`market_survivorship` estimated and what the volatile-book review inferred,
now on the funded ledger with the strict benchmark loader.

The point-in-time book is smaller (index names in the book's sub-industries,
about 50 in 2016-2020 against 94 today) and the rule's top decile is scaled
to the names it can see, so it holds about five names early on; that is the
rule's own definition. The point-in-time drawdown is shallower for the same
reason.

## Gate H on the signed-rotation arm: FAILED (insufficient evidence)

The arm makes the rotation half-vote reach both sides (`Opinion.signed`).
Same command, same sessions, offsets, costs and windows:

| block | frozen rule | arm |
|---|---|---|
| 10 bp 2016-2023 | 28.5% / -36.8% / 1.13 | 27.1% / -37.1% / 1.09 |
| 10 bp 2024-2026 | 109.1% / -36.7% / 2.01 | 111.9% / -36.5% / 2.07 |
| 10 bp all | 42.3% / -38.5% / 1.32 | 41.8% / -38.7% / 1.32 |
| 25 bp 2016-2023 | 26.1% / -37.7% / 1.05 | 24.6% / -38.0% / 1.01 |
| 25 bp 2024-2026 | 105.0% / -37.0% / 1.96 | 107.6% / -36.8% / 2.02 |
| 25 bp all | 39.6% / -38.9% / 1.25 | 39.2% / -39.4% / 1.25 |
| point-in-time, 10 bp all | 18.8% / -24.3% / 1.16 | 17.9% / -23.9% / 1.12 |
| point-in-time, 25 bp all | 17.9% / -24.7% / 1.11 | 16.9% / -24.3% / 1.07 |

Gate H's first criterion is a positive median improvement on the choosing
window (2016-2023) at both costs. The arm is -1.4 points at 10 bp and -1.5
at 25 bp there, and -0.9 / -1.0 on the point-in-time line over all
sessions. The only block where it is ahead is 2024-2026, which is reported
and never tuned on. DSR, SPA and PBO are not reached because the first
criterion fails. Verdict: **insufficient evidence**; the mechanism stays
available behind `signed_rotation=True` and the live rule is unchanged.
The docstring's claim that following the leader pays is not supported once
the vote actually reaches the leader's side.

## What this changes in the order of work

1. The hurdle for any learner is now a number: the equal-weight point-in-time
   book, and QQQ. A selection model earns its place only by beating equal
   weight on the point-in-time universe, at 25 bp, on 2016-2023, with the
   trials counted.
2. The rule's own selection (top decile by summed conviction) has no measured
   edge over equal weight point in time. Before a learned ranker is built to
   replace it, the cheapest arm is the one already in the plan as P1.2:
   capped equal weight across every A/A+ name. Score it with the same
   command next.
3. The published curve on the dashboard shows the today's-book line. It
   should show the point-in-time line beside it, labelled, so the page
   stops presenting the universe choice as the strategy's return.
