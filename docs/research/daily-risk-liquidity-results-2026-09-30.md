# Daily risk and liquidity: completed first experiment

## Outcome

Volatility and dollar turnover are forecastable, but these results do not
establish a better trading strategy. Keep `/5` unchanged. Retain the simple
learned volume baseline and the existing CNN as research comparators; do not
start a larger neural-volume model or volume-scheduling project on this evidence.

The [frozen protocol](daily-risk-liquidity-plan-2026-09-30.md) was committed as
`32fce610` before implementation. Code and the pre-run baseline clarification:
`f31adb8937a14fbd9cf1a0b8ad7f7ea464a5fe3c`, clean at execution. Source base:
GitHub main `908e683`; research branch `research/daily-risk-liquidity-20260930`.

## Measured forecasts

98 existing cube files, 94 eligible stock names, 2,700 exchange sessions;
86,062 input rows. Labels observed: 85,093 next-session RTH variance/turnover
rows and 81,389 five-session gap-augmented variance rows. Seventeen expanding
chronological test blocks, first test 2018-04-19, last input 2026-09-29.
Refit every 126 sessions, 63-session validation and five-session purges on both
boundaries. All names share date partitions. Four CPU threads; no GPU training.
The complete historical run took 26.97 seconds on Spark.

LightGBM's reduction in primary prediction loss versus the strongest simple
comparator in each window (positive is better):

| Target | Primary loss | 2018–2023 | 2024–2026 | Reading |
|---|---|---:|---:|---|
| Next-session RTH variance | QLIKE | +3.45% | +9.73% | Forecast research lead only |
| Five-session gap-augmented variance | QLIKE | −1.37% | +8.75% | Inconsistent; no incremental lead |
| Next-session dollar turnover | Log-MAE | +0.76% | +0.83% | Below the registered 2% increment |

The HAR-style linear model already reduced volume log-MAE by **18.92% / 21.65%**
versus trailing-20 averages. LightGBM reached 19.53% / 22.30%. Same-weekday
averaging was worse than trailing-20. There is measurable volume predictability;
there is little incremental value from the nonlinear model in this study.

RTH LightGBM versus HAR paired daily-loss t statistics: **1.82 / 3.34** (HAC20).
The earlier-window improvement is not strong statistical evidence, especially
after multiple comparisons. The forecast lead label is a screening result,
not statistical confirmation or live approval.

On common rows with the older CNN archive, RTH log-MSE was:

| Model | 2018–2023 | 2024–2026 |
|---|---:|---:|
| HAR-style ridge | 0.40668 | 0.46275 |
| LightGBM | 0.40342 | 0.43889 |
| Archived CNN | 0.38207 | 0.43852 |

The CNN retains `legacy-unrecorded` row provenance. It was not retrained or
requalified here. This comparison gives no reason to claim a new neural advance.

## Regimes and uncertainty

The 10th–90th percentile bands covered 79.8% / 77.8% of RTH outcomes,
81.3% / 78.8% of gap-augmented outcomes and 80.3% / 78.2% of turnover outcomes.
These are prediction intervals for the named quantity, not high/low price bands.

Aggregate accuracy hides meaningful failures. In high-SPY-volatility sessions
with SPY below its trailing-60 average, RTH LightGBM was **2.81% worse** than
the strongest simple model on 2018–2023. For the gap-augmented target, the
recent stressed slice exceeded the predicted 90th percentile **21.60%** of the
time, not the nominal 10%. That is unsuitable evidence for a confident risk-off
switch. Regimes use observable features and training-only thresholds, not
hindsight labels for crashes. These slices are diagnostics, not a rule search.

## Execution relevance

Read one paper-state snapshot without broker calls. Its policy stamp is `/4`;
per-order policy versions are absent. It is **not a verified `/5` trade history**.

- 74 journal entries, 65 with positive recorded fills. Median filled-order
  notional $1,973; maximum $10,615. Total recorded filled notional $173,619.52.
- 51 completed orders matched a previous-session turnover forecast. Thirteen
  filled entries lack completion timestamps and one is a non-filled/partial
  status; these were not assigned invented execution dates.
