# Installed joint configuration: results — 2026-11-02

**Verdict: FAIL on the pre-registered primary gate. The exact installed joint
configuration does not meet the program's objective on the honest S&P 500
point-in-time universe at 25 bp. Median Sharpe is 0.837 against the 1.0 floor,
and median CAGR is 13.650% against SPY's 13.669%, a shortfall of 1.8 bp a year.
The median drawdown passes narrowly at -34.56% against -35%, but the worst
offset is -39.24%, deeper than the objective's approximate bound. The P/E
overlay adds 0.375 CAGR points and 0.021 Sharpe across all sessions but is not
statistically distinguishable: the paired mean is +0.053 bp/day, Newey-West t
0.39, month-block bootstrap -0.215..+0.323 bp/day, and the 2016-2023 mean is
negative. No live change; the 252-session forward record remains the
out-of-sample arbiter.**

This is the result of
`installed-joint-configuration-preregistration-2026-11-02.md`, run after the
note was committed. Research only: no live rule, order, grade, prompt or risk
dial changed, and no live file was written.

## The result

All sessions, 25 bp, 2,964 paired sessions, medians across the 20 offsets:

| line | CAGR | median drawdown | worst drawdown | median Sharpe | above EW PIT | above QQQ |
|---|---:|---:|---:|---:|---:|---:|
| scorecard floor (arm 1) | 13.28% | -34.42% | -39.42% | 0.815 | 20/20 | 0/20 |
| live ordering, no P/E (arm 2) | 13.28% | -34.39% | -39.42% | 0.816 | 20/20 | 0/20 |
| **joint, live ordering + P/E (arm 3)** | **13.65%** | **-34.56%** | **-39.24%** | **0.837** | **20/20** | **0/20** |
| SPY | 13.67% | -33.72% | -33.72% | 0.820 | — | — |
| QQQ | 18.48% | -35.12% | -35.12% | 0.884 | — | — |

The joint arm is the installed rule: the A-or-better held set, sized by
`grade_led_leader_policy.leader_weights` (leader tilt 0.5 over 63 sessions,
P/E-history multiplier 0.5, EWMA-20 volatility target 0.25 with floor 0.5,
then the 25% cap). Arms 1 and 2 are the controls. The two orderings agree closely: all-window
CAGR differs by 0.009 points, median drawdown by 0.03 points and Sharpe by
0.001. The cap-before-scale versus cap-after-scale difference and the
250-return versus 63-return volatility window are not material on this
universe, so arm 2 is a faithful live-ordering control.

## Gate fields

| field | value |
|---|---|
| primary median Sharpe >= 1.0 | **fail (0.837)** |
| primary median drawdown no deeper than -35% | pass (-34.56%); worst offset -39.24% |
| primary median CAGR above SPY's median CAGR | **fail (13.650% vs 13.669%, -0.018 points)** |
| secondary joint minus live mean > 0 | pass (+0.053 bp/day) |
| secondary Newey-West t >= 2.0 | **fail (0.39)** |
| secondary bootstrap lower > 0 | **fail (-0.215 bp/day)** |
| secondary joint above live in >= 15 of 20 offsets | pass (18 of 20) |
| secondary paired mean positive in both sub-periods | **fail (2016-2023 -0.093; 2024-2026 +0.482)** |
| **verdict** | **FAIL** |

The primary gate is read at 25 bp over all sessions, as pre-registered. Gate 2
is read as the median across offsets of each offset's worst drawdown (the
scorecard's `median_drawdown`), per the pre-registration's "medians across the
20 offsets"; it passes at -34.56%. The worst offset is -39.24%, 4.24 points
deeper than the objective's approximate -35% bound; if the gate is read as the
worst across offsets, it fails too. The verdict is unchanged because gates 1
and 3 fail.

## Sub-periods

| window | arm 3 CAGR | arm 3 median DD | arm 3 worst DD | arm 3 Sharpe | arm 3 above QQQ |
|---|---:|---:|---:|---:|---:|
| 2016-2023 | 11.73% | -34.56% | -39.24% | 0.721 | 0/20 |
| 2024-2026 | 23.22% | -20.76% | -22.16% | 1.391 | 18/20 |
| all | 13.65% | -34.56% | -39.24% | 0.837 | 0/20 |

The all-window failure is the 2016-2023 window. The 2024-2026 window is
strong on every measure and beats QQQ in 18 of 20 offsets; it does not carry
the eleven-year objective.

At 10 bp the joint arm is 15.15% CAGR, -34.32% median drawdown, -39.08% worst
drawdown and 0.917 Sharpe all-window. It beats SPY on CAGR and Sharpe at
10 bp but still misses the 1.0 Sharpe objective. The pre-registered gate is
25 bp.

## The P/E overlay

Joint minus the live control at the median offset:

| window | mean | Newey-West t (lag 20) | 95% month-block bootstrap | PSR |
|---|---:|---:|---:|---:|
| 2016-2023 | **-0.093 bp/day** | -0.58 | -0.374 .. +0.210 | 0.277 |
| 2024-2026 | +0.482 bp/day | 1.44 | -0.243 .. +1.187 | 0.896 |
| all | +0.053 bp/day | 0.39 | -0.215 .. +0.323 | 0.646 |

Joint minus the scorecard A-cut control tells the same story: all +0.041
bp/day, t 0.31, bootstrap -0.221..+0.312; 2016-2023 -0.109 bp/day, t -0.70;
2024-2026 +0.480 bp/day, t 1.46.

