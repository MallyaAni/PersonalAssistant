# Pre-registration: grade-B entry timing on the current panel (grade-C diagnostic)

Written 2026-10-29 before any run of the B or C sample on the current panel. This
replaces the sample of `grade-b-vwap-overlay-preregistration-2026-10-29.md`, which
stopped at its baseline reproduction check before either arm was read. The rule,
window, fills, costs and gate are unchanged; the sample changes from the installed
replay's panel to the current panel, and this note says what changed and why.

## Why the first B/C pre-registration stopped

The first note required the current `desk.run` panel, truncated to 2026-10-23, to
reproduce the installed replay manifest `leader_ewma_minB_floor50/2026-10-23`
exactly. It does not. The replay was generated under `fomc-3-session-weakness/2`
and an older `policy_book.py`; the current code runs `fomc-hold-through-meeting/1`
(the pre-meeting cut was retired on 2026-10-28) and the funded-scaling simulator.
The source hashes in the replay manifest confirm the code vintage:
`event_risk.py` 34462a0…, `policy_book.py` 9955963…, replay CLI a97ebb6…; the
current deploy checkout is `event_risk.py` a4444ec…, `policy_book.py` 5d9124d…,
replay CLI 225266a…. The current baseline book summary on the same truncated panel
differs from the replay manifest by:

| Metric | Replay manifest | Current baseline | Diff |
|---|---:|---:|---:|
| all CAGR | 36.16% | 38.92% | +2.76 pp |
| all max drawdown | −28.27% | −27.70% | +0.57 pp |
| all Sharpe | 1.4089 | 1.4927 | +0.0838 |
| all total | +3,415% | +4,154% | +739 pp |
| to_2022 CAGR | 19.68% | 22.02% | +2.34 pp |
| to_2022 max drawdown | −28.27% | −27.70% | +0.57 pp |
| to_2022 Sharpe | 0.9252 | 1.0162 | +0.0910 |
| to_2022 total | +301.5% | +358.4% | +57.0 pp |
| from_2023 CAGR | 77.17% | 81.00% | +3.84 pp |
| from_2023 max drawdown | −25.38% | −24.91% | +0.47 pp |
| from_2023 Sharpe | 2.2284 | 2.2961 | +0.0678 |
| from_2023 total | +775.5% | +845.3% | +69.8 pp |
| fills | 7,201 | 7,413 | +212 |
| costs | 70,087.80 | 87,657.88 | +17,570.07 |

The replay's book cannot be reproduced from today's code, so the first note's
stop condition fired and neither the B nor the C arm was read. No B/C execution
result exists. This note does not retry that sample; it registers a new sample on
the current panel, which is the book the live rule actually runs now.

## Question

The installed rule enters only at A/A+ (`entry_grade=2`) and holds through B
(`hold_grade=1`); it never buys a B name. If the rule admitted B names, the
selection would be weaker and the entry windows may not drift up as much as the
grade-A windows did. Does the same mechanical `trend-vwap-bounce/1` rule improve
the entry price on B first entries? And, as a diagnostic, on C first entries?

The grade-A overlay failed all three gate components: 648 triggered entries
averaged −42.1 bp, and the registered −20.5 bp came from 18 forced fills in
falling windows. The grade-A windows drift up, so waiting for a VWAP bounce buys
higher than the next open. This is a new sample on the current panel, not a retry
of the grade-A rule.

## Sample

- Book panel: the current report and panel the nightly decides from
  (`desk.run` with `FUNDAMENTALS_CURRENT`, the current deploy code
  `5b54b96e` / `fundamentals-features/6`), truncated to 2026-10-23. The panel has
  2,970 sessions, 94 names plus the benchmark column.
- Policy runs with the production `policy_book.simulate`, all other fields at the
  installed defaults (minimum trade 1%, band block, FOMC, target 0.25, exposure
  floor 0.5, 10 bp in the policy run):
  - baseline: `Rule()` (`entry_grade=2`, `hold_grade=1`), the current installed
    rule; its book summary is recorded beside the replay manifest's summary above;
  - B arm: `Rule(entry_grade=1, hold_grade=1)`;
  - C arm: `Rule(entry_grade=0, hold_grade=0)`.
- The current code's FOMC policy is `fomc-hold-through-meeting/1`; the
  pre-meeting cut is retired, so `event_risk.live_path` returns full exposure on
  every session. The `fomc` flag stays at the installed default `True`. The B/C
  arms run under the same policy as the current baseline.
- B entries: every first buy (`action == "BUY"`, `before == 0`) whose grade at
  `decided` is B, decided 2016-02-01 through 2026-10-16. C entries: the same with
  grade C from the `entry_grade=0` run. The date floor and cutoff match the
  grade-A study so every window is fully covered by the Alpaca bar fetch. Entries
  after 2026-10-16 are excluded and counted.
