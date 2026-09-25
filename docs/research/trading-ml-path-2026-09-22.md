# Trading ML path — primary-paper review and a prospective specification

Reviewed 2026-09-22. Objective: identify research relevant to stock-level sizing
without treating prediction accuracy as profit or expanding the authorized fixed
strategy evaluation. This is a specification only: no training, model downloads,
data purchases, orders, services or dashboard changes.

September 25 supplement: [2026 microstructure research at a 15-minute cadence](microstructure-15-minute-review-2026-09-25.md)
reviews TradeFM and an intraday falsification study, distinguishes cadence from
holding duration, and records a separate unlaunched timing hypothesis. It does
not change this document's frozen ten-session forecast specification.

## What the papers establish

**DeepLOB — Zhang, Zohren and Roberts.** A CNN/LSTM forecasts short-horizon
mid-price direction from event-level limit-order books. The LSE experiment uses
chronological training, validation and test periods and also tests unseen stocks.
Its trading illustration executes at mid-price and reports gross profit before
fees; it is a comparison of predictors under simplified execution. It does not
establish attainable net returns for this desk. The relevant lesson is to test
temporal and cross-instrument generalization, then separately evaluate realistic
execution. Daily OHLCV and 15-minute bars do not reconstruct the book states this
model requires. [Primary full text, especially sections V-C and V-D](https://arxiv.org/html/1808.03668v5).

**Sirignano and Cont.** Their network predicts the direction of the next
mid-price change using order-flow history across many equities. They compare
pooled and stock-specific models, evaluate later periods and previously unseen
stocks, and find predictive benefits from pooling and history. This is evidence
about price formation and prediction; the study does not provide a net-of-cost
trading ledger for this desk. The earlier draft's description of accuracy as only
a few points above chance was unsupported and is removed. Pooling is a research
idea worth testing, not proof that event-level forecasts transfer to multi-day
returns. [Primary paper, sections 2–4](https://arxiv.org/pdf/1803.06917).

**Gu, Kelly and Xiu.** They predict monthly stock excess returns using stock
characteristics and macroeconomic interactions, with chronological training,
validation and an expanding out-of-sample evaluation. Trees and neural networks
capture useful nonlinear interactions; momentum, liquidity and volatility are
prominent predictors. Portfolio and market-timing illustrations connect forecasts
to economic outcomes, but their headline portfolio returns do not establish
after-cost performance here. Neither a value-weighted gross Sharpe ratio nor an
equal-weighted one proves realizability; declaring either impossible is also
unjustified without an execution/cost analysis. This is the closest conceptual
match to cross-sectional sizing, although its monthly horizon, universe and
long-short portfolio differ from our long-only stock/index/cash problem.
[Authors' September 2019 full text](https://dachxiu.chicagobooth.edu/download/ML_BKP.pdf);
[published article](https://doi.org/10.1093/rfs/hhaa009).

**Nevmyvaka, Feng and Kearns.** Their reinforcement-learning problem optimizes
execution of a given inventory over a short deadline, using order-book state,
remaining time and remaining inventory. Historical-book simulation evaluates
execution cost relative to simpler execution policies. This addresses how to
trade a decided order, not which stocks to own. Their simulation assumes
negligible commissions/exchange fees and no order-arrival delay. Transfer would require suitable
book data, controllable order placement, and validated fill/impact assumptions.
It does not require an independent intraday alpha signal to be useful in
principle, but the present next-open research ledger cannot test this mechanism.
[Primary ICML paper](https://www.cis.upenn.edu/~mkearns/papers/rlexec.pdf).

**Inference for this project:** cross-sectional return prediction is a more
direct hypothesis for multi-day sizing than copying a limit-order-book network.
These papers neither establish that HFT alpha survives this desk's costs nor
prove it cannot. More daily rows do not establish more independent evidence than
a monthly panel: shared market moves, overlapping labels and repeated regimes
create dependence. Calendar coverage and honest untouched observations matter.

## Current evidence and boundaries

The current integration's authoritative accounting convention is a close-time
decision followed by next-open execution, NAV starting at 1, 10 bps per traded
dollar per side, zero cash yield, and the predeclared 25 bps cost stress. This
applies to both buys and sells in the funded evaluation. Old research modules or
legacy order paths with next-close fills are not interchangeable with it.
The source is experimental and is not evidence of a deployed live configuration.

The fixed `vol` and `vol_trend` comparison retains 2016-01-04 through 2026-09-18
and both dividend-inclusive SPY and QQQ benchmarks. These reused observations
are development evidence, not a fresh holdout. This review authorizes no changed
windows, additional horizon sweep, fitting, threshold search or repeated baseline.
See `MAC_CONTINUATION.md` for the measured results and artifact provenance.

An immutable downloaded snapshot proves what was retrieved then; it does not
prove every historical field was available at its historical decision date.
The retrospective survivor-selected book and current-constituent comparison
cannot establish survivor-free performance. A non-book subset of today's
survivors does not solve that problem. Past pilot documents can inform failure
hypotheses, but their different labels, fills and populations are not comparable
performance evidence for this implementation.

## One prospective experiment, specification only

No model is fitted or launched by this document. Before any later authorized
shadow experiment starts, freeze the following in a versioned registration:

- **Question and horizon:** does a stock-relative forecast improve the existing
  long-only allocation? Use exactly **10 trading sessions**, retaining the
  existing ranker's horizon; do not search 5/10/20 sessions or select a horizon
  after viewing results. Define the label as the stock return from the next
  executable open through the open ten sessions later, less SPY over those same
  endpoints, with consistent corporate-action/total-return treatment.
- **Point-in-time data:** retain observation and publication timestamps,
  fundamentals' original releases and revisions, corporate actions, historical
  membership, listings and delisting outcomes. Fit transformations using only
  eligible training observations. A label enters training only after its entire
  outcome is observable. Missing evidence remains missing rather than filled
  using later knowledge. Without these records, mark the historical claim
  unverified and restrict conclusions to the prospectively recorded universe.
- **Locked comparison:** before seeing prospective outcomes, nominate one
  existing model/configuration, feature set, training window, refit cadence and
  forecast-to-weight rule. Keep the shared risk caps, eligibility and funded
  execution unchanged. Record any legacy model's historical tuning exposure.
  No model/hyperparameter contest or adaptive best-of selection is authorized.
- **Separation:** use chronological folds for any later authorized training;
  purge every training observation whose label interval overlaps validation or
  test outcomes. With this label that covers at least its ten-session span,
  including the next-open offset; enforce interval overlap directly rather than
  relying on an inherited five-session embargo. Fix any additional embargo
  before evaluation. Do not reuse the fixed 2016–2026 comparison as untouched
  ML evidence.
- **Prospective shadow:** timestamp forecasts, inputs, membership, configuration
  and intended weights before executable opens. Freeze a future evaluation
  start, duration and review date before collecting outcomes. Keep predictions
  shadow-only and retain all failures; no early stopping when results look good.
- **Accounting and comparisons:** use the same next-open funded ledger, NAV1,
  10 bps and predeclared 25 bps stress, zero cash yield and explicit research
  index eligibility. Compare with **both SPY and QQQ**, the frozen non-ML
  allocation, and a predeclared simple stock baseline on identical sessions.
  Report net compounded return, maximum drawdown, rolling-window success,
  turnover, fees, concentration and actual exposure. Rank IC is a diagnostic,
  not an adoption criterion by itself; uncertainty must account for shared dates
  and overlapping labels rather than treating stock-days as independent.

## What would justify a later adoption decision

The intended objective remains higher net compounded return than both SPY and
QQQ with no greater maximum drawdown than either, assessed at the registered
review date and alongside cost sensitivity, rolling consistency and dependence-
aware uncertainty. Any improvement must also be attributable against the frozen
non-ML comparator under the same execution and risk constraints. A favorable
single backtest, accuracy score or conventional IC t-statistic is insufficient.

Failure to establish data availability, membership history, causal labels or
adequate untouched evidence keeps the candidate experimental. Passing a future
shadow evaluation would support a separate adoption review, not automatic live
orders or a claim of universal superiority. The present implementation/evaluation
task does not authorize that training or adoption step.
