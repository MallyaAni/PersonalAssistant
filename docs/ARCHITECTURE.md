# AniOS Architecture

This document describes the repository as implemented. Runtime results and active blockers belong in [NEXT_SESSION.md](NEXT_SESSION.md); future delivery sequencing belongs in [ROADMAP.md](ROADMAP.md).

## Status labels

- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: a placeholder or fixed implementation supplies the behavior.
- `PLANNED`: the capability is future work.

The absence of one of these labels does not imply runtime verification.

## Runtime topology

`docker-compose.yml` defines three services:

| Service | Implementation | Host port | Current architectural role |
| --- | --- | --- | --- |
| `backend` | FastAPI/Uvicorn image built from the root `Dockerfile` | `8000` | HTTP API |
| `db` | `pgvector/pgvector:pg16` | `5432` | PostgreSQL conversation/personal-memory persistence and pgvector semantic search |
| `redis` | `redis:7-alpine` | `6379` | `SCAFFOLDED`: container exists; backend code does not use a Redis client |

The frontend is not a Compose service. It runs separately from `frontend/` with Vite on port `5173`. The backend image has no source bind mount and does not use reload mode, so source changes require an image rebuild for container validation.

LM Studio is an external local process rather than a Compose service. The host-source backend defaults to `http://127.0.0.1:1234`, selects `google/gemma-4-12b` for chat, and selects `text-embedding-nomic-embed-text-v1.5` for 768-dimensional embeddings.

## Backend boundaries

### Presentation

`backend/main.py` constructs the FastAPI application, allows CORS from the local Vite origins, mounts the v1 router at `/api/v1`, and defines `GET /health`.

`backend/api/v1/api.py` defines:

- `GET /api/v1/`;
- `POST /api/v1/chat`, which validates a typed `ChatRequest` and returns Server-Sent Events named `start`, `delta`, optional `memory_proposal`, and `done`. A streaming failure is logged server-side and returned as a sanitized `error` event.

`backend/api/v1/memory.py` defines user-scoped profile, preferred-name approval/deletion, episodic/semantic create-correct-search-delete, export, and delete-all endpoints beneath `/api/v1/memory/{user_id}`. Preferred-name approval writes a `memory_facts` version containing approval/lifecycle state and source conversation/trace provenance while retaining `user_profiles.name` as a compatibility projection. Correction supersedes the previous fact version; name deletion removes all name-fact versions and clears the projection. Personal delete-all also propagates to conversation and tool-memory tables.

Authentication is not implemented on these routes.

### Services and dependency assembly

`backend/core/dependencies.py` assembles `ConversationService` and its collaborators through FastAPI dependencies.

The active collaborators are:

| Component | Status | Implemented reality |
| --- | --- | --- |
| `ConversationService` | implemented local boundary | Loads profile/episodic/semantic context plus bounded same-user conversation history, streams an injected model through LangGraph, accumulates the response, and persists it under a stable conversation ID |
| `PostgresMemoryService` | implemented local boundary | Supports profile upsert, episodic save/read, live embedding generation, pgvector semantic save/search, snapshots, and scoped deletion |
| `SQLAlchemyConversationRepository` | implemented local boundary | Saves turns under stable conversation IDs and reads a configured newest-turn window filtered by both conversation ID and user ID, returned in chronological order |
| `LoggingConversationTracer` | implemented local boundary | Generates a new trace UUID for each request and records lifecycle events through application logging |

Earlier no-op knowledge, internet, notification, tool, context-builder, and streamer collaborators are not part of current dependency assembly. Those capabilities remain `PLANNED`, not mocked runtime behavior.

Preferred-name capture is a narrow implemented approval boundary. The conversation service recognizes supported “my name is”/“call me” statements and emits a proposal only after the conversation turn is saved; the proposal itself is not persisted. The frontend explicitly approves or rejects it. Approval writes the existing user profile name while preserving preferences, correction overwrites that value, and deletion clears only the name. General fact extraction remains `PLANNED`.

### Agent orchestration

LangGraph currently contains one model-backed assistant node. The node receives bounded profile/preferences plus episodic/semantic content as explicitly untrusted data, followed by the configured chronological conversation-history window and current query. It calls the injected LLM client and publishes message deltas with LangGraph's custom stream writer. Tool executor, researcher, reflection, sub-agent, and multi-agent nodes remain `PLANNED`.

### LLM integration

`backend/core/llm.py` implements LM Studio's OpenAI-compatible `/v1/chat/completions` contract for buffered and streamed generation. Dependency assembly injects this client into the graph. The client preserves the complete ordered `messages` list so system, prior user/assistant, and current-user messages reach Gemma, explicitly configures `reasoning_effort` (default `none`) so the local reasoning model reserves output for a visible answer, yields only assistant content deltas, and requires terminal `[DONE]`. Other providers remain `PLANNED`.

`backend/embeddings/lm_studio.py` implements LM Studio's OpenAI-compatible `/v1/embeddings` boundary. Nomic document/query task prefixes are applied and the configured 768-value dimension is validated before persistence or search.

### Persistence

SQLAlchemy models exist for conversations, profiles, episodic memory, and semantic memory. Persistence is `SCAFFOLDED`:

