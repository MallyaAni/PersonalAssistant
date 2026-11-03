# Candidate: remove the P/E-history tilt (`grade-led-leader-weight/3`)

The installed `grade-led-leader-weight/2` multiplies each sized name's leader
slot by a P/E own-history tilt (strength 0.5 over a trailing 756 sessions,
minimum 250 readings). This candidate removes that tilt and nothing else:
`PE_HISTORY_TILT = 0.0`, and `size_report` no longer reads the value analyst's
price/earnings evidence. Every other parameter is unchanged: entry at A or
better, held while A, 1% minimum trade, 63-session leader tilt 0.5, EWMA-20
volatility target 0.25 with exposure floor 0.5, 25% per-name cap, valuation
analyst at three votes, next-open execution. The policy version becomes
`grade-led-leader-weight/3`; the contract's revision 8 records the change.

## Why this is the selected arm

The simplicity/ablation audit
(`docs/research/simplicity-ablation-results-2026-11-03.md`) measured the tilt's
decision marginal on the honest S&P 500
point-in-time universe, 2026-10-30 vintage, 25 bp, 20 offsets, 2,964 paired
sessions, medians: +0.053 bp/day, Newey-West t 0.39, month-block bootstrap
-0.215..+0.323 bp/day, PSR 0.646. It is not significant. Removing it is within
every pre-registered non-inferiority tolerance:

| reading | installed `/2` | candidate `/3` | difference | tolerance |
|---|---|---|---|---|
| median CAGR | 13.65% | 13.28% | -0.375 points | no more than 0.50 lower |
| median Sharpe | 0.837 | 0.816 | -0.021 | no more than 0.03 lower |
| median drawdown | -34.56% | -34.39% | 0.167 points shallower | no more than 1.00 deeper |
| worst drawdown | -39.24% | -39.42% | 0.18 points deeper | reported |
| paired HAC t | | | -0.39 | above -2.0 |
| bootstrap lower | | | -0.323 bp/day | above -1.0 bp/day |
| turnover | 8.61x/year | 8.44x/year | -0.17x | must not increase |

The other four components are kept by the same pre-registered rule: the
volatility target because removing it deepens the median drawdown by 2.75
points against a 1.00-point tolerance; the exposure floor because removing it
puts CAGR 0.415 points below the tolerance floor; the leader tilt because
removing it puts CAGR 0.080 points below the tolerance floor; the 25% cap
because it is a risk limit and is never a candidate for removal. The cap is
inert on the honest universe.

## What this evidence is not

The candidate still fails the program objective: median Sharpe 0.816 against
1.0, median CAGR 13.28% against SPY's 13.67%, worst drawdown -39.42% against
the -35% bound, and 0/20 offsets above QQQ. The ablation is in-sample research
on a fixed vintage, not forward proof. The 252-session forward record restarts
under `grade-led-leader-weight/3`; the paper account's forward record is the
only out-of-sample evidence that counts.

## Bound sources changed

Two: `backend/market/grade_led_leader_policy.py` and
`docs/research/grade-led-leader-weight-contract-2026-10-21.md`. The 42 other
sources in the 44-source identity are unchanged. The replay
(`backend/cli/market_policy_replay_research.py`) now maps `/3` to the
live-ordering no-P/E arm and simulates the installed book without the tilt,
and the nightly parity check (`backend/market/plan_parity.py`) compares the
live plan without it; neither is a bound source.

## Acceptance

Targeted gate: `test_policy_book`, `test_grade_led_leader_policy`,
`test_grade_led_parity`, `test_plan_parity`,
`test_market_policy_replay_research`, `test_curve_valuation_evidence`,
`test_market_nightly_check`, `test_model_allocation_view`,
`test_strategy_reference_source_review`, `test_strategy_publication_admission`.
Targeted gate result: 130 passed, 2 expected xfails in 16.98s. Full unit gate
result: 11,928 passed, 94 skipped, 10 xfailed, 508 warnings and 48 subtests
passed in 1,166.79s (19:26) on fresh database `anios_gate_leader3`; exit 0.
Both ran before installation and the full result is recorded in the installed
evidence. Installed 2026-11-03: `approved_at` 2026-11-03T19:38:59Z, archive
`20261103T193859-leader-3f96e35bf04744e4b5cc55d13ab5c136`, evidence
`17c291ad...`, release `4966fd7d...`, config `88c269c7...`, admission
ADMITTED. Installation was through the release ceremony under the paper lock;
the deploy, a fresh ordinary nightly and the following real session on the
paper account are recorded in `docs/NEXT_SESSION.md`. The candidate does not
install itself.

Owner authorization: the conditional authorization recorded 2026-11-02 —
install the simpler rule through the release ceremony, restarting the forward
record, if the simplicity/ablation audit shows a simpler rule is at least as
good.
