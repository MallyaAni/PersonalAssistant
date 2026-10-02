# Frozen comparison details

Registered before any real fitting/inference outcomes. User requests parallel
approaches: gradient boosting, one fixed ridge alternative, and pinned Chronos-2
as documented in its own preregistration. Do not mine models or hyperparameters.

The training pool is the frozen 94-stock book, excluding SPY/QQQ targets.
Benchmark history is available as causal market context and comparison only.
Unavailable training or prediction rows remain explicit. Supplied historical
grades/membership are current-vintage conditional evidence, not historic live
records. Fundamentals/earnings history is unavailable for this first stage.

The learned heads predict log-return moments. Convert to the second-order
arithmetic expectation `mu_log + 0.5 * E[x^2]` and use cross moments
`cov_log + outer(mu_log, mu_log)` in the growth penalty. This avoids subtracting
the single-asset log risk twice: full exposure predicts `mu_log`. Independently
inconsistent moments are counted and given conservative variance at least the
squared predicted mean; they never become zero-risk bets. The 1e-8 variance
floor is numerical, not an economic allocation target.

The 1% control uses the first completed dip/pop among bars 0–23 and the next
consecutive open, otherwise an observed official auction print. No trigger
after closing submission changes that intent; absent auction data is missing.
This isolates the price/grade component, not FOMC/discretionary/broker parity.
Every one of its 20 reset phases is reported. It is not the current whole-share
production planner. There is no synthetic fallback for missing cube execution.

Waiting sells can retain capital planned for buys. Cap remaining increases to
available portfolio weight and fund actual fills from morning cash, holding
same-day sale proceeds aside throughout the day. Report price-missing and
cash-limited attempts separately; repeated quarter-hour attempts are not unique
orders. Partial/no fills remain in the account, never omitted from performance.

For the pretrained comparison, additionally use a fresh NAV1 account on the
fixed 2026-08-17..09-30 holdout with all three methods limited to completed bar9.
Use the same cash/grade gates, controls, benchmarks and 0/10/25bp costs. This
supplement has a different starting account from continuously carried full
history; do not splice it into compounded long-history returns or select a
better clock. Pretrained moments/terminal regular-close proxy are approximate,
and historical pretraining contamination cannot be proved absent before the
pinned public model release. Chronos comparisons must disclose those limits.
