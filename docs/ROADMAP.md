# AniOS Roadmap

This document is the canonical milestone tracker. It records durable status at a higher level than the frequently rewritten [NEXT_SESSION.md](NEXT_SESSION.md).

## Status definitions

- `VERIFIED`: the milestone behavior passed an applicable runtime or functional check.
- `FAILED`: an attempted acceptance check failed.
- `UNVERIFIED`: adequate evidence has not been collected.
- `SCAFFOLDED`: structure exists without complete demonstrated behavior.
- `MOCKED`: placeholder behavior is wired.
- `PLANNED`: future work that is not current functionality.

## Milestone 1: stable conversational platform — VERIFIED

Goal: provide a locally runnable frontend and backend that complete a real chat request, stream a meaningful response, and persist the conversation.

Current evidence as of 2026-07-18:

- `VERIFIED`: PostgreSQL and Redis start in Compose; PostgreSQL reported healthy while the backend ran from current host source.
- `VERIFIED`: the documented chat payload returns `200 text/event-stream`, reaches `ConversationService` and the injected provider-neutral main model through LangGraph, emits message deltas, terminates, and creates a conversation row with the completed response.
- `VERIFIED`: initial Alembic revision `20260716_0001` creates the four application tables and `alembic check` reports no pending operations.
- `VERIFIED`: Playwright Chromium covers deterministic chat success/failure; its opt-in live path verifies a unique configured-main-model response, response content appearing while loading remains active, stream termination, loading cleanup, and clean Console/Network state.
- `VERIFIED`: the visible transcript survives navigation between Chat and Memory for the active conversation; starting a new conversation from Memory returns to a fresh Chat view; a bounded owned transcript and ready diagram restore from the stored active conversation after a full reload.
- `VERIFIED`: the responsive light-neutral frontend presents an empty search-first state and an active question/result layout, keeps request identifiers behind an accessible answer-level three-dot popover, uses one native system font stack in the composer and shell, and passes deterministic narrow-viewport plus live-provider browser acceptance.
- `VERIFIED`: assistant CommonMark renders as semantic styled headings, paragraphs, emphasis, lists, links, quotes, and code while raw HTML interpretation remains disabled and user messages remain literal.
- `VERIFIED`: targeted provider/chat/API tests, deterministic and live browser tests, and the frontend TypeScript/Vite production build pass.
- `VERIFIED`: the complete backend suite passes 27 tests; memory and conversation-history integration tests use isolated users and cleanup boundaries.

Milestone 1 acceptance criteria:

- backend and frontend start from documented commands;
- health and API availability checks pass;
- a browser chat request reaches the conversation service;
- a real configured model produces the expected non-placeholder response;
- streaming emits and terminates without client or server errors;
- the conversation is saved and can be read back;
- relevant automated tests and the frontend build pass;
- an automated browser test performs the primary chat workflow and fails on page exceptions, blocking console errors, failed required requests, or incorrect rendered output;
- browser Console and Network checks show no blocking errors.

Milestone 1 validation work still required:

- `SCAFFOLDED`: deterministic backend/API coverage exists for the current model-backed conversation path;
- `PLANNED`: frontend component coverage for loading, streaming, success, and failure states;
- `VERIFIED`: browser end-to-end coverage for deterministic success/failure and a separate opt-in live-LLM acceptance check;
- `PLANNED`: component-level frontend coverage and conversation selection/history browsing beyond active-conversation reload restoration.

Do not mark this milestone complete from health checks alone.

## Milestone 2: personal memory — SCAFFOLDED

Current evidence as of 2026-07-17:

- `VERIFIED`: profile upsert/readback, user-scoped episodic memory, metadata persistence, Nomic embedding generation, 768-dimensional pgvector storage, and semantic similarity retrieval pass integration tests.
- `VERIFIED`: the graph consumes bounded profile, episodic, and semantic context labeled as untrusted data.
- `VERIFIED`: REST and browser paths create, reload, recall, list, and delete personal memory; cross-user record deletion is rejected.
- `VERIFIED`: live Chromium paths persisted and deleted semantic memory and a
  real uploaded visual artifact. Delete-all removes owned artifact metadata,
  derived visual memory, and binary bytes while preserving another user's
  rows/files; the public browser confirms empty artifact history afterward.
- `VERIFIED`: ordinary chat supplies the configured 10 newest chronological turns for the same user and conversation to Gemma. A real two-message Chromium exchange recalled a unique name stated only in the first message, reused one conversation ID, used distinct per-request traces, terminated both streams, and cleared loading state without blocking browser errors.
- `VERIFIED`: chat can propose a preferred name without persisting it; real Chromium rejection wrote nothing, approval recalled the name in a new conversation, correction replaced it and recalled the replacement in another new conversation, another user remained isolated, and deletion cleared the profile value.
- `VERIFIED`: approved preferred names are structured, user-scoped, versioned facts with source conversation/trace provenance, approval and supersession state, confidence, purpose, timestamps, optional expiry, and embedding metadata fields. Correction supersedes rather than overwrites the prior version; expired facts are not projected into chat context.
- `VERIFIED`: semantic retrieval enforces a configurable cosine-distance threshold, result-count limit, and prompt-character budget at repository/service boundaries; results carry stable distance/relevance metadata and a repeatable hit/miss/edge/privacy evaluation fixture passes.
- `VERIFIED`: episodic/semantic correction, JSON export including conversations, per-record deletion, and delete-all propagation across conversations, facts, profiles, episodic/semantic memory, and tool-memory tables pass API and browser checks.
- `VERIFIED`: explicit memories carry purpose and optional expiry; semantic records also carry embedding model/version/dimension. Expired semantic records are excluded from retrieval while remaining exportable.
- `VERIFIED`: optional expiring HMAC-signed local user tokens bind chat and every memory/tool-memory route to the token subject when `AUTH_REQUIRED=true`; missing, invalid, expired, and cross-user requests are rejected before service access.
- `VERIFIED`: safe MCP tool descriptors can be embedded and discovered by user/server with schema-fingerprint invalidation; approved allowlisted preferences and sanitized outcome categories are stored separately, while secret-shaped descriptor/preference input is rejected.
- `VERIFIED`: a typed `AgentMemoryManager` persists semantic-cache, session-working, procedural/workflow, entity/relation, knowledge-document/chunk, and conversation-summary records. Current Alembic head `20260726_0015` adds durable presentation jobs on top of per-slide feedback association, presentation persistence, and binary visual metadata; the memory stores introduced through `0009` retain pgvector HNSW indexes and source-request provenance.
- `VERIFIED`: the deterministic `MemoryCoordinatorAgent` searches every embedded user-scoped store on each turn so anything relevant can be recalled regardless of phrasing, gates only the non-embedded episodic store by keyword, includes the latest conversation digest, relies on per-store distance thresholds plus one shared relevance budget to bound prompt fields, and keeps retrieved values as untrusted literal data. Completed turns update expiring session state and create a rolling digest every configured interval. Live-verified: an approved dentist entity was recalled by a question containing none of the old entity keywords.
- `VERIFIED`: a live Gemma/Nomic acceptance seeded unique entity, knowledge, summary, procedure, and toolbox codes; one chat query retrieved and reproduced all five codes, terminated with `done`, and cleanup returned all scoped agent-memory counts to zero.
- `VERIFIED`: the browser Memory screen renders all short- and long-term memory forms with live personal, agent, and toolbox counts. Every map card opens an on-demand owned detail view; full export is not fetched until a card is selected, displayed records are bounded, and embedding/storage internals are omitted.
- `VERIFIED`: response-style chat proposals require approval; generic structured-fact APIs provide provenance idempotency, normalized deduplication, contradiction supersession/versioning, correction, key/record deletion, and profile projection.
- `VERIFIED`: deterministic dry-run/apply retention, resumable same-dimension re-embedding across every vector store, natural-key transaction locks, concurrent write tests, a pgvector retrieval benchmark, and user-scoped operational inspection/CLI checks pass.
- `VERIFIED`: FastAPI, conversation, memory, coordinator, and operational persistence use SQLAlchemy `AsyncSession` through `asyncpg` with a bounded runtime pool. Six concurrent real PostgreSQL waits through a two-connection test pool preserved an event-loop heartbeat, never exceeded two checkouts, and drained completely; direct SSE chat and all live browser workflows passed through the same async repositories.
- `VERIFIED`: a configurable mixed live soak completed 6,526 public operations in 60.758 seconds with concurrency four: 66 terminal chat streams plus 6,460 working-memory/operations calls, zero failures, 63.044 ms p95 overall latency, and scoped cleanup. Transaction-abort and pool-checkout-timeout tests prove database recovery.
- `VERIFIED`: a shared configurable embedding concurrency limit remains at the provider-neutral boundary; the unchanged soak passed after the targeted fix and the promoted vLLM embedding batch passed live acceptance.
- `VERIFIED`: an opt-in Compose maintenance runner schedules retention, optional re-embedding, and final health inspection; it emits JSON/exit-code alert signals, continues after transient interval failures, and the API exposes Prometheus-compatible non-content metrics.
- `VERIFIED`: vector dimension is runtime-configured, and an offline resumable shadow-column migrator covers all seven vector stores. An isolated PostgreSQL acceptance forced a wrong-dimension failure that preserved both original `vector(3)` values, then retried, changed the column to `vector(2)`, and rebuilt HNSW; a production dry run confirmed every real store remains `vector(768)` with no shadow columns.
- `VERIFIED`: chat deterministically proposes explicit person/relationship, reusable workflow, and titled-reference memory in addition to preferred name and response style. Rejection performs no write; browser approval uses typed APIs with conversation/trace provenance. Live new-conversation checks recalled an approved dentist name plus unique workflow and reference codes, then cleanup removed the scoped data.
- `UNVERIFIED`: long-duration production-capacity/HNSW recall testing and delivery into a selected external alert platform.
- `VERIFIED` (bounded, opt-in): AES-256-GCM application-level encryption at rest for conversation, episodic/semantic memory, and image content when `ENCRYPTION_KEY` is set, with lazy plaintext migration, authenticated ciphertext, and integrity preserved over the plaintext; embeddings and deduplication columns are intentionally excluded and documented as residual exposure.
- `VERIFIED` (bounded): least-privilege token scopes (`chat`, `memory:read`, `memory:write`, `tools:invoke`, `vision`, and `memory`/`tools` groups) enforced per route action, validated at issue time, with unscoped tokens remaining unrestricted for compatibility.
- `PLANNED` by explicit user direction as remaining final-subsystem work:
  full-store/backup encryption, tested disaster restore, redacted audits,
  MFA/recovery, and backup/log deletion. Shared login/registration attempt
  limiting, invited password enrollment, and revocable browser sessions are
  now verified.
