# ADR 0003: Local Visual Artifacts and Resource-Aware Orchestration

## Status

Accepted and partially implemented. Architecture maintenance, the dedicated diagram graph, editable Mermaid artifacts, free local HiDream raster generation, opaque generated/uploaded binary storage, validated image upload, Gemma image understanding, aligned multimodal image embeddings, browser image integration, and an agent-facing local FastMCP facade are implemented. Durable queues, automated retention, GPU leases/model transitions, embedding VLM analysis text into personal memory, and generalized multi-agent visual workers remain `PLANNED`.

## Context

AniOS needs two related but different visual capabilities. Maintainers need an accurate, reviewable high-level architecture diagram, while users should eventually be able to request editable flowcharts, technical diagrams, generated images, and later image understanding through chat.

The current local development machine runs Gemma 4 12B through LM Studio on an RTX 5080 with 32 GB of system RAM. Long-context KV cache can be offloaded or reduced, but a visual model may still compete with Gemma for GPU capacity. A planned DGX Spark changes available capacity but must not require an AniOS redesign.

The user requires a free approach: no subscriptions, paid API credits, or automatic cloud fallback. AniOS is also intended to grow into a scalable multi-agent orchestration framework rather than allow one model or inference runtime to own application policy.

## Decision

1. Mermaid source is authoritative for technical architecture and flow diagrams. Generated SVG is a sharing artifact, not the source of truth. A normalized source/configuration/renderer fingerprint plus fresh render check keeps both synchronized across development platforms.
2. Architecture diagrams change only with components, agents, persistent stores, external dependencies, deployment/trust boundaries, ownership boundaries, or cross-component data flows. Every modifying task declares its diagram impact.
3. Runtime visual outputs are first-class, user-scoped artifacts with conversation and trace provenance, lifecycle status, provider/model metadata, listing, owned content, integrity metadata, and deletion. Editable diagrams remain database source; generated and uploaded image bytes use opaque local binary storage. Automated binary export and retention remain planned extensions.
4. AniOS will expose focused provider contracts for diagram rendering, visual generation, artifact storage, and model-runtime control. Application services and typed orchestration nodes depend on those contracts rather than LM Studio, ComfyUI, Mermaid, or a particular model.
5. A deterministic application coordinator owns artifact routing, durable job state, GPU leases, queueing, cancellation, timeout, provider transitions, and recovery. An LLM may produce a bounded diagram specification or image prompt, but it cannot unload models, allocate hardware, authorize storage, or declare a job successful.
6. Gemma is the primary logical reasoning provider, not required to remain resident permanently. When simultaneous residency fails measured resource gates, the coordinator drains active streams, persists the prepared job, unloads or reduces the chat runtime, runs a visual worker, releases it, restores Gemma, and then resumes queued work.
7. Model context size is a configurable resource profile selected by application policy. Normal chat, long-context work, and visual-job preparation can use different profiles without changing conversation or memory ownership.
8. Free local providers are mandatory. Paid endpoints and automatic cloud fallback are excluded. Candidate models must pass pinned-license review and local quality, latency, VRAM, cancellation, and recovery acceptance before selection.
9. Multi-agent expansion uses typed nodes and bounded messages over durable application-owned state. Specialized diagram, image, research, coding, and tool workers may be introduced incrementally; they do not receive raw database, permission, secret, or hardware-management authority merely because they are agents.
10. Image understanding and multimodal vector retrieval are separate capabilities. Gemma provides validated image understanding through a focused adapter. Nomic Embed Vision and its aligned text encoder provide bounded image retrieval in a distinct vector index; these vectors are not inferred from Nomic text-memory embeddings or HiDream generation.
11. Repository architecture generation is LLM-assisted rather than LLM-authoritative. The application selects explicit bounded context, validates passive Mermaid and required implementation labels, renders a new candidate, and refuses canonical overwrite. Technical and visual review must precede an explicit manual canonical change.
12. Existing visual application services are exposed to future agents through a
    dedicated local FastMCP adapter rather than duplicated tool
    implementations. Model-visible schemas contain task arguments only;
    application-owned user, conversation, and trace context travels as
    opt-in request metadata. Tool results return bounded artifact handles, not
    binary content or storage keys. Artifact-producing calls remain
    confirmation-gated until a visible approval/resume workflow is implemented.
13. Generated images retain their bounded generation prompt as provenance.
    Deterministic application routing distinguishes a request for a new image
    from a question about a prior image. If the user explicitly asks for web
    comparison, AniOS may append one bounded stored analysis or generation
    prompt only after image recall and before outbound privacy screening; it
    never sends image bytes to search.
14. Calls made through the shared local Gemma chat client are serialized because
    the current LM Studio runtime can terminate an in-flight generation when
    another call overlaps it. This lock is a local safety boundary; durable
    queues, multi-process scheduling, and resource leases remain planned.

## Consequences

Benefits:

- technical diagrams remain accurate, editable, diffable, and shareable, while a separate manager-facing presentation layer can simplify them without replacing source-of-truth views;
- the user experiences one AniOS assistant while specialized providers remain replaceable;
- hardware transitions from the RTX 5080 to DGX Spark affect configuration and scheduling rather than domain workflows;
- exclusive GPU use and simultaneous residency can both be supported from measured capacity;
- provider failure cannot erase conversation, memory, or durable job state;
- future multi-agent workers inherit explicit authority and lifecycle boundaries.
- browser APIs and agent-facing MCP tools share one set of visual lifecycle and
  ownership services instead of diverging implementations.

Costs and risks:

- model transitions add latency and require careful drain, timeout, and recovery behavior;
- artifact metadata and binary storage add retention, deletion, and ownership obligations;
- generated diagram specifications and uploaded media are untrusted inputs and require bounded validation;
- local open-weight licenses, hardware requirements, and runtime support must be checked for each pinned model version;
- durable job coordination may eventually require a real queue, but Redis is not considered implemented until application code and acceptance evidence use it.
- the local FastMCP sidecar has application-service access and therefore needs
  future service authentication and process/network hardening; it is an
  adapter boundary, not a sandbox.

## Alternatives considered

- Pixel-generating models were rejected as the source of truth for technical diagrams because labels, edges, and component names must be reviewable and exact.
- A single unified multimodal model remains a benchmark candidate but was rejected as a mandatory architecture dependency; one model's current quality or runtime support should not constrain every modality.
- Permanent simultaneous model residency was rejected as an assumption because lowering KV cache does not eliminate model-weight pressure and current hardware evidence is not yet collected.
- Paid hosted image APIs and cloud fallback were rejected by the zero-cost requirement.
- Giving Gemma direct LM Studio or GPU lifecycle tools was rejected because model-resource control is application policy and must remain deterministic and recoverable.
