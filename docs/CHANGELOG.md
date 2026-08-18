# Changelog

This file is append-only history for meaningful, verified changes. It must not contain plans, active blockers, speculative work, or implementation-complete claims based only on source inspection.

## 2026-08-17

- Replaced the multi-call new-image analysis chain with one schema-constrained
  primary VLM inspection. Identification confidence now belongs to each visible
  item: high-confidence evidence may enter derived visual memory, medium items
  are explicitly unconfirmed, and low-confidence guesses are hidden;
  safety-sensitive cases remain strict. Added a one-shot
  optional specialist-VLM retry for genuine primary-model uncertainty. The real
  authenticated browser upload rendered candidates as Markdown, terminated,
  cleared loading, and produced no blocking browser errors; the current host's
  specialist role remains unconfigured and therefore runtime-unverified.

## 2026-07-15 — Documentation system consolidated

- Replaced overlapping project, AI-context, engineering, debugging, completion, API, memory, RAG, and decision summaries with a ten-document system with explicit ownership.
- Added a concise root `AGENTS.md` and reduced `.clinerules/.clinerules.md` to a compatibility pointer.
- Separated volatile runtime handoff (`NEXT_SESSION.md`), durable milestone state (`ROADMAP.md`), current architecture (`ARCHITECTURE.md`), operational procedures (`DEVELOPMENT_GUIDE.md`), and verified history (this file).
- Corrected documentation claims using observed Compose, HTTP, Vite, test, build, OpenAPI, and PostgreSQL evidence.
- Removed the earlier `0.1.0` entry because it described the conversation engine and infrastructure as completed without recorded functional validation. Repository scaffolding remains documented as `SCAFFOLDED` in the architecture.

## 2026-07-15 — Agent workflow and UI verification clarified

- Restored the complete current-session handoff after it had been truncated.
- Condensed the local-model rules into an atomic evidence-driven loop with stale-artifact detection and a three-hypothesis stop condition.
- Made automated browser testing or documented manual browser execution the requirement for verified UI behavior; endpoint reachability is explicitly insufficient.
- Documented the currently absent frontend test harness as `PLANNED` without adding application dependencies or claiming runtime behavior changed.

## 2026-07-15 — Safe Git checkpoint policy documented

- Defined Git as recoverable code history while retaining functional evidence as the requirement for a verified checkpoint.
- Added starting and final branch, commit, and working-tree reporting when Git is available, with explicit `UNAVAILABLE` handling.
- Documented safe branch/worktree recovery and prohibited automatic destructive reset, clean, restore, checkout, and force-push operations.
- Added Git provenance fields to the current-session handoff without claiming that an existing commit is functionally verified.

## 2026-07-16 — Browser chat path restored

- Corrected the FastAPI chat dependency declaration so valid JSON reaches `ConversationService` and missing required fields still return intentional client errors.
- Added the initial PostgreSQL/pgvector migration, unified model metadata, aligned memory reads with the injected synchronous session, and supplied the required user ID when saving conversation turns.
- Made handled frontend request failures visible, added the missing TypeScript configuration, and restored the production build.
- Verified direct API streaming and persistence plus real Edge success and failure workflows, including rendered responses, stream termination, loading cleanup, Console/Network behavior, and user-visible failures.
- Added targeted chat API and service regression coverage; the graph remains a fixed placeholder and is not recorded as model-backed behavior.

## 2026-07-16 — Browser regression harness added

- Added dependency-managed Playwright Chromium coverage for deterministic chat success, handled connection failure, required request payload, stream completion, loading cleanup, and blocking browser errors.
- Added a separately gated live-provider browser test so repeatable application coverage is not conflated with local-model availability.
- Updated the Vite React plugin to its Vite 8-compatible line and verified the frontend production build.

## 2026-07-16 — LM Studio Gemma chat and streaming verified

- Replaced the fixed graph response with an injected LM Studio native REST client configured for `google/gemma-4-12b`.
- Routed native `message.delta` events through the existing single-node LangGraph and appended transport chunks in the React chat window.
- Verified a six-chunk direct AniOS response, exact completed-response persistence, and a real Playwright browser submission with visible in-progress content, clean termination, loading cleanup, and no blocking Console or page errors.
- Added provider-contract, truncated-stream, graph/service streaming, and persistence regression coverage. Multi-agent orchestration and complete memory behavior remain outside this verified change.

## 2026-07-16 — Memory persistence test boundary restored

- Aligned memory integration tests with the application's synchronous SQLAlchemy session and isolated every test in a rolled-back outer transaction.
- Exposed profile saving through `PostgresMemoryService` and corrected episodic and semantic metadata persistence to use the mapped `extra_data` fields.
- Verified default profile retrieval, profile saving, user-scoped episodic save/read, semantic vector-row saving, and metadata persistence; the full backend suite now passes 13 tests.
- Kept semantic text embedding/retrieval and assistant use of loaded memory explicitly unverified.

## 2026-07-16 — Personal memory verified for local development

- Added a validated LM Studio Nomic embedding provider and migrated semantic memory from 1,536 to 768 dimensions with mandatory user scoping.
- Implemented profile upsert, episodic and semantic persistence, pgvector similarity search, bounded untrusted-memory graph context, memory snapshots, scoped record deletion, and delete-all behavior.
- Added a browser Personal Memory screen and stable conversation IDs distinct from per-request trace IDs.
- Verified with 21 backend tests, four deterministic browser tests, two live Gemma/Nomic browser tests, Alembic drift, the production build, PostgreSQL readback, cross-user deletion rejection, reload persistence, exact Gemma recall, and post-delete database absence.
- Authentication and authorization remain absent; local user IDs are not recorded as security boundaries.

## 2026-07-16 — Conversational-memory scope corrected

- Reproduced a same-conversation workflow where the user stated their name and later asked for it; the assistant did not remember it.
- Confirmed conversation IDs and turn persistence worked, while prior turns were not loaded and no profile, episodic, or semantic row was created.
- Corrected milestone and handoff language: explicit Memory Logs/API persistence and recall remain verified, but ordinary conversational memory is incomplete.

## 2026-07-16 — Same-conversation recall verified

- Added a configurable, newest-10-turn conversation-history window filtered by both conversation ID and user ID and returned to the graph in chronological order.
- Preserved system, prior user/assistant, and current-user messages by moving chat generation to LM Studio's OpenAI-compatible chat-completions endpoint; streaming now requires the provider's terminal `[DONE]` event.
- Verified direct two-request API recall, distinct per-request traces, same-conversation PostgreSQL persistence, and real Chromium name recall with stream termination, loading cleanup, and no Console or page errors.
- Expanded regression evidence to 23 backend tests, four deterministic browser tests, three live Gemma/Nomic browser tests, a clean Alembic drift check, and a passing frontend production build.
- Durable fact extraction across new conversations remains unimplemented; this change does not create profile, episodic, or semantic memory from ordinary chat.

## 2026-07-16 — Runtime boundaries and repository hygiene verified

- Replaced raw chat-body parsing and ad hoc chunks with a validated request model and framed SSE start/delta/done/error contract; streaming failures now expose a generic client message while retaining server-side diagnostics.
- Reduced active dependency assembly and interfaces to implemented collaborators, added privacy-safe trace logging, removed dead backend/UI scaffolding and unused packages, and added ignored environment/build/cache defaults plus a safe example environment file.
- Isolated chat and memory UI state across user/conversation changes, cancelled obsolete memory reads, and expanded deterministic browser coverage to five workflows.
- Verified the current-source direct Gemma API path and lifecycle logs, three live Chromium Gemma/history/Nomic workflows, 27 backend tests, the frontend build, static type/format/lint checks, dependency integrity, npm audit, and Alembic drift.
- Documented remaining production-memory gates and a planned deterministic, data-minimizing internet-search policy. Neither production hardening nor internet search is recorded as implemented.

## 2026-07-16 — Approval-based preferred-name memory verified

- Added narrow deterministic preferred-name proposals to the chat SSE contract without persisting the proposal, plus explicit approval, rejection, correction, and name-only deletion controls.
- Preserved profile preferences during approved name writes and kept user scoping at the existing local-development boundary.
- Increased Gemma's default output budget from 512 to 1,024 tokens after a live reasoning-only response exhausted the smaller budget; the identical direct acceptance path then terminated all five streams.

## 2026-07-16 — Structured preferred-name facts verified

- Added the `memory_facts` migration and structured fact model with user scope, normalized values, source conversation/trace provenance, approval/confidence/purpose, version/supersession, timestamps, optional expiry, and embedding-version metadata fields.
- Migrated preferred-name approval, correction, projection, snapshot, and deletion to the structured fact lifecycle while retaining the profile name as a compatibility projection.
- Configured LM Studio `reasoning_effort=none` after provider probes proved the generic `reasoning=off` field was ignored on chat completions; revised memory-context instructions so approved values remain usable while values are still treated as untrusted literal data.
- Verified migration upgrade/downgrade/re-upgrade, deterministic fact lifecycle tests, a direct reject/approve/recall/correct/recall API path with terminal streams and clean logs, and the real Chromium preferred-name workflow.

## 2026-07-16 — Memory lifecycle, retrieval, ownership, and tool memory verified

- Added relevance-gated semantic retrieval with configurable cosine distance, result and character budgets, stable relevance metadata, prompt-injection isolation, and a repeatable quality/privacy fixture.
- Added episodic/semantic record correction, semantic re-embedding, explicit purpose/expiry, embedding model/version/dimension metadata, conversation-inclusive JSON export, and delete-all propagation across all current user-owned PostgreSQL tables.
- Added inline browser correction and JSON export controls; deterministic and live Chromium paths verified correction, reload, Gemma recall, export, loading recovery, deletion, and clean Console/Network behavior.
- Added provenance-idempotent preferred-name approval backed by a database uniqueness constraint; identical retries return the original fact while conflicting provenance returns 409.
- Added optional expiring HMAC-signed local-user tokens and ownership enforcement for chat, memory, exports, deletion, and tool memory. Auth-enabled runtime checks returned 401 for missing/invalid tokens, 403 for cross-user access, and completed an owner chat stream.
- Added separately stored safe MCP tool descriptors, approved allowlisted preferences, and sanitized outcome categories. Descriptor embedding/discovery is user/server scoped, schema changes deactivate stale versions, secret-shaped data is rejected, and stored records cannot authorize or invoke tools.
- Advanced Alembic through `20260716_0007`; 53 backend tests, static/type/format/migration checks, the frontend build, 7 deterministic browser tests, and 4 live LM Studio browser tests pass.
- Verified direct and real Chromium rejection-without-write, approval, two new-conversation recalls, correction, cross-user isolation, deletion, visible approval failures, loading cleanup, Console/Network behavior, PostgreSQL conversation readback, 37 backend tests, seven deterministic browser tests, four live browser tests, static checks, Alembic drift, and the production build.

## 2026-07-16 — Chat navigation and memory controls verified

- Preserved the active in-memory transcript when switching between Chat and Memory while retaining intentional resets for a new conversation or changed user.
- Made `New conversation` open a fresh Chat view even when invoked from Memory, and disabled blank Send/manual-memory actions instead of presenting controls that silently do nothing.
- Kept explicit manual memory creation as an advanced capability while replacing primary `episodic`/`semantic` jargon with `event or experience` and `fact or preference` labels.
- Verified 10 deterministic Chromium workflows, all four live Gemma/Nomic Chromium workflows, real Memory endpoint navigation with transcript preservation, clean Console/page state, and the TypeScript/Vite production build.

## 2026-07-16 — Search-first light theme verified

- Replaced the dense dark developer-console presentation with a responsive light-neutral system-font theme, translucent navigation, restrained blue/indigo accents, generous spacing, and rounded high-contrast surfaces.
- Reworked empty chat around one centered search composer and active chat into a question/result flow instead of opposing bubbles; request trace and conversation IDs remain accessible under a collapsed details disclosure.
- Kept one Composer instance mounted across the empty-to-active transition, collapsed navigation by default on narrow screens, and preserved all existing streaming, failure, navigation, proposal, and memory behavior.
- Verified 11 deterministic Chromium workflows including a 390 x 844 no-overflow layout, all four live Gemma/Nomic workflows, desktop/mobile visual inspection, and the TypeScript/Vite production build.

## 2026-07-16 — Answer metadata, native composer font, and primary user verified

- Replaced the persistent request-details row with an accessible answer-level three-dot popover containing trace and conversation IDs.
- Made the composer explicitly inherit the shell's native font stack, using SF Pro aliases on Apple platforms and the native `system-ui` fallback elsewhere.
- Migrated missing or legacy `dev_user_001` browser state to the requested `ani.mallya` default with a fresh conversation while preserving every non-legacy stored identity unchanged.
- Isolated and cleaned up the generic live Gemma validation user so automated tests do not add conversations to the primary user.
- Verified 12 deterministic Chromium workflows, all four live Gemma/Nomic workflows, rendered metadata/default-user inspection, and the TypeScript/Vite production build.

## 2026-07-16 — Composer focus and thinking state verified

- Removed the composer's inherited blue textarea focus outline and blue shell shadow while retaining a visible neutral focus boundary and the global focus treatment for other controls.
- Added an accessible `Thinking...` assistant row from submission through the first real SSE response delta; it clears on both successful content and visible request failure.
- Verified the pending, response, failure, loading-cleanup, and neutral-focus states across all 12 deterministic Chromium workflows and passed the TypeScript/Vite production build.

## 2026-07-17 — Typed memory-aware agent and full memory taxonomy verified

- Added typed user-scoped stores and APIs for semantic cache, working memory, approved versioned procedures, entities/relations, knowledge documents/chunks, and conversation summaries, while retaining profile/persona, episodic/semantic, conversational, and safe toolbox memory.
- Added a deterministic memory coordinator that caches typed retrieval plans, queries selected stores, curates bounded untrusted prompt values, updates expiring session state, and creates periodic rolling conversation digests without giving Gemma raw database or durable-write authority.
- Advanced Alembic to `20260717_0008` with pgvector HNSW cosine indexes; upgrade/downgrade/re-upgrade and no-drift validation passed against PostgreSQL.
- Added a Memory-screen taxonomy map backed by personal, agent, and toolbox snapshots, and recorded the store-manager/indexing choice in ADR 0002.
- Verified a direct exact-token Gemma stream, a live all-form query that reproduced unique entity/knowledge/summary/procedure/toolbox codes, complete scoped cleanup, 65 backend tests, 13 deterministic and 4 live Chromium tests, the frontend build, Black, Ruff, MyPy, Alembic drift, and dependency integrity.

## 2026-07-17 — Memory lifecycle and operational hardening verified

- Added scoped dry-run/apply retention across expiring memory stores, profile-projection cleanup, a safety-gated purge CLI, and atomic/idempotent PostgreSQL validation.
- Added generic approved facts with normalized deduplication, provenance idempotency, contradiction supersession/versioning, correction, per-record/key deletion, preferred-name/response-style projections, and an explicit response-style chat approval flow.
- Added resumable batch re-embedding for every vector-bearing store, same-dimension enforcement and rollback, stale-vector inventory, a safety-gated CLI, and real Nomic migration evidence.
- Added transaction advisory locks for natural-key memory writes, scoped agent/tool per-record deletion, concurrent write tests, a repeatable real-provider pgvector hit-rate/latency evaluator, and operational counts/backlog/invariant/DB inspection through API and CLI.
- Verified 83 backend tests, 14 deterministic and 5 live Chromium workflows, the TypeScript/Vite build, Black, Ruff, strict MyPy, Alembic head, and dependency integrity. Non-blocking async database access, vector-column dimension changes, external scheduling/alerts, and the explicitly deferred security/backup subsystem remain unfinished.

## 2026-07-18 — Non-blocking memory persistence verified

- Converted FastAPI, conversation, memory, coordinator, retention, re-embedding, and operations persistence to SQLAlchemy `AsyncSession` through `asyncpg`, with a bounded runtime pool and a migration-only synchronous engine.
- Added a real PostgreSQL concurrency acceptance that preserves an event-loop heartbeat while six tasks share a two-connection pool, proves the checkout ceiling, and proves complete pool drain.
- Verified the documented direct SSE payload through Gemma/Nomic, 84 backend tests, 14 deterministic and all 5 live Chromium workflows, the Vite production build, Ruff, Black, strict MyPy, Alembic head/no-drift, and dependency integrity.

## 2026-07-18 — Memory load, recovery, maintenance, and metrics verified

- Added a configurable mixed live soak runner, database transaction/pool recovery tests, and a shared configurable embedding concurrency limit after the first soak exposed LM Studio HTTP 400 responses under concurrent embedding calls.
- The unchanged 15-second, concurrency-four soak then completed 836 public operations—34 terminal Gemma chats and 802 memory/health calls—with zero failures, 89.062 ms p95 latency, and scoped cleanup.
- Added an opt-in Compose maintenance runner for retention, optional re-embedding, final health inspection, recurring JSON/exit signals, and transient-cycle recovery, plus Prometheus-compatible non-content memory metrics.
- Verified 95 backend tests, Ruff, Black, strict MyPy, the Compose maintenance profile, a live one-shot maintenance cycle, and live metric scraping.

## 2026-07-18 — Resumable vector-dimension migration verified

- Made the model vector dimension configuration-driven and added an offline migrator that inventories all seven vector stores, resumes committed shadow-column batches, requires an explicit writer-offline acknowledgement, and switches all pending stores plus HNSW indexes in one PostgreSQL transaction.
- An isolated acceptance forced an incompatible provider response and proved both original `vector(3)` values remained authoritative; retry backfilled both rows, atomically switched to `vector(2)`, and recreated the HNSW index.
- A read-only production inventory confirmed semantic memory, cache, procedures, entities, knowledge chunks, summaries, and tool descriptors remain clean `vector(768)` columns with no abandoned shadow state.

## 2026-07-18 — Approval-gated structured memory capture verified

- Added deterministic chat proposals and browser review controls for explicit person/relationship, reusable workflow, and titled-reference memory without giving Gemma durable-write authority.
- Advanced Alembic to `20260718_0009` so approved procedures and knowledge documents retain source conversation/trace provenance and knowledge approval state.
- Fixed the first live recall boundary by restricting coordinator-plan caching to exact queries; semantically similar cached plans can no longer suppress deterministic store routing.
- Verified rejection-without-write, typed approval, counts, provenance, new-conversation recall of a dentist name plus unique workflow/reference codes, visible UI state, terminal streams, and scoped cleanup in real Chromium.

## 2026-07-18 — Memory production regression completed

- Verified the exact current source with the documented direct SSE payload and clean Gemma/Nomic logs, 101 backend tests, 15 deterministic and all 6 live Chromium workflows, the Vite production build, Ruff, Black, strict MyPy, Alembic head/no-drift, dependency integrity, and the Compose maintenance profile.
- A 60-second concurrency-four soak completed 6,526 public operations—66 terminal chats and 6,460 memory/health calls—with zero failures, 63.044 ms p95 overall latency, and confirmed scoped cleanup.
- No commit or recovery operation was created; the full memory work remains in the pre-existing dirty working tree at `HEAD aa8b1b218e98b543d5e1ebea018e5b258425d2ac`.

## 2026-07-18 — Architecture diagram maintenance verified

- Added a canonical Mermaid source and rendered SVG for the current AniOS system, plus a pinned local renderer and cross-platform render-input synchronization check.
- Added explicit diagram-impact governance so diagrams change with architectural components, ownership, boundaries, and cross-component flows rather than ordinary implementation churn.
- Recorded the free/local-only, provider-neutral visual-artifact and resource-aware multi-agent direction in ADR 0003 without claiming runtime diagram, image, GPU-transition, or specialized-worker behavior exists.
- Verified a fresh Mermaid render, source/SVG synchronization, visual readability inspection, Node syntax, and the unchanged TypeScript/Vite production build.

## 2026-07-18 — Local diagram artifacts verified

- Added provider-neutral diagram and artifact contracts, a bounded local Gemma-to-Mermaid provider with one format-correction retry, user-scoped pending/ready/failed PostgreSQL persistence, migration `20260718_0010`, listing/deletion APIs, and artifact SSE events.
- Added lazy strict Mermaid rendering in chat with editable source, visible generation/render failure states, loading cleanup, and in-memory retention while switching between Chat and Memory.
- The direct API acceptance reached LM Studio, emitted `start`, `artifact_started`, `delta`, `artifact_ready`, and terminal `done`, persisted provider/model plus conversation/trace provenance, and logged successful completion without a server exception.
- Real Chromium submitted a unique diagram request through the live Gemma path, observed the required SSE request, rendered the SVG and source, confirmed persisted ready state and tab-navigation retention, cleared loading, found no blocking Console/page errors, and cleaned its scoped records.
- Verified 117 backend tests, 17 deterministic Chromium workflows, the focused live diagram workflow, TypeScript/Vite build, Ruff, Black, strict MyPy, Alembic head/no-drift, dependency integrity, and synchronized/readable architecture source plus SVG.

## 2026-07-18 — Detailed subsystem diagram suite verified

- Expanded the canonical architecture documentation into seven synchronized Mermaid/SVG pairs: full system, runtime/deployment, chat orchestration, memory, tool memory, visual artifacts, and frontend.
- Generalized the pinned local renderer so one render or check command fingerprints and syntax-validates every maintained diagram against its own source plus the shared configuration and renderer version.
- Added a diagram catalog that maps common technical questions to the correct view and explicitly distinguishes the current modular FastAPI backend from independently deployed microservices.
- Visually inspected every SVG in Chromium, restructured four initially over-wide views, then verified the final suite synchronization, local documentation links, Node syntax, and unchanged frontend production build.

## 2026-07-18 — Subsystem diagram maintenance governance verified

- Required every modifying task to assess the full-system view and each detailed subsystem view that owns the changed code.
- Added an actionable code-area ownership map, new-subsystem registration rule, full-suite synchronization procedure, affected-view visual check, and exact completion-report format.
- Verified the unchanged seven-diagram suite remains synchronized and the updated Markdown references resolve locally; no runtime architecture fact changed.

## 2026-07-18 — Diagram agent and reviewed architecture candidates verified

- Added a focused typed `DiagramAgent` LangGraph workflow between artifact orchestration and the replaceable provider without granting persistence, authorization, or hardware authority.
- Added a local-only maintainer command that combines registered canonical source with bounded explicit repository evidence, refuses remote endpoints and canonical overwrite, validates passive Mermaid plus required labels with one bounded semantic correction, and renders new review candidates through the pinned toolchain.
- A real Gemma candidate contained all four required implementation labels, rendered successfully, and remained outside canonical documentation until technical and visual review; an earlier incomplete candidate was safely rejected by review.
- Direct current-source API and live Chromium acceptance reached Gemma through the diagram graph, produced and rendered terminal ready artifacts, cleared loading, found no blocking browser errors, and cleaned scoped records.
- Verified 124 backend tests, Ruff, Black over 109 files, strict MyPy over 71 source files, dependency integrity, 17 deterministic and the focused live Chromium workflow, the frontend build, and eight synchronized/readable architecture views.

## 2026-07-18 — Active conversation and diagram reload restoration verified

- Added a bounded, user-owned conversation snapshot API that joins persisted turns with their visual artifacts without exposing cross-user records.
- Made React session initialization side-effect free, then restored the locally active conversation after full reload with visible loading/failure states, reconstructed questions and answers, strict SVG rendering, and editable Mermaid source.
- Real Chromium submitted a unique diagram through current-source AniOS and Gemma, switched views, reloaded the page, observed the snapshot request, and restored the persisted transcript and diagram without blocking Console/page errors; scoped cleanup removed the validation records.
- Verified 125 backend tests, Ruff, Black over 111 files, strict MyPy over 72 source files, 18 deterministic Chromium workflows, the focused live Gemma workflow, the frontend build, and eight synchronized architecture diagrams.

## 2026-07-18 — Visual artifact history and local export verified

- Added a bounded recent-artifact listing boundary across a user's conversations and a dedicated Artifacts view with refresh, strict rendering, visible empty/error states, and owned deletion.
- Added local `.mmd` and rendered `.svg` downloads to every ready diagram card without another model request or external transfer.
- Live Chromium generated a unique diagram through Gemma, restored it after reload, listed it in artifact history, downloaded both formats, deleted it through the UI, and observed the empty state with clean blocking Console/page evidence.
- Verified 125 backend tests, Ruff, Black, strict MyPy, 20 deterministic Chromium workflows, the focused live Gemma workflow, the frontend build, and eight synchronized diagrams; one concurrently loaded heartbeat timing check passed both isolated and in the sequential full rerun.

## 2026-07-18 — Interrupted diagram cleanup verified

- Added explicit cancellation handling around diagram provider work and shielded only the durable terminal cleanup so disconnect cancellation is still re-raised.
- A direct HTTP client disconnected immediately after `artifact_started`; within 750 ms the persisted record was `failed` with sanitized `error_code=cancelled`, no source, and a matching cancelled trace log instead of remaining pending.
- The first direct run proved cancellation reached the handler but also cancelled the SQLAlchemy cleanup commit; an AnyIO shield around only that write fixed the unchanged acceptance path.
- Verified 126 backend tests, Ruff, Black, strict MyPy, scoped cleanup, and eight synchronized diagrams with the updated chat and visual-artifact cancellation flow.

## 2026-07-18 — Local image generation and vision analysis verified

- Added a free, local ComfyUI image-generation provider backed by the pinned HiDream-I1 Dev FP8 model, with bounded concurrency, polling, output validation, cancellation, and sanitized terminal failures.
- Added durable private binary-artifact storage for generated and uploaded PNG, JPEG, and WebP images, including ownership checks, integrity metadata, atomic writes, content delivery, and coordinated file-plus-record deletion.
- Added bounded image upload and Gemma vision analysis through the existing local LM Studio boundary; successful analyses preserve model and usage provenance, while provider failures preserve the owned upload with an explicit failed analysis state.
- Direct API acceptance generated and visually inspected unique images, analyzed an uploaded image with Gemma, rejected invalid media and unsupported resolutions, enforced cross-user isolation, removed an owned artifact from both storage and PostgreSQL, and confirmed image generation coexists with the primary 256k-context Gemma runtime.
- Kept browser image-generation and upload controls out of this atomic backend stage; the next task is to integrate these verified APIs into the existing visual-artifact UI with progress, preview, analysis, download, deletion, and visible failure states.
- Verified all 132 backend tests, Ruff, Black over 121 files, strict MyPy over 81 source files, Alembic head/no-drift, the frontend production build, 20 deterministic Chromium regressions, and eight synchronized architecture diagrams; visually reviewed the three affected diagrams and cleaned all scoped acceptance artifacts.

## 2026-07-18 — Browser image generation, vision, and cancellation verified

- Added Chat, Create image, and Analyze image composer modes with bounded upload selection, visible progress and failures, retained retry state, request cancellation, private image previews, grounded Gemma analysis, download, deletion, artifact history, and conversation/reload restoration.
- Matched the browser client to the actual wrapped vision response and added a disconnect monitor around image-provider work so browser cancellation interrupts the exact ComfyUI prompt and durably records `failed/cancelled` without a backend exception.
- Direct current-source acceptance generated and visually inspected a unique 2048x2048 image, verified exact persisted/downloaded size and SHA-256, and cleaned the owned artifact. Live Chromium then completed real ComfyUI generation plus multipart Gemma analysis with terminal loading, clean successful Console/Network behavior, reload/history restoration, and scoped cleanup.
- Verified 133 backend tests, Ruff, Black over 122 files, strict MyPy over 81 source files, Alembic head/no-drift, 24 deterministic Chromium workflows, both focused live visual workflows, the TypeScript/Vite production build, and all eight synchronized architecture diagrams.

## 2026-07-18 — Safe assistant Markdown rendering verified

- Replaced plain assistant-answer text with styled CommonMark rendering for semantic headings, paragraphs, bold/emphasis, ordered and unordered lists, block quotes, code, links, and horizontal rules while keeping user messages literal.
- Kept raw HTML interpretation disabled. A browser fixture containing an image event handler created no image and executed no script.
- The exact controlled streamed sample changed from zero semantic formatting elements to a rendered heading, strong text, emphasis, and list item with no visible marker characters or blocking browser errors. A live Gemma stream independently rendered the heading syntax it emitted through the current backend and UI, and the chess-style answer layout passed visual inspection.
- Verified all 25 deterministic Chromium workflows, the TypeScript/Vite production build, zero npm audit vulnerabilities during installation, and scoped cleanup of both live validation users.

