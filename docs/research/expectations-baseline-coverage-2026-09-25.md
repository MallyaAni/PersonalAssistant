# Earnings-expectations reporting coverage and paired comparisons

## Scope

This is a reporting-only correction to `market_expectations`, following the
[baseline-unit correction](expectations-baseline-scale-2026-09-25.md). It does
not change shared features, targets, fitting, live expectations, grades,
allocations, optional before-report studies or saved historical results.

The legacy EDGAR feature producer replaces missing/nonfinite revenue growth
with zero. Genuine zero growth, missing prior-year revenue, a zero denominator,
no current revenue, zero current revenue and two negative revenues can therefore
all reach the learner as the same zero feature. Its current-revenue presence
flag cannot recover that distinction and is not an expectations model input.
This does not establish that the target was zero-filled or quantify model harm.

## Implemented contract

`expectations_reporting.growth_evidence` supplies a separate aligned witness,
schema `legacy-growth-computability/1`. It reads the same legacy
`edgar._known_quarters(..., strict_before_session=True)` selector at each
dataset row's explicit ticker and feature-session indices. It never substitutes
the reaction date minus one. Reordered/repeated rows retain their own identity.

Read-only arrays retain the latest/prior revenue operands and usability;
tuples retain ticker, feature date, record source time, latest selected filing
date and a reason. Usability requires positive finite operands and a finite
legacy `log(current/prior)` calculation. Missing, nonfinite, nonpositive and
failed-arithmetic reasons remain distinct. Record source time and filing dates
are legacy declarations, not authentication of historical availability.

The reporting baseline still inverts the existing float32/clipped log feature
and applies the target's `[-0.9, 5.0]` clipping. Only this new baseline array is
masked when the witness is unusable. No operand-derived replacement feature is
introduced. The report names this **positive-revenue legacy-source log-feature
computability**, not qualified source provenance, fiscal periods or units.

Accuracy now compares learner and naive forecasts on the intersection of finite
learner, baseline and target rows. It prints cohort/exclusion counts, explains
overlapping exclusion reasons, retains paired yearly correlations and reports
the wider learner coverage separately as `learner (all scorable pairs)`.
Empty, singleton and constant-sample correlations are unavailable rather than
invented zeros. Anchoring before scaling preserves small finite variation;
scaled fallback arithmetic retains representable mean errors even when one
individual subtraction overflows. Genuinely unrepresentable metrics remain
unavailable.

Post-report surprise fifths use the same eligible events for both models and
retain the existing causal bucket construction. Only after bucketing does each
contrast intersect the dates with a finite session mean in all four groups:
learner selected/comparison and naive selected/comparison. The existing spread
and HAC estimator then use that same date support. Future outcome availability
does not filter the quantile calibration pools. Counts describe finite selected
observations, not independent trades; fewer than ten common dates withholds
statistics and retains the legacy zero-count convention. Outcomes are explicitly
labelled beta-adjusted log-return residuals, not net trade returns.

## Acceptance and original failures

Starting main: `cf5a248560e9d937bcdc35ee1bc79b71ecc081ae`. Initial pull was
current; a pre-publication fetch again found no incoming commits. Tests exercise
the mounted checkout, not source baked into a stale image. The cached Python
image is `63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`,
with network disabled, read-only source/root, temporary filesystems and synthetic
credentials. No production service or provider is exercised.

**VERIFIED:** the final relevant suite has **132 passes, one existing
missing-LightGBM skip, 32 existing empty-slice warnings, 6.24 seconds**. The
skipped fitting path is not a pass. Scoped Ruff/check-format pass; independent
source and numerical review has no remaining concrete findings. All 33
unchanged diagram/page checks pass.

The new tests exercise the real synthetic parsed-facts → EDGAR features → block
→ timestamp-bounded dataset → reporting path. Six source conditions distinguish
computability while retaining unchanged model arrays. Repeating those
rows only crosses main's 500-row guard; it is not additional independent data.
Main/accuracy/after dispatch run with supplied forecasts and no fit. Optional
studies retain their original arrays and call conditions.

Separate acceptance checks real trailing fifth construction and real spread/HAC
arithmetic. The paired-return fixture has twelve common dates, 23 learner versus
12 naive selected observations, and independently calculated means/statistics.
Missing outcome groups remove a date from both comparisons; a partly missing
group remains usable. All six after-report contrasts use paired support.

**FAILED before correction:** five original reporting assertions, eleven tests
requiring the missing witness, four corrected-harness main-path assertions and
five original paired-return assertions. One source control already passed,
showing unchanged legacy model inputs. The first CLI baseline exposed a test
sector-map mismatch, corrected before reproducing the four actual failures.
The first paired-return candidate exposed a test count error: legacy `_spread`
counted 35 including a date not used by its mean; paired contributing-date
count is correctly 33. The test, not production arithmetic, was corrected.
All original evidence remains retained.

Independent review also found two defects in the new metrics helper before
publication: small adjacent-float variation lost affine correlation, and an
overflowing individual difference hid a representable MAE. Permanent tests
reproduced three failures/seven passes before the fix and ten passes after it.
A separate 100-digit Decimal oracle passes 164 synthetic cases with no warnings;
maximum relative MAE error is `2.30e-16`, maximum absolute correlation error
`2.22e-16`. This is arithmetic proof, not forecast skill.

## Limits and next work

**UNVERIFIED:** source units, exact fiscal-period compatibility, original-response
provenance, historical universes/availability, corrected historical prevalence,
fitted model quality, funded performance and deployed behavior. The legacy
first-filed/fuzzy-quarter source selector and zero-filled live features remain
unchanged. This witness does not qualify those inputs, promote a strategy or
establish an edge over SPY/QQQ. No historical fit/replay was rerun.

There are no prompt, model-server, route, datastore, account, holding, order,
collector or permission changes. No frontend change in this checkpoint, so no
new browser acceptance is claimed. Full deployment gates have not run and this
is not deployed. Deployment remains Spark-only through `scripts/deploy.sh`;
the unanswered recurring-quote collector activation boundary still applies.

Evidence: `/private/tmp/anios-expectations-reporting.PVDMlm/RECEIPT.md`;
independent paired-return receipt:
`/private/tmp/anios-paired-returns.DVTimg/RECEIPT.md`.

**Diagram impact: NONE — internal research-reporting evidence and numerical
comparability, without a new component, store, dependency or ownership flow.**
