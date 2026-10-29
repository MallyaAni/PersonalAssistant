# Pre-registration: 15-minute trend + VWAP-bounce execution overlay

Written 2026-10-28 before any run of the rule. Nothing below changes after the first result except
items explicitly marked "frozen after the run".

## Question

The installed grade-led rule buys at the next regular open. The owner's discretionary method is to
follow the 15-minute trend and buy a bounce off session VWAP. Does that exact mechanical rule, applied
to the installed rule's own grade-A entries, buy at a better price than the next open, after costs?

This is the rule the chart-judgment results note said had not been tested:

> The exact rule (15-minute trend filter plus VWAP entry) has not been tested. Adopting it would
> need a new pre-registration and a forward shadow, not another look at the same entries.

It is an execution overlay on entries the installed rule already takes. It is not a new selection
signal and does not change which stocks are bought.

## Relation to the chart-judgment study

The chart-judgment study (pre-registration 2026-10-27, results 2026-10-28) tested the local vision
model's multi-timeframe judgment and priced two mechanical comparators: a limit at session VWAP
(+5.0 bp) and a limit at the hourly EMA21 (+5.2 bp). The model scored +3.0 bp and failed the gate.
Neither comparator implemented the 15-minute trend filter or a bounce confirmation. This study tests
that exact rule.

## Sample

- The same 666 entries scored by the chart-judgment study: every `BUY` with `before == 0` in the
  installed replay (`research/policy-replay/leader_ewma_minB_floor50/2026-10-23`, 95 names), decided
  on or after 2016-02-01, minus the 30-entry pilot and minus the 4 entries with no Alpaca bars
  (DELL 2017-04-03, 2017-09-15, 2018-09-10; SMCI 2019-09-09).
- The entry list is read from `~/dsv41/vision/main.jsonl` (`ticker`, `decided`) so the sample is
  exactly the one already scored. No new entries are added.
- Entries decided 2016-02-02 through 2026-10-16; all windows end on or before 2026-10-23 and are
  fully covered by the bar fetch.

## Bars

- Alpaca 15Min, split-adjusted (`adjustment=split`), same source as the chart-judgment study.
- SIP 2016-01-01.. (04:00-20:00 ET); BOATS 2024-09-16.. (20:00-04:00 ET).
- Merged and labelled exactly as `chartlib.prepare`: SIP is authoritative 04:00-20:00, BOATS only
  fills the overnight session; session is overnight 20:00-04:00, pre 04:00-09:30, regular
  09:30-16:00, post 16:00-20:00 (bar start, ET); an overnight bar belongs to the next trading day.
- The trading calendar is the set of regular sessions with at least 20 AAPL bars, as in the
  chart-judgment runner.
- Split check before scoring: NVDA around 2024-06-10 (10:1) must show a continuous adjusted series
  (pre-split closes near 120, not 1,200). If the fetched series is not adjusted, stop.

## Decision window (ET)

- Signal session t: `decided` is the session whose close produced the grade.
- Baseline A fills at the open of the first regular 15-minute bar of t+1 (09:30).
- The overlay may trigger from the first bar starting at or after 20:00 ET on t when BOATS data
  exists (t >= 2024-09-16), otherwise from 04:00 ET on t+1.
- Triggers are evaluated at every 15-minute bar close in the window. The last trigger bar must end
  at or before 15:00 ET on t+5. The window's forced fill is at the close of the last regular bar of
  t+5.
- If t+5 has no regular bars for the ticker, the forced fill is at the close of the last regular bar
  in the window. If the window has no regular bars at all, the entry is unscored and counted.

## Indicators (computed from bars whose end time is <= the trigger bar's end)

- EMA9 and EMA21 on 15-minute closes over all visible bars in the merged feed (including extended
  and overnight bars), using the recursive EMA in `chartlib.ema` (span 9 and 21).
- Session VWAP: typical price (high + low + close) / 3, multiplied by volume, cumulated from the
  session anchor, divided by cumulated volume. Day-session anchor 04:00 ET; overnight anchor
  20:00 ET. Same formula and anchors as `chartlib.snapshot` / `chartlib.indicators`.
- A missing or zero volume bar leaves VWAP NaN at that bar; a trigger cannot use a NaN indicator.

## The rule (frozen before the run)

Rule name: `trend-vwap-bounce/1`. At bar i, trigger a buy when all five hold:

1. bar i is not the first bar of its session (at least one earlier bar in the same session);
2. EMA9(i) > EMA21(i);
3. close(i-1) > VWAP(i-1) (price was above VWAP before the pullback);
4. low(i) <= VWAP(i) (the bar touched or pierced VWAP);
5. close(i) > VWAP(i) (the bar closed back above VWAP).

