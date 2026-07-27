# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-26, America/New_York

Verified implementation checkpoint: `204a1e5def5c239aa2af665d1c64081de8106721`.

## Current boundary

AniOS now has a bounded hybrid main supervisor. After the existing explicit
diagram branch, `MainSupervisorAgent` runs one typed LangGraph policy node
before retrieval. It delegates explicit presentation creation to the registered
`presentation_agent`; every other request continues to the ordinary assistant,
memory, search, and MCP path.

The supervisor owns no service, storage, permission, or execution capability.
Application code validates its typed decision, enqueues the durable
presentation job, persists the turn, and streams visible `agent_started` and
`agent_finished` events with the exact specialist, model, job ID, and status.
The presentation worker then invokes `PresentationAgent` independently of the
foreground conversation.

This is not yet a dynamic agent team. The supervisor does not compare all
agents and MCP tools in one decision, create arbitrary agents, perform A2A, or
resume a consequential-tool confirmation.

The current RTX 5080 runtime must preload both qualified text roles explicitly.
The verified profile has exactly one Qwen and one Gemma instance, each at an
8,192-token context and one inference slot; Gemma keeps KV cache in system RAM.
Loading Gemma by model name alone selected a 256k context, required about
29.44 GB, and failed LM Studio's resource guardrail. AniOS documents the bounded
profile but does not yet own model-residency preflight or recovery.

## Qualified model roles

- Main response and native MCP selection:
  `MAIN_LLM_MODEL=qwen/qwen3.5-9b`.
- Diagram planning: `DIAGRAM_LLM_MODEL=qwen/qwen3.5-9b`.
- Progressive presentation planning/revision:
  `PRESENTATION_LLM_MODEL=google/gemma-4-12b`.
- Vision remains `VISION_MODEL=google/gemma-4-12b`.
- Text embeddings remain
  `EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5`.
- Each main/presentation/diagram role has an independent endpoint and reasoning
  setting. Blank values fall back through main and legacy LM Studio settings.
  Compose forwards every role setting to the services that use it.
- The final loaded workstation profile reported about 6.10 GiB for Qwen and
  9.28 GiB for Gemma. These are measured local profiles, not portable defaults.

`backend.cli.qualify_models` compares candidates sequentially on five bounded
supervisor/tool decisions plus a production-shaped progressive two-slide
contract. It is a gate, not promotion proof. The actual owning subsystem's API,
worker, state, logs, and browser path remain authoritative.

## Git and runtime identity

- Branch: `main`.
- Starting and current `HEAD`:
  `aeafbb51a4f0cc6efd7fc6790b62a22dc0251e43`.
- The working tree is intentionally uncommitted and contains this task plus
  pre-existing presentation work. No commit, tag, branch, stash, reset,
  restore, clean, push, or recovery operation was performed.
- Final-source Compose images exercised:
  - backend:
    `sha256:d823e0dd58e05898b0f69cf303779a2290a4d2ba115cb361540346976124aab7`;
  - presentation worker:
    `sha256:ec9438bf30f5fcf1727f417fa39094f3864bf4d7142d9468bd3b71f52495d256`;
  - local capabilities:
    `sha256:e2e7998d8a1a884eb501a34d2095e7da6842606142eeabdaa68ca6749b23dcfe`;
  - frontend:
    `sha256:b3c1f576a658f8e0817a15ad59bbb6e56d60e40c31b3b45f54be0d0b9a41926c`.

## VERIFIED

- The configured Qwen cascade passed the complete committed search-routing
  evaluation: 52 cases, 1.0 recall, 1.0 specificity, no misses, and no
  unnecessary searches. An earlier run also had no misses and one conservative
  extra search, so both exceeded the 0.90/0.80 gates.
- Forced worker termination is live-verified. A disposable worker claimed job
  `63753036-a55d-4cc0-8c91-51241ff2b937`; it was stopped while running, the
  canonical worker reclaimed the same row on attempt 2 after the killed
  process's Redis model lease expired naturally, and produced a ready,
  exact four-slide, 96,229-byte PPTX through Gemma and
  `pptxgenjs+libreoffice`.
- Cooperative cancellation is live-verified through both the direct API and
  isolated Chromium. Cancellation occurred only after persisted worker
  ownership, returned HTTP 204, reached terminal `cancelled` with
  `cancel_requested=true` and `error_code=cancelled`, left no promoted revision,
  showed request/terminal notices, cleared the browser resume key, and removed
  its scoped presentation.
