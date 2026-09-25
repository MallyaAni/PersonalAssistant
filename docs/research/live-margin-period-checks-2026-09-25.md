# Margin period-date checks in the current desk

## Objective and failure

Correct one current consumer defect: fundamental margins must not divide values
covering different retained fiscal intervals simply because their end dates
match. The prior public-path regression recorded income for December 22–March
31 divided by revenue for January 1–March 31 as a valid 0.1 margin. The source
frames already preserve starts; the loss occurs in the quarter-end projection.

This change is connected to `desk._fundamental_opinion`: stored versions →
`fundamental_features.features` → `fundamental.opine_corrected`. It does not
activate the separate unit-preserving or source-bound period research helpers.

## Acceptance contract

- Keep the existing as-of tag selection and legacy `_quarters` projection
  numerically unchanged, including its existing derivation and priority rules.
- Keep revenue growth, acceleration, availability and filing staleness unchanged.
- Retain full `(start, end)` intervals for the four margins. At the latest end
  known to both operands, require exactly one span on each side and equal
  starts. Otherwise withhold the ratio and its reference date. Do not hide an
  invalid latest shared end by falling back to an older valid ratio.
- Continue allowing a dated older shared end when only one operand has advanced.
  Missing/zero denominators remain unavailable; a real zero numerator is valid.
- Later filings cannot alter earlier feature values or decision-time exclusions.
- Exercise actual stored-frame readback and the current desk analyst: an invalid
  gross margin cannot contribute a scored leg; compatible controls still can.
- New opinions and records use `fundamentals-features/2`. Existing `/1` and
  `edgar-frozen` records are not rewritten. Browser labels distinguish those
  versions, absent sources and unrecognized sources; old simulations must not
  appear to have used the new checks.

## Limits

Matching retained dates is not complete financial compatibility. The unitless
stored versions cannot establish currency consistency. The existing annual
remainder can still derive Q4 from gapped first-three-quarter coverage. Those
independent defects remain strict expected failures; the original mismatch
test becomes an ordinary regression only when the connected fix passes.

No raw financial-source reimport, historical archive rewrite, policy parameter
change, fit, historical strategy rerun, model/provider call, account change or
order is included. Future desk calculations can change because invalid margin
legs are removed; old grades and backtests are not retroactively corrected.
This neither establishes AAOI's fair value nor qualifies any investment edge.

## Verification

**VERIFIED, synthetic current-source acceptance:** the 45 new backend cases
initially produced 23 failures (17 feature/ambiguity/scoring failures and six
missing extraction-API assertions). After the correction, the agent's broader
suite passed 209 cases, with one optional-Torch skip and four strict known-defect
xfails. Root independently passed 238 cases, with the same skip/four xfails and
24 existing warnings. The original period-mismatch xfail now passes normally.
Root's separate six-case exact-predecessor differential includes 2,048 legacy
quarter projections (all 512 input subsets × two insertion orders × two YTD
modes) and synthetic growth/tag/vintage comparisons against published `d0707b8`.
Original and final evidence is retained; no historical strategy was rerun.

**VERIFIED, local browser acceptance:** 12 new provenance cases failed the old
bundle. The candidate passes the agent's 151-case neighboring suite and root's
214-case combined suite (125.825 seconds), zero failures/skips/flakes. All 62
attached root diagnostic records are clean. Current/prior source combinations,
old execution policy, unknown/absent tags and reload are exercised; desktop and
phone summary screenshots were inspected. Existing chart and quote semantics
remain covered. This does not claim to fix pre-existing truncated summary values.
Two new-test corrections retained their failures: decorative benchmark arrows
in expected text and an exact locator needed after adding a summary source label.
No product safety assertion was relaxed.

TypeScript/build, scoped Ruff/format, independent source review and all 33
diagram/page checks pass. Root's first build and diagram checks failed on
read-only Vite config caching and root-browser launch configuration respectively;
the config-loader runner and existing isolated-browser wrapper resolved those
environment boundaries without source changes.

Root evidence: `/private/tmp/anios-margin-root.fahEwK/` (`accepted-backend.xml`,
`browser.json`, exact-predecessor harness and screenshots). Browser report SHA256:
`95b07b0ea89dbf9a3f90ecb4d3cc954ef0db35c18ee16472c5faaaf4d3c183f2`.
Agent evidence: `/private/tmp/anios-margin-intervals.MCOmyW/` and
`/private/tmp/anios-fundamental-ui.yBQMB1/`.
Compiled asset: `index-Du7iSXGx.js`, SHA256
`500c3d5731efe05ea4512fb3e1349a995c6d56a405d1d77927b1258242395233`.

The tests use synthetic APIs/filings and the real calculation/browser paths,
not a deployed feed or authenticated historical financial source. Deployment,
the skipped Torch path and investment performance remain **UNVERIFIED**. The
quote-collector approval and Spark-only gated release requirements are unchanged.

Diagram impact: NONE — an internal feature check and existing source labels;
no new component, store, trust boundary or cross-component flow.
