# Real-release extraction comparison — registered before inference

Parent pilot: eight synthetic cases passed on `grounded_release/1`. This study
checks real-document coverage and reading quality, not trading performance.

## Fixed sample and procedure

Six names: AAOI, ORCL, NVDA, MU, ADBE and INTC. For each, choose the latest
stored item-2.02 earnings event filed on or before 2022-12-31, and the latest
filed on or before 2026-09-30. This gives at most twelve releases across
semiconductors, optical hardware and software, including an earlier difficult
market period. Selection does not use returns, grades or model output. These
are not twelve independent tests of a strategy or a representative market sample.

Read existing local EDGAR event metadata only. Fetch each selected index and
EX-99 exhibit once from SEC (at most 24 requests, paced). Stop acquisition
after three consecutive failures; retain missing/oversize rows and do not
replace them with easier documents. Retain acceptance/filing/retrieval instants,
source URL and exact body hashes. No production store writes or credentials.

Before inference, read every available complete release and commit human-reviewed
labels with supporting excerpts and notes. Mark genuinely ambiguous fields as
ambiguous rather than tuning a label to either model's output. No unchanged
or missing label may be inferred simply because a word search found nothing.

Run each eligible full document once through the frozen grounded extractor
and once through the current `ReleaseToneReader` using the same served model,
sequentially. Grounded bound stays 48,000 characters / 1,200 output tokens;
the incumbent keeps its actual 24,000-character / 300-token behavior. Report
input clipping and eligibility rather than hide these differences. Maximum
24 inference calls. Record raw scores, exact quotations, hashes and latency.

## Comparison and acceptance

Grounded labels: explicit guidance revision, demand direction, financing risk.
Require exact source quotes for each nonmissing prediction. Report exact-match
accuracy on unambiguous labels, missingness, coverage and every failure.
For this small diagnostic gate require all explicit guidance raises/cuts to be
correct and no invented quotation; report any other miss rather than declaring
general readiness. No prompt change or rerun on this set before recording v1.

The old guidance score means broad forward-outlook direction, **not** guidance
revision. Do not score its positive forecast as an erroneous raise: instead
report the semantic difference. Its demand scalar has a comparable direction:
above +0.2 positive, below -0.2 negative, otherwise neutral. Its zero conflates
missing and stable evidence, so report those separately without claiming it
has a missingness field it lacks. Financing risk is not an incumbent field.

Only after this comparison: decide whether a concrete defect justifies a
new extractor version, or whether the evidence supports a broader annotation
study. Do not change live grades, trading decisions or portfolio sizing.
Any subsequent economic test must compare current `/5`, SPY and QQQ with
chronological validation, costs, drawdown and untouched test data. Modern-model
historical hindsight is not solved by dating the document correctly.
