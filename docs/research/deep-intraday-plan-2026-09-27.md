# Deep sequence models on the fifteen-minute bars: pre-registration (2026-09-27)

The operator asked whether a time-series neural network with reinforcement
learning could earn a higher CAGR than the measured graded equal-weight
book. This note is the plan written before any model is trained, with the
kill criteria fixed first, so the result cannot be argued into a success
afterwards. Stage 1 is deliberately small: one evening on spark1's CPUs,
one question. Everything that follows is gated on its answer.

## What the literature says held up out of sample

Read on 2026-09-27; the pattern, not the details, is what matters here.

- Intraday **volatility and volume** are strongly forecastable at every
  horizon; this is the least controversial result in the field and the
  one every model in this family gets for free ([volume forecasting with
  ML](https://arxiv.org/html/2505.08180v1)). A model that "predicts
  returns" but is really predicting volatility is the standard false
  positive.
- **Index-level intraday momentum**: the rest-of-day return predicts the
  last half hour, on 60 futures across asset classes, equity βROD 4.18 (t
  7.3), R²OOS 2.9%, Sharpe 0.9-1.7 before costs, stable 1974-2020 and
  strongest under option-dealer negative gamma and leveraged-ETF
  rebalancing ([Baltussen, Da, Lammers, Martens](https://academicweb.nd.edu/~zda/intramom.pdf);
  the original [Gao, Han, Li, Zhou](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866)).
  It is a flow effect at the index level; individual names carry it only
  through their beta. Our own session-anatomy run found the first
  half-hour uninformative for the book's names (slope +0.02, t 0.2), which
  is consistent: the effect is late-day and index-driven, not open-driven
  and name-specific.
- **Cross-sectional deep learning on daily panels** ([Deep Learning
  Statistical Arbitrage](https://arxiv.org/abs/2106.04028)): factor
  residuals, a convolutional transformer signal and a policy trained on
  Sharpe, high out-of-sample Sharpe on ~500 names over decades - with
  returns that decline over the sample and are highly sensitive to costs.
  The lesson is the recipe (residualize, learn on a large cross-section,
  train the policy on the objective with costs inside it), not the
  headline number, which our 94-name book cannot reproduce.
- **Deep limit-order-book models** ([microstructural guide](https://arxiv.org/html/2403.09267v1)):
  high classification accuracy that "does not necessarily correspond to
  actionable trading signals"; predictability depends on tick size and
  liquidity and evaporates once a complete round trip is required.

The prior these set: a small model on our bars can plausibly find (i)
next-session volatility, (ii) a late-day index flow effect, (iii) a small
cross-sectional return signal that must be tested against costs and the
equal-weight hurdle. It is unlikely to find a large name-specific return
signal, and if it appears to, leakage is the first suspect.

## Stage 1: the one question

**Does a small sequence model on the last five sessions of fifteen-minute
bars carry out-of-sample information about the next session that the
grade does not already have?**

- **Data.** `sip_cube` for the book's names, point-in-time membership,
  complete 26-slot sessions only. Choosing window 2016-2023 (walk-forward
  folds inside it); 2024-2026 reported, never tuned on.
- **Inputs, one row per (name, session t).** The last `K=5` sessions of
  bars as a 130-step sequence with three channels: bar log return, bar
  volume share of the session, bar range over close; plus the session's
  gap and the name's trailing 20-session return and volatility as
  scalars. Nothing after the close of t.
- **Targets.** (a) next session's open-to-close log return,
  rank-normalized within the date's eligible names (the ranking question);
  (b) next session's realized volatility, log of the sum of squared bar
  returns (the volatility question, kept separate so (a) cannot be
  credited with it).
- **Models.** Ridge regression on the flattened inputs (baseline); a
  temporal CNN of about fifty thousand parameters (three dilated
  convolutions, global pooling, two heads). CPU training; refit every 63
  sessions on an expanding window with a 5-session purge; first fit after
  500 sessions. No hyperparameter search beyond one fixed configuration
  written here: Adam 1e-3, 20 epochs, batch 512, dropout 0.1, weight decay
  1e-4.
- **Added 2026-09-27, before any of the four was run on the store.** Two
  more model families on the same inputs, targets, walk-forward and
  configuration constants: a PatchTST (non-overlapping patches of 13
  steps, channel-independent, d_model 64, two encoder layers, mean-pooled)
  and a frozen pretrained Chronos-Bolt encoder whose mean-pooled
  embedding of the bar-return channel feeds the same ridge as the
  baseline; with both counted on both targets the trial count becomes
  eight. Transfer learning is tried as a frozen encoder rather than
  fine-tuning because a frozen encoder adds no training loop and no
  learning rate or epoch count to choose - the embedding of a row depends
  on that row alone and the only fitted object is the ridge on top, so the
  one-configuration, no-search rule and the purge hold as written;
  fine-tuning is a stage-2 question if the frozen embedding shows
  anything. The models now train on the GPU when one is present; the
  statistics, the schedule and the kill criteria do not change.
- **Metrics.** Return head: daily cross-sectional Spearman IC, its mean
  and Newey-West t over dates; and the equal-weight top-quintile
  portfolio (next-session open to close, 10 bp) against equal weight of
  every eligible name, paired HAC t at lag 20 - the same hurdle every arm
  faces - plus the same restricted to names the desk graded A/A+, to
  answer "does it add to the grade". Volatility head: out-of-sample R²
  against the trailing 20-session realized volatility, per window.
- **Kill criteria, fixed now.** Return head: mean IC t < 2.0 on
  2016-2023, or top-quintile-minus-hurdle t < 2.0 at 10 bp, is
  INSUFFICIENT EVIDENCE and stage 2 does not start. Volatility head: R²
  OOS <= 0 against trailing volatility is a failure of the model, not a
  finding. A return-head result that vanishes when the volatility head's
  prediction is added as a control is a volatility result and is reported
  as such. Trials counted: two models, two targets, one configuration -
  four (eight with the two families added on 2026-09-27, above; a
  payload counts the pairs it ran against that total).
- **Budget.** One evening on twenty CPU cores. If it needs the GPU it is
  already too big for this question.

## Stage 2, only if stage 1 passes

Reinforcement learning as the sizing and timing layer, never as the
return predictor: an agent that takes the stage-1 forecasts and the
desk's state and chooses weights inside the simulator whose fills the
shadow ledger has validated against the broker, with costs in the reward.
Its hurdle is `ew_graded_full` under the live execution policy on the
choosing window. Not before the shadow has run.

## What would make me wrong about the ceiling

A stage-1 IC above 0.05 with t above 4 on the choosing window that
survives the volatility control and the cost-charged portfolio test. That
would say the book's names carry a name-specific intraday signal the
literature does not lead me to expect, and the GPU week would be earned.
