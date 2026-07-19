# AniOS Architecture

This document describes the repository as implemented. Runtime results and active blockers belong in [NEXT_SESSION.md](NEXT_SESSION.md); future delivery sequencing belongs in [ROADMAP.md](ROADMAP.md).

## Status labels

- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: a placeholder or fixed implementation supplies the behavior.
- `PLANNED`: the capability is future work.

The absence of one of these labels does not imply runtime verification.

## Canonical system diagram

![AniOS current system architecture](diagrams/anios-system.svg)

The editable source is [anios-system.mmd](diagrams/anios-system.mmd). It describes current implemented and explicitly scaffolded relationships only, including editable diagrams, generated and uploaded raster artifacts, local binary storage, ComfyUI, Gemma vision analysis, and their browser integration. Multimodal embeddings, durable queues, GPU leases, and multi-agent workers remain outside the current diagram until their runtime boundaries exist. The render/check procedure is documented in [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).

## Detailed subsystem diagrams

AniOS currently has a modular FastAPI backend rather than independently deployed internal microservices. These views expand the actual subsystem boundaries while the full-system diagram remains the deployment-level overview. The [diagram catalog](diagrams/README.md) explains which view to use for common technical questions.

| Current view | Technical scope | Source | SVG |
| --- | --- | --- | --- |
| Runtime and deployment | Processes, ports, protocols, Compose, LM Studio, database sessions, migration and maintenance paths | [source](diagrams/runtime-deployment.mmd) | [view](diagrams/runtime-deployment.svg) |
| Chat orchestration | Request ownership, routing, memory planning, history, LangGraph/Gemma streaming, persistence, proposals, artifact branch, SSE | [source](diagrams/chat-orchestration.mmd) | [view](diagrams/chat-orchestration.svg) |
| Memory subsystem | All short/long-term forms, write authority, coordinator, typed services, pgvector retrieval, lifecycle and operations | [source](diagrams/memory-subsystem.mmd) | [view](diagrams/memory-subsystem.svg) |
| Tool memory | Safe descriptors, approved preferences, sanitized outcomes, embeddings, toolbox context, non-execution boundary | [source](diagrams/tool-memory-subsystem.mmd) | [view](diagrams/tool-memory-subsystem.svg) |
| Visual artifacts | Diagram classification/rendering, HiDream generation, validated uploads, opaque binary storage, integrity/deletion, and Gemma vision analysis | [source](diagrams/visual-artifact-subsystem.mmd) | [view](diagrams/visual-artifact-subsystem.svg) |
| Architecture maintenance | Explicit repository evidence, local Gemma candidate generation, passive/required-label validation, pinned rendering, review, and manual canonical promotion | [source](diagrams/architecture-maintenance-subsystem.mmd) | [view](diagrams/architecture-maintenance-subsystem.svg) |
| Frontend | Identity/conversation state, view lifecycle, chat components, memory management, typed API/SSE client, diagram rendering | [source](diagrams/frontend-subsystem.mmd) | [view](diagrams/frontend-subsystem.svg) |

## Runtime topology

`docker-compose.yml` defines three services:

| Service | Implementation | Host port | Current architectural role |
| --- | --- | --- | --- |
| `backend` | FastAPI/Uvicorn image built from the root `Dockerfile` | `8000` | HTTP API |
| `db` | `pgvector/pgvector:pg16` | `5432` | PostgreSQL conversation/personal-memory persistence and pgvector semantic search |
| `redis` | `redis:7-alpine` | `6379` | `SCAFFOLDED`: container exists; backend code does not use a Redis client |

The frontend is not a Compose service. It runs separately from `frontend/` with Vite on port `5173`. The backend image has no source bind mount and does not use reload mode, so source changes require an image rebuild for container validation.

LM Studio is an external local process rather than a Compose service. The host-source backend defaults to `http://127.0.0.1:1234`, selects `google/gemma-4-12b` for chat and validated image understanding, and selects `text-embedding-nomic-embed-text-v1.5` for 768-dimensional text embeddings. ComfyUI is a second external loopback process at `127.0.0.1:8188`; the selected local provider is `hidream_o1_image_dev_fp8_scaled.safetensors`. Generated and uploaded bytes live below the configurable opaque local artifact root; Compose mounts `/app/data/artifacts` from the `artifactdata` volume.

## Backend boundaries

### Presentation

`backend/main.py` constructs the FastAPI application, allows CORS from the local Vite origins, mounts the v1 router at `/api/v1`, and defines `GET /health`.

`backend/api/v1/api.py` defines:

