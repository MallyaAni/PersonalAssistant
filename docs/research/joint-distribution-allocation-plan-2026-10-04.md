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

## Frozen scenario construction

Use the existing authenticated learned-held-exits/1-research forecasts and their
original adjusted-open one-session labels. Do not fit or restore an estimator.
Validate their complete monthly lineage, exact endpoints, support, publication
clock and saved array identities before consuming OOS errors. Preserve the
explicit adjusted-open proxy/current-vintage limitation; these are not forecasts
of actual broker cash, corporate-action processing or fills.

For a book declared from information at the current completed close, use the
preceding756 actual exchange sessions before that month's first session.
Every residual endpoint must precede both the month and August17,2026 freeze.
Only jointly available historical OOS rows for every required named stock can
form a simultaneous scenario. Require252 distinct joint dates. Record all
candidate, unavailable, per-name and joint support counts; never select stocks
from future outcome availability or silently substitute independent marginals.

For stock s and past date d, the gross forecast error is
(1 + actual[d,s]) / (1 + forecast[d,s]). Apply the same dated joint error vector
to current gross predictions: (1 + forecast[now,s]) * gross_error[d,s] - 1.
Each historical date gets equal probability. This avoids arithmetic shifting
that can invent losses beyond100%; genuine bankruptcy outcomes remain-1.
Do not recenter residual bias, clip tails or drop nonfinite generated scenarios.
Missing current forecasts, insufficient joint dates or arithmetic overflow make
the required book unavailable. Current realized labels do not gate requests.

This empirical calibration adjusts a stock/structure-conditioned mean using
rolling stock-specific joint OOS error history. It does not establish conditional
volatility accuracy, calibration guarantees or optimal sizing. Those require
subsequent diagnostics and funded evidence. Freeze input copies and shared
monthly residual records so callers cannot mutate an admitted reader or repeat
full lineage reconstruction on every decision.

Saved-artifact acceptance is a separate, read-only input diagnostic. Authenticate
the original held and bridge reports, independent proofs, forecast arrays and
fit receipts by their previously recorded hashes. Read saved numeric forecasts;
never restore a fitted estimator, predict, fit, replay or score an account.
At the final saved decision date, request each nonbenchmark stock separately,
plus the fixed AAOI/COHR, STX/WDC and AVGO/NVDA pairs. Retain every unavailable
request and its cause. Check original bytes and source before and after, shared
row identity, strict endpoint purge and returned scenario/probability hashes.
Do not select a winning stock, infer historical profit or use these diagnostics
to change the fixed candidate. Subsequent calibration and funded testing remain
required.

## Separate risk inference from trading eligibility

The original saved support diagnostic found a specific boundary: AAOI, COHR
and STX have years of price outcomes but only18 grade-gated forecasts after
September4; WDC has none. Do not relax joint-history requirements or fabricate
grades. Freeze a new optional holding-price-inference/1-research artifact before
new predictions: use the exact authenticated saved monthly held-model heads,
original thirteen features, authenticated price prefixes, original publication clock
and complete calendar. No fitting, additional model, hyperparameter, cost,
horizon or training-row change. NaN grades stay NaN and follow saved tree routes.

Source inspection corrected the first support assumption before saved inference:
the prepared valid mask already includes membership and a recorded grade.
Preserve and authenticate it as training provenance; it cannot define independent
price support. Reconstruct the original253-session completed-close availability
from authenticated adjusted closes, including SPY history, and require observed
original price/market features and finite original breadth. Individual missing
features, including grade, follow saved native tree routes. Keep incomplete price histories
unavailable. No history imputation or recomputation of features from later prices.

Inference support is that price-prefix availability, completed decision close,
and a nonbenchmark symbol. It is independent of
grade, membership and current/future labels. Trading eligibility remains the
allocator's separate unchanged grade/membership/cash/safety gate. The original
heads were trained on grade-qualified rows; scoring outside that population
is a declared distribution-shift risk, not proof of generalization.

Validate exact numeric model identities and complete monthly availability.
Use no pickle or restored sklearn estimator: traverse the saved numeric nodes,
including their actual missing routes, and retain unavailable heads/invalid
returns. Check original supported predictions against the authenticated saved
predictions within their existing numeric-verifier tolerance, then preserve
those original values exactly in the new artifact. Retain original training
support, dated purge and model receipts separately from expanded inference
support. The old fit/forecast files must not be relabelled or overwritten.

Bind original feature/valid hashes, adjusted-close hash, parent manifest, monthly model and prediction
receipts, expanded mask and new source/protocol identities. Validate these before
the joint scenario reader accepts expanded risk forecasts. Keep the same252
joint dates,756 sessions and August17 calibration freeze; current labels cannot
gate risk inference. Unavailable risk still prevents unsupported additions.

Acceptance: real64-tree sklearn versus numeric prediction including NaNs;
malformed numeric tree/config/identity rejection; original supported predictions
preserved; unknown-grade/nonmember price histories receive risk forecasts without
trading permission; unavailable months remain explicit; future feature/label
suffix cannot change earlier predictions; feature/valid substitutions, wrong
monthly head, forged expanded lineage and changed parent training rejected.
After acceptance, one saved-head inference run and the same fixed97-request
final-date input diagnostic, with independent model, arithmetic and source proof.
No account scores, strategy promotion, conditional-calibration guarantee or
claim of superiority from expanded coverage.
