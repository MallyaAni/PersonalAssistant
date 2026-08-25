# ADR 0014 - supporting detail: should the embedding models be replaced?

Researched 2026-08-23 after the operator asked whether nomic is outdated.
**Accepted as a decision on 2026-08-25**, after a second research pass
(current MTEB/MMEB leaders, licences, vLLM support) reached the same
recommendation: keep the pair now, and name the coordinated migration target
for the next hardware step - Qwen3-VL-Embedding with Qwen3-VL-Reranker, one
family with one unified text/image/video space and Matryoshka output that
keeps the 768-wide columns. The signature-per-vector scheme and the
one-command backfill that make such a swap safe were built on 2026-08-24;
the reranker half of that family's contract is already the deployed
`/v2/rerank` client. Evidence and the rejected candidates are in
`docs/NEXT_SESSION.md` ("Embedding research verdict"). The image embedder
was found disabled in production on 2026-08-23 and restored separately; that
was a deployment fix, not a model change.

---

## 1. THE RECOMMENDATION

**Keep nomic-embed-text-v1.5 and nomic-embed-vision-v1.5. Do not swap either half.** Restore the vision weights (already in flight), repair the three *live* embedding gaps found in the database today, build a labelled retrieval eval, and revisit the question in a quarter with an instrument that can actually answer it. There is no 2026 model that is better *for this system* by a margin this system can measure, and the one model that is genuinely better on paper — Qwen3-VL-Embedding-2B — would require replacing both halves, rewriting the query/document prefix contract, moving image encoding onto a GPU with ~12 GB free, serving an architecture absent from vLLM's mainline embedding registry on aarch64, and re-calibrating a dozen hand-measured thresholds — all to chase a gain that is unpublished at 768 dimensions and unmeasurable on a corpus of this size.

## 2. WHY, GROUNDED IN THE NUMBERS

I queried anios_db directly (read-only). **The entire text corpus is 514 vectors across ten tables**: conversations 177, memory_entities 88, procedure_memories 88, discovery_seen_items 92, semantic_cache_entries 44, semantic_memory 8, discovery_familiar_items 8, conversation_summaries 7, knowledge_chunks 1, tool_descriptors 1. The image corpus is 18 eligible rows (`status='ready'`, generated/uploaded), 17 embedded at `nomic-embed-vision-v1.5`/768.

That number decides the question. MTEB/MMTEB/MIEB deltas are measured over BEIR-class corpora of 10⁵–10⁷ documents; at n≈500 a nearest-neighbour search is dominated by threshold calibration, not by encoder rank quality. The claimed gains are also not real numbers: nomic's 62.28 is MTEB v1 English, Qwen3-VL-Embedding-2B's 63.87 is MMTEB — different task sets, explicitly non-comparable. gte-modernbert's +4.2 (66.3 vs 62.1, Granite R2 paper Table 8) is measured against `modernbert-embed-base`, not against the incumbent. BeyondCLIP (Apr 2026) puts the noise floor at ~2 points and reports held-out evaluation dropping 3–5 points below public boards. **The honest answer is: the gain is unmeasured on this data, and the best available estimate of it is inside the noise.**

Against that, here are the failures that *are* measured, today, in production:
- `discovery_familiar_items`: **8 of 8 rows have a NULL embedding** (4 written 2026-08-08, 4 on 2026-08-12). Similarity-based dismissal suppression has never worked — `mark_known` swallows the embed exception and records identity only.
- `discovery_seen_items`: 5 of 92 NULL, all from 2026-08-14. Near-duplicate suppression is blind on those rows.
- `visual_artifacts`: 1 eligible row NULL (uploaded today) plus every future image, until the weights land.

Those are 100% failures in specific paths. The proposed upgrade offers a few unmeasurable percent. Fix the 100%s first.

## 3. THE ALIGNMENT PROBLEM

`interfaces.py:346-352` states the contract and three things enforce it: one 768 column, one distance-threshold family, and a query embedded by the *text* model searched directly against the *image* column (`api/v1/artifacts.py:46-52`, `conversation_service.py:1301-1309`).

**Replace the text model alone and nothing raises.** Width stays 768, `nomic_vision.py:87` never trips, every retrieval site issues a bare `cosine_distance` with no model predicate. Image search keeps returning ten results, ranked by a query vector that now lives in a different latent space from the pictures — pure noise, presented as an answer. The only guard, `test_vision_embedding_alignment.py`, asserts `matching_score > unrelated_score` (ordering only, never the 0.96 band) and *skips itself* when the weights or the endpoint are missing — which is precisely how the image side went dark unnoticed during the migration.

**Replace the vision model alone** and you break alignment the same way, unless you replace both.

Of the candidates, exactly two keep an aligned pair:
- **nomic v1.5** (incumbent) — the only Apache-2.0 aligned pair with a 92M ONNX encoder already wired into this codebase. Nomic has shipped no successor in this line; `nomic-embed-text-v2-moe` drops context 8192→512 and has no vision sibling.
- **jina-embeddings-v5** (`-text-nano` + `-omni-nano`, text embeddings bit-identical between them) — the only genuine replication of the arrangement. But omni-nano's image tower scores MIEB **46.41** against 60.69 for a 2025-era SigLIP-so400m at similar size, it is CC BY-NC 4.0, and its vLLM path needs a nightly build carrying PR #39575 on aarch64. It is a downgrade on the half you are trying to fix.