- `VERIFIED` (bounded): approval-gated episodic capture from conversations. The grammar-constrained semantic memory agent may select one concrete first-person past experience as the lowest-priority non-profile candidate. Approval routes through the existing `POST /memory/{user}/episodic` boundary with chat provenance; rejection writes nothing, preserving the "no silent model extraction" principle.

Delivered local-development capabilities include:

- user profile storage and retrieval;
- episodic memory with user scoping;
- semantic memory backed by embeddings and pgvector;
- typed semantic cache, working memory, procedures, entities/relations, knowledge, summaries, and toolbox metadata;
- deterministic memory-aware retrieval and rolling conversation digests;
- migration coverage and integration tests;
- privacy controls and deletion behavior.

Explicitly saved memory, bounded same-conversation recall, structured approval-based profile/entity/procedure/knowledge capture, generic fact lifecycle controls, relevance-gated semantic retrieval, retention/re-embedding/dimension-migration operations, non-blocking database access, optional signed ownership, and the safe tool-memory store work. The milestone is not complete until the remaining deployment-scale and deliberately deferred security gates below pass. With auth disabled, caller-supplied user IDs remain only logical scope; production-like deployment must enable auth and protect the signing secret.

Production-grade memory completion gates:

- authenticated ownership and authorization on every conversation and memory read/write/delete path;
- approval-based fact capture with provenance, confidence, purpose, and timestamps rather than silent model extraction;
- correction, versioning, contradiction handling, deduplication, export, per-record deletion, delete-all, and deletion propagation to embeddings, conversations, caches, logs, and backups;
- retention/expiry policies and storage encryption (opt-in content encryption at rest is implemented; full-store coverage, backup encryption, tested backup/restore, and redacted audit events remain);
- semantic relevance thresholds, hybrid retrieval/reranking where justified, prompt-injection isolation, and a repeatable retrieval-quality/privacy evaluation set;
- embedding-model/version metadata plus a tested re-embedding and vector-dimension migration path;
- non-blocking database access, service-level transaction boundaries, idempotent writes, indexes, concurrency/load tests, failure recovery, and operational monitoring.

The verified items above satisfy parts of these gates; the explicit `UNVERIFIED` and `PLANNED` items remain requirements. They should be delivered in separately verified atomic stages.

## Milestone 3: knowledge and RAG — SCAFFOLDED

- `VERIFIED`: user-scoped text document ingestion, content-hash idempotency, deterministic paragraph chunking, Nomic embedding, pgvector HNSW search, coordinator prompt delivery, export, and deletion;
- `VERIFIED`: live Gemma reproduced a unique fact retrieved from an ingested validation document;
- `PLANNED`: local open-source Unstructured parsing behind an application-owned
  parser interface for supported document types. Preserve source hashes,
  element types, titles/sections, page coordinates, tables, parent-document
  lineage, and parser/version provenance; keep OCR and format-specific system
  dependencies isolated in a background ingestion worker. Do not require the
  hosted Unstructured API or send private documents to it.
- `PLANNED`: agentic chunking as a bounded, optional ingestion strategy after
  Unstructured partitioning. A specialist may propose semantic boundaries,
  hierarchy, contextual labels, and parent/child groupings, but application
  code must validate source coverage, ordering, maximum size, overlap,
  provenance, idempotency, and prompt-injection isolation before indexing.
- `PLANNED`: benchmark deterministic paragraph, Unstructured element/`by_title`,
  parent-document, semantic, and agentic chunking on one versioned retrieval
  evaluation set. Promote agentic chunking only when it improves answer recall,
  precision, citation faithfulness, and context efficiency within explicit
  ingestion-latency and local-compute budgets; retain deterministic fallback.
- `PLANNED`: file/connector ingestion, durable background jobs, source lifecycle
  refresh, hybrid search and reranking, retrieval-quality evaluation, and
  citation/source-display policy;
- `PLANNED`: optional RAGFlow, GraphRAG, MultiQuery, and HyDE experiments.

The local knowledge store is a working semantic retrieval path, but it is not yet a production RAG system. The remaining items above require separate functional acceptance.

## Milestone 4: multimodal artifacts and visual generation — SCAFFOLDED

Goal: let one AniOS conversation create editable technical diagrams and locally generated visual media while keeping models, renderers, storage, and scarce hardware replaceable behind typed orchestration boundaries.

