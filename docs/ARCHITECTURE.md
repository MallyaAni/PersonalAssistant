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
| `db` | `pgvector/pgvector:pg16` | `5432` | PostgreSQL and future vector persistence |
| `redis` | `redis:7-alpine` | `6379` | `SCAFFOLDED`: container exists; backend code does not use a Redis client |

The frontend is not a Compose service. It runs separately from `frontend/` with Vite on port `5173`. The backend image has no source bind mount and does not use reload mode, so source changes require an image rebuild for container validation.

## Backend boundaries

### Presentation

`backend/main.py` constructs the FastAPI application, allows CORS from the local Vite origins, mounts the v1 router at `/api/v1`, and defines `GET /health`.

`backend/api/v1/api.py` defines:

- `GET /api/v1/`;
- `POST /api/v1/chat`, which accepts a raw JSON request and returns a `StreamingResponse` declaration.

Authentication is not implemented on these routes.

### Services and dependency assembly

`backend/core/dependencies.py` assembles `ConversationService` and its collaborators through FastAPI dependencies.

The collaborators have different maturity levels:

| Component | Status | Implemented reality |
| --- | --- | --- |
| `ConversationService` | `SCAFFOLDED` | Loads memory context, invokes the fixed placeholder graph, persists a turn, and yields one response chunk |
| `PostgresMemoryService` | `SCAFFOLDED` | Profile and episodic reads use the injected synchronous session; semantic retrieval returns an empty list; broader memory writes remain incomplete |
| `SQLAlchemyConversationRepository` | `SCAFFOLDED` | Saves and reads conversation records; metadata is not mapped correctly because the model field is named `extra_data` |
| Knowledge service | `MOCKED` | Returns no knowledge results |
| Internet service | `MOCKED` | Returns no search results |
| Notification service | `MOCKED` | Performs no action |
| Tool service | `MOCKED` | Returns a fixed mock result |
| Context builder | `MOCKED` | Returns only the user ID and query |
| Tracer | `MOCKED` | Generates a UUID and prints trace steps |
| Streamer | `MOCKED` | Wrapper exists but is not used by `ConversationService.process_request` |

### Agent orchestration

LangGraph is present, but the graph is `MOCKED`. `backend/agents/graph.py` contains one assistant node that returns the fixed text `Thinking...`. Tool executor, researcher, reflection, and multi-agent nodes are `PLANNED`.

### LLM integration

`backend/core/llm.py` defines an abstraction and an OpenAI-compatible class, but the concrete generation methods have no implementation and no LLM client is injected into the conversation path. LM Studio and other OpenAI-compatible providers are `SCAFFOLDED`; model-backed answers are `PLANNED`.

### Persistence

SQLAlchemy models exist for conversations, profiles, episodic memory, and semantic memory. Persistence is `SCAFFOLDED`:

- all models use `backend.database.session.Base`;
- Alembic targets that metadata and includes initial revision `20260716_0001` for PostgreSQL and pgvector;
- the current conversation path uses a synchronous SQLAlchemy session consistently;
- some broader memory write methods still use incorrect `metadata` constructor names, and semantic retrieval is not operational.

PostgreSQL and pgvector infrastructure exist. A conversation turn can be persisted through the current placeholder chat path, but complete conversation retrieval and personal-memory behavior remain `SCAFFOLDED`.

## Frontend

The React frontend is `SCAFFOLDED`. It contains a sidebar, chat window, composer, message list, and an unused developer panel with mock metrics. `frontend/src/services/api.ts` sends JSON to `/api/v1/chat` and reads response bytes as a stream. It uses `VITE_API_URL` with `http://localhost:8000` as the default. The composer clears its loading state on completion and renders a user-visible message for handled request failures. A TypeScript project configuration supports the production build.

Conversation history navigation, configuration screens, memory logs, and complete multi-chunk accumulation are not implemented. Each received chunk currently replaces the assistant message content instead of appending to it.

## Automated validation

Backend tests under `backend/tests` include targeted chat API and service coverage, while the older memory-service module still fails during fixture setup. The frontend package defines `dev`, `build`, and `preview` scripts only. It has no component-test script, browser automation dependency, browser configuration, or committed end-to-end UI test.

The intended validation layers are:

| Layer | Status | Responsibility |
| --- | --- | --- |
| Backend unit and integration tests | `SCAFFOLDED` | Validate service behavior, API boundaries, streaming, and persistence with controlled dependencies |
| Frontend component tests | `PLANNED` | Validate rendering and interaction states in isolated components |
| Automated browser tests | `PLANNED` | Exercise complete user workflows, network behavior, rendered results, console errors, and persistence across navigation or reload |
| Live-provider acceptance | `PLANNED` | Separately prove that a configured non-mock LLM provider is called and returns a non-placeholder result |

Deterministic browser tests should use a controlled backend or fake LLM response for repeatability. That proves application behavior, not live-model connectivity; live-provider verification remains a separate acceptance layer.

## Intended conversation flow

The current scaffold expresses this intended flow:

```text
Frontend -> POST /api/v1/chat -> FastAPI dependency assembly
         -> ConversationService -> memory context -> LangGraph
         -> conversation repository -> streamed response
```

Current host-source validation completes this flow through the fixed placeholder graph and conversation persistence. It does not establish live-model integration or complete memory behavior. Current runtime evidence and failures are recorded in [NEXT_SESSION.md](NEXT_SESSION.md).

## Capability boundaries

- Personal profile and episodic memory: `SCAFFOLDED`.
- Semantic memory and embeddings: `SCAFFOLDED`; operational vector retrieval is `PLANNED`.
- RAG, ingestion, hybrid retrieval, reranking, and GraphRAG: `PLANNED`; only abstract retriever/embedding structures exist.
- Authentication and user management: `PLANNED`.
- Internet search, notifications, calendar, email, voice, mobile clients, autonomous agents, and multi-agent workflows: `PLANNED`.

## Architectural decision

The project has adopted clean-architecture and dependency-inversion principles as a design direction. The decision and its tradeoffs are recorded in [ADR 0001](adr/0001-clean-architecture-and-modular-structure.md). Existing code only partially realizes that decision.
