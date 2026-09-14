# Neural and sequential RL growth pilot — September 14, 2026

**Result: trained and reproducibly evaluated, not adopted.** Three supervised
neural scorers and three sequential RL allocators completed a bounded CPU run.
None beat either simple momentum baseline on total test-period wealth. The
neural models suffered large drawdowns; RL depended heavily on the random seed.
This does not establish that neural networks or RL cannot help the full desk.

## Regime dates and interpretation

The [June 17 FOMC statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm)
already omitted the forward-guidance language. The
[August 28 Jackson Hole speech](https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm)
elaborated on Warsh's objections to regular forward guidance. Treating August 28
as the first removal date would mix earlier policy changes into the old regime.
Neither source establishes that every pre-meeting selloff is caused by this change.

Both boundaries are reported. Each announcement day is a separate cell: daily
bars cannot isolate the intraday speech reaction. June 18–August 27 supplies
49 observations and one FOMC decision; August 31–September 11 supplies just nine
observations and no FOMC decision. These are market dates, not independent samples
multiplied by 93 tickers. The September 14 selloff is outside the completed daily
dataset. No significance claim, post-speech annualization or best-cutoff search.

## Experiment contract

- Training: 2018–2023. Last supervised label ends December 29, 2023.
- Selection: 2024 only. Last selection label ends December 31, 2024.
- Retrospective test: January 2, 2025 initial NAV through September 11, 2026;
  423 daily transitions. Earlier project experiments have examined this history,
  so this is not a pristine holdout.
- Inputs: causal price returns, volatility, moving-average distance and relative
  volume. RL also observes market breadth, scheduled FOMC distance and current
  cash/allocation. Unscheduled March 2020 events are not exposed in advance.
- Neural scorer: a small two-hidden-layer network predicts delayed four-session
  total log returns, trained by MSE. Best epoch is chosen on 2024 MSE. It selects
  up to ten positive-prediction names, with a 10% target cap per name.
- RL: sampled categorical policy gradient with a learned value baseline;
  120 episodes per seed, 26 sequential five-session periods per episode. Actions
  are cash, momentum20, momentum120, equal weight, and half-exposure versions.
  Current holdings affect costs and future states. No in-sample neural prediction
  is passed into RL. Checkpoints are chosen using 2024 net log wealth.
- Reward: undiscounted incremental log net NAV, scaled by a positive constant
  for numerical training. No volatility divisor or entropy/risk penalty.
- Accounting: decide after close, execute at next close, let prior holdings
  bear the intervening return. Fractional adjusted-price units approximate
  reinvested total returns. Costs are funded against traded dollars. Missing
  execution or held-asset prices invalidate a path; they are never zero returns.
- Evaluation costs: 10 and 30 bp per traded dollar; identical paths and starting
  capital across contenders. Ending NAV is marked, not liquidated; no invented
  cash interest. Each test account continues across the event boundaries.

## Results

These are **biased retrospective simulations**, not achievable return forecasts.
Today's thematic membership excludes historical failures and can favor recent
winners. The large baseline numbers make that limitation particularly material.

| Contender | Total return, 10 bp | Total return, 30 bp | Max drawdown, 10 bp |
|---|---:|---:|---:|
| USD | 0.00% | 0.00% | 0.00% |
| SPY | 31.19% | 30.93% | -18.76% |
| Momentum20 | 357.27% | 291.58% | -38.26% |
| Momentum120 | 396.68% | 365.76% | -48.13% |
| Equal weight | 129.61% | 127.03% | -33.39% |
| Neural seed 0 | 114.75% | 79.00% | -48.02% |
| Neural seed 1 | 163.09% | 125.88% | -52.54% |
| Neural seed 2 | 183.59% | 139.92% | -53.01% |
| RL seed 0 | 9.00% | 0.51% | -36.22% |
| RL seed 1 | 99.47% | 90.41% | -42.28% |
| RL seed 2 | 201.58% | 187.11% | -22.87% |

The same 10 bp paths, excluding both announcement days:

| Contender | June 18–August 27 | August 31–September 11 |
|---|---:|---:|
| USD | 0.00% | 0.00% |
| SPY | 4.34% | -0.66% |
| Momentum20 | -2.68% | -10.58% |
| Momentum120 | -24.05% | 5.46% |
| Equal weight | -0.26% | 1.50% |
| Neural seed 0 | -2.05% | 13.18% |
| Neural seed 1 | -4.98% | 6.73% |
| Neural seed 2 | -0.10% | 7.78% |
| RL seed 0 | -27.94% | 0.00% |
| RL seed 1 | 2.89% | 1.50% |
| RL seed 2 | -11.20% | 2.81% |

The reversal across these periods supports reporting them separately. It does
not identify a stable new distribution or establish that the speech caused it.
An unseen regime flag has no learnable historical effect; an adaptation model
would need prospective observations and uncertainty bounds, not a hand-assigned
profitable response. The highest post-speech seed is not selected for adoption.

## What this does and does not prove

VERIFIED: real training completed at source 3dcce629; six weights files and
22 account paths retained. Twelve causality/accounting/objective tests passed.
Frozen-model replay independently loaded all six saved models and reproduced
their 12 cost-specific paths (NAV tolerance 1e-10, exact decisions and dates).
Price and feature hashes must match the original manifest before replay.

UNVERIFIED: a calibrated current-price opportunity predictor, full analyst/
DeepSeek feature integration, point-in-time universe membership, historical
spread/liquidity/settlement realism, and superiority over the adopted desk.
This daily pilot does not apply or replace the adopted FOMC overlay and does not
model 15-minute entry timing. Existing dashboard, paper and real accounts are
unchanged by the experiment. Training used two CPU threads and no model-serving
GPU resources. No new prompt or production policy was introduced.

The next useful comparison needs historical membership including delistings,
dated analyst/valuation features, and the adopted desk evaluated with identical
execution and event constraints. Only then should an adapted challenger enter
the separate forward paper track. Preserve pre/post-June and post-Jackson-Hole
reporting and keep the short prospective regime separate from model selection.

## Artifacts and replay

Full artifacts on spark1:
`/home/animallya96/research/growth-pilot-20260914-3dcce629/`.
Machine-readable [summary and hashes](growth-pilot-2026-09-14.json) are committed.
Source is `backend/cli/market_growth_pilot.py`; pure accounting is in
`backend/market/growth_pilot.py`. `--verify` replays without training or writing.

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 CUDA_VISIBLE_DEVICES= \
python -m backend.cli.market_growth_pilot \
  --data-dir /home/animallya96/anios/data/market \
  --output /home/animallya96/research/growth-pilot-20260914-3dcce629 \
  --asof 2026-09-14 --revision 3dcce629 --verify
```

A fresh training invocation must use a new output directory. Its manifest pins
the source argument, dependencies, input hashes and dates. The stored models
are research artifacts; no runtime reads them for trading decisions.