The first bar in the window satisfying all five is the trigger. The buy fills at the open of the
first bar starting at or after the trigger bar's end. If no bar starts before the forced close, the
entry is forced at the close of the last regular bar of t+5.

## Fill simulation and costs

- Overlay B: fill at the open of the first bar starting at or after the trigger bar's end. If the
  trigger is at 14:45-15:00 ET on t+5, the fill is the 15:00 bar open, which is before the 16:00
  forced close.
- Forced: close of the last regular bar of t+5, session regular, cost 5 bp.
- Costs (one side, bp): regular 5, pre-market/after-hours 15, overnight 30. A pays 5.
- A: open of the first regular bar of t+1.

## Primary statistic

Per entry: `improvement_bp = 1e4 * (ln P_A - ln P_B) - (cost_B - cost_A)`, where `cost_B` is the
cost of the fill bar's session and `cost_A` is 5 bp. Both arms are assumed to hold to the same later
date, so the entry-price difference is the whole difference in outcome.

## Gate (all three must pass)

- G1: mean improvement > 0 and the month-block bootstrap (2000 draws, resampling calendar months)
  95% CI lower bound > 0.
- G2: placebo. For each of 50 seeds, permute the trigger bar offsets across entries: the offset is
  the index of the trigger bar from the first bar of the entry's window, with a sentinel for forced
  entries. Each entry is then filled at the bar at that offset in its own window, using the same
  fill rule and costs; an offset beyond the entry's window is forced at the close. B's mean must
  exceed the 90th percentile of the 50 placebo means. This keeps the distribution of waiting times,
  session mix and forced share, and removes only the chart-specific trigger.
- G3: mean improvement > 0 in 2016-2020 and 2021-2026 separately.

## Reported, not gated

- Trigger count, forced count, fill session mix, share of triggers in each session, mean bars waited.
- Improvement by year; 2026 entries separately (the sample's 42 entries decided in 2026).
- B-veto: entries never triggered; their 20- and 60-session forward returns from A's fill vs the
  triggered ones.
- Diagnostics, each reported only and not part of the gate:
  - trend-only: trigger on EMA9(i) > EMA21(i) and close(i) > VWAP(i), without the bounce
    conditions (3)-(5); fill at the next bar open;
  - VWAP-limit-in-uptrend: when EMA9(i) > EMA21(i), place a limit at VWAP(i) for the next bar;
    fill if that bar's low < VWAP(i) at min(open, VWAP(i)); re-place at every bar close;
  - the chart-judgment mechanical comparators (limit at session VWAP +5.0 bp, hourly EMA21
    +5.2 bp) and the model's +3.0 bp, quoted from the results note.
- The diagnostics use the same fills and costs. They are not gated because the gate was fixed for
  the primary rule; a diagnostic that looks better is a candidate for a new pre-registration, not
  a promotion.

## Look-ahead controls

- Visibility: the indicator at bar i reads only bars with `end <= end(i)`. The fill reads only bars
  starting at or after `end(i)`. The forced fill reads only bars in the window.
- Perturbation test: for a fixed sample of 100 triggers, multiply every bar after the trigger bar's
  end by a random factor in [0.95, 1.05]; the trigger index and the indicator values up to the
  trigger must be identical. Change the trigger bar's close by +1% and the trigger set or the
  indicator at that bar must change for at least one sampled case.
- Fill test: a trigger at bar i can only fill on a bar starting at or after `end(i)`; a decision at
  15:00 ET of t+5 cannot fill after the 16:00 forced close.
- Split check as above.

## Stop conditions

- If fewer than 90% of the 666 entries have both a baseline A bar and a full window, stop and report
  coverage before reading the gate.
- If the fetched SIP bars for a ticker start after an entry's `decided`, that entry is unscored and
  counted.
- A failed gate closes `trend-vwap-bounce/1`; it is not retried with a different EMA length, VWAP
  anchor, bounce definition, trigger frequency or window without a new pre-registration saying what
  changed and why.

## What passing buys

Only the next step: an account-level replay through `policy_book` with B's fills, then a forward
shadow on live data. No live change on this result alone.

## Clarifications

- No model call and no prompt in this study; the rule is fully mechanical. The model's +3.0 bp is
  quoted only as a comparator.
- The sample is the installed rule's own book, not the point-in-time S&P 500 universe. The result is
  an execution overlay on that book, not a new signal; a PIT-universe replication is a separate
  pre-registration if this overlay passes.
- The rule is evaluated at every 15-minute bar, not only at the chart-judgment checkpoints. The
  window, baseline A, costs and improvement formula are otherwise the same as the chart-judgment
  study.
