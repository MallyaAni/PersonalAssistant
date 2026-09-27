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

## What is not on the list

No new model without a specific hypothesis and an agreed evaluation
budget; no tuning on 2024–2026, which every line here has now touched;
no sizing change that cannot be traced to a recorded shadow's untouched
sessions; and nothing that reads a private or paid data source.