## 2026-07-20 — Threaded followup questions on owned images verified

- Added `POST /api/v1/vision/artifacts/{artifact_id}/ask`, allowing bounded followup questions about any owned ready generated or uploaded image. The handler re-reads the integrity-checked stored bytes instead of requiring a new upload, so a generated image can now be discussed multimodally.
- Extended the `VisionProvider` boundary with a threaded call that anchors the image once and replays a bounded prior question/answer context; `VisionAnalysisService` appends each grounded answer to a size-bounded thread persisted in artifact metadata, seeds that thread from a prior flat analysis, and returns 404 for unowned or non-ready images before any provider call. Configurable `VISION_THREAD_CONTEXT_TURNS` and `VISION_THREAD_MAX_STORED` bound replayed context and stored size so a long thread cannot grow the VLM input or metadata without limit.
- Added a threaded "Ask about this image" control to the private image card that renders the accumulated question/answer thread and appends each answer in place.
- Verified the full backend suite (138 passed) with the PostgreSQL container up, including five new followup service tests covering thread accumulation and history replay, independent context/storage bounding, legacy flat-analysis seeding, unowned/non-ready rejection, and failure that preserves the prior thread. A new deterministic Chromium test exercises the ask box end to end. Ruff, strict MyPy on the changed modules, the frontend TypeScript check, and the eight-diagram render/synchronization check all pass. A live Gemma followup session and any memory-subsystem indexing of image content were not run and remain deferred.

## 2026-07-21 — Memory retrieval throughput, budget, and manager overview

- Collapsed per-turn embedding work: a chat turn now embeds the query exactly once and reuses that vector across personal semantic, entity, knowledge, procedure, summary, and toolbox retrieval. Previously a single multi-store turn could issue roughly seven serialized embedding calls through the one-slot local provider, including one purely to store a deterministic keyword plan.
- Removed the embedding-backed coordinator plan cache. Routing is deterministic keyword matching, so the plan is now recomputed directly instead of embedding the query to write and re-read a cached plan; the semantic cache remains available as a general response cache.
- Added a batch `embed_texts` provider call (single request, index-ordered reassembly) and used it so multi-chunk knowledge ingestion embeds in one call rather than one request per chunk.
- Added one shared per-turn relevance budget in the coordinator that ranks retrieved items across every store, drops duplicate content, and caps total items and characters, replacing independent unbounded per-store top-k lists reaching the prompt.
- Bounded the display memory snapshot with a configurable per-form cap while keeping the export path complete, so the frequently called snapshot endpoint cannot load unbounded rows.
- Added a manager-facing `memory-overview` diagram (numbered per-turn path, approval gate, short-term vs long-term stores, data-control note, and a legend) and registered it in the renderer suite and catalog. Updated the detailed `memory-subsystem` diagram to show single-embedding retrieval and the cross-store relevance budget.
- Verified the full backend suite (140 passed) with the PostgreSQL container up, plus new embedding-batch and context-budget tests; Ruff, strict MyPy (81 files), Black, and the nine-diagram render/synchronization check all pass. Episodic relevance ranking, Redis-backed working memory, enforced authentication, and encryption-at-rest are staged as the next verified increment and are not claimed here.

## 2026-07-21 — Frontend and ComfyUI containerization

- Added a `frontend` Docker Compose service (dev image `frontend/Dockerfile.dev`) that bind-mounts the working tree and runs Vite with polling so hot module reload fires across the Docker/Windows mount; added a minimal `vite.config.ts` that binds all interfaces and enables polling only when `VITE_USE_POLLING` is set, preserving host-run behavior. Verified: the container serves the real console (`AniOS Developer Console`, Vite HMR client injected) and the container backend reaches host LM Studio at `host.docker.internal:1234`.
- Wired the Compose backend to the containerized stack: `LLM_BASE_URL=http://host.docker.internal:1234`, `IMAGE_PROVIDER_BASE_URL=http://comfyui:8188`, and `host.docker.internal` mapped via `extra_hosts` so a containerized backend reaches host LM Studio and the sibling ComfyUI service.
- Added an opt-in `comfyui` Compose service (`comfyui` profile) with a CUDA 12.8 / Blackwell-capable PyTorch image (`docker/comfyui/`) that bind-mounts the existing host ComfyUI install (`COMFYUI_HOST_PATH`, default `E:/AI/ComfyUI`) and requests the NVIDIA GPU through Compose device reservations; a first-boot entrypoint installs the mounted install's non-torch requirements before launching ComfyUI on `0.0.0.0:8188`.
- Updated the `runtime-deployment` diagram to show frontend, backend, and ComfyUI as Compose services with LM Studio remaining a host process; nine diagrams remain synchronized.
- Known limitation observed during verification: the ComfyUI image was not brought up because the Docker Desktop disk (WSL2 image on `C:`) filled during the multi-GB CUDA/PyTorch build, producing an `input/output error` and stopping Docker Desktop. The service definition and image build steps are in place; completing ComfyUI verification requires freeing disk space or relocating the Docker Desktop disk to a larger volume.

## 2026-07-22 — Gemma-selected MCP tools and MCP internet search verified

- Added native Gemma tool selection over a bounded user-scoped semantic shortlist while keeping live schema/fingerprint checks, risk policy, argument validation, privacy screening, invocation, and result bounding under application control.
- Added built-in read-only `local_utility/current_time` and `internet/search_web` stdio MCP servers. Internet eligibility and query minimization remain deterministic outside Gemma; the internet server receives only allowlisted search environment variables and returns compact valid JSON as untrusted source data.
- Added streamed tool lifecycle events and browser status for running, succeeded, refused, and failed calls without displaying arguments or raw results. Search continues to render its source cards.
- Verified the final rebuilt backend image through a direct documented chat payload, backend logs, real Gemma tool selection, real Tavily-backed MCP search, and a live Chromium workflow that observed transient and terminal tool state, source cards, stream completion, loading cleanup, and no blocking Console/page errors.
- Verified 339 backend tests, Ruff, Black over 155 files, strict MyPy over 109 source files, all 28 deterministic Chromium workflows, the TypeScript/Vite production build, and nine synchronized architecture diagrams. `alembic check` still reports unrelated pre-existing metadata drift for `ix_visual_artifacts_embedding_hnsw`; it is not claimed clean.

## 2026-07-22 — Local visual FastMCP capability facade verified

- Added a dedicated streamable-HTTP FastMCP sidecar that reuses the existing
  diagram, image-generation, vision-followup, artifact-repository, and binary
  storage services through four agent-facing tools. Tool schemas omit
  ownership identifiers and results return bounded public artifact handles
  without binary data or storage keys.
- Added opt-in application-context forwarding at the MCP invocation boundary.
  AniOS supplies user, conversation, and trace values only to a configured
  `forward_context` server; the local visual server validates those values
  outside model-selected arguments and remains confirmation-gated as
  `untrusted`.
- Live direct acceptance discovered and indexed all four visual tools, created
  a ready Mermaid artifact with Gemma, generated a ready 2048×2048 image with
  ComfyUI, answered a grounded followup with Gemma vision, read the artifact
  handle, and refused the same unconfirmed server with HTTP 409. Scoped cleanup
  removed both artifacts and all six disposable descriptors.
- Repaired the live browser visual test's machine-specific upload path by
  analyzing the image it had just generated, and changed its stale raw-Markdown
  assertion to verify rendered semantic content. Real Chromium then completed
  generation, rendering, navigation/reload restoration, upload analysis,
  loading cleanup, deletion, and clean Console/page state.
- Verified 348 backend tests, Ruff, Black over 172 files, strict MyPy over 111
  source files, all 28 deterministic Chromium workflows, the focused live
  visual browser workflow, the TypeScript/Vite production build, and all nine
  synchronized architecture diagrams. `alembic check` still reports the
  pre-existing `ix_visual_artifacts_embedding_hnsw` metadata drift and is not
  claimed clean.

## 2026-07-23 — Referenced-image conversation and memory drilldown verified

- Added deterministic composer intent so natural-language new-image requests
  submitted from Chat invoke the existing image API and select Create image,
  while historical questions submitted from Create image switch to chat
  without generating again.
- Persisted bounded generation-prompt provenance on ready images and extended
  image recall to historical and referential questions. Explicit web comparison
  now recalls the image first, appends one bounded description, privacy-screens
  the combined query, and invokes the read-only internet MCP tool without image
  bytes.
- Made every Agent memory map card clickable. Details load only after selection
  through the owned export boundary, show bounded readable records, and omit
  embedding vectors and private storage keys.
- Serialized shared Gemma chat-client requests after live browser evidence
  showed LM Studio terminating an overlapping stream. A concurrency regression
  test proves provider calls through that client do not overlap.
- Direct live API checks generated a real ComfyUI image with prompt provenance,
  answered a grounded historical question, and completed an image-aware Tavily
  search with image/search/tool SSE evidence. Real Chromium then completed
  natural generation, chat followup, search lifecycle, terminal loading/input
  cleanup, and memory drilldown with clean Console, page, and required-network
  evidence.
- Verified 353 backend tests, Ruff, Black over 158 files, strict MyPy over 111
  source files, all 30 deterministic Chromium workflows, the focused live
  referenced-image workflow, the TypeScript/Vite production build, and all nine
  synchronized architecture diagrams with five affected views visually
  inspected.

## 2026-07-23 — Hybrid Google and Tavily web research implemented

- Added a pinned Google ADK 2.5.0 research worker using Gemini 2.5 Flash and
  native Google Search Grounding. Each request uses a new single-turn in-memory
  session and receives only the normalized, privacy-screened public query—no
  AniOS identity, conversation history, memory, documents, image bytes,
  credentials, or general tools.
- Added application-owned provider policy: Google is primary when configured,
  Tavily handles disabled/failed/empty/quota-exhausted fallback, and explicit
  verify/cross-check language calls both configured providers once before
  URL-deduplicating results.
- Added an atomic SQLite Pacific-day Google budget containing only provider,
  day, and count. The default 450-call cap leaves headroom below the documented
  500-request free allowance and never enables paid usage.
- Preserved provider attribution through compact MCP JSON, local validation,
  untrusted prompt context, SSE, and browser source cards. Nullable scores allow
  grounded Google sources without bypassing Tavily's relevance floor.
- Final-image direct API trace `6d3277c4-4365-4805-8ab6-c1528dfd4227` and live
  Chromium trace `5604e820-b892-482a-b8ac-587dbb827bb3` verified the rebuilt
  Tavily-fallback path through real MCP, Tavily, Gemma, source rendering,
  terminal `done`, loading cleanup, and clean blocking browser-error evidence.
  Live Google grounding remains `UNVERIFIED` because no Google/Gemini API key
  is configured.
- Verified 367 backend tests, Ruff, Black, strict MyPy over 114 source files,
  dependency integrity, all 31 deterministic Chromium workflows, the focused
  live browser search workflow, the TypeScript/Vite production build, and ten
  synchronized canonical diagrams. Added the dedicated search/research view and
  ADR 0004.

## 2026-07-24 — Search routing measured against a committed labelled set

- Replaced the informally asserted routing accuracy with a committed set of
  labelled routing cases and a mode-aware evaluator that fails a build below
  per-mode recall and specificity floors, so a routing regression is caught
  rather than assumed absent.
- Admitted the labelled-case module explicitly to the architecture-boundary
  test's `search/` allowlist, so a new file in that package cannot slip in
  unreviewed.

## 2026-07-24 — Optional OpenTelemetry request and outbound-call tracing

- Added opt-in OpenTelemetry wiring that instruments FastAPI and httpx, so every
  outbound call—LM Studio, Tavily, an HTTP MCP server—appears as a child span
  carrying W3C trace-context and a slow turn is attributable to the provider
  that caused it. Tracing is off unless `OTEL_ENABLED=true`, and an unreachable
  collector drops spans in the background rather than failing a request.
- Wrapped, rather than replaced, the existing conversation tracer: the adapter
  stamps the application trace id and user id onto the active request span and
  records each step as a bounded, stringified span event, so the custom trace
  and the OpenTelemetry trace refer to the same turn without leaking raw text.

## 2026-07-24 — MCP tool-call idempotency and bounded retry

- Added `MCPRetryPolicy`, which retries a transient transport failure only for a
  server the operator classified `read_only` or `trusted`—the same set that
  skips confirmation—because only a replay-safe call can be repeated without
  risking a duplicate write.
- Kept a consequential server at exactly one attempt: a dropped connection does
  not prove the write never reached the server, so it is never retried into a
  double-execution. A deterministic refusal—a gate rejection, schema failure, or
  privacy block—is never retried; retry wraps only the transport, and the
  invocation gates still run once per call.
- Verified with seven dedicated retry tests and the full suite: 396 backend
  tests, Ruff, Black, and strict MyPy over 119 source files pass.

## 2026-07-24 — Opt-in encryption at rest and least-privilege token scopes

- Added `FieldCipher`, an AES-256-GCM envelope with a self-describing versioned
  format (`enc:1:…`), a fresh per-value nonce, and authenticated ciphertext.
  Encryption is opt-in: with no `ENCRYPTION_KEY` configured it is a transparent
  pass-through, so zero-config local development is unchanged.
- Applied it transparently at the persistence boundary through an
  `EncryptedText` column type on conversation turns and episodic/semantic memory
  content, and sealed generated/uploaded image bytes in the artifact store while
  recording integrity over the plaintext so the existing SHA-256 re-check still
  holds. Legacy plaintext reads back unchanged, so encryption enables without a
  migration; a fresh nonce per value is why it is applied only to content
  retrieved by id or vector, never to a deduplication or uniqueness column.
- Documented the threat model honestly: this is defence in depth over OS
  full-disk encryption for data that leaves the process without the key, not a
  sandbox against a live compromised host; embedding vectors stay searchable and
  therefore unencrypted, a residual disclosure vector recorded in SECURITY.md.
- Added least-privilege token scopes (`chat`, `memory:read`, `memory:write`,
  `tools:invoke`, `vision`, and the `memory`/`tools` groups) enforced per route
  action, so a read token is refused a write before the handler runs. A group
  scope grants its children, an unknown scope is rejected at issue time, and a
  token with no scope claim stays unrestricted so existing tokens keep working.
  Scopes narrow a valid token without replacing the ownership check.
- Verified with new crypto, encrypted-column, binary-store, and scope tests plus
  the full suite: 414 backend tests, Ruff, Black, and strict MyPy over 122
  source files pass.

## 2026-07-24 — Proactive approval-gated episodic memory capture

