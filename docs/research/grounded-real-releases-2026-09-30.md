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

Before inference, read every available complete release and commit source-reviewed
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

## Observed v1 result — 2026-09-30 18:00 UTC

Protocol registered at `aba1278`, source-reviewed labels committed at
`5ee36d8`, comparison implementation `498bcf3`. One Codex source review,
not independent human adjudication. Twelve releases were retrieved with
24 paced SEC requests; ten fit the frozen bound and two were excluded.
No replacement, prompt tuning, label changes or retries. Twenty real calls
to the existing `deepseek-v4-flash` completed in 142.88 seconds wall time
(142.83 seconds summed call time; 2,730 completion tokens).

**FAIL: do not promote this extractor.** Only 4/10 eligible documents produced
fully valid exact-grounded output (4/12 of the original sample). Six were
rejected because the model decoded entities, removed intervening formatting,
or otherwise rewrote the purported exact quote. No invalid output became a
feature. End-to-end correct fields: **10/26**; guidance 3/9, demand 4/8,
financing risk 3/9. Four predeclared ambiguous fields remain excluded from
that denominator. An extraction failure counts as incorrect for every known
field on the failed document; it does not become a missing/neutral success.

The four accepted outputs were ORCL-2026, NVDA-2022, ADBE-2022 and ADBE-2026.
Oracle's accepted quotation was real but did not support its `raised` label:
“we now expect” supplied neither the prior same-period target nor an explicit
raise. Rejected raw outputs also incorrectly called NVDA-2026 and MU-2026
raised; MU-2026 missed the explicit growing-demand sentence. ADBE-2026's
explicit raise was correctly extracted. Exact quotation presence is therefore
necessary but not sufficient for semantic correctness.

The incumbent returned 10/10 parsed outputs; six inputs were clipped at
24,000 characters. It read AAOI-2026's guidance/demand as +1/+1, while also
correctly recording a GAAP net loss of $22.8 million. This is an optimistic
outlook score, not evidence of cheap valuation or a risk-free entry. On the
four unambiguous strengthening-demand examples its direction was positive
4/4. On four strict `not_stated` demand labels it gave neutral once and
positive/negative three times; its broader prompt and lack of a missingness
field prevent treating these as the same classification task. Its guidance
score cannot be scored as a guidance-revision classifier.

Raw public answers, source URLs, hashes, clipping, time and usage:
[real-comparison-v1.json](scorecards/grounded-release/real-comparison-v1.json).
Frozen annotations:
[real-labels-v1.json](scorecards/grounded-release/real-labels-v1.json).
Full immutable input texts remain on Spark at
`/home/animallya96/scratch/grounded-release.YRPKeN/real-release-corpus-v1.json`;
its file hash is recorded in the result manifest. No further SEC retrieval is
needed. Structural/integration acceptance: 164 related backend tests pass,
eight existing all-NaN fixture warnings; changed Python passes Ruff.

This is a small deliberately selected development diagnostic, not evidence of
market generalization, economic superiority, or a profitable replacement for
`/5`. Live policy, scores, model serving and broker state remain unchanged.

## Next bounded ablation — registered before normalized-input inference

Test input hygiene only: decode HTML entities once and canonicalize whitespace
before inference. Preserve raw and normalized hashes, text lengths, source
metadata and transformation version. Quotes/offsets must still match the exact
text sent to the model; do not normalize or repair a model's answer. The frozen
prompt, schema, 48,000-character/1,200-token limits and labels stay unchanged.

One grounded call for each of the same ten eligible v1 releases, at most ten
calls; do not rerun the incumbent or tune prompts. The two original oversize
rows remain unscored, though report their new input-bound eligibility. No new
labels will be inferred for them. This is an in-sample diagnostic ablation,
not a fresh test set. Record v1 before this run, retain every failure, and do
not promote even a perfect in-sample result without independent validation.
If this does not fix extraction quality, stop this variant rather than stacking
prompt exceptions or launching a large historical rescore.
