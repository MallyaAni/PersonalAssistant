# Specialist contributions: implementation and fixed evaluation

Protocol `specialist-contributions/1`, registered before new model outcomes on
2026-10-01. Starting source `74c2ef75`, branch
`codex/specialist-contributions-20261001`. User authorized all implementable
specialist contributions, parallel work, and evaluation. This is research
implementation; adoption still requires economic evidence and guarded release.

## Frozen evidence and comparisons

Reuse the original immutable `forecasts-v2.json`, `portfolio.npz` and source
declarations under Spark `scratch/open-source-inputs-20261001`. No provider
request, frozen-file replacement or rerun of unchanged univariate inference.
Twelve original symbols, September 3–30, 2026 (19 close decisions), 252 daily
context observations, ten-session horizon, checkpoint/code pins, seed and
10/25 bp funded-cost conventions remain unchanged. Original grades are later
reconstructions; price availability is assumed at close, not attested original
publication. This retrospective diagnostic is not an untouched holdout.

Joint Chronos-2 and TimesFM-3 receive the target, explicit context members and
SPY in one multivariate group. For NVDA/AMD/AVGO the context is the other two
semiconductor names. For MSFT/AMZN/GOOGL/META it is the other three platform
names. AAPL/TSLA/AAOI receive QQQ as a declared broad-market proxy, not a sector
label. Each benchmark receives the other benchmark. Duplicate channels are
removed. These are declared research peer groups, not point-in-time historical
sector assignments; mapping availability is assumed September 3 at 16:00 ET.
No future market prices or future-unknown covariates are passed to a model.
Both joint and original univariate predictions share the same causal inputs.
Downloaded TimesFM-3 and its outputs remain non-production research only.

The allocation decomposition holds incumbent grade eligibility and capital
constraints constant. It compares incumbent sizing, joint ranking within that
eligibility, covariance-only sizing, covariance plus TTM risk reduction,
gross-matched incumbent sizing, and the combined research candidate. Report
unavailable opportunities rather than remove them. Use one source-global
ten-session reset phase and the existing funded next-adjusted-open ledger;
this declared control is not exact live intraday-policy reconstruction.

## Candle timing

Kronos-small uses 252 completed regular 15-minute RAW bars, with the unchanged
official checkpoint/code, eight independent paths using seeds 0–7 and a
horizon covering the remaining regular-session slots. One permission per
original allocation intent is issued after the first completed bar (09:45 ET),
and expires at regular close, including early closes. Buy cap is the empirical
25th percentile of sampled remaining low minima; sell floor is the 75th
percentile of sampled remaining high maxima. A buy cap may not exceed the
last observed close; a sell floor may not be below it. No threshold search.

Only a later consecutive bar OPEN favorable to the permission may establish
a bar execution proxy. An intrabar touch is not a fill; missed orders remain
missed. No fabricated quotes, midpoint fills or bid/ask spreads. Grade intent,
cash, existing quantities and total holdings belong to the common account,
not the forecaster. Report missed buys, missed exits, partials, expiry and
realized turnover. Decisions never use that day's eventual official close to
adjust RAW prefixes. Split-discontinuous raw history is unavailable unless a
dated, causal corporate-action reconciliation is supplied.

The funded timing diagnostic uses the same prior-close adjusted-unit intents
at September 3 and September 18, executed September 4 and September 21.
All twelve declared symbols at both resets remain in the denominator. A
unit-sized permission probes the price bound only; the shared ledger funds
the actual fractional adjusted research units with NAV 1. This is not a
broker whole-share account. Compare a next-open control, a control restricted
to causally prepared/valid model permissions, and the bounded path candidate.
No additional retry or close fallback is introduced on any of those lines.
Convert RAW proxy prices to common adjusted economics only after the decision,
using the daily adjusted close divided by the cube's official session close.
That label-only conversion never enters intent sizing or forecast permissions.
If its source is unavailable, retain the opportunity as unavailable; do not
infer a ratio from a different time or a later price. This small diagnostic
cannot establish intraday live parity or a midpoint fill.

## Risk and scenario selection

Ledoit-Wolf uses preceding 252 adjusted-close returns. Long-only weights have
25% name caps. Covariance-only sizing preserves feasible incumbent gross;
TTM risk sizing may reduce but never increase it. Risk multiplier is capped
at one and compares the predicted mean squared return to the trailing
20-session counterpart. Include a gross-matched incumbent control to isolate
composition from cash. Missing risk evidence retains incumbent sizing with a
recorded fallback rather than creates fictitious confidence.
The fixed sizing objective minimizes covariance divided by its trace plus
the squared distance from the incumbent weights times the risk multiplier,
with distance coefficient one. TTM marginal variances preserve the estimated
correlation matrix; the multiplier compares aggregate forecast risk with
aggregate trailing risk. This is anchored risk adjustment, not pure minimum
variance or a fitted return-maximization claim.

Scenario features are SPY's trailing 60-session return sign and trailing
20-session realized volatility relative to the median of preceding 252
volatility observations. Threshold history excludes the current observation.
Insufficient history is explicit. These are observable diagnostic partitions,
not a claim that true latent regimes can be identified without error.

A monthly nonnegative convex specialist selector fits only complete dated
incremental utilities relative to the incumbent, with prediction/evidence
known by their decision and label end/availability strictly before the test
month. Require at least 20 eligible observations from at least three distinct
prediction months in that scenario. Weights are frozen during the test month;
unallocated weight stays with the incumbent. September's short artifact set
cannot satisfy this requirement and must fall back, rather than manufacture
a learned edge. Do not reuse future rows or select retrospective test winners.

## Acceptance and adoption

Test input units, late publication, completed-bar causality, future-prefix
invariance, sample identity, early closes, cash conservation, no overselling,
label purging, monthly freezing, missingness and complete common denominators.
Run actual pinned model inference on CPU and bind artifacts to source hashes.
Report compounded gain against incumbent, SPY and QQQ, costs, drawdown,
realized volatility/tail losses, exposure, turnover and scenario counts. Short
annualized metrics are descriptive. No superiority or live activation follows
from implementation tests, small retrospective slices or author benchmarks.

KiT cannot be natively implemented until official code/weights are released.
Chroma's specialist-selection principle is implemented by the causal selector;
do not mislabel it as reproducing Chroma's pretrained weights or training.
Nautilus remains the execution acceptance tool, not an alpha model. Existing
Docling provenance fixes remain; no duplicate parser or unrelated cleanup.
