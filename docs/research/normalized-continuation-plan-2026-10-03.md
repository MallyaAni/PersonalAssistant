# Stock-conditioned nonlinear continuation

Objective: replace the universal1% execution trigger with a learned decision
between acting and waiting. VERIFIED: the previous Ridge continuation model,
causal features and funded ledger are implemented and independently audited.
FAILED: its recent32-session and two recorded-day comparisons did not establish
an advantage. UNVERIFIED: nonlinear stock-conditioned continuation usefulness,
current-policy compatibility and live adoption. The existing trigger is a
comparator, not an established optimum. This protocol is frozen before new fits
or economic outcomes. No production imports, order submission or UI changes.

One hypothesis: a pooled nonlinear model can learn interactions between
volatility, completed price structure and time remaining that separate linear
clock heads missed. This changes the target/architecture of earlier one-bar
HGB experiments; it is not a repeat of their return or squared-risk target.
Use [HistGradientBoostingRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)
with the already registered squared-error configuration:64trees,15leaves,
learning_rate0.05,min_samples_leaf200,early_stoppingFalse,random_state0.
These capacity constants are not trade-price thresholds or fitted choices.

Reuse the immutable original prepared data and all116 monthly whole-session
crossfitted target archives. Require the original manifest SHA
21afa50d2d36c1f03c20fa50dd4c18b05538865559ee80f7bf7ea553373a4c00
and the existing numeric-artifact/maturity/fold verifier. Do not refit nuisance
Ridge chains. Each target remains stop-minus-price selected by a held-session
suffix policy, divided by observed close. No hindsight best price. This is ONE
policy-improvement regression over that frozen suffix; its suffix is not the
new model's own Bellman continuation, and it is not optimal stopping proof.

Sparse-clock scoring is an interpolation approximation; clocks20..23 are beyond
the latest training clock19. Retain and report these clocks rather than claim
all-clock training parity. Normalizing the loss changes its weighting across
volatility levels; rescaling the output restores units, not the training loss.

Two pooled heads, buy and sell. Fit only clocks0,3,9,19 from the original fixed
training schedule (terminal24 has no continuation target). Retain all21 causal
features. Divide the target by prior20-session daily log-return standard
deviation times sqrt((24-clock)/26). This is a causal diffusion scale, not a
calibrated predictive interval. No floor, future volatility, ratio fitting,
tail clipping or threshold search. Zero/missing/nonpositive scale makes the
forecast unavailable. At scoring, multiply the predicted normalized mean by
the same observed scale. Nonlinear pooling shares statistical strength across
stocks/clocks while allowing volatility/path interactions. Training loss is
equal-row normalized squared error, not dollar-weighted portfolio loss.
No probability, accuracy or interval claim substitutes for funded net wealth.

Preserve min504/max756 prior calendar sessions, monthly cutoff, conservative
10-session maturity, stock-only training and August17 holdout cutoff. Score all
ordinary clocks0..23 using valid observed prefixes regardless of future outcome
availability. Buy waits if predicted stop-minus-wait price difference>0; sell
waits if<0. Zero acts. Missing forecast stays pending until the unchanged final
clock24 lifecycle action. Preserve original early-close missingness; no auction
fill fabrication. Known current close/volatility may be used; actual next open
may not. Conditional execution cost at the same per-side rate does not change
the sign of stop-versus-wait price difference for the same intended quantity;
actual costs, funding and changing quantities remain in the shared account.

Acceptance before fits: real small nonlinear fits, direction and rescaling,
no future-price/volatility influence, terminal/missing-scale behavior, benchmark
training exclusion, missing outcomes retained, strict teacher-byte/fold/maturity
validation and saved prediction authentication. New source/model/input hashes
and actual dependency versions must accompany every fit. An interrupted monthly
fit may resume only after its saved output hashes and source identity match.

One fixed comparison:2018-02-01..2026-09-30,94 current-vintage stocks plus
SPY/QQQ, twenty carried fractional NAV1 reset phases, zero cash yield and
0/10/25bp. Reuse authenticated saved current1% control, first-available and ETF
curves; replay only the new candidate. Report paired gain in initial-NAV units,
CAGR, positive drawdown loss, Sharpe, rolling252 wins, fees, turnover, missed
intents, full/2018-20/2021-26/recent32-session windows. No phase, window, regime
or model selection. Prior-only regime slices are descriptive. Recent data and
Oct1/2 were already inspected: they are reused validation, never untouched test.
Historical grades/universe are current-vintage reconstructions. This is a
conditional selection-book timing diagnostic, not full live-policy parity.
The separate grade-B sell-versus-retain problem is not solved by this model.

Any favorable result still requires supported current-policy, early-close and
broker-clock evidence before live release. Unfavorable evidence does not prove
1% optimal. Do not tune this method to observed failures. No paid data, new
provider calls, frozen-history writes, GPU/model-service changes or deployments.
Diagram impact NONE: existing internal research model/account boundary.
