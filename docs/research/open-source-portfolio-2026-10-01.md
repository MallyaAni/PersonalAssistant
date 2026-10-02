# Covariance-aware sizing: fixed research protocol

Registered before market outcomes on `codex/open-source-research-20261001`.
No live allocation, order dispatch, grade computation or main deployment changes.

**Current status: VERIFIED implementation and qualified conditional backtest;
reject adoption.** The independent [solver review](portfolio-solver-review-2026-10-01.md)
resolved the initial numerical failure with an equivalent direct quadratic
formulation using skfolio's same fitted covariance. All 101 historical fits
returned optimal, and 497 applicable tests passed. The candidate materially
underperformed the `/5` target control at both declared costs. The failure
history below records the earlier submission, not the final source status.

The existing `/4` inverse-volatility and volatility-target study found all six
variants worse than its control. This study tests covariance allocation rather
than repeating those trials. Lower variance does not imply higher total gain.

One candidate: `skfolio-covariance-sizing/1-research`, minimum variance with
[skfolio MeanRisk](https://skfolio.org/generated/skfolio.optimization.MeanRisk.html)
and Ledoit-Wolf covariance from the preceding 252 completed adjusted-close
returns. No expected-return predictor, grid search or outcome-driven selection.
Only the supplied date's point-in-time members graded A/A+ qualify. Gross is
`min(1, qualifying count * 0.25)`, identical to `graded-equal-weight/5`.
Each name is capped at 25%; remaining capital earns zero cash yield.

Total L1 change from the candidate's previous declared target is bounded by the
greater of the same reset's `/5` declared target turnover and the exact minimum
needed to satisfy the new eligible capped simplex. Mandatory exits and changed
gross are therefore feasible. Every relaxation is recorded. This target-change
constraint is not a claim about realized account turnover; the latter is reported
from the funded ledger. There is no arbitrary fitted turnover threshold.

Decisions use the original source-row-zero 20-session cadence, with an initial
close-time instruction at the declared account start. Fills occur at the next
adjusted open through the existing `allocation_replay` and `simulate._Book`:
actual cash, no leverage or assumed same-batch sale funding, fees, positions and
retry accounting. Missing covariance history makes the whole candidate basket
explicitly unavailable/cash and remains in the common opportunity denominator.
Missing execution prices or optimizer/dependency failures refuse the run.

Controls: `/5` target rule, equal weight across all dated book members without
grade selection, SPY and QQQ. All five use the same continuous funded account,
decision/fill prices, cadence and 10/25 bp one-way costs. This isolates sizing;
it does not reproduce live intraday dip timing, FOMC pauses or exit overlays.
Report CAGR, positive drawdown loss, zero-cash-yield Sharpe, annualized actual
one-way turnover, fees and common-calendar 252-session rolling win rates.
Split 2016–20 and 2021–26 only where source coverage exists; account state is
never reset at reporting boundaries. A truncated window is labelled by its
actual first/last sessions, not implied to cover missing years.

Inputs must be an immutable NPZ plus JSON: dated open/close/adjusted-close,
integer grades, Boolean membership, ordered symbols, explicit price basis,
grade/membership evidence mode, source hashes and snapshot hash. Recomputed
current-vintage grades are conditional research, never archived historical
eligibility or exact live reconstruction. A declaration is not proof of source
publication time. No performance-based adoption is automatic.

## Implementation and acceptance

Three owned code/test files implement the optional adapter, hash-bound CLI and
independent acceptance. `skfolio==1.4.10`, CVXPY and CLARABEL were exercised on
CPU in `/home/animallya96/scratch/open-source-runtime-20261001`; no GPU, model
service, live checkout, source store or broker changes. Code was mounted in
`/home/animallya96/scratch/open-source-source-20261001`. The 119-case targeted
suite passed in 1.63 s, including real optimizer fits, actual CLI, funded opening
gaps, independent journal replay, no-cash fallback, prefix causality, scale
equivalence, mandatory exits and existing `/5`/allocation-replay acceptance.
All three tested source hashes matched the branch files; Ruff and diff checks
passed. A dedicated case refuses `optimal_inaccurate` even with feasible weights.

Snapshot: 2,953 source sessions, 96 symbols, through 2026-09-30,
`portfolio.npz` SHA256
`8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58`.
Source prices are frozen September-30 vendor bytes; historical grades are
reconstructed current-vintage rows from October-1 histories; membership is the
committed dated research file. This is conditional evidence, not an original
historical advice archive or independent untouched test period.

## Initial numerical boundary: FAILED, subsequently resolved

The initial fixed diagnostic produced feasible bounded weights, retained three
unavailable candidate resets and returned a provisional table, but CLARABEL
emitted 21 inaccurate-solution warnings. Feasibility alone does not establish
minimum variance. The implementation now requires `problem_.status == OPTIMAL`;
the initial full-history acceptance refused its first unqualified solution,
wrote no successful replacement artifact and promoted nothing. The earlier table must
not be presented as a qualified backtest.

Three targeted hypotheses were investigated: analytically return the uniquely
feasible capped or zero-turnover allocation; express the exact minimum-turnover
boundary as equivalent monotone constraints; rescale the positive optimization
objective on the captured failing fit. The first two improve individual cases
without changing the declared feasible set; the full run still refuses, and
the rescaling diagnostic did not resolve it. Further numerical edits stopped
under the repository's three-hypothesis rule. Next investigation: numerical
solver/dual-residual review or an independent CPU solver certificate, preserving
the frozen allocation objective and all constraints. No outcome tuning.

Minimal real failure retained at Spark `/tmp/codex-skfolio-first-failure.npz`:
252 returns by seven names, gross approximately 1, prior selected weights about
0.75, mandatory exits about 0.25, total target turnover about 0.5. No personal
holdings or credentials appear in it. All source/result artifacts remain in
`/home/animallya96/scratch/open-source-inputs-20261001`.

The initial provisional 25 bp full-window CAGR was 21.13% for the candidate,
29.65% for the `/5` daily control, 26.93% for PIT equal weight, 15.05% SPY and
20.29% QQQ. Candidate drawdown loss was 42.33% versus `/5` 45.24%. These are
recorded solely to preserve the abandoned numerical diagnostic, not evidence
for deployment. Return-maximization support was absent even before the stricter
numerical rejection. The live strategy remains unchanged.

Diagram impact: NONE — optional research code reuses existing data/accounting
boundaries and has no production caller.

Run the final fixed implementation in the isolated dependency environment:

```bash
python -m backend.cli.market_open_source_portfolio \
  --snapshot /absolute/portfolio.npz --provenance /absolute/portfolio.json \
  --output /absolute/new-portfolio-result.json
```

The final qualified artifact is `portfolio-results-qualified-qp.json` in the
original Spark research input directory. Source/input/output hashes, numerical
certificate, full cost/split tables and coverage are in the solver review.
