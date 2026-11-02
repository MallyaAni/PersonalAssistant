# Pre-registration: the installed joint configuration on the honest universe

Written 2026-11-02 before the first run. This scores the exact installed rule —
A hold, 63-session leader tilt 0.5, EWMA-20 volatility target 0.25 with
exposure floor 0.5, 25% per-name cap, and the P/E-history tilt 0.5 — on the
honest S&P 500 point-in-time universe. It is research only: it changes no live
rule, order, grade, prompt or risk dial, and writes no live file.

Disclosure: the published A-cut scorecard
(`regrade_broad_value3_ew_graded_leader_forecast_ewma.json`) is the arm without
the exposure floor. The installed rule has floor 0.5. The P/E-history tilt's
evidence is on the account simulator with the survivor book and the B-hold
baseline (`pe-history-tilt-2026-10-24.md`); it was never scored on the honest
universe. The installed rule's exact scorecard is therefore missing on two
counts, and this run closes both. The P/E strength 0.5 was fixed before the
2023-2026 results were read in the prior study; no strength search is run here.

The paired A-minus-B significance test of the same day failed its primary gate.
This is a different question, not a retry: it asks whether the configuration
that is actually installed meets the program's objective, and whether its
P/E overlay adds anything on the honest universe.

## Question

Does the exact installed joint configuration meet the program's objective on
the honest S&P 500 point-in-time universe at 25 bp — median Sharpe at least
1.0, median worst drawdown no deeper than -35%, median CAGR above SPY — and
does the P/E-history tilt add return over the same rule without it?

## Data

- Report: `market_universe_hindsight_research.broad_report(store)` over the
  market store, regraded with the installed analyst votes (`value` 3,
  `fundamental` 1, `technical` 1, `sentiment` 1), the same construction as the
  published broad A/B payloads.
- Membership: `~/dsv41/universe/sp500_membership_history.csv`, the same dated
  S&P 500 file the published broad payloads use.
- P/E readings: `report.opinions["value"].evidence["price_earnings"]`,
  `valuation.own_history_rank` with window 756 and `min_known` 250; row t reads
  only readings up to t. A missing or non-positive reading leaves the slot
  unchanged.
- 20 offsets, costs 10 and 25 bp, through `market_pit_scorecard.build`, the
  same sessions, membership mask and controls as the published scorecards.

## Arms

1. `leader_ewma_minA_floor50` — the A hold with floor 0.5 in the scorecard's
   ordering (leader tilt, cap, then the EWMA volatility scale). This is the
   registered arm closest to the installed rule and the control for the
   published evidence.
2. `leader_ewma_minA_floor50_live` — the same A-or-better held set, sized by
   the live policy's own `leader_weights`: leader tilt, P/E multiplier (none
   here), EWMA-20 scale with floor 0.5, then the 25% cap. This isolates the
   live ordering from the P/E tilt.
3. `leader_ewma_minA_floor50_pe` — arm 2 plus the P/E-history multiplier, the
   installed joint configuration.

Arms 2 and 3 call `grade_led_leader_policy.leader_weights` directly, so the
sizing is the live function, not a reimplementation. A name without a full
64-session finite positive window is not sized, as in the live policy. Arm 3
refuses to run if the report carries no P/E evidence rather than silently
scoring arm 2.

## Statistics

- Median and worst across offsets for CAGR, worst drawdown and Sharpe for each
  arm, at both costs, in 2016-2023, 2024-2026 and all sessions.
- Paired daily difference at the median offset: joint minus the live control,
  and joint minus the scorecard A-cut control; Newey-West t at lag 20, a 95%
  month-block bootstrap (2,000 draws), and PSR.
- Per-offset CAGR sign: how many of the 20 offsets the joint arm is above the
  live control.
- SPY and QQQ descriptive, as in the published payloads.

## Gate

Primary, all sessions at 25 bp, medians across the 20 offsets:

1. median Sharpe at least 1.0;
2. median worst drawdown no deeper than -35%;
3. median CAGR above SPY's median CAGR.

Secondary, all three for a PASS:

4. joint minus live control paired mean greater than 0, Newey-West t at least
   2.0, and the bootstrap 95% lower bound greater than 0;
5. joint above the live control in at least 15 of 20 offsets;
6. the paired mean is positive in both 2016-2023 and 2024-2026.

Verdict: PASS if primary and secondary pass; PARTIAL if the primary passes and
the secondary fails; FAIL if the primary fails. The published no-floor A-cut
row is a descriptive reference, not a gate.

## What passing buys

The contract's evidence paragraph can cite the exact installed configuration's
honest-universe scorecard, not the no-floor approximation, and can state
whether the P/E overlay adds return there. No live change; the 252-session
forward record continues.

## What failing means

The installed joint configuration does not meet the objective on the honest
universe, or the P/E tilt is not distinguishable from the same rule without
it. The result is recorded honestly. The live rule stays as installed because
the owner chose it and the forward record is running; the 252-session review is
the out-of-sample arbiter. A failure is not retried with a different floor,
P/E strength, window or universe without a new pre-registration saying what
changed and why.

## Look-ahead and multiplicity

- The P/E rank is causal by construction (`own_history_rank` reads only the
  trailing window ending on t); the leader tilt reads only the trailing 64
  closes; the volatility scale reads only the trailing basket through t.
- One joint arm plus two controls, with parameters fixed before the run. The
  P/E strength 0.5 was fixed before the 2023-2026 results were read in the
  prior study. No search over strength, floor, window or cap.
- The deflated-Sharpe hurdle is descriptive, with the trial count from the
  program of record, not used to rescue a failed gate.
