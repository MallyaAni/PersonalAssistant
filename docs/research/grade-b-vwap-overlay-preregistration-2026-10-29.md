# Pre-registration: grade-B entry timing with the trend + VWAP-bounce overlay (grade-C diagnostic)

Written 2026-10-29 before any run of the B or C sample. Nothing below changes after
the first result except items explicitly marked "frozen after the run".

## Question

The grade-A overlay (`trend-vwap-bounce/1`) failed all three gate components. The 648
entries that triggered averaged −42.1 bp; the registered −20.5 bp came from 18 forced
fills in falling windows. The grade-A windows drift up, so waiting for a VWAP bounce
buys higher than the next open.

The installed rule enters only at A/A+ (`entry_grade=2`) and holds through B
(`hold_grade=1`); it never buys a B name. If the rule admitted B names, the selection
would be weaker and the windows may not drift up as much. Does the same mechanical
rule improve the entry price on B first entries? And, as a diagnostic, on C first
entries?

This is a new sample, not a retry of the grade-A rule. The rule, window, fills, costs
and gate are unchanged; the sample changes from grade-A entries to grade-B first
entries. The pre-registration says what changed and why.

## Relation to prior studies

- `trend-vwap-bounce/1` grade-A result: −20.5 bp, 95% CI [−43.9, +4.0], placebo 90th
  percentile −15.1, both halves negative; the rule is closed.
- Chart-judgment LLM study: +3.0 bp, confidence interval spanning zero; closed.
- The installed rule is `grade-led-leader-weight/1`: `entry_grade=2`, `hold_grade=1`,
  replayed as `leader_ewma_minB_floor50/2026-10-23` (94 names, through 2026-10-23).
- The B and C entries are hypothetical extensions. The installed rule does not buy
  them. The result is an execution diagnostic, not a live change.

## Sample

- Book panel: the same report and panel the installed replay uses (`desk.run` with the
  current fundamentals mode), truncated to the replay's through date (2026-10-23) so
  the installed rule reproduces the replay manifest exactly.
- Policy runs with the production `policy_book.simulate`, all other fields at the
  installed defaults (minimum trade 1%, band block, FOMC, target 0.25, exposure floor
  0.5, 10 bp in the policy run):
  - baseline: `Rule()` (`entry_grade=2`, `hold_grade=1`), must reproduce the installed
    replay's book summary;
  - B arm: `Rule(entry_grade=1, hold_grade=1)`;
  - C arm: `Rule(entry_grade=0, hold_grade=0)`.
- B entries: every first buy (`action == "BUY"`, `before == 0`) whose grade at
  `decided` is B, decided 2016-02-01 through 2026-10-16. C entries: the same with
  grade C from the `entry_grade=0` run. The date floor and cutoff match the grade-A
  study so every window is fully covered by the Alpaca bar fetch. Entries after
  2026-10-16 are excluded and counted.
- The sample count is reported. If the B sample is below 100 entries, stop and report
  before reading the gate.
- The four book tickers not in `main.jsonl` (ARM, GLXY, GOOGL, TXN) are fetched with
  the same SIP and BOATS settings.

## Bars

- Alpaca 15Min, split-adjusted, SIP 04:00-20:00 ET from 2016-01-01 and BOATS
  20:00-04:00 ET from 2024-09-16, merged and labelled exactly as `chartlib.prepare`.
- Split check before scoring: NVDA around 2024-06-10 must show a continuous adjusted
  series (pre-split closes near 120, not 1,200). If the fetched series is not
  adjusted, stop.
- Coverage: at least 90% of the B sample must have both a baseline A bar and a full
  window. Unscored entries are counted and reported.

## Rule, window, fills and costs

Exactly `trend-vwap-bounce/1`, unchanged:

- Signal session t: `decided` is the session whose close produced the grade. Baseline
  A fills at the open of the first regular 15-minute bar of t+1 (09:30).
- The overlay may trigger from the first bar starting at or after 20:00 ET on t when
  BOATS data exists (t >= 2024-09-16), otherwise from 04:00 ET on t+1. Trigger bars
  end at or before 15:00 ET on t+5. The forced fill is the close of the last regular
  bar of t+5, or the last regular bar in the window if t+5 has none.