- all models use `backend.database.session.Base`;
- Alembic targets that metadata; revisions `20260716_0002` and `20260716_0003` add user-scoped 768-dimensional semantic vectors and stable conversation IDs;
- the current conversation path uses a synchronous SQLAlchemy session consistently;
- episodic and semantic writers map caller metadata to the models' `extra_data` columns;
- semantic embedding and cosine-distance retrieval are operational through the injected provider;
- profile, episodic, and semantic records expose user-scoped deletion paths.

The FastAPI handlers are asynchronous but the current SQLAlchemy session and repository operations are synchronous. That is acceptable for the verified local scaffold but can block the event loop under concurrent production load. Async database access, service-level transaction boundaries, and concurrency/load validation remain production requirements.

PostgreSQL and pgvector persist conversations, personal memory, safe MCP tool descriptors, approved tool preferences, and sanitized tool outcomes. Semantic and tool-descriptor searches apply user scope, active/expiry filters, cosine-distance thresholds, and result limits before context use. `backend/core/auth.py` provides optional expiring HMAC-signed local tokens; with `AUTH_REQUIRED=true`, the token subject must match every chat body or memory path user ID. Auth-disabled local development retains caller-supplied logical scoping.

## Frontend

The React frontend contains a responsive light-neutral shell with a search-first chat view and Personal Memory view. Empty chat centers one dominant query composer; active chat presents each user query and assistant response as a left-aligned result flow rather than opposing message bubbles. Request trace/conversation identifiers remain available through an answer-level three-dot metadata popover instead of the primary answer text. The native font stack selects SF Pro through the Apple system aliases where available and the platform `system-ui` font elsewhere; the composer explicitly inherits that same stack. The memory screen explicitly applies user changes, cancels obsolete reads, edits profile/preferences, lists and deletes records, confirms delete-all, and keeps manual event/fact creation behind an advanced plain-language disclosure. Chat parses the SSE contract, appends message deltas, persists a conversation ID across reloads/views, keeps the in-memory transcript mounted across Chat/Memory view switches, rotates it through `New conversation`, and clears the visible transcript when either the user or conversation changes.

The trusted-local developer UI defaults a missing or legacy `dev_user_001` browser identity to `ani.mallya` and rotates the legacy conversation ID. Any other stored user/conversation identity is preserved. This is local UI convenience, not authentication.

Conversation history restoration after a full browser reload and configuration screens are not implemented.

## Automated validation

Backend tests cover LM Studio chat/embedding contracts, streaming, bounded same-user chronological history, conversation identity, memory services/APIs, PostgreSQL/pgvector persistence, scoping, and deletion. Playwright covers deterministic chat/memory workflows and separately gated live Gemma/Nomic acceptance, including real same-conversation recall. There is no component-test framework.

The intended validation layers are:

| Layer | Status | Responsibility |
| --- | --- | --- |
| Backend unit and integration tests | `SCAFFOLDED` | Validate service behavior, API boundaries, streaming, and persistence with controlled dependencies |
| Frontend component tests | `PLANNED` | Validate rendering and interaction states in isolated components |
| Automated browser tests | implemented | Playwright covers chat success/failure, conversation identity, memory management, and loading cleanup |
| Live-provider acceptance | implemented opt-in | Proves Gemma streaming and same-conversation recall plus Nomic persistence, reload, recall, and deletion |

Deterministic browser tests should use a controlled backend or fake LLM response for repeatability. That proves application behavior, not live-model connectivity; live-provider verification remains a separate acceptance layer.

## Intended conversation flow

The current scaffold expresses this intended flow:

```text
Frontend -> POST /api/v1/chat -> FastAPI dependency assembly
         -> ConversationService -> memory context -> LangGraph
         -> conversation repository -> streamed response
```

Current host-source validation completes this flow through Gemma, a bounded same-user history window, and personal memory. Current runtime evidence is recorded in [NEXT_SESSION.md](NEXT_SESSION.md).

## Capability boundaries

- Personal profile, episodic memory, relevance-gated semantic search, management/export/correction/deletion UI, and optional signed user authentication: functionally implemented; auth is disabled by default for trusted-local development.
- RAG, ingestion, hybrid retrieval, reranking, and GraphRAG: `PLANNED`; an embedding-provider boundary exists for personal memory, but there is no document retriever or RAG pipeline.
- Signed local-user route ownership: implemented when enabled. Password login, account management, token revocation, and external identity providers: `PLANNED`.
- Internet search, its privacy decision gate, notifications, calendar, email, voice, mobile clients, autonomous agents, and multi-agent workflows: `PLANNED`.
- Semantic safe-descriptor discovery and user-scoped approved preference/sanitized outcome memory: implemented. MCP connectivity, authoritative live-registry synchronization, permissions, and invocation remain `PLANNED`; tool memory cannot authorize execution.

## Architectural decision

The project has adopted clean-architecture and dependency-inversion principles as a design direction. The decision and its tradeoffs are recorded in [ADR 0001](adr/0001-clean-architecture-and-modular-structure.md). Existing code only partially realizes that decision.
