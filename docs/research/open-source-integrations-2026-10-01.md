# Open-source integrations: frozen research protocol

Registered before new numerical outcomes, 2026-10-01. Branch
`codex/open-source-research-20261001`, starting source `ae9aa077`.
User authorized sequential integration, parallel engineering, and backtests;
not live promotion, real orders, model-service changes or paid compute.

## Shared boundaries

Each integration is optional and research-only, with real dependency/runtime
acceptance separate from synthetic tests and economic evidence. Missing data,
failed inference, immature labels and rejected orders remain in denominators.
No result selects a new threshold, seed, cohort, horizon or model revision.
No existing experiment or frozen history is overwritten. No provider refetch
is required for this protocol. Original files and metadata are hashed.

The daily store has split-adjusted OHLC and total-return adjusted close. Use
the declared dividend factor `adjusted_close / close` consistently for daily
OHLC. Provider-reported volumes are not silently rescaled or asserted to be
original broker-share volumes. Reconstructed grades and historical prices in
a later vintage are not contemporaneously recorded signals. Session-close
availability assumptions must be named, preserving original fetch timestamps.
All return accounts use the existing funded allocation ledger, next-open
execution, starting NAV 1, zero cash yield and no leverage. Added costs 10 and
25 bp are sensitivity conventions, not proof of actual commissions or fills.

## Portfolio sizing

One candidate: skfolio 1.4.10 minimum variance, Ledoit-Wolf covariance over
the preceding 252 completed adjusted-close returns; same /5 A/A+ eligibility,
gross and 25% per-name cap. Reset every 20 sessions from a fixed first-session
phase. Total L1 target turnover is bounded by the incumbent's same-date
turnover, or the minimum distance to the eligible capped simplex when exits
make that necessary. No inverse-volatility or volatility-target sweep.
Insufficient covariance makes the candidate unavailable/cash, with coverage
reported explicitly. Controls: /5 target replay, eligible equal weight, SPY
and QQQ. Historical period 2016-01-04 through 2026-09-30 where frozen source
supports it; show 2016-20 and 2021-26 separately. Report CAGR, drawdown,
Sharpe, turnover, exposure, rolling-window wins and unavailable observations.
This target replay does not claim full intraday live-policy reconstruction.

## Pretrained forecasts

Fixed cohort: AAPL, MSFT, NVDA, AVGO, AMD, AMZN, META, GOOGL, TSLA, AAOI,
SPY and QQQ. Completed-close decisions 2026-09-03 through 2026-09-30, source
cutoff 2026-09-30; 252 preceding completed daily OHLCV observations, ten-session
horizon. Pin immutable checkpoint/code revisions and preserve model licensing.
Chronos-2, Kronos-small and TimesFM-3 predict terminal price change relative
to the known close, minus a separately predicted SPY change. Same fixed
positive-excess ranking rule, equal weights capped at 25%, ten-session reset
phase from the first declared decision. Economic execution is next-open;
close-to-close forecast error is a separate diagnostic. All models use common
eligible opportunities. Late ten-session labels remain immature.

This short post-checkpoint retrospective slice is not historical production
tradability or a new untouched holdout. Unknown pretraining membership/cutoffs
and later source/code vintages are explicit. TimesFM-3 is non-commercial
research only. TinyTimeMixer is risk-only: ten-session mean squared log return
versus the trailing 20-session constant-risk baseline; no automatic sizing
promotion. No fine-tuning is predeclared. CPU inference runs are sequential
with bounded threads and batches; GPUs/model services remain unchanged.

## Execution and document infrastructure

NautilusTrader stable 1.231.0 independently replays supplied timestamped raw
bid/ask observations in a cash account. Compare current timing and explicit
bounded permissions, retaining missed/expired/partial opportunities. Displayed
liquidity simulation is conditional, not real IOC fill proof. Historical OHLC
alone cannot establish bid/ask, queues, latency or midpoint execution. If
quote history is absent, report that limitation rather than invent a profitable
historical account.

Docling is already the document parser. Extend and test source/page/table
provenance narrowly after inspecting actual output; do not add a duplicate
parser or change model prompts. Document extraction has acceptance tests, not
trading backtests. Real parser availability remains a separate runtime gate.

## Adoption

Implementation, dependency acceptance and favorable economic results are
different claims. No candidate is automatically adopted from this protocol.
Publish unfavorable and unavailable outcomes as well as wins. New live use
needs a separate funded forward comparison and guarded release.

## Post-result literature review: specialist roles