- `VERIFIED`: twelve concise canonical Mermaid/SVG orientation views, a documented one-question readability contract, render-input synchronization checks, architecture-change governance, and a local review-only Qwen candidate command are present. Eleven views document the current system; the separately labelled visual-memory/editing target records accepted future architecture without claiming implementation. The candidate path reads bounded explicit repository evidence, refuses remote endpoints and canonical overwrite, validates passive source plus required labels, renders an SVG, and still requires technical/visual review before manual promotion.
- `VERIFIED`: a focused `PresentationAgent` asks the configured presentation model, currently Qwen 3.5 4B through vLLM, for a compact outline, one bounded slide-content microtask at a time, or a strict selected-slide edit. Durable PostgreSQL jobs are claimed by a standalone leased worker that invokes this LangGraph, checkpoints progressive drafts, survives browser navigation/disconnect, and exposes reconnectable progress/cancellation. A Redis foreground-priority lease lets a waiting chat run between presentation microtasks. A deterministic application compiler turns bounded model output into stable editable layout objects. PptxGenJS renders editable native text, shapes, charts, tables, images, and notes; structural OOXML inspection and headless LibreOffice validation both precede atomic current-revision promotion. User-scoped append-only history, stable target-slide association, independent per-slide feedback conversations, stale-base conflict protection, opaque binary storage, progressive browser previews, slide thumbnails, navigation/reload restoration, named `.pptx` download, deletion, and visible queued/running/ready/failed/cancelled states pass direct and real-browser acceptance.
- `VERIFIED`: forced worker termination reclaimed the same PostgreSQL job on attempt 2 and produced its exact four-slide validated PPTX after the killed worker's Redis model lease expired naturally. Two simultaneous disposable workers claimed separate jobs with distinct worker IDs and each completed once with one revision and its exact two slides. Direct and isolated real-browser cancellation both reached persisted `cancelled` state after worker ownership, cleared resumable browser state, exposed visible progress/terminal messages, and cleaned up their scoped records.
- `VERIFIED`: a bounded four-client mixed workload overlapped six terminal chat streams and 45 memory/operations calls with two real presentation jobs. All 51 operations passed with zero failures; overall p95 was 35.059 seconds and maximum was 67.255 seconds, while both exact two-slide decks reached `ready` on attempt 1 in 147.881 seconds. An isolated live Chromium chat/deck workflow also passed in 131.2 seconds with both qualified models resident.
- `VERIFIED`: the presentation specialist declares bounded image briefs and priorities with slide content. The durable worker automatically enriches the configured highest-value applicable slides through the owned ComfyUI/HiDream artifact boundary, checkpoints each image into reconnectable browser progress, and still promotes an editable text deck when imagery is unavailable. The bounded RTX 5080 profile defaults to one 1024px hero image because two serial defaults exceeded the five-minute live-browser readiness gate with both 8k text roles resident; users can add or refine imagery per slide afterward. The browser converts those durable outline, slide, selected-visual, and render/validation checkpoints into an accessible stage-weighted progress bar rather than an invented time estimate. Later image feedback reads the attached owned artifact through the shared integrity boundary, creates an immutable FLUX.2 Klein child, replaces the image UUID in a new deck revision and in-place browser preview, and preserves the same editable-object rendering and promotion gates.
- `PLANNED`: capacity-aware presentation pipelining. Once a separate GPU or a
  tested GPU-memory lease proves the configured inference runtime and ComfyUI can overlap safely,
  enqueue an eligible high-priority visual as soon as its slide checkpoint is
  durable while the presentation specialist plans later slides. Bound
  in-flight work per provider, preserve deterministic slide/image association,
  propagate cancellation and failure independently, retain serial fallback,
  and measure time-to-first-slide, time-to-first-image, foreground-chat latency,
  peak VRAM, and total deck latency before enabling it by default. The current
  shared RTX 5080 qualification intentionally keeps both provider paths at
  concurrency one.
- `IMPLEMENTED, NOT SOLVED`: source-grounded deck research. `DeckResearch` runs
  one privacy-screened search per deck at outline time — before layouts are
  chosen, because that is where a slide is told to carry a number — and quotes
  bounded sources into the outline and every slide request, with the rule that
  an unsupported figure must become a plainer layout. The brief is reduced to
  its research subject first; sent verbatim it returned a slideware marketing
  page. Measured on the same brief and model, the grounded run gave six crewed
  landings against the ungrounded run's seven, and the right Apollo 8 date, but
  still placed Charles Duke on Apollo 15. Grounding reduces invented figures at
  the current 4B presentation role; it does not remove them, and this stays open
  until a deck's figures can be trusted without checking. Per-claim citations
  remain `PLANNED`.
- `PLANNED`: presentation citations, reusable theme/master libraries, diagram-asset hydration, arbitrary existing-PPTX import, automated visual-diff review with minimum-readable-font enforcement, sustained multi-host load/latency testing, and distributed GPU-capacity scheduling. The current worker queue is durable and horizontally claim-safe, but it is not yet a general distributed scheduler. Raster image pixels are not decomposed into editable drawing primitives, although the image object remains replaceable in PowerPoint.
- `VERIFIED`: explicit diagram requests create user-scoped PostgreSQL artifact records with pending/ready/failed lifecycle, conversation/trace provenance, provider/model metadata, recent owned history, scoped deletion, active-conversation transcript/artifact restoration after full reload, local Mermaid/SVG downloads, and shielded failed/cancelled terminal cleanup after client disconnect. Retention cleanup remains `PLANNED`.
- `VERIFIED`: deterministic application policy routes explicit diagram requests through a specialized typed `DiagramAgent` LangGraph workflow plus provider/repository contracts; the configured diagram model produces only a bounded specification and cannot select providers, write storage, or control hardware. Raster generation and vision now use focused provider/service contracts; autonomous image agents and multi-agent visual workers remain `PLANNED`.
- `VERIFIED`: the local Mermaid provider validates allowlisted passive source, performs one bounded format-correction retry, streams artifact lifecycle events, and lazily renders editable source as strict SVG in chat with visible generation/render failure states.
- `PLANNED`: a hardware-resource manager that leases GPU capacity, drains active inference safely, selects configured per-role context/offload profiles, verifies residency before dispatch, and restores the configured main and specialist providers after a model transition or failure.
- `VERIFIED`: free local ComfyUI 0.28 plus MIT-licensed HiDream-O1 Dev FP8 generates 2048x2048 PNGs through a typed provider and one-job concurrency gate. Direct RTX 5080 acceptance completed in 35.01 seconds under exclusive residency and 35.061 seconds while Gemma remained loaded at its 256k/parallel-4 profile; the immediate post-generation Gemma chat stream also completed. Live browser cancellation now interrupts the exact ComfyUI prompt, records `failed/cancelled`, clears loading, and produces no backend exception. Broader quality, crash recovery, and sustained-load benchmarks remain `PLANNED`; paid APIs, subscriptions, credits, and automatic cloud fallback remain excluded.
- `VERIFIED`: generated and uploaded images use user-scoped PostgreSQL pending/ready/failed lifecycle plus opaque atomic local storage, SHA-256/size integrity checks, owned content reads, scoped file-plus-row deletion, and sanitized invalid-input/provider failures. Automated retention/export and crash reconciliation remain `PLANNED`.
- `VERIFIED`: bounded PNG/JPEG/WebP multipart upload validation and real local VLM image understanding are implemented. The current Qwen 3.5 4B vLLM path described a persisted 2048px validation image through the owning API in 7.31 seconds; malformed bytes return 422 and create no record. Dedicated multimodal embeddings are now `VERIFIED`: `nomic-embed-vision-v1.5`
runs locally through ONNX and is aligned to the text latent space, generated and
uploaded images are embedded at store time, and a text query retrieves them by
pixel content through `GET /api/v1/artifacts/{user_id}/search/images` and through
deterministic image recall in chat. Cross-modal scores are not comparable to
text-text scores, so image vectors keep a separate column, index, and calibrated
threshold rather than sharing one ranked list. Retrieval quality is measured
rather than assumed: an 18-query labelled evaluation returns 14/14 correct
top-1 matches and rejects 4/4 distractor queries, using a distance ceiling plus
a required best-to-runner-up margin. Search routing now has a committed harness,
`backend/cli/evaluate_search_routing.py`, which scores a labelled set and exits
non-zero below a per-mode floor. The configured Qwen cascade passed all 52
committed cases in the final live run with 1.0 recall, 1.0 specificity, no
misses, and no unnecessary searches. Image-retrieval calibration remains manual
and is the next evaluation gap.
- `VERIFIED`: threaded followup questions about any owned generated or uploaded image reuse the integrity-checked stored bytes and the same provider-neutral vision boundary, replay a bounded question/answer context, persist a size-bounded thread in artifact metadata, seed from a prior flat analysis, and reject unowned or non-ready images with 404 before any provider call. Deterministic Chromium plus backend/unit coverage pass, and live local-VLM calls completed through the visual MCP facade and current Qwen vLLM endpoint. The interactive follow-up thread lives only on the artifact record. The initial upload analysis is indexed into semantic memory as a provenance-labelled description and is recalled by an ordinary conversation turn (live-verified); shortlist retrieval requires the referenced artifact to remain ready and owned, and artifact deletion removes its derived index row in the same database commit. Indexing the follow-up thread itself remains `PLANNED`.
- `VERIFIED`: the unified composer routes explicit natural-language new-image requests to image generation, image attachments to analysis, and image questions back to ordinary chat without creating another image. The newest visible image is shown as a removable thumbnail reference; every image card can explicitly replace it, so several visible images are unambiguous without maintaining a second input under each card. Chat sends the exact selected artifact ID, while an unselected visual question may use owner-scoped semantic descriptions to find relevant prior images. Imperative and polite question-shaped edits such as `can you make this car red?` send the integrity-checked source pixels, exact feedback, and preservation constraints through the four-step local FLUX.2 Klein 4B Distilled editor. The immutable child records its parent, source SHA-256, feedback, model, seed, steps, and latency, receives its own visual embedding, and replaces the active card in place. Focused Chromium covers selection, switching, clearing, questions, and generated/uploaded refinement; live RTX 5080 acceptance covers generated and uploaded parents plus slide-attached images. Prompt-only HiDream refinement and the experimental SAM recolor branch were removed after failing preservation or quality evidence.
- `IN PROGRESS` (accepted design in ADR 0007): initial VLM descriptions and semantic/pixel vectors support owner-scoped image recall, and one bounded local-model policy selects relevant offered image IDs by meaning rather than trigger words. Ready FLUX refinements are now observed by the local Qwen vision boundary and receive their own derived description/index; observation failure preserves the valid edited artifact and degrades to lineage. Durable idempotent observation for every generated-image path, typed append-only semantics, calibrated alias/conversation/recency fusion, and semantic post-edit verification remain planned.
- `PLANNED`: artifact reference resolution becomes type-neutral. Every generated, uploaded, or discussed artifact keeps one owned handle, provenance, lineage, derived semantic descriptions, and modality-specific retrieval data; explicit UI selection overrides semantic resolution. Video observations and parsed PDF/RAG chunks will join this contract without copying private binaries into prompts or allowing cross-user retrieval.
- `VERIFIED`: an explicit internet search about a recalled image runs image retrieval first, appends only a bounded prompt/analysis description to the normalized subject, privacy-screens the combined query, invokes the read-only internet MCP tool, and never sends image bytes. Real Chromium verified generation, grounded followup, visible search-tool lifecycle, terminal streaming, cleared loading/input, and memory-map drilldown.
- `VERIFIED`: deterministic and live Chromium acceptance covers diagrams, real ComfyUI image generation, multipart local-VLM analysis, private image rendering, progress/cancellation, retry, 413/422/502/503 failure display, navigation and reload restoration, history, download, owned deletion, clean successful Network/Console behavior, and terminal loading state.