- `GET /api/v1/`;
- `POST /api/v1/chat`, which validates a typed `ChatRequest` and returns Server-Sent Events named `start`, `delta`, optional `memory_proposal`, optional `artifact_started`/`artifact_ready`/`artifact_error`, and `done`. A streaming failure is logged server-side and returned as a sanitized `error` event.

`backend/api/v1/memory.py` defines user-scoped profile, generic approved-fact lifecycle, preferred-name approval/deletion, episodic/semantic create-correct-search-delete, export, and delete-all endpoints beneath `/api/v1/memory/{user_id}`. `backend/api/v1/agent_memory.py` adds typed semantic-cache, working-memory, procedure, entity/relation, knowledge-document/chunk, conversation-summary, retention, re-embedding, operations, and per-record deletion routes beneath `/api/v1/memory/{user_id}/agent`. Approved facts carry source conversation/trace provenance; normalization deduplicates equal values, contradictions create a superseding version, and supported `preferred_name`/`response_style` keys project into `user_profiles`. Export and delete-all cover conversation, personal, tool, and agent-memory tables.

`backend/api/v1/artifacts.py` lists recent owned artifacts, returns owned binary content with private/no-store and nosniff headers, and deletes both the database row and binary file. Explicit diagram requests create a pending record before provider work and stream a sanitized terminal success or failure lifecycle. If the client disconnects after pending persistence, the application shields only the terminal cleanup write, marks the record failed with `cancelled`, and re-raises cancellation.

`backend/api/v1/images.py` accepts a bounded prompt and one allowlisted HiDream training resolution, then returns a terminal generated-image artifact. `backend/api/v1/vision.py` streams a bounded multipart upload, validates actual PNG/JPEG/WebP content, rejects animation, MIME mismatch, excess bytes, and excess pixels, persists the owned upload, and sends only the validated image plus bounded prompt to the configured local vision provider. Invalid uploads create no artifact; VLM failure preserves the valid upload with `analysis_status=failed` for later deletion or retry work.

The image-generation handler monitors HTTP disconnects around provider work. A browser cancellation cancels the service task, interrupts the matching ComfyUI prompt, shields the terminal `failed/cancelled` write, and finishes without an application exception. The React composer exposes Chat, Create image, and Analyze image modes with progress, cancellation, retained retry input, visible API failures, and bounded file selection. `ImageArtifact` fetches private bytes with the optional auth header, renders a temporary object URL, exposes grounded Gemma text, and supports local download and owned deletion. Conversation hydration and artifact history restore both diagrams and binary images.

`backend/api/v1/conversations.py` returns a bounded, user-owned conversation snapshot containing persisted turns and their conversation artifacts. The frontend uses that read boundary to reconstruct the active transcript and ready/failed diagram cards after a full reload.

Every chat and memory route applies the optional signed-user ownership boundary. Authentication is disabled by default for trusted-local development; when enabled, the token subject must equal the body or path user ID.

### Services and dependency assembly

`backend/core/dependencies.py` assembles `ConversationService` and its collaborators through FastAPI dependencies.

The active collaborators are:

| Component | Status | Implemented reality |
| --- | --- | --- |
| `ConversationService` | implemented local boundary | Obtains a memory query plan, loads selected context plus bounded same-user history, streams an injected model through LangGraph, persists the response, and updates memory lifecycle state |
| `PostgresMemoryService` | implemented local boundary | Supports profile upsert, episodic save/read, live embedding generation, pgvector semantic save/search, snapshots, and scoped deletion |
| `AgentMemoryManager` | implemented typed store facade | Owns user-scoped semantic-cache, working, procedure, entity/relation, knowledge, and summary stores without exposing raw tables to the coordinator or model |
| `MemoryCoordinatorAgent` | implemented deterministic policy boundary | Classifies memory intent, caches the typed plan, queries only selected stores, curates bounded prompt context, writes expiring session state, and periodically rolls conversation digests |
| `ToolMemoryService` | implemented safe metadata boundary | Stores and retrieves user-scoped safe tool descriptors, approved preferences, and sanitized outcomes; it cannot invoke or authorize tools |
| `DiagramAgent` | implemented specialized LangGraph boundary | Runs one typed `generate_diagram` node around the replaceable provider; it has no persistence, authorization, or hardware-management authority |
| `DiagramArtifactService` | implemented local artifact boundary | Coordinates pending/ready/failed diagram records, invokes a replaceable bounded diagram provider, and never gives the model persistence authority |
| `ImageArtifactService` | implemented local binary artifact boundary | Coordinates generated/uploaded pending/ready/failed records, opaque atomic file storage, SHA-256/size integrity checks, owned content reads, and file-plus-row deletion |
| `ComfyUIImageProvider` | implemented free local provider | Submits a pinned HiDream-O1 Dev workflow through ComfyUI, polls terminal history, fetches one output, validates it, and limits concurrent jobs to one |
| `VisionAnalysisService` | implemented local VLM boundary | Persists a validated upload before sending its bytes and bounded prompt through the replaceable Gemma vision adapter, then records ready/failed analysis metadata |
| `ArchitectureCandidateService` | implemented review-only maintenance boundary | Combines registered canonical source with bounded explicit repository evidence, requires selected visible labels, and returns a candidate without canonical write authority |
| `SQLAlchemyArtifactRepository` | implemented user-scoped persistence boundary | Stores diagram source, lifecycle, conversation/trace provenance, provider/model metadata, and supports conversation listing plus individual deletion |
| `SQLAlchemyConversationRepository` | implemented local boundary | Saves and counts turns under stable conversation IDs and reads a configured newest-turn window filtered by both conversation ID and user ID, returned in chronological order |
| `LoggingConversationTracer` | implemented local boundary | Generates a new trace UUID for each request and records lifecycle events through application logging |

