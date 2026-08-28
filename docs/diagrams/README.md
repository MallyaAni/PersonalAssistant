# AniOS Architecture Diagram Catalog

These diagrams are concise orientation maps of the current implementation. AniOS currently deploys one modular FastAPI backend, not one independently deployed microservice per internal subsystem. Exact endpoints, configuration, schemas, and exception paths belong in the architecture prose and code rather than in these views.

Mermaid source is authoritative; SVG is the generated sharing format.

The self-contained [published architecture page](../architecture.html) includes every cataloged view in the reading order below. Each section provides fit-to-page context, bounded zoom controls, a full-size SVG link, and the canonical Mermaid source so managers and engineers can use the same artifact at different levels of detail.

| Diagram | Use it to answer | Editable source | Rendered view |
| --- | --- | --- | --- |
| Full system | What are the major AniOS components and external dependencies? | [anios-system.mmd](anios-system.mmd) | [anios-system.svg](anios-system.svg) |
| Runtime and deployment | What runs in Compose, on the host, and outside AniOS? | [runtime-deployment.mmd](runtime-deployment.mmd) | [runtime-deployment.svg](runtime-deployment.svg) |
| Inference scaling target | How can model serving scale without moving authorization or durable-state ownership into vLLM? | [inference-scaling-target.mmd](inference-scaling-target.mmd) | [inference-scaling-target.svg](inference-scaling-target.svg) |
| ML serving design | Which model at which quantisation, why the KV cache is 4-bit MLA at 1M context, why utilisation is 0.81 and spark2 decides it, every retrieval gate's value, and what was measured and rejected? | [ml-serving-design.mmd](ml-serving-design.mmd) | [ml-serving-design.svg](ml-serving-design.svg) |
| Authentication and ownership | How does an invite login become one stable, server-derived owner for all private data? | [authentication-subsystem.mmd](authentication-subsystem.mmd) | [authentication-subsystem.svg](authentication-subsystem.svg) |
| Chat orchestration | How does one chat request reach the correct workflow and return a visible result? | [chat-orchestration.mmd](chat-orchestration.mmd) | [chat-orchestration.svg](chat-orchestration.svg) |
| Search and research | How does a privacy-screened query become a cited answer? | [search-research-subsystem.mmd](search-research-subsystem.mmd) | [search-research-subsystem.svg](search-research-subsystem.svg) |
| Context management | How does a turn's material become a bounded prompt, and what makes turn two fast? | [context-management.mmd](context-management.mmd) | [context-management.svg](context-management.svg) |
| Memory subsystem | Which short- and long-term types exist, and how do they become bounded assistant context? | [memory-subsystem.mmd](memory-subsystem.mmd) | [memory-subsystem.svg](memory-subsystem.svg) |
| Memory overview (manager) | How do short- and long-term memory help a turn while remaining under user control? | [memory-overview.mmd](memory-overview.mmd) | [memory-overview.svg](memory-overview.svg) |
| Scout discovery | How do approved home and interest facts drive local findings, travel, ranking, and dismissal controls? | [discovery-subsystem.mmd](discovery-subsystem.mmd) | [discovery-subsystem.svg](discovery-subsystem.svg) |
| iMessage bridge | How does a text from an allowlisted sender become a full-pipeline reply, and what never leaves the Mac? | [imessage-bridge.mmd](imessage-bridge.mmd) | [imessage-bridge.svg](imessage-bridge.svg) |
| Group chats (a room is an account) | How does a message in an iMessage group reach Scout only when it was addressed to it, what may the room know about each member, whose memory does a fact said in the room land in, and how does the answer get back into the chat? | [group-chats-subsystem.mmd](group-chats-subsystem.mmd) | [group-chats-subsystem.svg](group-chats-subsystem.svg) |
| Tasks and skills (Scout's second shape) | How does "remind me every weekday at 7" become a saved task, how does "morning brief" reach a taught skill by meaning, and how does a due task become a turn delivered back to the person? | [scheduled-tasks-subsystem.mmd](scheduled-tasks-subsystem.mmd) | [scheduled-tasks-subsystem.svg](scheduled-tasks-subsystem.svg) |
| Tool memory and execution | How does AniOS discover and safely invoke an MCP tool? | [tool-memory-subsystem.mmd](tool-memory-subsystem.mmd) | [tool-memory-subsystem.svg](tool-memory-subsystem.svg) |
| Visual artifacts | How are diagrams, images, and image analysis produced and stored? | [visual-artifact-subsystem.mmd](visual-artifact-subsystem.mmd) | [visual-artifact-subsystem.svg](visual-artifact-subsystem.svg) |
| Multimodal artifact reference and image editing | How do explicit selection, semantic image recall, lineage, and editing work today, and how will video/PDF join the contract? | [visual-memory-editing-target.mmd](visual-memory-editing-target.mmd) | [visual-memory-editing-target.svg](visual-memory-editing-target.svg) |
| Presentations | How does a durable job produce an editable, validated PowerPoint? | [presentation-subsystem.mmd](presentation-subsystem.mmd) | [presentation-subsystem.svg](presentation-subsystem.svg) |
| Architecture maintenance | How does explicit repository evidence become an LLM-generated, validated, rendered, review-only candidate without automatic canonical overwrite? | [architecture-maintenance-subsystem.mmd](architecture-maintenance-subsystem.mmd) | [architecture-maintenance-subsystem.svg](architecture-maintenance-subsystem.svg) |
| Frontend | How do browser state, product views, and the typed API client fit together? | [frontend-subsystem.mmd](frontend-subsystem.mmd) | [frontend-subsystem.svg](frontend-subsystem.svg) |

Yellow dashed nodes identify a scaffolded component or a known current limitation. They do not claim planned behavior is implemented. Update a diagram only when the corresponding architecture changes, then render and check the complete suite using the commands in [the development guide](../DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).

## One view per agent

The subsystem views show a pipeline. These answer a different question, and the
one that matters most when reading an agent: **what does the model actually
decide, and what is decided for it?**

| Agent | What the model decides | Source | SVG |
| --- | --- | --- | --- |
| Scout | What each sweep searches for, what a candidate is scored against, the order of a qualified shortlist, and how a find reads. What *qualifies* is deterministic. | [source](agent-scout.mmd) | [view](agent-scout.svg) |
| Deck | Content and slide shape. Geometry, storage and promotion are not its to make. | [source](agent-deck.mmd) | [view](agent-deck.svg) |
| Diagram | The Mermaid, within bounds it is asked for and the validator enforces. | [source](agent-diagram.mmd) | [view](agent-diagram.svg) |
| Memory capture | What is worth offering to save. Whether it is saved is the user's. | [source](agent-memory.mmd) | [view](agent-memory.svg) |

## Readability contract

Each diagram answers one engineering question. Prefer 15 or fewer conceptual nodes and 18 or fewer primary edges; exceed those guides only when removing a boundary would make the view misleading. Use short noun labels, one main reading direction, and shared boundary nodes instead of drawing every component-to-store or component-to-provider dependency.

Keep exact endpoints, schemas, configuration values, retries, and uncommon failure branches in prose. Show a model name only where a model is actually called. If a view needs a second independent story, split it into another diagram instead of growing a dependency map.

## Maintenance ownership

Every modifying task must assess the full-system view plus each detailed view that owns the changed code. Use runtime/deployment for process, protocol, port, database/session, and external-process changes; the inference scaling target for role endpoints, model-pool replication, placement policy, serving control planes, and inference observability; chat orchestration for chat API, SSE, LangGraph, provider, and conversation-flow changes; search and research for routing, outbound minimization, research agents, provider/fallback policy, search budgets, and source provenance; memory for memory forms, policy, retrieval, lifecycle, vector, and operations changes; Scout discovery for profile facts, travel locality, sources, ranking, schedules, familiarity, and digest flows; tool memory for tool metadata, retrieval, and MCP-boundary changes; visual artifacts for current artifact providers, persistence, lifecycle, and rendering changes; the visual-memory target for planned observation, reference-resolution, editing, verification, and derived-data lifecycle decisions; presentations for DeckSpec/SlideSpec generation, focused-agent orchestration, revision/promotion rules, PowerPoint rendering, and Office validation; architecture maintenance for repository-context collection, LLM candidates, validation, rendering, and canonical-review changes; and frontend for browser state, components, API/SSE handling, and client rendering changes.

The inference scaling view deliberately mixes implemented blue application
boundaries with planned yellow serving infrastructure. Do not recolor a planned
pool, placement controller, or control plane until a multi-replica deployment
passes load, back-pressure, failure-recovery, and ownership acceptance.

Edit a source only when its architectural facts change: components, agents, stores, dependencies, deployment/trust/ownership boundaries, or cross-component flows. If a new subsystem has no detailed view, add and catalog a `.mmd`/`.svg` pair and register its basename in `frontend/scripts/architecture-diagram.mjs`. Render and check the full suite, then visually inspect every changed view.

The completion report must say either `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`.
