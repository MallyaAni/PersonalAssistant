# Simplicity/ablation audit: results — 2026-11-03

Status: **canonical result** for the simplicity/ablation audit (milestone 1).
Research only: this note changes no live rule, order, grade, prompt or risk
dial. Any install is a separate release-ceremony action under the owner's
conditional authorization of 2026-11-02.

**Verdict: the P/E-history tilt is removed. The candidate is
`leader_ewma_minA_floor50_live` — the live ordering without P/E. It is
non-inferior to the installed joint within the pre-registered tolerance and
has lower turnover, 8.44x a year against 8.61x, so the pre-registered rule
selects it. The other four components are kept: removing the volatility
target breaches the median-drawdown tolerance, removing the floor or the
leader tilt breaches the CAGR tolerance, and the 25% cap is a risk limit that
is never a removal candidate. The candidate still fails the program objective
— median Sharpe 0.816 against 1.0, median CAGR 13.28% against SPY's 13.67%,
worst offset -39.42% against the -35% bound — so the next focus is the
universe/mandate, not another overlay.**

This is the result of
`simplicity-ablation-preregistration-2026-11-03.md` and its amendment 1. The
pre-registration was committed at `f80f8f80` before the first run; amendment 1
was committed at `12bc3b01` before any arm was read.

## What was run

- Store: a read-only view of `/home/animallya96/deploy/anios/data/market`
  containing only partitions dated on or before 2026-10-30
  (`~/dsv41/universe/store_2026-10-30`). As-of 2026-10-30, 2,964 sessions.
- Report: `market_universe_hindsight_research.broad_report(store)`, regraded
  with the installed analyst votes (`value` 3, `fundamental` 1, `technical` 1,
  `sentiment` 1).
- Membership: `~/dsv41/universe/sp500_membership_history.csv` (dated, no
  survivorship).
- Costs: 10 and 25 bp; the gate is 25 bp. Offsets: 20. Seed: 20261102.
  Bootstrap: month-block, 2,000 draws, 95%. HAC: Newey-West, lag 20.
- Code revision: `12bc3b01be8df96ae8462b38f3dc772639e9924d`.
- Payloads: `~/dsv41/universe/simplicity_ablation_<arm>.json`; summary:
  `~/dsv41/universe/simplicity_ablation_summary.json`.

## Reproducibility

The first run used the live store, whose last complete session was 2026-11-02.
The pre-registered base check failed there: expected
`0.13650402269141293`, actual `0.13419998757629137`. The run stopped before
reading any arm.

The prior joint payload is as of 2026-10-30 with 2,964 sessions, and the
commits since that run are docs-only (`9d401771`, `f80f8f80`). Rerunning the
base arm on the 2026-10-30 view reproduces the pre-registered value exactly:
2,964 sessions, median CAGR `0.13650402269141293`. The live-store failure was
the one-session advance plus a small revision of historical adjusted closes,
not a code or data defect. Amendment 1 records the decision to run the study
on the vintage view. The live-store reading is preserved under
`simplicity_ablation_*_current_store_2026-11-02.json` as a data-advance check
and is not used for any decision.

## The result

All sessions, 25 bp, medians across the 20 offsets:

| arm | construction | CAGR | median DD | worst DD | Sharpe | above EW PIT | above QQQ | turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | grade-only, no cap, fully invested | 14.10% | -37.31% | -39.35% | 0.822 | 20/20 | 0/20 | 7.92x |
| 2 | + vol target, no cap | 12.74% | -33.23% | -36.71% | 0.812 | 20/20 | 0/20 | 7.93x |
| 2b | grade-only + 25% cap | 14.10% | -37.31% | -39.35% | 0.822 | 20/20 | 0/20 | 7.92x |
| 3 | cap + vol target | 12.74% | -33.23% | -36.71% | 0.812 | 20/20 | 0/20 | 7.93x |
| 4 | + exposure floor 0.5 | 13.07% | -34.99% | -36.71% | 0.824 | 20/20 | 0/20 | 7.91x |
| 5 | + leader tilt (scorecard ordering) | 13.28% | -34.42% | -39.42% | 0.815 | 20/20 | 0/20 | 8.43x |
| control | live ordering, no P/E | 13.28% | -34.39% | -39.42% | 0.816 | 20/20 | 0/20 | 8.44x |
| **6** | **installed joint, live ordering + P/E** | **13.65%** | **-34.56%** | **-39.24%** | **0.837** | **20/20** | **0/20** | **8.61x** |
| SPY | — | 13.67% | -33.72% | -33.72% | 0.820 | — | — | — |
| QQQ | — | 18.48% | -35.12% | -35.12% | 0.884 | — | — | — |