Internet, notification, tool-execution, and external-agent collaborators are not part of current dependency assembly. Knowledge ingestion/retrieval is implemented as a local memory store; a complete RAG pipeline remains `SCAFFOLDED`.

Chat memory capture is a narrow deterministic approval boundary. The conversation service recognizes explicit preferred-name, response-style, person/relationship, reusable workflow, and titled-reference statements and emits at most one typed proposal only after the conversation turn is saved; the proposal itself is not persisted. The frontend explicitly approves or rejects it. Approval uses the existing typed store API with source conversation/trace provenance. The model never receives a durable-write tool, and unrestricted implicit fact extraction remains intentionally unsupported.

### Agent orchestration

AniOS has two focused LangGraph workflows: the ordinary assistant graph contains one streaming Gemma node, while `DiagramAgent` contains one asynchronous `generate_diagram` node around `DiagramProvider`. Before the assistant graph runs, the deterministic `MemoryCoordinatorAgent` produces a typed query plan and retrieves bounded working, episodic, semantic, entity, knowledge, summary, procedure, and toolbox context as applicable. Retrieved values are serialized as untrusted literal data; they cannot add instructions or grant permissions. Neither graph owns persistence or hardware policy. Tool executor, researcher, reflection, image worker, and general multi-agent graph nodes remain `PLANNED`.

### LLM integration

`backend/core/llm.py` implements LM Studio's OpenAI-compatible `/v1/chat/completions` contract for buffered and streamed generation. Dependency assembly injects this client into the graph. The client preserves the complete ordered `messages` list so system, prior user/assistant, and current-user messages reach Gemma, explicitly configures `reasoning_effort` (default `none`) so the local reasoning model reserves output for a visible answer, yields only assistant content deltas, and requires terminal `[DONE]`. Other providers remain `PLANNED`.

Explicit diagram requests bypass ordinary memory retrieval and the assistant graph, then run through the dedicated `DiagramAgent` graph. `LLMDiagramProvider` asks the same configured local model for a bounded JSON/Mermaid specification, performs one correction retry for malformed local-model formatting, and accepts only allowlisted diagram declarations and passive source within size/line limits. The provider is behind `DiagramProvider`; the application owns routing, validation, persistence, and lifecycle events.

The maintainer-only architecture candidate command uses the same agent/provider boundary but remains outside the HTTP runtime. `ArchitectureCandidateService` reads the registered canonical source plus only explicitly selected, bounded repository text. The CLI requires a loopback LM Studio endpoint; rejects traversal, common secret-bearing names, unsupported types, existing outputs, and canonical output paths; can require implementation-backed visible labels with one bounded semantic correction; and invokes the pinned Mermaid renderer. Output is a new review candidate only. Technical and visual review, followed by an explicit manual canonical edit or promotion, remains mandatory because label presence and syntax cannot prove relationship accuracy.

`backend/embeddings/lm_studio.py` implements LM Studio's OpenAI-compatible `/v1/embeddings` boundary. Nomic document/query task prefixes are applied and the configured 768-value dimension is validated before persistence or search.

### Persistence

SQLAlchemy models exist for conversations, profiles/facts, episodic/semantic memory, safe tool memory, semantic cache, working memory, procedures, entities/relations, knowledge documents/chunks, conversation summaries, and visual artifacts. Persistence has the following implemented boundaries:

- all models use `backend.database.session.Base`;
- Alembic targets that metadata; head `20260718_0011` extends the user-scoped visual-artifact lifecycle with generated/uploaded kinds plus opaque storage key, byte size, SHA-256, and dimensions on top of the typed memory tables, capture provenance, and pgvector HNSW indexes;
- FastAPI, conversation, memory, coordinator, and operational paths use injected SQLAlchemy `AsyncSession` transactions through `asyncpg`;
- runtime uses a bounded async queue pool, while the synchronous psycopg2 engine is retained only for Alembic and explicit inspection/test utilities;
- episodic and semantic writers map caller metadata to the models' `extra_data` columns;
- semantic embedding and cosine-distance retrieval are operational through the injected provider;
- every current user-owned memory table participates in JSON export and delete-all; knowledge documents also have a scoped individual deletion path.

PostgreSQL transaction advisory locks serialize natural-key writes. An async acceptance test runs six real PostgreSQL waits through a two-connection bounded pool while an event-loop heartbeat continues; it verifies a peak of two checked-out connections and complete pool drain. Transaction-abort and pool-timeout tests prove rollback/reuse and checkout recovery. The shared LM Studio embedding adapter serializes requests by default because mixed load proved that the local provider returns HTTP 400 under concurrent embedding calls; the limit is configurable after provider validation.

An opt-in Compose maintenance service applies retention, optionally refreshes stale vectors, performs final inspection, emits non-content JSON monitoring events, and continues after transient interval failures. The operations API also exposes Prometheus-compatible counts, expiry backlog, stale vectors, invariants, database latency, and a binary health gauge. A configurable live soak mixes chat, working-memory reads/writes, and health inspection through the public API and cleans its isolated user afterward.

PostgreSQL and pgvector persist all durable and expiring memory forms. Vector stores use 768-dimensional embeddings with HNSW cosine indexes; retrieval applies user scope, approval/active/expiry filters, cosine-distance thresholds, and result limits before prompt use. Oracle-specific IVF helpers are not used: schema and indexes are owned by SQLAlchemy metadata and Alembic. `backend/core/auth.py` provides optional expiring HMAC-signed local tokens; auth-disabled local development retains caller-supplied logical scoping.

The model vector type follows the validated `EMBEDDING_DIMENSION` setting. Offline dimension changes use resumable `embedding_next` shadow columns across semantic memory, cache, procedures, entities, knowledge chunks, summaries, and tool descriptors. Batches commit without replacing the authoritative old vectors; after all shadow rows validate, one PostgreSQL transaction locks and switches every pending table, updates embedding metadata, and rebuilds each HNSW cosine index. Provider/backfill failure therefore leaves old vectors usable and the shadow work resumable.

## Frontend

The React frontend contains a responsive light-neutral shell with search-first Chat, Personal Memory, and Visual Artifacts views. Empty chat centers one dominant query composer; active chat presents each user query and assistant response as a left-aligned result flow rather than opposing message bubbles. Request trace/conversation identifiers remain available through an answer-level three-dot metadata popover instead of the primary answer text. The native font stack selects SF Pro through the Apple system aliases where available and the platform `system-ui` font elsewhere; the composer explicitly inherits that same stack. The memory screen explicitly applies user changes, cancels obsolete reads, edits profile/preferences, lists and deletes records, confirms delete-all, keeps manual event/fact creation behind an advanced plain-language disclosure, and renders live counts for every implemented short- and long-term memory form. Chat parses the text, memory-proposal, and artifact SSE lifecycles. Assistant text is rendered as styled CommonMark through ReactMarkdown with raw HTML interpretation disabled, while user messages remain literal text. Chat lazily loads Mermaid only for ready diagrams, renders under strict settings with HTML labels disabled, exposes editable source, and shows generation/render failures. The Artifacts view lists recent owned ready diagrams, reuses strict rendering, downloads Mermaid or the locally rendered SVG without another provider call, exposes refresh/load failures, and deletes owned records. The browser persists a conversation ID across reloads/views, keeps the in-memory transcript mounted across view switches, restores a bounded owned transcript and its diagram artifacts after a full reload, rotates it through `New conversation`, and clears the visible transcript when either the user or conversation changes.

The trusted-local developer UI defaults a missing or legacy `dev_user_001` browser identity to `ani.mallya` and rotates the legacy conversation ID. Any other stored user/conversation identity is preserved. This is local UI convenience, not authentication.

Conversation selection/history browsing and configuration screens are not implemented; reload restoration currently targets the active locally stored conversation ID.

## Automated validation

