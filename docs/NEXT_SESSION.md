# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-08-01, America/New_York

## Current boundary

AniOS now uses vLLM rather than LM Studio as its default local inference
runtime. Docker Compose owns two pinned services:

- `vllm-main` at host port `8003` serves pinned Qwen 3.5 4B as
  `qwen/qwen3.5-4b` for main chat, native tools, diagrams, presentations,
  architecture candidates, and vision;
- `vllm-embedding` at host port `8004` serves pinned Nomic Embed Text v1.5 as
  `text-embedding-nomic-embed-text-v1.5` for 768-dimensional embeddings.

The RTX 5080 requires ordered cold initialization: Qwen must reach health
before Nomic starts, and host ComfyUI starts afterward. Compose dependencies and
`scripts/start-anios.ps1` encode that order. Model and compile caches are
bind-mounted below `E:/AI/`.

Qwen is quantized to FP8 with an FP8 KV cache on the RTX 5080's native Blackwell
tensor cores, serving a 16,384-token context at 0.55 GPU-memory utilization;
Nomic runs at 0.06, sized to its measured 0.26 GiB of weights. Boundaries that
parse model output as data send a JSON Schema that the runtime decodes as a
grammar, and routing classifiers decode greedily.

## Runtime and Git identity

- Branch: `main`.
- Session-start and current `HEAD`:
  `dfaa3a2021fa53db66103556336e7e5788df4dc3`.
- Task source exercised: the current uncommitted working tree layered on that
  `HEAD`; no commit or push was authorized.
- Live stack: backend `:8000`, frontend `:5173`, local capability MCP `:8001`,
  renderer `:8002`, PostgreSQL `:5432`, Redis `:6379`, vLLM main `:8003`, vLLM
  embedding `:8004`, and host ComfyUI `:8188`.
- Hardware: NVIDIA GeForce RTX 5080 with 16,303 MiB and driver 610.47 under
  Docker Desktop's Linux/WSL2 NVIDIA runtime.

## VERIFIED

- The official vLLM 0.23.0 image and pinned Qwen/Nomic revisions start through
  Compose. Both services report healthy and coexist on the RTX 5080.
- FP8 halved resident weights from 8.61 GiB to 5.09 GiB and raised cached tokens
  from 45,428 to 64,046 while doubling the context to 16,384. Free GPU memory
  with both services resident rose from 1,860 MiB to 6,588 MiB, which is the
  headroom host ComfyUI previously did not have.
- The provider-neutral benchmark passed 5/5 on FP8 and improved every latency
  against the BF16 baseline: main TTFT 0.160 s, total 1.173 s at 39.222
  normalized estimated tokens/s, native tool 0.316 s, presentation structured
  output 0.136 s, three-vector Nomic embedding batch 0.025 s, and fixed-fixture
  vision 0.192 s.
- Schema-constrained decoding holds against an adversarial prompt: asked
  explicitly for `optional_` field prefixes and null notes, the live `DeckPlan`
  grammar produced neither and honoured an exact three-slide bound.
- A real queued three-slide job reached `ready` on attempt 1 with no correction
  retry and rendered through `pptxgenjs+libreoffice`; a real SSE chat returned
  the exact requested text with terminal `done`.
- A 16-case labelled freshness set scored 16/16 with zero unusable answers under
  FP8 and greedy decoding.
- Full-project MyPy passes across 152 source files; the backend suite passes 506
  tests; Ruff and Black pass. The 36 deterministic Playwright tests pass, and the
  live configured-provider suite passes 3 against the rebuilt images.
- Host ComfyUI generated a real 2048x2048 image through the owning API in 20.0 s
  (HTTP 201, `ready`), against a 36.47 s BF16-profile baseline, while both vLLM
  services stayed healthy. ComfyUI now claims the GPU headroom FP8 released.
- All 13 Mermaid/SVG pairs and the published architecture page are synchronized.
- The documented direct `POST /api/v1/chat` payload returned `200
  text/event-stream`, exact text `vLLM AniOS validation ok`, seven deltas, and
  terminal `done`. Backend logs showed successful Qwen chat-completion and Nomic
  embedding requests with no exception.
- Warm foreground chat completed in 3.13 s while a presentation job was active.
  A following post-image chat completed in 9.20 s with both vLLM services still
  healthy.
- A real Chromium test against the final rebuilt application images submitted a
  unique message through the UI, received the required SSE response, rendered a
  non-empty answer, cleared thinking/loading, re-enabled and emptied the
  composer, navigated through Memory and restored the exact conversation, and
  recorded no blocking Console or page errors. Backend logs recorded successful
  Qwen/Nomic requests and a completed graph trace.
