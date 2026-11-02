# Current-code no-floor control: results — 2026-11-02

**Verdict: drift dominant; the 0.5 exposure floor is not the cause of the gap.
The published 17.088% A-cut is not reproducible on current code with or without
the floor. The same no-floor arm earns 12.954% median CAGR at 25 bp on current
code, 4.134 points below the published payload, while the floor 0.5 arm earns
13.284%. The floor adds +0.330 CAGR points and +0.009 Sharpe, deepens the
median drawdown by 0.605 points and leaves the worst drawdown unchanged. The
drift is 12.5 times the floor effect, and the pre-registered rule calls it
dominant. No live change; the 252-session forward record remains the arbiter.**

This is the result of `no-floor-control-preregistration-2026-11-02.md`, run
after the note was committed. Research only: no live rule, order, grade, prompt
or risk dial changed, and no live file was written.

## The result

All sessions, 25 bp, medians across the 20 offsets:

| line | CAGR | median drawdown | worst drawdown | Sharpe |
|---|---:|---:|---:|---:|
| published no-floor A cut (2026-10-21) | 17.088% | -30.191% | -34.675% | 1.002 |
| current-code no-floor A cut | 12.954% | -33.818% | -39.425% | 0.806 |
| current-code floor 0.5 A hold | 13.284% | -34.423% | -39.425% | 0.815 |
| installed joint (floor 0.5 + P/E), reference | 13.650% | -34.560% | -39.237% | 0.837 |

The installed joint row is carried from the joint-configuration result for
context; it is not an arm of this study. The two current-code arms are the
study: the published factory `ew_graded_leader_forecast_ewma` (no floor) and
`leader_ewma_minA_floor50` (floor 0.5), both run in one process on the same
broad honest universe and regrade weights.

## The decomposition

At 25 bp, all sessions, medians across offsets, in CAGR points:

| component | CAGR | worst drawdown | median drawdown | Sharpe |
|---|---:|---:|---:|---:|
| total gap (current floor minus published) | **-3.804** | -4.750 | -4.233 | -0.186 |
| floor effect (current floor minus current no floor) | **+0.330** | 0.000 | -0.605 | +0.009 |
| drift (current no floor minus published) | **-4.134** | -4.750 | -3.628 | -0.196 |
| sum check | 0.000 | 0.000 | 0.000 | 0.000 |

The pre-registered rule: the drift is dominant if it is at least twice the
floor effect in absolute CAGR points. It is 12.5 times the floor effect, so
the drift is dominant and the floor is not. The drawdown and Sharpe
decompositions are descriptive and tell the same story: the floor leaves the
worst drawdown exactly unchanged, deepens the median drawdown by 0.605 points,
and adds 0.009 Sharpe, while the drift accounts for the rest.

## The floor effect

Floor 0.5 minus no floor, paired daily at the median offset (offset 10 in both
arms), 25 bp:

| window | mean | Newey-West t (lag 20) | 95% month-block bootstrap | PSR |
|---|---:|---:|---:|---:|
| 2016-2023 | +0.303 bp/day | 0.88 | -0.157 .. +0.987 | 0.853 |
| 2024-2026 | +0.000 bp/day | 0.01 | -0.000 .. +0.000 | 0.507 |
| all | +0.205 bp/day | 0.88 | -0.103 .. +0.606 | 0.853 |

- Per-offset CAGR: the floor arm is above the no-floor arm in **19 of 20
  offsets**, median +0.341 points, worst -0.049, best +0.602.
- The floor binds on **944 of 2,012 sessions in 2016-2023**, with a maximum
  daily weight difference of 3.24%. The +0.303 bp/day mean over the window's
  2,012 sessions compounds to about +6.1% cumulative, which is why the
  2016-2023 CAGR gain is +0.428 points.
- In **2024-2026 the floor never binds**: the two arms hold identical weights
  to machine precision (47 sessions differ by at most 1.0e-11 in daily return;
  the paired mean is 6e-12 bp/day). The 2024-2026 floor effect is exactly zero
  in CAGR and drawdown. This is why the 2024-2026 gap is pure drift.
- The floor is not statistically distinguishable from no floor on daily
  returns (t 0.88, bootstrap crosses zero in every window). Its point estimate
  is small and positive, not the 3.8-point cost the published comparison
  implied.

## The drift

Current-code no floor minus published no floor, 25 bp:

| window | CAGR | worst drawdown | median drawdown | Sharpe | sessions (current / published) |
|---|---:|---:|---:|---:|---:|
| 2016-2023 | **-3.551** | -4.750 | -3.628 | -0.170 | 2,012 / 2,012 |
| 2024-2026 | **-4.541** | -0.471 | -0.211 | -0.200 | 711 / 704 |
| all | **-4.134** | -4.750 | -3.628 | -0.196 | 2,964 / 2,957 |

- Per-offset CAGR: the current no-floor arm is above the published arm in
  **0 of 20 offsets**, median -4.155 points, worst -4.755, best -3.131. The
  drift is systematic across every phase offset, not a few paths.
