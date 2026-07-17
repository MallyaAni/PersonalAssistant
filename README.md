# AniOS

AniOS is an early-stage, local-first personal AI assistant project. Its long-term direction includes conversation, personal memory, retrieval, and agent workflows, but future capabilities are not current functionality unless the documentation labels them otherwise.

The repository contains:

- a FastAPI backend;
- a React and Vite developer console;
- Docker Compose definitions for PostgreSQL with pgvector, Redis, and the backend;
- a model-backed conversation path, PostgreSQL/pgvector personal memory, and a small LangGraph agent boundary.

See [the current session handoff](docs/NEXT_SESSION.md) for verified runtime state and active blockers. See [the roadmap](docs/ROADMAP.md) for milestone status and explicitly planned capabilities.

## Quick orientation

The supported development paths and required environment variables are documented in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md). Do not start the Compose backend and a host Uvicorn process on port 8000 at the same time.

Common entry points are:

```text
Backend health:  http://localhost:8000/health
OpenAPI UI:      http://localhost:8000/docs
Frontend:        http://localhost:5173
Memory API:      http://localhost:8000/api/v1/memory/{user_id}
```

These addresses being reachable does not prove chat or persistence works. Follow the functional validation protocol in the development guide.

User-visible behavior is considered verified only when the intended workflow is exercised through an automated browser test or a documented manual browser session. API reachability alone cannot verify the frontend.

## Documentation

- [Agent instructions](AGENTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development and validation](docs/DEVELOPMENT_GUIDE.md)
- [Roadmap](docs/ROADMAP.md)
- [Next session handoff](docs/NEXT_SESSION.md)
- [Changelog](docs/CHANGELOG.md)
- [Security](docs/SECURITY.md)
- [Architecture decisions](docs/adr/0001-clean-architecture-and-modular-structure.md)

## Status language

- `VERIFIED`: directly observed through an applicable runtime or functional check.
- `FAILED`: an attempted check did not meet its acceptance criteria.
- `UNVERIFIED`: no adequate check has been completed.
- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: behavior is supplied by a placeholder or fixed test implementation.
- `PLANNED`: future capability; it must not be described as current behavior.