AniOS now uses one qualified local model across generation roles:
`qwen/qwen3.5-4b` is the current main response/native-tool, diagram,
presentation, architecture-candidate, and vision model, while Nomic remains
the text embedding model. Both run through pinned vLLM Compose services. No model owns orchestration state or
its own lifecycle. The application owns policy, durable jobs, resource leases,
and provider recovery so specialized workers and future multi-agent graphs can
scale without coupling the system to the current RTX 5080 or planned DGX Spark.

## Milestone 5: tools and specialized agents — IN PROGRESS

- `VERIFIED`: stdio and streamable-HTTP MCP client connections with locally assigned server trust;
- `VERIFIED`: a dedicated local FastMCP sidecar exposes existing diagram,
  image-generation, image-followup, artifact-status, presentation-create,
  selected-slide-revise, and presentation-status services as seven
  metadata-only tools with application-owned identity outside model-visible
  schemas;
- `VERIFIED`: live-list/fingerprint/argument/privacy/risk invocation gates; consequential calls remain approval-gated but chat approval/resume is not implemented;
- `VERIFIED`: semantic discovery over safe, versioned MCP tool descriptors and native configured-main-model selection from a bounded live-validated shortlist;
- `VERIFIED`: user-scoped tool preference and usage-outcome memory;
- `VERIFIED`: `MainActionSelector` offers live search, image generation/edit,
  diagrams, presentation delegation, and the user's own registered MCP tools
  to the main model as one native tool-calling decision per turn, made from
  genuine understanding rather than a regex or a narrow bounded classifier
  judging the question alone; a labelled-benchmark functional test holds its
  search recall/specificity to the floor the retired regex-plus-classifier
  cascade (`MainSupervisorAgent`'s deterministic LangGraph delegation policy
  and `CascadingSearchRouter`) was held to, and separate functional tests
  cover image/diagram/delegation routing and refusing to guess a location it
  does not know. Delegation still emits visible agent/model lifecycle events
  and image/diagram actions still emit artifact lifecycle events, now shared
  across all three since generation and editing also run inside the chat
  stream instead of a separate client-triggered REST call;
- `VERIFIED`: independently configurable main, presentation, and diagram model
  endpoints/identifiers/reasoning settings plus a repeatable comparative
  qualification harness. Qwen 3.5 4B passed bounded provider checks plus real
  chat, vision, image-coexistence, and repeated presentation-worker paths;
- `VERIFIED`: provider-neutral text, vision, and embedding contracts now sit
  behind a fail-closed `openai_compatible` adapter factory. Main,
  presentation, diagram, vision, and embedding roles independently select an
  adapter and endpoint. The qualified profile is now vLLM 0.23.0 with pinned
  Qwen/Nomic model revisions and an ordered Compose startup. Buffered and
  streaming Qwen paths passed live acceptance. Dynamic discovery, runtime
  model switching, sleep/wake, context/KV-cache changes, and general GPU
  capacity scheduling remain outside this boundary;
- `VERIFIED`: a sanitized provider-neutral operational benchmark records
  adapter/runtime/model and host GPU identity, enforces explicit exit-code
  thresholds, and measures main TTFT/throughput/terminal streaming, native tool
  correctness, presentation buffered structured output, embedding batch
  latency/dimension, and fixed-fixture vision latency. Three sequential LM Studio
  baselines and the promoted vLLM RTX 5080 profile passed all five role checks;
- `VERIFIED`: the configured Qwen search cascade passed the complete 52-case
  routing evaluation with 1.0 recall and 1.0 specificity. Long-duration
  accuracy drift, contexts above the verified 8k workstation profile, and DGX
  Spark behavior remain unmeasured;
- `VERIFIED` (Tavily runtime; Google deterministic): deterministic
  privacy-preserving MCP internet research with an isolated Google ADK worker,
  Tavily fallback, explicit dual-provider verification, local non-content
  quota protection, visible tool/search status, and provider-attributed source
  cards. Live Google requests are `FAILED` for the tested free-only account:
  Gemini 2.5 models reject new users and Gemini 3 Search Grounding returns zero
  available account quota without the required plan;
- coding, finance, and scheduling capabilities;
- reflection and multi-agent orchestration;
- `VERIFIED`: trace-correlated tool execution with visible running/success/refusal/failure status; durable audit and consequential-call approval UI remain planned.

The primary assistant LangGraph still has one model-backed node. The typed
first-step supervisor currently has one registered delegation policy:
presentation creation. It does not yet dynamically compare every agent and MCP
tool in one decision. The deterministic memory coordinator is a policy/service
boundary, not a spawned LLM sub-agent or multi-agent graph. Presentation
creation runs as a focused LangGraph subagent in its own durable worker process,
independently of the foreground chat request.
The visual MCP facade is an
application-capability adapter, not a new autonomous agent. Its `untrusted`
classification keeps artifact-producing calls outside ordinary autonomous chat
selection until proposal/approval/resume is implemented. One narrow
request-scoped Google ADK researcher is implemented behind `SearchProvider`; it
has no AniOS memory, identity, general MCP access, durable session, or
authorization authority. General researcher teams, tool-executor agents,
a unified dynamic capability registry, ambiguity clarification/resume, general
LangGraph agent-team scheduling, and A2A are not implemented.

