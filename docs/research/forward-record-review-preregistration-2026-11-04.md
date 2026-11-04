# 252-session forward record review: pre-registration — 2026-11-04

Status: **pre-registration**. Written and committed before the record's first
session, against a zero-session record. Research and review design only: this
note changes no live rule, order, grade, prompt or risk dial. It is milestone
5 of `docs/trading/PROGRAM-DIRECTION.md`, whose forward record is the
out-of-sample arbiter for the installed `grade-led-leader-weight/3`.

## The question

Does the installed `/3` rule work out of sample on the live paper account over
252 sessions? The review answers five things, in this order:

1. Did the rule breach the live risk mandate (worst drawdown no deeper than
   about -35%)?
2. Did the account beat SPY over the same sessions, the program objective's
   forward test?
3. Is the forward-record component of the top-tier claim met (CAGR above QQQ
   and forward Sharpe at least 1.0)?
4. Did every scheduled session complete and did the rule run as contracted?
5. What was the realized turnover against the 2x/year program constraint?

It does not search for a better rule, and it does not evaluate performance
before the record ends.

## The record

**Start.** The first completed ordinary nightly after the 2026-11-04
report-bound repair deploy is the baseline session. Its equity entry in
`data/market/paper/state.json` is the record's starting equity. The first
`/3` orders from that plan fill at the next open, so the first daily return is
the baseline session's close to the next session's close.

**Length.** The record is the next 252 completed return sessions after the
baseline. A return session is a session with an equity entry in the paper
state; its return is that entry's equity over the previous entry's equity.
The review runs after the 252nd return session's nightly. The baseline session
has no `/3` return and is not counted.

**Completed session.** A session counts when the ordinary nightly wrote a
fresh `desk/strategy-recommendations/latest.json` for that session and
appended that session's equity entry to `paper/state.json`. A fresh
publication with no equity entry, or an equity entry with no fresh
publication, is not a completed session and is reported as a defect.

**Missed sessions.** A scheduled trading session with no completed nightly is
listed with its cause. The clock counts completed return sessions, so a missed
session extends the record's calendar end; it does not shorten it. A gap
between recorded sessions is one multi-session return in the series, flagged
and listed. Three or more consecutive missed sessions, or ten or more in
total, is an operational failure and triggers an owner review before the
record continues.

**Voids.** The record restarts, and this pre-registration no longer applies to
the new record, if any of these changes during it: the policy version; any
grade boundary, sizing parameter, execution rule, universe or risk dial; a
correctness fix that changes any decision, sizing, grade or execution; a paper
account reset, broker change or starting-equity change. A fix that changes
only reporting, alerts or non-trading views does not void the record and is
recorded. Any live change requires the release ceremony and the owner's
authorization; the direction doc's no-interim-change rule stands.

## Data sources

- `data/market/paper/state.json`: the `history` equity entries (the account's
  recorded equity, cash and positions per session) and the `journal` filled
  orders. The broker's recorded equity is the live truth; the review does not
  re-mark the book from bars.
- `data/market/desk/asof=<session>/desk.json`: the paper block and the
  published plan per session.
- `data/market/desk/strategy-recommendations/latest.json` and the publication
  files it points to: the session's published plan and its report-bound
  identity.
- `data/market/desk/nightly-health.json` and `nightly-readiness.json`: the
  nightly verdicts and account snapshots.
- SPY and QQQ bars in the store, adjusted close, on the record's session dates.

## Metric definitions

These match `backend/cli/market_pit_scorecard.py:window_stats` so the forward
record and the research scorecard are read the same way.

- **Daily return:** `r_t = equity_t / equity_{t-1} - 1` for consecutive
  recorded sessions. `n` is the number of returns; the baseline entry has no
  return. A gap return spans the missed sessions and is flagged.
- **CAGR:** `(equity_last / equity_base) ** (252 / n) - 1`. The curve starts
  at 1.0 on the baseline equity, as the scorecard's does.
- **Max drawdown:** `min(curve / running_peak - 1)` over the curve including
  the baseline. Report the trough and peak dates.
- **Sharpe:** `mean(r) / std(r, ddof=1) * sqrt(252)`, no risk-free
  subtraction, matching the scorecard.
- **Benchmarks:** SPY and QQQ daily returns from adjusted close on the same
  session dates; the same CAGR, drawdown and Sharpe definitions. A benchmark
  with no bar on a record date is a data defect: report and stop, never
  interpolate.
- **Paired evidence (descriptive):** account minus SPY daily differences;
  Newey-West t at lag 20 and a month-block bootstrap (2,000 draws, seed
  20261102) with the 95% lower bound; PSR. These are reported but are not
  gates: one path has low power.