Qwen3-VL-Embedding-2B collapses both halves into one Apache-2.0 space — the architecturally right answer, and the one to bake off *later*, not now.

## 4. THE MIGRATION (if it ever happens)

**Matryoshka truncation to 768 does avoid the schema change.** The columns are dimension-typed only and record nothing about which model wrote them, so a model emitting 768 needs no Alembic revision and no index rebuild. It is not free: `lm_studio.py:48` sends only `{model, input}` — no `dimensions` field — and `:80-84` hard-rejects any width but the configured one, so either the server serves 768 natively or the provider gains truncate-and-renormalize code.

**What re-embeds: everything.** No 2026 model shares nomic's space. But at 514 text vectors and 18 images that is **minutes of compute, not hours** — the cost of a swap here is entirely calibration and code, never throughput.

**Safety against a database with no backups is trivially solved at this scale**: `pg_dump` of eleven tables holding ~530 vectors is a small file. Take it before any `--apply`, verify the restore into a scratch database, then proceed. Beyond that: `vector_dimension_migration_service` covers 7 of the 11 columns; the other four (`conversations`, `visual_artifacts`, `discovery_seen_items`, `discovery_familiar_items`) have **no re-embed path** — the two "backfill" CLIs filter on `embedding IS NULL` and would report "nothing to do" while every row was stale. The service cannot be extended to them as written: it issues `ALTER COLUMN embedding SET NOT NULL` unconditionally and all four are nullable. And its raw DDL writes no Alembic revision, so `verify-migrations.sh` would keep proving a schema production no longer has.

## 5. HOW IT WOULD BE JUDGED

**No adequate labelled set exists — for text or for images.** `evaluate_discovery_ranking` (the CLI AGENTS.md names as the retrieval gate) never calls the text embedder; it would score identically before and after. `evaluate_memory_retrieval` takes one hand-typed `--query` and `--expected-content`. `backend/tests/fixtures/memory_retrieval_cases.json` supplies distances directly, so it tests threshold policy and passes with any model. `evaluate_visual_grounding` scores the *decision to search*, not retrieval.

Build two things:

1. `backend/discovery/../embedding_retrieval_cases.json` + `python -m backend.cli.evaluate_embedding_retrieval` — ≥40 cases drawn from the real 501 populated rows: natural query → expected row id, with hard negatives.
2. `backend/vision/retrieval_cases.py` — for each of the 18 ready images, 2–3 queries the operator would actually type, the expected artifact id, and 5 negatives.

**Acceptance bar, stated now, before anything runs:** measure nomic's baseline first and record it. A replacement ships only if (a) recall@5 on text ≥ baseline **and zero cases that nomic answered correctly drop out**; (b) recall@3 on images ≥ baseline, same zero-regression rule; (c) every one of the ~12 thresholds is re-derived from a measured correct-pair vs unrelated-pair distance histogram — never carried over — and the separation margin is at least as wide as nomic's recorded tool-search band (0.295–0.437 correct vs 0.477+ unrelated); (d) p95 embed latency ≤ baseline + 20%. Anything less than all four is a "no".

## 6. WHAT TO DO FIRST, THIS WEEK

In order, and none of it is a model swap:

1. **Finish the vision weights restore**, then `python -m backend.cli.backfill_image_embeddings` (dry run, then `--apply`). One row. Confirm `image_embedding_reconciler` is running so this cannot silently lapse again.
2. **Make the alignment test fail instead of skip.** `test_vision_embedding_alignment.py:23-27` skipping on missing weights is the exact mechanism that hid this for a whole migration. Gate the skip behind an explicit env flag and add an assertion on the 0.96 band, not just ordering.
3. **Repair `discovery_familiar_items` — 8/8 vectors missing.** This needs new code (no re-embed path exists for it), and it is the same code any future swap would need. Biggest real recall win available. Do `discovery_seen_items`' 5 rows with it.
4. **Build the labelled sets and the eval CLI in §5, and record nomic's baseline numbers.** Until this exists, no swap can be judged, and per CLAUDE.md no swap can be called complete.
5. **Fix the compose split.** `EMBEDDING_MODEL` is hardcoded at `docker-compose.yml:234` and `:689` but substitutable at `:127` and `:432`, and `memory-maintenance` gets no `EMBEDDING_*` at all. A swap done via `.env` today would put two models' vectors into the same tables. Free to fix, and AGENTS.md records this trap costing real time twice.
6. **Then the 2048-token serving cap.** I verified it live against `172.16.8.3:8004`: `max_model_len: 2048`, and a 2049-token input returns a hard 400. It is *not* currently biting — `conversations.embedding` is the embedding of the user query only (max 6370 chars ≈ ~1600 tokens, avg 145) — but it is a loaded landmine for document ingestion, and the failure is swallowed to a NULL embedding in several paths. Raise `VLLM_EMBEDDING_MAX_MODEL_LEN` to 8192 and **measure the footprint on spark1** before committing; do not add `truncate_prompt_tokens`, which would silently discard content — the exact failure mode this codebase deletes features over.

Revisit the swap after step 4 exists. When you do, the single candidate worth bench time is **Qwen3-VL-Embedding-2B truncated to 768** (Apache 2.0, one model for both halves), and it must clear the bar in §5 on the real corpus — including a measured 2048-vs-768 truncation cost, which Qwen has never published.