The 25% cap is exactly non-binding in this chain: arm 2b reproduces arm 1 and
arm 3 reproduces arm 2 to floating-point precision, because equal-weight slots
over roughly 400 eligible names are far below 25%. Its marginal is 0.0 bp/day.
It remains a risk limit and is never a removal candidate.

At 10 bp, the ordering is the same: arm 6 is 15.15% CAGR, -34.32% median
drawdown, -39.08% worst drawdown, 0.917 Sharpe; the control is 14.73%,
-34.27%, -39.34%, 0.893. The gate is 25 bp.

## Sub-periods, 25 bp

| window | arm 6 CAGR | arm 6 median DD | arm 6 Sharpe | control CAGR | control median DD | control Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 2016-2023 | 11.73% | -34.56% | 0.721 | 11.70% | -34.39% | 0.714 |
| 2024-2026 | 23.22% | -20.75% | 1.391 | 21.39% | -20.51% | 1.273 |
| all | 13.65% | -34.56% | 0.837 | 13.28% | -34.39% | 0.816 |

The 2024-2026 window is strong for every arm and beats QQQ in 18 of 20 offsets
for arm 6 and 14 of 20 for the control. It does not carry the eleven-year
objective. The 2016-2023 window is where the installed joint and the control
both sit below SPY.

## Decision marginals (with minus without, all sessions, 25 bp)

| component | with | without | mean bp/day | NW t | bootstrap 95% | PSR | significant | removed |
|---|---|---|---:|---:|---|---:|---|---|
| volatility target | arm 3 | arm 2b | -0.810 | -1.30 | -1.944 .. -0.001 | 0.049 | no | no |
| 25% cap | arm 3 | arm 2 | +0.000 | nan | +0.000 .. +0.000 | nan | no | no (risk limit) |
| exposure floor | arm 4 | arm 3 | +0.342 | 1.08 | -0.066 .. +0.909 | 0.922 | no | no |
| leader tilt | arm 5 | arm 4 | -0.087 | -0.34 | -0.596 .. +0.417 | 0.361 | no | no |
| P/E history | arm 6 | control | +0.053 | 0.39 | -0.215 .. +0.323 | 0.646 | no | **yes** |

