# Simplicity/ablation audit: pre-registration — 2026-11-03

Status: **pre-registration**. Written and committed before the first run. The
owner's decision of 2026-11-02 selected the simplicity/ablation audit as the
first study and conditionally authorized installing a simpler rule if the
ablation shows one is at least as good. Research only: this note changes no
live rule, order, grade, prompt or risk dial.

This is the study required by milestone 1 of
`docs/trading/PROGRAM-DIRECTION.md`. It asks whether each component of the
installed joint rule earns its complexity on the honest S&P 500 point-in-time
universe, and whether a simpler rule is at least as good.

## The question

On the honest S&P 500 point-in-time universe, current code, 25 bp, 20 start
offsets, does each installed component add value over the grade-only baseline,
and is a simpler rule at least as good as the installed joint?

The installed joint is `grade-led-leader-weight/2` sizing: A-or-better held
set, equal slots tilted by trailing 63-session return rank (strength 0.5),
EWMA-20 volatility target 0.25 with exposure floor 0.5, 25% per-name cap, and
P/E-history tilt 0.5. The grade hold is fixed at A; A versus B is closed by
`installed-rule-significance-results-2026-11-02.md`. The 1% minimum trade and
next-open execution are engine settings, fixed, not ablation components.

## Fixed arms (no parameter search)

The chain is additive and fixed before the run. The 25% cap is a risk limit:
it is measured for attribution but is not a candidate for removal. Arms 1 and
2 omit the cap and are measurement-only; arm 2b is the supplementary
cap-retained arm that makes the volatility-target decision meaningful when the
cap is retained.

| arm | construction | component added | candidate? |
|---|---|---|---|
| 1 | `ew_graded_full` | grade-only: A/A+ equal weight, no cap, fully invested | no (no cap) |
| 2 | `_leader_ewma(strength=0.0, floor=0.0, cap=1.0)` | EWMA-20 volatility target 0.25, no cap | no (no cap) |
| 2b | `_leader_ewma(strength=0.0, floor=0.0, cap=0.25, target=1e9)` | grade-only + 25% cap, no volatility target | yes |
| 3 | `_leader_ewma(strength=0.0, floor=0.0, cap=0.25)` | + EWMA-20 volatility target 0.25 | yes |
| 4 | `_leader_ewma(strength=0.0, floor=0.5, cap=0.25)` | + exposure floor 0.5 | yes |
| 5 | `leader_ewma_minA_floor50` | + leader tilt 0.5 over 63 sessions (scorecard ordering) | yes |
| control | `leader_ewma_minA_floor50_live` | live ordering, no P/E | yes |
| 6 | `leader_ewma_minA_floor50_pe` | + P/E-history tilt 0.5 over 756 sessions (live ordering; installed joint) | reference |

Notes on the construction:

- Arm 1 is `point_in_time.graded_equal_weight_allocator(mask, min_grade=A,
  cap=1.0, gross=1.0)`.
- Arms 2, 2b, 3 and 4 use the scorecard's `_leader_ewma` factory with the
  stated parameters. Arm 2b's `target=1e9` makes the volatility scale 1, so it
  is grade-only plus the cap.
- Arm 5 is the registered scorecard arm: the same factory with the defaults
  `strength=0.5`, `window=63`, `target=0.25`, `cap=0.25`, `span=20`,
  `floor=0.5`, `min_grade=A`.
- The control and arm 6 use the live ordering (`_leader_live`), which sizes
  the A-or-better held set with `leader_weights`: leader tilt, optional P/E
  multiplier, volatility target with floor, then the 25% cap.
- The joint result shows the scorecard-versus-live ordering difference is
  immaterial (0.009 CAGR points, 0.03 drawdown points, 0.001 Sharpe), so the
  scorecard-ordering chain is a faithful attribution. The control is the clean
  P/E comparison because it differs from arm 6 only by the P/E tilt.

The supplementary arm 2b is not a search. It is the cap-retained form of the
grade-only baseline, required because the cap is a risk limit that every
candidate must retain. Without it, a decision to remove the volatility target
would have no measured cap-retained candidate.

## The decision rule (pre-registered)

All comparisons are at 25 bp, all sessions, 20 offsets, paired daily at the
median offset (offset 10, the convention of the prior studies). The paired
test reports the mean difference in bp/day, a Newey-West t at lag 20, and a
month-block bootstrap 95% interval (2,000 draws, seed 20261102).

**Marginal significance.** A component's marginal is the paired daily
difference between the adjacent arms that differ only by that component:

| component | decision marginal | cross-check |
|---|---|---|
| volatility target | arm 3 minus arm 2b (cap retained) | arm 2 minus arm 1 (no cap) |
| 25% cap | arm 3 minus arm 2 (descriptive only; cap not removable) | arm 2b minus arm 1 |
| exposure floor | arm 4 minus arm 3 | — |
| leader tilt | arm 5 minus arm 4 (scorecard ordering) | control minus arm 4 (live ordering) |
| P/E-history tilt | arm 6 minus control (live ordering) | — |

A marginal is **statistically significant** if the Newey-West t is at least
2.0 in absolute value and the bootstrap 95% interval excludes zero on the same
side as the point estimate. Otherwise it is not significant.

**Non-inferiority.** For each candidate arm, compare the candidate to arm 6
(the installed joint). Removing a component is within tolerance if all of:

- median CAGR no more than 0.50 points lower than arm 6;
- median Sharpe no more than 0.03 lower than arm 6;
- median worst drawdown no more than 1.00 point deeper than arm 6;
- paired daily mean HAC t greater than -2.0;
- bootstrap 95% lower bound greater than -1.0 bp/day.

