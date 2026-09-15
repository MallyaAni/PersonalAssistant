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

## Results

Filled in by `python -m backend.cli.market_reversal --backtest` after
this file was committed; see the section appended below and the JSON
beside it.
