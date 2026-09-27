# The trading system: what "best" means here, and the order of work

Written 2026-09-15 from the evidence of the last two weeks. The desk's
purpose is a book of AI and software names sized by a fixed, explained
rule, run every night, traded in a paper account, judged only on sessions
it had not seen. "Best" is not the highest backtest; every backtest here
carries a universe chosen in 2026 with hindsight. Best is: correct data,
a nightly that always finishes, measurement that cannot flatter, and a
strategy that changes only when untouched sessions say so.

## What the evidence has settled

- **No learned model has beaten the rule or equal weight** on corrected
  data: ridge, trees and the frozen network all sit at or below equal
  weight over 2024–2026; the valuation increment over momentum and risk
  has a combined t of 0.05. Both lines are closed. The rule is the
  baseline, not "the best".
- **The rule's own backtest was flattered by the data**: on as-of filing
  versions the valuation rule's retrospective return fell from about
  +255% to +150%. Data correctness comes before any strategy question.
- **Operations lose sessions**: a widened tone step ran 13 hours past
  the close and wrote no record; the ML observer's guard skipped the
  session silently. A nightly that does not finish is worse than any
  model choice.
- **Price sensitivity in sizing has not been shown to help**: the
  candidate was indistinguishable from the rule; the tilt stays at zero.

## The order of work

1. **Correct data, seen before it is used.** Every filed version kept
   (`fundamentals_asof`); the plain rule on as-of data recorded beside
   the frozen path each night (`fundamentals_asof` in the record, live
   since 2026-09-15). After a week of blocks, the value analyst reads the
   as-of levels and the frozen path becomes the shadow. Then the same
   discipline for the other inputs: tone under a stated prompt version,
   filings by acceptance time, bars complete before anything reads them.