The medians are across the 20 offsets. The paired test is at the median
offset. The drawdown fields are the scorecard's `median_drawdown` (the median
across offsets of each offset's worst drawdown) and the worst offset.

**Removal and keeping.** A component is **removed** if its decision marginal
is not statistically significant and its removal is within tolerance. A
component is **kept** if its marginal is statistically significant or its
removal breaches the tolerance.

- The 25% cap is never removed. It is a risk limit, and its marginal is
  reported for attribution only.
- The exposure floor is a risk control. It is removed only if the candidate
  without it is within the non-inferiority tolerance and the candidate's
  median drawdown remains no deeper than -35.00%, the program objective's
  research gate. The worst-offset reading is reported; the installed joint
  already fails the live -35% mandate at -39.237%, so that failure is not
  attributed to the floor and is not repaired by this study.
- A component whose marginal is significantly negative is reported as a
  measured cost. The pre-registered rule as written keeps it, because the
  rule removes only insignificant components; the owner may direct a separate
  removal. The study does not remove it on its own.

**The candidate.** The candidate is the simplest arm among arms 2b, 3, 4, 5,
the control and 6 that is within the non-inferiority tolerance and whose
removed components each have a non-significant decision marginal. If P/E is
removed, the candidate is the control (live ordering, no P/E), because it
matches the live ordering and the ordering difference is immaterial. If the
leader tilt is removed, the candidate is arm 4 (or the cap-retained
equivalent); if the floor is also removed, arm 3; if the volatility target is
also removed, arm 2b.

If the candidate is arm 6, keep `/2` and close the ablation. If the candidate
is simpler than `/2`, the program prepares it for installation under the
owner's conditional authorization. A candidate that increases turnover
relative to arm 6 is not eligible; if no non-inferior arm meets the turnover
constraint, keep `/2`.

**Turnover.** Report annualized one-way notional traded divided by average
equity for every arm, the same definition as the sector-flow study. The
candidate must not increase turnover relative to arm 6.

**Objective.** Report the program objective for every arm: median Sharpe at
least 1.0, median CAGR above SPY, and the median and worst drawdown readings.
A simpler arm that passes the objective is the strongest outcome. A simpler
arm that is non-inferior but still fails the objective is still the better
live rule because it is simpler and lower-turnover; the next focus is the
universe/mandate, not another overlay.

## What passing buys

If the simplest non-inferior candidate is simpler than `/2`, the program
prepares a candidate folder under
`docs/research/trading-approval-candidates-<date>/<name>/`, a policy version
`/3`, the next contract revision, the full gate, the release ceremony,
`scripts/deploy.sh`, admission ADMITTED, a fresh ordinary nightly and the
following real session on the paper account. The 252-session forward record
restarts under `/3`. The install is the owner's conditional authorization of
2026-11-02; the study itself changes nothing.

If no simpler arm qualifies, keep `/2`, record the verdict, and move to
milestone 2 (turnover diagnosis). Do not install a rule the evidence does not
support.

## Data, windows and reproducibility

- Store: `/home/animallya96/deploy/anios/data/market`, as of the last complete
  session at run time; record the as-of date.
- Report: `market_universe_hindsight_research.broad_report(store)`, regraded
  with the installed analyst votes (`value` 3, `fundamental` 1, `technical` 1,
  `sentiment` 1).
- Membership: `~/dsv41/universe/sp500_membership_history.csv` (dated file, no
  survivorship).
- Offsets: 20. Costs: 10 and 25 bp; the gate is 25 bp.
- Windows: all sessions is the gate; 2016-2023 and 2024-2026 are reported and
  never tuned on.
- Seed: 20261102. Bootstrap: month-block, 2,000 draws, 95% interval.
- HAC: Newey-West t at lag 20.
- PSR and deflated Sharpe: descriptive, with the trial count from the program
  of record; neither is used to rescue or condemn a result.
- Base reproducibility check: arm 6's all-window 25 bp median CAGR must equal
  `0.13650402269141293`. If it does not, stop and investigate before reading
  any arm.
- Record the code revision (`git rev-parse HEAD`) and the store as-of date in
  the result. The pre-registration is committed before the first run. No
  live-path code changes are planned for this study; the script lives at
  `~/dsv41/universe/simplicity_ablation.py`.
- Script pattern: `~/dsv41/universe/joint_config.py` and `sector_flow.py`.
  Payloads: `simplicity_ablation_<arm>.json` and
  `simplicity_ablation_summary.json` under `~/dsv41/universe/`.

## Look-ahead and multiplicity

- The leader tilt reads only the trailing 63-session return window (64
  closes); the P/E rank reads only the trailing 756 readings ending on t, with
  at least 250 readings; the volatility scale reads only the trailing basket
  through t. The membership file is dated. Every allocator is causal by
  construction.
- The chain is fixed before the run: six chain arms, one supplementary
  cap-retained arm and one control. No search over strength, floor, window,
  cap, target or span. The trial count is recorded; the deflated Sharpe is
  descriptive.
- The 20 offsets are phase offsets of one history, not independent trials.
  The paired daily tests are the inferential unit; the offset sign is
  descriptive.
- A significantly negative component is reported, not silently removed; the
  removal rule is the one above, fixed before the run.

## What the study does not do

- It does not change the live rule, place orders, change grades, prompts or
  risk dials, or write into the live store outside `research/`.
- It does not retry the failed sector-flow, QQQ-brake or timing ideas.
- It does not search parameters or add overlays.
- It does not treat a non-inferior backtest as forward evidence. The
  252-session forward record remains the out-of-sample arbiter.

## Change log

- **2026-11-03:** created and committed before the first run.
