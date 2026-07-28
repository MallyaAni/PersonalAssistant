# AniOS

AniOS is an early-stage, local-first personal AI assistant project. Its long-term direction includes conversation, personal memory, retrieval, and agent workflows, but future capabilities are not current functionality unless the documentation labels them otherwise.

The repository contains:

- a FastAPI backend;
- a React and Vite developer console;
- Docker Compose definitions for PostgreSQL with pgvector, Redis, the backend,
  frontend, local capability FastMCP sidecar, presentation worker, and
  presentation renderer;
- a role-configurable model-backed conversation path, PostgreSQL/pgvector personal memory, and focused LangGraph supervisor, assistant, diagram-agent, and presentation-agent boundaries;
- main-model-native MCP tool selection over a semantic live-validated shortlist,
  guarded execution, visible chat status, and a read-only internet-search MCP
  server with an isolated Google ADK research worker, Tavily fallback, bounded
  local quota protection and provider-attributed sources;
- an explicit chat-to-Mermaid diagram path with user-scoped PostgreSQL artifact persistence and strict in-browser SVG rendering;
- free local HiDream/ComfyUI image generation, four-step FLUX.2 Klein
  source-aware editing, and validated Gemma vision analysis in the chat
  composer, with natural-language creation intent, immutable edit lineage,
  in-place active revisions, grounded historical questions, guarded
  referenced-image web comparison, private previews, retry/cancel, reload
  restoration, history, download, owned deletion, and threaded followup
  questions on any owned image;
- a clickable Agent memory map whose bounded store details load on demand through the owned export boundary;
- a focused presentation subsystem where a separately qualified specialist model produces compact slide content,
  a durable worker executes the presentation LangGraph independently of chat,
  application code compiles strict editable deck specifications, PptxGenJS
  renders native Office objects, and LibreOffice validates each revision before
  reconnectable progress, persistent per-slide feedback, history, preview,
  download, or deletion;
- an agent-facing local FastMCP facade over the same visual and presentation
  services, returning bounded metadata handles rather than private binary data;
- a repeatable local-model qualification command for bounded supervisor/tool decisions and progressive presentation contracts, plus a local-only review-first command that uses explicit repository evidence to generate architecture-diagram candidates without automatically overwriting canonical documentation.

See [the current session handoff](docs/NEXT_SESSION.md) for verified runtime state and active blockers. See [the roadmap](docs/ROADMAP.md) for milestone status and explicitly planned capabilities.

## Quick orientation

The supported development paths and required environment variables are documented in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md). Do not start the Compose backend and a host Uvicorn process on port 8000 at the same time.

Start the complete user-facing local stack, including host ComfyUI image
generation, with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-anios.ps1
```

`docker compose up` starts the core services but intentionally does not start
the profile-controlled or host ComfyUI process. Treat that command as an
incomplete startup whenever image generation is part of the acceptance path.

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
Image refinement: http://localhost:8000/api/v1/images/{artifact_id}/refine
Image analysis:   http://localhost:8000/api/v1/vision/analyze
Image followup:   http://localhost:8000/api/v1/vision/artifacts/{artifact_id}/ask
Conversation:    http://localhost:8000/api/v1/conversations/{user_id}/{conversation_id}
Tool invocation: http://localhost:8000/api/v1/tools/{user_id}/call
Presentations:   http://localhost:8000/api/v1/presentations/{user_id}
Capability MCP:  http://localhost:8001/mcp
PPTX renderer:   http://localhost:8002/health
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
- [Architecture decisions](docs/adr/0001-clean-architecture-and-modular-structure.md), including [local visual artifacts and resource-aware orchestration](docs/adr/0003-local-visual-artifacts-and-resource-aware-orchestration.md), [hybrid free-tier web research](docs/adr/0004-hybrid-free-tier-web-research.md), [typed editable presentation generation](docs/adr/0005-typed-editable-presentation-generation.md), and [versioned visual semantics, memory references, and editing](docs/adr/0007-versioned-visual-semantics-memory-and-editing.md)

## Status language

- `VERIFIED`: directly observed through an applicable runtime or functional check.
- `FAILED`: an attempted check did not meet its acceptance criteria.
- `UNVERIFIED`: no adequate check has been completed.
- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: behavior is supplied by a placeholder or fixed test implementation.
- `PLANNED`: future capability; it must not be described as current behavior.