Internet-search policy and acceptance gates:

- A deterministic policy outside the LLM must require search for explicitly current/latest/recent information; changing facts such as news, weather, prices, schedules, scores, laws, regulations, security advisories, and software versions; requested links/quotes/source verification; or a material factual uncertainty that local knowledge cannot safely resolve.
- The policy must avoid search for analysis or summarization of supplied/local content, private-memory questions, creative work, and stable questions answerable without current sources.
- Before any outbound request, classify and minimize the query. Never include credentials, tokens, private memory or conversation history, private document passages, account identifiers, or identifying medical, financial, legal, or precise-location data.
- When useful personalization requires private or materially identifying context, show the proposed sanitized query and require user approval. If the query cannot be made safe without changing the task, do not send it.
- Use a read-only, allowlisted search capability with least privilege. Treat results as untrusted data rather than instructions, preserve source provenance, cite factual claims, and prevent result content from authorizing tools or accessing memory.
- Log the decision, reason category, domains, and trace ID with redaction; do not log the sensitive source text or raw private query.
- Deterministic tests must cover required-search, no-search, sanitization, approval, denial, prompt-injection, provider failure, citation, and no-network-on-block cases. Real-browser acceptance must make search use and failures visible to the user.

Search routing, query normalization, privacy enforcement, read-only MCP
execution, Google-first/Tavily-fallback policy, explicit cross-checking,
cloud-worker context isolation, non-content daily quota, untrusted result
isolation, visible status, and provider source provenance are implemented.
Deterministic coverage verifies both provider branches; direct API and real
Chromium acceptance verify Tavily fallback. A real Google-grounded request is
`UNVERIFIED` until an operator configures a key. The local models have no unrestricted
network access. Review/approval when a useful query needs materially identifying
context, broader PII classification, durable redacted decision audit,
distributed quota coordination, and claim-level citation evaluation remain
`PLANNED`.

MCP tool discovery and memory acceptance gates:

- The live, authorized MCP `tools/list` result is the source of truth. AniOS may embed a canonical descriptor containing a tool's server identity, name, description, input-purpose summary, version/schema fingerprint, and trusted risk classification to improve discovery when the registry becomes too large for direct model context.
- Tool embeddings are partitioned by user/tenant and MCP server trust boundary. A tool selected through similarity must be re-resolved against the current registry, schema, permissions, and policy immediately before invocation; a stale vector can never authorize a call.
- Tool-list change notifications or a fresh-list comparison invalidate removed or changed descriptors. Tests must prove that a removed, renamed, re-scoped, or schema-changed tool cannot be invoked from stale memory.
- Durable user-tool memory stores only approved derived facts such as “prefer calendar A for work events,” explicit defaults, last-used timestamps, success/failure categories, and user feedback. It is separate from the authoritative registry and from an append-only execution/audit record.
- Credentials, authorization tokens, environment values, raw private arguments, private resource contents, and unrestricted tool outputs are never embedded. Persisting a sanitized argument/default or result summary requires an explicit field allowlist, provenance, purpose, retention policy, and user deletion path.
- MCP descriptions, schemas, annotations, resources, and tool results are untrusted unless the server and metadata are independently trusted. Retrieved content cannot change permissions, approve an invocation, or override confirmation requirements.
- The selection policy combines semantic relevance with deterministic capability, risk, permission, freshness, and user-preference filters. High-impact, destructive, external-communication, purchase, account, or sensitive-data actions remain visible and approval-gated.
- Acceptance must cover semantic tool discovery, direct selection for small registries, user preference learning and correction, cross-user/server isolation, stale-index invalidation, schema drift, prompt injection, secret/PII non-persistence, denied permissions, approval, failure feedback, and complete deletion.

Live MCP discovery over stdio is now `VERIFIED`: configured servers are listed,
paginated, and indexed into `tool_descriptors` for semantic retrieval, with
locally assigned trust, description-inclusive fingerprints that expose rug
pulls, and quarantine for instruction-shaped descriptions. Verified against a
real server: 13 tools discovered and indexed, and natural-language queries
retrieve the correct tool while unrelated questions return nothing.

Safe tool-descriptor embeddings, approved preference/sanitized outcome memory, live MCP connectivity, native main-model tool selection, permission-aware invocation, pre-invocation registry re-resolution, and the local visual FastMCP capability facade are `VERIFIED`. Automatic registry refresh/change notifications, durable execution audit, per-server user authorization scopes, and chat approval/resume for consequential tools remain `PLANNED`; a stored descriptor never authorizes a call.

## Milestone 6: additional interfaces and automation — IN PROGRESS

- `VERIFIED` (local boundary): a loopback-only same-origin Nginx gateway serves
  the compiled UI and proxies API, SSE, upload, download, and long-running
  requests. The frontend uses relative production API URLs, so a remote browser
  does not attempt its own localhost. `PLANNED`: publish one HTTPS hostname
  through an authenticated edge/tunnel that gates every UI and `/api` request
  with a password-style login, one-time code, or approved identity before it
  reaches a same-origin local reverse proxy. Keep PostgreSQL, Redis, vLLM,
  ComfyUI, the renderer, and internal MCP endpoints unaddressable from the
  public Internet; expose no secrets in the Vite bundle; support SSE, uploads,
  downloads, and long presentation/image requests through the proxy; use
  expiring sessions, logout/revocation, rate limits, and deny-by-default origin
  checks. GitHub Pages may host a public static demonstration, but it is not the
  target for the authenticated working application because it does not provide
  the required local API path or ordinary free private-site access control.
- calendar and email integrations;
- voice interaction;
- mobile applications.

### Ambient local discovery and notification — IN PROGRESS

The first capability that reaches *out* rather than answering when asked: on a
daily or weekly cadence, find things happening near where the user lives that
match interests they have already approved, and offer each one as a phone
notification plus a calendar entry.

Cadence is deliberately slow. Social and venue schedules publish ahead of time,
so a weekly sweep loses nothing a continuous one would catch, and it keeps the
whole feature inside the free tiers the project already commits to. The loop
must never be the reason a paid search tier is enabled.

Deliver as separately verified atomic stages, in this order:

- `VERIFIED` stage 1 — interest and locality profile. Typed, user-scoped
  interests and places persist behind `/api/v1/discovery/{user_id}` with
  create/update, list, and scoped delete. Labels are sealed with `EncryptedText`
  and identified by a SHA-256 digest of their normalized form, because a sealed
  column cannot carry a unique constraint; case and spacing differences resolve
  to one interest. Provenance is validated against an allowed set so an inferred
  value can never be written as though the user asked for it, and the interest
  list is bounded because every label is eligible to enter a prompt. Coordinates
  are deliberately not stored until a source needs them. Live-verified: the
  profile round-trips through the owned API and a delete with another user's
  identifier returns 404 without removing the row. Explicit chat statements
  about home produce deterministic approval cards. A local Qwen 3.5 4B
  classifier semantically recognizes explicit current user interests—including
  natural phrasing, negation, ownership, and lists—and proposes up to eight at
  once; one approval writes the facts and Scout projections atomically, while
  panel edits record the same approved fact. A live authenticated browser run
  projected basketball, soccer, baseball, and hiking from one chat statement
  into Scout with no post-login console or page errors.

  `VERIFIED` profile-control closure: export and delete-all cover all eight
  discovery table families; familiar-item dismissals are reviewable and
  reversible; travel mode selects one database-enforced active destination
  without changing home; and each interest exposes its 1–3 ranking strength.
  A rebuilt live browser workflow exercised home, interest, strength, travel,
  dismissal undo, memory inspection, and isolated delete-all against PostgreSQL.
