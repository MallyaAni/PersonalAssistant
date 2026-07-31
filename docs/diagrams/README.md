# AniOS Architecture Diagram Catalog

These diagrams are concise orientation maps of the current implementation. AniOS currently deploys one modular FastAPI backend, not one independently deployed microservice per internal subsystem. Exact endpoints, configuration, schemas, and exception paths belong in the architecture prose and code rather than in these views.

Mermaid source is authoritative; SVG is the generated sharing format.

The self-contained [published architecture page](../architecture.html) includes every cataloged view in the reading order below. Each section provides fit-to-page context, bounded zoom controls, a full-size SVG link, and the canonical Mermaid source so managers and engineers can use the same artifact at different levels of detail.

| Diagram | Use it to answer | Editable source | Rendered view |
| --- | --- | --- | --- |
| Full system | What are the major AniOS components and external dependencies? | [anios-system.mmd](anios-system.mmd) | [anios-system.svg](anios-system.svg) |
| Runtime and deployment | What runs in Compose, on the host, and outside AniOS? | [runtime-deployment.mmd](runtime-deployment.mmd) | [runtime-deployment.svg](runtime-deployment.svg) |
| Chat orchestration | How does one chat request reach the correct workflow and return a visible result? | [chat-orchestration.mmd](chat-orchestration.mmd) | [chat-orchestration.svg](chat-orchestration.svg) |
| Search and research | How does a privacy-screened query become a cited answer? | [search-research-subsystem.mmd](search-research-subsystem.mmd) | [search-research-subsystem.svg](search-research-subsystem.svg) |
| Memory subsystem | How does approved memory become bounded assistant context? | [memory-subsystem.mmd](memory-subsystem.mmd) | [memory-subsystem.svg](memory-subsystem.svg) |
| Memory overview (manager) | How does memory help a turn while remaining under user control? | [memory-overview.mmd](memory-overview.mmd) | [memory-overview.svg](memory-overview.svg) |
| Tool memory and execution | How does AniOS discover and safely invoke an MCP tool? | [tool-memory-subsystem.mmd](tool-memory-subsystem.mmd) | [tool-memory-subsystem.svg](tool-memory-subsystem.svg) |
| Visual artifacts | How are diagrams, images, and image analysis produced and stored? | [visual-artifact-subsystem.mmd](visual-artifact-subsystem.mmd) | [visual-artifact-subsystem.svg](visual-artifact-subsystem.svg) |
| Visual memory and editing | What visual editing works today, and what semantic recall stages remain planned? | [visual-memory-editing-target.mmd](visual-memory-editing-target.mmd) | [visual-memory-editing-target.svg](visual-memory-editing-target.svg) |
| Presentations | How does a durable job produce an editable, validated PowerPoint? | [presentation-subsystem.mmd](presentation-subsystem.mmd) | [presentation-subsystem.svg](presentation-subsystem.svg) |
| Architecture maintenance | How does explicit repository evidence become an LLM-generated, validated, rendered, review-only candidate without automatic canonical overwrite? | [architecture-maintenance-subsystem.mmd](architecture-maintenance-subsystem.mmd) | [architecture-maintenance-subsystem.svg](architecture-maintenance-subsystem.svg) |
| Frontend | How do browser state, product views, and the typed API client fit together? | [frontend-subsystem.mmd](frontend-subsystem.mmd) | [frontend-subsystem.svg](frontend-subsystem.svg) |

Yellow dashed nodes identify a scaffolded component or a known current limitation. They do not claim planned behavior is implemented. Update a diagram only when the corresponding architecture changes, then render and check the complete suite using the commands in [the development guide](../DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).

## Readability contract

Each diagram answers one engineering question. Prefer 15 or fewer conceptual nodes and 18 or fewer primary edges; exceed those guides only when removing a boundary would make the view misleading. Use short noun labels, one main reading direction, and shared boundary nodes instead of drawing every component-to-store or component-to-provider dependency.

Keep exact endpoints, schemas, configuration values, retries, and uncommon failure branches in prose. Show a model name only where a model is actually called. If a view needs a second independent story, split it into another diagram instead of growing a dependency map.

## Maintenance ownership

Every modifying task must assess the full-system view plus each detailed view that owns the changed code. Use runtime/deployment for process, protocol, port, database/session, and external-process changes; chat orchestration for chat API, SSE, LangGraph, provider, and conversation-flow changes; search and research for routing, outbound minimization, research agents, provider/fallback policy, search budgets, and source provenance; memory for memory forms, policy, retrieval, lifecycle, vector, and operations changes; tool memory for tool metadata, retrieval, and MCP-boundary changes; visual artifacts for current artifact providers, persistence, lifecycle, and rendering changes; the visual-memory target for planned observation, reference-resolution, editing, verification, and derived-data lifecycle decisions; presentations for DeckSpec/SlideSpec generation, focused-agent orchestration, revision/promotion rules, PowerPoint rendering, and Office validation; architecture maintenance for repository-context collection, LLM candidates, validation, rendering, and canonical-review changes; and frontend for browser state, components, API/SSE handling, and client rendering changes.

Edit a source only when its architectural facts change: components, agents, stores, dependencies, deployment/trust/ownership boundaries, or cross-component flows. If a new subsystem has no detailed view, add and catalog a `.mmd`/`.svg` pair and register its basename in `frontend/scripts/architecture-diagram.mjs`. Render and check the full suite, then visually inspect every changed view.

The completion report must say either `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`.