Backend tests cover LM Studio chat/embedding contracts, streaming, bounded same-user chronological history, coordinator routing/caching, rolling summaries, every typed memory API, diagram-agent validation/lifecycle/routing, repository candidate boundaries, retention, re-embedding rollback, concurrency, operational inspection, PostgreSQL/pgvector persistence, scoping, export, and deletion. Playwright covers deterministic chat/memory/diagram workflows and separately gated live Gemma/Nomic acceptance, including a persisted real-model Mermaid artifact rendered in Chromium. There is no component-test framework.

The intended validation layers are:

| Layer | Status | Responsibility |
| --- | --- | --- |
| Backend unit and integration tests | `SCAFFOLDED` | Validate service behavior, API boundaries, streaming, and persistence with controlled dependencies |
| Frontend component tests | `PLANNED` | Validate rendering and interaction states in isolated components |
| Automated browser tests | implemented | Playwright covers chat success/failure, safe semantic Markdown rendering, diagram success/failure, navigation retention, conversation identity, memory management, and loading cleanup |
| Live-provider acceptance | implemented opt-in | Proves Gemma streaming, persisted diagram rendering, and same-conversation recall plus Nomic persistence, reload, recall, and deletion |

Deterministic browser tests should use a controlled backend or fake LLM response for repeatability. That proves application behavior, not live-model connectivity; live-provider verification remains a separate acceptance layer.

## Intended conversation flow

The current scaffold expresses this intended flow:

```text
Frontend -> POST /api/v1/chat -> FastAPI dependency assembly
         -> ConversationService -> MemoryCoordinatorAgent -> typed stores
         -> curated memory context -> LangGraph
         -> conversation repository -> streamed response

Explicit diagram request -> ConversationService -> DiagramArtifactService
                         -> pending artifact -> DiagramAgent -> local provider
                         -> validated Mermaid source -> ready/failed artifact SSE
                         -> strict in-browser SVG rendering

Architecture maintenance -> explicit repository evidence -> ArchitectureCandidateService
                         -> DiagramAgent -> validated candidate Mermaid and SVG
                         -> technical/visual review -> manual canonical update
```

Current host-source validation completes this flow through Gemma, a bounded same-user history window, and personal memory. Current runtime evidence is recorded in [NEXT_SESSION.md](NEXT_SESSION.md).

## Capability boundaries

- Personal profile, episodic memory, relevance-gated semantic search, management/export/correction/deletion UI, and optional signed user authentication: functionally implemented; auth is disabled by default for trusted-local development.
- Local knowledge-document ingestion, deterministic chunking, embedding, semantic retrieval, prompt curation, export, and deletion: implemented. Hybrid retrieval, reranking, source-citation policy, file connectors, ingestion jobs, and GraphRAG remain `PLANNED`.
- Signed local-user route ownership: implemented when enabled. Password login, account management, token revocation, and external identity providers: `PLANNED`.
- Internet search, its privacy decision gate, notifications, calendar, email, voice, mobile clients, autonomous agents, and multi-agent workflows: `PLANNED`.
- Explicit Mermaid diagram generation through a dedicated diagram graph, user-scoped lifecycle/history/deletion, strict rendering, reload restoration, local Mermaid/SVG export, and disconnect recovery: implemented and browser/direct-client verified. Free local raster generation, bounded upload, opaque binary storage, owned content/deletion, Gemma image understanding, browser progress/retry/cancel, private rendering, navigation/reload restoration, history, download, and deletion are implemented and direct/live-browser verified. Review-only local Gemma architecture candidates remain implemented and never update canonical source automatically. Automated retention/export, multimodal embeddings, durable queues, GPU resource leasing/transitions, and generalized image agents remain `PLANNED`.
- Semantic safe-descriptor discovery and user-scoped approved preference/sanitized outcome memory: implemented. MCP connectivity, authoritative live-registry synchronization, permissions, and invocation remain `PLANNED`; tool memory cannot authorize execution.

## Architectural decision

The project has adopted clean-architecture and dependency-inversion principles as a design direction. [ADR 0001](adr/0001-clean-architecture-and-modular-structure.md) records that direction. [ADR 0002](adr/0002-typed-agent-memory-manager-and-pgvector-indexes.md) records the typed store-manager/coordinator boundary and the pgvector HNSW indexing choice. [ADR 0003](adr/0003-local-visual-artifacts-and-resource-aware-orchestration.md) records the local-only visual-artifact, GPU-resource, and scalable orchestration direction; editable diagrams, raster generation, binary storage, upload validation, VLM analysis, and browser integration are implemented while deterministic resource orchestration remains `PLANNED`.