- **Turnover:** filled gross notional in the return window divided by average
  equity divided by `n / 252` years. Gross notional is
  `sum(abs(filled_qty * filled_price))` over filled journal rows whose
  `execution.filled_at`, converted to the New York date, falls in the return
  window. One-way turnover is gross divided by two. Rows with no
  `execution.filled_at` are listed and excluded, with the count reported.

## Decision criteria (pre-registered)

The verdict is mechanical; the action is the owner's, per the direction doc's
decision rights.

| criterion | measure | threshold | verdict if it fails |
|---|---|---|---|
| live risk mandate | max drawdown over the record | no deeper than -35% | **mandate breach**; the program recommends the owner consider the B hold |
| program objective | account CAGR minus SPY CAGR | at least 0 | **objective not met out of sample**; the program recommends the owner consider the B hold or a pre-registered simplification |
| top-tier eligibility | account CAGR vs QQQ CAGR; forward Sharpe | above QQQ and at least 1.0 | **top-tier claim not met**; it is not claimed, and no live change follows from this alone |
| operational | 252 completed return sessions; fresh publication and equity entry each | no unexplained miss | **operational failure** if 3+ consecutive or 10+ total misses; diagnose and fix through the correctness path |
| turnover | gross x/year and one-way x/year | report against the 2x/year program constraint | **constraint failure** recorded; no rule change follows from this record |
| simplification | contract conformance (below) | no divergence | **contract divergence**; any divergence is a defect and triggers an owner review |

**Contract conformance checks.** Every publication carries the report-bound
identity (`report_context`, no learned close context), the policy is `/3`, the
plan's names are within the installed risk bank, the grades come from the
authenticated nightly report, execution is next open, and no learned
distribution, monthly model or fifteen-minute timing is consulted. The removed
P/E tilt is not measurable on a single live path and no claim is made about
it.

**Reading the result.** The risk mandate and the objective are the primary
verdicts. The top-tier line is a claim gate, not an action gate. Turnover is a
program constraint with a known, unresolved failure; the record measures it
and does not select a cadence change. The verdict is written as the
pre-registered rule reads, with the numbers beside it; thresholds are never
adjusted after seeing the data.

## Statistical honesty

A single 252-session path cannot confirm Sharpe 1.0 at conventional
significance. With `T` years the asymptotic standard error of an annualized
Sharpe is about `sqrt((1 + SR^2 / 2) / T)`; at `T = 1` and `SR = 0.8` it is
about 1.1. The forward Sharpe is therefore reported as a point estimate with
that caveat, and the top-tier claim is descriptive. The honest-universe
backtest remains the statistical evidence; the forward record tests
execution, operations, the mandate and whether the live path behaves as
contracted.

No interim performance verdicts. Nightly health, freshness and fills are
checked operationally every day; performance is not read for a keep/switch
decision before the 252nd return session. There are no arms, no parameter
search and no multiplicity correction to apply: the trial count is one.

## Reproducibility

The review script is written at review time, committed with the result, and
implements the definitions above exactly. It reads the state file and the
bars, reports `n`, the baseline and final equity, the calendar span and the
missed-session list, and must reproduce the first and last equity entries by
hand-check. The result records the code revision, the store as-of date and the
state file hash. It does not rewrite the state or any live artifact.

## What passing and failing buy

- **All primary criteria pass:** the record supports keeping `/3` for the next
  period. No live change. If the top-tier line also passes, the forward-record
  component of the top-tier claim is met; the claim is stated with the
  statistical caveat above.
- **Mandate breach or objective missed:** the program writes the verdict and
  recommends the owner consider the B hold (entry A, hold B) or a
  pre-registered simplification. Either is a live change through the release
  ceremony, restarting the record; the B hold's evidence is the research
  scorecard, not a fabricated live comparison.
- **Operational or contract failure:** diagnose and fix through the
  correctness path. A fix that changes economics voids the record; a fix that
  changes only reporting does not.
- **Turnover above 2x:** recorded as a program constraint failure. It is not a
  rule verdict and does not by itself justify a live change.

## What this review is not

- It is not a significance test of the backtest, and it does not compare the
  account's CAGR to the honest-universe 13.28%: the live book is the
  AI/software mandate (94 names), not the honest S&P 500 universe.
- It is not a parameter search, and it does not tune any threshold after the
  data.
- It is not a live B-hold comparison; no B-hold shadow exists on the paper
  account.
- It is not a claim about the removed P/E tilt, the learned monthly model, the
  timing publication or the fifteen-minute execution; the contract does not
  consult them, and no live evidence about them is produced.
- It is not a reason to change the rule mid-record. The direction doc's rule
  stands: no interim live change except an owner-authorized simplification or
  a correctness fix.
