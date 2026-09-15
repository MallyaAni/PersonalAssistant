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

## What is not on the list

No new model without a specific hypothesis and an agreed evaluation
budget; no tuning on 2024–2026, which every line here has now touched;
no sizing change that cannot be traced to a recorded shadow's untouched
sessions; and nothing that reads a private or paid data source.
