# Persistence length and release-event votes — closed 2026-09-16

## Question

A held stance changes only after the analyst's raw stance has repeated
for three consecutive sessions (`opinions.PERSISTENCE`). In the week of
2026-09-11 that cost the desk on both sides: ORCL's upbeat Sep 10 report
counted in the Sep 15 record, and ADBE's poor Sep 10 report left an A+
standing until Sep 15. NTAP and HPE showed the same three-session lag
after their Sep 3 reports. Does a shorter wait, or a rule that lets a
new release reading vote the night it is read, do better?

## Method

The plain rule on the desktop research store (`data/market`, the
2026-09-16 pull), `desk.run` and `simulate.run(since=2018-06-01,
use_exits=False)`, the same path as every other registered comparison.
Four variants, everything else unchanged:

- persistence 3 (the live rule);
- persistence 2;
- persistence 1 (no wait);
- persistence 3 with release-event resets: the sentiment stance applies
  at once on the first session a scored release is on file and on any
  session a scored field changes (a new release or a re-read), all other
  analysts unchanged. Branch `release-event-vote` (36cccb68), unmerged.

Bar written before the run: adopt a variant only if CAGR is higher with
the drawdown no deeper and turnover not higher.

## Result

| Rule | CAGR | Max drawdown | Sharpe | Turnover | Grade changes / yr |
|---|---|---|---|---|---|
| 3 sessions (live) | 25.05% | −22.08% | 1.463 | 5.81 | 940 |
| 2 sessions | 24.57% | −22.31% | 1.428 | 5.83 | 1,299 |
| 1 session | 23.77% | −22.25% | 1.385 | 6.05 | 2,436 |
| 3 sessions + release votes at once | 24.34% | −22.08% | 1.428 | 5.84 | 965 |

Every shorter or event-driven variant is worse on CAGR and Sharpe. The
release-event rule changes few grades a year (25 more) and still costs
0.7 points a year: across the history the first-night reading of a
release is wrong often enough that waiting pays, and the cases that
prompted the question are the ones where it did not.

## Decision

Insufficient evidence to advance. The live rule stays at three sessions
for every analyst. The release-event code stays on its branch as the
record of what was tested. What the page now does instead is say so:
the ticker panel names the analyst that moved, its readings and the
three-session rule, so a lag reads as the rule working rather than as
an unexplained grade.

## Data revision noted

PANW's vote flipped bearish in one session on 2026-09-11 with no new
release. Its Sep 2 release was re-scored under `release_tone/2` that
night (guidance and demand 1.0 → 0.8) and again under `release_tone/3`
on Sep 15; the recomputed history already held three sessions of the new
reading. A prompt-version change that moves a grade is a data revision
the record should name. Not fixed here.