- `VERIFIED` stage 2 — structured schedule sources. A provider-neutral
  `EventSource` contract returns typed events carrying a stable per-source
  identity, start, place, and link. Two adapters ship: iCalendar and RSS/Atom,
  both parsed with the standard library so every bound and sanitization step
  stays visible at the boundary where untrusted feed text enters. Text is
  stripped of control characters and length-bounded, non-web URL schemes are
  dropped, each source is capped at 200 events, bodies are abandoned mid-stream
  past 5 MB, and a `RequestBudget` fixes how many outbound requests one run may
  make so the free-tier claim stays checkable. General web search is explicitly
  not the discovery mechanism: local listings are already structured, and search
  would be noisier, less parseable, and the one part of the loop with a hard
  monthly ceiling. The cascade remains available for enrichment, never for
  enumeration. Live-verified against real public feeds: a calendar yielded 42
  typed events with correct zone-aware all-day starts, and an RSS feed yielded
  15 items within a 2-request budget.

  RSS is deliberately weaker than iCalendar. A feed item states when it was
  published, not when the happening occurs, so items yield no start time unless
  the publisher supplies an explicit event date; the live RSS check returned 15
  events all correctly marked unschedulable. Inventing a start from `pubDate`
  would produce calendar entries that are confidently wrong. Treat iCalendar as
  the source of record for anything that must reach a calendar, and RSS as a
  discovery signal that a later enrichment stage may date.
- `VERIFIED` stage 3 — durable scheduled discovery. A `discovery_schedules` row
  states one user's cadence (daily or weekly, at a chosen local hour) and
  `discovery_runs` holds each durable, leased instance. Leasing reuses the
  presentation-worker pattern rather than introducing a second scheduler:
  `FOR UPDATE SKIP LOCKED` over queued-or-lease-expired rows, a renewable lease,
  attempt counting, cancellation, and terminal states that release the lease.

  Two invariants carry the "never double-notify" requirement, and both are
  tested rather than asserted. A unique constraint on `(schedule_id,
  scheduled_for)` makes a slot exactly-once, so a restarted or duplicated
  producer cannot queue the same sweep twice; polling the same due slot three
  times produced one run. And `delivered_at` is written once, so a resumed run
  that already delivered returns `False` rather than delivering again. A run
  whose lease lapses mid-work is reclaimed with its persisted digest intact, so
  the second attempt resumes rather than repeats.

  Cadence maths is pure and computed in the user's own timezone, including the
  daylight-saving case where a 9am sweep must stay 9am rather than drift with
  the old UTC offset. The next slot is strictly future, so completing a run at
  exactly its slot time cannot re-arm the same slot and spin. Each run records
  `requests_spent`, making the free-tier claim checkable after the fact rather
  than only asserted in advance.

  The run body is not yet wired: stage 3 delivers the machinery, and stage 4
  supplies the selection it will persist as a digest.
- `VERIFIED` stage 4 — novelty and relevance. `discovery_sources` holds the
  feeds a sweep reads, sealed and digest-identified like every other
  user-supplied value. `discovery_seen_items` records what has been accounted
  for, and novelty is decided in two passes: exact identity by a SHA-256 of the
  source and its own external id, then a pgvector near-duplicate check for the
  same happening relisted under a new identifier. Only an *announced* item
  suppresses a later one, so being ranked out once cannot permanently mask
  something the user was never shown.

  Ranking is deterministic and runs outside the model, for the same reason
  search routing does: a sweep happens while nobody is watching, and a sampled
  judgement would make one feed produce different results on different days. A
  candidate scores against its best single interest weighted by strength —
  summing across interests would let something weakly resembling everything beat
  something strongly matching one stated interest — and must clear a floor and a
  lead-time window to be shown at all. An empty digest is a better outcome than
  a padded one.

  Explicit dates before the current day are rejected during web-result
  conversion rather than collapsed into the genuinely undated mention path.
  Undated links remain bounded and are labeled as date-unconfirmed in the
  user-facing digest.

  Live-verified against a real public calendar: 42 events yielded 34 novel
  candidates and 1 selection, and an immediately repeated sweep over the
  unchanged feed produced 0 novel and 0 selected. A feed listing the same event
  twice in one response yields one candidate; an embedding-service failure
  degrades the sweep to identity-only novelty rather than failing it.
- `VERIFIED` (format and API; on-device import `UNVERIFIED`) stage 5 — calendar
  artifacts. Each selected event becomes a valid single-`VEVENT` `.ics` at
  `/api/v1/discovery/{user_id}/calendar/{item_digest}.ics`, rendered from the
  stored item rather than re-fetching the feed. iOS adds these natively from a
  link or attachment, so one artifact satisfies every transport below without
  CalDAV, an Apple developer account, or write access to the user's calendar.

  Written against RFC 5545 rather than formatted from a template, because the
  failure mode is silent: a client that dislikes a file usually declines it
  without explaining why, and one it accepts but misreads produces an
  appointment at the wrong time. Escaping is ordered so backslashes cannot be
  double-escaped, folding counts octets so a multi-byte character is never split
  across the 75-octet boundary, naive timestamps are refused rather than guessed
  at, and UIDs are stable across renders so re-importing updates the appointment
  instead of creating a second one. A real feed produced a correctly folded,
  correctly zoned file served as `text/calendar`. Opening one on an actual
  iPhone remains unverified, and requires the transport decision below.

  Verified when a generated file opens in iOS
  Calendar with correct title, start/end, timezone, and location.
- `IN PROGRESS` stage 6 — notification egress under an explicit permission
  boundary. The contract, the permission model, and the pull path exist;
  outbound sending ships disabled behind `DISCOVERY_EGRESS_ENABLED`, and no real
  message has been delivered.

  A subscriber is a revocable permission to send one person one kind of message
  — not an account, no memory, no ability to ask the assistant anything. Keeping
  it that small is what lets outbound delivery exist before multi-user identity
  does. Consent is a recorded column and never inferred, so an address enrolled
  without it is stored inactive and the default outcome of a mistake is that
  nothing is sent. Revocation stops delivery and rotates the token in one
  operation, so a calendar link already shared stops resolving too.

  The digest text is assembled from typed records rather than generated. Feed
  text is untrusted and this string leaves the machine: a model asked to
  summarize hostile input can be steered by that input, and the output reaches
  third parties over a channel that cannot be unsent.

  iMessage is the chosen channel for a small circle. Apple publishes no
  server-side API, so the unpaid path is a Mac signed into Messages exposing a
  send tool over the existing MCP boundary — AniOS decides whether to send, that
  machine does the sending, and the tool learns only an address and a body.
  `shortcuts_pull` is a first-class alternative where the recipient's own device
  fetches and AniOS makes no outbound connection at all.

  Live-verified: enrolling without consent yields an undeliverable permission
  and a feed that 404s; consenting opens it; the feed serves a real
  `text/calendar` subscription document; and revoking makes the
  already-shared link 404 again. Sending a real iMessage remains `UNVERIFIED`
  and requires a Mac.

  Original scope, still outstanding: A provider-neutral `NotificationChannel` contract whose first
  adapter is one-way push (ntfy, Pushover, or an Apple Shortcuts webhook).
  Egress is opt-in per channel, revocable, rate-limited, and audited; a channel
  carries only the approved digest fields and the artifact link, never raw
  memory content. This is the milestone's real risk: every earlier subsystem
  fails closed inside the machine, and this one does not. Verified when a real
  push arrives on-device with a working calendar link and revocation
  immediately stops delivery.
- `PLANNED` stage 7 — optional two-way messaging, only if replying is wanted.
  A gateway such as OpenClaw may serve as transport, calling AniOS over the
  existing MCP/HTTP boundary. AniOS remains the only scheduler and the only
  memory owner: a second assistant maintaining its own heartbeat and its own
  Markdown memory would fork the source of truth that the typed,
  provenance-tracked memory subsystem exists to protect. Adopt the gateway for
  its messaging integrations, not for its agent loop.

Sequencing and gates:

