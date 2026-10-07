# Learned entry, exit and risk sizing

User correction: a closing-window change still leaves the arbitrary 1% timing
and equal-weight targets. That experiment is superseded and is not evaluated.
Implement one joint learned policy, registered here before its fitted outcomes.
Source main `ffe182fe`; no live policy activation or real/paper orders from this
research run. Existing grading supplies quality evidence, not an immediate Buy.

At each completed regular 15-minute bar, predict three quantities from its
observed prefix and the preceding daily context: log return from next-bar entry
to the close ten sessions later; that return's second moment; and the log-price
advantage of waiting one further decision. At the final regular decision,
waiting means the next session's first completed-bar decision. The common exit
endpoint isolates execution-price advantage rather than rewarding different
holding horizons. No 1% dip/pop gate or guaranteed end-of-day entry.

Features: prior 5/20/60/252-session returns, 20-session volatility, trailing
drawdown, EMA distances, prior grade, market return/volatility and breadth;
current gap, session/last-bar returns, running range, range location, VWAP
distance, realized prefix volatility and time. Prefix ratios use the cube's
same-session raw prior close, not future closing prices. Missing future outcomes
must never exclude a prediction row. Do not synthesize historical fundamental
or earnings observations from today's values.

Use three histogram gradient-boosting regressors, one fixed architecture:
64 iterations, 15 leaves, learning rate 0.05, minimum leaf 200, no early stopping,
seed 0. Refit monthly using up to 756 preceding sessions, requiring 504 distinct
training sessions. Pool five declared training clocks (completed-bar indices
0,3,9,19,24), score every regular completed-bar decision with a consecutive
execution open. Missing publication/maturity is not a training example. Purge
all rows whose ten-session endpoint is on/after the fit date. Freeze label ends
before 2026-08-17 for the final holdout through 2026-09-30, including September
refits. Earlier experiments have examined parts of this history; this is a
frozen candidate holdout, not a claim of a universally untouched dataset.

Choose weights by maximizing the second-order expected log-growth objective
from learned mean and variance, trailing correlation (Ledoit-Wolf shrinkage),
and the declared per-side transaction cost on changes from current holdings.
Cash has zero yield. Long-only, fully funded, at most 25% in one stock and gross
at most 100%; these are safety limits, not learned price/return targets. Weight
reductions are exits/trims; increases are entries. Existing below-A holdings
may remain when forecasts support holding, but cannot receive new capital;
unknown/absent membership cannot receive capital. Waiting is chosen only when
its forecast improves execution for that trade side; no hardcoded dip distance.
The fitted model, feature builder and sizing function are shared callable
components for replay and a future live adapter; no parallel approximate model.

Use the previously frozen portfolio snapshot SHA256
`8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58` and
cached SIP cubes read-only. Later adjusted raw-price scales are used only for
outcome/account units, not prefix features. Retain missing data and missing
funded marks explicitly. Cube v2 excludes early closes; report that limitation.
Reconstructed grades, retrospective prices and declared membership make this a
conditional research test, not exact historic live reconstruction. No paid
data, frozen-cache rewrites, threshold/window mining or GPU/model-service changes.

Run one continuous learned account at 0/10/25 bp against the fixed 1% dip/pop
control across all 20 reset phases, and same-capital SPY/QQQ. Begin the common
comparison only when all model heads have a mature fit; unavailable warmup is
not fabricated trading history. The learned account carries shares/cash across
sessions and trades on model decisions; windows never reset capital. Same-day
sale proceeds cannot fund buys. Bar opens are explicit price proxies, not
quote, depth, queue, midpoint or broker-fill proof. Report compounded total net
gain first, then CAGR, positive drawdown loss, Sharpe, exposure, costs/turnover,
unfilled/unknown observations and 252-session win rates. Report 2016–20,
2021–26 and final holdout with actual dates/counts; do not annualize discontinuous
regime slices. Compare causal prior-SPY trend and volatility regime groups only
as diagnostics; they do not select models or parameters.

Acceptance: split/basis equivalence; completed-prefix/future-label invariance;
monthly label maturity and purge including every holdout refit; deterministic
model hashes and identical replay/live callable output; weights respond to
forecast return/risk/correlation rather than equal allocation; costs discourage
unnecessary turnover; no borrowing, uncovered exits or same-day reinvestment;
all-missing/unknown inputs fail closed. Verify before real fits. Positive
forecast accuracy or code tests alone cannot justify live promotion.