Reviewed 2026-10-01 after the fixed comparisons. This section does not amend
their frozen protocol or scores, activate a policy, or establish a market-regime
edge. Publication supports a stated task under the authors' evaluation, not
automatic profitability on this desk. The following roles are research
hypotheses unless explicitly identified as measured here.

| Integration | Evidence-backed capability | Appropriate desk question and remaining gap |
| --- | --- | --- |
| Chronos-2 | Group attention supports related series and covariates, with benchmark gains on multivariate tasks. [Original paper](https://arxiv.org/abs/2510.15821). | Can joint stock, sector and SPY context improve relative-return forecasts? Our adapter supplied one close series at a time, so the fixed result did not test this capability. Sector-rotation advantage remains unverified. |
| Kronos | Financial OHLCV modelling; authors evaluate returns, volatility and generated candles. [Original paper](https://arxiv.org/abs/2508.02739). | Can candle-path or volatility information improve entry/exit timing conditional on existing grades? Our fixed adapter read only predicted closes from its OHLCV output. No validated 15-minute timing or bull/bear specialization follows from that result. |
| Tiny Time Mixers | Compact CPU forecasting and cross-channel/exogenous modelling during fine-tuning. [NeurIPS paper](https://arxiv.org/abs/2401.03955). | Can a low-cost risk forecast improve exposure without sacrificing compounded gain? Our squared-return error improvement is a measured diagnostic, not a learned trading brake or profit result. No cross-channel fine-tuning was tested. |
| TimesFM-3 | Native joint multivariate forecasting and covariates; released August 31, 2026. [Google release](https://research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/). | A research comparator for the joint-context question. Our adapter was univariate. Downloaded weights and outputs are restricted to non-commercial, non-production use under the [actual license](https://huggingface.co/google/timesfm-3.0-pytorch/blob/main/LICENSE); do not feed production decisions from this checkpoint. |
| skfolio / Ledoit-Wolf | Covariance shrinkage addresses estimation noise in portfolio optimization. [Authors' research](https://ledoit.net/research.htm). | Can correlation-aware constraints reduce concentration or tail losses while preserving net gain? The tested minimum-variance replacement lost CAGR versus the incumbent. It was not a regime-conditioned risk overlay and does not predict winning stocks. |
| NautilusTrader | Event-driven matching and accounting with supplied market data. [Official data requirements](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/). | Validate a selected policy's cash, partial fills, cancellations and timing. It supplies no directional edge; bar data cannot establish spreads, queue position or exact intrabar order. |

Three 2026 sources are relevant without adding more live models:

- **Chroma, ICLR 2026:** [Test-Time Efficient Pretrained Model Portfolios for
  Time Series Forecasting](https://cdn.amazon.science/17/d9/c04a2190493fb3a1fdf6000c66f9/mert-amazon-project.pdf)
  supports domain/frequency specialists and validation-selected ensembles on
  forecasting benchmarks. This is a methodological precedent for the user's
  specialist idea, not evidence that our models have distinct profitable market
  regimes. Its selection uses validation data, not future test winners.
- **KiT, September 28, 2026 preprint:** [paper](https://arxiv.org/abs/2609.34507)
  generates joint OHLCV paths with continuous flow matching, including
  15-minute resolution. The authors report return and volatility ranking gains
  and an A-share backtest; these do not establish US-stock next-open performance
  against SPY/QQQ. Its [repository](https://github.com/Luciferbobo/KiT) currently
  contains documentation/assets and says code will be available soon, so native
  inference cannot yet be reproduced. Appendix A.2 also explicitly selects a
  fine-tuned Kronos comparator by test-set scores; audit the evaluation before
  treating headline comparisons as adoption evidence.
- **June 25, 2026 US-equity study:** [Pretrained Time-Series Foundation Models
  for Financial Return Forecasting](https://arxiv.org/abs/2606.27100) finds
  strong rankings among neural models but sparse statistically significant
  improvements over random walk on its five equities. This supports testing
  asset/task specificity and simple controls rather than assuming publication
  establishes reliable alpha.

Priority is to test the existing models' intended contributions, not fit a
retrospective winner switch. For entry/exit evaluation, hold grades and funding
constant and isolate timing; for risk evaluation, include exposure-matched
controls and realized tail losses. Any combined selector needs point-in-time
features, only matured training outcomes, chronological purging, an untouched
forward window, common opportunity denominators and the full incumbent
executor. Judge total compounded gain net of costs versus the incumbent, SPY
and QQQ, with drawdown and turnover reported. An uncertain scenario may retain
the incumbent; every specialist need not be used.
