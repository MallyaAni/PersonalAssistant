# AniOS

AniOS is an early-stage, local-first personal AI assistant project. Its long-term direction includes conversation, personal memory, retrieval, and agent workflows, but future capabilities are not current functionality unless the documentation labels them otherwise.

The repository contains:

- a FastAPI backend;
- a React and Vite developer console;
- invited profile creation and login backed by one-time expiring codes,
  Argon2id password hashes, shared attempt limits, revocable HttpOnly browser
  sessions, server-derived ownership, and stable per-user data IDs;
- Docker Compose definitions for PostgreSQL with pgvector, Redis, two pinned
  vLLM inference services, the backend, frontend, local capability FastMCP
  sidecar, presentation worker, and presentation renderer;
- an OpenAI-compatible, provider-neutral inference boundary with independently
  configurable text, vision, and embedding roles; the qualified RTX 5080
  profile runs Qwen 3.5 4B and Nomic through pinned vLLM services and requires
  no LM Studio process or model-management API;
- a role-configurable model-backed conversation path, PostgreSQL/pgvector personal memory, and focused LangGraph supervisor, assistant, diagram-agent, and presentation-agent boundaries;
- main-model-native MCP tool selection over a semantic live-validated shortlist,
  guarded execution, visible chat status, and a read-only internet-search MCP
  server with an isolated Google ADK research worker, Tavily fallback, bounded
  local quota protection and provider-attributed sources;
- an explicit chat-to-Mermaid diagram path with user-scoped PostgreSQL artifact persistence and strict in-browser SVG rendering;
- free local HiDream/ComfyUI image generation, four-step FLUX.2 Klein
  source-aware editing of generated or uploaded images, and validated Qwen
  vision analysis in the chat composer, with natural-language creation intent,
  immutable edit lineage,
  in-place active revisions, grounded historical questions, guarded
  referenced-image web comparison, private previews, retry/cancel, reload
  restoration, history, download, owned deletion, and threaded followup
  questions on any owned image;
- a clickable Agent memory map whose bounded store details load on demand through the owned export boundary;
- a durable Scout discovery agent whose approved home and interests share the
  personal-memory fact lifecycle, with editable ranking strength, reversible
  travel mode, familiar-item undo, bounded sources, scheduled sweeps, digests,
  and calendar artifacts;
- a focused presentation subsystem where a separately qualified specialist model produces compact slide content,
  a durable worker executes the presentation LangGraph independently of chat,
  application code compiles strict editable deck specifications and ranked
  visual briefs, the worker progressively adds the highest-value applicable
  HiDream visuals by default without making imagery a deck-success dependency, PptxGenJS
  renders native Office objects, and LibreOffice validates each revision before
  reconnectable stage-weighted progress from outline through Office validation,
  persistent per-slide feedback, additional HiDream generation, FLUX refinement
  of an attached slide image, history, preview, download, deletion, and explicit
  cleanup of failed decks without completed slides;
- an agent-facing local FastMCP facade over the same visual and presentation
  services, returning bounded metadata handles rather than private binary data;
- a repeatable local-model qualification command for bounded supervisor/tool decisions and progressive presentation contracts, plus a local-only review-first command that uses explicit repository evidence to generate architecture-diagram candidates without automatically overwriting canonical documentation.

See [the current session handoff](docs/NEXT_SESSION.md) for verified runtime state and active blockers. See [the roadmap](docs/ROADMAP.md) for milestone status and explicitly planned capabilities.

## Quick orientation

The supported development paths and required environment variables are documented in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md). Do not start the Compose backend and a host Uvicorn process on port 8000 at the same time.

Start the complete user-facing local stack, including host ComfyUI image
generation, with:

```bash
bash scripts/start-anios.sh
```

`docker compose up` starts the core services but intentionally does not start
the profile-controlled or host ComfyUI process. Treat that command as an
incomplete startup whenever image generation is part of the acceptance path.

Common entry points are:

```text
Backend health:  http://localhost:8000/health
OpenAPI UI:      http://localhost:8000/docs
Frontend:        http://localhost:5173
Local gateway:   http://localhost:8080
Authentication: http://localhost:8000/api/v1/auth/session
Memory API:      http://localhost:8000/api/v1/memory/{user_id}
Scout discovery: http://localhost:8000/api/v1/discovery/{user_id}
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
- [Scalable inference target](docs/diagrams/inference-scaling-target.svg)
- [Authentication and ownership](docs/diagrams/authentication-subsystem.svg)
- [Detailed subsystem diagram catalog](docs/diagrams/README.md)
- [Development and validation](docs/DEVELOPMENT_GUIDE.md)
- [Roadmap](docs/ROADMAP.md)
- [Next session handoff](docs/NEXT_SESSION.md)
- [Changelog](docs/CHANGELOG.md)
- [Security](docs/SECURITY.md)
- [Architecture decisions](docs/adr/0001-clean-architecture-and-modular-structure.md), including [local visual artifacts and resource-aware orchestration](docs/adr/0003-local-visual-artifacts-and-resource-aware-orchestration.md), [hybrid free-tier web research](docs/adr/0004-hybrid-free-tier-web-research.md), [typed editable presentation generation](docs/adr/0005-typed-editable-presentation-generation.md), [versioned visual semantics, memory references, and editing](docs/adr/0007-versioned-visual-semantics-memory-and-editing.md), and the [default vLLM runtime](docs/adr/0009-vllm-default-local-inference-runtime.md)

## Status language

- `VERIFIED`: directly observed through an applicable runtime or functional check.
- `FAILED`: an attempted check did not meet its acceptance criteria.
- `UNVERIFIED`: no adequate check has been completed.
- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: behavior is supplied by a placeholder or fixed test implementation.
- `PLANNED`: future capability; it must not be described as current behavior.
