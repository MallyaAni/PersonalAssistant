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

## Completed evidence

Registered producer c236b2bd; selector acceptance ed0e6fcc. All 40 new accounts
completed once, producer exited 0 / OOM false. Exact image:
5c6c560537b3e7c70202edd6dfc872d299e2a268aa302ec23c3f48a3f49d099d.
Original research dependency tree is frozen 248bf5ad; original source/input and
forecast checks passed. One CPU, 4 GB, network disabled, source and input
mounts read-only. Existing larger producers were neither changed nor restarted.

Median within-phase cumulative gain difference versus original 1% timing,
percentage points, zero costs:

| Changed timing | Full period | Winning phases | 2018–20 | 2021–26 | Reused recent |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buys only | -11.0333 | 9/20 | +1.2706 | +3.9519 | -0.8982 |
| Sells only | +6.8011 | 12/20 | -0.5496 | +4.1563 | +0.0127 |

Recent wins: buys 5/20, sells 11/20. Full-period phase ranges are -150.62 to
+202.67 points for buys and -45.49 to +55.36 for sells. These overlapping
phases are sensitivity checks, not independent observations. Window medians
are not additive; changing a fill changes subsequent carried funding.

VERIFIED: four saved-trace tests and four original-selector tests pass.
Independent recorded-ledger acceptance verifies all 40 accounts / 34,451
intents: causal attempt eligibility, proportional funding, actual next-open
prices, covered sales, outcomes, daily cash/NAV/fees/turnover, stock wealth.
It does not call the producer or refit models. Original verifier SHA:
73946b7624930d32a16e82bb6d2c882bb80ad47405289575dcf8b1099c8c5e2a.
Adapter chooses the existing scalar checker per side and omits only the
cash_limited_decisions metadata-field requirement, which this producer did
not emit; all funding assertions and numeric tolerances remain unchanged.
Calendar source bytes are authenticated against the original report hashes.
The JSON companion records each account's exact hash and every window.

FAILED: evidence supporting either hybrid as a reliable replacement.
UNVERIFIED: fresh-period superiority, historical membership/grade authenticity,
whole-share current-policy parity and live performance. Costs cannot explain
these failures: every new account used zero. No strategy was deployed.

Private original output:
/home/animallya96/scratch/zero-cost-side-ablation-20261005-c236b2bd.
The saved-trace diagnostic is in zero-cost-timing-traces-2026-10-05.json.
Do not rerun these accounts or treat the reused recent window as untouched.
The unresolved research question is stock-conditioned entry continuation;
selling and buying must be evaluated separately with funded compounding.