- Stages 1 through 5 stay inside the existing trust boundary and may proceed as
  ordinary work. Stage 6 is the first outbound delivery path and must require
  the verified revocable password session boundary plus the remaining remote
  ingress, audit, and recipient-confirmation controls before it can reach a
  user's phone.
- Requalify on the DGX Spark before starting. The measured RTX 5080 profile —
  FP8 kernel selection, KV sizing, and vLLM/ComfyUI GPU contention — does not
  transfer, and unified memory removes the residency conflict that shaped the
  current runtime.
- Every stage keeps the free-tier posture: no paid search tier, no paid
  messaging tier, and a bounded per-run request budget recorded with the digest.

Security and privacy gates in [SECURITY.md](SECURITY.md) apply before these capabilities can be considered complete.

## Milestone 7: multi-user identity and private per-user profiles — IN PROGRESS

The target: each person logs in, has their own profile and memory, and can view
only their own information. The per-user data model (every store scoped by
`user_id`) and the authorization layer (ownership binding plus least-privilege
token scopes) already exist and are `VERIFIED`; with `AUTH_REQUIRED=true` one
user cannot read another's data at the application layer. Invited identity
and revocable browser-session lifecycle are now `VERIFIED`. Cryptographic
per-user privacy and hardened public administration remain.

- `VERIFIED` (bounded): an operator either creates an account directly or mints
  an expiring one-time invitation. A friend chooses a username and password in
  the browser; registration consumes the digest-only invitation atomically with
  account and first-session creation. `POST /auth/login` verifies Argon2id
  passwords, issues an opaque HttpOnly session whose digest is stored in
  PostgreSQL, and the frontend gates all private views on the server-derived
  owner. There is deliberately no unrestricted public signup.
- `PLANNED`: per-user encryption keys for a true "only I can read it, not even
  the operator" guarantee. The current at-rest encryption uses a single
  server-side key, which protects a stolen database or backup but does not stop
  a holder of that key from reading every user's data. The privacy vision needs
  envelope encryption: a per-user data key wrapped by a key derived from the
  user's own password (or a KMS/HSM), so content is unreadable without the user.
  This decision shapes the login flow, because the password must unlock the key,
  and should be settled before more data is encrypted under the single key.
- `VERIFIED` (bounded): password browser sessions expire and are revoked by
  logout, password replacement, or account disable. The operator CLI creates,
  enables, disables, and resets accounts without offering destructive deletion.
  Shared Redis windows rate-limit invalid login/registration attempts and fail
  closed when protection is unavailable. Session refresh/rotation, recovery,
  MFA, and a browser administration surface remain `PLANNED`.
- `PLANNED`: per-user key rotation and recovery, including what happens to
  a user's encrypted data on password reset (unrecoverable without a recovery
  key or escrow), documented as an explicit product decision.

Ordering note: the verified session boundary does not yet unlock a per-user
encryption key. Settle recovery/escrow semantics before migrating content from
the current optional server-wide encryption key; do not retrofit key derivation
by rewriting user data without a tested backup and restore acceptance path.

## Milestone 8: reclaiming storage — IN PROGRESS

Goal: stop unreferenced bytes accumulating, without giving up anything a person
can see.

Measured on 2026-08-11 before deciding anything, because the intuitive answers
were both wrong:

| | size |
| --- | --- |
| Artifacts on disk | **553 MB** across 137 files |
| — orphaned: nothing in the database points at them | **460 MB**, 109 files |
| — superseded renders, rebuildable from their spec | **80 MB**, 23 files |
| Entire database | **17 MB** |
| `presentation_revisions` (the history itself) | 504 kB |
| Conversation transcripts | below the eight largest tables |

- `DONE` (2026-08-12): garbage-collect artifact files with no referencing row.
  `backend/artifacts/collection.py` plans a sweep and
  `python -m backend.cli.collect_storage` runs it, reporting by default and
  deleting only with `--apply`. Three guards, each for a distinct way this could
  destroy something irreplaceable: an unreadable reference table refuses the
  sweep rather than treating "no references found" as "nothing is referenced";
  files written within a grace period are left for the next sweep, because a
  render writes bytes before it records a row; and a key that is absolute or
  escapes the root is refused the same way a read would refuse it.

  Ran on 2026-08-12: **109 files, 460.3 MB reclaimed**, leaving 30 referenced
  files at 95.6 MB. Verified before deleting that all 109 filenames were
  artifact ids with no surviving row in `visual_artifacts`,
  `presentation_revisions` or `presentations`, and verified afterwards that all
  30 survivors read back with matching SHA-256 and that every artifact the API
  lists still downloads.
- `PLANNED`: drop the rendered `.pptx` of superseded revisions while keeping the
  specification. A render is ~15 MB and regenerable from the spec it came from;
  the spec is a few kB and is what undo needs. Deleting renders recovers the
  space and keeps the history, which is the opposite trade to deleting history.
- `AVAILABLE, NOT ENABLED`: run it on a schedule rather than by hand. A
  `storage-collection` service sweeps every six hours with a one-day grace
  period, under the same `maintenance` profile as `memory-maintenance` — which
  means neither runs until the profile is enabled:
  `docker compose --profile maintenance up -d storage-collection`. Deleting a
  row and deleting its bytes cannot be made atomic across a database and a
  filesystem, so a leak stays possible however careful each call site is; a
  sweep is what bounds it in time. Raising `IMAGE_EDIT_MEGAPIXELS` to 2.0 makes
  every new image larger, so this accumulates faster than when these numbers
  were taken.

**Deliberately not planned: deleting conversation transcripts or presentation
revision history.** Both were proposed as storage measures and neither is one.
Transcripts are a rounding error — the whole database is smaller than a single
rendered deck — and they carry the source conversation and trace provenance that
approved memory facts point back at, so dropping them costs the ability to
answer "where did this come from". Revision history is 504 kB and is what makes
an edit undoable. Together they would recover under 1 MB of 553 MB while
removing real function.

The security and privacy gates in [SECURITY.md](SECURITY.md) apply throughout;
enabling `AUTH_REQUIRED` and protecting the signing and encryption keys are
prerequisites for any non-local, multi-person deployment.

## Milestone 9: local inference on the DGX Spark — IN PROGRESS

Goal: use the DGX Spark's 128 GB unified memory for a substantially larger
model than the RTX 5080's VRAM can hold, without disturbing the working
RTX 5080 stack (`vllm-main`, `vllm-embedding`) it would sit alongside.

Hardware inventory and access are documented in
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md#available-hardware-nvidia-dgx-spark).

