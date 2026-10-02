# Risk contributions and causal monthly selection

Research-only addition on `codex/specialist-contributions-20261001`.
This contract freezes a contribution mechanism before new economic outcomes;
it does not establish a profitable risk policy, regime edge or live adoption.
The combined evaluator owns funding, costs, cohort membership and comparisons.
No pretrained model, provider query, original forecast or production caller is
changed here.

## Objective and boundaries

Assess risk composition, risk exposure and specialist selection separately.
Every specialist weight is nonnegative; the incumbent receives the remaining
weight. Neither missing forecasts nor insufficient selector history become a
fictional cash strategy or a discarded opportunity. Retain those observations
as explicit incumbent fallbacks in the common calendar.

`risk_sizing(base_weights, returns, risk_records, decision_at,
return_dates=..., covariance_only=False, reduce_gross=False)` returns weights,
an exposure-matched incumbent control, a gross multiplier, risk diagnostics and
an explicit status/reason. Base weights must already satisfy long-only 25% caps
and total gross at most one. Only incumbent positive names may receive risk
weights. Dated returns must match columns and be ordered; the helper truncates
future sessions before reading the trailing 252 observations. Today's daily
return is excluded before 16:00 ET. At or after 16:00 the final return session
must equal the decision session; otherwise covariance is unavailable. This is a
declared regular-close convention, not proof of vendor publication timing.

Ledoit-Wolf estimates covariance from 252 completed **log** adjusted-price
returns. The log basis matches TTM's existing `mean_squared_log_return` target.
Finite flat or numerically negligible returns can trigger skfolio's specific
`NonPositiveVarianceError` (the pinned estimator rejects diagonal variance
below `1e-15`). That boundary retains incumbent intent with explicit
`degenerate_covariance`; no noise or variance floor is invented. Other
estimator failures still refuse the evaluation.
TTM supplies each active name's ten-session mean squared log return. The helper
requires a dated `prediction_at`, `known_at`, active future `horizon_end`, the
exact target, forecast status and finite nonnegative `predicted_risk`.
Publication must occur by the decision and no earlier than the prediction.
An unavailable, late or expired required forecast preserves incumbent weights
with its reason. These guards enforce supplied timestamps; they do not attest
the original source or model training cutoff.

The TTM risk covariance retains estimated correlations and substitutes its
forecast marginal variances. The trailing-20 comparison uses the same estimated
correlations with each name's trailing-20 squared-log-return mean. Consequently
`forecast_variance` and `trailing20_variance` describe the incumbent basket under
different marginal risk assumptions; they are not prediction error or realized
portfolio variance.

The fixed allocation objective is
`w' C_normalized w + ||w - incumbent * multiplier||²`, where covariance is
normalized by its trace. The anchoring coefficient is one, with no parameter
grid. Constrain weights to `[0, 0.25]` and their sum to declared gross. Require
CLARABEL `optimal` and independently check finite weights, gross and caps.
This objective is an incumbent-anchored research hypothesis; no unconditional
replacement by the previous minimum-variance policy is implied.

Decomposition requires three funded lines on the same opportunities:

- `covariance_only=True`: use Ledoit-Wolf covariance without TTM, preserve
  incumbent gross. Combining this mode with a gross reduction is refused.
- TTM risk sleeve with `reduce_gross=True`: multiply gross by
  `min(1, sqrt(trailing20_variance / forecast_variance))`; a zero forecast
  variance leaves multiplier one. This is an explicit risk budget and never
  adds leverage. Then fit the anchored composition at that gross.
- Exposure-matched incumbent: multiply original incumbent weights by the exact
  risk-sleeve multiplier. Comparing the risk sleeve with this line isolates
  composition from its cash exposure. Cash is the funded ledger's residual.

All three still need actual funded net returns, exposure, turnover, fees and
drawdown at the common 10/25 bp conventions; a risk forecast diagnostic cannot
qualify a trading advantage.

## Regimes and walk-forward fitting

`causal_regime(dates, spy_close, t)` uses only completed observations through
row `t`. Trend is the sign of the trailing 60-session SPY return. Volatility is
the trailing 20-session mean squared log return compared with the median of
252 prior 20-session estimates, whose last observation ends **before** `t`.
This needs 273 prices. Keys are `up_high`, `up_low`, `down_high`, `down_low`.
Missing history is unavailable; a flat trend or volatility boundary is
ambiguous. Numerical equality tolerances are fixed at `1e-12` for trend and
`1e-15` for squared return. No future smoothing, hidden-state decoding or
retrospective winner label is used.

