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