- The owning vision API accepted a 5,467,794-byte PNG, returned HTTP 201 in
  7.31 s, persisted its analysis, and recorded
  `analysis_model=qwen/qwen3.5-4b`.
- Host ComfyUI generated and persisted a real 2048x2048 HiDream PNG in 36.47 s
  while Qwen and Nomic remained resident and healthy.
- Presentation migration reproduced two narrow Qwen output variants:
  invented `optional_` field prefixes and `notes: null`. Exact-name prompting
  plus null-note normalization fixed the typed boundary. Three consecutive real
  queued one-slide jobs then reached `ready` with exact slide counts; an earlier
  real two-slide deck also rendered with `pptxgenjs+libreoffice`.
- `scripts/start-anios.ps1` parsed and ran successfully, waited for both vLLM
  services, detected ComfyUI, started the application services, and reported the
  frontend/API endpoints.
- Complete backend suite: 504 passed. Deterministic Playwright: 36 passed. Live
  configured-provider Playwright: 1 passed. Ruff and full-project Black:
  passed. TypeScript/Vite production build: passed with only the existing
  chunk-size advisory. All 13 Mermaid/SVG pairs and the published architecture
  page are synchronized and the changed views passed visual inspection.
- Isolated validation artifacts, presentations, conversations, and memory were
  deleted through owned APIs after acceptance.

## FAILED

- Concurrent cold startup of Qwen and Nomic initially failed Qwen initialization
  with `No available memory for the cache blocks`; ordered Compose startup fixed
  the original acceptance path.
- The first presentation reliability set produced two ready jobs and one
  `generation_failed` job because Qwen emitted `notes: null`; normalization and
  the repeated three-job acceptance passed.
- Full-project MyPy previously reported two errors in
  `backend/capabilities/visual_mcp.py` where calls to
  `get_image_artifact_service` omitted the required `edit_provider` argument.
  Both call sites now pass `get_image_edit_provider()` and the gate is clean.
- The working `.env` still pointed at LM Studio (`127.0.0.1:1234`) with
  `google/gemma-4-12b` and `qwen/qwen3.5-9b`. Compose overrides these per
  service, so the containerized app was unaffected, but every host-run tool read
  them: the benchmark failed 5/5 with `HTTPStatusError` against a model the
  runtime does not serve. The inference entries were migrated and the previous
  file kept as `.env.backup-pre-vllm`.
- At the runtime's default sampling, the freshness classifier answered the same
  question `YES` three times and `NO` three times across six identical calls,
  making a search decision depend on sampling. Greedy decoding fixed it.
- `test_vision_embedding_alignment` was silently skipping: it requested
  embeddings from `LLM_BASE_URL`, which under split vLLM services is the
  generation endpoint and returns 404. It now resolves the embedding service the
  way dependency assembly does, and the cross-modal ordering assertions run.
- The first full-suite invocation used system Python 3.14 and failed collection
  because Google ADK and OpenTelemetry were absent. Repeating with the documented
  workspace `.venv` passed all 504 tests; the initial result is an invocation
  failure, not an application regression.
- A real two-slide presentation job reached `ready`, but a prompt-requested
  native comparison table was not present; its element types were text and
  shape only. This is an existing planning/compiler capability gap, not a vLLM
  startup or transport failure.
- After the final application rebuild, three PowerShell direct-request command
  variants failed to capture a complete SSE body: two `curl.exe` invocations
  lost JSON quoting and received parse-level 422 responses, while
  `Invoke-WebRequest` opened HTTP 200 and called Qwen/Nomic but disconnected
  with its SSE null-reference bug before persistence. Per the three-hypothesis
  rule no fourth command variant was attempted. The documented direct API path
  had already passed earlier against the same chat/settings/runtime
  implementation; later production changes were confined to the presentation
  planner/provider boundary and comments.

## UNVERIFIED

- Sustained concurrent load, p50/p95 distributions, context beyond the qualified
  16,384-token profile, crash recovery of vLLM, and DGX Spark behavior remain
  unmeasured.
- FP8 output quality is measured, not proven equivalent to BF16. vLLM warns that
  the checkpoint supplies no calibrated `k_scale`/`q_scale` factors and falls
  back to 1.0. The benchmark, a 16-case classifier set, and a real deck all
  passed, but no head-to-head BF16 comparison and no long-context degradation
  test were run. `VLLM_MAIN_QUANTIZATION=auto` reverts the change.
- The model cache still loads over a 9P Windows bind mount, costing about 64 s of
  a roughly four-minute cold start (engine init added 143 s, 59 s of it
  compilation). Moving the cache to a WSL-native Docker volume should cut the
  load portion but requires copying or re-downloading the 8.68 GiB checkpoint and
  changes where the models live; it was left as a deliberate decision, not done.