2. **A nightly that always ends with a record.** One run at a time (the
   store's lock), a time budget on the only step that can run for hours
   (release tone, default three hours, unscored names carry earlier
   scores), the ML observer's receipt in the record so a lost
   observation is visible, and every refresh failure named. Next: a
   red status on the dashboard when the last session has no record by
   a deadline, and the same for a missing observation.
3. **Measurement that cannot flatter.** The scorecard prices every
   strategy by name across untouched sessions at stated costs; the frozen
   ML accounts do the same for the network. Membership is recorded from
   now on so a future evaluation can be point in time. Any change to the
   rule runs first as a named shadow beside it for a season, with the
   gate written before the first session; passing means advancing, and
   failing means "insufficient evidence", never a retune on the same
   sessions.
4. **Execution and risk, measured.** Fills against the decision's
   reference price per order; slippage and cost as a series on the
   scorecard; the drawdown limit, the volatility target and the regime
   exposure kept as they are unless a shadow shows better on untouched
   sessions.
5. **Strategy last, and only by the gate.** Candidates are welcome as
   shadows: the history reference alone, a sector-neutral value leg, an
   exit rule. None is adopted on a backtest of this universe.

## Where it stands (kept current)

- 2026-09-15: stage one of the fundamentals correction live (as-of block
  in every record); the nightly under a lock with a tone budget, per-name
  failure isolation, the observer's receipt and the revision it started
  from; the page names a late record or observation; the FOMC overlay's
  gate registered and priced nightly against the book that never traded
  it; execution against the decision price as a series. Open: stage two
  of the fundamentals switch after a week of blocks; the FOMC verdict
  after six meetings; nothing on strategy.

- 2026-09-26: the first point-in-time scorecard
  ([pit-scorecard-2026-09-26.md](research/pit-scorecard-2026-09-26.md)).
  On the names the desk could have known about (dated membership file,
  `market_membership`), the rule earns what QQQ earns (paired t -0.28) and
  trails the equal-weight point-in-time book by about 7 CAGR points (t
  -1.80); the 23-point gap to the today's-book curve is the hindsight
  choice of names. The hurdle for every candidate from here is equal weight
  on the point-in-time universe at 25 bp on 2016-2023. First arm scored,
  `signed_rotation`: FAILED gate H (median -1.4 / -1.5 points on the
  choosing window); insufficient evidence, live rule unchanged. Next arm:
  capped equal weight across every A/A+ name (P1.2).

- 2026-09-26, evening: six arms scored on the point-in-time book
  ([pit-arms-2026-09-26.md](research/pit-arms-2026-09-26.md)). Equal
  weight of every A/A+ member, fully invested, earns 29.9% on 2016-2023 at
  25 bp against 14.4% for the frozen rule (20/20 offsets) and 27.7% for
  equal weight of every member (19/20, t 1.5): the grade selects a little,
  and the sizing layer on top of it (inverse volatility, the 0.30 target,
  regime multipliers, top-decile concentration) is what has been losing
  about 15 points a year. Under the 20% hold limit (`ew_graded_20`): 28.3%,
  level with equal weight, 14 points over the rule in every offset -
  **the `/4` candidate, to the fidelity shadow next.** Both learned
  rankers and the day-type classifier: insufficient evidence; the price
  ranker fails outright.

- 2026-09-26, late: `graded-equal-weight/4` policy + shadow ledger, BUILT
  (`desk/policy_v4.py`, `desk/shadow_ledger.py`, the nightly's
  `_policy_shadows` hook and `record["policy_shadows"]`). The policy
  reproduces the scorecard's `ew_graded_20` arm return for return in the
  simulator (asserted at four offsets and both costs); the nightly now
  observes a dry-run ledger for it beside the live `/3` book every session
  - whole shares, next-open fills at 10 bp, cash never negative, the
  arm's 20-session reset clock - and writes its receipt into the record,
  or a note when it could not. It never places an order. Open: the first
  live observation on the Spark (the code has not run against the store),
  then the 4-6 week fidelity judgment (order agreement with a simulator
  replay, tracking, negative-cash sessions, fills per order class); the
  status row belongs in the volatile-book architecture doc's table when
  that branch lands, and `agent-trading-desk.svg` needs re-rendering
  (source updated, no browser in the sandbox).

- 2026-09-27: `1fc59696` deployed - the `/4` shadow, the SIP fifteen-minute
  store and the point-in-time browser test together (gates 7,543 / 100
  passed). First shadow receipt due Monday 2026-09-28. The SIP backfill is
  running on spark1 (about 15,000 requests, not the estimated 1,633: Alpaca
  pages at about 1,000 bars; estimator fixed) and the 2016-2018 exchange
  calendar is now reviewed from the official releases. Open: the reconcile
  verdict, the nightly SIP append, the candidate line on the dashboard.

- 2026-09-27: the `/4` candidate line is on the dashboard, BUILT
  (`market_daily._candidate_curve`, `curve_block["candidate_point_in_time"]`,
  a third series and a `CAGR, candidate /4` cell in `DeskPanel`). It is
  priced plain - next-open fills at the default cost, the arm's rebalance
  clock, no exits, none of the live execution policy - so its number is
  the scorecard's `ew_graded_20` line, asserted equal to 1e-12 on the same
  report and sessions, and not a live record; what the candidate's
  execution earns stays the fidelity shadow's question. The browser spec
  (`desk-candidate-line.spec.ts`) has not run in the sandbox: UNVERIFIED
  until the next deploy's Playwright run.

- 2026-09-27: grade parity, BUILT (`backend/market/grade_parity.py`,
  `backend.cli.market_grade_parity`, the nightly's `_grade_parity` hook,
  `record["grade_parity"]`, `/desk` `grade_parity`, the red `Grade parity`
  alert above the board). Every night after the record: each name's live
  grade against the point-in-time replay of the same report on the same
  session, membership both ways against `membership_history.csv`, and the
  record's targets against `live_policy.targets` to 1e-9; a mismatch is
  written to `desk/grade_parity.json`, printed as `GRADE PARITY MISMATCH`
  into the nightly log, put on the record and shown on the board with the
  names and "do not trade from this board". The nightly never raises on it.
  The rule for the operator: a red parity banner means the board is not
  evidence tonight - run `python -m backend.cli.market_grade_parity --root
  data/market`, read which names and which kind (grade, membership,
  targets, session), and look at `membership_history.csv` for those names
  and at the store's newest partition dates against the record's session
  before anything is sized. Open: the first live run on the Spark; the
  browser spec (`desk-grade-parity.spec.ts`) has not run in the sandbox.

- 2026-09-27: session anatomy, the first fifteen-minute study, BUILT and
  not run (`market/sip_cube.py`, `market/session_anatomy.py`,
  `cli/market_session_anatomy.py`). Session cubes from the SIP store with
  an on-disk cache; variance and extreme-slot shares, the open drive,
  dips and extensions at fixed slots and thresholds, fill costs against
  the open; every t on the daily cross-sectional average at HAC lag 5;
  the book pooled on point-in-time membership, benchmarks apart; 2016-2023
  choosing, 2024-2026 reported. The hypotheses are in the module
  docstring, written before any number exists. There are no results: the
  command has not run against the store. Next: run it on the Spark, read
  the tables against the hypotheses, and record the result as a research
  note before anything downstream uses it.

- 2026-09-27, morning: the SIP fifteen-minute store is filled and accepted
  ([research/sip-15m-acceptance-2026-09-27.md](research/sip-15m-acceptance-2026-09-27.md)):
  the closing auction was the missing quarter of every day's volume and
  is now a stored row; the 2016-2018 half days are repaired. The first
  fifteen-minute study ran
  ([research/session-anatomy-2026-09-27.md](research/session-anatomy-2026-09-27.md)):
  the day is front-loaded (22% of variance in the first bar), the first
  half-hour predicts nothing, intraday dips continue slightly rather than
  bounce, and fill timing is worth 1-4 bp against a 186 bp session sd.
  The fifteen-minute engine's edge, if any, is below the session or in
  conditioning the desk does not yet do; execution timing is not it.

- 2026-09-27, later: the hold cap priced
  ([research/cap-sweep-2026-09-27.md](research/cap-sweep-2026-09-27.md)):
  eight caps on the point-in-time book. The cap binds only when fewer
  names qualify than it allows and its whole cost is idle cash: 19 CAGR
  points from 5% to 20%, 1.2 from 20% to 25%, 0.2 to 33%, nothing above.
  It buys a bound on one name (worst single-name day 3.1% at 20%, 3.6% at
  25%, 5.8% uncapped). 20% is the knee, the conservative end of a flat
  region; the candidate stays there for the shadow and the limit is the
  operator's to move before the shadow's verdict, not after.

- 2026-09-27, evening: the policy's decisions on the ticker chart, BUILT
  (`desk/decision_history.py`, the history files' `target_weight` /
  `delta_weight` / `action` columns, `policy`, `decision_note` and
  `fills`, `market_daily --history-only`, decision and fill markers plus a
  text list in `TickerChart`). The operator asked to see, for each stock,
  the buy/sell/hold recommendation with its size back in time beside the
  grade markers, to check entries and exits against price. The series is
  `policy_v4.targets` replayed on the point-in-time membership mask (a
  name has no decision before it joined), dated to the close it was
  decided at; the paper account's real fills come out of the nightly
  records. Display only, nothing trades. Backend tests pass (13 new); the
  browser spec (`chart-decision-history.spec.ts`) and `tsc` have not run
  in the sandbox: UNVERIFIED until the next deploy. Open: backfill on the
  Spark with `python -m backend.cli.market_daily --history-only
  --data-dir data/market` before the nightly next rewrites the files.

- 2026-09-27, late: stage 1 of the deep-intraday plan, BUILT and not run
  ([research/deep-intraday-plan-2026-09-27.md](research/deep-intraday-plan-2026-09-27.md);
  `market/deep_intraday.py`, `market/deep_intraday_cnn.py`,
  `cli/market_deep_intraday.py`). One question, kill criteria fixed
  before the first fit: does a small sequence model on five sessions of
  fifteen-minute bars carry out-of-sample information about the next
  session that the grade does not already have? Ridge and a temporal CNN,
  rank and volatility targets, walk-forward with a purge, the daily IC
  and the cost-charged top-quintile portfolio against equal weight (and
  against equal weight of the A/A+ names), volatility R² against trailing
  volatility, the volatility control; INSUFFICIENT EVIDENCE unless IC t
  and portfolio t both clear 2.0 on 2016-2023. Four trials. The synthetic
  tests find a planted signal and nothing in noise; the CNN has run
  nowhere yet. Next: `python -m backend.cli.market_deep_intraday --root
  data/market` on spark1's CPUs (one evening), the result as a research
  note, and stage 2 only if the verdict is PASSED.

- 2026-09-27, night: the ticker chart at fifteen minutes, BUILT
  (`market/ticker_chart_intraday.py`, `timeframe=15m` on
  `/desk/chart/{ticker}` with `sessions` 1..60, the `15m` button and
  sessions selector in `TickerChart`). The operator could not tell from a
  daily candle when in the session a buy, trim or sell happens. The view
  draws the last N complete sessions of raw SIP fifteen-minute bars
  (auction bar included) and marks the decision on the last bar before
  the close it was made at, where it fills (next open for a buy, next
  close for an ordinary sell, from `market_daily._submit`'s order types)
  and the paper account's real fills on the bar they crossed in. Display
  only. Backend tests pass (10 new); `chart-15m.spec.ts` and `tsc` have
  not run in the sandbox: UNVERIFIED until the next deploy.

- 2026-09-27, evening: stage 1 of the deep-intraday plan run
  ([research/deep-intraday-stage1-2026-09-27.md](research/deep-intraday-stage1-2026-09-27.md)):
  ridge, temporal CNN, PatchTST and a frozen Chronos-Bolt encoder all find
  the same thing on the fifteen-minute bars - a cross-sectional return
  signal of IC 0.01 that loses 6-13 bp a day after costs, and a
  volatility forecast that beats trailing volatility (CNN R² 0.27).
  INSUFFICIENT EVIDENCE for returns; RL sizing does not start; the
  volatility head goes to a sizing trial on the graded book.

- 2026-09-27, night: the catastrophe stop, RUN and RECORDED
  ([research/catastrophe-stop-2026-09-27.md](research/catastrophe-stop-2026-09-27.md)):
  a stop 50% below entry fired zero times in ten point-in-time years, 60%
  below the peak zero times; the stops that did fire (2020-03-18, spring
  2022, CRWD's 2024 outage) were all false alarms and cost 0.1-1.4 CAGR
  points. Worst single-name day -2.7% of equity (2016-2023), -3.6%
  (2024-2026). Every stop RECORD; the universe, the equal-weight cap and
  the grade rotation are the protection, and they are sufficient. Built
  as (`market/catastrophe_stop.py`, `python -m
  backend.cli.market_catastrophe_stop`;
  [research/catastrophe-stop-plan-2026-09-27.md](research/catastrophe-stop-plan-2026-09-27.md)).
  The operator asked how the graded equal-weight book avoids a Lucid-type
  collapse; today only the grade rotation and the equal-weight cap bound
  a single name's loss. Seven variants fixed before the run - the control
  and a sale on the first close 40, 50 or 60% below the entry close or
  below the peak close since entry - each a registered trial on the pit
  scorecard's offsets and costs under plain fills, with a cooldown that
  keeps a stopped name out until the mask has excluded it for a cycle.
  Reports the worst single-name day, triggers a year and the false-alarm
  rate beside the usual medians. A stop is ADOPT (registered) only within
  0.5 CAGR points of the control while saving 3 drawdown points or 25% of
  the worst single-name day and not worse on 2024-2026; else RECORD, with
  the insurance premium priced. `simulate.run` gained the optional
  `weight_filter` hook (None is byte-identical). Ten tests pass on the
  synthetic book; the command has not run against the store. Next: run it
  on the Spark (280 simulator runs), record the note, and change the
  executor only if the verdict names a stop.

- 2026-09-27, night: volatility sizing on the `/4` book, BUILT and not run
  ([research/vol-sizing-plan-2026-09-27.md](research/vol-sizing-plan-2026-09-27.md)):
  the CNN's next-session volatility forecast (R² 0.27 against trailing)
  as the sizing input for the graded equal-weight book, in six registered
  variants and the control - inverse volatility, a no-leverage volatility
  target and the hybrid, each fed the forecast and fed trailing volatility
  as its twin - priced under plain and under live options
  (`market/vol_forecast.py`, `market/vol_sizing.py`, `python -m
  backend.cli.market_vol_forecast`, `python -m
  backend.cli.market_vol_sizing`). ADOPT (registered) only with a point
  over the control at t >= 2 under live options, drawdown not worse, not
  worse on 2024-2026, and half a point over the trailing twin; a gain the
  trailing twin matches is recorded as inverse vol, not the forecast.
  Prior: 0-2 points either way, the forecast adding little over trailing.
  Next: export the forecasts on the RTX from the stage-1 dataset, run the
  trial on the Spark (560 simulator runs), record the note.

- 2026-09-27, night: the execution ablation, RUN and RECORDED
  ([research/execution-ablation-2026-09-27.md](research/execution-ablation-2026-09-27.md)):
  the whole 4.3-point gap is `live_midcycle` (removing it: 27.8% against
  23.2% on 2016-2023) but at paired t 0.5 - a difference of paths, not an
  edge - and on 2024-2026 the same option earns 5 points and 10 points of
  drawdown. Every option KEEP; the executor is unchanged. Built as
  (`market/execution_ablation.py`, `python -m
  backend.cli.market_execution_ablation`). The fill-timing trial
  ([research/execution-timing-2026-09-27.md](research/execution-timing-2026-09-27.md))
  showed the band gate on buys is neutral, so the 4.4 CAGR points the live
  execution policy costs the `/4` book on 2016-2023 at 25 bp belong to the
  other live conventions. Ten variants fixed before the run - plain, live,
  live with each of `block_overbought`, `exit_at_close` (with
  `deferred_buys`, which needs it), `green_day_skip`, `live_midcycle`,
  `deferred_buys` and the FOMC path removed, plain with `exit_at_close` or
  the FOMC path added - each a registered trial, paired against both plain
  and live at every offset and cost. A removal is REMOVE (registered) only
  at >= 1.0 CAGR point with paired t >= 2.0 on 2016-2023 and not worse on
  2024-2026; the sum of single removals is set against the plain-minus-live
  gap so an interaction is visible. Eight tests pass on the synthetic book;
  the command has not run against the store. Next: run it on the Spark
  (about 400 simulator runs), record the note, and change the executor
  only for options the verdict names.

## What is not on the list

No new model without a specific hypothesis and an agreed evaluation
budget; no tuning on 2024–2026, which every line here has now touched;
no sizing change that cannot be traced to a recorded shadow's untouched
sessions; and nothing that reads a private or paid data source.
