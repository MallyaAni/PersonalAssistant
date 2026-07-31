# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-31, America/New_York

This working tree is based on `main` commit
`5f04f13322c8c7725377f7e88435ac8189a3eae6`. It was already modified at session
start and remains intentionally uncommitted. Preserve all pre-existing work;
the current `HEAD` is not a verified checkpoint for these uncommitted changes.

## Current boundary

AniOS now assembles main, presentation, diagram, vision, and text-embedding
roles through provider-neutral contracts and fail-closed adapter factories.
The implemented adapter is `openai_compatible`. Each role can independently
select its adapter, endpoint, model, and reasoning setting; blank role adapters
inherit `INFERENCE_ADAPTER`. `INFERENCE_PROVIDER_NAME` is provenance only.

The qualified runtime remains unchanged: Qwen `qwen/qwen3.5-9b` serves main,
tool-selection, and diagram roles; Gemma `google/gemma-4-12b` serves
presentations and vision; Nomic serves text embeddings through LM Studio. Both
text models are resident at 8192 context and parallel one. The inference
boundary does not discover, load, unload, resize, or restore models.

The RTX 5080 presentation profile still defaults to one automatic 1024px
HiDream hero image. Redis prioritizes foreground chat between presentation
model microtasks. Gemma planning and ComfyUI image work remain serial because
they share one 16 GB GPU. Automatic lifecycle transitions remain planned:
LM Studio's tested REST reload did not reproduce the qualified CLI residency
profile.

## Runtime and Git identity

- Branch: `main`.
- Starting/current `HEAD`:
  `5f04f13322c8c7725377f7e88435ac8189a3eae6`.
- Working tree: modified and intentionally uncommitted; no commit was created.
- Backend image exercised:
  `sha256:1688dd5bf39292ba0ffac66a16d94bee71b93e4e330b8a12915f615ac6990c23`.
- Presentation-worker image exercised:
  `sha256:68a4899d96944dcdc2845082c6bcf95788796d282cf5db08367dd4ab7edcf559`.
- Local-capabilities image exercised:
  `sha256:72e555910f1d5d9c236bd7f1b10255609e887c2778661a65e95bdc64608374f7`.
- Presentation-renderer image exercised:
  `sha256:8f13b1e0b03cef2d4eaeae9db9a9396f4ff908248d5f546b0bc6040eefa4ff59`.
- Frontend image exercised:
  `sha256:392722f6657609e87cd7e7709d83b24ad44f7d18b35c5607e6d5f30450cafe82`;
  the Vite service bind-mounted the current frontend source.

## VERIFIED

- The rebuilt backend resolved main, presentation, and diagram roles to
  `OpenAICompatibleInferenceProvider`, vision to
  `OpenAICompatibleVisionProvider`, and text embeddings to
  `OpenAICompatibleEmbeddingProvider`, while preserving the configured Qwen,
  Gemma, and Nomic model keys.
- The exact direct chat payload for user
  `provider_boundary_1785472464976` returned HTTP 200
  `text/event-stream`, emitted `start`, 17 deltas, and terminal `done`, and
  concatenated exactly `BOUNDARY_FINAL_1785472464976` in 112.070 seconds.
  Conversation readback and scoped deletion both returned 200.
- Backend logs for trace
  `913e00a8-4f98-4360-aae5-9077dc5745d7` showed successful embedding,
  classifier, and main chat-completion calls plus completed graph execution,
  with no backend exception.
- Live Chromium submitted a unique ordinary chat request against the same
  backend image. The non-empty response streamed to the UI, loading terminated,
  the composer reset, the exact rendered answer survived Memory/Conversations
  navigation, required Network responses succeeded, blocking Console/page
  errors were empty, and scoped cleanup returned 200. The test passed in 2.2
  minutes.
- The presentation role returned exact `READY` from
  `google/gemma-4-12b` through `OpenAICompatibleInferenceProvider`.
- Thirty-eight focused provider, embedding, vision-factory, chat API, and
  presentation-agent tests passed. Ruff, Black, and MyPy passed on the changed
  backend boundary.
- The workspace `.venv` editable development install passed `pip check`.
  With Docker Desktop running and PostgreSQL healthy, the complete backend
  suite passed: 499 tests in 22.51 seconds. This includes Google ADK,
  internet-MCP, OpenTelemetry, real-weight ONNX vision alignment, and all
  database integration tests.
- The TypeScript/Vite production build and `docker compose config --quiet`
  passed. The build retained only the existing chunk-size advisory.
- All twelve Mermaid/SVG views and `docs/architecture.html` are synchronized.
  The system and chat views were rendered and visually inspected.
- At final inspection, Qwen and Gemma retained 8192 context and parallel one;
  Gemma retained CPU KV cache, and Nomic text embedding remained loaded.

## FAILED

- None for the provider-neutral inference boundary. The earlier partial-suite
  failures were environment invocation failures: global Python omitted the
  workspace dependencies, and Docker Desktop was stopped so PostgreSQL was
  unreachable. The unchanged complete suite passed through `.venv` after the
  database became healthy.

## UNVERIFIED

- No second inference runtime has implemented or passed the adapter contract.
  vLLM, TensorRT-LLM, and automatic model transitions remain unimplemented.
- Live vision and live text-embedding requests were exercised indirectly
  through the chat path only for text embedding; the current-source browser
  acceptance did not upload an image. Their unchanged deterministic contracts
  passed prior subsystem acceptance, but a new runtime must repeat those paths.
- Automatic model unload/reload, complete residency-profile capture/restore,
  sustained concurrent load, DGX Spark performance, and a capacity-aware GPU
  resource manager remain unverified.
- A rendered-slide visual quality gate and automatic typed VLM observations
  remain planned.
- Security hardening remains deferred per roadmap.

## Next atomic task

Add a repeatable provider-neutral inference benchmark without changing the
qualified runtime. Record adapter/runtime/model identity and measure main-role
time-to-first-token, generation throughput and terminal streaming; bounded
native tool/structured correctness; presentation-role buffered latency;
embedding batch latency/dimension; and vision latency on a fixed owned fixture.
Run and document the LM Studio RTX 5080 baseline first. Do not add vLLM,
TensorRT-LLM, model unload/reload, or GPU scheduling until the benchmark is
stable and its pass/fail thresholds are explicit.