- FlashInfer as the attention backend and ngram speculative decoding for the
  repetitive JSON in presentations remain unevaluated. The runtime currently
  selects FlashAttention 2.
- Native chart/table realization from a Qwen-generated presentation request is
  not verified; the runtime migration proves typed progressive jobs and editable
  PPTX rendering, not every requested native object kind.
- Dynamic model discovery/switching, vLLM sleep/wake, capacity-aware GPU leases,
  multi-GPU or multi-host placement, and TensorRT-LLM remain unimplemented.
- The historical LM-Studio-named compatibility modules and aliases remain source
  naming debt; active runtime assembly no longer calls LM Studio.
- Security hardening remains deferred per roadmap.

## GPU contention (resolved by measurement, not by the handoff)

HiDream needs about 10 GiB and vLLM claims about 11 GiB of a 16.3 GiB card, so
the two cannot both be fully resident. Image latency tracks ComfyUI's free VRAM
rather than any sampler setting: at a fixed 2048x2048 the same prompt took 17.7 s
at 28 steps but 312 s at 6 steps and 840 s at 16 steps. Resolution is not a
lever either, because 2048x2048 is the smallest size HiDream supports.

`InferenceGpuHandoff` sleeps vLLM around one image job and is verified working
end to end on the shipped runtime: two sleep/wake cycles, correct inference after
each wake, and about 10 GiB released while asleep. It ships disabled anyway,
because it measured **slower**: 47/64/42 s with the handoff against 37/35 s
without it. ComfyUI already manages its own residency, so a full offload and
reload per image costs more than the contention it removes. Revisit only if a
larger image model makes sharing genuinely impossible, and re-measure first.

Two constraints discovered along the way, both encoded in Compose:

- An **FP8 KV cache cannot be woken** on vLLM 0.23.0 (`'list' object has no
  attribute 'zero_'`) and strands the engine asleep. FP8 *weights* wake fine.
  This is why `--kv-cache-dtype` is `auto`; the pre-quantized checkpoint still
  yields 93,992 cached tokens, up from 64,046 with the FP8 KV cache.
- `--gpu-memory-utilization` is a fraction of *total* VRAM, so vLLM must start
  before ComfyUI or it cannot reach its share and dies with `No available memory
  for the cache blocks`. `scripts/start-anios.ps1` already encodes that order.

## Presentation editing and ambient discovery

A deck is now editable as a structure: slides can be added at any position,
deleted, and reordered, each as an ordinary linked revision. A slide takes one of
seven shapes, and charts and tables compile from the plan so a revision can edit
their data or remove them. Geometry is measured from the text rather than fixed,
and every layout yields the column a generated image occupies.

Ambient discovery stages 1 to 3 exist as independent boundaries: the interest and
locality profile, the `EventSource` contract with iCalendar and RSS adapters, and
durable scheduled runs with exactly-once slots and write-once delivery. The run
body, novelty filtering, calendar artifacts, and egress remain unbuilt, so
nothing is scheduled end to end yet.

`scripts/start-anios.ps1` now applies migrations before starting the application.
It previously did not, so a fresh clone came up against a database with no
tables. Verified by dropping the schema and re-running that step: 25 tables at
head `20260801_0017`, then a real chat and a discovery write both succeeded.

The presentation rail — drag reordering and the insertion points — has no browser
coverage. It produced four defects in one session, each found by using it rather
than by a test: the drop never firing, the indicator naming the wrong position,
insert-at-front being impossible, and unhittable targets.

## Next atomic task

Try a pre-quantized FP8 Qwen checkpoint so the GPU handoff can be enabled. That
is the one change that removes the image-latency ceiling rather than working
around it: it should avoid the online-quantizer wake bug, after which
`GPU_HANDOFF_ENABLED`, `--enable-sleep-mode`, and `VLLM_SERVER_DEV_MODE=1` can be
turned on together. Verify by sleeping and waking twice, then running a real
image job and a chat in that order. If the wake still fails, leave the handoff
off and record the checkpoint that was tried.

Afterwards, decide the model-cache location. Weight loading over the 9P mount
costs about 64 s of every cold start, and moving `VLLM_MODEL_CACHE_PATH` to a
WSL-native Docker volume should cut most of it. The tradeoff is copying the
8.68 GiB checkpoint once (or re-downloading it) and giving up a browsable host
folder, so confirm the intent before moving it. Measure a cold start before and
after rather than assuming the improvement. Do not begin dynamic model lifecycle
or GPU resource scheduling before this is settled.
