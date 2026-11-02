# Candidate: hold at A (`grade-led-leader-weight/2`)

The installed `grade-led-leader-weight/1` admits a name at A or better and
holds it while it keeps at least B. This candidate changes only the hold
boundary: a name is admitted at A or better and held while it keeps at least
A (`ENTRY_GRADE = 2`, `HOLD_GRADE = 2`, `exit_letter = "A"`). Every other
parameter is unchanged: 63-session leader tilt 0.5, EWMA-20 volatility target
0.25 with exposure floor 0.5, 25% per-name cap, P/E-history tilt 0.5, 1%
minimum trade, valuation analyst at three votes, next-open execution. The
policy version becomes `grade-led-leader-weight/2`; the contract's revision 7
records the change.

## Why this is the selected arm

On the honest S&P 500 point-in-time universe at 25 bp, 20 offsets, medians,
the A hold earned 17.1% a year at worst drawdown -34.7% and Sharpe 1.00,
against the B hold's 14.4%, -38.3% and 0.87. SPY earned 13.9%, -33.7% and
0.83; QQQ 19.0%, -35.1% and 0.91. The A hold is the only tested arm that
reaches the program's Sharpe-at-least-1.0 objective on that universe; it beats
SPY on CAGR and Sharpe while its worst drawdown is 1.0 point deeper. It trails
QQQ's raw CAGR while beating QQQ's Sharpe and drawdown.

In the same regrade scorecard on the live 94-name book the A hold gives up 1.6
points of CAGR (25.0% against 26.6%) at the same Sharpe 1.11 and a 0.7-point
deeper drawdown (-34.1% against -33.4%). That is the disclosed cost of the
honest-universe robustness; the owner chose it for the top-tier objective.
Walk-forward, the A hold makes 18.3% at 0.98 on the S&P 500 against equal
votes' 16.0% at 0.88, and 23.8% at 0.95 on the book against 19.6% at 0.82.

## What this evidence is not

There is no formal significance test and no forward record. The scorecard is
in-sample research, not forward proof. The joint configuration's exact
scorecard is the A-cut study plus the P/E-history tilt's separate evidence;
the two were not scored together. The 252-session forward record restarts
under `grade-led-leader-weight/2`; the paper account's forward record is the
only out-of-sample evidence that counts. The P/E-history tilt's separate
evidence is `docs/research/pe-history-tilt-2026-10-24.md`.

## Bound sources changed

Two: `backend/market/grade_led_leader_policy.py` and
`docs/research/grade-led-leader-weight-contract-2026-10-21.md`. The 42 other
sources in the 44-source identity are unchanged.

## Acceptance

Targeted gate: 119 passed, 2 expected xfails
(`test_policy_book`, `test_grade_led_leader_policy`, `test_grade_led_parity`,
`test_market_policy_replay_research`, `test_curve_valuation_evidence`,
`test_market_nightly_check`, `test_model_allocation_view`,
`test_strategy_reference_source_review`, `test_strategy_publication_admission`).
The full unit gate runs before installation and its result is recorded in the
installed evidence. Installation is through the release ceremony under the
paper lock, then the deploy, then a fresh ordinary nightly and the following
real session on the paper account. The candidate does not install itself.

Owner authorization: the directive of 2026-11-01, "i need you to implement the
top tier system and go live deploy."
