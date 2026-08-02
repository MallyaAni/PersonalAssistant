# Changelog

This file is append-only history for meaningful, verified changes. It must not contain plans, active blockers, speculative work, or implementation-complete claims based only on source inspection.

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
