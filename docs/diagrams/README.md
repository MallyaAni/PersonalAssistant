# AniOS Architecture Diagram Catalog

These diagrams describe the current implementation. AniOS currently deploys one modular FastAPI backend, not one independently deployed microservice per internal subsystem. The detailed views expose module, API, persistence, model, ownership, and lifecycle boundaries so the system can be explained without inventing services that do not exist.

Mermaid source is authoritative; SVG is the generated sharing format.

| Diagram | Use it to answer | Editable source | Rendered view |
| --- | --- | --- | --- |
| Full system | What are the major AniOS components and external dependencies? | [anios-system.mmd](anios-system.mmd) | [anios-system.svg](anios-system.svg) |
| Runtime and deployment | Which processes run where, on which ports, and through which protocols? | [runtime-deployment.mmd](runtime-deployment.mmd) | [runtime-deployment.svg](runtime-deployment.svg) |
| Chat orchestration | What happens from message submission through memory/search/tool retrieval, Gemma selection and streaming, persistence, and SSE completion? | [chat-orchestration.mmd](chat-orchestration.mmd) | [chat-orchestration.svg](chat-orchestration.svg) |
| Memory subsystem | Which memory forms exist, who may write them, how are they retrieved, and how are retention/re-embedding/operations handled? | [memory-subsystem.mmd](memory-subsystem.mmd) | [memory-subsystem.svg](memory-subsystem.svg) |
| Memory overview (manager) | First-contact, plain-language walkthrough of a memory turn, the approval gate, short-term vs long-term stores, and user data control | [memory-overview.mmd](memory-overview.mmd) | [memory-overview.svg](memory-overview.svg) |
| Tool memory and execution | How are safe MCP descriptors stored/retrieved, then live-validated, model-selected, policy-gated, invoked, and surfaced? | [tool-memory-subsystem.mmd](tool-memory-subsystem.mmd) | [tool-memory-subsystem.svg](tool-memory-subsystem.svg) |
| Visual artifacts | How do editable diagrams, browser image creation/analysis, cancellation, local providers, binary storage, and owned lifecycle boundaries work together? | [visual-artifact-subsystem.mmd](visual-artifact-subsystem.mmd) | [visual-artifact-subsystem.svg](visual-artifact-subsystem.svg) |
| Architecture maintenance | How does explicit repository evidence become an LLM-generated, validated, rendered, review-only candidate without automatic canonical overwrite? | [architecture-maintenance-subsystem.mmd](architecture-maintenance-subsystem.mmd) | [architecture-maintenance-subsystem.svg](architecture-maintenance-subsystem.svg) |
| Frontend | How do browser identity, conversation state, Chat, Memory, SSE parsing, API calls, and diagram rendering fit together? | [frontend-subsystem.mmd](frontend-subsystem.mmd) | [frontend-subsystem.svg](frontend-subsystem.svg) |

Yellow dashed nodes identify a scaffolded component or a known current limitation. They do not claim planned behavior is implemented. Update a diagram only when the corresponding architecture changes, then render and check the complete suite using the commands in [the development guide](../DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).

## Maintenance ownership

Every modifying task must assess the full-system view plus each detailed view that owns the changed code. Use runtime/deployment for process, protocol, port, database/session, and external-process changes; chat orchestration for chat API, SSE, LangGraph, provider, and conversation-flow changes; memory for memory forms, policy, retrieval, lifecycle, vector, and operations changes; tool memory for tool metadata, retrieval, and MCP-boundary changes; visual artifacts for artifact providers, persistence, lifecycle, and rendering changes; architecture maintenance for repository-context collection, LLM candidates, validation, rendering, and canonical-review changes; and frontend for browser state, components, API/SSE handling, and client rendering changes.

Edit a source only when its architectural facts change: components, agents, stores, dependencies, deployment/trust/ownership boundaries, or cross-component flows. If a new subsystem has no detailed view, add and catalog a `.mmd`/`.svg` pair and register its basename in `frontend/scripts/architecture-diagram.mjs`. Render and check the full suite, then visually inspect every changed view.

The completion report must say either `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`.
