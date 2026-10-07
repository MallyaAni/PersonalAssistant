# Nonlinear remaining-session continuation

Objective: improve ordinary buy/sell execution timing using the remaining session,
not a universal price percentage or only a one-bar forecast. The existing Ridge
suffix and volatility-normalized teacher model are implemented. Their conditional
component results do not qualify live adoption. The active actual-policy timing
comparison, its source, fixed300-account grid and results remain unchanged.

Exactly one new hypothesis: pooled nonlinear continuation heads, trained at every
ordinary clock, improve their own suffix policy instead of approximating the
previous Ridge policy. This is a finite fitted policy iteration, not a proven
optimal stopping solution or a new holding/profit-exit policy.

Use the same original21 causal features, stock-only training, fixed HistGradient-
Boosting squared-error estimator (64iterations,15leaves,learning_rate0.05,
min_samples_leaf200,early_stoppingFalse,random_state0), and prior20-session
volatility times sqrt((24-clock)/26) normalization. These are unchanged registered
capacity/scale conventions, not fitted execution thresholds. Fit all clocks0..23
in each pooled side head. Terminal24 remains lifecycle completion, not a forecast.

Fit only on each calendar month's first supplied session. Keep min504/max756
sessions and conservative10-session label maturity, with the existing August17
freeze. Every training endpoint must strictly precede the monthly cutoff. Three
whole-date folds use original calendar index modulo3; no held date's ticker,
clock, outcome or preprocessing row enters its nuisance fits. All training dates,
features, normalized targets, selected clocks and estimator parameters are bound
by receipts. Training data remains current-vintage conditional evidence.

For each nuisance complement, initialize a terminal-only execution policy.
Perform exactly three fixed policy-improvement fits before seeing real outcomes.
At each iteration, train side heads from stop-minus-selected-future execution
price, divided by the observed close and causal volatility scale. Select each
future suffix using the preceding iteration's forecasts from features observed
at that future clock. The suffix starts strictly at current clock+1. Read the
selected realized training price after selecting the clock; never select the
hindsight minimum, maximum or better outcome. Missing chosen prices remain
missing even when another future price exists.

The three-iteration limit is a bounded approximation; record action changes and
do not claim convergence. Apply the final complement policy to held dates, then
fit two final pooled heads using their held-fold suffix labels. These final
heads are one further policy improvement over the excluded-date chains, not an
exact Bellman solution. Neither inner held predictions nor training fit scores
are economic out-of-sample evidence. Outer monthly scoring uses only causal
features, without requiring the scoring period's labels or execution outcomes.

Before historical training: exercise actual fixed estimators on synthetic paths;
correct buy/sell signs; excluded held-date outcomes cannot affect nuisance model
bytes; mutation of scoring outcomes cannot affect predictions; all-clock coverage;
missing chosen outcomes and unknown terminal prefixes stay missing; benchmark
training exclusion; strict monthly/maturity/date/feature contracts; stock-volatility
scale equivalence; retention of unfavorable prediction-selected execution prices.

No real historical fit or economic scoring is authorized by passing these tests
alone. First authenticate original input/model/calendar units and write the
bounded account evaluation contract. Evaluate actual funded planner/sender parity
at fixed0/10/25bp, common carried books, SPY/QQQ/current rule and every declared
period; retain missing outcomes and all tested starts. Reuse completed benchmarks
only when the source/account contracts match. Do not change the active comparator
or choose a model, threshold, clock, window or regime from observed returns.

The requested holding/profit-exit and stock-specific funded sizing enhancements
remain separate acceptance requirements. No ordinary execution forecast should
be presented as deciding whether a profitable holding should remain in the book.
No live imports, broker calls, paid data, data rewrites, model-service changes or
deployment belong to this implementation step. Diagram impact NONE: existing
internal research model/account boundary, with no new subsystem or live flow.
