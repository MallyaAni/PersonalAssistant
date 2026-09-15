# Post-decision reversal in the most beaten book names — registered 2026-09-15, before the run

The operator's observation: after the July 29, 2026 decision the names
that had fallen hardest into the meeting rose 26 to 30% the next day and
33 to 47% within ten sessions, and the desk held none of them because
its rule never buys weakness. Across the five 2026 meetings the same
basket returned −8.2%, +1.9%, +22.3%, −6.9% and +33.4% over five
sessions: two large winners on the two deepest selloffs, two losers, one
mixed. That is a hypothesis about depth and reversal, not a result.

## The specification, fixed before the run

- **Universe**: the 93 book names with a price on the decision day.
  Chosen in 2026, so every number below carries survivorship bias, and
  names listed after a meeting are absent from it.
- **Signal** at the decision close t: the five-session return
  close_t / close_(t−5) − 1. The **basket** is the worst decile by that
  return (at least five names), equal weight.
- **Entry** at the next session's open; **exit** at the close ten
  sessions after entry. Adjusted prices; the open adjusted by the same
  factor as the close.
- **Costs**: 10 and 30 basis points per side on traded notional.
- **Benchmark adjustment**: the basket return less beta × SPY over the
  same window, beta from the trailing 120 sessions of daily returns
  known at the decision, clipped to [0, 3]. Raw returns reported too.
- **Sizing for the book**: 10% of equity in the basket, so the book's
  contribution is a tenth of the basket's return.
- **Meetings**: every scheduled decision from 2021-01-27 through
  2026-07-29 in `fomc_decisions.csv` (the 2020 rows include unscheduled
  actions and are excluded). About 45 non-overlapping windows.
- **Depth split**, written now: meetings where the basket's mean
  five-session return into the meeting is at or below −10% ("deep")
  against the rest. The hypothesis is that the reversal is a deep-selloff
  effect, so this split is primary evidence, not an afterthought.

## The bar, written now

Primary: across all meetings, the mean beta-adjusted basket return after
30 bp costs is positive with a t-statistic above 2 (windows do not
overlap, so a plain t on the meeting series applies), and positive in at
least 60% of meetings.

Secondary: the same on the deep subset alone, with at least eight deep
meetings.

- Primary passes: the rule runs as a named shadow beside the desk for
  the next six meetings, unconditional.
- Only the secondary passes: the shadow runs with the depth condition
  (fires only when the basket is at or below −10% into the meeting).
- Neither passes: "insufficient evidence to advance this specification".
  The shadow still runs as evidence, since it costs nothing and trades
  nothing, but nothing is promoted and no parameter is retuned on these
  meetings. A different specification is a new registration.

Promotion into the paper book, if ever, needs the shadow's own six
meetings to clear the same bar on untouched sessions.

## What this cannot show

Forty-five meetings on a hindsight universe is thin; the two biggest
winners were also the two deepest selloffs, so a depth rule fit here is
partly fit to July. The reversal's cause in July was earnings-season
news, not the Fed, which the specification does not separate. Intraday
timing (the first minutes after the open) is not modeled; the entry is
the open print.

## Generalisation, registered before its run

The operator asked whether the meeting matters at all. It need not: the
condition may simply be a deep five-session selloff in the book's worst
decile. The **any-day form**, registered now: on any session since
2021-01-27 where the worst decile's mean five-session return is at or
below −10% and no episode is still holding, the same basket, next-open
entry, ten-session hold, close exit, costs and beta adjustment. Episodes
cannot overlap, so their windows are independent. The same primary bar
applies (mean after 30 bp > 0, t > 2, positive in at least 60% of
episodes). If the any-day form passes and the meeting form does not, the
meeting is not the condition; the depth is.

## Results — run once on 2026-09-15 after the registrations above

Bars through 2026-09-04 on the research copy of the store. JSON beside
this file: `post-decision-reversal-2026-09-15.json` (meetings) and
`post-decision-reversal-anyday-2026-09-15.json` (any day).

**Meeting form, 45 decisions 2021-01-27 to 2026-07-29**

| basket return, mean over meetings | mean | median | sd | positive | t |
|---|---|---|---|---|---|
| raw | +3.83% | +1.92% | 9.90% | 64% | 2.60 |
| SPY over the same window | +1.10% | +0.85% | 2.80% | 67% | 2.63 |
| beta-adjusted | +1.70% | +0.37% | 7.32% | 56% | 1.56 |
| after 10 bp per side | +1.50% | +0.17% | 7.32% | 51% | 1.38 |
| **after 30 bp per side (the bar)** | **+1.10%** | −0.23% | 7.32% | **49%** | **1.01** |

Deep subset (into-meeting mean ≤ −10%): 18 meetings, +1.60% after
30 bp, t 0.74, 56% positive. Not deep: 27 meetings, +0.77%. Without
July 2026: +0.76%, t 0.71. By year after 30 bp: 2021 +0.2%, 2022 −1.9%,
2023 +5.6%, 2024 +0.5%, 2025 −0.9%, 2026 +4.2%. Book contribution at 10%
weight: about +0.11% per meeting.

**Any-day form, 95 non-overlapping episodes since 2021**

| basket return, mean over episodes | mean | median | sd | positive | t |
|---|---|---|---|---|---|
| raw | +3.11% | +1.24% | 11.07% | 61% | 2.74 |
| beta-adjusted | +1.84% | +1.00% | 9.33% | 57% | 1.92 |
| after 10 bp per side | +1.64% | +0.80% | 9.33% | 56% | 1.71 |
| **after 30 bp per side (the bar)** | **+1.24%** | +0.40% | 9.33% | **52%** | **1.30** |

Without July 2026: +1.17%, t 1.21. By year after 30 bp: 2021 +1.4%,
2022 −0.9%, 2023 +1.4%, 2024 +1.6%, 2025 +2.6%, 2026 +2.0%.

**Verdict on both: insufficient evidence to advance this specification.**
Neither the primary nor the secondary bar is met. The raw basket does
rise after a selloff, and so does SPY: most of the raw return is the
market and the basket's beta, and what is left after costs is about a
percent with a standard deviation seven to nine times larger. July 2026
is the largest single observation in either form and moves the meeting
mean by a third of a point on its own. The any-day form is the more
promising of the two, with a t of 1.3 on 95 episodes and positive means
in five of six years, but it does not clear a bar that was set to keep
one July from becoming a rule.

**What runs from here.** Both shadows record forward, trading nothing:
the meeting form opens a cycle at each decision close from 2026-09-16,
the any-day form at each trigger. Cycles fill at the next open and
close ten sessions later; the ledgers sit beside the records and the
API carries them. The same bar applies to the shadows' own cycles. A
different specification (a shorter hold, a tighter decile, a
confirmation at the open, a news condition) is a new registration, not
a retune of this one.