`MonthlySelector(experts, min_samples=20).select(decision_at, regime,
outcome_rows)` returns specialist weights and incumbent residual, frozen month,
fit cutoff, admitted/purged counts and a training hash. A regime dictionary is
accepted only if its information date does not exceed the decision date.
Unavailable or ambiguous regimes use incumbent fallback.

Each training row is one portfolio prediction opportunity, with timezone-aware
`prediction_at`, `known_at`, `label_end`, `label_available_at`, causal `regime`
and complete `utilities` keyed by the declared experts. Utilities must be
**incremental versus the same incumbent**, after the evaluator's declared
funding and cost conventions. Duplicate opportunities and impossible
publication chronology are refusals; every label must end **strictly after**
its prediction. Zero-session and backward label horizons cannot train the
selector. Missing expert utilities remain counted
as purged unavailable observations; zero utility is not invented.

Every monthly fit uses the last instant before the test month's first day as
its cutoff. Prediction and publication must be at or before that cutoff, and
label end must be strictly before the test month. This purges any outcome that
overlaps the test month, even when supplied early. At least 20 complete matured
observations from at least **three distinct prediction calendar months in that
regime** are required. This floor limits the original short September slice;
it does not turn overlapping training labels into independent observations.

Fit nonnegative convex weights with sum at most one by maximizing mean
incremental utility minus half its uncentered second moment and a fixed
`1e-4` ridge penalty. Require `optimal` and independently check constraints.
Negative specialists may receive zero; no model is forced into the portfolio.
The remaining weight belongs to the incumbent. A fit is cached by month/regime
and returned as a copy: later outcomes, altered inputs and caller mutations
cannot refit that month. A new month computes a new admissible training set.

The original short forecast history cannot qualify this selector. Where cached
long-history forecasts are absent, retain unavailable observations and report
incumbent fallback. New historical forecasts must not be silently invented.
Fitted monthly parameters remain retrospective conditional evidence until a
separate untouched funded forward comparison exercises them.

## Engineering proof and remaining claims

Temporal checks do not authenticate utility cost, source or forecast horizon.
The fixed September study must reject arbitrary nonempty external utility
history rather than qualify it as training. A future history adapter needs
separate bindings to predictions, labels, incumbent, costs and source evidence.

**VERIFIED:** 32 helper acceptance cases passed on the isolated existing CPU
runtime, 0.76 seconds, no skips. They exercise real skfolio, CVXPY and CLARABEL,
the anchored risk objective, caps/gross, no-leverage risk reduction, matched
exposure, future-return prefix invariance, intraday cutoff, causal regimes,
late/overlapping label purge, three-month minimum history, month freezing and
refitting, harmful-specialist zero weighting, and malformed/missing evidence.
The real flat/near-zero covariance failure was reproduced before correction;
four cases now check actual estimator fallback in both covariance-only and TTM
modes, and a fifth proves unrelated estimator errors are not swallowed.
The real zero-session admission was reproduced before correction. Two new
cases refuse zero/backward horizons, and a third retains valid positive
matured labels without changing the supplied evidence.
Ruff using the repository's `pyproject.toml` passes both owned Python files.

Source hashes exercised and independently matched on Mac and isolated Spark:

- `specialist_risk.py`:
  `0bdb40edb3a4c282c863b2c7b33c3aaa4fb632544f75a00e441a5985f6b1a65f`
- `test_specialist_risk.py`:
  `0a889d6ac009bf6ab46b4814aee84cf5f01fde5f0970d2145c0af258fd4420fc`
- Unchanged `open_source_portfolio.py` dependency:
  `4e2c7e8ded7b31e41a16a9909f476d0606ebdab06598a7678d931bc0a2c58219`

Final isolated source stage:
`/home/animallya96/scratch/specialist-study-source-20261001/`, base source
`1b145c9079487fe6c91f3300fa1ed48e6f856edc` with the two hash-bound new files.
Acceptance command: `python -m pytest backend/tests/test_specialist_risk.py -q`.
Runtime: NumPy 2.5.2, CVXPY 1.9.3, skfolio 1.4.10; CPU only with
OPENBLAS/OMP threads limited to one. No model service was changed.

**UNVERIFIED here:** combined funded acceptance, an economically useful risk
contribution, original historical availability, untouched OOS performance,
profitable regime switching and live promotion. No model inference, market
backtest or production deployment was performed by these helper tests.
Diagram impact: NONE; these are optional pure research helpers, not a new
production agent or tool.