The point estimates: the joint arm is above the live control in **18 of 20
offsets**, with a median CAGR difference of +0.34 points, a worst case of
-0.05 points and a best case of +0.71 points. That unanimity is a statement
about the phase offsets of one history, not independent evidence. The paired
daily mean is within noise, the 2016-2023 mean is negative, and the bootstrap
interval crosses zero in every window.

The yearly pattern is mixed. On the median-offset curve the P/E tilt adds
+1.68 points in 2019, +1.15 in 2021, +1.79 in 2023, +2.82 in 2024, +0.23 in
2025 and +1.32 in 2026, and subtracts 3.35 in 2016, 1.20 in 2017, 0.45 in
2018, 0.13 in 2020 and 1.23 in 2022. It is period-dependent, not a consistent
edge. The honest-universe effect is much smaller than the survivor-book
evidence (`pe-history-tilt-2026-10-24.md`, +2.6 CAGR points at 10 bp); the
edge was top-heavy there, and this result is consistent with that warning.

## The published A-cut is not a same-code control

The published A-cut payload (`regrade_broad_value3_ew_graded_leader_forecast_ewma.json`,
17.1% CAGR, -34.7% worst drawdown, 1.00 Sharpe) is as of 2026-10-21. It omits
the 0.5 exposure floor, and it predates the 2026-10-24 simulator and
split-correction commits (`e7525ba9`, `86f10a39`). It is a historical
reference, not a same-code control for the installed rule. The current-code
floor arm is 13.28%, -34.42%, 0.815; the joint arm is 13.65%, -34.56%, 0.837.

The contract's evidence paragraph cites the published A-cut. That citation
overstates the installed configuration's honest-universe performance: the
exact installed joint configuration's current-code scorecard is the table
above, and it fails the objective. The gap to the published number is material
but cannot be attributed to the floor alone, because the code and data moved
with it. A current-code no-floor arm is needed to separate the two; this run
does not contain one.

## What drives the failure

- The worst drawdown episode is the COVID crash: -38.13% at the 2020-03-23
  trough from the 2020-02-19 peak on the median offset. The 0.5 floor holds
  half the book through the crash, so the drawdown is deeper than the no-floor
  evidence; the floor's cost is visible, but the code drift confounds it.
- The 2016-2023 window is weak (11.73% CAGR, 0.721 Sharpe, 0/20 above QQQ);
  the 2024-2026 window is strong (23.22%, 1.391, 18/20 above QQQ). The
  eleven-year median is the blend, and the early window carries the failure.
- The joint arm still beats the equal-weight point-in-time book in 20 of 20
  offsets and on the paired daily mean (+5.5 bp/day, HAC t 2.78 at 25 bp). The
  selection and sizing add value over the survivorship hurdle; that value is
  not enough to meet the absolute Sharpe and CAGR objectives, and the arm does
  not beat QQQ on mean daily return (-2.3 bp/day, t -1.39).

## What this means

- The installed joint configuration does not meet the program's objective on
  the honest universe at 25 bp on the current code and data. The failure is on
  Sharpe and CAGR, not on the median drawdown.
- The P/E overlay's honest-universe effect is positive but small and not
  statistically distinguishable. It is not a rescue.
- No live change. The owner chose the rule and the 252-session forward record
  is running; the review is the out-of-sample arbiter. The B hold remains the
  fallback at that review.
- The next research question is a pre-registered current-code no-floor control
  to separate the floor from the simulator/split drift, and possibly a floor
  comparison (0 against 0.5) on the A hold. This is a different question, not
  a retry of this one, and it must be pre-registered with what changed and why
  before its first run. Research only.
- Positive-shock drift remains owner-blocked.

## Look-ahead and multiplicity

- The P/E rank is causal by construction (`valuation.own_history_rank` reads
  only the trailing 756 readings ending on t); the leader tilt reads only the
  trailing 64 closes; the volatility scale reads only the trailing basket
  through t. The P/E strength 0.5 was fixed before the 2023-2026 results were
  read in the prior study.
- One joint arm plus two controls, with parameters fixed before the run. No
  search over strength, floor, window or cap. The 18-of-20 offset sign is one
  history's phase offsets, not independent evidence.
- The deflated-Sharpe hurdle is descriptive, with the trial count from the
  program of record, not used to rescue a failed gate.

## Data and reproducibility

- Run as of 2026-10-30 (the store's last complete session): 2,964 sessions in
  the all window, 2,012 in 2016-2023, 711 in 2024-2026.
- Report: `market_universe_hindsight_research.broad_report(store)`, regraded
  with the installed analyst votes (`value` 3, `fundamental` 1, `technical` 1,
  `sentiment` 1); membership `~/dsv41/universe/sp500_membership_history.csv`;
  20 offsets; costs 10 and 25 bp.
- Script: `~/dsv41/universe/joint_config.py`; payloads
  `joint_<arm>.json` and summary `joint_config_summary.json` under
  `~/dsv41/universe/`.
- Limitation: for the first 63 panel sessions (2015-01-16 to 2015-04-20) no
  name has a full 64-session window in the panel, so the live arms fall back to
  the scorecard A-cut allocator rather than holding cash. This is outside the
  2016-2023 and 2024-2026 windows, affects only the all window, and is
  identical in both live arms, so the paired joint-minus-live comparison is
  unaffected. The live policy would have had pre-panel store history; the
  backtest panel does not.
