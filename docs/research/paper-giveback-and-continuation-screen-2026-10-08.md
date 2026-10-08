# October 8 paper giveback and completed continuation screen

## Paper account: verified observation, not a closing result

At 2026-10-08 14:12:53 America/New_York, the paper broker reported equity
$102,828.66, last-equity $106,760.96 and cash $1,007.63. The dashboard's day
calculation is equity minus broker last-equity: **-$3,932.30 (-3.6833%)**.
All ten positions were down versus their broker previous-day marks. Summed
position intraday P&L is -$3,932.305, reconciling within half a cent to account
P&L. The separately requested five-minute history has a different observation
clock; do not combine its final mark with these position values.

| Holding | Broker intraday P&L | Current equity weight |
|---|---:|---:|
| SMCI | -$947.175 | 15.03% |
| ALAB | -$714.42 | 9.34% |
| SNDK | -$508.65 | 9.38% |
| MU | -$473.25 | 10.12% |
| SWKS | -$367.90 | 10.19% |
| NTAP | -$352.56 | 17.54% |
| STX | -$351.96 | 9.08% |
| HPE | -$192.05 | 11.52% |
| SNPS | -$20.40 | 5.85% |
| GEV | -$3.94 | 0.97% |

The broker's October 8 fill activity is complete and empty. Orders submitted
since October 7 contain only the already-filled October 7 GEV buy. This loss
therefore comes from existing positions, not today's execution fills. Cash is
0.98% of equity; NTAP and SMCI together are 32.57%.

**First decision boundary:** the October 7 nightly graded every held name A/A+.
The incumbent rotates holdings out when they fall below A; ordinary intraday
timing acts on previously planned intents and cannot invent a protective exit.
The recorded plan contains only a one-share deferred GEV buy, with no sell or
trim. The last rebalance was September 28, with seven sessions elapsed and
thirteen remaining on the twenty-session clock. NTAP and SMCI exceed their
current 10% targets, but target weights are not continuously enforced holding
limits. Recorded `paper.actions` say `trim` for these names; those are allocation
differences, not submitted or scheduled orders. No actual browser interpretation
of these legacy fields was verified in this observation.

This establishes the exposure/holding-policy limitation relevant to the user's
complaint. It does not establish that selling at a selected earlier price would
have been a causal policy, or that a new timing model would prevent this loss.
Do not tune a protective threshold from this session's already-observed moves.
Holding exits and portfolio exposure must be evaluated jointly with funded timing;
changing the 1% timing trigger alone cannot address today's absence of exit intents.

Runtime: backend container
1902cd4ffd2e4d98c6adc4792cd4d43a26688fdbfe9d817d14ae1fdc6441db42,
image b030999a3cdfecabdc04e41f0afa6610b536035a2ba0ae19b29913888b78ab89,
started October 7 09:19:47 UTC, deployed source
92b11bb981fb42a580dd98f140c8aa440c462f3e. Actual container bytes of paper,
intraday_orders, live_policy and policy_v5 match the reviewed checkout exactly.
Policy remains graded-equal-weight/5; no learned holding replacement was activated.

The private observation transport structurally admits only bodyless HTTPS GETs
to paper-api.alpaca.markets. It retained original responses with hashes and
receipt clocks under container-private `/tmp/paper-loss-observation-20261008-1415`.
Evidence SHA ba69a3ceece0a31c1be62e8996a3ff45e1cd01c8d9d7d8f1bb871410c2d63837.
Original October 7 desk record SHA
1853c3e9b1e9cce027bbb66231d9e989964146d8752df7a4778c26c91fd7e994.
No orders, account changes, production-data writes or model calls occurred.

## Nonlinear continuation screen: completed, not adoption evidence

Independent saved-account verifier finished with
`VERIFIED_THREE_ACCOUNT_CONTINUATION_COMPONENT_SCREEN`, adoption_eligible=false,
zero fits and zero producer replays. All three funded accounts closed. Both
producer 736e55e7b376 and verifier f9c4b21deeb3 exited zero without OOM, using
original 5c6c image and isolated read-only source/input mounts. Completion receipt
agrees with actual results hash
1e416244d6012217a71841b096821c3f400cf651ca567b73f04a64e12ca5eac0.
Complete-account manifest SHA
8751fabe1096f59bfafcf8e83fdbaf94b216e442f911194e55b48bf4089d5936.

Same carried $100,000 start-zero account, February 1, 2018 through September 30,
2026. Returns include the verifier's complete-wealth convention and corporate
actions. Only timing differs; selection, quantities and holding exits do not.

| Cost each execution | New timing total gain | Rule total gain | SPY | QQQ | New timing CAGR | New timing max loss |
|---|---:|---:|---:|---:|---:|---:|
| 0 bp | 707.71% | 763.51% | 190.50% | 350.63% | 27.36% | 42.43% |
| 10 bp | 576.29% | 603.10% | 190.40% | 350.53% | 24.77% | 43.92% |
| 25 bp | 406.23% | 432.96% | 189.71% | 349.79% | 20.65% | 45.93% |

All 36 reference/window pairs are retained in the original report; do not select
another cost or period after seeing outcomes. These three start-zero component
accounts underperform the unchanged rule in full-period wealth at every cost.
This is a completed adverse result, not a runtime block or proof that no possible
replacement can improve the system. No deployment follows from it.

Limitations: current-vintage selection, conditional raw-open historical fills,
unchanged holding exits/confidence sizing, one start and reused recent period.
The source report remains at Spark scratch/nonlinear-funded-screen-20261008/
results/proof-output-runtimefix1/proof/results.json. The separate 300-account
control continuation is still active and was neither changed nor restarted.

Acceptance: VERIFIED broker-day reconciliation, position attribution, complete
empty fill activity, source-matched decision explanation, completed saved-ledger
screen. UNVERIFIED closing October 8 performance, missed optimal exits, a qualified
joint holding/exposure replacement, current production activation and UI workflow.