- Two disposable worker replicas simultaneously claimed separate jobs with
  distinct worker IDs. Both completed on attempt 1 with exact two-slide
  specifications, one revision each, valid content metadata, and no duplicate
  claim. The disposable containers were removed and the canonical worker was
  restored.
- A 30-second, four-client mixed live workload overlapped six terminal chat
  streams and 45 working-memory/operations calls with two real two-slide jobs.
  All 51 operations passed with zero failures; p95 was 35.059 seconds, maximum
  was 67.255 seconds, and both decks reached ready on attempt 1 in 147.881
  seconds.
- After explicit bounded model loading, isolated live Chromium completed
  foreground Qwen chat plus a background Gemma two-slide deck in 131.2 seconds.
  It required the unique rendered chat reference, terminal ready state, exact
  slide count, model/renderer/content metadata, cleared loading, enabled empty
  composer, clean required Network/Console/page state, and scoped cleanup.
  Isolated live Chromium cancellation passed in 93.4 seconds.
- The unified-composer image acceptance tests now exercise the real natural
  language send, paperclip/file chooser, image follow-up/refinement field, and
  unified Retry control. All seven affected image workflows pass.
- Full backend regression passed in the exact runtime image with declared dev
  extras: 488 passed, 2 skipped, and five deprecation warnings. The focused
  presentation/supervisor/search set separately passed 106 tests.
- All 34 deterministic Chromium tests pass. The TypeScript/Vite production
  build passes with only the existing chunk-size advisory.
- Ruff and `git diff --check` pass.
- All 11 Mermaid/SVG pairs and `docs/architecture.html` remain synchronized.

## FAILED

- The first combined live browser rerun failed because only Qwen was loaded.
  Gemma's name-only auto-load selected a 256k context; LM Studio estimated
  29.44 GB and rejected it under the resource guardrail. The deck produced no
  draft within 180 seconds and the following cancellation job remained queued
  behind the occupied worker. The two scoped jobs were removed.
- A second combined run exposed duplicate Gemma instances (256k and 8k) and
  Qwen eviction. After normalizing residency, the next isolated run reached the
  chat boundary but the synthetic `LIVE_BG_*` instruction produced an unrelated
  Qwen response. A direct natural reference prompt succeeded; the isolated
  browser acceptance now uses that production-like prompt and passes.
- The first deterministic frontend sweep found seven stale image tests still
  targeting removed mode buttons. The current UI is intentionally one unified
  prompt/attachment composer. Tests were updated to the actual accessible
  workflow, including explicit image intent and the renamed follow-up field;
  the complete deterministic suite now passes.
- Repository-wide `alembic check` retains the previously documented unrelated
  visual-artifact HNSW metadata drift. This task did not alter that schema.

## UNVERIFIED

- The application does not yet preload, validate, or repair LM Studio role
  residency. The documented bounded RTX 5080 profile is manual; a server/model
  restart can reintroduce unsafe default contexts or role eviction until an
  application-owned preflight exists.
- Qwen's current role evidence is local to the downloaded quantization,
  prompts, LM Studio version, and 8k/parallel-1 RTX 5080 profile. Long-duration
  multi-user latency, accuracy drift across repeated releases, contexts above
  8k, memory pressure beyond the bounded run, and DGX Spark behavior remain
  unmeasured.
- The supervisor registry currently contains only presentation creation.
  Ambiguous agent/tool selection, clarification/resume, consequential MCP
  approval, dynamic agent teams, A2A, and general distributed scheduling remain
  unimplemented.
- The bounded two-replica test proves PostgreSQL claim safety on one host; it
  does not prove multi-host GPU scheduling, fairness, autoscaling, or
  long-duration crash churn.

## Next atomic task

Add an application-owned role-model residency preflight before starting model
work. It should read the configured main/presentation/diagram identifiers,
query LM Studio's management API, reject duplicate or unsafe context profiles,
and return an actionable readiness failure instead of allowing a worker to
spend repeated provider timeouts on an unloaded role. Keep model load/unload
mutation explicit and operator-controlled in this slice; do not build the full
GPU scheduler yet. Acceptance must cover both roles resident with the verified
profile, missing presentation model, duplicate/oversized Gemma instances,
provider-unreachable behavior, redacted logs, and the isolated live
chat-plus-deck browser path.

After that guard is verified, resume the typed capability-registry task shared
by the main supervisor and MCP shortlist.