None of the five marginals is statistically significant at the pre-registered
bar (|Newey-West t| >= 2.0 and the bootstrap interval excluding zero on the
point estimate's side).

The volatility target has a negative point estimate: it costs 0.810 bp/day and
1.37 CAGR points, but it cuts median drawdown by 4.08 points. Removing it
(arm 2b) puts median drawdown 2.75 points deeper than arm 6, beyond the
1.00-point tolerance, so it is kept as a risk control.

The floor adds 0.342 bp/day and 0.34 CAGR points while deepening median
drawdown by 1.76 points against arm 3. Removing it (arm 3) puts CAGR 0.915
points below arm 6, beyond the 0.50-point tolerance, so it is kept.

The leader tilt adds 0.214 CAGR points against arm 4, but its own marginal is
-0.087 bp/day and not significant. Removing it (arm 4) puts CAGR 0.581 points
below arm 6, just beyond the 0.50-point tolerance, so the pre-registered rule
keeps it. This is the thinnest keep in the study: the breach is 0.080 points.

The P/E tilt adds 0.375 CAGR points and 0.021 Sharpe, is not significant, and
its removal is within every tolerance. It is the only component removed.

## Non-inferiority versus the installed joint

| candidate | CAGR check | Sharpe check | median DD check | HAC t | bootstrap low | pass |
|---|---|---|---|---|---|---|
| arm 2b | pass | pass | **fail** (-37.31%) | pass | pass | **fail** |
| arm 3 | **fail** (12.74%) | pass | pass | pass | pass | **fail** |
| arm 4 | **fail** (13.07%) | pass | pass | pass | pass | **fail** |
| control | pass | pass | pass | pass | pass | **pass** |
| arm 5 | pass | pass | pass | pass | pass | **pass** |

Tolerance versus arm 6: median CAGR no more than 0.50 points lower, median
Sharpe no more than 0.03 lower, median drawdown no more than 1.00 point
deeper, paired HAC t above -2.0, bootstrap lower above -1.0 bp/day.

The control is the simplest arm that passes. It is 0.375 CAGR points and
0.021 Sharpe below arm 6, 0.167 points shallower on median drawdown, 0.184
points deeper on the worst offset, and 0.171x lower on turnover. Arm 5 also
passes but is the scorecard ordering; the pre-registration prefers the control
because it matches the live ordering and the ordering difference is
immaterial.

## Objective, all sessions, 25 bp

| arm | median Sharpe >= 1.0 | median CAGR > SPY | median DD >= -35% | offsets above QQQ |
|---|---|---|---|---|
| arm 1 | fail (0.822) | pass (14.10% vs 13.67%) | fail (-37.31%) | 0/20 |
| arm 2 | fail (0.812) | fail (12.74%) | pass (-33.23%) | 0/20 |
| arm 2b | fail (0.822) | pass (14.10%) | fail (-37.31%) | 0/20 |
| arm 3 | fail (0.812) | fail (12.74%) | pass (-33.23%) | 0/20 |
| arm 4 | fail (0.824) | fail (13.07%) | pass (-34.99%) | 0/20 |
| arm 5 | fail (0.815) | fail (13.28%) | pass (-34.42%) | 0/20 |
| control | fail (0.816) | fail (13.28%) | pass (-34.39%) | 0/20 |
| arm 6 | fail (0.837) | fail (13.65%) | pass (-34.56%) | 0/20 |

No arm passes the objective. The grade-only baseline has the highest CAGR,
14.10%, but its median drawdown is 2.75 points beyond tolerance and its worst
offset is -39.35%, so it is not a candidate. The candidate is non-inferior
but still fails Sharpe, CAGR against SPY and QQQ. Per the pre-registration, a
simpler non-inferior arm is still the better live rule because it is simpler
and lower-turnover; the next focus is the universe/mandate, not another
overlay.

The worst-offset drawdown is deeper than -35% for every arm except 2, 3 and 4.
The candidate's worst offset is -39.42%, 4.42 points beyond the live risk
mandate, slightly deeper than arm 6's -39.24%. The ablation does not repair
that failure and does not claim to; the pre-registration's non-inferiority
test is on the median across offsets, and the worst offset is reported.

## The decision

The pre-registered rule yields:

- **Removed: P/E history.** Marginal +0.053 bp/day, Newey-West t 0.39,
  bootstrap -0.215..+0.323; not significant. Removal (the control) is within
  all five tolerances and lowers turnover from 8.61x to 8.44x a year.
- **Kept: volatility target.** Removal breaches the median-drawdown tolerance
  by 1.75 points.
- **Kept: exposure floor.** Removal breaches the CAGR tolerance by 0.415
  points.
- **Kept: leader tilt.** Removal breaches the CAGR tolerance by 0.080 points;
  the marginal itself is not significant and slightly negative.
- **Kept: 25% cap.** A risk limit, never a removal candidate; its marginal is
  zero on this universe.

- **Candidate: `leader_ewma_minA_floor50_live`** (live ordering, no P/E). It
  is simpler than `/2`, non-inferior within tolerance, and does not increase
  turnover. Under the owner's conditional authorization of 2026-11-02, the
  program prepares it for installation through the release ceremony as policy
  `/3`, with the forward record restarting.

## Limitations

- The 20 offsets are phase offsets of one history, not independent trials.
  The paired daily tests are the inferential unit; the offset sign is
  descriptive. The control beats arm 6 in 2 of 20 offsets on CAGR; the median
  difference is -0.34 points.
- Removing P/E is not proof that P/E is worthless. Its point estimate is
  positive in the all-window and 2024-2026, negative in 2016-2023, and never
  significant. The pre-registered rule removes it because the evidence does
  not support paying for it, not because it is measured to hurt.
- The leader-tilt keep is fragile: 0.080 CAGR points of tolerance headroom,
  with a non-significant and slightly negative marginal. A future
  pre-registration could revisit it; this study does not.
- The candidate still fails the objective and the worst-offset drawdown
  mandate. The forward record remains the out-of-sample arbiter.
- The cap is inert on the honest universe. It is retained as a risk limit;
  the study makes no claim that it earns attribution.
- The study is on the 2026-10-30 vintage. The live store has advanced one
  session; the live-store base reading differs by 0.230 CAGR points, which the
  amendment records as a data advance, not a result.

## What happens next

If the release gate passes, install the candidate as `/3` through the release
ceremony: candidate folder, contract revision, full unit gate on a fresh
database, targeted trading gate and AST pins, install under the paper lock,
deploy via `scripts/deploy.sh`, admission ADMITTED, a fresh ordinary nightly
and the following real paper session, with the 252-session forward record
restarting under `/3`. If the gate fails, keep `/2` and record why.

After the install decision, milestone 2 is the turnover diagnosis. The
candidate's turnover is 8.44x a year, still more than four times the 2x
program target; removing P/E did not address the dominant source.

## Change log

- **2026-11-03:** created after the vintage run. Records the P/E removal, the
  control candidate, the four keeps, the objective failure, the reproducibility
  investigation and the limitations.
