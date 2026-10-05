# Zero-cost entry and exit isolation

Objective: improve the existing 1% timing rule, with stock selection fixed and
zero spread, fees and slippage, as requested. This is separate from concurrent
allocation research and does not change its producer or frozen inputs.

VERIFIED before this experiment: the original sequential model's paired median
zero-cost gain advantage is 17.45 percentage points over 2018–September 2026,
11/20 planning phases positive; recent paired gain is -0.690 points, 5/20
positive. FAILED: consistent advantage. UNVERIFIED: a superior live policy.

Saved-trace diagnosis authenticates original report
2a8276f0c5e677292a600c260e87016d39029ee33359cdfae9c228c70fe22f11.
Recent common-fill entries averaged -12.81 bp advantage, additions -139.67 bp,
trims +12.13 bp and full exits +8.11 bp. Respectively 95/15/23/108 matched
observations across overlapping phases. Missing fills/action changes stay in
denominators; this is not causal profit attribution. No threshold is selected.

Freeze two exploratory interventions before their account outcomes:
1. Learned buy timing with original sell timing.
2. Original buy timing with learned sell timing.

Use all 20 original planning phases, 2018-02-01 through 2026-09-30, the same
selection/targets, original carried fractional NAV1 ledger, prior-session
funding, missingness, next-consecutive-open proxy and final deadline. Reuse
authenticated saved forecasts; fit nothing. Reuse completed original control
and both-sides curves; do not regenerate them. Evaluate only zero costs.
Keep full/early/later/reused-recent windows and every phase. Report paired
cumulative gain, winning phases, drawdowns and unmatched outcomes. Do not
select a phase, window or regime from the results.

Acceptance: selectors preserve the untouched side and final deadline; forecast
and source hashes match original evidence; actual account cash/stock wealth
reconciles and persisted results pass readback. The two new arms are diagnostic
ablations on reused history, not fresh out-of-sample validation. Any proposed
hybrid still requires prospective validation. No live strategy deployment.

Starting source f77d6e57, isolated codex/entry-exit-zero-cost-attribution.
Shared checkout and existing research producers preserved. Diagram impact:
NONE, isolated diagnostic using existing saved artifacts and ledger.
