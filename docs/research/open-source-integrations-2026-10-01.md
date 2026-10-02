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
