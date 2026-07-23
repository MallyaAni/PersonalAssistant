# AniOS

AniOS is an early-stage, local-first personal AI assistant project. Its long-term direction includes conversation, personal memory, retrieval, and agent workflows, but future capabilities are not current functionality unless the documentation labels them otherwise.

The repository contains:

- a FastAPI backend;
- a React and Vite developer console;
- Docker Compose definitions for PostgreSQL with pgvector, Redis, and the backend;
- a model-backed conversation path, PostgreSQL/pgvector personal memory, and focused LangGraph assistant and diagram-agent boundaries;
- Gemma-native MCP tool selection over a semantic live-validated shortlist, guarded execution, visible chat status, and a read-only internet-search MCP server;
- an explicit chat-to-Mermaid diagram path with user-scoped PostgreSQL artifact persistence and strict in-browser SVG rendering;
- free local HiDream/ComfyUI image generation plus validated Gemma vision analysis in the chat composer, with private previews, retry/cancel, reload restoration, history, download, owned deletion, and threaded followup questions on any owned image;
- a local-only, review-first command that uses Gemma and explicit repository evidence to generate architecture-diagram candidates without automatically overwriting canonical documentation.

See [the current session handoff](docs/NEXT_SESSION.md) for verified runtime state and active blockers. See [the roadmap](docs/ROADMAP.md) for milestone status and explicitly planned capabilities.

## Quick orientation

The supported development paths and required environment variables are documented in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md). Do not start the Compose backend and a host Uvicorn process on port 8000 at the same time.

Common entry points are:

```text
Backend health:  http://localhost:8000/health
OpenAPI UI:      http://localhost:8000/docs
Frontend:        http://localhost:5173
Memory API:      http://localhost:8000/api/v1/memory/{user_id}
Agent memory:    http://localhost:8000/api/v1/memory/{user_id}/agent
Artifacts API:   http://localhost:8000/api/v1/artifacts/{user_id}/conversations/{conversation_id}
Artifact history: http://localhost:8000/api/v1/artifacts/{user_id}
Image generation: http://localhost:8000/api/v1/images/generate
Image analysis:   http://localhost:8000/api/v1/vision/analyze
Image followup:   http://localhost:8000/api/v1/vision/artifacts/{artifact_id}/ask
Conversation:    http://localhost:8000/api/v1/conversations/{user_id}/{conversation_id}
```

These addresses being reachable does not prove chat or persistence works. Follow the functional validation protocol in the development guide.

User-visible behavior is considered verified only when the intended workflow is exercised through an automated browser test or a documented manual browser session. API reachability alone cannot verify the frontend.

## Documentation

- [Agent instructions](AGENTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Canonical system diagram](docs/diagrams/anios-system.svg)
- [Detailed subsystem diagram catalog](docs/diagrams/README.md)
- [Development and validation](docs/DEVELOPMENT_GUIDE.md)
- [Roadmap](docs/ROADMAP.md)
- [Next session handoff](docs/NEXT_SESSION.md)
- [Changelog](docs/CHANGELOG.md)
- [Security](docs/SECURITY.md)
- [Architecture decisions](docs/adr/0001-clean-architecture-and-modular-structure.md), including [local visual artifacts and resource-aware orchestration](docs/adr/0003-local-visual-artifacts-and-resource-aware-orchestration.md)

## Status language

- `VERIFIED`: directly observed through an applicable runtime or functional check.
- `FAILED`: an attempted check did not meet its acceptance criteria.
- `UNVERIFIED`: no adequate check has been completed.
- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: behavior is supplied by a placeholder or fixed test implementation.
- `PLANNED`: future capability; it must not be described as current behavior.
