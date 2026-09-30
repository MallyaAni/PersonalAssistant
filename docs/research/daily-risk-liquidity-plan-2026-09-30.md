# Daily risk and liquidity: frozen first experiment

User authorization: implement and test the daily volatility/volume study.
Starting source: GitHub main `908e683`, clean; branch
`research/daily-risk-liquidity-20260930`. Spark's shared main is older and
divergent; the attempted routine pull was aborted without retaining changes.
Do not rewrite either main or merge unrelated work to run this study.

VERIFIED from existing records: a CNN reduced next-session log-variance
prediction error; volatility sizing, bad-day exposure reduction and the recent
entry-timing studies did not earn promotion. UNVERIFIED: a volume forecast's
economic benefit, complete extended-hours coverage and a fully survivorship-free
universe. This study must produce real out-of-sample predictions, persisted
scores and an execution-relevance diagnostic, not just passing unit tests.

## Scope and targets (fixed before results)

Read existing SIP cube files only; hash every input. Do not rebuild production
caches, fetch data, call a model server or broker, or alter live decisions.
Use the dated membership mask for stock rows, SPY/QQQ/SMH as context only.
Decision time is after the completed regular-session bars have arrived that
evening, not 16:00:00 and not an intraday-prefix forecast.

1. `rth_variance_1`: next exchange session's sum of squared 15-minute returns,
   first return from the session open; explicitly excludes overnight.
2. `gap_augmented_variance_5`: mean of the next five sessions' regular variance
   plus squared prior-close-to-open gap. This is a risk proxy including the
   net overnight move, NOT realized extended-hours path variance.
3. `dollar_volume_1`: next session's sum of typical bar price times shares,
   09:30–16:00 excluding the separately stored closing-auction bar. It is an
   OHLCV dollar-turnover proxy, not exact dollar volume, quoted liquidity or
   order-book depth. Dollar units avoid artificial share-volume jumps at splits.

Reindex to the reviewed exchange calendar. Missing/short sessions remain
missing; labels cannot bridge them. Select rows using current inputs and dated
membership only; preserve rows with missing future labels. Daily features use
1/5/20/60-session volatility and dollar turnover, signed semivariance, gap,
returns, range, observed-data coverage, weekday and benchmark context. Rolling
means require 80% observed calendar sessions; no interpolation. Do not clip
genuine crashes or classify all large moves as bad data.

## Comparators and validation

Three point baselines: trailing-20 risk/volume; HAR-style ridge on 1/5/20
target-history levels; shallow LightGBM on the richer causal features. Targets
are log values relative to trailing-20 levels. Ridge and LightGBM log forecasts
are multiplicatively calibrated using past validation outcomes for QLIKE;
unadjusted log errors are also reported. Add LightGBM 10th/90th quantiles for
uncertainty. Their central point forecast is a conditional-mean estimate on
the log scale, not a median or guaranteed expected range.

Minimum 504 training exchange sessions, 63 validation sessions, five-session
purges on both boundaries; test/refit blocks of 126 sessions. Label end must
be strictly before the next partition starts. All names share date partitions.
Training-only imputation/scaling; no ticker identity feature; one seed (17),
no parameter sweep. LightGBM: at most 120 trees, depth 3, 7 leaves,
learning rate .05, minimum 100 rows/leaf, L2=10, four CPU threads; validation
early stopping with patience 12. No GPU/service changes. Quantiles are sorted
at inference and crossing frequency recorded.

Score 2018–2023 and 2024–2026 separately, with date-averaged paired loss tests
(HAC lag 20), log-MSE skill, variance QLIKE, volume log-MAE, quantile pinball
loss and empirical interval coverage. Regimes: SPY trailing-20 variance above
its training-only 80th percentile, SPY below its trailing-60 mean, and their
complements. Regime labels are audit slices, never future crash labels.

The three targets and two learned point families are six exploratory
comparisons; quantiles are calibration diagnostics, not six extra strategies.
Prior cumulative strategy trials were 457. This is reused history, not a new
holdout. A forecast is only a research lead if its primary loss improves at
least 2% versus the stronger simple comparator in both windows; report date-
clustered uncertainty, do not describe this threshold as statistical proof.
No forecast-only result qualifies live allocation or beats an index.

## Execution relevance and stopping

Use the existing paper journal read-only to measure actual filled-order sizes
and the dated account equity. Preserve missing execution timestamps and policy
provenance; never relabel legacy orders as `/5`. Compare order notional with
prior available turnover forecasts and realized execution-session turnover
where dates and inputs match. Report coverage, notional-weighted participation,
and the hypothetical dollar/account benefit of saving 1/5/10 bp per filled
notional. These are sensitivity scenarios, NOT measured savings or an oracle
upper bound. Without quotes and missed-order outcomes, no fill-probability or
slippage model can honestly be validated.

If the account's orders are tiny and the savings scenarios immaterial, stop
before adding execution scheduling. If forecasting fails, retain its evidence
without neural architecture search. Any later action policy requires a separate
frozen funded backtest versus `/5`, SPY and QQQ with costs, cash yield, false
defensive moves and missed recoveries. Indexes are not cash in a broad selloff.

Sources: arXiv 2608.12251 (regime-gated volatility), 2608.01599 (regime audits),
2609.25617 (joint return/volume/volatility), 2505.08180 (volume/execution).
Their reported performance is not evidence of this portfolio's profitability.

Diagram impact: NONE — an offline study inside the existing market-data
forecast/evaluation boundary; no new service, dependency or live data flow.
