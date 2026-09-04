# What the inference engine already does, so we stop rebuilding it

A survey taken 2026-08-29 against the running server, not from documentation.
Every version and flag below came from the live process; anything that could
not be verified says so.

The question it answers: which parts of this codebase hand-roll something the
engine provides, and which parts must stay hand-rolled whatever the engine
offers.

## What is actually running

One vLLM process, tensor-parallel across both Sparks — spark1 is rank 0 and
serves `:8000`, spark2 is rank 1 and headless.

```
$ curl -s http://localhost:8000/version
{"version":"0.25.2.dev0+g752a3a504.d20260714"}
```

- Image `ghcr.io/anemll/dspark-vllm-gx10:0.1.1`; vLLM `0.25.2.dev0+g752a3a504`, built 2026-07-14.
- Model `DeepSeek-V4-Flash-0731`, served as `deepseek-v4-flash`, `max_model_len` 1,048,576.
- Launch flags (`deploy/spark/ds4-tp2.sh`): `--enable-prefix-caching`,
  `--tool-call-parser deepseek_v4 --enable-auto-tool-choice`,
  `--reasoning-parser deepseek_v4`, `--kv-cache-dtype nvfp4_ds_mla`,
  `--block-size 256`, `--max-num-seqs 6`, `--generation-config vllm`.
- Embeddings are a separate pooling server (`nomic-embed-text-v1.5` on `:8004`);
  reranking left vLLM for an in-process ONNX cross-encoder on 2026-09-03, and
  the `:8006` server was retired with it. Vision is `qwen3-vl-8b` on
  spark2 `:8001`.

Live prefix-cache hit rate at the time of the survey: **89.2%**
(61.9M hits / 69.4M queries). The context ordering work in
`backend/agents/graph.py` is what earns that, and it is not a reimplementation
of anything — it is the correct way to cooperate with the cache.

Two facts that contradict comments in the codebase:

- `reasoning_effort: "none"` **is** accepted by this build; its enum is
  `none, minimal, low, medium, high, xhigh, max`. The comment at
  `backend/core/llm.py:207` says it is rejected with a 400, and
  `_retry_without_reasoning` is dead code against this server. Kept for now as
  portability to the Qwen fallback, but the comment misdescribes the engine.
- `--generation-config vllm` means the model's own sampling defaults are
  ignored in favour of vLLM's, which are also `temperature 1.0`. Either way,
  **a request that omits `temperature` samples at 1.0.**

## Already used

| Capability | Where |
| --- | --- |
| JSON-schema guided decoding, enforced server-side by token masking | `backend/core/llm.py:228` — ~20 call sites pass a schema |
| Native tool calling, grammar-constrained by the `deepseek_v4` parser | `backend/core/llm.py:100` |
| Automatic prefix caching | cooperated with by `backend/agents/graph.py:714` and `CONTEXT_CACHE_ORDERING` |
| Reasoning split into `reasoning_content` and not rendered | `backend/core/llm.py:135` |

## Available and unused

Verified present in the live request schema. None of these strings appear
anywhere in the repository.

- `structured_outputs` with `choice`, `regex`, `grammar`, `structural_tag`.
  `choice` would replace the family of sentinel strings we parse by hand —
  `ENOUGH` (`backend/services/search_planner.py:59`), `NOTHING_TO_REPORT`
  (`backend/tasks/quiet.py:11`), `NONE`, `RED_SQUARE`.
- `min_tokens` — aimed squarely at the empty-reply problem recorded at
  `backend/config/settings.py:120`, which is currently addressed by
  over-budgeting `max_tokens`.
- `thinking_token_budget` — bound reasoning per role instead of the
  all-or-nothing `reasoning_effort: none` used everywhere today.
- `cache_salt` — per-user prefix-cache isolation. Worth a thought for a
  multi-user assistant sharing one KV cache.
- `logprobs` / `prompt_logprobs` — there is currently **no signal at all** for
  "the router was unsure", and this would provide one.
- `truncate_prompt_tokens` + `truncation_side` — token-exact, server-side, to
  replace roughly twenty character-slice truncations.
- `repetition_detection` — ends a degenerate loop instead of burning the whole
  token budget.
- `stop`, `seed`, `min_p`, `top_p`, `top_k`, `logit_bias`, `bad_words`,
  `allowed_token_ids`, `n`, `chat_template_kwargs`, `stream_options`.
- Endpoints: `/tokenize`, `/detokenize`, `/v1/chat/completions/batch`,
  `/v1/responses`. Batch is interesting given `--max-num-seqs 6`.

