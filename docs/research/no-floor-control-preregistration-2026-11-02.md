# Pre-registration: the current-code no-floor control

Written 2026-11-02 before the first run. This attributes the gap between the
published 2026-10-21 A-cut scorecard and the current-code installed-rule
scorecard: how much of it is the 0.5 exposure floor, and how much is the
2026-10-24 simulator/split drift. It is research only: it changes no live
rule, order, grade, prompt or risk dial, and writes no live file.

Disclosure: the published A-cut payload
(`regrade_broad_value3_ew_graded_leader_forecast_ewma.json`, 17.088% median
CAGR, -34.675% worst drawdown, 1.002 median Sharpe, 2,957 sessions, as of
2026-10-21) is the no-floor arm on older code. The current-code floor arm
(`leader_ewma_minA_floor50`, 13.284% median CAGR, -39.425% worst drawdown,
0.815 median Sharpe, 2,964 sessions, as of 2026-10-30) is the same rule with
floor 0.5 on current code. The two differ on two axes at once, floor and code,
and the joint-configuration result
(`installed-joint-configuration-results-2026-11-02.md`) could not separate
them. This run adds the missing cell: the same no-floor arm on current code.

This is not a retry of the failed joint gate. It has no objective gate and no
pass/fail verdict. It is an attribution study, named as the next research
question in the joint result. No arm is promoted to live by it.

## Question

On current code and data, how much of the gap between the published no-floor
A-cut and the current-code floor A hold is the 0.5 exposure floor, and how
much is the 2026-10-24 simulator/split drift?

## Data

- Report: `market_universe_hindsight_research.broad_report(store)` over the
  market store, regraded with the installed analyst votes (`value` 3,
  `fundamental` 1, `technical` 1, `sentiment` 1), the same construction as the
  published broad payloads and the joint study.
- Membership: `~/dsv41/universe/sp500_membership_history.csv`.
- 20 offsets, costs 10 and 25 bp, through `market_pit_scorecard.build`, the
  same sessions, membership mask and controls as the published scorecards.
  The drift comparison reads the 25 bp rows only, because the published
  payload was built at 25 bp only.
- Published reference: `regrade_broad_value3_ew_graded_leader_forecast_ewma.json`
  under `~/dsv41/universe/`, as of 2026-10-21, 2,957 sessions.
- Run script: `~/dsv41/universe/nofloor_control.py`; it writes
  `nofloor_control_<arm>.json` and `nofloor_control_summary.json` under
  `~/dsv41/universe/`.

## Arms

1. `ew_graded_leader_forecast_ewma` — the published no-floor A cut, run on
   current code and data. This is the missing cell. It is the same arm the
   published payload used, not a reimplementation: the scorecard factory is
   the published lambda, `forecast_targeted_allocator(graded_tilted_allocator(
   min_grade=A, tilt=leader, strength=0.5, window=63, target=1e9, cap=0.25),
   forecaster=ewma, target=0.25, floor=0.0)`.
2. `leader_ewma_minA_floor50` — the same rule with floor 0.5 in the
   scorecard's ordering, re-run in the same process for exact pairing. This is
   the current-code floor arm already scored in the joint study; the re-run is
   a reproducibility check.

No P/E tilt in either arm, and no live-ordering arm: the joint study showed
the live ordering differs from the scorecard ordering by 0.009 CAGR points,
0.03 drawdown points and 0.001 Sharpe, so the floor effect measured in the
scorecard ordering is a faithful estimate for the installed rule.

## Statistics

- Median and worst across offsets for CAGR, worst drawdown and Sharpe for each
  arm, at both costs, in 2016-2023, 2024-2026 and all sessions.
- Floor effect: floor 0.5 minus no floor, paired daily at the median offset,
  mean bp/day, Newey-West t at lag 20, a 95% month-block bootstrap (2,000
  draws, seed 20261102), and PSR. Per-offset CAGR difference: sign count,
  median, worst, best.
- Drift: current-code no floor minus published no floor, per-offset CAGR
  differences across the 20 offsets (median, worst, best, sign count), and the
  all-window median CAGR, worst drawdown and Sharpe differences. Descriptive:
  the published payload ends 2026-10-21 and the current store ends 2026-10-30,
  so the comparison carries seven extra sessions; this is stated, not
  adjusted.
- Decomposition, at 25 bp, all sessions, medians across offsets:
  total gap = current floor minus published; floor effect = current floor
  minus current no floor; drift = current no floor minus published. The two
  components sum to the total gap by construction.
- Reproducibility check: arm 2's all-window 25 bp median CAGR must match the
  joint study's 0.132842 to three decimals. If it does not, the run stops and
  reports the discrepancy instead of interpreting the decomposition.

## Interpretation rule

Fixed before the run:

- Attribute the larger share of the CAGR gap to whichever component has the
  larger absolute value.
- If the floor effect is at least twice the drift in absolute CAGR points,
  call the floor the dominant driver. If the drift is at least twice the
  floor effect, call the drift dominant. Otherwise call both material.
- The drawdown and Sharpe gaps are decomposed the same way, descriptively,
  with no attribution rule: floor and drift can move them in opposite
  directions.
- No pass/fail verdict and no promotion. A negative floor effect on CAGR
  means the floor costs return; a positive one means it adds return.

## What the result buys

Nothing live. It tells the contract's evidence paragraph which number to cite
and whether the installed floor is the cost or the stale-code citation is.
The 252-session forward record remains the out-of-sample arbiter.

## What a surprising result means

- If the current no-floor arm lands near 13.3%, the floor is not the cause of
  the gap and the 17.088% citation is a stale-code artifact.
- If it lands near 17.088%, the floor costs about 3.8 CAGR points and the
  citation is a no-floor number misapplied to a floor rule.
- Either way, no live change. This study is not retried with a different
  floor, window, strength or universe without a new pre-registration saying
  what changed and why.

## Look-ahead and multiplicity

- The leader tilt reads only the trailing 64 closes; the volatility scale
  reads only the trailing basket through t; the membership file is dated.
  Both arms are causal by construction.
- Two arms, parameters fixed before the run. No search over floor, strength,
  window, cap or target.
- The published payload is a historical reference run on older code;
  comparing to it measures drift, not a new trial. The deflated-Sharpe hurdle
  is descriptive and is not used here.
