# Conditional holding calibration

Register one optional policy, `joint-stock-risk-funded/3-log-calibration-research`,
before its economic outcomes. Incumbent, v1/v2, original numeric forecasts,
models, source snapshots and running accounts remain unchanged. Motivation:
the saved mean diagnostic shows miscalibration, cash decisions and excessive
allocation turnover. Calibration cannot manufacture predictive discrimination.

At each original monthly cutoff, independently fit each stock's conditional
non-default log return as an affine function of its original log-gross forecast.
Use the existing single-stock, strictly mature genuine OOS forecast/outcome bank:
preceding 756 exchange sessions, at least 252 admitted dates, endpoints before
the original monthly cutoff and August 17 freeze. No new base-model fit, pooled
stock substitution, fitted sign constraint, economic threshold or window search.
Coefficients must not change with the other names requested in that month.

Center and scale the predictor for numerical stability; ordinary least squares
learns intercept and slope. Exact constant forecasts use an intercept-only fit.
Retain actual total-loss observations as empirical default point masses rather
than fitting their undefined logs or discarding their dates. Require enough
non-default observations for positive residual degrees of freedom. A constant
outcome or zero residual is legitimate; it is not invented certainty.

Construct scenarios on the original common simultaneous dates, still requiring
252 joint dates. For each stock, apply its fitted current conditional log mean
plus its same-date fitted residual, scaled by current/prior stock volatility.
Multiply residuals by sqrt(n/(n-p)*(1+leverage)): the usual linear-regression
degrees-of-freedom and prediction-leverage adjustment. This is an approximation
under regression assumptions, not a calibrated probability guarantee; it does
not independently model cross-stock coefficient uncertainty or serial dependence.
Keep default rows exactly -1. Exponentiate to arithmetic returns; refuse overflow
or numerical total-loss fabrication, never clip or silently drop a joint row.

These are fitted calibration residuals of genuinely OOS base forecasts, not
out-of-sample residuals of the calibration layer. Record that distinction,
coefficients, cutoff, source/selected-row hashes, degrees of freedom, leverage,
support and original scenario identity. Preserve simultaneous dates, equal date
probability, all missing opportunities and actual current publication clocks.
Historical and published forward readers must use the same transformation.

Use the unchanged globally certified joint log-growth optimizer and v2 entry
qualification, grade/B-hold/company/event/band permissions, 25% name cap, actual
cash, whole shares, fees and no prospective sale funding. Both buying and held
exits respond to conditional portfolio utility; no fixed dip/profit percentage
is introduced. Intraday execution timing remains a separate, unpromoted component.
Never relabel v2 or allow production brokers to select this research policy.

Acceptance before scoring: independent affine and constant-predictor oracles,
true-default and numeric-tail handling, volatility/leverage response, stock order
invariance, unchanged original reader/default policy, monthly reuse, explicit
missingness, current/future-label and future-feature prefix invariance, freeze,
real private nightly persistence/repeat/cash/held-B/event boundaries and forward
clock/report rejection. Authenticate exact source and saved input bytes.

Initial economic screen: exactly the first registered 2018-02-01 start through
2026-09-30 at each original 0/10/25bp cost, $100,000 cash and zero cash yield.
Use new IDs and original reviewed whole-share/corporate-action accounting.
Reuse independently verified matching rule, boosting, ridge, SPY and QQQ controls;
do not replay them or remove immature/missing rows. Report gain, CAGR, maximum
loss, Sharpe, turnover, exposure and the original fixed eras/reused recent window.
This screen and its development data cannot establish adoption; broader fixed
start/cost evidence and genuinely prospective carried-book evaluation are still
required. Do not launch 60 new accounts before checking this bounded screen.

Methodological context: [Gneiting and Resin, conditional calibration](https://arxiv.org/abs/2108.03210)
distinguish calibration, discrimination and uncertainty. The proposed affine
log-return postprocessor is our explicitly declared engineering choice, not
that paper's isotonic method or a published guarantee of trading profit.