- Median matched order / predicted daily turnover: **0.000138%**; 95th
  percentile **0.001207%**. This uses actual filled sizes retrospectively, not
  proposed sizes known before execution. Daily turnover is not displayed depth.
- Saving a hypothetical 1/5/10 bp on every recorded filled dollar gives
  **$17.36 / $86.81 / $173.62** across this journal. At the snapshot's $100,030.89
  equity, the 5 bp scenario is 0.0868%. These are sensitivities, NOT measured
  savings, achievable improvements, annual returns or an oracle ceiling.
- Separate `/5` cap scenario: a $25,007.72 order (25% of that fixed equity),
  across all eligible recent stock-days, has 95th-percentile participation
  **0.02642%** of forecast daily turnover. These are not historical `/5` orders.

Do not implement sophisticated scheduling from this evidence. Order-book
spread/depth, executable timestamps and missed orders are needed to measure
actual execution improvement. Paper fills alone cannot establish it.

## Verification and retained artifacts

The actual CLI ran from the clean implementation revision, saved predictions
and strict JSON, and completed successfully. The acceptance test independently
exercises fixture input loading, real CPU fitting and artifact readback.
Fourteen new tests cover future-input/test-label mutation, missing sessions,
split invariance, gap/turnover definitions, membership, seasonal baselines,
training-only imputation, purges, missing broker timestamps and output refusal.

**81 related tests passed** on `f31adb89`, including the existing cube,
volatility, day-type, session-anatomy, execution and deep-intraday suites.
Ruff and `git diff --check` passed. Existing LightGBM API-deprecation and
multiprocessing-fork warnings remain. The first broader run had two unrelated
Chronos-cache failures; using the already-present cache with
`HF_HOME=/home/animallya96/scratch/hf HF_HUB_OFFLINE=1` made both pass without
downloads or permission changes. `CUDA_VISIBLE_DEVICES=` is required even for
the older CPU Torch tests, whose optimizer otherwise probes CUDA.

Independent recomputation, without the study's label/score helpers:
**120/120 score rows**, **51 target-fold boundary records**, and **6,000 sampled
label cells** (5,855 observed, 145 missing). Maximum label and score difference:
**zero**. The [verification result](scorecards/daily-risk-liquidity/verification.json)
and [standalone verifier](scorecards/daily-risk-liquidity/verify.py) are retained.

Full [scorecard](scorecards/daily-risk-liquidity/results.json) includes every
regime, baseline, fit iteration, input hash and coverage exclusion. Predictions
remain on Spark, outside production:
`/home/animallya96/scratch/daily-risk.06R33E/results-v1/predictions.npz`.
SHA256: `3c007a92c4d12e558456c034b836c62ad6635efa5c6a097d56270d8009f314b6`.

Run from the research checkout with the existing research Python:

```sh
CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 \
  /home/animallya96/research-venv/bin/python \
  -m backend.cli.market_daily_risk_liquidity \
  --cubes-dir /home/animallya96/deploy/anios/data/market/research/sip_cubes \
  --paper-state /home/animallya96/deploy/anios/data/market/paper/state.json \
  --cnn-forecast /home/animallya96/scratch/vol_forecasts.npz \
  --out-dir /home/animallya96/scratch/daily-risk-new-result
```

The output directory must not already exist. Do not run with `--smoke` and call
that registered research. Reproducibility requires matching input hashes, not
merely rerunning against today's changing store.

## Limits and next decision

Historical availability is not certified by a hash. Membership does not restore
missing delisted-company prices. Full-session cubes exclude early closes and
some incomplete days; those exclusions and missing outcomes remain explicit.
The overnight component is the net close-to-open move, not the full premarket,
postmarket or overnight path. Genuine crashes were not winsorized away.

No allocation, entry, exit, sizing or dashboard action changed. **No portfolio
return or SPY/QQQ comparison is claimed**, because no new action policy was
tested. Reused 2024–2026 data is not a fresh holdout. Future action-policy work
must demonstrate incremental net returns and drawdown benefits against `/5`
and both indexes, including false exits and missed recoveries. These forecasts
do not justify reopening the already-failed blanket volatility-sizing strategy.

Diagram impact: NONE — internal offline forecasting/evaluation in the existing
market-data subsystem; no new service, dependency or live flow.