- EMA9 and EMA21 on 15-minute closes over all visible bars in the merged feed, using
  `chartlib.ema`. Session VWAP: typical price times volume cumulated from the session
  anchor (04:00 ET day, 20:00 ET overnight), divided by cumulated volume.
- At bar i, trigger when all five hold: (1) bar i is not the first bar of its session;
  (2) EMA9(i) > EMA21(i); (3) close(i-1) > VWAP(i-1); (4) low(i) <= VWAP(i);
  (5) close(i) > VWAP(i). The first such bar is the trigger.
- Fill at the open of the first bar starting at or after the trigger bar's end, before
  the forced close. Costs one side: regular 5 bp, pre-market and after-hours 15 bp,
  overnight 30 bp. A pays 5 bp.
- `improvement_bp = 1e4 * (ln P_A - ln P_B) - (cost_B - cost_A)`.

## Primary statistic and gate

The B arm is primary; the C arm is reported only and is not gated.

- G1: B mean improvement > 0 and the month-block bootstrap (2,000 draws, resampling
  calendar months) 95% CI lower bound > 0.
- G2: placebo. For each of 50 seeds, permute the trigger bar offsets across B entries
  (the offset is the index of the trigger bar from the first bar of the entry's
  window, with a sentinel for forced entries). Each entry is filled at the bar at
  that offset in its own window, using the same fill rule and costs; an offset beyond
  the entry's window is forced at the close. The B mean must exceed the 90th
  percentile of the 50 placebo means.
- G3: B mean improvement > 0 in 2016-2020 and 2021-2026 separately.

The grade-A result is quoted as a comparator, not a gate.

## Selection diagnostic (reported before the execution gate)

- The B and C policy books' CAGR, Sharpe and drawdown (all, to 2022, from 2023) beside
  the installed rule's book summary, on the same truncated panel.
- The B and C entries' 20- and 60-session forward returns from A beside the grade-A
  entries' forward returns.
- The share of the book in B and C entries and the number of B and C first entries.

A pass on the execution gate does not justify buying B or C names. The selection
question is separate and needs a point-in-time-universe pre-registration. If the B
policy's book is worse than the installed rule, the B extension is not a live
candidate regardless of the execution result.

## Look-ahead controls

- Visibility: the indicator at bar i reads only bars with `end <= end(i)`. The fill
  reads only bars starting at or after `end(i)`. The forced fill reads only bars in
  the window.
- Perturbation: for a fixed sample of 100 B triggers, multiply every bar after the
  trigger bar's end by a random factor in [0.95, 1.05]; the trigger index and the
  indicator values up to the trigger must be identical. Change the trigger bar's
  close by +1% and the trigger set or the indicator at that bar must change for at
  least one sampled case.
- The policy engine reads only data up to each close. The B and C samples are the
  engine's own trades, not a hand-picked list.

## Stop conditions

- B sample below 100 entries, coverage below 90%, or split check fails: stop and
  report before reading the gate.
- The baseline run with `Rule()` must reproduce the installed replay's book summary
  on the truncated panel. If it does not, stop and report.
- A failed B gate closes the B extension. It is not retried with a different grade
  cut, EMA length, VWAP anchor, bounce definition, trigger frequency or window
  without a new pre-registration saying what changed and why.
- The C arm is a diagnostic; a pass is a candidate for a new pre-registration, not a
  promotion.

## What passing buys

Only a candidate for a separate point-in-time-universe selection study and a forward
shadow. No live change on this result alone. The live rule stays frozen through the
252-session review.

## Clarifications

- The B and C entries are hypothetical; the installed rule enters at A/A+ only.
- The sample is the installed rule's own book, not the point-in-time S&P 500 universe.
  A PIT replication is a separate pre-registration if this execution study passes.
- No model call and no prompt; the rule is fully mechanical.
- The rule is evaluated at every 15-minute bar, not only at the chart-judgment
  checkpoints. The window, baseline A, costs and improvement formula are the same as
  the grade-A overlay.
