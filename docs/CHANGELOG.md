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
