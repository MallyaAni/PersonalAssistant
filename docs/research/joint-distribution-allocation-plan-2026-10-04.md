# Joint distribution sizing and holding decisions

Objective: jointly choose additions, retention, trims and exits by expected
net compounded wealth, using stock-conditioned predictive return scenarios.
This is a research option, default isolated; it does not change the running
fixed timing study, production planner, hard safety exits or saved forecasts.

VERIFIED: the earlier quadratic growth approximation reduced funded gain;
the execution CDF describes price waiting advantage, not holding profit.
UNVERIFIED: a jointly calibrated holding distribution, strategy advantage or
live adoption. The next-open to following-open holding target must remain
separate from the one-decision entry target. No probability is multiplied by
position size and no acquisition-profit threshold is added.

Freeze before implementation/economic outcomes: a supplied-input optimizer
maximizes sum of scenario weights times log(1 + portfolio return - trade fees).
Every scenario is a simultaneous cross-stock observation; independent marginal
draws cannot supply portfolio correlation. Probabilities must be positive and
sum to one. Returns must be finite, aligned arithmetic returns at least -1
or explicitly missing. No recentering, tail clipping, zero-risk replacement or
silent scenario-row dropping. The caller authenticates model/source bytes and
strictly mature, genuinely OOS residual clocks; numeric arrays cannot prove it.

Keep the existing long-only 25% per-name risk cap and total weight at most one.
Purchases plus their fees must fit observed cash before sales; prospective
sales cannot fund additions. Costs are proportional per side. Current B holdings
may remain or shrink but cannot be added to or rebought; unheld B is excluded.
Mandatory grade/membership and explicit safety exits remain authoritative.
Missing held cross-risk makes discretionary optimization unavailable; preserve
other holdings without additions and retain mandatory exits/cap trims. Missing
unheld names remain unavailable rather than manufacturing their forecasts.

Use auxiliary absolute-trade and positive-purchase weights and a convex solve.
Only globally certified feasible output may become a target. Exact holding,
zero and upper-bound candidates must be certified, not produced by epsilon
rounding. Solver tolerances are numerical certificates, not economic signals.
Paid fees and forecast uncertainty remain separate. An estimated win probability
is a diagnostic, not a calibration guarantee or a buy instruction.

Acceptance: same probability/different losses changes position size; correlated
versus diversifying scenarios change joint exposure; positive/negative remaining
utility retains or exits held B; no B addition/rebuy; fee-aware hold kinks;
cash and covered bounds; missing held evidence; malformed probabilities/horizon
refusal; permutation invariance; actual solver/global certificate; old default
allocator unchanged. No new historical fit, score, window/cohort/threshold
selection or source/cache rewrite in this implementation step.

Next evidence must build authenticated past-only joint holding scenarios, measure
forecast support/calibration and run fixed funded timing × sizing/holding accounts
against the completed current-policy/SPY/QQQ controls. Those steps and guarded
live adoption are still required; synthetic solves do not establish profitability.
