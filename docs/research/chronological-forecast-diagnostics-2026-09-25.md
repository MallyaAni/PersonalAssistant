# Saved chronological forecast diagnostics — September 25, 2026

## Purpose and contract

The allocation gate is already rejected by the saved net-account comparison.
This change makes its forecast-quality audit repeatable for future candidates;
it does not fit a replacement, choose a threshold or improve strategy returns.

`backend.market.forecast_diagnostics.diagnose` consumes `RegressionInputs` and
retained outer-fold receipts/predictions. The caller declares an exact half-open
decision range and a daily evaluation cutoff. Every decision remains in the
report; gaps, overlaps, missing folds and incomplete terminal coverage fail.
The evaluation cannot precede any declared decision. Earlier as-of reports need
earlier declared coverage, not a report containing models fitted in their future.

For each actual fold, the observer:

- authenticates complete receipt, model-state, used-input and prediction hashes
  under their existing distinct canonical conventions;
- reconciles eligible training rows and consumed feature/label evidence to the
  supplied normalized inputs, using features available by their original
  decision and labels whose endpoint and publication strictly precede fitting;
- derives each target's baseline from its own eligible training-label mean,
  never from the fitted intercept or feature-transform mean;
- applies saved transforms/coefficients to decision-time features to check
  finite recorded predictions, without refitting or filling an explicit null;
- scores outcomes only when both endpoint and publication are no later than
  the evaluation date, masking future outcome values and their missingness.

Full-sample and actual-fold metrics retain total/scored/excluded counts,
overlapping exclusion reasons, squared error, RMSE, forecast-minus-realized bias,
Pearson correlation and `1 - model SSE / training-mean SSE`. Pooled metrics use
the individual observations, not the mean of fold metrics. Empty samples, zero
variance and zero baseline squared error have explicit null values/reasons.
Invalid or nonfinite arithmetic fails rather than producing a misleading score.

Relative labels are stock minus SPY, stock minus QQQ and SPY minus QQQ. Both
targets must be scoreable and their actual endpoints must match. The baseline
is the difference of each target's own eligible training mean, not a new fit on
the intersection of their cohorts. Common label start, units and economic basis
remain caller-attested: `RegressionInputs` does not encode them.

The current study supplies overlapping five-session gross log-return proxies,
adjusted open `t+1` to open `t+6`, not funded net account P&L. Correlation or
squared-error skill is not calibrated downside probability, timing significance,
or proof of superior trading returns. Hashes are not signed provenance and saved
state application does not verify the optimizer. Historical input availability,
independent validation and adoption eligibility remain explicitly false.

## Integration and verification scope

`nested_market_study.run` adds `summary.forecast_diagnostics` beside the existing
funded-account scorecards. The report follows the same archive/digest path; no
protocol, price, strategy, execution, account, live route, prompt or UI changes.
An existing study can be inspected without refitting it. Keep derived output
outside the original archive and authenticate the original inputs before/after.

The initial integration test failed on the unchanged implementation with
`KeyError: forecast_diagnostics`. Independent review then reproduced constant
non-binary values receiving spurious correlation/baseline skill from floating
rounding, and a Boolean/numeric equality bypass of a per-target input payload
check. Regression cases retain those boundaries.

**VERIFIED final acceptance:** 1,215 tests passed, one intentionally deselected
completed historical reproduction, five existing empty-slice warnings, 40.42s.
This includes 36 direct diagnostic cases and the actual synthetic study,
archive/readback and standalone journal-verifier paths. Scoped Ruff lint/format
and all 33 unchanged canonical diagram/page checks pass. Independent review has
no remaining actionable findings. No UI or model prompt changed; production
browser/model, routing and deployment gates were not run for this slice.

The final observer also checked the original 14 saved outer fits and all 1,684
declared decisions, with 1,679 scored labels per target and five explicit terminal
exclusions. All eight pinned input files and exercised source hashes stayed
unchanged. Across 48 metric sets, 336 scalar comparisons to the earlier
independently checked audit agree within `4.44e-16`; this is not a new independent
strategy trial. The original producer remains **FAILED by OOM**, with no root
manifest. No replacement manifest, model fit or historical strategy replay was
created. Final derived report SHA-256:
`dfed26921149be1f550e82968150d40c0ddcdcdad166e6f3fd8643ff958453d7`.

Final evidence: `/private/tmp/anios-forecast-diagnostics-final.hPcK1YmS/`.
Initial integration and first full/frozen acceptance remain under
`/private/tmp/anios-forecast-diagnostics.d3OWOXdX/`; targeted failing regressions
and final independent review suite under
`/private/tmp/anios-forecast-diagnostic-tests.18roee/`.
The initial full suite passed 1,213 tests before the two near-constant cases were
added. A later container bind-mount setup failed before Python started; a checked
copy of the saved-fit extraction corrected the harness without changing the
original archive. All failures remain recorded, not counted as final successes.

## Relation to the research

The [saved gate audit](allocation-decision-attribution-2026-09-25.md#what-the-frozen-gate-evidence-says)
already found squared-error skill of approximately −6.46% stock, −14.89% SPY
and −15.35% QQQ against training-only means, on 1,679 observed overlapping
labels. This observer must reproduce that evidence, not tune against it.
The five terminal unavailable labels remain in the decision report as exclusions;
they must not remove actual account-return intervals.

The previously reviewed [Fonseca paper](https://arxiv.org/html/2607.04958v1)
motivates explicit information timing and temporal non-interference checks.
The [Pollok–Robik paper](https://arxiv.org/html/2607.00475v1) distinguishes
positive investment returns from demonstrated timing ability. Neither paper
qualifies this gate. The implementation adds measurement, not a new model or
an independent result on previously untouched history.

The more fundamental [historical-universe qualification](historical-universe-coverage-2026-09-25.md#bounded-public-reconstruction-audit)
remains incomplete. A public reconstruction seed supplies candidate ticker lists,
not the missing announcement clocks, security identities or terminal outcomes.

Diagram impact: NONE — internal reporting within the existing research flow.