- Added `propose_episodic`, which proactively proposes an episodic memory when a
  chat turn narrates a first-person past-tense event. Unlike the existing
  proposers it fires without an explicit "remember" trigger, so it is kept
  high-precision (a curated experiential verb set, a first-person-question
  guard, the user's own sentence retained as content) and made the lowest-
  priority proposal, so any explicit preferred-name/style/entity/workflow/
  reference intent still wins.
- Reused the existing approval boundary end to end: the proposal streams as the
  same `memory_proposal` SSE event, the frontend adds an approve/reject card for
  it, and approval routes through the existing `POST /memory/{user}/episodic`
  endpoint with chat conversation/trace provenance. Rejection writes nothing, so
  the "no silent model extraction" principle holds.
- Live-verified against the running stack: a chat turn ("I graduated from
  university last month") emitted the episodic proposal over SSE, and the
  approval call persisted it with `chat_approval` provenance.
- Verified with new proposer tests plus the full suite: 424 backend tests, Ruff,
  Black, and strict MyPy over 122 source files, and the frontend production
  build pass.

## 2026-07-24 — Personal narration no longer triggers a spurious web search

- Fixed a search-routing false positive surfaced by episodic capture: a
  first-person account of the user's own life ("I graduated last month", "I
  moved to Seattle last year") matched the bare `relative_period` temporal
  signal and was routed to the web. A narrated statement is now allowed to veto
  the weak temporal-and-year-only signals (`recency_term`, `time_term`,
  `relative_period`, current/future year) and returns `personal_statement`.
- Kept the veto narrow: a genuine information signal (news, weather, price,
  role holder, schedule, explicit request) still wins inside a first-person
  sentence, and a question or an explicit request ("I need/want/am looking
  for ...") is never treated as a statement. Past-tense and stative verbs both
  count, tolerating an intervening adverb ("I recently adopted a dog").
- Added the narration cases to the committed routing evaluation set (now 52
  labelled cases); patterns-mode specificity is 1.0 with no unnecessary
  searches. Live-verified: "I moved to Seattle last month for a new job" no
  longer searches (and still proposes the episodic memory), while "what is the
  latest Python version this month" still searches.
- Verified with the full suite: 435 backend tests, Ruff, Black, and strict MyPy
  over 122 source files pass.

## 2026-07-24 — Search routing defers ambiguous personal queries to the classifier

- Replaced the regex approach to personal statements (added earlier the same
  day) with a structural fix, after it proved to be whack-a-mole: enumerating
  how people phrase their lives could never be complete, missing contractions
  ("I'm currently reading"), third-person subjects ("my sister got married last
  month") and questions about oneself ("what did I do last month").
- A bare temporal word is now treated as ambiguous, because it attaches equally
  to an information need and to a statement about the user; the difference is
  intent, not vocabulary. The policy detects the one finite, stable thing here -
  self-reference (`I/me/my/we/our`) - and when it accompanies only a weak
  temporal-or-year signal, the patterns abstain (`ambiguous_self_reference`) and
  the cascade defers to the freshness classifier, which judges intent. A strong
  topic signal (weather, price, role holder) still resolves deterministically
  inside a first-person sentence, and a temporal query with no self-reference
  still routes on its own, so the fast path is unchanged.
- Anchored the classifier for this judgement with a system-prompt clause and two
  examples: a statement about the user's life and a question about their own
  history both classify as NO (personal, not public).
- Live-verified through the full cascade with the 12B classifier: "I'm currently
  reading a great novel", "my sister got married last month", "what did I do
  last month" and "what did I eat yesterday" no longer search, while "what is
  the latest treatment for my psoriasis" and "what is the latest Python version
  this month" still search. Patterns-mode specificity stays 1.0 over the 52-case
  set.
- Verified with the full suite: 436 backend tests, Ruff, Black, and strict MyPy
  over 122 source files pass.

## 2026-07-24 — Memory recall searches every embedded store, not keyword-gated ones

- Made the memory coordinator search every embedded store (entities, knowledge,
  summaries, procedures, toolbox) on every turn instead of gating them behind
  keyword triggers. The gate had the same flaw as the old web-search routing:
  "what did my dentist recommend" names an entity worth recalling but contains
  none of the entity trigger words, so recall silently dropped it. Anything
  relevant can now surface regardless of phrasing.
- This is safe because the safety valve already existed: each store filters by a
  cosine-distance threshold (0.35, toolbox 0.45), so an unrelated store returns
  nothing rather than polluting the prompt, and the shared cross-store relevance
  budget with item/character caps keeps only the closest matches. The query is
  still embedded once per turn and reused across stores.
- Episodic memory stays keyword-gated for now because it has no embedding and so
  cannot be recalled by similarity; embedding it is the tracked next step.
- Live-verified: an approved "Dr. Avery Chen (dentist)" entity was recalled by
  "what did my dentist suggest for my teeth?" - a query with none of the old
  entity keywords - and the model answered with the stored recommendation.
- Verified with the full suite: 434 backend tests, Ruff, Black, and strict MyPy
  over 122 source files pass.

## 2026-07-24 — Editable presentation subsystem verified

- Added a focused `PresentationAgent` and strict typed deck/slide contracts so
  local Gemma can plan a complete deck or revise one selected slide without
  receiving persistence, permission, renderer, or sibling-slide authority.
- Added user-scoped presentations and append-only revision lineage with
  stale-base conflict protection, encrypted title/spec fields, opaque binary
  storage, SHA-256 metadata, terminal failures, and promotion only after every
  generation, validation, and storage boundary succeeds.
- Added a pinned PptxGenJS worker that produces native editable text, shapes,
  charts, tables, images, and notes, validates OOXML structure, and opens/exports
  every Compose result through headless LibreOffice before returning it.
- Added owned presentation APIs, a React deck/slide preview, slide-specific
  feedback, revision history, named `.pptx` downloads, deletion, visible
  loading/errors, and three metadata-only presentation tools on the existing
  confirmation-gated local FastMCP facade.
- Verified a real three-slide Gemma deck through direct API creation, native
  chart/table/notes package inspection, selected-slide revision with exact
  sibling preservation, stale-base HTTP 409, and a final live Chromium
  revision/navigation/download workflow with no blocking browser errors.
- Verified 18 focused backend tests with one renderer-environment skip, the
  native Node renderer test, strict MyPy over 13 changed production files,
  Ruff, the frontend production build, deterministic and live presentation
  Playwright workflows, Compose configuration, migration head
  `20260724_0013`, and all 11 synchronized architecture diagrams.

## 2026-07-24 — Persistent per-slide presentation follow-ups verified

- Associated every presentation feedback revision with its stable selected
  slide ID so one deck can reconstruct independent chronological conversations
  for each slide without duplicating feedback in a second store.
- Added an image-followup-style browser thread showing the user's suggestion,
  in-progress PresentationAgent state, and persisted ready/failed outcome.
  Switching slides changes threads; navigating away and back restores them.
- Direct live API acceptance created ready revision 8 for slide 1 and returned
  its target-slide association. Live Chromium then created revisions 9 and 10
  for slide 2, restored that slide's exact suggestion/outcome after navigation,
  preserved sibling slides, downloaded the ready PPTX, and reported no blocking
  page or Console errors.
- Verified the focused backend test, deterministic and live presentation
  Playwright workflows, frontend production build, strict MyPy, Ruff, clean
  backend/renderer logs, and Alembic head `20260724_0014`.

## 2026-07-24 — Compact presentation planning latency verified

- Replaced full model-authored deck layout JSON with a compact semantic
  `DeckPlan` and deterministic application compiler that owns the theme,
  coordinates, editable objects, and stable slide/element identifiers.
- Limited normal deck planning to 2,048 tokens while retaining the strict
  selected-slide contract and bounded correction path for feedback revisions.
- Corrected OOXML native-text inspection to recognize PowerPoint
  `p:txBody` elements and added a regression test for that namespace boundary.
- The unchanged `create a presentation on horses, 6 slides` request improved
  from a roughly 200-second malformed-output HTTP 503 to HTTP 201 in 28.67
  seconds direct and 37.98 seconds in final-source Chromium. The retained
  116,620-byte PPTX
  has six slides, 42 editable text bodies, 72 shapes, six notes slides, and
  passed the PptxGenJS plus LibreOffice path.
- Verified 452 backend tests, the focused nine-test presentation suite, the
  native Node renderer test, deterministic presentation Playwright, the
  frontend production build, repository-wide Ruff/Black, strict MyPy over 135
  source files, Compose configuration, migration head `20260724_0014`, and all
  11 synchronized architecture views.

## 2026-07-26 — Exact model-call provenance documented

- Audited the current implementation and configuration after the latest Claude
  Code changes, then named the exact model at every model-backed boundary in the
  full-system and detailed subsystem architecture views.
- Added a per-stage call map covering local Gemma text/vision calls, LM Studio
  text embeddings, in-process vision embeddings, ComfyUI/HiDream raster
  generation, and the conditional Google-grounded Gemini worker. The diagrams
  now distinguish unconditional, conditional, and disabled-by-default calls and
  make clear that the frontend does not call models directly.
- Corrected stale diagram labels from Gemini 2.5 to configured
  `gemini-3.6-flash`, from HiDream-I1 to the configured HiDream-O1 checkpoint,
  and from generic Gemma/Nomic names to their configured identifiers.
- Regenerated all 11 SVGs and the published architecture page, visually
  inspected the final full-system render, passed the synchronized-diagram check,
  passed all six architecture-candidate tests, passed the focused presentation
  service regressions, and completed the frontend production build.

## 2026-07-26 — Durable presentation subagent and foreground chat verified

- Moved presentation creation off the HTTP request path into user-scoped
  PostgreSQL jobs claimed by a standalone leased worker. The worker invokes the
  focused `PresentationAgent` LangGraph, checkpoints each progressive draft,
  reconciles terminal revisions after worker loss, and supports reconnectable
  status plus cooperative cancellation.
- Split deck generation into one compact Gemma outline followed by one bounded
  slide-content microtask per slide. A Redis execution gate gives waiting chat
  priority between those background calls without putting prompts, answers, or
  user content in Redis.
- Updated the presentation UI to retain the active job across navigation and
  reload, show background-agent progress, allow chat while work continues,
  render persisted draft slides, cancel the job, and hydrate the ready deck.
  The local FastMCP create tool now returns the same durable job handle.
- Live Chromium queued a real two-slide deck, switched to Conversations,
  completed a unique Gemma response while the deck was still running, returned
  to Presentations, observed terminal ready state, and exposed the validated
  downloadable PPTX with no required Network, Console, or page errors.
- Verified migration head `20260726_0015`, five recent exact-count jobs ready in
  one attempt, 45 focused backend tests, Ruff, Black, the frontend production
  build, two deterministic presentation browser tests, the live browser
  concurrency workflow, clean recent backend/worker logs, and all 11
  synchronized architecture diagrams.

## 2026-07-26 — Hybrid supervisor and qualified model roles verified

- Added a typed `MainSupervisorAgent` LangGraph step before ordinary chat
  retrieval. Its bounded registered policy delegates explicit presentation
  creation to the durable `PresentationAgent` worker and leaves other turns on
  the existing assistant/MCP path; it has no service, persistence, permission,
  or invocation authority.
- Added independent main, presentation, and diagram model endpoints,
  identifiers, and reasoning settings with compatibility fallbacks. Compose
  forwards them to the backend, presentation worker, and local capability
  sidecar.
- Added visible `agent_started` and `agent_finished` chat events carrying the
  exact specialist/model/job state, plus deterministic and live Chromium
  coverage for the handoff and continued foreground chat.
- Added a repeatable sequential local-model qualification CLI. Qwen 3.5 9B
  passed all bounded supervisor/tool cases and real ordinary-chat and diagram
  paths, so it is the current main/tool-selection and diagram model. Gemma 4
  12B remains the presentation specialist because Qwen failed the actual
  worker's strict progressive slide contract after its correction budget,
  despite passing one smaller harness run.
- Final direct chat reconstructed exact `final source verified` content and
  terminated with `done`. Direct presentation delegation queued in 53 ms before
  the final mechanical format/type pass; the rebuilt final-source Chromium path
  repeated the same agent lifecycle and produced an exact two-slide,
  68,243-byte editable PPTX through Gemma and PptxGenJS/LibreOffice in one
  attempt. The delegated presentation plus parallel-chat workflow passed in
  33.0 seconds with no required Console, Network, or page errors.
- Verified 56 focused backend tests, Ruff, Black, strict MyPy on the changed
  orchestration path, the frontend production build, the deterministic
  delegation browser test, the live browser workflow, clean recent runtime
  logs, all 11 synchronized architecture diagrams, and visual inspection of the
  full-system, chat, and presentation renders.

## 2026-07-26 — Presentation operations and model-role runtime verified

- Qualified the configured Qwen search cascade on all 52 committed routing
  cases. The final live run achieved 1.0 recall and 1.0 specificity with no
  misses or unnecessary searches.
- Stopped a disposable worker during a live leased job and verified canonical
  reclaim on attempt 2, exact four-slide completion, and natural expiry of the
  killed process's Redis model lease. Two simultaneous disposable replicas
  then claimed distinct jobs and each produced one exact two-slide revision on
  attempt 1 without duplicate ownership.
- Verified direct and real-browser cooperative cancellation after worker
  ownership, including persisted terminal state, visible cancellation
  lifecycle, cleared resumable browser state, and scoped cleanup.
- Overlapped a four-client mixed chat/memory workload with two real deck jobs:
  all 51 operations passed, including six terminal chat streams; p95 was
  35.059 seconds, maximum was 67.255 seconds, and both decks reached ready in
  147.881 seconds.
- Found and corrected the live runtime's first failing boundary: a name-only
  Gemma load selected a 256k context and exceeded LM Studio's 29.44 GB resource
  guardrail. Exactly one Qwen and one Gemma instance were reloaded at 8k
  context and parallelism one; isolated Chromium then passed foreground chat
  plus a background two-slide deck in 131.2 seconds and worker-owned
  cancellation in 93.4 seconds.
- Updated stale image browser acceptance to the unified prompt/attachment
  composer, real file chooser, combined image Q&A/refinement field, and unified
  retry control. All 34 deterministic Chromium tests and the frontend
  production build pass.
- Verified 488 backend tests with two intentional skips in the exact runtime
  image, plus 106 focused presentation/supervisor/search tests, Ruff,
  `git diff --check`, and all 11 synchronized architecture diagrams. No
  production component or data-flow relationship changed.

## 2026-07-26 — Published architecture model roles clarified

- Made the full-system, chat-orchestration, and presentation diagrams state
  explicitly that `MainSupervisorAgent` is a deterministic registered-intent
  LangGraph router and makes no LLM call. Qwen remains the main response,
  diagram, and eligible MCP tool-selection model; Gemma remains the focused
  presentation and vision specialist.
- Rebuilt `architecture.html` as a manager-facing entry point containing all
  11 canonical subsystem views instead of the previous seven, with current
  model-role and validation summaries, direct full-size SVG and Mermaid-source
  links, and independent accessible zoom controls.

## 2026-07-27 — Polite generated-image refinements verified

- Corrected the generated-image follow-up classifier so polite edit-shaped
  questions such as `can you make this car red?` use the existing refinement
  API instead of being misrouted to vision Q&A.
- Kept ordinary questions on the grounded vision path and added deterministic
  browser coverage for both decisions, linked revision rendering, exact
  feedback submission, and clean browser state.
- Verified the user's exact prompt in live Chromium against the existing car
  artifact: the refinement returned HTTP 201, persisted parent/feedback
  lineage, rendered a ready 2048x2048 HiDream revision, cleared loading, and
  produced no failed required requests, Console errors, or page errors. Visual
  inspection confirmed that the regenerated car is red.
- All eight image-focused deterministic Chromium tests and the frontend
  production build pass.

## 2026-07-27 — Visual memory/editing target and in-place revision UI verified

- Accepted ADR 0007 for non-blocking generated-image observation, append-only
  typed visual semantics, handle-based picture memory, calibrated reference
  resolution, source-aware local editing, post-edit verification, immutable
  lineage, and derived-data lifecycle.
- Added a separately labelled planned visual-memory/editing target view without
  presenting it as current functionality. Updated the current visual-artifact
  view with the implemented prompt-refinement and active-revision relationships;
  all 12 Mermaid/SVG pairs and the manager architecture page are synchronized.
- Changed successful refinement presentation so the linked child replaces its
  parent in the active image card while persisted lineage retains revision
  history. The deterministic real-browser path confirms one visible card,
  refreshed child bytes, exact feedback, no vision call, and no blocking
  browser errors.
- All eight image-focused deterministic Chromium tests and the frontend
  production build pass. Accurate source-conditioned editing is not claimed by
  this entry.

## 2026-07-27 — Fast source-aware FLUX image editing verified

- Replaced prompt-only HiDream refinement with the official-style local
  FLUX.2 Klein 4B Distilled FP8 single-reference ComfyUI workflow using the
  Qwen 3 4B encoder, FLUX.2 VAE, and four sampling steps.
- Removed the superseded Qwen-Image-Edit wiring and the experimental SAM
  recolor path after live evidence showed that SAM tinted windows, wheels,
  grille, and plate without a latency benefit. Removed the three unused Qwen
  edit assets from the local ComfyUI installation, reclaiming 30,172,239,743
  bytes while retaining the Qwen 3 encoder required by FLUX.
- Verified localized color/material, object addition, and exact plate-text
  edits against the same owned car source. Provider time ranged from 4.2 to
  10.9 seconds; every child retained immutable parent, source-hash, feedback,
  model, seed, step, and latency provenance.
- Verified a real Chromium generation/edit/vision workflow with visible
  refinement progress, exactly one active replacement card, reload
  persistence, clean required Network/Console/page state, and scoped cleanup.
  The browser edit preserved the blue seahorse and scene while changing only
  the copper sphere to polished gold.
- Passed 17 focused backend tests, all 35 deterministic Chromium tests, and the
  TypeScript/Vite production build. Full backend collection remains
  unavailable in the present host environments because their declared test
  dependencies are incomplete.

## 2026-07-27 — FLUX slide and uploaded-image refinement verified

- Generalized the owned-source refinement boundary so both generated and
  uploaded images use the qualified four-step FLUX.2 Klein editor, immutable
  parent/child lineage, and per-revision visual embeddings.
- Made `PresentationImageService` inspect the selected slide: HiDream creates
  its first image, while later image feedback refines the attached source
  artifact with FLUX and replaces its UUID in a new editable deck revision.
- Updated the chat and presentation interfaces with explicit model/action
  states, in-place child replacement, visible failures, and image-feedback
  controls that require a non-empty edit when a slide image already exists.
- Verified direct upload/Gemma/FLUX APIs and PostgreSQL embeddings; real
  Chromium upload/refine/reload and background deck/HiDream/FLUX/PPTX paths;
  62 related backend tests; deterministic presentation and upload-refinement
  browser suites; and the TypeScript/Vite production build.

## 2026-07-28 — Default presentation imagery verified

- Extended the typed presentation plan with bounded visual briefs and
  priorities while keeping provider execution, coordinates, persistence, and
  revision promotion under deterministic application authority.
- Made the durable presentation worker automatically generate at most the two
  highest-priority applicable HiDream visuals, persist them as owned embedded
  artifacts, and checkpoint each enriched deck into reconnectable browser
  progress. Image-provider failure retains a promotable editable text deck.
- Corrected the worker's Compose boundary so its ComfyUI calls use
  `host.docker.internal:8188`, and made progressive previews fetch private
  image bytes instead of displaying artifact placeholders.
- Verified a real two-slide direct job with two default images and an
  11,185,081-byte editable LibreOffice-validated PPTX. A final 155.5-second
  Chromium path verified concurrent foreground chat, default images, in-place
  FLUX feedback, lineage, download, cleanup, and clean Console/page/required
  Network state. Nineteen focused backend tests, two deterministic presentation
  browser tests, Ruff, and the production frontend build passed.

## 2026-07-28 — Failed presentation cleanup verified

- Replaced indistinguishable pending `Untitled presentation` names with a
  bounded, whitespace-normalized form of the submitted brief; a successful
  deck still promotes its model-generated title.
- Added latest-revision lifecycle metadata to list summaries, explicit
  `Failed · no completed slides` copy and terminal-failure explanation for
  empty records, visible text delete controls on every library row, and a
  confirmed `Clear failed (N)` action that excludes ready and pending decks.
- Verified a real isolated queue/cancel/open/delete lifecycle in Chromium
  against the rebuilt API and PostgreSQL: the useful title and failed state
  rendered, DELETE returned 204, the row disappeared, the detail endpoint
  returned 404, and Console/page errors were empty. Three deterministic
  presentation browser tests, ten focused backend tests, and the frontend
  production build passed.

## 2026-07-28 — Reconnectable presentation progress verified

- Added an accessible stage-weighted PowerPoint completion bar that appears
  before the first draft and advances from persisted outline and slide work
  through selected visual generation and render/validation.
- Exposed the configured automatic-image budget on durable job responses so
  reloads and view changes reconstruct progress without a volatile timer or
  invented wall-clock estimate.
- Kept Gemma planning and HiDream execution serial on the current shared RTX
  5080, where both qualified provider paths use concurrency one; safe pipeline
  overlap remains planned behind separate capacity.
- Verified the exact 8%, 37%, 65%, and 92% transitions in deterministic
  Chromium. A real isolated job returned the progress contract, persisted one
  Gemma slide and one HiDream image, reconnected in Chromium at the visual
  stage, reached a ready editable deck, cleared its loading/job state, and was
  cleaned up. Nineteen focused backend tests and the frontend production build
  passed.

## 2026-07-30 — Engineering architecture views simplified

- Reworked all twelve canonical Mermaid views as concise orientation maps with
  one primary engineering question, short labels, shared service boundaries,
  and model names only at actual model-call points.
- Restored the explicit implemented memory taxonomy after visual review:
  short-term LLM context, session working memory, and semantic cache; plus
  long-term procedural/workflow, toolbox, entity, knowledge, persona,
  semantic, episodic, summary, and conversation memory.
- Replaced dense component-to-store and component-to-provider meshes in the
  full-system, runtime, memory, presentation, visual-artifact, and frontend
  views, and changed the search, visual-memory target, and architecture
  maintenance views to readable top-to-bottom flows.
- Added a durable readability contract to the diagram catalog and development
  guide, shortened every published-page description, and clarified that exact
  endpoints, schemas, configuration, and uncommon branches belong in prose.
- Regenerated all twelve SVGs and the published architecture page. The
  synchronization check passed; Chromium found twelve non-empty views and
  twelve canonical-source links with no Console or page errors; every view was
  visually inspected; both architecture scripts passed syntax checks; and the
  TypeScript/Vite production build passed with only the existing chunk-size
  advisory.

## 2026-07-30 — Bounded RTX 5080 presentation profile verified

- Reproduced the live deck/chat workflow with Qwen and Gemma warm at 8k context
  and parallel one. Two 2048px default images produced a 423-second job; two
  1024px images still produced a 367-second job because shared-VRAM model
  swapping, rather than pixel count alone, dominated the first image.
- Set the single-GPU default to one automatic 1024px hero image while retaining
  configurable limits and on-demand per-slide generation/refinement. The exact
  live Chromium workflow then passed in 4.5 minutes with foreground chat,
  default HiDream imagery, in-place FLUX refinement, editable PPTX download,
  terminal loading cleanup, clean required Network/Console state, and scoped
  cleanup.
- Confirmed that LM Studio's REST reload does not reproduce the qualified
  workstation profile: a probe changed Gemma from parallel one to four and
  nearly exhausted VRAM. Restored the exact CLI profile and left automatic
  model transitions behind the planned capacity-aware resource manager.
- Forty-four presentation/chat backend tests, three deterministic presentation
  browser tests, and the TypeScript/Vite production build passed.

## 2026-07-31 — Provider-neutral inference boundary verified

- Replaced dependency assembly's concrete LM Studio construction with
  fail-closed provider-neutral factories for text generation/tool calls,
  vision, and embeddings. Main, presentation, diagram, vision, and embedding
  roles now independently select an adapter and endpoint while preserving
  compatibility aliases and the qualified LM Studio Qwen/Gemma/Nomic profile.
- Kept model discovery, loading, unloading, context/KV-cache configuration,
  GPU offload, residency verification, and restoration outside the inference
  boundary for a future deterministic resource manager.
- The rebuilt current-source backend emitted `start`, 17 deltas, and terminal
  `done` for a direct unique-marker request, persisted and read back the turn,
  logged successful embedding/classifier/main calls, and cleaned the scoped
  user. Gemma separately returned exact buffered output through the
  presentation role.
- Live Chromium streamed a non-empty configured-provider response, cleared
  loading/composer state, restored the exact rendered response after view
  navigation, observed successful required requests, and reported no blocking
  Console/page errors. Thirty-eight focused backend tests, Ruff, Black, MyPy,
  the frontend build, Compose resolution, and twelve synchronized architecture
  diagrams passed. After selecting the workspace `.venv` and restoring the
  PostgreSQL container, dependency integrity and the unchanged complete
  backend suite passed with 499 tests, including Google ADK, OpenTelemetry,
  ONNX Runtime, and database integration coverage.

## 2026-07-31 — Provider-neutral inference benchmark verified

- Added a sanitized operational benchmark over the provider-neutral text,
  native-tool, presentation, embedding, and vision contracts, with explicit
  thresholds and automation-friendly pass/fail exit status.
- Recorded adapter/runtime/model identity and non-identifying RTX 5080 host
  facts without retaining prompts, model output, fixture bytes, tool arguments,
  credentials, or user data.
- Three sequential LM Studio runs with the qualified Qwen/Gemma/Nomic roles
  passed all five checks. Main TTFT was 9.790-10.900 seconds, complete main
  streaming was 10.902-11.991 seconds with terminal completion, and the tool,
  presentation, embedding, and fixed-fixture vision checks all passed their
  correctness and latency limits.

## 2026-07-31 — Default inference runtime migrated to vLLM

- Replaced the externally managed LM Studio deployment with pinned
  `vllm-main` and `vllm-embedding` Compose services. Qwen 3.5 4B now serves
  main, tool, diagram, presentation, architecture-candidate, and vision roles;
  Nomic remains the 768-dimensional text embedder.
- Encoded the RTX 5080 startup requirement that Qwen reach health before Nomic,
  then ComfyUI, after concurrent cold initialization reproduced a negative
  KV-cache boundary. Persisted model and compile caches live on `E:`.
- Tightened the presentation model contract to forbid invented `optional_`
  field names and normalize explicit null optional notes. Three consecutive
  real queued presentation jobs then reached `ready` with exact slide counts.
- Verified provider-level streaming, native tools, structured output,
  embeddings, and vision; exact direct AniOS SSE chat; real browser response
  rendering/restoration; a 5.47 MB owning-API vision upload; and a real 2048px
  ComfyUI generation while both vLLM services remained healthy.
- The complete backend suite passed 504 tests, all 36 deterministic browser
  tests passed, the live configured-provider browser test passed against final
  rebuilt images, Ruff and full-project Black passed, and the frontend
  production build passed. All 12 diagram pairs and the published architecture
  page were regenerated, synchronized, and visually reviewed. Full MyPy
  retains two pre-existing `visual_mcp.py` call-site errors and is not recorded
  as passing.

## 2026-07-31 — FP8 inference profile and schema-constrained model boundaries

- Quantized `vllm-main` to FP8 with an FP8 KV cache on the RTX 5080's native
  Blackwell tensor cores (vLLM selected `CutlassFP8ScaledMMLinearKernel`).
  Resident weights fell from 8.61 GiB to 5.09 GiB, cached tokens rose from
  45,428 to 64,046, the qualified context doubled to 16,384, and free GPU memory
  with both services resident rose from 1,860 MiB to 6,588 MiB for host ComfyUI.
- Sized the embedding service to its measured 0.26 GiB of weights, releasing
  roughly 2 GiB that the previous 0.15 utilization reserved and never used.
- Sent JSON Schemas on the boundaries whose replies are parsed as data, so the
  runtime decodes them as grammars. The presentation schema is derived from the
  Pydantic model that validates the reply, and an explicitly requested slide
  count compiles into `minItems`/`maxItems` instead of a validate-and-re-prompt
  cycle. A prompt explicitly demanding `optional_` prefixes and null notes
  produced neither, and a real three-slide job reached `ready` on attempt 1.
- Fixed nondeterministic search routing: at the runtime's default sampling one
  freshness question answered both `YES` and `NO` across identical calls.
  Classifiers now decode greedily and scored 16/16 on a labelled set under FP8.
- Migrated the working `.env`, which still pointed every host-run tool at LM
  Studio on `127.0.0.1:1234` with Gemma models; the benchmark had been failing
  5/5 against a model the runtime does not serve.
- Restored the full MyPy gate by supplying the missing `edit_provider` argument
  at both `visual_mcp.py` call sites.
- Benchmark passed 5/5 on FP8 and improved every latency against the BF16
  baseline: main TTFT 0.260 s to 0.160 s, total 1.653 s to 1.173 s, 27.821 to
  39.222 normalized estimated tokens/s, native tool 0.439 s to 0.316 s, and the
  embedding batch 0.065 s to 0.025 s. Real SSE chat returned exact text and
  terminal `done`. Backend suite 506 passed; Ruff, Black, and full-project MyPy
  across 152 source files passed.
- Repointed `test_vision_embedding_alignment` at the embedding service. It had
  requested embeddings from `LLM_BASE_URL`, which under split vLLM services is
  the generation endpoint and returns 404, so the cross-modal ordering
  assertions had been skipping silently rather than running.

## 2026-07-31 — Image-wait feedback, composer clearing, and a GPU contention finding

- Cleared the composer as soon as a send is accepted. `setInput('')` previously
  ran only after the whole response finished, so submitted text stayed in the
  box for the entire stream while also appearing in the transcript. The text is
  restored on failure so the existing Retry action still has something to send.
- Replaced the single pulsing line shown during image generation with a
  Genmoji-style conjuring tile: a square placeholder in the accent hues with a
  sweeping highlight, holding the space the image will occupy so the transcript
  does not reflow on arrival. It honours `prefers-reduced-motion`, and the exact
  `Generating image...` status text is preserved for assistive technology.
- Established that image latency on this workstation is dominated by GPU
  contention, not by sampler settings. At a fixed 2048x2048 the same prompt took
  17.7 s at 28 steps but 312 s at 6 steps and 840 s at 16 steps, tracking
  ComfyUI's available VRAM (7.25 GiB with vLLM stopped, 1.46 GiB while
  thrashing) rather than the step count. HiDream needs about 10 GiB and vLLM
  pins about 9.9 GiB on a 16.3 GiB card, so the diffusion runtime streams
  weights from host RAM whenever both are resident.
- Added a tested GPU handoff that sleeps local inference for the duration of one
  image job. `POST /sleep` is verified to return 5.4 GiB, but `POST /wake_up`
  fails on vLLM 0.23.0 when weights were quantized with `--quantization fp8`
  (`'list' object has no attribute 'zero_'`) and leaves the engine permanently
  asleep. The handoff therefore ships behind `GPU_HANDOFF_ENABLED=false` with
  sleep mode absent from Compose, pending a pre-quantized FP8 checkpoint or a
  fixed vLLM.
- Reverted a 0.45 GPU-memory-utilization attempt. The value is a fraction of
  total VRAM, so once ComfyUI holds its weights vLLM cannot reach its own share
  and fails startup with `No available memory for the cache blocks`.
- Stopped caching the routing-classifier inference client. One shared instance
  serialized every concurrent chat behind another chat's classifier call,
  because a provider guards its own requests with an internal lock.

## 2026-07-31 — Pre-quantized FP8 checkpoint and a measured verdict on GPU handoff

- Replaced on-the-fly `--quantization fp8` with the pre-quantized
  `RedHatAI/Qwen3.5-4B-FP8-dynamic` checkpoint (compressed-tensors, revision
  pinned). vLLM selects `CompressedTensorsW8A8Fp8` on the same native Blackwell
  kernel, the vision tower is retained, and the benchmark passes 5/5 warm:
  TTFT 0.169 s, 35.187 normalized estimated tokens/s, native tool 0.394 s,
  presentation structured output 0.211 s, embeddings 0.056 s, vision 0.139 s.
- Isolated the sleep/wake failure to the **KV cache dtype**, not FP8 weights.
  With `--kv-cache-dtype fp8`, waking fails with `'list' object has no attribute
  'zero_'` and strands the engine asleep; with the default dtype, two sleep/wake
  cycles succeed and inference is correct after each. Returning the KV cache to
  the default still raised cached tokens from 64,046 to 93,992, because the
  pre-quantized weights leave more room than the online quantizer did.
- Left `GPU_HANDOFF_ENABLED` off after measuring it. The handoff works, but a
  sleep/reload round trip per image cost more than the contention it removed:
  47/64/42 s with it against 37/35 s without. ComfyUI already manages its own
  residency. The implementation and its tests stay for a future model that makes
  sharing the card genuinely impossible.

## 2026-08-01 — Ambient discovery stage 1: interest and locality profile

- Added user-scoped interests and localities behind `/api/v1/discovery/{user_id}`
  with create/update, read, and scoped delete, plus migration `20260801_0016`.
  This is the profile a scheduled discovery run will score candidates against,
  and the first time AniOS has any concept of where the user lives.
- Sealed every label with `EncryptedText` and identified it by a SHA-256 digest
  of its normalized form. The sealed type documents that it cannot back a unique
  constraint, since each value is encrypted with a fresh nonce, so the digest
  carries identity while the readable copy stays encrypted at rest.
- Bounded the profile at 50 interests and 5 localities because every label is
  eligible to enter a chat prompt, and validated interest provenance against an
  allowed set so an inferred value cannot be stored as a user-stated one.
- Omitted home coordinates deliberately. They would be the most sensitive value
  the application holds and nothing consumes them yet; a place name and radius
  are enough until a source requires more.
- Wired the profile into ordinary chat context. A live turn answered with the
  recorded interests and city from the profile alone.
- Fixed two defects found by live verification rather than by the unit tests:
  the API serialized `slots=True` dataclasses with `vars()`, which has no
  `__dict__` and returned 500; and re-saving a place without the primary flag
  silently demoted it, leaving discovery runs with no default locality. Both now
  have regression coverage, including a router-level round trip.
- Backend suite 522 passed; Ruff, Black, and full-project MyPy across 160 source
  files passed.

## 2026-08-01 — Ambient discovery stage 2: structured schedule sources

- Added a provider-neutral `EventSource` contract returning typed events with a
  stable per-source identity, start, place, and link, plus iCalendar and
  RSS/Atom adapters. Discovery reads structured listings rather than searching,
  which keeps the loop inside the free tiers and yields parseable records
  instead of prose a model would have to interpret.
- Parsed both formats with the standard library. Only a few properties are
  needed, their grammar is small and stable, and keeping the parsing local means
  every bound and sanitization step is visible at the boundary where untrusted
  feed text enters rather than buried in a dependency.
- Treated feeds as hostile input: control characters stripped, text bounded,
  non-web URL schemes dropped so `javascript:` or `file:` targets cannot reach a
  notification, 200 events per source, and response bodies abandoned mid-stream
  past 5 MB rather than after they are already held.
- Added `RequestBudget`, which fixes how many outbound requests one scheduled
  run may make. The free-tier claim is only checkable if that number is decided
  in advance rather than emerging from how many sources happen to be configured.
- Made RSS honest about dates. A feed item states when it was published, not
  when the happening occurs, so items carry no start time unless the publisher
  supplies an explicit event date. A live check returned 15 real items, all
  correctly unschedulable. Inventing a start from `pubDate` would produce
  calendar entries that are confidently wrong.
- Live-verified both adapters against real public feeds within a 2-request
  budget: 42 typed calendar events with correct zone-aware all-day starts, and
  15 RSS items.
- Backend suite 538 passed; Ruff, Black, and full-project MyPy across 165 source
  files passed.

## 2026-08-01 — Ambient discovery stage 3: durable scheduled runs

- Added `discovery_schedules` and `discovery_runs` with migration
  `20260801_0017`. A schedule states one user's cadence; a run is one durable,
  leased instance of a sweep. Leasing reuses the presentation-worker pattern
  rather than introducing a second scheduler: `FOR UPDATE SKIP LOCKED` over
  queued-or-lease-expired rows, a renewable lease, attempt counting,
  cancellation, and terminal states that release the lease.
- Made a slot exactly-once with a unique constraint on `(schedule_id,
  scheduled_for)`. A restarted or duplicated producer cannot queue the same
  sweep twice, which is the difference between a reliable digest and one the
  user receives again after a restart.
- Made delivery exactly-once with a write-once `delivered_at`. A resumed run
  that already delivered declines rather than delivering again, and a run whose
  lease lapses mid-work is reclaimed with its persisted digest intact so the
  second attempt resumes rather than repeats.
- Computed cadence in the user's own timezone, including the daylight-saving
  case where a 9am sweep must remain 9am rather than drift with the old UTC
  offset. The next slot is strictly future, so completing a run at exactly its
  slot time cannot re-arm the same slot and spin.
- Recorded `requests_spent` per run so the free-tier claim is checkable after
  the fact rather than only asserted in advance.
- Corrected `created_at`/`updated_at` on the stage 1 discovery models, which
  were declared naive while their columns were timezone-aware. The mismatch was
  latent until a repository assigned an aware value directly.
- Backend suite 552 passed; Ruff, Black, and full-project MyPy across 168 source
  files passed.

## 2026-08-01 — Recalled images are framed as shared history, not search results

- Fixed a contradictory answer: asked "remember the car we generated?", the
  assistant listed the matching cars and returned their images while stating
  that no car "was generated as a permanent memory for me to remember". The
  images were in the same prompt it was denying.
- Two prompt framings caused it. The recall block read as an external lookup
  ("the application searched the user's stored images", labelled "Matched
  images"), and the training-data staleness caveat was being applied to the
  user's own history. Recall is now framed as a shared record of work the user
  and AniOS did together, with `kind` explaining who made each image and
  `created_at`/`generation_prompt` supplying when and from what, and the
  staleness caveat is explicitly scoped to facts about the world.
- Verified live end to end: after generating a car, the same question now
  answers "Yes, I remember! On July 31st, I generated an image of a red sports
  car on a wet city street at night", with the image matches still displayed.
- Backend suite 554 passed; Ruff, Black, and full-project MyPy across 168 source
  files passed.

## 2026-08-01 — Slide text no longer overflows its boxes

- Fixed clipped and colliding slide text. Slide geometry was fixed regardless of
  content: the title box was 0.65in while a 57-character title wraps to two
  lines at 30pt, and six bullets on a 0.82in pitch ended at 6.60in while the key
  message was pinned at 6.55in, so they always collided. A specification that
  overflows is still a valid specification, so nothing in the pipeline noticed.
- Added `backend/presentations/layout.py`, which estimates rendered line count
  and height from text length, box width, and point size. The compiler now sizes
  the title and purpose to their actual content, stacks bullets at their own
  measured heights, and shrinks the body font within bounds when content is
  dense rather than letting it overflow. Geometry stays deterministic and
  editable rather than depending on renderer autofit.
- Reserved the right column for slides that expect generated imagery. Bullets
  spanned x=1.42 to 11.97 while a slide image occupies x=8.45 to 12.85, so text
  ran underneath any picture the deck produced.
- Verified on a real generated deck: zero elements past the slide edge, zero
  bullet overlaps, and zero key-message collisions.
- Made Enter submit in the presentation panel's slide-feedback and slide-image
  inputs, with Shift+Enter for a newline, matching the chat composer. The
  multi-line deck brief keeps plain Enter, since it asks for several lines.
- Backend suite 563 passed; Ruff, Black, and full-project MyPy across 169 source
  files passed; 36 deterministic browser tests passed.

## 2026-08-01 — Slides can be added to an existing deck

- Added the missing add-slide capability. A deck previously supported only
  `create`, `revise_slide`, and `attach_image`, so asking to "add another slide"
  could only be read as feedback on the slide already selected, and rewrote it.
  `POST /presentations/{user}/{id}/slides` now appends a slide, or inserts one
  directly after a named slide, as an ordinary linked revision.
- Kept accepted work untouched. The model receives only the deck title and each
  existing slide's title and purpose, and writes just the new slide, so an
  addition cannot rewrite slides the user already approved. Element identifiers
  and geometry never reach the model.
- Minted identifiers that cannot collide. Slide identifiers are identities
  rather than positions, so inserting mid-deck does not renumber its neighbours
  and earlier revisions keep resolving.
- Exposed it in the panel as a distinct "Add a slide" control beside slide
  feedback, so the two intentions are not competing for one box.
- Verified live: appending produced revision 2 with `slide_003` and both
  original slides intact; inserting after `slide_001` produced revision 3 with
  order `001, 004, 002, 003`; an unknown `after_slide_id` and another user's
  deck each returned 404, and a stale base revision returned 409.
- Backend suite 566 passed; Ruff, Black, and full-project MyPy across 169 source
  files passed; 36 deterministic browser tests passed.

## 2026-08-01 — Slides take five shapes instead of one

- Added section, statistic, quote, and comparison layouts beside the existing
  bullets layout. Every slide previously had the same shape — title, purpose,
  bullet list, key message — which is the single largest reason a generated deck
  reads as generated, ahead of anything about the prose.
- Let the model choose the shape while deterministic code keeps geometry. The
  layout is an enum in the decoding grammar, so an unknown layout is
  unrepresentable rather than validated after the fact, and a layout missing the
  content it needs degrades to bullets rather than rendering an empty panel.
- Moved the choice to the outline stage after measuring it. Asked per slide, the
  model saw only that slide's title and purpose, which carry no signal about
  what shape the deck needs next, and returned bullets for everything: a deck
  explicitly asking for a statistic, a quote, and a comparison used two layouts.
  Choosing in the outline, with every slide in view, produced four.
- Verified on real decks: a five-slide brief now yields bullets, statistic,
  quote, and comparison slides with zero elements past the slide edge.
- Backend suite 570 passed; Ruff, Black, and full-project MyPy across 169 source
  files passed.

## 2026-08-01 — Charts and tables materialise, and slides carry fewer bullets

- Reached the chart and table capability the deck already had. `ChartElement`
  and `TableElement` existed in the type system and the renderer, but the
  planner could never emit one, so a brief asking for a comparison table got
  prose. Both are now layouts, compiling to native PowerPoint objects whose data
  stays editable.
- Required each layout's fields in the decoding grammar rather than naming them
  in prose. Asked for a chart slide, the model returned layout `chart` with no
  categories and no series, and the compiler correctly degraded it to bullets;
  the outline had chosen correctly, so the gap was the slide pass. Pinning the
  layout with `const` and promoting its fields to `required`, with the null
  branch removed, makes a chart slide without chart data undecodable.
- Kept the compiler's fallback for data that cannot be drawn: a series that does
  not match its categories, or a row that does not match its headers, degrades
  to bullets instead of raising inside the element type and losing the slide.
- Capped bullets at four, down from six, and told the planner that a slide is a
  visual aid whose supporting detail belongs in notes.
- Verified live on one brief: bullets, chart, table, comparison, and statistic
  slides, with a real line chart (120, 185, 290 across 2024-2026), a five-row
  table, two to four bullets per slide, and zero elements past the slide edge.
- Backend suite 575 passed; Ruff, Black, and full-project MyPy across 169 source
  files passed.

## 2026-08-01 — Enter submits in every multi-line box

- Made Enter submit and Shift+Enter start a new line in every text box, not just
  the chat composer. A browser never submits a form from inside a textarea, so
  each box needs this wired explicitly, which is exactly how one box ends up
  behaving unlike the one beside it.
- Wired the create-deck brief, which had deliberately been left on plain Enter
  because it asks for several lines. That reasoning was wrong: Shift+Enter
  already covers multi-line input, and consistency matters more than the guess.
- Also wired the two memory boxes, and extracted the three inline handlers added
  earlier into one shared `submitOnEnter` helper. Every handler now mirrors its
  button's own disabled condition, so the keyboard cannot trigger an action the
  button would refuse, and none of them fire while an input method editor is
  composing, where Enter accepts a candidate rather than sending.
- Added browser coverage for the behaviour: Shift+Enter extends the message
  without sending, Enter sends and empties the composer without a click, and
  Enter on an empty composer sends nothing.
- 37 deterministic browser tests passed; TypeScript and the production build
  passed; backend suite 575 passed.

## 2026-08-01 — Preview text matches the downloaded deck

- Fixed slide text appearing clipped in the browser preview while the downloaded
  PowerPoint was correct. The preview canvas is a `container-type: inline-size`
  element spanning the whole slide, so 100cqw is 13.333 inches and one point is
  7.5/72 cqw, meaning a point size divides by 9.6. The preview divided by 7.2,
  drawing every string a third larger than the compiler had measured, wrapping
  it onto more lines, and clipping it against `overflow-hidden`. PowerPoint was
  never wrong because it renders the real point sizes.
- Matched the preview's line height to the compiler's own assumption. A preview
  that assumes different line spacing than the geometry it draws will disagree
  with that geometry no matter how correct the boxes are.
- 37 deterministic browser tests passed; TypeScript and the production build
  passed.

## 2026-08-01 — Slides can be deleted

- Added the missing delete-slide capability. Revising a slide replaces its
  content and can never remove it, so a deck had no way to drop a slide short of
  deleting the whole presentation. `DELETE /presentations/{user}/{id}/slides/
  {slide_id}` now removes one slide as an ordinary linked revision, with the
  base revision travelling as a query parameter because a DELETE body is not
  reliably transmitted.
- Refused the two cases that would otherwise corrupt a deck: an unknown slide
  returns 404, and deleting the only remaining slide returns 409 rather than
  letting the specification fail its own minimum-length validation and lose the
  presentation.
- Exposed it in the panel as a distinct destructive control, disabled when only
  one slide remains and confirmed before it runs, with the selection moving to
  the first surviving slide afterwards.
- Verified live: deleting a middle slide produced a new ready revision, an
  unknown slide returned 404, and deleting the last slide returned 409 with the
  deck intact at its previous revision.
- Backend suite 575 passed; Ruff, Black, and full-project MyPy across 169 source
  files passed; 37 deterministic browser tests passed.

## 2026-08-01 — Layout fixes, editable data objects, and deck controls on the rail

- Fixed generated images overlapping slide text. Only the bullets layout yielded
  the column a picture occupies, so statistic, quote, comparison, chart, and
  table slides ran their content underneath it. Every layout now derives its
  width from one place, and the heading band narrows too: the purpose line sits
  low enough to reach the picture's top edge, which a horizontal-only check
  would have missed.
- Stopped a revision duplicating or silently deleting a chart or table. Charts
  and tables are compiled from the plan, so the plan owns them and the old one
  is no longer carried over; only the attached image survives, because nothing
  regenerates it. The revision view now reports the slide's current shape and
  its existing chart or table data, and the layout is pinned in the decoding
  grammar rather than requested in prose.
- Naming the layout in prose was not enough twice over: first the model returned
  a chart layout with no chart data, and then, once the data was required, the
  prompt still told it to keep the slide's previous shape while the grammar
  asked for a new one. Prompt and grammar now state the same layout. Verified
  live: adding, editing, and removing a chart through slide feedback each behave
  correctly.
- Moved add and delete onto the thumbnail rail, where deck structure belongs.
  "Revise this slide" had accumulated four controls, two of which changed the
  deck rather than the slide. Deleting is now a hover control on each thumbnail
  and adding is a tile at the end of the rail.
- Pointed an addition's revision at the slide it created, so a new slide has its
  own follow-up history instead of none.
- Backend suite 577 passed; Ruff, Black, and full-project MyPy across 169 source
  files passed; 37 deterministic browser tests passed.

## 2026-08-01 — Slides can be reordered by dragging their thumbnails

- Added deck reordering. `PUT /presentations/{user}/{id}/slides/order` takes the
  complete new order and permutes the deck as an ordinary linked revision. No
  model runs: the caller states the order and the result is deterministic.
- Refused anything that is not a permutation. Sending a short list or a repeated
  slide returns 409 rather than silently dropping or duplicating a slide, which
  is the failure mode a partial order would otherwise cause.
- Matched the PowerPoint interaction in the thumbnail rail: a thumbnail is
  dragged onto the position it should take, the dragged one dims, and a blue
  insertion line marks where it will land.
- Verified live: moving the last slide to the front produced a new ready
  revision with the expected order, while dropping a slide and duplicating one
  were both refused with the deck left intact.
- Backend suite 577 passed; Ruff, Black, and full-project MyPy across 169 source
  files passed; 37 deterministic browser tests passed.

## 2026-08-01 — Reordering reflows the deck, and waits show the conjuring tile

- Made the deck reflow under the cursor while a slide is dragged. Displaced
  thumbnails now slide aside by exactly one thumbnail width, in either
  direction, so the pending position is visible before the pointer is released
  rather than only implied by a line. The line is gone, because the gap opening
  is the clearer signal.
- Fixed the drop landing somewhere other than where it was indicated. The move
  spliced against the original list, so a rightward drag placed the slide after
  the target while the indicator promised before it. The insertion point is now
  stated explicitly, taken from which half of the thumbnail the pointer is over,
  and the slide lands exactly where the reflow showed it would.
- Added grab and grabbing cursors and a short hint, so the rail reads as
  draggable instead of requiring the interaction to be guessed at.
- Extended the conjuring tile beyond chat: slide-image generation now holds the
  square the picture will fill, and deck building shows the same tile during its
  visual stage. Deck building keeps its staged progress bar, which says what is
  happening and is more use than an animation on its own.
- Verified live in both directions: dragging a slide right to sit after another
  and dragging one left to sit before another each produced the expected order.
- Backend suite 577 passed; 37 deterministic browser tests passed; TypeScript
  and the production build passed.

## 2026-08-01 — Dropping a slide commits, and slides insert anywhere

- Fixed reordering not taking effect on release. The drag set no `dataTransfer`
  payload, so the browser treated it as an invalid drag and never fired `drop`:
  the deck reflowed under the cursor and then snapped back. The drag now carries
  its slide id, and the drop is committed from tracked state at the rail rather
  than from whichever element received the event, since the thumbnails have
  moved under the pointer by then.
- Replaced add-slide's "after this slide" reference with a 0-based position.
  A neighbour reference cannot express the very first position, because there is
  no slide before it, so a slide could not be inserted at the front of a deck.
- Added insertion points between thumbnails. Hovering a gap opens it and shows a
  plus; clicking it targets that exact position, so a slide can be added
  anywhere rather than only appended.
- Verified live: inserting at position 0 put the new slide first, inserting at
  position 2 placed it mid-deck, and a position beyond the deck was refused.
- Backend suite 577 passed; 37 deterministic browser tests passed; TypeScript,
  Ruff, Black, MyPy across 169 source files, and the production build passed.

## 2026-08-01 — One way to add a slide, and a way to change your mind

- Removed the separate "Add slide" tile from the end of the rail. With insertion
  points between thumbnails there were two ways to do the same thing, and the
  tile was the one that could only append. A trailing insertion point replaces
  it, so appending still works through the same affordance as inserting.
- Gave the add box a way out. Opening it was one click and closing it was
  impossible without adding a slide. Clicking the same insertion point again
  closes it, Escape dismisses it, and an explicit Cancel sits beside the confirm.
  The brief is cleared on cancel so a discarded thought does not reappear.
- 37 deterministic browser tests passed; backend suite 577 passed; TypeScript and
  the production build passed.

## 2026-08-01 — The slide rail scrolls to its end and its controls can be hit

- Padded the end of the thumbnail rail. The last control sat flush against the
  scroll edge, so the rail looked as though it would not scroll the whole way
  and the final target was partly unreachable.
- Widened the insertion points. A collapsed 6px target is not reliably
  clickable, least of all at the edge of a scrolling strip. The points between
  slides are now 12px and widen on hover, and the trailing one is a permanently
  visible dashed tile, because appending is the common case and it sits exactly
  where the rail runs out.
- 37 deterministic browser tests passed; TypeScript and the production build
  passed.

## 2026-08-01 — One-command startup applies migrations, and the docs catch up

- Made the documented one-command startup actually stand the system up. Compose
  starts services but never applies migrations, and neither did the script, so a
  fresh clone came up against a database with no tables while the README
  presented that command as the whole setup. It now runs Alembic inside the
  backend image, which already carries the driver, and aborts rather than
  starting the application if the migration fails.
- Documented the presentation editing surface and the ambient discovery
  subsystem in the architecture, neither of which had any mention: structural
  slide operations as linked revisions, the seven slide shapes and how the
  decoding grammar enforces them, measured geometry, the sealed interest and
  locality profile, the `EventSource` contract, and durable scheduled runs.
- Updated the presentation diagram to show structural edits and the path that
  needs no model at all.
- Verified the claim rather than asserting it: dropping the schema entirely and
  running the script's migration step produced 25 tables at head
  `20260801_0017`, after which a real chat and a discovery write both succeeded.

## 2026-08-01 — The one-command startup is a Bash script

- Replaced `scripts/start-anios.ps1` with `scripts/start-anios.sh`, preserving
  every ordering constraint: vLLM main before embedding before host ComfyUI,
  migrations before the application, then a bounded wait on backend health.
  PowerShell tied the documented entry point to one shell on one platform, which
  the DGX Spark migration would have broken outright.
- Replaced the PowerShell primitives with ones that need nothing extra
  installed: Bash's own `/dev/tcp` for the port probes rather than netcat, which
  Git Bash does not ship, and `curl` for the warmup calls. Reading
  `COMFYUI_HOST_PATH` stays a literal `grep`, never a shell sourcing, so nothing
  in `.env` can execute.
- Made the closing report stop lying about ComfyUI. It takes well over a minute
  to bind, so on a run that had just launched it the report raced its startup and
  announced image generation as unavailable. The script now waits for the port,
  but only when it was the one that started the process.
- ComfyUI's startup output goes to `comfyui-startup.log` instead of being
  discarded, since a failed launch was otherwise silent.
- Added `.gitattributes` pinning `*.sh` to LF. This repository is developed with
  `core.autocrlf=true`, which would have rewritten the script to CRLF on
  checkout and left every interpreter reading a carriage return as part of the
  shebang path.
- Verified by running it end to end against the live stack: both vLLM services
  and the renderer reported healthy, migrations applied, the frontend started,
  `/health` returned `{"status":"healthy"}`, and ComfyUI — absent at the start of
  the run — was listening on 8188 afterward.

## 2026-08-01 — The database is backed up, and migrations verify safely

- Startup now dumps the database before applying migrations, retaining the ten
  most recent runs below `data/backups/`. The stack had been running unbacked
  since 2026-07-13 with `archive_mode = off`, meaning any loss was permanent.
  A fresh install with no tables is skipped so empty dumps cannot push real ones
  out of the retention window, and a failed dump warns rather than blocking
  startup.
- Added `scripts/verify-migrations.sh`, which builds the schema from nothing
  inside a throwaway database and drops it however the run exits. This replaces
  the practice that caused the loss below: emptying the real database to prove
  migrations work, which passes convincingly because migrations recreate
  structure and never data.
- Documented backup, restore, and safe migration verification in the development
  guide, including the exact restore command.
- Verified all three claims rather than asserting them. The verifier built 25
  tables at head `20260801_0017` against a scratch database and left none behind;
  startup produced a real dump containing 25 `CREATE TABLE` statements; and that
  dump restored into a separate database, reproducing 25 tables at the same head.

### Data loss

Verifying the migration step on 2026-08-01 ran `DROP SCHEMA public CASCADE`
against `anios_db` — the live database rather than a scratch one. All
accumulated conversations, memory, presentations, and artifact records were
destroyed. It is unrecoverable: WAL archiving was off, no dump existed, and the
volume was the original. Two image files survive under `data/artifacts/` with no
rows referencing them. The two changes above exist so this cannot recur.

## 2026-08-01 — Ambient discovery stages 4 and 5

- Built the sweep body. A run now reads the user's configured feeds within its
  request budget, decides what is new, ranks it against approved interests, and
  produces calendar files. Stage 3 had delivered the durable machinery with
  nothing for it to carry.
- Added `discovery_sources` and `discovery_seen_items`, both sealing the
  user-supplied value and identifying it by digest, since `EncryptedText` uses a
  fresh nonce per value and cannot back a unique constraint.
- Novelty runs in two passes ordered by cost: exact source identity, then a
  pgvector near-duplicate check for the same happening relisted under a new
  identifier. Only an announced item suppresses a later one — being ranked out
  once must not permanently mask something the user was never shown — and the
  lookback is bounded so an annual event recurring next year still counts as new.
- Ranking is deterministic and outside the model. A sweep runs unattended, so a
  sampled judgement would make one feed produce different results on different
  days. A candidate scores against its best single interest weighted by strength
  rather than summing across interests, and must clear a floor and a lead-time
  window; an empty digest beats a padded one.
- Calendar files are written against RFC 5545 rather than formatted from a
  template, because the failure mode is silent. Escaping is ordered so
  backslashes are not double-escaped, folding counts octets so a multi-byte
  character is never split at the 75-octet boundary, naive timestamps are
  refused rather than guessed at, and UIDs are stable so re-importing updates an
  appointment instead of duplicating it.
- Made `verify-migrations.sh` mount the working tree's migrations over the
  image's copy. It had verified whatever was baked in at the last build, so a
  migration added since appeared to pass without ever having run — which is
  exactly what happened on the first run of this work.
- Live-verified against a real public calendar feed: 42 events yielded 34 novel
  candidates and 1 selection scoring 1.04 against the stated interest, and an
  immediately repeated sweep over the unchanged feed produced 0 novel and 0
  selected. The selection downloaded as `text/calendar` with correct folding and
  a stable UID. Test data removed afterward.
- 591 backend tests pass, including 30 new ones. Ruff, Black, and full-project
  MyPy across 175 files pass.

## 2026-08-01 — Ambient discovery stage 6: the outbound boundary

- Built the permission model, digest, and channel contract for delivering a
  sweep to a small circle of friends. Outbound sending ships **disabled** behind
  `DISCOVERY_EGRESS_ENABLED`; nothing has been delivered to anyone.
- A subscriber is a revocable permission, not an account: no memory, no profile
  access, no ability to ask the assistant anything. That smallness is what lets
  outbound delivery exist before multi-user identity does.
- Consent is a recorded column and never inferred. An address enrolled without
  it is stored inactive, so the default outcome of a mistake is silence.
  Revocation stops delivery and rotates the token in one operation, so a
  calendar link already handed out stops resolving.
- The digest text is assembled from typed records rather than generated. Feed
  text is untrusted and this string leaves the machine — a model asked to
  summarize hostile input can be steered by it, and the result reaches third
  parties over a channel that cannot be unsent.
- Delivery marks the run delivered *before* calling any channel. Losing a digest
  is recoverable by someone asking; duplicating one is not.
- iMessage goes through a Mac signed into Messages, exposed as an MCP send tool.
  AniOS decides whether to send; that machine does the sending; the tool receives
  an address and a body and nothing else. `shortcuts_pull` is the alternative
  where the recipient's device fetches and AniOS opens no outbound connection.
- Subscription feeds are addressed by an unguessable token and no user path,
  which is how every calendar subscription URL works. Revocation rotates it.
- Live-verified end to end: enrolling without consent gave an undeliverable
  permission and a 404 feed; consenting opened it; the feed served a real
  `text/calendar` document; revoking made the already-shared link 404 again.
  Test data removed. Sending a real iMessage is unverified and needs a Mac.
- 605 backend tests pass. Ruff, Black, and MyPy across 180 files pass.

## 2026-08-01 — The discovery loop actually runs

- Added `discovery-worker` as its own Compose service. Nothing called
  `enqueue_due_runs` or `claim_next`, so every piece of the ambient loop existed
  and none of it ran: the schedule could never fire and a sweep only happened if
  someone posted to `/sweep` by hand. This was the difference between a feature
  and an endpoint.
- The worker both produces and consumes in one process, so there is one thing to
  run and one thing to stop. Producing is safe from any number of processes
  because the slot uniqueness constraint turns a duplicate into a no-op.
- It does not depend on `vllm-main`. A sweep reads feeds and embeddings and never
  the generation model, so waiting on the generation service to be healthy would
  have coupled the loop to something it does not use.
- The digest is persisted before delivery is attempted and delivery is
  write-once, so a crash between the two resumes rather than resends.
- Live-verified against a real public feed with the worker running as a
  container: an armed schedule was picked up unattended, the run reached `ready`
  with 1 candidate for 1 request spent, the digest persisted, the schedule
  re-armed to a strictly future slot, and exactly one run existed afterwards —
  it did not spin. Test data removed.
- 608 backend tests pass, including three new ones covering the scheduled path.
  Ruff, Black, and MyPy across 181 files pass.

## 2026-08-01 — An Agents tab that reports live state

- Added a workspace Agents tab listing the specialized workers and what each is
  currently doing. Two exist today: **Scout**, the ambient discovery loop, and
  **Deck**, the presentation specialist.
- The registry stores nothing. Every field is derived from the tables each agent
  already writes, so the tab cannot drift from reality by being updated in the
  wrong place, and an agent that stops working shows as stalled rather than
  showing whatever it last claimed. Adding an agent means adding a describer.
- Status is five-valued rather than a boolean, because `needs_setup` and `idle`
  are different problems: the most common discovery failure is having no sources
  or interests, and calling that "idle" hides the one action the user can take.
  The detail line names what is missing.
- Times are relative — "in 4 h", "2 d ago" — since an absolute timestamp is the
  wrong unit for "when does this happen next" and makes the reader do
  arithmetic. An agent that has never run says so rather than showing a
  fabricated date.
- Covered by a browser test, because a new tab shipped without one repeats the
  gap that produced four defects in the slide rail. It asserts per-card so a
  status on one agent cannot satisfy an assertion about the other.
- 612 backend tests and 41 deterministic Playwright tests pass. Ruff, Black, and
  MyPy across 183 files pass; the TypeScript build passes.

## 2026-08-01 — Setup assist, and delegation as a registry

- Scout reported "needs setup" because configuring it meant hand-finding `.ics`
  URLs. It now proposes them: search is used **once, at setup, to find sources**
  rather than events. That division preserves both properties the weekly loop
  depends on — search is the only metered component, so it stays off the
  recurring path; and a search snippet cannot supply a zone-aware start, so
  enumerating events that way would mean inferring dates from prose and
  producing calendar entries that are confidently wrong.
- A suggested feed is offered only after AniOS has fetched it, parsed it with
  the same adapter a sweep uses, and seen real typed events come out. Each
  candidate carries sample titles so the user recognizes what they are adding
  rather than trusting a URL.
- Interests are proposed from already-approved memory. Only approved facts are
  read, since building a profile from inferences would produce an agent acting
  on things the user never said, and a proposal is never a fact — accepting one
  is the separate call that records `user_explicit` provenance.
- **Bug found by live verification, not by its test.** A note filed under the
  key `dentist` had prose for a value; the value was correctly rejected as prose
  and the code then fell back to the internal key, proposing "dentist" as an
  interest. The unit test passed because its fixture had no key field. Removed
  the fallback entirely — a record must say what the user likes, not what it is
  filed as — and added the regression test.
- Replaced the supervisor's single hardcoded check with an ordered, listable
  delegation registry. A policy names a capability and grants nothing; the
  conversation service resolves that name against what is actually wired up, so
  a policy for an agent with no handler falls through to the ordinary assistant.
  Adding a specialist is deliberately two steps, because routing to something
  that cannot run is worse than not routing at all.
- 640 backend tests pass. Ruff, Black, and MyPy across 187 files pass.

## 2026-08-01 — Configuring Scout from the Agents tab

- The Scout card now expands into a configuration panel: set the place, add and
  remove interests, add and remove feeds, and run a sweep immediately. Both
  suggestion paths are wired in — feeds found by search and validated by
  fetching, interests proposed from already-approved memory.
- Added "Use my location". The browser's fix is precise enough to identify a
  building, and for a request made at home that is the user's address, so the
  coordinate is rounded to roughly a kilometre before a single lookup names the
  town, and only the town is stored. The panel says so rather than leaving the
  user to assume it.
- Coarsening happens in `resolve_place`, not in an adapter, so no future
  resolver can be written that forgets to do it. An out-of-range coordinate
  never reaches the provider at all.
- Reverse geocoding is a `PlaceResolver` provider contract, matching how every
  other outbound boundary here works — `EventSource`, `SearchProvider`,
  `ImageProvider`. It had been written as a bare HTTP call inside a module,
  which broke that pattern and made the dependency unswappable and always-on.
  It now ships disabled: an unconfigured deployment resolves nothing rather
  than silently reaching a third party.
- 646 backend tests pass; Ruff, Black and MyPy across 188 files pass; the
  TypeScript build passes.

## 2026-08-01 — Fix: the location button could never have worked

- `DISCOVERY_PLACE_RESOLVER` was added to settings but never plumbed through
  Compose to the backend service, which uses an explicit environment allowlist.
  Setting it in `.env` did nothing, so "Use my location" always failed. Added it,
  and the two related values, to the backend service.
- The UI discarded the backend's reason and showed a generic "Could not work out
  where that is." The server had said `Location lookup is not enabled` — the
  exact diagnosis — and the panel threw it away, so the only way to find out was
  to ask. API errors now surface the server's own `detail` when it gave one.
- Verified live end to end: a street-level fix resolves to `New Haven,
  Connecticut`; two different precise coordinates a few hundred metres apart
  resolve identically, which is the observable proof that precision was dropped
  before the request; an out-of-range coordinate is refused before any outbound
  call.

## 2026-08-01 — Saving a place says so, and says which one

- Saving a typed place gave no feedback at all — only the location button set a
  notice — so there was no way to tell whether it had worked. The panel now
  carries a persistent line stating what is actually saved, rather than relying
  on a message the user has to catch, and flags an edited field as an unsaved
  edit so a half-typed change cannot look committed.
- A town name alone is ambiguous: "Arlington" exists in several countries. The
  resolver now reads country separately from region rather than as a fallback,
  which had meant a town with both would silently lose its country while one
  without a state would report the country as its region. Places read as
  "Arlington, Virginia (US)" and store as "Arlington · Virginia, US".
- Verified live against two real coordinates: 38.88/-77.09 resolves to
  `Arlington, Virginia (US)`, and a coordinate in England resolves with `(GB)`,
  so the country is doing real disambiguating work rather than being decoration.

## 2026-08-01 — Search enumerates too, without inventing dates

- Feeds cover institutions and publish nothing for a trail association's group
  hike. `WebEventSource` now queries the configured `SearchProvider` — MCP when
  that is the configured provider — once per interest inside the sweep's request
  budget, so niche interests have coverage at all.
- Revised an earlier judgement: the objection that search would burn the free
  tier assumed continuous enumeration. At a weekly cadence with a bounded query
  count it is a handful of queries a month. The date objection stands and shapes
  the design; the metering one was overweighted.
- A start time is read, never inferred. Explicit forms parse deterministically;
  "this weekend" and "next Saturday" yield no start, because resolving them needs
  a reference point the snippet does not carry. Undated finds appear in a
  separate digest section with a link and no calendar entry.
- Undated finds rank in their own bounded slot so a weaker offer never displaces
  a schedulable one.
- **Two defects found by running it, not by its tests.** Queries used the town
  label alone, so "hiking near Arlington" returned River Legacy Foundation
  (Texas) and Boulder River Trail (Montana); queries now carry the region.
  And the sweep response offered a calendar link for undated finds, which would
  have failed on click; the link is now gated on having a date.
- Verified live for `hiking` in Arlington, Virginia with **no feeds configured at
  all**: one search request produced four finds, all genuinely local —
  arlingtonva.us, Eventbrite VA-Arlington, stayarlington.com, and REI's
  Arlington VA page — one dated with a working calendar link and three as
  mentions.
- 663 backend tests pass; Ruff, Black and MyPy across 189 files pass.

## 2026-08-01 — Calendar links that actually open on a phone

- A digest's whole value is its "Add" link, and the default pointed at
  `localhost`. On the recipient's phone `localhost` is the phone, so every link
  would have failed silently — the class of defect that works perfectly on the
  machine serving it and nowhere else.
- Links are now built from an address other devices can reach. An explicitly
  configured value always wins, since an operator publishing a real hostname must
  not be second-guessed.
- Detection **refuses to answer inside a container**. It would find the
  container's own bridge address, which looks routable and is reachable only
  from the Docker network — a plausible wrong answer is worse than none here,
  because it produces links that fail without explaining why. Observed rather
  than predicted: the first version reported `172.18.0.7`.
- The Scout card states where links point, and when they are unreachable it says
  what to do about it rather than only that something is wrong.
- 668 backend tests pass; Ruff, Black and MyPy across 190 files pass.

## 2026-08-01 — Preview what would be sent, without sending it

- Added a digest preview: the Scout panel and
  `GET /api/v1/discovery/{user_id}/digest/preview` render the exact string a
  channel would receive, from the same code path, and name who would have
  received it. Verifying an outbound feature by triggering it is a bad trade —
  the send cannot be recalled and a wrong digest reaches real people.
- Preview reads what has already been announced rather than sweeping again, so
  looking costs no metered query and marks nothing as seen.
- It reports the three things that decide whether a real send would work:
  whether any subscriber would receive it, whether egress is on, and whether the
  calendar links are reachable from another device.

## 2026-08-01 — A find you can actually decide on

- A recipient was being shown "Nature and History Events – Official Website of
  Arlington County Virginia Government" and a wall of scraped markdown. Nobody
  can judge that. Titles are now cleaned deterministically, and a one-line
  description is written for each selected find.
- This is the one place a model belongs here. What *qualifies* stays
  deterministic — a sweep runs unattended and must not vary by sampling — but
  turning a scraped paragraph into a readable sentence is what a model is for.
  It answers into a decoding grammar with a bounded field, greedily, so the same
  page describes itself identically each sweep.
- No URL survives model output: links come from the typed record, so a page
  cannot put a link of its choosing in front of a recipient. Any failure falls
  back to a first-sentence extract that never invents.
- **Found by running it:** descriptions were applied after ranking but the seen
  store persisted the pre-description candidates, so the work existed only in the
  sweep's return value and every preview showed raw text. The stored payload is
  what later previews, digests, and calendar files are built from, so selections
  are now persisted in their described form.
- Live result, same event before and after:
  `Nature and History Events – Official Website of Arlington County Virginia
  Government` / `## History Hike: Boundary Stones 12 Sep 2026 Local and national
  history meet during…` became `Nature and History Events` / `A local and
  national history hike for participants to explore D.C.'s original boundary
  stones and surveyor stories.` The `.ics` carries the same clean description.
- 680 backend tests pass; Ruff, Black and MyPy across 191 files pass.

## 2026-08-01 — The calendar travels with the message

- Digests now attach one `.ics` carrying every dated find instead of linking to
  one. A link requires AniOS to be reachable from wherever the recipient is; a
  file that arrives with the message does not. This is what makes the feature
  work for someone on mobile data, and it needs no public hostname, no tunnel,
  and no part of AniOS exposed.
- One combined file rather than one per event, so a phone can offer to add them
  together. UIDs are stable, so re-sending updates an entry rather than
  duplicating it.
- When the file is attached the message drops its `Add:` links, because those
  are precisely the links that would fail off the sender's network.
- The channel contract carries an optional attachment, bounded in size, base64
  encoded because the tool boundary is JSON. Undated finds keep their own source
  URL, which is a third-party page and reachable from anywhere.
- 685 backend tests pass; Ruff, Black and MyPy across 191 files pass.

## 2026-08-01 — Scout can be scheduled from the panel

- Added schedule endpoints and a clock control in the Scout panel: cadence, day,
  and hour, stated in the user's own timezone. Without this the worker polled
  forever and found nothing due, so a fully built loop only ever ran when
  someone pressed a button.
- The panel says plainly when nothing is scheduled, rather than looking
  configured while never running.
- Fixed a stale rule in the agent registry: it still demanded a feed before
  Scout could work, which stopped being true when search became a second
  enumerator. A feed is now required only when search cannot enumerate, so a
  user with an interest and a place is not sent hunting for `.ics` URLs they do
  not need. Both branches are covered.
- 686 backend tests and the Agents tab browser test pass; Ruff, Black and MyPy
  across 191 files pass.

## 2026-08-01 — A rehearsal you can run repeatedly

- Added `Try it` to the Scout panel and `commit=false` to the sweep endpoint: the
  whole pipeline runs, nothing is recorded, and novelty is not consulted, so the
  same configuration can be run again and compared.
- This existed because a *real* sweep is useless for judging quality. The
  novelty filter is working correctly when the second run finds nothing, which
  is precisely what stops anyone from tuning interests and seeing the difference.
- Both buttons now show the rendered message rather than counts, so quality is
  judged on the thing a person would actually receive.
- Verified live: two consecutive rehearsals on the same profile returned the same
  three finds, and the seen-item count was 5 before and 5 after, so a rehearsal
  writes nothing. A real sweep following a rehearsal still announces once and
  then nothing, so the rehearsal does not poison the store.

## 2026-08-01 — Telling a happening apart from a page that lists happenings

- The digest was returning trail directories and Meetup landing pages for
  "hiking". An embedding cannot make this call: "Events in Arlington, Virginia |
  Meetup" is a genuinely excellent semantic match for someone interested in local
  events, and it is not something you can go to. The distinction is structural,
  so it is now decided by URL and title signals rather than by similarity.
- Every case in `listing_filter` is a real result from a live sweep, labelled by
  hand. A specific event path (`/event/<slug>`, `/events/<id>`) beats a generic
  title, because the URL is the harder signal to fake.
- **The query was the larger problem, and it was measured rather than guessed.**
  "hiking events near Arlington upcoming" kept **0 of 5** results — that phrasing
  is how a directory page describes itself, so that is what ranks for it. Naming
  the current month instead kept **6 of 9** across hiking, pottery, and jazz, and
  surfaced real happenings: *Tour de Trail: Pentagon Memorial*, *Hand-Built
  Pottery Class*, *Lubber Run Amphitheater*. A date appears on a page about one
  happening and not on a landing page.
- Added guide patterns after "The Complete Guide To Hiking In Northern Virginia"
  reached a live digest; a guide to a category is a directory under another name.
- The Deck card now reports what it is configured to do — read from settings, so
  it cannot claim a behaviour it does not have — and links through to the
  Presentations workspace.
- 716 backend tests and the Agents tab browser test pass.

## 2026-08-01 — Field encryption was never switched on

- Every claim made about interests, localities, and subscriber addresses being
  "sealed at rest" described a capability the deployment did not have.
  `EncryptedText` and `FieldCipher` were correct and wired; `ENCRYPTION_KEY` was
  empty in `.env.example`, absent from `.env`, and **not present in
  `docker-compose.yml` at all** — so setting it would not have reached a
  container either. Found by reading a backup and seeing `Hiking` in plaintext.
- Plumbed the key into every service that reads or writes a sealed column:
  backend, discovery worker, presentation worker. The worker mattered as much as
  the API — one writing plaintext into a column the other reads as sealed is
  worse than neither doing it.
- Enabling it is non-breaking by design and was verified rather than assumed:
  the pre-existing `Hiking` row still reads through the API, while a newly added
  interest is `enc:1:Dq4uVNF…` on disk.
- Added `scripts/backup-db.sh`. Startup takes a backup, but startup can be weeks
  apart and everything added since is unprotected — the only existing dump
  predated the interests it was supposed to protect. It also warns that a dump
  taken with encryption on is only as recoverable as the key.

## 2026-08-02 — Familiarity, scoped to where you are

- Novelty and familiarity are different questions. The seen store answers "have I
  shown you this"; a find can now be dismissed as "I already know this", which
  answers "did you already know it". For someone who has lived somewhere a while
  those diverge, and a digest of trails they walk weekly is one they stop reading.
- Dismissal suppresses by embedding proximity, not identity: marking one trail
  directory as known is only useful if the next four like it also go.
- **Scoped per locality, which is the point.** Someone who knows every trail in
  Arlington knows none in Denver, so the same happening is noise at home and a
  find while travelling. A global list would make the agent progressively useless
  exactly when travel makes it most valuable.
- **Found by running it:** the first dismissal silently did nothing. The user
  dismisses the title they were *shown* — already stripped of its CMS site name —
  while a candidate still carries the raw one from search. Both sides now clean
  the title before comparing.
- Verified live end to end: dismissing "Trails" in Arlington removed it from the
  next rehearsal there; switching the primary place to Denver reported 0 known
  and returned three unsuppressed finds including trail runs; switching back
  showed the Arlington dismissal still in force.
- 724 backend tests pass; migrations build to 29 tables at head `20260802_0020`.

## 2026-08-02 — Unified Scout memory and profile controls

- Closed the discovery privacy gap: personal-memory export and delete-all now
  cover interests, localities, sources, seen items, subscribers, familiar
  items, schedules, and runs. Tests seed every table, verify export/deletion
  counts, assert zero owned rows remain, and preserve another user's rows.
- Made approved home and interests versioned memory facts with a bidirectional
  typed Scout projection. Explicit chat statements produce approval cards;
  panel edits record the same facts; removal clears the owning fact history.
- Added user-facing recovery and ranking controls: dismissed familiar items can
  be undone, interest importance is editable from Low through High, and travel
  mode temporarily changes Scout's active locality without changing home. A
  partial unique index enforces one active travel destination per user.
- Verified the rebuilt source tree through 766 backend tests, 42 deterministic
  Chromium tests, a production frontend build, Ruff, Black, MyPy, Alembic head
  `20260802_0022`, and a real Chromium workflow against the API and PostgreSQL.
  The live path persisted and reloaded home/interests, changed strength, started
  and stopped travel, undid a dismissal, inspected memory, and deleted the
  isolated user without browser or backend errors.

## 2026-08-02 — Invite-only password authentication verified

- Added Argon2id invite accounts with login names independent of stable owned
  user IDs, digest-only revocable browser sessions, logout/password-reset/
  disable revocation, unsafe-request Origin checks, and retained scoped bearer
  compatibility for automation.
- Gated the React workspace on a server-derived session, removed browser-driven
  identity switching, scoped retained conversation IDs by authenticated owner,
  and added visible login/logout behavior.
- Added additive migrations through `20260802_0024`, a non-destructive operator
  CLI with hidden password prompts, safe backup/migration/move guidance, and a
  dedicated authentication architecture view.
- Verified 768 backend tests, 43 deterministic Chromium tests, the production
  build, static/type gates, clean scratch and real migrations, direct live
  ownership/revocation behavior, and a real alias-login Chromium chat plus
  cross-owner isolation workflow.

## 2026-08-02 — Invited browser profiles and same-origin gateway verified

- Added expiring one-time registration invitations with digest-only storage,
  atomic account/session creation, browser username/password enrollment, and
  shared Redis attempt limits. Unrestricted public signup remains unavailable.
- Added a loopback-only Nginx gateway that serves the production React build and
  proxies API, SSE, uploads, and downloads on one origin; production clients no
  longer call their own localhost.
- Live Chromium created two invited profiles through the gateway, persisted a
  semantic marker for one through the real embedding service, proved the other
  profile received 403 and no semantic result, then logged back into the owner
  and recalled the marker. Test-owned rows were cleaned up afterward.
- Verified migration head `20260802_0025` from an empty scratch database and in
  place after a fresh backup, all 772 backend tests, all 44 deterministic
  Chromium tests, the live two-profile browser path, and the production build.
  Public Tailscale Funnel ingress remains unconfigured and unverified.

## 2026-08-02 — Recorded how sharing between accounts will work

- Added [ADR 0011](adr/0011-sharing-by-copy-on-accept.md). Invited accounts made
  a second person real, and the first thing two people want is to give each
  other something. Sharing will **copy on accept** rather than grant access into
  another owner's store.
- The decision was measured, not preferred: single ownership is load-bearing in
  133 places across the backend, 33 of them in deletion and export alone. A
  grant table consulted by every read means editing all 133, and each one missed
  is a disclosure or an invisible omission — which this project has already done
  once, when discovery escaped the memory subsystem and "forget me" left
  someone's home town and their friends' phone numbers behind.
- From the recipient's side the flow reuses the account-invitation machinery: an
  expiring one-time code, a preview before accepting, and then it is theirs,
  attributed. Accepted items land in ordinary memory and search rather than a
  "shared with me" silo nobody remembers to open.
- Honest limit recorded rather than designed around: acceptance cannot be
  undone by the sharer. A code can be withdrawn before it is used; a recipe
  someone already has is theirs, like a message already delivered.

## 2026-08-02 — An operator boundary, separate from ownership

- Added `is_admin` to accounts, defaulting false. The migration promotes the
  oldest existing account, so an already-deployed instance still has an operator
  after upgrading rather than none.
- `require_admin` answers a different question from `authorize_path_user`.
  Ownership asks "is this your data" — an invited guest's chat, memory, and
  agents are entirely theirs. Administration asks "may you act on the machine",
  which a guest may not: inviting people, enumerating accounts, or changing what
  this machine does on the operator's behalf.
- The refusal deliberately does not distinguish "not an admin" from "no such
  account", so it cannot be used to confirm who exists.
- Added invite management: list with status and who consumed each one, mint with
  a bounded TTL, and revoke. A listing never returns a code — only a digest is
  stored, so one cannot be recovered even by the operator, which is exactly why
  revoking is the recovery for a code sent to the wrong person. An already-used
  invitation refuses revocation, because it is the record of how an account
  exists.
- **Found by running the suite:** the new test module set `AUTH_REQUIRED` through
  the environment at import, which leaked into every other module in the same
  pytest process and broke four unrelated tests. It is now toggled per test and
  restored.
- Verified live through the public HTTPS URL with a real invited guest: `403` on
  every admin route, `200` on their own memory. Test account removed.
- 764 backend tests pass; migrations build 32 tables at head `20260802_0026`.

## 2026-08-02 — The operator surface, visible

- Added an **Operator** view to the workspace: create an invitation with a
  chosen lifetime, see every invitation with its status and who used it, revoke
  an open one, and list accounts.
- The session endpoint now reports `is_admin`, so the workspace can hide what a
  guest cannot use. It is a display hint only — every operator route re-derives
  the answer from the database, so a modified client gains nothing.
- A minted code is shown once with a copy control and says so plainly. It cannot
  be shown again, which is exactly why revoking is the recovery for a code that
  reached the wrong person.
- Verified live over the public HTTPS URL: an operator session reports
  `is_admin: true`, lists invitations, mints a 43-character code, and revokes it
  (`204`). An invited guest was previously verified as `403` on every one of
  those routes while keeping `200` on their own memory. Both temporary accounts
  removed.
- 764 backend tests pass; the TypeScript build passes.

## 2026-08-02 — Who gets messaged, and who decides

- A guest can now subscribe **themselves** to their own agent's digest by
  entering their own iMessage address. An agent that cannot tell its owner
  anything is not an agent, so restricting this entirely was wrong.
- What a guest cannot do is make this machine message an address. The bridge
  sends from the operator's Apple ID, so an iMessage subscription arrives
  **consented by the recipient and unapproved by the operator**, and stays
  undeliverable until the operator approves it. Consent and approval are
  genuinely different permissions and both are now required.
- The operator's view differs by design: a guest sees only their own
  subscription and cannot approve it; the operator sees every subscription with
  who requested it, and the address — which is shown there and nowhere else,
  because approving it is a decision that cannot be made blind.
- An account may hold one subscription. Choosing where your own digest goes is
  reasonable; accumulating destinations is a way to make someone else's Apple ID
  message several people.
- A `shortcuts_pull` subscription needs no approval, because nothing is sent —
  the recipient's own device fetches.
- The operator enrolling an address directly is itself the approval; only
  self-service leaves it pending. That fell out of running the suite, where four
  delivery tests correctly failed against the stricter rule.
- 780 backend tests pass; migrations build 32 tables at head `20260802_0027`.

## 2026-08-03 — Three reported defects fixed: memory capture, empty slides, ungrounded decks

- Explicit "remember this" now reaches memory. Every one of the eight
  extractors was a narrow shape matcher, so an ordinary fact about a person's
  life — "Remember that my dog is called Biscuit." — matched no rule and
  reached no store. A general-fact proposer catches an explicit save request
  and stores the fact, not the instruction wrapping it, as semantic memory. It
  runs after every structured proposer, so a dentist is still an entity and a
  workflow still a procedure, and before the episodic proposer, because an
  explicit request outranks a proactively noticed event. A recall question
  ("do you remember...") is guarded off the save path.
- The assistant no longer claims a save it does not control. Telling the model
  only that it cannot write to memory was not enough: it answered "your
  personal memory has been updated" — passive, true-sounding, and false. The
  proposal is now decided before the answer is generated rather than after, and
  the turn's real save state is stated in the prompt with the sentence to
  write. Verified live: the reply became "I cannot store this myself, just
  approve the save card below".
- A section slide renders its points instead of discarding them. Every slide is
  planned with two to four points and this layout rendered none of them, which
  is how a real five-slide deck came back with three slides holding a title, a
  purpose, and nothing else. The divider keeps its rule and centred title; the
  block is centred as a whole, so a divider carrying no points sits where it
  always did, and the point font is fitted against the space left at the
  highest permitted position so a long title plus four long points cannot push
  the rule off the slide. The statistic, quote, comparison, chart, and table
  layouts already degraded correctly and were unchanged.
- Deck content is grounded in one web search per deck. The per-slide contract
  solicited `statistic_value`, `quote_attribution`, `table_rows`, and
  `chart_series` with nothing behind them. `DeckResearch` now gathers bounded
  public sources at outline time — before layouts are chosen, because that is
  where a slide is told to carry a number — and the same sources are quoted
  into every slide request as untrusted data with the rule that an unsupported
  figure must become a plainer layout instead. The brief is reduced to its
  subject first: sent verbatim, "create a deck about X with a statistic slide,
  4 slides" returned a slideware marketing page, because most of those words
  describe the artifact rather than the subject. Screening, metering, and
  failure behaviour reuse the existing shared gate, the per-account budget, and
  best-effort degradation.
- Measured effect on a real deck, same brief, same model: the ungrounded run
  asserted seven crewed landings, "285-day intervals", a "21-year span", and
  "Apollo 11 December 1969"; the grounded run gave six landings, Apollo 8 in
  December 1968, and correct Apollo 12 and 14 crews. Two errors survived, so
  this reduces invention rather than eliminating it.
- Pinned `mcp<2.0.0`. The range was open at `>=1.0.0`, and 2.0 removes
  `mcp.server.fastmcp`, which every built-in server and the local-capabilities
  sidecar import. An image rebuilt after that release lost web search and both
  stdio MCP servers while the host venv stayed on 1.x and the tests still
  passed — the same rug-pull shape the MCP guidance warns about, arriving
  through a Python dependency instead of a server.
- 869 backend tests pass; Ruff, Black, and MyPy are clean; the frontend builds;
  all 15 architecture diagrams render and check as synchronized.

## 2026-08-03 — Scout: let it look, and stop a trip rewriting where you live

- "Look now" required a configured feed. The runner does not — search
  enumerates events from the place and interests alone, and treats feeds and
  search as independent contributors — so an account with a home, two interests
  and no feeds had the button permanently greyed out. "Try it", the same sweep
  one flag apart, stayed enabled and worked. A rehearsal on that exact account
  returned two real Arlington finds with zero feeds. The hint now names which
  condition is missing rather than listing three.
- Reporting a location no longer says you moved house. "Use my location" wrote
  the *primary* locality, and `add_locality` records the approved memory fact
  behind it, so one press from a hotel rewrote where the user lived, stranded
  the familiarity they had built at home, and left memory asserting the move —
  twice, once they came back and pressed it again. `PUT /current-place` records
  where someone is and never where they live.
- Being away stopped being a mode. It was a switch to remember to turn off, and
  a forgotten one is silent: a weekly digest about a city left in spring still
  looks like a working digest. A reported place that differs from home is
  simply being away, it carries `travel_expires_at` (`DISCOVERY_TRIP_DAYS`,
  default 14), and `active_locality` ignores a lapsed one, so forgetting costs
  a couple of digests instead of every digest from now on.
- Home and current place remain two values, deliberately. Familiarity is scoped
  per locality, so collapsing them would either strand what someone already
  knew at home or teach Scout that everything ordinary where they are visiting
  is familiar. What was redundant was the toggle, not the distinction.
- A coordinate cannot tell visiting from moving, so the panel asks once and
  defaults to visiting; promoting a place to home stays an explicit action. The
  status line states the fact — "Looking around Denver · you live in Arlington"
  — with when it lapses and a way back.
- Migration `20260803_0031` adds the nullable expiry; a destination set before
  it stays open-ended. Verified on a throwaway database (33 tables at head)
  before `anios_db` was touched, and the live profile round-tripped
  Arlington → Denver → Arlington with home and the memory fact unchanged
  throughout.
- 874 backend tests pass; Ruff, Black and MyPy are clean; the frontend builds;
  15 diagrams render and check as synchronized.

## 2026-08-03 — Scout: a dismissal means the thing it names, and findings are readable

- Dismissals are keyed on the happening's own identity (`source_id` +
  `external_id`, the digest novelty already uses) rather than its cleaned
  title. The title path let a real page title collapse to a common word and
  become the suppression key: after dismissing one county's trails page, the
  stored key was `trails`, so any later find whose cleaned title was also
  "Trails" — another county's listing, never shown before — was dropped without
  a trace. Identity digests cannot collide that way, and the rule is uniform
  rather than a special case for titles that look too generic.
- The familiarity radius moved from `0.16` to the near-duplicate bound `0.08`.
  It was chosen to suppress a whole family on the reasoning that the user had
  asked to see less of that kind of thing. They had not: the control says "I
  know <this thing>" and names one item. Its remaining job is narrower and
  real — the same happening carried by a second source has a different
  `external_id` — which is exactly what `0.08` already means elsewhere.
  Measured against the live embedder, the old radius was not in fact hiding
  the trail category (nearest real trail find sat at `0.3156`), so this is a
  correction of intent and of the collision risk, not of an active mass-hide.
- Dismissals made before this change still suppress, through the legacy title
  key, so nothing anyone had already hidden comes back.
- A sweep now reports how many finds it dropped as already known, and the
  dismiss control shows the item's full name instead of truncating it at 26
  characters. A wrong dismissal was previously undiscoverable: the panel lists
  what was dismissed, never what those dismissals removed, and a truncated
  label reads as a category.
- `GET /discovery/{user}/runs` returns recent sweeps and what each one found.
  Every run already persisted its digest and nothing could read it back, so a
  scheduled sweep's recommendations were reachable only through a delivery that
  is still switched off — the one loop that runs unattended was the one loop
  nobody could check. The panel shows the last three sweeps, each find with its
  date, place and link, and states plainly whether it was sent.
- 877 backend tests pass; Ruff, Black and MyPy are clean; the frontend builds.

## 2026-08-03 — Scout's scheduled sweeps could never find anything

- `discovery-worker` had no search configuration. It carried
  `SEARCH_MONTHLY_CREDITS` and `MCP_SERVERS_JSON` — which made search look
  wired up — but not `SEARCH_PROVIDER_NAME`, `SEARCH_API_KEY`, or
  `DISCOVERY_WEB_SEARCH_ENABLED`. `SEARCH_PROVIDER_NAME` defaults to `tavily`
  and the key was absent, so the provider was disabled. For a profile with no
  feeds, that leaves nothing to read: every scheduled sweep returned
  `candidate_count: 0`.
- It was invisible because the same account finds things through the API: the
  backend container has the keys, so "Try it" and "Look now" worked while the
  weekly sweep — the entire point of the agent — quietly found nothing. The
  stored digest of the 2026-08-04 run was
  `{"selected":[],"candidate_count":0,...}`.
- Measured on the live account from inside the worker after the fix: 5
  candidates, 5 novel, 5 selected, including "2026 NOVA Running Club 5K",
  against 0 before. Run as a rehearsal so nothing was recorded.
- This is the environment-allowlist trap the agent instructions already record,
  found a third time. The presence of one `SEARCH_*` key is what made it look
  configured; the check that matters is `printenv` in the container that does
  the work, not the key list in `.env`.
- The findings panel no longer reports "nothing found yet" for a sweep that ran
  and found nothing. Those are different states — one means the feature has not
  started, the other means it is working and empty-handed — and collapsing them
  is what made a broken sweep look like an idle one. It now names the sweep's
  date and, when there is one, the last sweep that did find something.

## 2026-08-03 — Audit: what else the discovery worker was missing

Method worth repeating. Static reachability proved useless — importing any
entrypoint pulls ~145 backend modules through `dependencies.py`, so all three
services look identical. Instrumenting `Settings.__getattribute__` and running a
real sweep gives the settings the *executing path* actually reads: 44 of them,
28 falling back to code defaults inside `discovery-worker`.

- `LLM_BASE_URL` was undeclared, so it defaulted to `http://127.0.0.1:8003` —
  the host's address, which inside the container is nothing. The sweep writes
  each find's description with the model and falls back to a first-sentence
  extract when it cannot, so every scheduled digest silently used the fallback
  and never the model. The failure is invisible by design: falling back is
  correct when the model is genuinely down, so nothing distinguishes "down"
  from "never configured". Now pointed at `vllm-main:8000`; verified the model
  endpoint answers and the sweep produces written descriptions.
- `REDIS_URL` had the same shape of default, resolving to the container itself
  rather than the shared Redis.
- Checked and deliberately not changed: `SEARCH_MIN_SCORE`, `SEARCH_MAX_RESULTS`,
  `SEARCH_MAX_CONTENT_CHARS`, `SEARCH_DEPTH`, `SEARCH_TIMEOUT_SECONDS`. The
  backend does not declare them either, so both sides use identical code
  defaults and there is no divergence to fix. An earlier draft of this change
  declared them with a wrong fallback (1200 against the real default of 2000),
  which would have created the divergence it claimed to prevent.
- The general lesson: the dangerous default is not a missing key, it is a key
  whose default is a loopback address. Those resolve successfully inside a
  container, to the wrong thing.

## 2026-08-03 — Scheduled sweeps can sit at a quarter past

- A schedule's slot was built from the hour alone, so every sweep fired at :00.
  `Cadence` now carries a `minute`, `next_run_at` builds the instant from it,
  and the picker offers quarter hours beside the hour.
- The domain accepts any minute 0–59 while the interface offers only quarters.
  A stricter domain would reject a schedule someone had already set through the
  API, and a 60-item list is a worse way to choose a sweep time than four.
- Migration `20260803_0032` defaults the column to `0` rather than making it
  nullable, so every existing schedule keeps firing at exactly the time it
  fired before. Verified on the live row: `daily 21:00` stayed `21:00`.
- The daylight-saving property is preserved: the instant is still rebuilt from
  local calendar fields, so a 9:15 sweep stays 9:15 across a shift rather than
  drifting by the old offset. The slot also stays strictly future, so a run
  completing exactly on its own slot cannot re-arm it and spin — both covered
  by tests.
- Verified through the API on a disposable account: `hour 9, minute 15` stored
  and `next_run_at` returned `13:15Z`, which is 09:15 America/New_York.
- 881 backend tests pass; Ruff, Black and MyPy clean; gateway rebuilt and the
  served bundle confirmed to contain the picker.

## 2026-08-03 — "Suggest from memory" proposed the user's own name

- `_approved_facts` discarded `fact_key`, so every approved fact reached the
  finder looking alike and any short value became an interest candidate. On the
  live account the only two approved facts are a home locality and a preferred
  name, and both were offered: `arlington, virginia, us` and `ani`. Those two
  facts exist on almost every account, which is what made the feature look like
  it suggested everything in memory.
- The key is now carried, and facts that describe the person rather than what
  they enjoy — `discovery_locality`, `preferred_name`, `response_style`, and
  interests already projected onto the profile — are skipped. Verified against
  the live account: it now proposes nothing, which is correct, because neither
  stored fact is an interest.
- Suggestions also keep their capitalisation. `_normalize` returned the
  casefolded form as the display label, so every suggestion arrived lower case
  while a typed interest kept its capitals — visible on the live profile as
  `Hiking` beside `trail running`. Normalizing decides whether something is
  interest-shaped; it does not decide how it reads, and `label_digest`
  normalizes identity separately, so `Rock Climbing` and `rock climbing` remain
  one interest.
- 885 backend tests pass; Ruff, Black and MyPy clean.

## 2026-08-04 — Scout can surface something you never asked for

- Every ranking path was anchored to a stated interest, so the loop could only
  ever return more of what it already knew about: a meteor shower or a one-night
  exhibit scored near zero against "hiking" and was dropped before anyone saw
  it. It was also never searched for — queries are built one per interest.
- One query per sweep now names no interest, spent first so a tight budget
  buys the query that can return something new. `NotableSelector` picks at most
  two finds that match no interest and are unlike anything the account has been
  shown, under their own heading in the digest and the panel.
- Unlikeness is the distance to the nearest item in the user's own history, not
  to a centroid: the centroid of a varied history resembles nothing, so
  everything looks far from it.
- **The first design was wrong and measurement caught it.** Against the real
  ten-item history a guided night hike scored `0.362` unlike and a hot air
  balloon festival `0.328`, so a bar on unlikeness alone admitted the hiking
  event and rejected the balloon festival — exactly backwards. Distance from
  history is a weak signal on a short history. The criterion that discriminates
  is whether the matcher wanted it, so a candidate scoring at or above the
  matcher's own floor is now excluded outright, and the unlikeness bar dropped
  to `0.25` as a secondary check. Verified against the live account: the night
  hike is excluded, and a motorcycle swap meet and a baroque recital surface.
- The broad query also reintroduced a failure this module had already measured
  and designed against — it returned directory pages, and `Events Arlington,
  Virginia` and `Arlington, VA Events, Calendar & Tickets | Eventbrite` reached
  the *matched* list by scoring well against "hiking". `looks_like_a_directory`
  missed both: one has no preposition, and the ticketing sites write "Events,
  Calendar & Tickets" rather than "Events & Tickets". Both are now refused, and
  a happening named "Event Horizon Film Festival" still survives, which is why
  the new rule is keyed on the plural at the start of a title.
- 896 backend tests pass; Ruff, Black and MyPy clean; gateway rebuilt and the
  served bundle confirmed to carry the section.

## 2026-08-08 — Semantic chat interests configure Scout

- Replaced Scout's single-value interest regex with a focused local
  `qwen/qwen3.5-4b` classifier that produces grammar-constrained, bounded
  multi-interest proposals while understanding ownership, negation, and former
  interests. Reasoning is disabled so the 128-token budget reaches final JSON.
- Kept consent application-owned: the classifier cannot write memory or call
  tools, the browser displays one approval card, and approval atomically writes
  every approved fact and user-scoped Scout profile projection. Capacity failure
  maps to a memory conflict and rolls the entire batch back.
- Fixed Scout subscription UI calls to use the authenticated request boundary;
  this removed post-login 401s from the Agents view.
- Verified the exact four-interest sentence through direct authenticated SSE and
  Chromium, including approval, stream termination, loading cleanup, Scout UI
  readback, and clean post-login Console/page behavior. A live Scout rehearsal
  then exercised MCP → Tavily, Nomic ranking, and Qwen descriptions over those
  interests and an Arlington, Virginia locality.
- 127 relevant backend tests, two deterministic Scout browser tests, the live
  authenticated browser test, Ruff, strict MyPy, the production frontend build,
  and architecture synchronization pass.

## 2026-08-08 — Scout past-event rejection and readable uncertainty verified

- Fixed the web-result boundary that collapsed an explicit past date into the
  same `None` value as an absent date, allowing a finished event to return as an
  undated recommendation.
- Kept genuinely undated links but changed the digest to say plainly that Scout
  could not confirm their dates instead of using the mechanical `Worth a look —
  no date given` heading.
- Repeated the authenticated `ani.mallya` acceptance through live MCP/Tavily,
  Nomic ranking, the rebuilt API, and Chromium's real **Try it** interaction;
  the stale candidate was rejected, the new copy rendered, and no blocking
  browser or backend error occurred.
- Verified 286 discovery tests, Ruff, strict MyPy, focused Scout browser tests,
  and the frontend production build. Cleared only the 28 `ani.mallya`
  `discovery_seen_items` rows afterward at the user's request so the next test
  begins with an empty seen set.

## 2026-08-08 — Scout runtime isolation and mobile account controls verified

- Traced a reported cross-user 9:30 PM Scout delivery through schedules, runs,
  profile interests, subscribers, and delivery records. The 9:30 schedule and
  successful phone delivery both belonged to `ani.mallya`; `jenos1` retained a
  separate 7:45 schedule, subscriber address, and disjoint interest profile.
- Found the actual isolation failure at deployment: the running backend was a
  stale container with authentication disabled despite current Compose and
  `.env` configuration requiring it. Recreated the backend with
  `AUTH_REQUIRED=true` and restarted the gateway.
- Verified live API ownership: each user can read their own Scout state, an
  `ani.mallya` token receives 403 for the `jenos1` profile, and an anonymous
  request receives 401. Backend logs contain both decisions without exceptions.
- Added an explicit two-user delivery regression proving a digest selects only
  the requested owner's approved subscriber.
- Added visible account identity and a labeled logout action to the mobile
  navigation drawer. At 390x844, Chromium exercised the rebuilt production
  gateway, showed the live authenticated owner, received 204 from logout, and
  returned to login without Console/page errors or failed requests.
- Verified 45 focused backend tests, two focused browser tests, and the frontend
  production build.

## 2026-08-09 — Scout searches and ranks for the person, not the topic

- Added `backend/discovery/personal_context.py`: one narrow door between
  approved personal memory and a sweep. It reads approved, unexpired facts and
  remembered sentences, skips the interest and locality projections already
  typed into the Scout profile, never reads `preferred_name` or
  `response_style`, screens every statement through the shared
  `OutboundPrivacyPolicy`, and bounds the result to 12 statements.
- Added `backend/discovery/aiming.py`: one grammar-constrained, greedy model
  call per sweep turns each interest plus those facts into a search subject and
  a ranking profile. The measured query skeleton `{subject} {place} {month
  year}` and the query budget are unchanged, and a subject carrying a digit, a
  month, the place, query syntax, or personal framing is rejected in favour of
  the bare label.
- Added `backend/discovery/reranking.py`: the deterministic ranker now produces
  a shortlist twice the digest's width and the model orders it against the same
  facts. It cannot admit anything deterministic ranking rejected, keeps dated
  finds and undated mentions capped separately, and falls back to the
  deterministic order when it would return nothing.
- Interest vectors are now the aimed profile rather than the bare label, keyed
  by the user's own label so a digest still names the interest they stated.
- Measured against the live `qwen/qwen3.5-4b` and embedding service, read-only:
  aimed vectors roughly doubled the attribution margin for genuine matches
  (0.071 to 0.132 for a social run, 0.054 to 0.118 for a jazz trio) and could
  not suppress a disliked stadium show, which scored higher after enrichment.
  The re-ranker ordered the same shortlist correctly and deterministically.
- Recorded, in `reranking.py`, a measured negative result: strengthening the
  exclusion wording made the model exclude preferences as if they were
  eligibility bars, and exclude a women-only event for a person with no fact
  about gender. The conservative wording was kept and audience restriction was
  left to the deterministic route.
- Added `DISCOVERY_PERSONAL_QUERIES_ENABLED` and
  `DISCOVERY_MEMORY_RERANK_ENABLED` to settings and to the Compose environment
  allowlist for both `backend` and `discovery-worker`, verified present in the
  rendered `docker compose config`.
- Verified 1020 backend tests with `AUTH_REQUIRED=false`, including 28 new ones
  covering what may be read out of memory, the unchanged skeleton and budget,
  and every failure path landing on the previous behaviour; Ruff and strict
  MyPy clean over `backend/discovery`; 17 diagrams synchronized after updating
  the Scout discovery and Scout agent views.
- Not deployed: the images were not rebuilt and no sweep has run through the
  built containers.

## 2026-08-09 — Multi-fact profile capture reaches Scout

- Bounded preferred-name extraction before a following `and I` or `but I`
  clause, fixing `Jen and i like acting` being proposed as a name.
- Allowed one chat turn to stream all compatible profile-memory proposals while
  preserving the single-best rule for general semantic and episodic memory.
- Queued memory proposals in the chat UI so approving a name reveals the
  interests from the same sentence instead of silently losing them.
- Rebuilt the backend and verified the exact message through authenticated HTTP
  and real Chromium as `testuser`: the profile became `Jen`, Scout contained
  `acting`, `theater`, and `networking events`, the queue and loading state
  cleared, and browser and backend error checks were empty.
- Verified 72 focused backend tests, Ruff, three focused Playwright proposal
  regressions, and the frontend production build. A broader title grep timed out
  without a result and remains explicitly unverified.
- Follow-up runtime tracing showed a repeated `testuser` attempt submitted only
  the interest approval even though the name was first in the browser queue.
  Replaced the anonymous `1 more proposal` hint with a preview of every queued
  value and an **Approve all** action that preserves failed/unattempted items.
- Verified the exact sentence and combined action in real Chromium: preferred
  name returned 200, Scout interests returned 201, readback returned `Jen` plus
  all three interests, and browser error and loading checks were clean.

## 2026-08-09 — Replaced regex memory capture with semantic typed proposals

- Removed the production regex proposal module and the superseded dedicated
  Scout-interest agent.
- Added one grammar-constrained Qwen memory-proposal agent covering preferred
  name, response style, locality, interests, entity relationship, workflow,
  titled reference, semantic fact, and episodic event without phrase routing.
- Kept interpretation separate from authority: deterministic code validates
  model fields and visible approval routes them to typed, user-scoped stores.
- Verified real Qwen understands both the exact reported sentence and a
  paraphrase without the former trigger phrasing, rejects a hypothetical
  question, and semantically reuses existing Scout labels.
- Corrected a live semantic-fact miss where Qwen treated a named pet as an
  interest or returned nothing. Meaning-based examples now separate stable
  personal facts, genuine interests, and recall questions without application
  phrase matching; five positive/negative live controls pass.
- Rebuilt the backend and verified exact combined approval through real
  authenticated Chromium as `testuser`; both writes and persisted readback
  passed with clean browser and backend error checks.
- Verified 82 focused backend tests, Ruff, two focused Playwright acceptances,
  frontend production build, 17 rendered diagrams, and the published
  architecture page.

## 2026-08-09 — A cross-encoder between the embeddings and the model

- Added `backend/embeddings/cross_encoder.py` and the `RerankProvider`
  interface: a local ONNX cross-encoder (`ms-marco-MiniLM-L6-v2`, 22M) scoring
  query/document pairs in-process on CPU, following the lazy-load,
  missing-file-disables shape `NomicVisionEmbeddingProvider` established. CPU
  because the card is fully committed to generation and lent to ComfyUI, and
  because a weekly batch of a few hundred short pairs measured 8 ms per pair.
- Added `backend/discovery/precision.py` between deterministic ranking and the
  memory re-ranker. Embeddings admit a shortlist twice the digest's width, the
  cross-encoder orders and re-attributes it, then the model applies approved
  memory. The new stage can neither admit nor drop, so eligibility stays where
  it was calibrated.
- Measured over the eight candidates whose cosine scores `relevance.py`
  tabulates: cosine attributed 5 of 8 correctly and named the wrong interest
  three times; the cross-encoder attributed all eight correctly across four
  query framings.
- Recorded two measured corrections in the code. The provider returns raw
  logits rather than sigmoid probabilities, because the squashed scores put the
  gap between a right and a wrong attribution at 0.000 versus 0.001 where
  log-odds separate 0.29 from 1.49; and interest strength is deliberately not
  applied at this stage, because recall already applied it and multiplying a
  negative log-odds by a strength ratio would rank the interests a user cares
  most about *lowest*.
- `MIN_ATTRIBUTION_MARGIN` here is 1.0 in log-odds and is not comparable to
  `relevance.py`'s 0.035 in cosine; the measured table is in the module.
- Added `DISCOVERY_CROSS_ENCODER_*` settings, the Compose allowlist entry for
  both services, and a `tokenizers` pin capped below its next major.
- Removed unreferenced `count_interests`, `count_localities`, and
  `sent_anything`.
- Verified 991 backend tests with `AUTH_REQUIRED=false`, including 10 new ones;
  Ruff and strict MyPy clean; 17 diagrams synchronized after adding the stage to
  the Scout discovery and Scout agent views.
- Not deployed: the images were not rebuilt and no sweep has run through the
  built containers.

## 2026-08-09 — Measurement, and an agent per folder

- Reviewed the digest jenos1 actually received and found three defects: a
  concert attributed to the interest "Horses" after the pub it was in, three of
  four items being pages of happenings rather than happenings, and vacuous
  summaries. `AimPlanner` now runs even when memory is empty — which is every
  account today — so an interest is described rather than compared as a
  two-word string. Verified end to end: the same find moves from Horses to
  Music.
- Recorded a negative result: the cross-encoder makes that same "Light Horse"
  mistake more confidently than cosine did. Lexical overlap is what a
  cross-encoder is strongest at, so it cannot be the fix for it.
- Added and then withdrew a model judgement of whether a page is a listing. It
  emptied a live digest — on a London sweep it called four of five shortlisted
  finds listings, including a single Eventbrite event, while passing an index of
  festivals in another city. It is still computed for tuning and no longer drops
  anything.
- Added `backend/cli/evaluate_discovery_ranking` and 21 labelled items taken
  from real digests. Baseline: listing recall 0.46, happening retention 1.00.
  Retention is floored at 1.0 and recall is not, because an admitted listing
  wastes a slot while a rejected happening leaves no trace it existed.
- Gave each agent a folder: `agents/scout/`, `agents/deck/`, `agents/diagram/`,
  with shared shapes in `agents/cards.py` and a registry that is a tuple of
  describers. Scout's sweep stays in `backend/discovery/`, because the
  dependency runs agents → domain and moving it would close a cycle.
- Verified 1011 backend tests, Ruff, strict MyPy, and an unchanged harness
  scorecard across the restructure.

## 2026-08-10 — Delivery unblocked, and dates read rather than judged

- Found why scheduled digests stopped arriving, and it was not the Mac. The
  outbound privacy screen refused any run of 13 to 19 digits as a payment card,
  and `.../senior-line-dancing-2026-109463698` is thirteen digits — as is every
  Eventbrite link. The tool call raised `argument_withheld`, delivery recorded
  its catch-all `channel_failed`, and it read for hours as the bridge refusing.
  The card pattern now ignores a URL's scheme, host and path, and requires a
  Luhn checksum and an issuer prefix, so an ISBN or an order number is no longer
  mistaken for a card. Verified both digests delivered, and `redeliver()`
  exercised for testuser.
- Added `geography.py`: a find is refused when it names a region explicitly and
  none of them is the user's. Measured before wiring: catches the Arlington
  Texas index that reached an Arlington Virginia digest, keeps 18 of 18 local
  finds. Misses two, named in the scorecard, which now fails a run outright if
  geographic rejection ever removes a local find.
- A stated deadline is now read deterministically. jenos1 was offered a vote
  closing "through August 3" on August 10; the describe prompt does ask about
  this and a 4B model comparing two dates is not a clock. Removed
  `is_a_listing`, which had added a fourth required field to that same
  160-token call and whose answer nothing used.
- Novelty turned back on in `.env` and verified in both services.
- Dark mode groundwork: `theme.ts` decides from the clock on the user's own
  device — no location and no memory, because `new Date()` is already in their
  timezone — with the system preference winning when set. `theme-palette.json`
  maps all 40 interface colours to dark counterparts. The toggle and browser
  verification are not done; treat the visual result as unverified.

## 2026-08-10 — A schedule runs on the user's own clock

- A place saved through a chat approval was written with a hardcoded
  `America/New_York`, so an account living in Canggu held a locality — and a
  schedule inheriting its zone — in Virginia time, and the morning digest fired
  at 23:15 where they were. `agents/scout/timezones.py` asks the local model for
  the geography and `zoneinfo` checks the answer, so a zone the IANA database
  has never contained cannot be stored and an unresolvable place keeps the
  fallback every place had before. The checking is not decorative: asked for a
  bare "Alexandria" the model answers `Africa/Cairo` for an account in
  Alexandria, Virginia, which passing the locality's `region` settles.
- The schedule API now refuses a schedule with no locality, because there is no
  zone to store it in otherwise, and the Scout panel disables its clock until a
  place is saved and says why rather than letting a time be picked and refused.
- The locality backfill re-arms `next_run_at` when it moves a zone. Moving the
  stored zone alone left the armed instant where the wrong zone had put it —
  arsalon's 23:20 sweep still fired at 11:20 Bali time with the zone reading
  correctly.
- Verified against the running model in
  `backend/tests/functional/test_timezone_prompt_behaviour.py`, over zones whose
  name is not the nearest large city, countries spanning several zones, and one
  unanswerable place.

## 2026-08-10 — An interest survives how it is actually said

- The capture prompt said not to depend on trigger words and did. Measured
  against the running model, "I love woodworking" produced the interest while
  "I am into woodworking", "I am a big fan of jazz" and "I do a lot of rock
  climbing" produced nothing — and a dropped interest is never proposed, never
  approved, and leaves no trace that anything was missed. The constructions are
  now stated as a rule rather than generalized from one example, and a
  multi-word interest is stated to be one label.
- Held by ten phrasings of one interest plus four negatives, so a prompt
  loosened to catch them cannot pass by proposing everything: 5 of 17 failed
  before, 17 pass now, and it generalizes to held-out cases — "I am into
  birdwatching" captures, "My brother is into cycling" and "I used to love
  skiing but not anymore" stay empty.
- Six tests were 401ing before reaching the code they were written to exercise,
  because `.env` sets `AUTH_REQUIRED=true` and pytest reads the same file. They
  now carry their own token, and a cross-user read carries the *other* user's
  token so it keeps measuring data scoping rather than becoming a test of path
  authorization that passes for the wrong reason.

## 2026-08-10 — Listing rejection measured, and the theme control shipped

- Four more listing shapes, each taken from a page that reached a real digest: a
  taxonomy path, `/whats-on`, a place-scoped roster slug, and a strict plural
  with a trailing year. Title rules also apply per colon-separated segment.
  `listing_recall` 0.4615 → 0.8462 with `happening_retention` still 1.0 and
  nothing wrongly rejected; the harness floor moves to 0.80 so a regression
  fails rather than being noticed in a digest.
- The theme engine decided correctly and ran exactly once, at load, so an
  evening arriving while the tab was open went unnoticed and there was no way to
  disagree with it. The toggle cycles automatic → light → dark and is remembered
  across reloads.
- Automatic then turned out never to have run on the clock at all: the system
  preference was checked first and returns a positive match in every modern
  browser, so `themeForHour` was unreachable and an OS pinned to light kept the
  workspace light at 01:30. The clock now decides, and a system preference for
  dark can add darkness but never remove it. Covered at fixed times rather than
  at whatever hour the suite runs.

## 2026-08-10 — Every agent documented, and the diagram defect diagnosed

- `docs/AGENT_CATALOG.md` records every specialized agent: what its model
  decides, what is deliberately decided for it, where its folder, prompts, card,
  diagram and tests live, and the checklist for adding one. It also draws a line
  the code drew and nothing wrote down — the search-freshness and image-recall
  classifiers call a model and produce no work, so they are policies rather than
  agents. The catalog carries every model call with its token budget,
  temperature and grammar, and records that one model serves all of them.
- Deck and Diagram each gained a diagram of what their model decides, and Deck
  gained functional tests that pass against the real model.
- The diagram agent's `xfail` said the model ignored the prompt on some shapes.
  Across eight varied requests the defect was serialization, not reasoning:
  inside a JSON string the model joins its Mermaid lines with `<br/>` rather
  than escaped newlines, so a structurally correct graph was rejected whole.
  Normalizing that break took the set from 3/8 to 7/8. The call had also run at
  the provider default temperature, alone among the agents, which is why the
  same eight requests scored 0/8 then 3/8 with nothing changed and the bug read
  as a flaky test. It is greedy now and the test is six real cases. Asked for a
  state machine the model still returns `stateDiagram-v2` with no body; that is
  recorded and excluded rather than papered over.
- The four agent views were registered in the renderer and the catalog but never
  added to the published architecture page, which went on reporting "15 / 15
  synchronized" while 19 sources existed. All 19 are now published, and the
  count is read from the sources on disk and folded into the page fingerprint,
  so the same omission fails the check instead of printing a reassuring number.

## 2026-08-11 — AniOS is served at deep-matter.com

- The public address is a named Cloudflare tunnel on a domain registered in the
  same account, replacing a quick tunnel whose hostname was random on every
  start and died with the machine. `scripts/start-tunnel.sh` runs the named
  tunnel when `ANIOS_TUNNEL_NAME` and `ANIOS_PUBLIC_HOSTNAME` are set and falls
  back to a quick tunnel otherwise, so a machine without the one-time setup is
  unaffected. A named tunnel rewrites no downstream setting, because nothing
  about the address changes.
- `AUTH_COOKIE_SECURE` moved to true in the same step, which is the only safe
  order: true over plain HTTP leaves no working login anywhere, because the
  browser refuses the cookie and there is no HTTPS origin to set it on. Proved
  it reached the container with `printenv` rather than trusting `.env`.
- Nothing in the application needed the hostname. The gateway serves the app and
  proxies `/api` on one origin, so the browser is same-origin, and
  `validate_browser_origin` already derives `https://<host>` from the request
  rather than from a configured list.
- Verified from inside a container, never from the desktop, because a host check
  can resolve back to the local stack and report a healthy site that is publicly
  dead. DNS resolves to two Cloudflare edge addresses, both complete a TLS
  handshake, `/healthz` returns 200 `ok`, `/` serves the compiled application,
  and `/api/v1/agents/{user}` returns 401 from FastAPI — which is what proves
  the whole path rather than just the edge.
- Cloudflare's browser-integrity check answers a non-browser client with error
  1010, so a plain scripted request looks like a dead site. Any check from now
  on needs an ordinary user agent, or it measures the bot rule instead of AniOS.
- Still manual: installing the tunnel as a Windows service, which needs an
  elevated shell. Until then the public address does not survive a reboot.

## 2026-08-11 — Scout has a preference signal

- A digest now sends as one message per find, and a thumbs-up or thumbs-down on
  any of them is recorded against that find. First verified end to end tonight:
  `liked` on "Garden of Tomorrow expansion", `disliked` on "Seven Wonders at
  Tarara Winery", each carrying the locality and the same `item_digest` novelty
  and familiarity key on — so a like, a dismissal and a suppression name the
  same thing and stay comparable.
- Nothing in ranking reads it yet, deliberately. A loop trained on two reactions
  would learn noise.
- Reactions are matched by **message body**, never by Apple's identifier. There
  is none handed back at send time, and every way of recovering one afterwards
  failed against a real Mac: never captured, captured pointing at the wrong
  message, and pointing at a copy this machine never stored. The body is
  composed here and shared by every copy of the message.
- Recent macOS keeps most message bodies in `attributedBody` rather than `text`
  — 54 of 64 in one sample — so the original lookup, which matched on `text`,
  could never have worked whatever the permissions were.
- The Messages database must be opened `mode=ro`, not `immutable=1`: immutable
  makes SQLite skip the write-ahead log, which is exactly where a message sent
  seconds ago still is.
- **A reaction made on a phone in a thread with yourself cannot be linked.** The
  phone holds a different message object; its tapback references a row the Mac
  never stored, and reported `found: false` for both. The same reactions made in
  Messages on the Mac recorded immediately. Subscribers are unaffected — a normal
  recipient's reaction references the sender's own message — but it is the case
  every test uses, and it cost most of the evening.
- The digest also stopped silently dropping finds: asked for five lines the model
  returned three, and two finds never arrived. Lines are matched to finds by
  index now, and a find the model skipped is sent with its assembled line.

## 2026-08-11 — An edit request is recognized by a model, not a verb list

- Attaching a picture and asking for an edit in the same message now edits it.
  Whether words about an image ask for a change or an answer is decided by the
  main conversation model, answering into a two-value enum sent as a decoding
  grammar (`backend/services/image_intent.py`), and one decision now serves the
  composer, the upload path, and the image card's follow-up box.
- The rule it replaced matched the first word against a list of verbs. Measured
  against the phrasings people actually used, it routed "edit this image to give
  me a straw hat" to the editor and "give me a straw hat", "put a hat on me",
  "draw a hat on this" and "straw hat please" to a description. Its one branch
  for polite phrasing could never fire: "can you edit this..." matched the edit
  rule and was then rejected for starting with "can".
- Each miss did more than fail. The instruction was put to the vision model as a
  question, it answered that it cannot edit images, and that refusal was stored
  and embedded as the description of the picture just uploaded. The edit request
  no longer reaches the vision model at all — verified against the running
  models, where the same upload and instruction now return `intent: edit` and a
  real description of the picture.
- `backend/tests/functional/test_image_intent_behaviour.py` measures the
  classification against the live model: 15 edit phrasings, 10 questions, a
  minimal pair that differs only by a question mark, and an injected instruction
  that is classified rather than obeyed. All pass.
- The image card's button still guesses locally whether it will say "Refine" or
  "Ask", because that label updates on every keystroke; the send that follows
  asks the server, and the in-flight label is corrected from the answer.

## 2026-08-11 — An edited photograph remembers what it was

- Editing an uploaded picture lost the original's meaning. Recall collapses an
  original when one of its own revisions also matches, so the same picture is
  not shown twice — and everything the original knew was collapsed with it. A
  photograph the user supplied survived only as a `generated_image` titled
  "Edited image", described by an analysis of the edited pixels.
- Asked "remember the picture I gave you of my hat? where can I find that hat?",
  the assistant reported that the only image on record was one it had generated
  from a creative request. Reproduced against the running model with the context
  as it was: it named the *straw* hat from the edit as the hat in "the picture
  you uploaded". The user's actual photograph showed a wide-brimmed black cowboy
  hat, and that description was in the database the whole time.
- `collapse_revision_chains` now carries the lineage onto the revision that
  replaces the original: the root it descends from, whether the user supplied
  it, what it showed, and every edit applied since, oldest first. The walk is
  bounded and terminates on a cycle in stored metadata.
- `_render_image_context` explains the new fields, including that the origin's
  description is of the picture *before* the edits — without that, both hats are
  in the prompt and nothing says which is current.
- Verified against the running model with the same question: it now answers that
  the uploaded picture showed a wide-brimmed black cowboy hat and that the straw
  hat was the edit that followed.
  `backend/tests/functional/test_image_lineage_behaviour.py` measures the recall,
  that a supplied photograph is not called an invention, that the original and
  the edit stay distinct and in order, and that a plain generated image gains no
  lineage it does not have.

## 2026-08-11 — Provenance became a relationship

- `parent_artifact_id` is a real column on `visual_artifacts` — indexed, with a
  self-referencing foreign key that nulls on delete — rather than a note inside
  `extra_data` that nothing could join on. Backfilled for every existing chain
  whose parent still exists; the JSON key is still written and still read, so
  nothing that depended on it changed.
- `ArtifactLineageStore.resolve_lineage` answers what each artifact was derived
  from: one bounded recursive query for a whole page of matches, returning the
  root of each chain and the edits applied along it, oldest first. Ownership is
  enforced at every hop, not only at the seed, so a stored identifier cannot
  walk a chain into another account.
- This replaces yesterday's approach of carrying the collapsed original onto its
  revision, which could only answer when the original happened to match the same
  query — precisely when the answer was least needed. `collapse_revision_chains`
  went back to deciding what is shown and nothing more.
- Nothing here is specific to images: it resolves the parent edge, so a trimmed
  recording or a revised document is answered by the same code and the same
  index the day those exist.
- Measured against a real PostgreSQL rather than a fake repository, because the
  walk, the ownership check and the depth bound are all SQL: seven tests, each
  inside a transaction that is always rolled back, including the case the old
  approach could not answer — an edit resolving its origin when the origin was
  not itself retrieved.
- Verified on the live database against a real three-step chain: the root, the
  correct `supplied_by_user: false` for a generated original, and all three
  edits in the order they were applied. The seed lookup uses the primary key
  index, and the foreign key's delete path uses the new index instead of
  scanning every artifact.

## 2026-08-11 — Provenance stopped killing the chat stream

- Merging the resolved lineage into the match records broke every chat turn that
  recalled an image: those same records are streamed to the interface as the
  `image_matches` event, the API encodes each event with `json.dumps`, and a
  dataclass is not JSON. The user saw "Unable to complete the chat request" with
  nothing to connect it to provenance.
- The tests in place all passed. They asserted on objects in memory, and the
  objects were correct; what none of them exercised was whether the transport
  could carry them.
- Provenance is prompt context and now travels beside the matches rather than
  inside them, so nothing added for the model can reach the browser.
- `test_every_streamed_retrieval_event_survives_the_json_encoder` drives the
  real retrieval branch and encodes every event it yields, exactly as the API
  does. Confirmed to fail against the defect and pass against the fix.
- Verified end to end over real HTTP against the running stack, with the
  question that failed: the assistant answers that the photograph is the user's
  own, wearing a wide-brimmed black cowboy hat, and that the straw hat was the
  edit made from it.

## 2026-08-12 — 460 MB of unreachable bytes reclaimed

- Measured before deciding anything: 556 MB on disk, of which **460 MB across
  109 files was referenced by nothing at all** — 83%, mostly rendered decks whose
  rows were long gone. Metadata, by contrast, was 9.3 KB across 23 images, so the
  earlier instinct to trim stored descriptions would have saved a rounding error.
- `backend/artifacts/collection.py` plans a sweep;
  `python -m backend.cli.collect_storage` runs it, reporting by default and
  deleting only with `--apply`. Guards, each for a distinct way this could
  destroy something irreplaceable: an unreadable reference table refuses the
  sweep rather than reading "no references found" as "nothing is referenced"; a
  file written within the grace period is left alone, because a render writes
  bytes before it records its row; and a key that is absolute or escapes the root
  is refused exactly as a read would refuse it.
- Verified before deleting that all 109 filenames were artifact ids with no
  surviving row in `visual_artifacts`, `presentation_revisions` or
  `presentations`, and that referenced files found equalled keys on record.
  Verified after that all 30 survivors read back with matching SHA-256, that
  every artifact the API lists still downloads, and that image recall in chat
  still answers correctly.
- A `storage-collection` service sweeps every six hours with a one-day grace
  period, under the same `maintenance` profile as `memory-maintenance`. That
  profile is not enabled, so it does not run until someone turns it on.
- Left alone deliberately: one image memory from 2026-08-02 at 1,191 characters,
  written before the 400-character gist cap existed. Trimming it would recover
  700 bytes and re-embedding a truncated description risks making a working
  memory match worse. The gist cap is holding for everything written since —
  246 to 438 characters.

## 2026-08-12 — Scout records the decision, not only the outcome

- A reaction labels one item. It says nothing about which interest matched it,
  how strongly it scored, what it beat, or where in the message it sat — and the
  rejected candidates, the only evidence a rejection was wrong, were never
  written down at all. Four thumbs with no features cannot train or evaluate
  anything.
- `backend/discovery/decision_log.py` records the whole decision at the moment
  of selection: every shortlisted candidate with its score and matched interest,
  whether it was sent, its slot in the message, and the propensity the policy
  gave it. Stored sealed on the run beside the digest, in the same transaction,
  so an outcome can never exist without the decision that produced it.
- The shape is the one off-policy evaluation expects — context, action, reward,
  pscore, position, action_context — so the data can go to a standard estimator
  rather than being re-derived from whatever survived.
- `policy` is recorded rather than assumed, and it currently reads
  `deterministic_top_k`. That is a statement with teeth: a deterministic policy
  assigns propensity 1.0 to what it chose and 0.0 to everything else, and an
  action with zero logging probability contributes nothing to the usual
  estimators. **This data alone cannot measure an alternative ranker.** That
  needs exploration — sometimes sending something the policy did not rank first,
  and recording the real chance it had. Logging propensity honestly now is what
  will make that change visible in the data instead of silent.
- Verified by driving a real sweep, not by constructing arguments to the builder:
  every selected find appears with its slot, score, interest and propensity, and
  the record survives the sealed column intact.
- Existing runs have no decision on file, which is the truth: the column is
  newer than they are.

## 2026-08-12 — Image follow-ups moved into one explicit composer

- Removed the competing textarea beneath every image card. The newest visible
  image is shown as a removable thumbnail above the main composer, and **Ask or
  edit** on any image switches the exact owned artifact used by the next
  question or refinement.
- Added deterministic Chromium coverage for two-image disambiguation, clearing
  image context, exact `active_image_artifact_id` request bodies, grounded chat
  questions, and generated/uploaded source refinements. All five focused paths
  pass and the frontend production build succeeds.
- Documented semantic visual selection as the default natural-reference path
  and a type-neutral future contract for generated, uploaded, or discussed
  artifacts, including planned video observations and parsed PDF/RAG chunks.
- Corrected the public deployment boundary after `deep-matter.com` was found
  serving the previous gateway-compiled bundle even though port 5173 had the
  new source. Rebuilt and recreated the gateway; both Cloudflare edge addresses
  now serve the new hashed bundle with the selection controls and without the
  removed follow-up field. Added the required gateway rebuild to the operator
  guide and agent instructions. A real authenticated Chromium run against
  `https://deep-matter.com` restored an owned image and completed its grounded
  main-composer follow-up with clean Console/page/required-Network state.
- Traced `ani.mallya`'s exact **can you make it a straw hat instead?** turn from
  its 201 refinement response to the ready child artifact and found that the
  image card updated while a separate generation placeholder remained active.
  Refinement completion now retires that one placeholder, and successful image
  generation/refinement replaces transient starting copy with an explicit
  terminal message. Generated- and uploaded-image Chromium refinement paths,
  the production build, and the exact rebuilt bundle served by both Cloudflare
  IPv4 edges all pass.

## 2026-08-12 — Visual style memory rejects stale artifact handles

- Traced the exact repeated **how do you feel about my dress style?** denial to
  eight orphaned derived descriptions filling the visual-memory shortlist. The
  semantic model selected a relevant outfit, but its deleted artifact handle
  correctly failed the final ownership/readiness check and no live image reached
  the answer model.
- Visual candidate retrieval now joins descriptions to ready same-owner image
  artifacts before limiting results. Artifact deletion removes its derived
  visual description in the same PostgreSQL commit, while existing orphan rows
  remain inert rather than being destructively cleaned from live data.
- The image-memory prompt now gives a grounded style opinion without disclaiming
  memory or sight, and avoids treating one observed outfit as a permanent user
  preference. Focused PostgreSQL tests, real-Qwen functional tests, a direct
  memory-only API turn, and authenticated Chromium through `deep-matter.com`
  all pass.
- Ready FLUX children now pass through local Qwen vision after editing and store
  their own current-pixel analysis and derived semantic index. Observation is
  best-effort so valid edited pixels are never discarded; a strict functional
  `xfail` preserves the known degraded case where Qwen can prefer an origin
  detail over a text-only edit delta when observation is unavailable.
- Live acceptance created a source-conditioned straw-hat child, observed its
  current pixels with Qwen, grounded direct chat and the public Chromium UI in
  the straw hat, bomber jacket and white shirt, then deleted the temporary child
  and verified both its artifact and derived semantic rows were removed.
- Backfilled the reported existing straw-hat revision through the same local
  observation boundary. Its owned current-pixel analysis and semantic index now
  describe the straw hat and outfit, and the exact question passes through both
  direct chat and the public Cloudflare browser with that revision selected.

## 2026-08-12 — Cloudflare connector startup made self-healing

- Added a reproducible Windows user-logon task installer with a one-minute
  delayed trigger, network requirement, and start-when-available behavior.
- Replaced ineffective Task Scheduler process retry behavior with a task-owned
  supervisor that relaunches cloudflared after transient exits. Killing the
  connector registered a replacement in about 15 seconds while the task stayed
  running.
- Verified the replacement connector from the backend container across both
  published Cloudflare IPv4 addresses: application health and frontend returned
  200, and the protected agent route returned 401. A full Windows reboot remains
  unverified so the handoff does not overstate it.

## 2026-08-12 — Personal-memory wipe now removes visual artifacts

- Closed the forget-me boundary that left visual-artifact rows, embeddings, and
  opaque image files behind after **Delete all personal memory** returned 200.
- Added user-scoped bulk artifact deletion with returned storage keys,
  incomplete-file-cleanup reporting, explicit deletion counts, and cross-user
  row/file isolation coverage.
- Verified the rebuilt backend with real owner/control files and derived visual
  memory, then verified the public Cloudflare browser path with a real uploaded
  PNG, the Memory-panel delete action, empty artifact history, terminal loading,
  and no Console or page errors.

## 2026-08-12 — Turn routing became one native tool-calling decision

- Replaced four independent deterministic gates — a regex-plus-classifier
  cascade for web search, a regex for diagram requests, a regex delegation
  policy for presentation creation, and a browser-side keyword regex for image
  generation — with `MainActionSelector`: one native tool-calling call, made
  by the same model that answers the user, offering search, image
  generation/edit, diagrams, presentation delegation, and the user's own
  registered MCP tools together and refusing to act on a name that round
  never actually offered.
- Folded image generation and editing into the chat stream. Both used to be
  separate client-triggered REST calls invisible to conversation history —
  which was the direct cause of a reported bug: an edit request changed the
  picture but left no reply and no trace in memory. They now run inside
  `process_request` and emit the same `artifact_started`/`artifact_ready`
  lifecycle a diagram already used, so every exchange is persisted and an
  edit gets a visible reply.
- The routing prompt explicitly declines to guess a missing personal detail
  (most concretely, the user's location) rather than silently assuming one
  and searching anyway — the reported failure that started this change: a
  request for tonight's events returned suggestions from unrelated cities
  with no clarifying question asked.
- Added a labelled-benchmark functional test
  (`test_search_routing_quality_meets_the_retired_cascades_floor`) that holds
  the new native tool-calling decision to the same recall/specificity floor
  the retired regex-plus-classifier cascade was held to in
  `evaluate_search_routing.py`, plus functional tests for the location-guessing
  refusal, image/diagram/delegation routing, and ordinary questions choosing
  no action — all against the real vLLM runtime and the real `internet` MCP
  server. All 13 passed after one prompt revision driven by a real run: initial
  recall was 0.76 against the cascade's 0.90 floor, missing implicit-officeholder
  questions ("who is the prime minister of Canada"); naming that category
  explicitly and telling the model to prefer calling the tool when genuinely
  unsure closed the gap.
- Evidence: the full backend suite (1166 tests) passes; Ruff passes on every
  changed file; the frontend production build passes; the non-live browser
  suite (61 tests) passes against a real Chromium instance and a real frontend
  dev server, including every image-generation/edit test rewritten to mock the
  chat SSE stream instead of the retired direct REST calls — one of which
  caught a real bug before it shipped (the stream parser rejected any
  `artifact_started` kind other than `"diagram"`, which would have broken
  every chat-initiated image turn). Five pre-existing browser-suite failures
  were confirmed present on unmodified `HEAD` and are unrelated. The
  three `@live` image tests (real ComfyUI generation) were mechanically
  updated to the same event-stream shape but could not be run in this
  environment, since ComfyUI was not started; they remain unverified against
  the live provider.
- Restoring cancellability for a slow chat-initiated generation, discovered
  missing while adapting the cancellation test, needed threading an
  `AbortSignal` through `streamChat` and widening the composer's cancel
  button beyond the retired visual-only request path.
- Chat-initiated generation/edit failures now name an unreachable ComfyUI
  specifically, matching the retired direct REST endpoints -- caught missing
  while updating documentation, not by a test. A generic message would have
  reintroduced the exact failure named in this repository's own operational
  notes: a downed provider reading as a declined request rather than an
  outage nobody had started.
- `MainSupervisorAgent`, `CascadingSearchRouter`, and `SearchRoutingPolicy`
  remain in the tree, still tested standalone, but are no longer reachable
  from a live turn.

## 2026-08-13 — Chat memory proposals auto-save; a recalled photo stops repeating

- Every proposal `MemoryProposalAgent` classifies from a chat turn (preferred
  name, response style, home locality, Scout interests, entity, procedure,
  knowledge, semantic fact, episodic event) is now persisted immediately by
  `ConversationService`, before the reply is generated — no approval
  round-trip. Asking the user to confirm the same small facts turn after turn
  earned no accuracy and cost real friction; what ships instead is
  visibility, not consent: the `memory_proposal` SSE event now reports a
  record that already exists, and a per-candidate save failure is dropped and
  logged rather than raised, so it costs only that one candidate, never the
  turn's reply or any other candidate saved alongside it. `_render_save_state`
  in `graph.py` was rewritten to the same "already saved" framing, following
  this repository's own prior lesson: told only that it cannot save, the
  model answered "your personal memory has been updated" — true-sounding,
  passive, and false; naming the real state left nothing to route around. The
  frontend's approve/reject queue (`saveMemoryProposal`,
  `approveMemoryProposal`, `approveAllMemoryProposals`, `rejectMemoryProposal`,
  the turn-based retirement grace period, and the ten REST `approve*` client
  functions they called) was removed entirely; the reply-adjacent card is now
  a read-only "Saved X as Y memory" notice that clears on the next question.
- Investigated at the user's request from `ani.mallya`'s real conversation
  history (decrypted read-only from the dev database): a chat turn that
  merely referenced a previously generated photo for context (a style
  question, no "show me" language) re-attached the full image card to the
  reply. The cause was `_load_visual_memory_matches`, a real semantic-recall
  model call that correctly judges relevance on every adjacent turn about the
  same subject — so a multi-turn conversation about one outfit re-displayed
  the same photo on almost every reply, true in isolation, noisy in
  aggregate. Fixed in `_stream_retrieved_context`: that semantic-fallback path
  is now deduplicated against artifact ids this conversation already
  displayed (tracked via the persisted turn's `extra_data.artifact_ids`); an
  explicit recall ("show me that photo again") is never deduplicated. Each
  prompt image now carries a `freshly_shown` flag so the model is told,
  per item, whether it is newly attached this turn or already shown earlier —
  `_render_image_context` in `graph.py` was updated so it never claims a
  picture "just appeared" when `freshly_shown` is false.
- The separately reported "Artifact start event is invalid" error was found
  to already be fixed by the prior session's `d849522` (the `artifact_started`
  frontend validation was widened to accept `generated_image`, not only
  `diagram`); confirmed live in the running dev container via the file's
  modification time versus the conversation's timestamps. No new code change
  was needed for it.
- Evidence: the full backend suite (1170 tests) passes; Ruff passes on every
  changed file; the frontend production build (`tsc && vite build`) passes;
  the non-live browser suite passes, including nine `chat.spec.ts` tests
  rewritten from approval-click interactions to auto-save display assertions
  and a new dedup regression test; three pre-existing failures (a dark-mode
  color assertion, a flaky reload timeout, one flaky console-resource error)
  were confirmed present on unmodified `HEAD` and unrelated. New functional
  tests against the real running model: `test_memory_save_state_behaviour.py`
  (the model neither claims a save that did not happen nor describes a saved
  fact as pending approval — the first version of the "did not happen" prompt
  failed against the real model, which said "I've noted that ..." despite an
  explicit ban on the word; a worked positive/negative example fixed it) and
  a new case in `test_image_lineage_behaviour.py` (a repeated recall answers
  from the recalled description without claiming a picture was just shown).
- All ten proposal kinds were mapped to their exact persistence calls by
  reading the REST handlers they used to require: `approve_preferred_name`,
  `approve_fact` (locality and response style, via `locality_fact()`),
  `approve_discovery_interests`, and `save_semantic_memory` /
  `save_episodic_memory` on `MemoryService`; `entities.upsert`,
  `procedures.approve`, and `knowledge.ingest` on the newly wired
  `AgentMemoryManager` dependency (`ConversationService` had no reference to
  it before this change, so entity/procedure/knowledge proposals silently had
  no persistence path at all until now).
- Updated `docs/SECURITY.md`, `docs/ARCHITECTURE.md`,
  `docs/DEVELOPMENT_GUIDE.md`, and `docs/AGENT_CATALOG.md` to describe
  auto-save instead of the retired approval boundary, and regenerated
  `memory-overview.mmd`, `memory-subsystem.mmd`, `chat-orchestration.mmd`, and
  `agent-memory.mmd` (removing the "visible approval"/"Consent" gate nodes)
  plus their SVGs — `docs:diagram:check` reports all 19 diagrams synchronized.

## 2026-08-13 — Recalled photos display compactly; editing explains a missing target

- Reverted the same day's redisplay dedup after user feedback: the actual
  complaint was never "shows too often" but that each occurrence used the
  full 620px `ImageArtifact` card with its whole download/retry/delete
  toolbar. `_stream_retrieved_context` now always emits `image_matches`
  again for a relevant recall, exactly as before that dedup landed
  (`freshly_shown`, `_resolve_display`, `_render_image_prompt_context`, and
  their tests were removed with it). Instead, `ImageArtifact` gained a
  `compact` prop: a recalled match now renders as a small thumbnail chip
  ("From your library — tap to view") that expands to the identical full
  card and controls on click, and collapses back on demand. Only the
  `imageMatches` render path in `MessageBubble.tsx` uses it; an image just
  generated, uploaded, or edited still shows full-size immediately, per the
  user's own framing of the split.
- Fixed a real bug surfaced while investigating why editing silently stopped
  working after deleting a picture from chat: `handleVisualDeleted` reset
  `selectedImageId` to `null` when the deleted image was the active one —
  the same value a deliberate "clear image context" click uses. `null` means
  "stay detached"; a deletion is not that choice, and leaving it there
  silently disabled auto-following the newest visible image for the rest of
  the conversation, so a later edit request found nothing to apply to with
  no explanation. Changed to `undefined`, which resumes auto-follow.
- `edit_image` is now offered to the model every turn, active image or not —
  previously it was withheld unless the frontend already had one selected,
  so a message like "make it black and white" with nothing selected fell
  through to an ordinary reply that never mentioned a picture, reading as
  the feature being broken. `ConversationService` now checks the real
  selection state itself (the model has no way to know it) and, when the
  model judged this an edit request but nothing is active, replies with
  explicit guidance ("select the one you want changed... and I'll make the
  change from there") instead of guessing or staying silent.
  `_process_missing_edit_target`/`_dispatch_edit_image_action` persist this
  reply like any other turn.
- Always-offering `edit_image` needed two real-model-measured corrections.
  First: a wordy negative example added to the shared `_SYSTEM` prompt
  ("edit my resume is not this") fixed the false-positive but measurably
  dropped the search-routing benchmark's recall to 0.79 against its 0.85
  floor — confirmed by reverting on a clean tree, where it passed, and
  reproducing the drop with the addition restored. Moving the same
  clarification into `edit_image`'s own tool `description` field instead of
  the shared system-prompt block fixed the false positive without touching
  search routing: three consecutive real-model runs of the labelled
  search-routing benchmark all passed. Second: even the shared-prompt
  version needed the fix at all because "edit my resume to remove my last
  job" was observed, on the real model, actually calling `edit_image` with
  instruction "Remove the last job from the resume" — a genuine confusion
  the tests now hold a floor against
  (`test_an_unrelated_edit_request_does_not_choose_edit_image`).
- New tests: `test_edit_with_no_active_image_explains_instead_of_guessing`
  (backend unit), `test_an_edit_request_with_a_recent_picture_chooses_edit_image`
  / `test_an_unrelated_edit_request_does_not_choose_edit_image` (functional,
  real model), and two `chat.spec.ts` browser tests -
  `shows a recalled image as a compact thumbnail that expands on click` and
  `keeps auto-following the newest image after deleting the active one`,
  the latter reproducing the exact reported sequence (generate, delete,
  generate again, ask a followup) and asserting the second image's id
  reaches `active_image_artifact_id` on its own.
- Evidence: full backend suite (1170 tests) passes; Ruff passes on every
  changed file; `tsc && vite build` passes; the non-live `chat.spec.ts` suite
  passes (59 tests, two new); four pre-existing failures (the same dark-mode
  and diagram-reload-timeout ones as the prior entry, one flaky
  `net::ERR_FILE_NOT_FOUND` console error, and a "Sign out" click racing a
  detached DOM node) were confirmed present on unmodified `HEAD` via
  `git stash` and are unrelated.

## 2026-08-13 — Composer bar's dark-mode white bar; the model stopped inventing a city

- Investigated a follow-up screenshot ("weird white partition" in dark mode):
  `theme.css` hand-maps every compiled Tailwind arbitrary-colour class under
  `.dark`, but two variants of an already-mapped colour compile to their own
  distinct class that the base mapping does not reach — an opacity suffix
  (`bg-[#f5f5f7]/90`, the floating composer bar's blur background bakes the
  alpha into its own hex value) and a `hover:` prefix (`hover:bg-[#f5f5f7]`,
  introduced by the same day's compact-thumbnail button). Both stayed solid
  white against the dark surroundings. Mapped both, and swapped two other
  unmapped colours (the composer's image-in-use chip, the thumbnail's loading
  placeholder) for visually-equivalent ones already in the palette rather
  than growing it further. A new `theme.spec.ts` test reads the composer
  bar's actual computed `background-color` in dark mode; confirmed it fails
  against the unfixed code first.
- Separately, confirmed via trace that the reported "cowboy hat on beach"
  `/images/intent` bypass (see prior entry) really was resolved: the same
  message this time went through `/api/v1/chat` correctly and produced a
  valid `generated_image` artifact end to end — the remaining
  "Artifact start event is invalid" the user saw was a stale browser tab
  (confirmed by cross-referencing the persisted turn against the report; no
  code change needed).
- Traced a new report: asked for beach recommendations with a freshly wiped
  account (no profile, no facts, no locality, nothing earlier in the
  conversation), the assistant answered "Do you have a preferred proximity to
  a city (like Milwaukee, where you seem based)" — a specific, confident
  claim about the user's location with no source anywhere in its context. Not
  a routing bug: no search ran for that turn (verified against the trace) and
  no stored fact named a city (verified against the database) — the
  text-generation call fabricated it outright. Added an explicit instruction
  to `_build_system_prompt` in `graph.py`: never present a guess about the
  user's own personal facts (name, location, age, occupation) as if it were
  known, state one only when actually supplied. Added
  `test_it_does_not_invent_the_users_location`, though attempts to reproduce
  the original failure against the unmodified prompt did not reliably fail
  (4/4 passed) — real-model non-determinism at the edges of a shared prompt
  is not fully controllable, so this is best-effort regression coverage
  rather than a proven fix, kept because the instruction is a reasonable
  guardrail regardless. Unexpected side effect, caught by re-running the full
  file: `test_style_opinion_applies_the_edit_to_the_source_description`,
  previously `xfail(strict=True)` for a known Qwen limitation (preferring an
  edited photo's original detail over an explicit instructed change),
  XPASSed consistently (3/3) — the xfail marker was removed rather than left
  failing the suite.
- Evidence: full backend suite (1170 tests) passes; Ruff passes on every
  changed file; `tsc && vite build` passes; affected `chat.spec.ts` and
  `theme.spec.ts` tests pass, including the full `theme.spec.ts` file (6
  tests, one new) and a full `chat.spec.ts` run (56/59, the same three
  pre-existing failures as before, confirmed unrelated via `git stash`).

## 2026-08-13 — The gateway was a day-stale static build; recall stopped showing one photo three times

- Root cause of a whole session's worth of "still happening" frontend
  reports, finally found: `gateway` (`docker-compose.yml`, port 8080 — what
  the tunnel and deep-matter.com actually serve) is a one-shot static build.
  It runs `npm run build` once *inside its Docker image build* and bakes the
  result into nginx; nothing about it watches the source tree afterward,
  unlike `frontend` on `:5173`, the Vite dev server the user was never
  actually using. Confirmed directly: the bundle it served still contained
  the literal "1 matching image from your library" text removed hours
  earlier that day, and older client-side regex-based image routing from
  before the previous day's `MainActionSelector` migration. `docker restart`
  or `up -d` alone reuses the stale image and deploys nothing — verified a
  fix was actually live only after `docker compose build gateway && docker
  compose up -d --no-deps gateway`, by grepping the deployed bundle for
  strings that only exist in the new code. Documented as a new entry in
  `AGENTS.md`'s "Operational traps" section so it is not rediscovered the
  slow way again.
- One report that survived a full gateway rebuild and a genuine hard
  refresh (confirmed by pulling the exact persisted `response` text straight
  from the database, which ended cleanly with no such text — proving
  whatever the user was seeing was appended client-side, not generated)
  turned out to still be a stale *browser tab* specifically: a tab open
  since before the rebuild keeps running its already-loaded JavaScript until
  it is actually reloaded, independent of whether the server behind it is
  now correct.
- A genuine bug, once the deploy pipeline itself stopped being the variable:
  asking a style question recalled the same uploaded photo three times, each
  as its own "match." Traced to the database, not the selection logic: the
  same file had been uploaded across three separate conversations while
  testing that day, so `_load_visual_memory_matches` correctly found three
  real, independent, `sha256`-identical rows and correctly showed all three
  — each one was a genuine match, three times over. Added
  `collapse_duplicate_content` in `backend/artifacts/image_lineage.py`,
  alongside the existing `collapse_revision_chains` it is a sibling to:
  where that collapses a parent/child edit chain to its latest revision,
  this collapses independent rows sharing an identical `sha256` (provably
  the same file, not merely visually similar) to the newest copy. Wired into
  both `_load_image_matches` (the explicit-recall path) and
  `_load_visual_memory_matches` (the semantic-fallback path), since both
  retrieve independently and neither previously deduplicated by content.
- Evidence: full backend suite (1175 tests, 5 new) passes; Ruff passes on
  every changed file. New unit coverage for the pure function
  (`test_image_lineage.py`: newest-copy-wins, genuinely different images all
  kept, a missing digest never falsely collapsed, survivor order follows
  retrieval order rather than creation time) plus one integration test
  through the real `_stream_retrieved_context` path
  (`test_image_lineage_context.py`) reproducing the exact reported scenario
  end to end.

## 2026-08-13 — An edit no longer echoes an unasked description, and stopped re-editing on an opinion question

- An edit re-observes the result's pixels (`ImageRefinementService.refine` →
  `VisionAnalysisService.observe_artifact`) purely so the new artifact stays
  semantically findable — added in an earlier session to fix edited images
  being unrecallable. That write landed in the same `metadata.analysis` key
  the *upload* flow uses when the browser's default caption-less question is
  answered, and the frontend's `readAnalysisThread` legacy fallback cannot
  tell the two apart: any artifact with `analysis` set but no
  `analysis_thread` gets shown as a "Describe this image" card, unconditionally,
  right under the picture. Reported live: "can you edit this to a straw hat?"
  edited cleanly, then also surfaced an unrequested description underneath it.
  Fixed by marking the reindex-only write `analysis_user_facing: false` in
  `backend/services/vision_analysis_service.py` and having
  `frontend/src/services/api.ts`'s `readAnalysisThread` return no thread when
  that flag is present, before it ever reaches the legacy fallback. The
  upload flow's own use of the same key (where the description genuinely is
  the chat answer) is untouched since it never sets the new flag.
- Separately, read a real trace (conversation `3d463775`, 2026-08-13) where,
  after editing a photo's hat, "amazing! which hat do you like better for
  this outfit?" made `MainActionSelector` choose `edit_image` again —
  synthesizing a paraphrased instruction ("Replace the black cowboy hat with
  a straw hat") that silently redid the same edit instead of answering the
  comparison. Clarified `edit_image`'s own tool description (not the shared
  `_SYSTEM` prompt — widening that degraded unrelated search-routing recall
  earlier this session) to exclude an opinion, preference, or comparison
  question about the picture, even when it names the same subject a recent
  edit changed.
- Evidence: full backend suite (1175 tests) passes; Ruff passes on every
  changed file. `test_vision_memory_indexing.py` now asserts
  `analysis_user_facing is False` after `observe_artifact`. A new Playwright
  test (`chat.spec.ts`) reproduces the exact leak against the unfixed
  frontend (fails: analysis text visible) and passes against the fix. The
  `edit_image` routing fix has a functional test replaying the live trace
  verbatim, but that exact replay could not be forced to fail again against
  the unfixed description (12/12 passed) — a temperature-driven,
  low-probability slip rather than a deterministic gap, so it is recorded as
  best-effort coverage, not proof the fix changed measured behavior. The
  full `test_main_action_selector_behaviour.py` suite (17 tests, including
  the search-routing recall floor) stayed stable across three separate runs
  with the new `edit_image` wording in place.

## 2026-08-13 — The edit_image opinion-question fix was too narrow; broadened and measured properly

- The fix above shipped and was live for the next report: "do you recommend a
  straw hat instead?" (a differently-worded opinion question, same underlying
  shape as the one already fixed) again made `MainActionSelector` choose
  `edit_image` on a real trace. Called out directly: the first fix answered
  the one reported phrase rather than the general pattern. Rewrote
  `edit_image`'s description around the actual rule — a question is never an
  instruction, no matter what alternative it names — instead of listing
  specific comparison phrasings, and added four *different* opinion phrasings
  as examples so the wording itself demonstrates it generalizes.
- Verification this time used repeated trials instead of a single pass,
  because a single clean run had already been shown (earlier fix, same file)
  to hide a real gap. A parametrized test batches all four phrasings and
  requires every one to pass together, not one at a time: 24/24 across six
  independent runs, versus the single reported phrase this fix started from.
- That process caught a second, unrelated, **pre-existing** flake in the same
  tool description while iterating: "let's edit this project plan to push
  the deadline back a week" already misfired into `edit_image` roughly half
  the time on the *currently deployed* wording (2/4 direct trials), not
  something this change introduced — confirmed with `git stash` against the
  version already live. An intermediate draft of the broadened wording made
  it worse (3/4). The wording that shipped adds an explicit "even when the
  message says 'edit' and no other tool fits — answer directly instead of
  calling any tool" clause, which brought it to roughly 1/6 (down from ~1/2),
  a real reduction but not elimination — recorded honestly rather than
  claimed as fixed, since a residual gap this size will still surface again.
- The search-routing recall floor test failed once during this iteration's
  final verification pass, then passed clean on three immediate reruns (the
  same test, unchanged). Read as noise near this benchmark's known floor,
  not a regression from the tool-specific wording change — worth flagging in
  case it recurs, since a real regression and floor-adjacent noise look
  identical in a single run.
- Evidence: full backend suite (1175 tests) passes; Ruff passes.
  `test_main_action_selector_behaviour.py` grew to 21 tests. No frontend
  change, so no gateway rebuild — `docker restart anios_backend` only.

## 2026-08-14 — DeepSeek-V4-Flash on the DGX Spark now serves AniOS's presentation role

- A DGX Spark (GB10, 128 GB unified memory) joined the network alongside the
  RTX 5080 already serving `vllm-main`/`vllm-embedding` — addition, not
  replacement. Set up SSH access and a self-healing dashboard tunnel first;
  full detail (including two Task Scheduler bugs found and fixed along the
  way — a double-shell-parsing failure on a path containing a space, and
  Task Scheduler's launch `PATH` not including Git's `usr/bin`) is in
  `DEVELOPMENT_GUIDE.md`.
- Installed DeepSeek-V4-Flash-0731 (284B total / 13B active MoE) via
  [MiaAI-Lab/DeepSeek-v4-Flash-One-DGX-Spark](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-One-DGX-Spark)
  → `Entrpi/ds4-on-spark`, wrapping `antirez/ds4` ("DwarfStar 4", C/CUDA —
  not vLLM, which cannot read this quantization's asymmetric GGUF format).
  Read both install scripts in full before running anything on real
  hardware: entirely user-space, no `sudo`, no unexplained network calls, a
  real smoke test gates server start.
- Wired only into `PRESENTATION_LLM_BASE_URL`/`PRESENTATION_LLM_MODEL` in
  `docker-compose.yml` (`backend`, `presentation-worker`,
  `local-capabilities`) — deliberately not `MAIN_LLM_BASE_URL`. The main
  model drives `MainActionSelector`'s native tool-calling, which this session
  (and prior ones) already spent significant effort tuning against the RTX
  5080's model; that risk was not taken on today, and this engine's
  tool-calling behavior has never been tested at all.
- Two real bugs found and fixed during setup, not deferred: `ds4-server`
  binds `127.0.0.1` only by default, unreachable from the `anios_backend`
  container until restarted with `--host 0.0.0.0`; and nothing supervises it
  across a Spark reboot by default, fixed with a user crontab `@reboot`
  entry (no `sudo` available for a systemd unit).
- Verified with a real generation through the actual presentation code path
  (`LLMPresentationProvider` via `get_presentation_llm_client()`), not an
  endpoint health check: a genuine 3-slide, non-repeating deck with no
  invented statistics. A direct `/v1/chat/completions` call was also
  checked by hand after noticing the server's `/v1/models` response carries
  an unrelated embedded Codex CLI system prompt (an intentional
  compatibility feature, confirmed not to leak into actual completions, and
  confirmed that AniOS's `LLMClient` never reads that field anyway).
- Measured, not assumed: cold single-turn decode throughput is
  ~5.7 tokens/sec. Real and slow enough to matter for anything synchronous;
  tolerable for the async presentation-job path this was wired into.
  Sustained/concurrent throughput under real load was not measured.

## 2026-08-14 — Recreating `backend` broke deep-matter.com until `gateway` was also restarted

- Fallout of the change above: `docker compose up -d --no-deps backend
  presentation-worker local-capabilities`, needed to pick up the new
  `PRESENTATION_LLM_BASE_URL`, gave `anios_backend` a new Docker-internal IP.
  `nginx.gateway.conf` resolves the `backend` hostname once, at worker
  start, not per-request — `anios_gateway` (never restarted, since nothing
  about the frontend it serves had changed) kept proxying `/api/` to the old
  IP. Every request through `deep-matter.com` returned `502` with
  `connect() failed (111: Connection refused)` in the gateway's log, while a
  direct `docker exec anios_backend` call or `curl localhost:8000` from the
  host both worked — both paths bypass the gateway's stale resolution
  entirely, so neither could have shown the break, and neither did during
  this session's earlier verification.
- Fixed with `docker restart anios_gateway` (forces fresh DNS resolution;
  no rebuild needed, the served bundle did not change) and verified through
  the actual gateway path this time —
  `curl -H "Host: deep-matter.com" http://localhost:8080/api/v1/auth/session`
  went from `502` to the expected `401`.
- Documented as a new entry in `AGENTS.md`'s "Operational traps" section,
  next to the existing one-shot-static-build trap: recreating any service
  `gateway` proxies to needs a `gateway` restart afterward, and the only way
  to actually confirm that is a request through the gateway itself, not a
  container-internal or host-port check.

## 2026-08-14 — Reverted the presentation role to Qwen; found and fixed a real, pre-existing budget bug

- The DeepSeek-V4-Flash presentation attempt above failed on the user's
  actual first request: a `pydantic.ValidationError` with `extra_forbidden`
  on fields like `statistic` (schema wants `statistic_value`/
  `statistic_label`) and `content` (schema wants `points`, etc.) — the
  model's JSON was well-formed but did not use the exact field names AniOS's
  `DeckOutline` contract requires. Reverted `PRESENTATION_LLM_BASE_URL`/
  `PRESENTATION_LLM_MODEL` to `vllm-main`/`qwen/qwen3.5-4b` in
  `docker-compose.yml` immediately rather than attempt a same-session fix.
- Regenerating the user's exact prompt against the reverted (previously
  "known-good") Qwen config to confirm the revert worked **also failed**,
  2 of 3 identical attempts, with a different symptom: a JSON parse error
  from truncated output. `PRESENTATION_PLAN_MAX_TOKENS` defaulted to 2,048;
  this prompt's real plan needed close to that just for the outline. This is
  a pre-existing bug independent of the Spark work — it would have hit
  Qwen alone, on the original deployment, before any of this session's
  changes. Raised the default to 4,096 in `backend/config/settings.py`;
  3 of 3 identical attempts succeeded afterward.
- Both fixes required a full `docker compose build` + `up -d --no-deps` +
  `docker restart anios_gateway` cycle (the settings change is source code,
  not an env var — `anios_backend` does not bind-mount the repo), verified
  through the actual gateway path each time per the trap documented above.
- Evidence: full backend suite (1175 tests) passes; Ruff passes. Verified
  through the real `LLMPresentationProvider` code path at production
  settings, not a mock or a single successful run — 3 consecutive real
  generations of the exact prompt that originally failed.

## 2026-08-14 — Evaluated DeepSeek-V4-Flash's native tool-calling directly; found and fixed a real generate_image gap

- Built a standalone `MainActionSelector` pointed at
  `spark-b524.local:8888`/`deepseek-v4-flash`, never touching the running
  app's `MAIN_LLM_BASE_URL`, to answer directly whether this engine's
  tool-calling is reliable enough to ever be considered for the main model —
  the real question behind the presentation experiment, not inferred from
  it. No regex or hardcoded routing anywhere in this evaluation or in
  `MainActionSelector` itself; every decision is the model's own native tool
  call, same as Qwen today.
- Ran the same 52-case search-routing benchmark (`recall >= 0.85`,
  `specificity >= 0.75`) Qwen was held to: **recall 0.8519, specificity
  0.9565** — passes, with recall clearing the floor by under one case's
  margin. All 4 misses were the deliberately hard category (ongoing-event
  questions with no temporal marker).
- Every tool call the model produced across the whole evaluation was valid,
  correctly-typed JSON — a different and better property than the
  presentation failure showed, which needed a complex nested schema rather
  than tool-calling's flat arguments.
- Found one real, reproducible judgment gap: "write a haiku about rain"
  called `generate_image` to illustrate the rain instead of writing the
  haiku (2/2 on discovery). Broadened `generate_image`'s tool description
  around the general principle - text requests stay text even about a
  visual subject - rather than the one reported phrase, mirroring the
  `edit_image` fix pattern from earlier this session. Verified with poem,
  story, and description phrasings across different subjects: fixed
  cleanly. A second, more forceful version of the same description was
  tried and rejected - it introduced two new regressions (a previously
  100%-reliable diagram request, and the just-fixed poem case) without
  fixing the remaining gap, a direct instance of the overfitting risk this
  project has repeatedly been warned about. Reverted to the first,
  non-regressing wording.
- Disclosed, not hidden: short structured nature poetry specifically -
  haiku and limerick - stayed materially less reliable even after the fix
  (haiku 4/8, limerick 2/8 across combined runs), against ~100% for every
  other case tested. Read as a strong, specific model prior rather than a
  general problem. New regression coverage
  (`test_a_request_to_write_about_a_visual_subject_does_not_generate_image`)
  covers only the reliably-fixed cases, not the still-flaky ones, and was
  verified against the currently-live Qwen model too (3/3) with no
  regressions elsewhere in the suite.
- Evidence: full backend suite (1175 tests) passes; Ruff passes. Net
  conclusion recorded plainly in `ROADMAP.md`: more encouraging than the
  presentation result, but not sufficient evidence yet to promote this
  engine to `MAIN_LLM_BASE_URL` - the evidence base is single-digit repeats
  per case, and the haiku/limerick gap is real and unresolved.

## 2026-08-14 — Split tool-calling from reply generation; measured a real ~5x latency cost

- Added `ROUTING_LLM_BASE_URL`/`ROUTING_LLM_MODEL`/
  `ROUTING_LLM_REASONING_EFFORT`, falling back to `MAIN_LLM_*` when unset so
  default behaviour is unchanged (full 1175-test suite confirms it).
  `MainActionSelector`'s tool-calling decision and the conversational reply
  (`build_assistant_graph`/`stream_chat`) were already two separate model
  calls internally, just sharing one client - this makes the split real and
  configurable, so a main-model swap for reply quality does not have to also
  inherit that model's untested tool-calling behaviour. Not deployed to
  `docker-compose.yml` yet; this is measurement infrastructure.
- Measured real end-to-end reply latency through the actual code path that
  streams a reply to a user, Qwen vs DeepSeek-V4-Flash, four realistic
  prompts, no mocking: **average 6.4s vs 31.9s, roughly 5x slower**, ranging
  3-10x by query. Time-to-first-token stays close (~0.1s vs ~0.4-1.0s) -
  DeepSeek does not feel stuck at the start, but visibly trickles in far
  slower afterward.
- Verified, not assumed, that DeepSeek's chain-of-thought does not leak into
  the streamed reply: read `stream_chat`'s SSE parsing directly and
  confirmed it only ever reads `delta.content`, never
  `delta.reasoning_content`. A garbled character in the raw measurement
  output (`Here\x92s` instead of a curly apostrophe) was chased to the byte
  level and identified as a Windows-console `print()` encoding artifact in
  the measurement script, not a defect in the model or in `stream_chat` -
  recorded so this false lead is not rediscovered later.
- Full numbers and the latency table are in `ROADMAP.md` Milestone 9.

## 2026-08-14 — Evaluated NVIDIA Nemotron 3 Super the same way: a genuinely mixed result, not a clean win

- Installed Nemotron 3 Super (120B/12.7B active, NVFP4) via official vLLM
  support (`nvcr.io/nvidia/vllm:26.03.post1-py3`) - the lower-risk candidate
  identified after DeepSeek's presentation schema failure: officially
  supported on Spark, native CUDA graphs, real `--enable-auto-tool-choice`
  with a proper parser, not a bespoke community engine. Needed adding
  `animallya96` to the Spark's `docker` group (one-time `sudo`, credential
  given directly by the user, not stored); the container's own startup
  error revealed `ds4-server` from the DeepSeek evaluation was still
  resident holding ~115 of 121 GiB - stopped it and removed its crontab
  entry, since the two models cannot coexist and only one should survive a
  reboot. `--host 0.0.0.0` was set from the start this time.
- Ran the identical three-part evaluation used for DeepSeek. Result is
  genuinely mixed, not a win for either model across the board:
  - Tool-calling: **62/63 (98.4%)** across 3 repeats of the 21-case battery,
    measurably better than DeepSeek - and no haiku/limerick bias at all,
    unlike DeepSeek's persistent gap on exactly those cases.
  - Search-routing recall: **0.7931, fails the 0.85 floor** Qwen already
    clears (DeepSeek: 0.8519, barely passing) - worse on the deliberately
    hard implicit-volatile category specifically.
  - Real reply latency, same code path and prompts as DeepSeek: average
    total 57.6s (DeepSeek: 31.9s), and time-to-first-token averaging ~17s
    (4.5-34.1s, highly variable) against DeepSeek's steady ~0.4-1.0s. vLLM's
    published 22.7-23.7 tok/s figure describes decode throughput once
    generation starts; it says nothing about the substantial, unpredictable
    reasoning time before the first visible token, even at the model's own
    minimum reasoning setting (`"low"` - vLLM rejects AniOS's `"none"`
    default outright with a `400`, a real compatibility gap worth knowing
    before configuring this model's reasoning-effort setting in production).
- Net: official vendor support and a right-sized deployment did not
  translate into a uniformly better model once actually measured - the
  concrete reason this evaluation approach exists rather than choosing by
  spec sheet and vendor reputation. Full numbers and reasoning in
  `ROADMAP.md` Milestone 9. This evaluation does not choose between the two
  models or promote either to `MAIN_LLM_BASE_URL` - that decision is still
  open.

## 2026-08-14 — Promoted DeepSeek-V4-Flash to `MAIN_LLM_BASE_URL` after a blind quality read

- Ran a blind 6-prompt quality comparison (tradeoff reasoning, debugging, multi-step arithmetic, technical depth, judgment, writing) through the real `build_assistant_graph`/`stream_chat` path for Qwen, DeepSeek, and Nemotron, answers shuffled and unlabeled before reading.
- DeepSeek won or tied every category and never failed to answer. Nemotron hard-failed 2 of 6 (zero visible output, entire token budget spent on hidden reasoning) and severely truncated a third on a repeat run - confirms its latency problem is really an unreliability problem. Qwen itself had real quality gaps on the harder prompts: a garbled-text artifact, a debugging answer that never resolved, and a word-problem answer that ran out of budget before reaching a final number.
- Set `MAIN_LLM_BASE_URL`/`MAIN_LLM_MODEL` to DeepSeek-V4-Flash for the `backend` service in `docker-compose.yml`. Explicitly pinned `ROUTING_LLM_BASE_URL`/`ROUTING_LLM_MODEL` to Qwen in the same block so `MainActionSelector`'s tool-calling does not silently follow `MAIN_LLM_*` - DeepSeek's own routing eval passed only barely (recall at the 0.85 floor), so there was no evidence to move it. `PRESENTATION_LLM_*` and `DIAGRAM_LLM_*` stay independently pinned to Qwen, untouched.
- Verified live: `docker exec anios_backend printenv` confirmed the split landed; the real gateway path (`curl -H "Host: deep-matter.com" http://localhost:8080/api/v1/auth/session`) returned `401`, not `502`; a real `stream_chat` call through `get_llm_client()` inside the running `anios_backend` container returned a genuine DeepSeek reply. `ds4-server`'s `@reboot` crontab entry restored now that it backs a production role; `vllm-nemotron` stopped.
- Accepted cost: ~5x Qwen's average reply latency (~32s vs ~6s), taken deliberately given the quality gap measured above. Full reasoning and evidence in `ROADMAP.md` Milestone 9.

## 2026-08-14 — Image uploads answer before reasoning; a standby model covers the Spark being off

- Split the vision upload into a fast reply and a deferred reasoning pass. The endpoint held its connection open for the whole chain (vision model, search decision, search, main model) — about seventeen seconds sending nothing — and a phone that locked during that silence dropped the connection and reported "Load failed" for work the server had completed and stored. The reply now goes out in 2.6s carrying `reasoning_pending`; the reasoning runs afterwards through `BackgroundTasks` on its own session and rewrites the stored answer with `analysis_reasoned` set for the client to poll on.
- Added `GET /api/v1/artifacts/{user_id}/{artifact_id}` so a client can collect an answer produced after its own request finished. The internal storage key is stripped from the response. The frontend polls it and swaps the artifact into the message already on screen rather than appending a second answer to one question.
- Added `FallbackInferenceProvider`: when the main model's host cannot be reached at all, main-role work is served by a standby (`MAIN_LLM_STANDBY_*`, Qwen). The Spark shut down on schedule and took the whole assistant with it — every reply, route and classification raising `httpx.ConnectError` while `vllm-main` sat healthy and unused. Only transport failures fall back, so a model answering with an error still surfaces it; `stream_chat` switches only before its first token, never mid-stream.
- Verified the Spark's `@reboot` autostart against a real power cycle for the first time: `ds4-server` was running within a minute of boot, bound to `0.0.0.0`, and the backend returned to DeepSeek from the standby with no intervention.
- Documented the full role map in `ARCHITECTURE.md` ("Which model answers what"), including why vision and strict-JSON work cannot move to DeepSeek and why routing stays on Qwen for latency despite scoring lower than DeepSeek on accuracy.

## 2026-08-16 — The assistant's capability list now derives from the tool selector

- Replaced the four hardcoded capability bullets in `_build_system_prompt` (`backend/agents/graph.py`) with `_render_capability_context`, which renders whatever `context["capabilities"]` supplies. Each built-in action is now one `BuiltinTool` row in `backend/services/main_action_selector.py` holding the tool name, schema, a conversational `label`, and the `description` — and that single description string is both what the routing model is offered and what the reply prompt is told, so the wording governing conversation and the wording governing routing cannot drift into two answers.
- `MainActionSelector.describe_capabilities()` reads the same `_available_builtins()` list `select()` offers, so a disabled diagram or presentation agent stops being advertised at the same moment it stops being callable. `ConversationService._describe_capabilities` puts it in `context["capabilities"]` beside `context["agents"]`, degrading to an empty list on failure rather than costing the user their reply.
- Two capabilities deliberately do not derive, for stated reasons: `search_web`'s offered description belongs to the live MCP contract rather than to AniOS and reading it would cost a `list_tools` session per turn, so `_SEARCH_CAPABILITY` is AniOS's own sentence gated on the in-memory `can_auto_invoke`; and attaching a text document is handled by the composer directly, is never a tool the router sees, and so has no row to read.
- No routing text changed, proved rather than assumed: an AST comparison against `HEAD` shows all four tool descriptions and `_SYSTEM` byte-identical, and the tool payload `select()` builds at runtime is `json.dumps`-identical to `HEAD`'s, tool order included.
- Evidence: full backend suite (1173 tests, 8 new structural) passes; Ruff and MyPy pass on every changed file. `backend/tests/functional/test_capability_awareness_behaviour.py` (7 tests, 3 new) passes 3/3 consecutive runs against DeepSeek-V4-Flash, the configured reply model, and 4/4 against the Qwen standby.
- Verified on the real deployed path, not a container-internal shortcut: rebuilt and recreated `backend`, restarted `gateway` (401 not 502 through the gateway), and sent a real authenticated `POST /api/v1/chat` through it. The reply named creating, editing, and diagrams while quoting the actual tool descriptions back — "brand-new picture from a text description", "picture currently in view", "not for documents, plans, or schedules", and the six diagram kinds — which is the tuned `edit_image` negative reaching conversation for the first time.
- A negative control with the capability list emptied measured which new assertions actually discriminate: the picture test does (4/4 with, 0/4/1/4 without); the diagram test does not on its loose form and flakes 1-in-15 on its tight form, so it was left loose deliberately with the measurement recorded in the test.

## 2026-08-16 — Image recall was silently dead on DeepSeek; bounded classifiers moved to the routing role

- Found two live, user-facing breakages introduced by the 08-14 `MAIN_LLM_*` promotion, both failing closed so neither ever surfaced an error. `VisualMemorySelector` returned nothing at all: DeepSeek chose the correct picture but answered `{"selected": [...], "reasoning": ...}` where the schema requires `artifact_ids`, so pydantic raised `extra_forbidden` and the code degraded to "no images". `PlaceSuggester` returned an empty tuple on every call. Reproduced 3/3 against DeepSeek and passing 3/3 against Qwen, which is also ~25x faster on these bounded calls (1.6s versus 42s).
- Root cause is the serving engine, not the model: `ds4-server` treats a supplied JSON schema as advisory while vLLM enforces it. This is the third instance of one cause — the 2026-08-14 presentation revert was the same `extra_forbidden` field-naming failure, and pinning presentations to Qwen fixed that call site without the other strict-JSON callers being checked.
- Fixed at the principle: `get_classifier_llm()` and `get_place_suggester()` now follow `ROUTING_LLM_*` rather than `MAIN_LLM_*`. Every caller is a bounded judgement returning strict JSON against an application-owned schema, which is the same contract `MainActionSelector`'s tool-calling has, so it belongs on the routing role rather than on whichever model writes prose. `ROUTING_LLM_*` still falls back to `MAIN_LLM_*` when unset, so an install that configures neither is unchanged.
- Added `backend/tests/test_llm_role_wiring.py` (4 tests) so the role map is asserted rather than trusted, including that a dedicated `SEARCH_CLASSIFIER_MODEL` is served from the routing endpoint and that an unset routing role still falls back to the chat model. Confirmed unaffected: memory proposals and presentations are independently pinned to Qwen, and the discovery worker still runs Qwen, so Scout's sweep-side strict JSON was never involved.
- Evidence: full backend suite (1177 tests) passes; Ruff passes on changed files. Verified in the rebuilt and recreated production container with the gateway restarted (401 not 502): both roles resolve to `vllm-main`/`qwen/qwen3.5-4b`, image recall returns `('portrait',)`, and place suggestion returns both real Raleigh rows.

## 2026-08-16 — Completed the HiDream to FLUX.2 Klein swap, and gave ComfyUI a restart policy

- Finished an in-progress generation-model swap that did not run: `ComfyUIImageProvider.__init__` still assigned `self.negative_prompt` from a parameter the same change had removed, so every construction raised `NameError` and image generation was completely broken. One FLUX.2 Klein checkpoint now serves generation and editing alike, loaded through `UNETLoader`/`CLIPLoader`(`flux2`)/`VAELoader` rather than `CheckpointLoaderSimple`, which does not list it.
- Repaired the configuration chain the swap left inconsistent. `.env` still pinned `IMAGE_MODEL` to the HiDream checkpoint, and because pydantic reads `.env` directly that value won on the host and in tests — pointing both generation *and* editing at a checkpoint absent from `diffusion_models/`. `.env.example` still advertised the three retired `IMAGE_EDIT_*` keys.
- `docker-compose.yml` still passed the retired `IMAGE_EDIT_MODEL`/`IMAGE_EDIT_TEXT_ENCODER`/`IMAGE_EDIT_VAE` and passed none of the new `IMAGE_MODEL`/`IMAGE_TEXT_ENCODER`/`IMAGE_VAE`/`IMAGE_GENERATION_STEPS`, so the new settings could not be configured at all — the environment-allowlist trap this repository has been bitten by before. Also added them to `presentation-worker`, which creates slide imagery through the same provider and had never received any image-model setting: changing `IMAGE_MODEL` would have moved chat images to a new model while leaving slide images on the old one.
- Gave the `comfyui` service `restart: unless-stopped`. It was the only service in the stack without a restart policy, which is exactly how it behaved — the whole stack returned after a reboot and image generation alone did not, with every container reporting healthy. `profiles` gates `up`, not restart, so an existing container now comes back with Docker on its own.
- Added a ComfyUI healthcheck against `/system_stats` rather than `/`, because a ComfyUI whose CUDA context has died keeps answering `/` with 200 while every GPU call fails. Written with `python3`/`urllib` after finding the image ships neither `curl` nor `wget`; a probe that cannot run reports the service unhealthy for the wrong reason.
- Evidence: full backend suite (1190 tests) passes; Ruff passes on every changed file; `docker compose --profile comfyui config` validates. Two real 1024x1024 FLUX generations completed through the actual provider against live ComfyUI (161s, then 235s after container recreation), and the recreated container reports `restart=unless-stopped` with `health=healthy`. Documentation updated where it was operational; ROADMAP and ADR entries naming HiDream are historical records and were left as written.

## 2026-08-16 — Native tool decisions made deterministic

- Reproduced the exact `ani.mallya` Scout confirmation with its real recent history: the unchanged request selected web search 5/10 times, presentation delegation 1/10, and correctly selected no tool only 4/10. `chat_with_tools` omitted temperature, so vLLM used its sampling default for an application decision.
- Set native tool decisions to `temperature: 0.0` at the provider boundary so built-in routing and MCP tool selection cannot silently re-enable sampling at another call site.
- Added provider-contract coverage and a real-model functional regression that repeats the reported Scout confirmation five times. All five now select no external tool, while the existing labelled search-routing quality floor still passes.
- Evidence: 27 structural provider/action/MCP tests pass; both targeted real-model functional tests pass against `qwen/qwen3.5-4b` in 213.55 seconds; Ruff passes. Rebuilt and recreated the backend from the working tree and restarted the gateway. A real authenticated `testuser` chat through the gateway completed with start/delta/done and emitted neither `search_started` nor `image_matches`; its backend trace completed without a web-search routing log.

## 2026-08-16 — Owned artifact retrieval now has a semantic modality gate

- Added a constrained `ArtifactContextRouter` before artifact embedding and candidate lookup. It chooses among image, document, audio and video from meaning rather than keywords; only image retrieval is currently enabled, while the contract leaves the other modalities explicit for later index implementations.
- Kept the visual-memory selector as defense in depth and now collapses selected revision chains and duplicate content before sending image context to the assistant or frontend.
- Added real-model functional cases for personal appearance, prior images, schedules, reminders, general knowledge, new artifact generation and future document/audio/video references, plus structural coverage that an unrelated turn never reaches the embedder or artifact store.
- Verified through authenticated Playwright against the running application: a fresh style question semantically recalled and loaded two owned private images and rendered a grounded response; the exact Scout scheduling regression emitted no visual-memory or search events. Both streams terminated and the composer cleared its loading state with no blocking Console or required-network failure.

## 2026-08-17 — GPU handoff tested and ruled out; a diagram request stops going to the image model

- Tested `GPU_HANDOFF_ENABLED` properly, because generation had slowed to 88-112s against a 6.2s warm run with ComfyUI swapping weights every job. It cannot be used on this runtime: with `--enable-sleep-mode`, `VLLM_SERVER_DEV_MODE=1` and `--kv-cache-dtype auto` all satisfied, `POST /sleep?level=1` hangs past 120s, frees no GPU memory, and leaves `EngineCore` dead until the container is restarted (~150s). Reproduced twice, service restored both times, and recorded on the setting so the slow generations are not chased back to it.
- Corrected `.env.example`, which shipped `VLLM_MAIN_KV_CACHE_DTYPE=fp8` — the exact value `docker-compose.yml` documents as stranding the engine asleep, silently overriding compose's own `auto` default for anyone who copied the file.
- Stopped labelled technical diagrams being drawn by a diffusion model, which was the real cause of a report about poor English in generated images. `"Call create_diagram only when the user explicitly asks"` made the noun decide instead of the subject, so "create an image that describes medallion architecture … using a whiteboard" routed to `generate_image` 3/3 while "draw a diagram of" the same subject routed to `create_diagram` 3/3. Judging by subject moved diagram-shaped requests from 3/12 to 9/12 with picture-shaped requests unaffected at 12/12 and the search-routing floor still passing.
- Distinguished a dropped image job from a stopped one: `RemoteProtocolError`/`ReadTimeout` now say the backend stopped partway and will likely return, rather than falling through to a generic refusal that gave the user nothing to act on.
- Rewrote `NEXT_SESSION.md` around the state the second DGX Spark arrives into, and added two operational traps that each cost real time this session: `.env` silently overriding a raised compose default, and a prompt still asserting a policy that had since changed.

## 2026-08-17 — Unified artifact recall and calibrated uncertain vision answers

- Removed the live regex-plus-classifier image-recall path and its retired settings, modules, and tests. One structured `ArtifactContextRouter` decision now runs before either private image index; approved turns try aligned pixel vectors and then the description-vector/`VisualMemorySelector` fallback, while unrelated turns load neither.
- Made candidate absence explicit to the visual reasoner after a real DeepSeek run invented fish species despite receiving no VLM candidate. Supported high-confidence readings are preserved, weaker readings must remain compatible with their evidence, contradicted candidates may be omitted, and candidate-free uncertainty no longer spends web or main-model reasoning.
- Strengthened the built-in tool-selection gate with per-action floors and explicit stray-edit, no-tool, and diagram-to-generated-image confusion bounds. Corrected current FLUX/model-role documentation and regenerated the affected manager and subsystem diagrams.
- Evidence: the affected real-model functional suites pass 22/22, the complete non-functional backend suite passes 1209 tests, Ruff passes across `backend`, the frontend production build passes, and all 19 canonical diagrams plus the published architecture page are synchronized.

## 2026-08-17 — Short writing replies remain attached to the draft in progress

- Reproduced the latest `jenos1` email thread from persisted turns. Conversation history was intact, but the routing model interpreted `More casual` as an image edit; the missing-image response therefore replaced the expected email rewrite. A preceding date-and-time answer had also invoked web search unnecessarily.
- Tightened the semantic action-selection contract so an answer to the assistant's drafting question, details such as dates, times, quantities and deadlines, and tone or wording revisions continue the recent writing task without a tool. Image edits now require a picture to be the established subject. No keyword or regex router was added.
- Added four real-model writing-follow-up cases spanning requested scheduling details, tone revision, content addition and deadline revision. The complete Qwen tool-selection functional module passes 7/7, and the focused selector/search unit suites pass 30/30.
- Rebuilt the backend from the working tree, recreated it, and restarted the gateway. A four-turn authenticated `testuser` acceptance thread through `POST /api/v1/chat` retained Saturday 8am–7pm and one recipient, produced the draft, and rewrote it casually. All four traces completed; no web-search, MCP tool execution, image-edit or missing-image event appeared in their logs.
