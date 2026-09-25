# Source-bound financial periods — September 25, 2026

## Failure and scope

Unit preservation alone does not make a financial ratio compatible. The legacy
quarter builder drops interval starts, and the feature adapter then joins only
period ends. The real path returns 0.1 for income covering December 22–March 31
divided by revenue covering January 1–March 31. The unitless parser also returns
0.1 for EUR income divided by USD revenue. Separately, annual less three
quarters manufactures Q4 even when the first three quarters leave a gap.

All three failures were reproduced before the change and remain strict legacy
xfails. The new `fundamental_period_sources` helper is isolated research code;
it does not modify legacy parsing, features, live grades, frozen model inputs,
accounts or historical studies. It has no network, store or model call.

## Explicit contract

`RatioDeclaration` fixes the numerator and denominator monetary-flow names and
XBRL tags, literal monetary-unit identifier, `quarter` or `year` horizon, and
the `latest_shared_complete_interval` selection policy. Tags/units are never
chosen by full-history counts. A three-uppercase-letter unit check verifies
format, not membership in an authenticated currency registry. The caller must
declare the unit; matching labels do not prove currency truth or comparable
accounting policies. EPS, share counts, prices and FX conversion are excluded.

`evaluate(source, declaration, decision_dates=(...))` re-extracts the original
source bytes before using the supplied immutable observations. The decision
calendar must be strictly ordered date values; this helper does not establish
an exchange calendar or intraday execution eligibility. Availability follows the
existing conservative daily convention, not a newly inferred publication clock.

Each operand preserves its full inclusive `(start, end, unit)` interval and all
signed original source terms with their availability. Reported quarters take
precedence on exactly equal intervals. YTD differences require a common start
and matching units; all eligible residual intervals remain visible rather than
selecting only an adjacent prefix. An annual remainder requires an exact,
unambiguous, contiguous Q1–Q3 partition. Derived values are computed directly
from the retained signed original terms, not nested rounded intermediates.
Year mode uses reported annual intervals only. Annual-only data cannot become
a quarterly ratio, and no annual fallback occurs.

The latest shared full interval is used only if neither operand has competing
spans at that end. Equal-vintage conflicts, ambiguous derivations, missing
components, zero denominator and nonfinite arithmetic have explicit reasons.
A valid zero numerator remains zero. An older shared ratio can remain useful,
but the used interval and each operand's latest available end are separately
exposed. Future facts cannot alter earlier economic values, intervals,
availability or decision-facing missingness explanations; the overall source hash necessarily
changes when the supplied snapshot changes.

## Verification

Final affected suite: **252 passed**, one existing missing-Torch skip, six strict
legacy xfails, 24 existing empty-slice warnings, 6.77 seconds. The six xfails are
the three period/unit/partition failures, two earlier unit-source failures, and
the frozen price/share-basis defect. None is counted as fixed in its old path.
Independent review found and tested YTD ambiguity, nested arithmetic/lineage
disagreement and future leakage in missingness reasons; all are corrected in
the isolated helper. Scoped Ruff/format and all 33 unchanged diagram/page checks
pass. No new prompt or live model behavior is claimed.

Actual-source verification used the already retained ASML company-facts bytes,
SHA256 `28be6fd0f5608350ec396ae5d5097e45da95f4f29ad3fbd19aac328a15cce3d4`.
A separately prepared standard-library/50-digit Decimal oracle fixes four
EUR/revenue ratios across eight decision dates before exercising the helper.
Of 32 annual cases, 28 have compatible source evidence and four are unavailable;
all 32 quarterly cases remain unavailable because these declared tags contain
annual data only. There are 140 scalar and 392 raw component-field comparisons;
maximum ratio residual is `5.154178436711248418174342780e-17`. Source, oracle
and exercised module hashes remained unchanged. No new source request or
strategy simulation occurred.

Evidence: `/private/tmp/anios-fundamental-periods.AtH5U2/RECEIPT.md`.
Production SHA256:
`e5fe1a13e56ba351c22a625bee0c69428c1c855d48cea9e208b7fd9527d0f087`.
Independent review: `/private/tmp/anios-period-review.TpaTDv/RECEIPT.md`.

## Remaining boundary

The [retained-source inventory](fundamental-unit-sources-2026-09-25.md#retained-source-coverage)
does not support a full raw-backed historical reimport. Compatible amounts and
periods do not establish historical source authenticity, correct financial
classification, complete issuer coverage, investment quality or trading alpha.
No existing consumer switches to this helper. Retention/reimport, compatible
feature assembly and any live rollout need their own declared scope and proof.

Diagram impact: NONE — an internal research calculation with no new live flow.
