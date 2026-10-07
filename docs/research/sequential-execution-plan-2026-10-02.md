# Sequential execution: fixed continuation-policy experiment

Objective: improve buy/sell timing without a universal percentage distance,
holding the grading and target policy fixed. The earlier stock-conditioned
fifteen-minute forecasts are implemented and numerically VERIFIED, but their
adoption evidence FAILED. Their risk calibration improved while their price
forecasts did not beat the existing timing control. No live replacement is
implemented or proven. This is one new, separately registered hypothesis:
value the remaining session's execution opportunities rather than only the
next fifteen-minute return. Do not run an unregistered model/threshold search.

Method motivation: [Longstaff–Schwartz (2001)](https://doi.org/10.1093/RFS/14.1.113)
estimates continuation values to decide when to exercise an option. Here the
adaptation is a real-world execution-price policy improvement, not option
pricing, risk-neutral valuation, proven optimal stopping or evidence of alpha.

Use the same original 94 stock names plus SPY/QQQ, snapshot and frozen original
SIP cubes/prepared features. Original artifact hashes and source provenance
must pass. Existing observations are reused diagnostics, not new untouched
research evidence. Dates remain 2018-02-01 through 2026-09-30, all twenty reset
phases, zero cash yield and 0/10/25 bp per-side costs. Keep v5 grades/targets,
funding, first-attempt locks, retained partial/missing outcomes and carried NAV.
Weights are min(1/eligible_count,25%); there is no hard-coded 9% target.
Each account's quantities depend on its own prior NAV/holdings: identical
target policy does not mean identical realized share quantities.

The current live comparator differs from the old frozen curves. Deployed
621e28f0 uses a final market order at session close minus fifteen minutes;
origin/main204689db contains that source and its documentation. One new
matched current-gate control must use the current 1% completed-bar crossing
and that final next-open proxy. Old auction-terminal control curves remain
immutable and are not this comparator. Reuse SPY/QQQ reference curves only
after verifying their dates, units and costs; do not resimulate those ETFs.
This reconstructs the current price-gate semantics on the fixed target book,
not the whole cash-bounded/6 live executor or its historical paper receipts.

Clock contract: feature k observes completed bars0..k at09:45+15k minutes.
The next-open execution outcome is cube.open[k+1], never a known decision
input. Normal-session final action is k24, observed15:45, proxy open25.
The supplied preparation has no early-close support: all21 early-close dates
have unavailable prefixes/proxies. Retain those dates/opportunities as missing;
do not pad them or substitute auction/official-close prices. Runtime session
clocks still come from the exchange calendar; unsupported early-close evidence
prevents any claim of a ready all-session live replacement.

At each outer monthly cutoff use only the original mature prior window:
min504/max756 source-calendar sessions and conservative ten-session label
maturity, with the existing August17 cutoff retained. Use all ordinary clocks
0..23, terminal24. Only the stock pool trains; benchmark forecasts do not
train. Keep the original 21 causal features. No actual next-open, selected
future execution price, terminal price or future extrema enter a prediction.
Prediction eligibility uses prefix validity and a prior fitted head, not the
availability of a future outcome. Missing future labels only remove training
targets or make scored execution outcomes unavailable.

Exactly one estimator family: the existing Ridge pipeline (training-only
median imputation with missing indicators, standard scaling, alpha1,
Cholesky solver, float64 fit and fixed1e-8 numerical certificate). No estimator,
feature, hyperparameter, cost or window selection from outcomes. Use three
whole-session folds defined by stable source-calendar index modulo3. An outer
504-session window thus supplies about336 sessions per nuisance complement;
this is not a claim that each nuisance model sees504 sessions.

For each fold train an independent backward nuisance chain on its complement;
exclude every ticker/side/clock and preprocessing observation of held dates.
Terminal realized execution price is P24; missing P24 stays NaN. At clock k,
the side-specific target is
`(realized_next_open[k] - selected_future_price_side) / observed_close[k]`.
Fit its conditional expectation. Buy waits for positive predicted difference;
sell waits for negative predicted difference; zero means execute. This compares
expected stop-minus-wait costs directly: never compare a fitted continuation
with the actual unobserved current next-open. Update the training path using
the prediction-selected action, then read its realized price as the target.
Never select the realized cheaper buy/better sell or a hindsight day minimum.

Apply each independent chain to its held dates and compute suffix decisions
starting separately at k+1. A stop before k+1 cannot select that suffix.
Missing chosen execution locks that outcome as unavailable; no later-price
search or terminal fallback. Missing forecasts are separately unavailable;
the mandatory final action is separately labelled lifecycle completion.
Final clock/side heads train on all mature rows using those held-fold future
execution labels. Their nuisance future policy never saw the held session's
labels. This is one crossfitted policy improvement step; it is not an exact
Bellman solution. Inner dates may precede/follow each other inside the mature
outer window; inner outputs are never reported as out-of-sample performance.

No added risk multiplier or fixed price percentage. Volatility/structure are
stock-conditioned inputs; the objective is execution-price improvement with
existing position/exposure limits. This does not claim calibrated epistemic
confidence, optimal portfolio risk, covariance-aware sizing or a new allocation
policy. Portfolio gain/drawdown, turnover and fees still determine usefulness.

Acceptance before real fits: actual small Ridge fits/certificates; whole-date
fold exclusion; unfavorable prediction-selected outcomes retained; correct
buy/sell signs and suffixes; mutation of held labels cannot change their
nuisance heads/selected clocks; unknown test prices cannot change fixed-model
forecasts/actions; future test labels cannot change any monthly fit; prediction
retained despite missing outcomes; terminal action/missing fill/expiry distinct;
first attempt never retried after missing/partial fill; no same-observation sale
funding; every intent and stock wealth reconciles. Record targets and attempt
clocks so source-only target equality is not misrepresented as trace proof.

Freeze exact source before fitting. Fit once, then one fixed comparison with
all phases/windows, paired gains, CAGR, positive drawdown loss, Sharpe,
rolling252 wins versus SPY/QQQ/current gate, turnover/costs and explicit missing
outcomes. No selection by an attractive regime/phase or training fit. Independent
saved-byte verification must check clocks, data/model hashes, mature rows,
fold exclusion, funding, accounting and metrics without refitting/resimulating.
No adoption from this reused current-vintage diagnostic alone: any favorable
result still requires supported current-policy/shadow evidence and early-close
coverage before a guarded live release. No real orders, paid data, cache/history
rewrites, model-service changes, GPU use, old backtest repetitions or desk.run.
Diagram impact NONE for this experiment: existing internal research boundary.