- The sample count is reported. If the B sample is below 100 entries, stop and
  report before reading the gate.
- The four book tickers not in `main.jsonl` (ARM, GLXY, GOOGL, TXN) are fetched
  with the same SIP and BOATS settings.

## Bars

- Alpaca 15Min, split-adjusted, SIP 04:00-20:00 ET from 2016-01-01 and BOATS
  20:00-04:00 ET from 2024-09-16, merged and labelled exactly as
  `chartlib.prepare`.
- Split check before scoring: NVDA around 2024-06-10 must show a continuous
  adjusted series (pre-split closes near 120, not 1,200). If the fetched series is
  not adjusted, stop.
- Coverage: at least 90% of the B sample must have both a baseline A bar and a
  full window. Unscored entries are counted and reported.

## Rule, window, fills and costs

Exactly `trend-vwap-bounce/1`, unchanged:

- Signal session t: `decided` is the session whose close produced the grade.
  Baseline A fills at the open of the first regular 15-minute bar of t+1 (09:30).
- The overlay may trigger from the first bar starting at or after 20:00 ET on t
  when BOATS data exists (t >= 2024-09-16), otherwise from 04:00 ET on t+1.
  Trigger bars end at or before 15:00 ET on t+5. The forced fill is the close of
  the last regular bar of t+5, or the last regular bar in the window if t+5 has
  none.
- EMA9 and EMA21 on 15-minute closes over all visible bars in the merged feed,
  using `chartlib.ema`. Session VWAP: typical price times volume cumulated from
  the session anchor (04:00 ET day, 20:00 ET overnight), divided by cumulated
  volume.
- At bar i, trigger when all five hold: (1) bar i is not the first bar of its
  session; (2) EMA9(i) > EMA21(i); (3) close(i-1) > VWAP(i-1); (4) low(i) <=
  VWAP(i); (5) close(i) > VWAP(i). The first such bar is the trigger.
- Fill at the open of the first bar starting at or after the trigger bar's end,
  before the forced close. Costs one side: regular 5 bp, pre-market and
  after-hours 15 bp, overnight 30 bp. A pays 5 bp.
- `improvement_bp = 1e4 * (ln P_A - ln P_B) - (cost_B - cost_A)`.

## Primary statistic and gate

The B arm is primary; the C arm is reported only and is not gated.

- G1: B mean improvement > 0 and the month-block bootstrap (2,000 draws,
  resampling calendar months) 95% CI lower bound > 0.
- G2: placebo. For each of 50 seeds, permute the trigger bar offsets across B
  entries (the offset is the index of the trigger bar from the first bar of the
  entry's window, with a sentinel for forced entries). Each entry is filled at the
  bar at that offset in its own window, using the same fill rule and costs; an
  offset beyond the entry's window is forced at the close. The B mean must exceed
  the 90th percentile of the 50 placebo means.
- G3: B mean improvement > 0 in 2016-2020 and 2021-2026 separately.

The grade-A result is quoted as a comparator, not a gate.

## Selection diagnostic (reported before the execution gate)

- The B and C policy books' CAGR, Sharpe and drawdown (all, to 2022, from 2023)
  beside the current baseline's book summary on the same truncated panel.
- The B and C entries' 20- and 60-session forward returns from A beside the
  published grade-A entries' forward returns.
- The share of the book in B and C entries and the number of B and C first
  entries.

A pass on the execution gate does not justify buying B or C names. The selection
question is separate and needs a point-in-time-universe pre-registration. If the
B policy's book is worse than the current baseline, the B extension is not a live
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
- The current baseline is recorded, not required to reproduce the old replay
  manifest; the old replay's code vintage is gone and the first B/C note already
  stopped on it. If the current baseline itself cannot be computed, stop and
  report.
- A failed B gate closes the B extension. It is not retried with a different grade
  cut, EMA length, VWAP anchor, bounce definition, trigger frequency or window
  without a new pre-registration saying what changed and why.
- The C arm is a diagnostic; a pass is a candidate for a new pre-registration, not
  a promotion.

## What passing buys

Only a candidate for a separate point-in-time-universe selection study and a
forward shadow. No live change on this result alone. The live rule stays frozen
through the 252-session review.

## Clarifications

- The B and C entries are hypothetical; the installed rule enters at A/A+ only.
- The sample is the current rule's own book, not the point-in-time S&P 500
  universe. A PIT replication is a separate pre-registration if this execution
  study passes.
- No model call and no prompt; the rule is fully mechanical.
- The rule is evaluated at every 15-minute bar, not only at the chart-judgment
  checkpoints. The window, baseline A, costs and improvement formula are the same
  as the grade-A overlay.
- The first B/C note is stopped, not retried. This note registers a new sample on
  the current panel and states the changed baseline and the retired FOMC policy.