- `DONE, THEN REVERTED` (2026-08-14): DeepSeek-V4-Flash-0731 (284B total /
  13B active MoE) installed on the Spark via
  [MiaAI-Lab/DeepSeek-v4-Flash-One-DGX-Spark](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-One-DGX-Spark)
  → `Entrpi/ds4-on-spark`, wrapping `antirez/ds4` ("DwarfStar 4", C/CUDA, not
  vLLM — vLLM cannot read this repo's asymmetric GGUF quantization). Both
  install scripts were read in full before running anything on real hardware:
  entirely user-space (`$HOME` only), no `sudo`, no unexplained network
  calls, a real smoke test gating server start. Wired into the low-risk,
  non-tool-calling `PRESENTATION_LLM_BASE_URL`/`PRESENTATION_LLM_MODEL`
  roles, leaving `MAIN_LLM_BASE_URL` untouched. An initial synthetic
  verification (a simple 3-slide deck) passed clean; the user's actual first
  real request then failed with a `pydantic.ValidationError` —
  `extra_forbidden` on fields like `statistic` where the schema requires
  `statistic_value`/`statistic_label`. The model's JSON was well-formed, just
  not in AniOS's exact field names — real evidence about this engine's
  structured-output reliability, not a fluke the first synthetic test missed
  by chance. Reverted `PRESENTATION_LLM_BASE_URL`/`PRESENTATION_LLM_MODEL` to
  `vllm-main`/`qwen/qwen3.5-4b` the same session.
  Two real infrastructure bugs were found and fixed along the way regardless
  of the revert, since they'll matter again if this is revisited: `ds4-server`
  defaults to binding `127.0.0.1` only (unreachable from the `anios_backend`
  container until restarted with `--host 0.0.0.0`), and nothing supervises it
  across a Spark reboot by default (fixed with a user crontab `@reboot` entry
  — no `sudo` needed, no systemd unit installed).
  **Measured, not assumed:** decode throughput on a cold single-turn request
  was ~5.7 tokens/sec — genuinely slow, consistent with the
  `--enforce-eager`-class cost of this architecture lacking full CUDA graph
  support. Would not be tolerable for a synchronous chat path even if the
  schema issue were fixed — a second, independent reason (beyond tool-calling
  risk) this is not close to ready for `MAIN_LLM_BASE_URL`.
- `DONE` (2026-08-14, unrelated to DeepSeek): regenerating the user's failed
  prompt against the *reverted* Qwen config, to confirm the revert worked,
  also failed 2 of 3 attempts — truncated JSON, not a field-naming mismatch.
  `PRESENTATION_PLAN_MAX_TOKENS` defaulted to 2,048 and this prompt's real
  outline needed close to that. A genuine pre-existing bug, unrelated to any
  model choice — it would have hit Qwen alone, on the original deployment.
  Raised to 4,096 in `backend/config/settings.py`; 3 of 3 succeeded after,
  full backend suite (1175 tests) still passes.
- `PLANNED`: qualify whichever model lands on `MAIN_LLM_BASE_URL` (if this
  one, or another) through the same `backend.cli.qualify_models` harness the
  RTX 5080 profile used, particularly its native tool-calling behavior — the
  harness exists to catch exactly the class of routing regression this
  project has repeatedly hit this way. Not started; `MainActionSelector`
  still runs entirely on the RTX 5080's Qwen model.
- `DONE` (2026-08-14): tested this engine's native tool-calling directly —
  a standalone script built a real `MainActionSelector` pointed at
  `http://spark-b524.local:8888`/`deepseek-v4-flash`, never touching the
  running app's `MAIN_LLM_BASE_URL`. No regex, no hardcoded routing anywhere
  in this evaluation or in `MainActionSelector` itself — every decision is
  the model's own native tool call, exactly as for Qwen today.
  - **Search-routing benchmark** (the same 52-case, `recall >= 0.85 /
    specificity >= 0.75` floor Qwen was held to): **recall 0.8519, specificity
    0.9565** — a real pass, though recall clears the floor by less than one
    case's worth of margin. All 4 misses were the deliberately-hard category
    (implicit-volatile questions about ongoing events with no temporal
    marker, e.g. "did the merger go through") — the exact category the
    routing-cases file over-represents because it is where routing normally
    breaks.
  - **Tool-calling mechanics**: across every case tested, every tool call
    the model made was valid, correctly-typed JSON — no malformed structure,
    no wrong field names anywhere. That is a different and better property
    than the presentation failure showed; deck generation needed a complex
    nested schema, tool-calling here needs simple flat arguments, and this
    engine handled the latter cleanly every time.
  - **Tool-calling judgment**: found one real, reproducible gap - "write a
    haiku about rain" called `generate_image` to illustrate the rain instead
    of just writing the haiku (2/2 on first discovery). Broadened
    `generate_image`'s own tool description in
    `backend/services/main_action_selector.py` around the general principle
    (judge only by whether the user's words ask for a picture; a request to
    write text stays text even about a visual subject) rather than naming
    the one reported case, mirroring the `edit_image` fix earlier this
    session. Verified with varied phrasings across different subjects and
    forms (poem, story, description), not the one reported case: fixed
    cleanly and reproducibly. A second, more forceful rewrite of the same
    description was tried and **rejected** — it did not fix the remaining
    gap and introduced two new regressions elsewhere (a previously
    100%-reliable diagram request, and the just-fixed poem case), a direct,
    measured instance of the overfitting risk this project has been warned
    about repeatedly. Reverted to the first, non-regressing wording.
    **Residual gap, disclosed rather than hidden:** short, structured,
    nature-themed poetry forms specifically - haiku and limerick - stayed
    materially less reliable even after the fix: haiku 4/8 (50%), limerick
    2/8 (25%) across combined runs, against ~100% for every one of the other
    ~19 cases in the same battery (image requests, diagrams, delegation,
    edit_image, the opinion-question non-re-edit batch, ordinary
    no-action questions, and the broader poem/story/description class).
    This reads as a strong, specific model prior (haiku and limerick are
    frequently paired with an illustration in training data) that a tool
    description did not fully override, not a general reliability problem.
    New permanent regression coverage for the fixed cases (not the still-
    flaky haiku/limerick ones, which are not pinned to an unstable
    expectation) is in
    `test_a_request_to_write_about_a_visual_subject_does_not_generate_image`
    — verified against the currently-live Qwen model too (3/3), and the fix
    caused no regressions across the rest of that suite (the only failures
    on a full run were pre-existing, already-disclosed `edit_image`
    flakiness from earlier this session, unrelated to this change).
  - **Net read:** meaningfully more encouraging than the presentation
    result, on real evidence rather than optimism - but recall sits right at
    its floor, and the haiku/limerick gap is real and unresolved. Not
    sufficient evidence to promote this to `MAIN_LLM_BASE_URL` yet; the
    honest next step is more repeated runs building a wider confidence
    interval (this evidence base is single-digit repeats per case), plus a
    considered decision on whether the haiku/limerick-class gap is
    acceptable for a main model that answers creative-writing requests
    routinely.

- `DONE` (2026-08-14): split `MainActionSelector`'s tool-calling model from
  the conversational-reply model, so a main-model swap for reply quality
  does not have to also inherit that model's tool-calling behaviour
  wholesale. New `ROUTING_LLM_BASE_URL`/`ROUTING_LLM_MODEL`/
  `ROUTING_LLM_REASONING_EFFORT` in `backend/config/settings.py`, falling
  back to `MAIN_LLM_*` when unset (default behaviour is byte-for-byte
  unchanged - full backend suite, 1175 tests, confirms it). Wired via a new
  `get_routing_llm_client()`/`RoutingLlmDependency` in
  `backend/core/dependencies.py`; `get_main_action_selector` now takes that
  instead of the shared `LlmDependency`. Not deployed to `docker-compose.yml`
  - this is infrastructure for measurement, not a production change yet.
- `DONE` (2026-08-14): measured real end-to-end reply latency through the
  actual `build_assistant_graph`/`stream_chat` code path (the literal
  function that streams a reply to a user), Qwen vs DeepSeek-V4-Flash, four
  realistic conversational prompts, no mocking:

  | Query | Qwen | DeepSeek | Ratio |
  | --- | --- | --- | --- |
  | Rust learning path | 5.0s | 49.8s | 10x |
  | REST vs GraphQL tradeoffs | 11.3s | 35.6s | 3.2x |
  | Stress/deadline tips | 3.5s | 14.8s | 4.3x |
  | MoE vs dense explainer | 6.0s | 27.5s | 4.6x |

  Average 6.4s vs 31.9s - **roughly 5x slower**, ranging 3-10x by query.
  Time-to-first-token stays close for both (~0.1s vs ~0.4-1.0s) - DeepSeek
  does not feel stuck at the start, but the reply visibly trickles in far
  slower afterward, and it tended to write somewhat longer answers in this
  sample, compounding the wait rather than being the sole cause of it.
  Confirmed by reading `backend/core/llm.py`'s `stream_chat`, not assumed:
  it reads only `delta.content` from the SSE stream, never
  `delta.reasoning_content`, so DeepSeek's chain-of-thought does not leak
  into what a user would see - the length and slowness are both genuine,
  not an artifact of hidden reasoning text streaming through. One apparent
  garbled character in the raw output (`Here\x92s`, `\x92` instead of a
  curly apostrophe) was chased down to the byte and found to be a
  Windows-console `print()` encoding artifact in the measurement script
  itself, not a defect in the model's output or in `stream_chat` - recorded
  so the same false lead is not re-investigated later.
