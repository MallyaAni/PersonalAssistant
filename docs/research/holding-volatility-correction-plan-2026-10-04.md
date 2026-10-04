# Conditional stock-risk correction

Atomic objective: correct the verified high-volatility interval undercoverage
without fabricating an expected-return advantage. Original calibrationb04185c5
is complete:147476 paired mature cases, model80% coverage70.22% in high market
volatility versus83.09% low. Its mean-conditioned probabilities also have worse
Brier scores than the past-only reference. This experiment changes dispersion
only; it does not claim the mean head is useful or its confidence calibrated.

Freeze this transformation before new outputs. Reuse original saved risk1500cc4b,
parent, bridge, feature and price bytes; do not fit, regenerate predictions,
replay accounts or change the producer3files/joint protocol. For each original
singleton or required joint-stock request, keep exactly its original monthly
bank dates,252 minimum,756 lookback, strict maturity purge and August17 freeze.

For stock s at current decision t and original bank date j:
G[j,s]=(1+actual_return[j,s])/(1+forecast[j,s]);
H[j,s]=G[j,s]**(volatility[t,s]/volatility[j,s]);
corrected_gross[j,s]=(1+forecast[t,s])*H[j,s]*mean(G[:,s])/mean(H[:,s]).
Return=corrected_gross-1, with the original equal probabilities and shared dates.
This preserves each stock's original scenario arithmetic mean exactly up to
declared floating precision; widening the interval cannot invent expected gain
through a lognormal/Jensen effect. Volatility is original feature4, volatility_20,
in daily log-return units. Every value was available at its own decision, never
an endpoint or future close. No annualization factor, fitted multiplier or floor.

Implement logarithms/stable normalization to avoid intermediate powers overflowing.
If all per-row ratios for a stock equal one, preserve its original scenarios
exactly. Original true total-loss rows remain exactly-1; an all-total-loss bank
also remains total loss. Refuse unsupported finite arithmetic or underflow that
manufactures a new total loss. Never clip/impute tails or silently remove dates.
Require finite strictly positive current and every original bank volatility for
every requested stock; otherwise retain the whole request as unavailable with
the original dates and an explicit reason. This restriction is reported, not
hidden by a selected sample. It is not a live fallback to the1% threshold.

Bind the volatility context to the authenticated original features before
extracting it; detached immutable copies, original receipt hash, exact source/
protocol/volatility hashes, current/bank volatility and corrected scenario hashes.
Keep original forecast and outcome availability independent and admission before
examining current labels. No eligibility, grade, funding or account permission
is granted by this research reader.

Fixed comparison: same94 stocks/every session2018-02-01..2026-09-30 as the completed
diagnostic; same windows, costs0/10/25bp, proper scores, coverage, reliability and
causal groups. Read original model/reference scores from the authenticated saved
case evidence; do not rerun its completed baseline. New corrected scores and
original/reference comparisons use only common available/mature cases, while
all requested/missing/unavailable opportunities are retained. Report both old
full denominators and new common denominators. No favorable stock/regime/window
selection, significance claim, or compounded-profit interpretation.

Acceptance first: analytical unequal stock-volatility examples; preserved mean
and joint dates/probabilities; identity scaling; true total loss; zero/missing/
invalid contexts and numeric underflow refusal; immutable inputs; actual
authenticated saved-head reader; malformed requests; current/future-label and
future-volatility prefix invariance; original producer/artifact bytes unchanged.
Then one fixed diagnostic and independent saved-artifact verification of the
direct-power formula on supported data, proper scores and common aggregates.

Funded sizing/holding still requires reviewed whole-share/cash/corporate-action
accounting and cumulative gain against the rule/SPY/QQQ. Confidence calibration
from strictly earlier outcomes is a separate subsequent mechanism if still
needed. No strategy adoption or production deployment from this diagnostic.
