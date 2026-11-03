# Turnover diagnosis: pre-registration — 2026-11-03

Status: **pre-registration**. Written and committed before the first run.
Research only: this note changes no live rule, order, grade, prompt or risk
dial. It is milestone 2 of `docs/trading/PROGRAM-DIRECTION.md`, after the
`/3` install completed milestone 1.

## The question

The installed `grade-led-leader-weight/3` has a scorecard turnover of
8.44x/year at the median offset, 25 bp (the previous `/2` joint was 8.61x).
The live paper account's first 37 sessions, run under `/1`, show 430,776.63
of filled notional over an average equity of 97,239.94 in 0.1468 years, or
about 30.2x/year gross (15.1x one-way). The program target is about 2x/year.
Why is the live path roughly 3.6 times the scorecard's turnover, and which
source dominates?

This study decomposes the gap. It does not search for a better rule.

## Fixed cadence arms (measurement only)

The scorecard simulator rebalances on `paper.REBALANCE_EVERY = 20` sessions
and holds shares between rebalances. The installed live holding policy plans
on every session (`GradeLedLeaderFundedPolicy.plan` has no cadence gate), with
the 1% minimum trade. The fixed cadence set isolates that difference:

| arm | construction | purpose |
|---|---|---|
| `cadence_1` | installed `/3` allocator, `rebalance=1` | live-like daily sizing |
| `cadence_5` | installed `/3` allocator, `rebalance=5` | weekly-ish |
| `cadence_10` | installed `/3` allocator, `rebalance=10` | biweekly |
| `cadence_20` | installed `/3` allocator, `rebalance=20` | the researched arm and reproducibility check |
| `cadence_63` | installed `/3` allocator, `rebalance=63` | quarterly-ish |

All arms use the honest S&P 500 point-in-time universe, 2026-10-30 vintage,
installed analyst votes, the installed `/3` allocator
(`leader_ewma_minA_floor50_live`), 20 offsets, costs 10 and 25 bp. Turnover is
read at the median offset, 25 bp, from the simulator's own `turnover` metric
(notional traded per year over the average account). Performance is reported
for every arm but is **descriptive**: the cadence set is not a parameter
search and the best-performing cadence is not selected. The candidate rule is
fixed by the decision rule below, not by the table.

The live-side decomposition uses the paper account's filled orders, the same
source as `sector-flow-overlay-results-2026-11-02.md`: filled notional by
order reason, annualized over average equity and elapsed years. If the ledger
does not carry a reason for every fill, the study classifies by the order
metadata it does carry and states the limitation; it does not invent reasons.

## Decision rule (pre-registered)

The **dominant source** is the category with the largest share of annualized
live gross notional. Cadence is declared dominant only if both conditions
hold:

1. daily sizing (the `cadence_1` arm) has turnover more than twice the
   `cadence_20` arm; and
2. the `cadence_1` arm's turnover is at least 80% of the live paper's
   30.2x/year gross measurement, so daily sizing on the scorecard reproduces
   or exceeds the live turnover magnitude. It may exceed it: the scorecard
   simulator applies the engine's 0.5% minimum trade, while the installed
   policy applies 1%, so a higher scorecard daily turnover is expected and is
   still evidence that daily sizing is the source of the gap.

The live ledger's reason decomposition is supporting evidence for the source,
not a gate: if the ledger cannot classify fills by reason, the study reports
that limitation and relies on the two measurable conditions above.

If cadence is dominant, the candidate fix is: **the live holding policy
resizes on the engine's existing 20-session rebalance cadence, keeping grade
exits immediate.** This introduces no new parameter; 20 is
`paper.REBALANCE_EVERY`, already used by the scorecard and the desk's paper
plan. The fix is measured as `cadence_20` against `cadence_1`.

If cadence is not dominant, this study tests no fix. It writes the
decomposition, names the dominant source and stops; the next diagnosis or fix
is a separate pre-registration.

## Gate for the candidate fix

`cadence_20` must beat `cadence_1` on turnover and be non-inferior on
performance, at 25 bp, all-window, 20 offsets, paired daily at the median
offset:

- turnover at least halved: `cadence_20` turnover <= 0.5 x `cadence_1`
  turnover;
- median CAGR no more than 0.50 points lower than `cadence_1`;
- median Sharpe no more than 0.03 lower than `cadence_1`;
- median drawdown no more than 1.00 point deeper than `cadence_1` (the
  median across offsets; worst drawdown is reported descriptively);
- paired mean daily difference (20-session minus 1-session) HAC t > -2.0 and
  month-block bootstrap 95% lower bound > -1.0 bp/day, seed 20261102;
- report the same at 10 bp.

The gate compares the fix to the live-like arm, not to the installed `/3`
reference: the installed reference is `cadence_20` by construction, so a
comparison to it would be a reproducibility check, not evidence. A fix that
halves turnover but loses more than the tolerances above fails and is not
prepared for a release.

## Reproducibility and multiplicity

`cadence_20` must reproduce the ablation's installed `/3` control at 25 bp:
median CAGR `0.13275424766467725`, median Sharpe `0.8160719928118282`, median
drawdown `-0.343922645227457`, worst drawdown `-0.3942116034315978`, and
turnover `8.43752949642906`x/year. If any does not reproduce, stop and
investigate before reading any other arm.

Five cadence arms, fixed before the run; the trial count is recorded. The
deflated Sharpe is descriptive and is not used to rescue a result. There is no
new signal, so the information-shuffle placebo does not apply; the cadence
variants are mechanical changes to when the same allocator is applied.

## Windows and data

The all-window result is the gate; 2016-2023 and 2024-2026 are reported and
never tuned on. Broad honest report, installed analyst votes (value 3,
fundamental 1, technical 1, sentiment 1), dated membership file, 20 offsets,
costs 10 and 25 bp, seed 20261102. Record the code revision and the store
as-of date in the result. All allocators are causal by construction; the
cadence change only changes when the same trailing information is applied.

## What passing buys

A passing candidate fix is prepared as a candidate folder for a **separate**
release, with the owner's decision required. It does not install itself. The
installed `/3` forward record restarted on 2026-11-03; installing a cadence
change would restart it again, so the owner weighs the turnover gain against
another forward-record reset. No live change during the forward record except
an owner-authorized simplification or a correctness fix.

## What this study is not

It is not a search for the best rebalance cadence. It is not a claim that 20
sessions is optimal; it is the engine's existing researched cadence. It does
not diagnose the leader-tilt, volatility-target or minimum-trade components
beyond the cadence comparison; if one of those dominates, that is a separate
pre-registration. It does not treat the 37-session live measurement as a
stable estimate: the window is short, includes the initial build from cash and
the crash rebalancing, and annualizing it is noisy. The scorecard decomposition
is the reproducible evidence; the live ledger is the mandate check.
