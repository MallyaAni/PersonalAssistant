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
