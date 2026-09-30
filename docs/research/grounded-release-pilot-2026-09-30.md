# Grounded release pilot — registered before model evaluation

Branch: `research/grounded-release-pilot-20260930`, base `0cf5760`.
This is an extraction feasibility test, not a strategy backtest or model swap.
The independently deployable dashboard fixes are on
`fix/desk-order-evidence-20260930` (`eb0d02d`, handoff `09c70c1`).

## Hypothesis and fixed scope

The existing DeepSeek runtime can extract explicit guidance revisions,
demand changes and financing-risk changes with exact supporting spans. That
may provide better-audited text inputs than the current uncited scalar tone
scores. It does not establish that the features predict returns.

One schema-bound call per document; at most 48,000 characters, 1,200 output
tokens, one concurrent request and no model/server changes. Reject oversize
documents rather than silently truncate them. No tools, prices, holdings or
broker access. Exact quotations must exist in the provided document; absent
evidence stays missing, not an invented neutral observation. Distinguish an
explicit revision against prior guidance for the same period from a forecast
that is merely larger than last quarter's results.

Preserve source/prompt hashes, publication and extraction instants, model alias
and exact spans. A historical release extracted today is usable only after
today's extraction; publication-date alignment alone is not point-in-time
model evidence. No checkpoint hash or training-cutoff guarantee is available
from the serving alias. Anonymization would not establish either one.

## Acceptance and stopping rules

Pin eight fixed cases before the run: raised guidance, lowered guidance,
unchanged guidance, no comparable prior forecast, historical results only,
financing-risk disclosure, a material statement after character 24,000, and
an instruction embedded in a release. Use hand-labelled properties, not an
LLM grading itself. Run all eight once. Accept extraction feasibility only if
all case labels match and every nonmissing feature has a valid source span.
Record actual latency, token usage, hashes and returned evidence. Invalid
schema, missing quotes, output truncation and runtime errors fail closed.
Do not relax cases after seeing results; record misses before any new version.

Separately test model-aware cache compatibility across prior frames, current
partitions and resumable partial output. Never rewrite historical partitions.
Alias identity does not protect against changing weights behind the same alias.

## What follows, only if extraction succeeds

A public-release annotation set with sector and period diversity, compared
against the existing reader; then a separately preregistered economic study
against current `/5`, SPY and QQQ with costs and turnover. No shuffled K-fold:
train/validate chronologically with purging of overlapping labels, use inner
folds for tuning, and leave the final time block untouched. Report return,
drawdown, regime coverage and uncertainty; no live promotion from this pilot.
This does not duplicate a large anonymized re-score or download ChronoBERT.

Candidate-model context (primary cards reviewed on 2026-09-30):

- <https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash>
- <https://huggingface.co/Qwen/Qwen3.8-27B>
- <https://huggingface.co/manelalab/chrono-bert-v1-20171231>

These are comparison candidates, not measured winners here. The current
served alias is `deepseek-v4-flash`; see `docs/MODEL_EVALUATION.md` for local
measurement history and serving constraints.

## Observed result — 2026-09-30 16:39 UTC

Registered protocol `d68d41e`; implementation `d458e82`. **8/8 real-model
functional cases passed**, no skips and no retries, in 18.27 seconds of pytest
wall time. The eight calls used 785 completion tokens (11,604 total tokens);
median extraction latency 1.68 seconds, longest 5.88 seconds for the 28,217
character document. All expected feature values matched. All nonmissing
features had exact source spans, including the guidance cut at offset 28,105.
The forecast-versus-revision case correctly returned `not_comparable`; reported
results alone did not become guidance or demand claims. The embedded command
did not override the financial disclosure.

Raw answers, usage, hashes, timestamps and expected/observed labels:
[grounded-release-v1.json](scorecards/grounded-release/grounded-release-v1.json).
Artifact SHA256: `186180556bb71dd735c76eaf836d9af821785f6fb57361c5f6b2b42ba0649f02`.
The extractor hash in every answer matches the exact committed implementation.

**Decision: advance to a public-release annotation evaluation, not live trading.**
This small synthetic set measures a capability, not generalization to real
filings, resistance to every prompt injection, repeatability or investment
returns. It does not prove economic superiority over the old tone reader or
current `/5`. Exact-span presence is verified mechanically; relevance was
tested by these fixed hand-labelled cases, not established for arbitrary input.
No live ingestion, strategy feature, score, order, model or deployment changed.

Model-aware cache checks also pass across old frames, same-day immutable
partitions and interrupted partial work. They identify the recorded model alias,
not weights silently changed behind that alias. Legacy tone records still lack
extraction times; no historical data was rewritten to create fake provenance.
