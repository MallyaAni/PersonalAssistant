# Valuation increment over momentum and risk — one bounded run, 2026-09-14

**Status: closed, insufficient evidence to advance.** Results preserved as
run. No tuning, inverted predictions, other models or promoted variants.
Reopening needs a new, specific hypothesis and an agreed evaluation budget.

Research only. Production, the nightly and the frozen shadow ledger are
unchanged; no parameter was searched; the specification below was fixed
before the run and the run happened once (a second execution only fixed
tie handling in the rank statistic, which changed no number). Code:
`backend/cli/market_valuation_increment.py`, the strictly trailing
reference in `backend/market/attractiveness.py`, tests in
`backend/tests/test_valuation_increment.py` and
`backend/tests/test_attractiveness.py`. Data: the corrected as-of run
`opportunity-learning-asof-20260914` (versions sha 3353f5104f84).

## Question

Do price-sensitive valuation inputs predict future returns beyond
momentum and market exposure, well enough to change position sizing?

## Specification, as fixed

- **Two ridge models, alpha 10, fitted once on 2018–2023** (every fifth
  session, label endpoint purged: last training endpoint
  2023-12-27, first validation session
  2024-01-02). Baseline: the eight price
  and volume features (returns over 5, 20, 60, 120 sessions, 20-session
  volatility, distance to the 20 and 60-day averages, relative volume).
  Increment: the same eight plus the cross-sectional value rank, the
  relative valuation magnitude, and the strictly trailing history
  reference (median log price-to-sales over the previous 756 sessions,
  at least 250 known, **today's observation excluded**).
- **Label**: 20-session log return from the next close to the close 20
  sessions later, beta-adjusted by the trailing 120-session beta known at
  the decision. The label was verified against the price arithmetic of a
  next-close fill on a training row (test and in-run assertion), not
  assumed from the purge length.
- **Normalisation and imputation fitted on training rows only**, for both
  models. Both models score the same rows: eligible, finite label, finite
  price features, finite history reference. Requiring the history
  reference removes names without three years of as-of history from both
  models alike: 46,836 out-of-sample rows scored, from
  58,190 otherwise eligible
  (80%).
  Training rows 16,985.
- **Uncertainty** from the time series of per-session paired differences
  in Spearman rank correlation (increment minus baseline), Newey-West
  with lag 20 for the overlapping labels; effective sample size reported.
- **Gate** (an advancement gate, fixed beforehand): combined
  out-of-sample HAC t above 2 **and** a positive mean difference in at
  least two of the three periods, 2026 being partial and not a full
  independent year. Failing it means "insufficient evidence to advance
  this specification", not that valuation has no value.
- **Membership is not point in time**: the 93 names were chosen in 2026.
  Every number carries that selection bias, and 2024–2026-09-11 has been
  examined by earlier work here; nothing is untouched.

## Result: per-session rank correlation with the beta-adjusted label

| period | sessions | baseline IC (t) | +valuation IC (t) | difference | HAC t | effective n |
|---|---|---|---|---|---|---|
| 2024 | 252 | -0.0674 (-1.90) | -0.0655 (-2.65) | +0.0019 | +0.07 | 22 |
| 2025 | 250 | -0.0063 (-0.21) | -0.0336 (-0.98) | -0.0273 | -0.82 | 24 |
| 2026 (partial) | 153 | +0.0297 (+0.49) | +0.0773 (+2.03) | +0.0476 | +0.60 | 11 |
| combined 2024..2026-09-11 | 655 | -0.0214 (-0.89) | -0.0200 (-0.93) | +0.0014 | +0.05 | 49 |

The combined difference is +0.0014 with
t = +0.05 on an effective sample of about
49 independent sessions. The sign
is positive in 2 of three periods (2024 by a hair, 2026 partial), negative in 2025.

**Gate: insufficient evidence to advance this specification; not proof that valuation has no value.**

Neither model has predictive rank correlation on this period: the
baseline's combined IC is negative and insignificant, and so is the
increment's. In partial 2026 the increment model alone reaches
+0.077 (t 2.03 on about 21 effective sessions), which is the one place
valuation shows up; it did not in 2024 or 2025, and a partial year with
an effective n near eleven for the difference cannot carry a decision.

Coefficients of the increment model (standardised inputs): value rank
+0.99, magnitude -0.61, history reference
+0.61. Rank and magnitude are two monotone views of
the same cheapness, and the ridge splits them with opposite signs, so
their net is small; the history reference, the only input independent
of the other names' prices today, carries a clear positive weight. That
is a description of the fit, not evidence: it is one fit on one period.

## Funded books on the same rows (top ten by forecast, 10% cap, 20-session decisions, next-close fills)

| book 2024-01-03..2026-09-11 | net return | worst drawdown | volatility | turnover | top weight | cash |
|---|---|---|---|---|---|---|
| baseline@10bps | +254.4% | -43.5% | 49.8% | 49.6x | 10% | 2.9% |
| +valuation@10bps | +180.1% | -32.7% | 34.8% | 39.3x | 10% | 2.9% |
| SPY@10bps | +67.8% | -18.8% | 15.6% | 1.0x | 100% | 0.0% |
| equal@10bps | +288.8% | -33.4% | 32.7% | 4.7x | 1% | -0.0% |
| baseline@30bps | +220.9% | -43.8% | 49.8% | 49.5x | 10% | 2.9% |
| +valuation@30bps | +158.9% | -32.9% | 34.8% | 39.2x | 10% | 2.9% |
| SPY@30bps | +67.5% | -18.8% | 15.6% | 1.0x | 100% | 0.0% |
| equal@30bps | +285.2% | -33.5% | 32.7% | 4.7x | 1% | -0.0% |

The increment book returns less than the baseline book, with a shallower
drawdown, lower volatility and less turnover; both are beaten by equal
weight across the same names at a third of the drawdown of the baseline.
The books are not risk matched and are shown for the record, not as
the test; the test is the rank-correlation gate above. With the
survivorship of a universe picked in 2026 these levels say nothing about
what a live book would have earned.

## Reading

- This specification does not advance. The valuation inputs, as
  specified, do not add measurable rank-ordering power over momentum and
  risk on the sessions available, once the label is beta-adjusted and
  the uncertainty is measured on sessions rather than stock-days.
- What the run does establish about method: the strictly trailing
  reference, the training-only normalisation, the identical-row
  comparison and the session-level HAC statistic are in place and
  tested, so a later specification can be judged the same way.
- What would be informative next, if the operator wants it: the same
  gate on untouched sessions as they arrive, measured beside the frozen
  shadow ledger; or the history reference alone, since it was the one
  input with a consistent sign here. Neither is started.