- The 2016-2023 window has **identical sessions** in both payloads (2,012) and
  still shows a -3.551-point drift. The drift is therefore not the seven extra
  sessions between 2026-10-21 and 2026-10-30.
- The 2024-2026 window has the floor inactive and still shows a -4.541-point
  drift. The floor cannot explain it.
- The published payload was built on 2026-10-22 from the
  `/home/animallya96/dspark-commit` checkout; the current run is from
  `/home/animallya96/anios` at current main, against the same store path
  (`/home/animallya96/deploy/anios/data/market`). The published payload does
  not record its code revision, and that checkout has since moved to
  `2b3be53d` (2026-10-28), so the exact published revision is not recoverable
  from the payload or the log. The drift is consistent with the 2026-10-24
  simulator and split-corrected valuation-history commits (`e7525ba9`,
  `86f10a39`), which changed the valuation evidence that feeds the `value`
  analyst at three votes and therefore the A set. This study cannot isolate a
  specific commit, and cannot rule out other code or data changes between
  2026-10-22 and 2026-11-02.

## What the published payload actually measured

The published A-cut (`regrade_broad_value3_ew_graded_leader_forecast_ewma.json`,
17.088% CAGR, -34.675% worst drawdown, 1.002 Sharpe) was a real measurement of
the no-floor rule on the code and data of 2026-10-21. It is not a measurement
of the installed rule, and it is not reproducible on current code even as a
no-floor measurement. The current-code no-floor arm earns 12.954%, -39.425%
and 0.806; the floor arm earns 13.284%, -39.425% and 0.815. The contract's
evidence paragraph cites the published number, so it overstates the installed
rule's honest-universe performance by about 3.8 CAGR points, and the
overstatement is not attributable to the floor.

## What this means

- The 0.5 exposure floor is not the cost the joint result suspected. On current
  code it adds 0.330 CAGR points and 0.009 Sharpe, costs 0.605 median-drawdown
  points, and leaves the worst drawdown unchanged. The floor binds only in the
  high-volatility episodes of 2016-2023 (944 sessions) and never in 2024-2026.
- The installed joint rule's current-code honest-universe scorecard stands at
  13.650% CAGR, -34.560% median drawdown, -39.237% worst drawdown and 0.837
  Sharpe. The floor and the P/E tilt each add a little; neither closes the gap
  to SPY's 13.669% CAGR or QQQ's 18.476%. The objective still fails on median
  Sharpe and median CAGR.
- The published 17.088% should not be cited again. The contract
  (`docs/research/grade-led-leader-weight-contract-2026-10-21.md`) is a bound
  release source in `source_sha256`; editing it now would change the release
  source identity and break admission. The correction is recorded here and
  belongs to the next authorized contract/release update, not a silent edit.
- No live change. The owner chose the rule and the 252-session forward record
  is running; the review is the out-of-sample arbiter. The B hold remains the
  fallback at that review.
- A drift bisect is a separate question, not a retry of this one. It would
  need the old code and the old data state, and the split correction may have
  rewritten the valuation history, so it may not be recoverable. If pursued,
  it must be pre-registered with what changed and why before its first run.
  Research only.
- Positive-shock drift remains owner-blocked.

## Look-ahead and multiplicity

- The leader tilt reads only the trailing 64 closes; the volatility scale reads
  only the trailing basket through t; the membership file is dated. Both arms
  are causal by construction.
- Two arms, parameters fixed before the run. No search over floor, strength,
  window, cap or target. The published payload is a historical reference run
  on older code; comparing to it measures drift, not a new trial.
- The deflated-Sharpe hurdle is descriptive and is not used to rescue or
  condemn anything here.

## Data and reproducibility

- Run as of 2026-10-30 (the store's last complete session): 2,964 sessions in
  the all window, 2,012 in 2016-2023, 711 in 2024-2026. The published payload
  is as of 2026-10-21: 2,957 sessions, 2,012, 704.
- Report: `market_universe_hindsight_research.broad_report(store)`, regraded
  with the installed analyst votes (`value` 3, `fundamental` 1, `technical` 1,
  `sentiment` 1); membership `~/dsv41/universe/sp500_membership_history.csv`;
  20 offsets; costs 10 and 25 bp. The drift comparison reads 25 bp because the
  published payload was built at 25 bp only.
- Script: `~/dsv41/universe/nofloor_control.py`; payloads
  `nofloor_control_ew_graded_leader_forecast_ewma.json`,
  `nofloor_control_leader_ewma_minA_floor50.json` and summary
  `nofloor_control_summary.json` under `~/dsv41/universe/`.
- Reproducibility check: the floor arm's all-window 25 bp median CAGR is
  0.1328419731873035, identical to the joint study's value, so the re-run
  reproduces the earlier construction exactly. The check passed; the
  decomposition was interpreted.
- Limitation: the published payload's exact code revision is not recorded, and
  the `/home/animallya96/dspark-commit` checkout has since moved. The drift is
  measured between the published artifact and current main, not between two
  known revisions.
