# Fixed linear comparison

Register one additional method before fitting real outcomes: three independent
training-only median imputation (with explicit missing indicators),
StandardScaler + Ridge(alpha=1) heads, with an intercept and deterministic
direct solving. Empty training columns remain an explicit missing state; no
historical grade is invented. Scaling is fitted on training rows only. Use exactly the same
features, five training clocks, 504-session minimum, 756-session lookback,
monthly purge, frozen final holdout, prediction eligibility, sizing, funded
account, costs and benchmarks as the learned-entry-risk plan. This is a fixed
regularized linear alternative, not a parameter search or a replacement
selected from its holdout results. No production activation from this study.

The common training pool excludes SPY and QQQ, which remain benchmark-only
assets. Their feature rows may be scored for diagnostics, but their future
outcomes do not train either policy. A supplied boolean symbol mask pins the
book and is included in the run identity.