## Not available on this build

- `best_of` — removed upstream.
- `guided_json` / `guided_regex` / `guided_choice` — legacy names, superseded by
  `structured_outputs`. Do not write new code against them.
- `priority` scheduling — the parameter exists but errors unless the server is
  started with a priority policy, which it is not.

## Ranked: what to replace, and what it buys

1. **Done 2026-08-29.** `parallel_tool_calls` defaults to true and
   `backend/services/main_action_selector.py` took `tool_calls[0]` and dropped
   the rest silently. Fixed: the request pins one call so the grammar enforces
   it, and a second is logged rather than swallowed.
2. **Two JSON repair loops on already-constrained output**, in
   `backend/artifacts/diagram.py:52,173` and a byte-identical copy in
   `backend/presentations/provider.py:75,521`. Both call sites already send a
   schema, so a fence or a preamble is unrepresentable. Worse, both retries
   append to `messages[0]["content"]` — **mutating the system prompt and
   destroying the prefix cache** the rest of the system works to preserve.
   ~100 lines and a self-inflicted cache miss.
3. **Five copies of one tolerant `_parse`** on schemas that already carry
   `required` and `additionalProperties: false`:
   `backend/core/result_ranking.py:129`, `backend/services/readiness.py:94`,
   `backend/services/followup.py:105`, `backend/core/event_extraction.py:347`,
   `backend/memory/share_screen.py:95`. The unreachable branches are the
   "not a dict" and "key missing" ones; the timeout and refusal fallbacks must
   stay. `backend/services/referent_resolution.py:177` already shows the
   one-liner. ~70 lines.
4. **`backend/services/search_planner.py` round-trips a decision through free
   prose with no schema at all** (`:202`), then scrapes it back out with four
   helpers (`:42`, `:68`, `:82`, `:87`). This is genuinely unconstrained output
   today. A two-field schema deletes ~50 lines of a 212-line file.
5. **The permutation check in `backend/core/result_ranking.py:151` can be
   structural.** `count` is known at call time, so a per-request schema with
   `minItems`/`maxItems`/`uniqueItems` and a bounded integer range makes a
   non-permutation undecodable rather than fail-soft.
6. **~125 lines of English restating schemas that are already sent** —
   `backend/agents/deck/prompts.py:47,94,110`, "Return only the required JSON"
   at `backend/memory/proposal_agent.py:162,196` and four other files. Pure
   token cost on every call.
7. **The structured-output health check does not test structured output.**
   `backend/services/inference_benchmark_service.py:177` reports
   `structured_output_valid` but sends no schema — it asks in prose. A
   grammar-enforcement regression would pass this probe.
8. **Token estimation against a server that reports exact counts.**
   `backend/core/context_budget.py:59` calibrates a chars-per-token constant;
   every response carries `usage.prompt_tokens`, and `/tokenize` is exact.

## Keep hand-rolled

- **The `offered` tool-name guard** (`backend/services/main_action_selector.py`).
  Grammar makes an unoffered name near-impossible; this is an authorization
  check and must not depend on the model behaving.
- **Fail-soft fallbacks** in the ranker, readiness and the reranker. They
  handle timeouts, 500s and a dead engine — failure modes no schema touches.
  They can shed their *parse-failure* branches, not their *call-failure* ones.
- **The link fence** (`backend/core/links.py`) and the event grounding checks.
  The engine cannot know which URLs are real. See
  [ADR 0017](adr/0017-a-reply-may-only-say-what-something-else-stated.md).
- **`CONTEXT_CACHE_ORDERING`** — cooperation with the cache, not duplication of
  it. Measured 33.1s → 2.0s prefill; keep the revert flag.
- **Length and quality policies** (`backend/discovery/digest.py:98`) — a
  judgement, not a structural constraint.

## One caveat on the tool-call parser

Upstream [vllm#41240](https://github.com/vllm-project/vllm/issues/41240)
reports the `deepseek_v4` parser mishandling `string=` attributes and argument
unwrapping under exactly our flag combination. **This build is not affected** —
the container's own `vllm/parser/deepseek_v4.py:54,93` carries the fix. Pin the
image: `0.1.1` has it, an older tag may not.

## What was not verified

The survey read the server's version, its OpenAPI schema, its process flags,
its metrics and its own parser source. It did not POST a generation, so
grammar enforcement is confirmed from the engine's code paths rather than
end to end. Item 7 above is the way to close that.
