# Does respecting the allocator improve the existing /4 book?

Registered before implementation or historical execution, from Fable main
`60b3ac3`. This is a bounded retrospective execution ablation, not a new
forecast, an untouched holdout, or permission to change live trading.

## Question and fixed comparison

The stage-3 sequence overlay zeros the targets of its lowest-forecast names,
but the independent mid-cycle breakout planner can buy them again. Is
preventing that entry useful, and is any improvement actually attributable
to ML rather than changing the executor?

Run exactly four arms on the same report and calendars:

| Arm | Allocator | Breakout entry requires positive current target |
|---|---|---|
| base | current /4 | no |
| base_gate | current /4 | yes |
| ml | existing M3 stage-3 overlay | no |
| ml_gate | existing M3 stage-3 overlay | yes |

The gate changes only eligibility for newly planned breakout buys. It does
not change their sizing, existing holdings, exits, reset orders, deferred
retries, cash funding, events, the 20% cap, or idle-cash redeployment.
It is NOT a promise that every excluded holding disappears immediately.
An absent, nonfinite or nonpositive target is not permission to enter.
The new simulator option defaults off; the paper planner and dashboard
remain untouched. No new model fits, forecast regeneration or grid search.

Use the existing `s1_seq.npz` out-of-sample ensemble forecasts, not the
new frozen forward-shadow model. Reconstruct the desk as of 2026-09-28
using the existing expectations-gap path and committed membership history.
Record the forecast, membership, code and report-array hashes in the output.
Use the existing funding simulator, zero cash yield and no terminal
liquidation. Twenty reset offsets, 10 and 25 bp one-way costs. SPY and QQQ
are independently loaded funded buy-and-hold accounts on each offset's
same calendar, through the existing strict benchmark loader. Include
equal-weight membership as a simple control under the same live options.

## Reporting, acceptance and stopping

Report terminal wealth, CAGR, maximum drawdown, cash share and turnover;
paired net daily differences for `base_gate-base`, `ml-base`,
`ml_gate-base_gate`, `ml_gate-ml` and their difference-in-differences.
Use Newey-West lag 20 at offset 10, and show all-offset direction counts.
Report the model window through 2023, 2024-2026, the full model window,
each calendar year, and descriptive lagged-SPY up/down trend regimes.
Regime returns are conditional daily means, NOT disconnected-day CAGRs.
The trend uses the prior close versus its prior 200-session average;
unknown warm-up stays explicitly unknown. Do not reset accounts at
window or regime boundaries.

Primary economic check: `ml_gate-base_gate` must reach the existing
stage-3 +2 bp/session and t >= 2 floor on the model window through 2023
at both costs, be positive in at least 15/20 offsets at 25 bp, have no
more than 3 percentage points worse median drawdown, and not lose on
2024-2026. Passing is only a reason for further independent evaluation,
never automatic adoption. No changing caps, model or thresholds afterward.
This adds two execution variants to the previously inspected arms; all
dates have been examined and the laggard idea was selected post hoc.

Before history: prove the gate blocks only ineligible breakout buys,
preserves eligible sizes and rotation exits, is causal in the current
target, and reproduces default simulator returns when off. Run the actual
simulator on a synthetic excluded-name episode, not just mocked calls.
Stop on source/benchmark absence, nonfinite evaluated returns, failed
default parity or gate semantics. Preserve failure; do not drop names or
calendar rows to obtain a result. If the economic floor fails, record that
and stop this candidate; do not build more admission/archive machinery.

Limits retained: membership masking still lacks prices for some historical
exited names; sectors, grades and adjusted data retain the existing study's
retrospective limitations. This experiment cannot prove a top-tier system.
The unrelated forward shadow remains unchanged and is not scheduled here.

Diagram impact: NONE — an optional simulator eligibility condition and a
research comparison using the existing data and execution paths.
