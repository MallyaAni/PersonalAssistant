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
- `VERIFIED`: the documented chat payload returns `200 text/event-stream`, reaches `ConversationService` and the injected LM Studio Gemma model through LangGraph, emits multiple message deltas, terminates, and creates a conversation row with the completed response.
- `VERIFIED`: initial Alembic revision `20260716_0001` creates the four application tables and `alembic check` reports no pending operations.
- `VERIFIED`: Playwright Chromium covers deterministic chat success/failure; its opt-in live path verified a unique Gemma response, response content appearing while loading remained active, stream termination, loading cleanup, and clean Console/Network state.
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
- `VERIFIED`: a live Chromium path persisted a unique semantic memory, reloaded it, had Gemma recall it, deleted it, and confirmed database absence.
- `VERIFIED`: ordinary chat supplies the configured 10 newest chronological turns for the same user and conversation to Gemma. A real two-message Chromium exchange recalled a unique name stated only in the first message, reused one conversation ID, used distinct per-request traces, terminated both streams, and cleared loading state without blocking browser errors.
- `VERIFIED`: chat can propose a preferred name without persisting it; real Chromium rejection wrote nothing, approval recalled the name in a new conversation, correction replaced it and recalled the replacement in another new conversation, another user remained isolated, and deletion cleared the profile value.
- `VERIFIED`: approved preferred names are structured, user-scoped, versioned facts with source conversation/trace provenance, approval and supersession state, confidence, purpose, timestamps, optional expiry, and embedding metadata fields. Correction supersedes rather than overwrites the prior version; expired facts are not projected into chat context.
- `VERIFIED`: semantic retrieval enforces a configurable cosine-distance threshold, result-count limit, and prompt-character budget at repository/service boundaries; results carry stable distance/relevance metadata and a repeatable hit/miss/edge/privacy evaluation fixture passes.
- `VERIFIED`: episodic/semantic correction, JSON export including conversations, per-record deletion, and delete-all propagation across conversations, facts, profiles, episodic/semantic memory, and tool-memory tables pass API and browser checks.
- `VERIFIED`: explicit memories carry purpose and optional expiry; semantic records also carry embedding model/version/dimension. Expired semantic records are excluded from retrieval while remaining exportable.
- `VERIFIED`: optional expiring HMAC-signed local user tokens bind chat and every memory/tool-memory route to the token subject when `AUTH_REQUIRED=true`; missing, invalid, expired, and cross-user requests are rejected before service access.
- `VERIFIED`: safe MCP tool descriptors can be embedded and discovered by user/server with schema-fingerprint invalidation; approved allowlisted preferences and sanitized outcome categories are stored separately, while secret-shaped descriptor/preference input is rejected.
- `VERIFIED`: a typed `AgentMemoryManager` persists semantic-cache, session-working, procedural/workflow, entity/relation, knowledge-document/chunk, and conversation-summary records. Current Alembic head `20260718_0011` includes binary visual metadata; the memory stores introduced through `0009` retain pgvector HNSW indexes and source-request provenance.
- `VERIFIED`: the deterministic `MemoryCoordinatorAgent` caches a typed query plan, retrieves only selected user-scoped stores, includes the latest conversation digest, bounds prompt fields, and keeps retrieved values as untrusted literal data. Completed turns update expiring session state and create a rolling digest every configured interval.
- `VERIFIED`: a live Gemma/Nomic acceptance seeded unique entity, knowledge, summary, procedure, and toolbox codes; one chat query retrieved and reproduced all five codes, terminated with `done`, and cleanup returned all scoped agent-memory counts to zero.
- `VERIFIED`: the browser Memory screen renders all short- and long-term memory forms with live personal, agent, and toolbox counts; 15 deterministic and 6 live Chromium workflows pass.
- `VERIFIED`: response-style chat proposals require approval; generic structured-fact APIs provide provenance idempotency, normalized deduplication, contradiction supersession/versioning, correction, key/record deletion, and profile projection.
- `VERIFIED`: deterministic dry-run/apply retention, resumable same-dimension re-embedding across every vector store, natural-key transaction locks, concurrent write tests, a pgvector retrieval benchmark, and user-scoped operational inspection/CLI checks pass.
- `VERIFIED`: FastAPI, conversation, memory, coordinator, and operational persistence use SQLAlchemy `AsyncSession` through `asyncpg` with a bounded runtime pool. Six concurrent real PostgreSQL waits through a two-connection test pool preserved an event-loop heartbeat, never exceeded two checkouts, and drained completely; direct SSE chat and all live browser workflows passed through the same async repositories.
- `VERIFIED`: a configurable mixed live soak completed 6,526 public operations in 60.758 seconds with concurrency four: 66 terminal chat streams plus 6,460 working-memory/operations calls, zero failures, 63.044 ms p95 overall latency, and scoped cleanup. Transaction-abort and pool-checkout-timeout tests prove database recovery.
- `VERIFIED`: a shared configurable embedding concurrency limit prevents LM Studio's observed concurrent-request HTTP 400 failures; the unchanged soak passed after the targeted fix.
- `VERIFIED`: an opt-in Compose maintenance runner schedules retention, optional re-embedding, and final health inspection; it emits JSON/exit-code alert signals, continues after transient interval failures, and the API exposes Prometheus-compatible non-content metrics.
- `VERIFIED`: vector dimension is runtime-configured, and an offline resumable shadow-column migrator covers all seven vector stores. An isolated PostgreSQL acceptance forced a wrong-dimension failure that preserved both original `vector(3)` values, then retried, changed the column to `vector(2)`, and rebuilt HNSW; a production dry run confirmed every real store remains `vector(768)` with no shadow columns.
- `VERIFIED`: chat deterministically proposes explicit person/relationship, reusable workflow, and titled-reference memory in addition to preferred name and response style. Rejection performs no write; browser approval uses typed APIs with conversation/trace provenance. Live new-conversation checks recalled an approved dentist name plus unique workflow and reference codes, then cleanup removed the scoped data.
- `UNVERIFIED`: long-duration production-capacity/HNSW recall testing and delivery into a selected external alert platform.
- `PLANNED` by explicit user direction as the final subsystem: at-rest/backup encryption, tested backup/restore, token revocation/password-based login, redacted audits, and backup/log deletion.

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
- retention/expiry policies, storage and backup encryption, tested backup/restore, and redacted audit events;
- semantic relevance thresholds, hybrid retrieval/reranking where justified, prompt-injection isolation, and a repeatable retrieval-quality/privacy evaluation set;
- embedding-model/version metadata plus a tested re-embedding and vector-dimension migration path;
- non-blocking database access, service-level transaction boundaries, idempotent writes, indexes, concurrency/load tests, failure recovery, and operational monitoring.

The verified items above satisfy parts of these gates; the explicit `UNVERIFIED` and `PLANNED` items remain requirements. They should be delivered in separately verified atomic stages.

## Milestone 3: knowledge and RAG — SCAFFOLDED

- `VERIFIED`: user-scoped text document ingestion, content-hash idempotency, deterministic paragraph chunking, Nomic embedding, pgvector HNSW search, coordinator prompt delivery, export, and deletion;
- `VERIFIED`: live Gemma reproduced a unique fact retrieved from an ingested validation document;
- `PLANNED`: file/connector ingestion, background jobs, parsing beyond plain text, and source lifecycle refresh;
- hybrid search and reranking;
- evaluation of retrieval quality;
- citation and source-display policy;
- optional RAGFlow, parent-document, GraphRAG, MultiQuery, and HyDE experiments.

The local knowledge store is a working semantic retrieval path, but it is not yet a production RAG system. The remaining items above require separate functional acceptance.

## Milestone 4: multimodal artifacts and visual generation — SCAFFOLDED

Goal: let one AniOS conversation create editable technical diagrams and locally generated visual media while keeping models, renderers, storage, and scarce hardware replaceable behind typed orchestration boundaries.

- `VERIFIED`: eight canonical Mermaid/SVG views, render-input synchronization checks, architecture-change governance, and a local review-only Gemma candidate command are present. The candidate path reads bounded explicit repository evidence, refuses remote endpoints and canonical overwrite, validates passive source plus required labels, renders an SVG, and still requires technical/visual review before manual promotion.
- `PLANNED`: a manager-facing presentation layer with plain-language titles, legends, numbered primary flows, slide-readable aspect ratios, and simplified overview views; the current synchronized diagrams remain detailed engineering references rather than verified first-contact manager material.
- `VERIFIED`: explicit diagram requests create user-scoped PostgreSQL artifact records with pending/ready/failed lifecycle, conversation/trace provenance, provider/model metadata, recent owned history, scoped deletion, active-conversation transcript/artifact restoration after full reload, local Mermaid/SVG downloads, and shielded failed/cancelled terminal cleanup after client disconnect. Retention cleanup remains `PLANNED`.
- `VERIFIED`: deterministic application policy routes explicit diagram requests through a specialized typed `DiagramAgent` LangGraph workflow plus provider/repository contracts; Gemma produces only a bounded specification and cannot select providers, write storage, or control hardware. Raster generation and vision now use focused provider/service contracts; autonomous image agents and multi-agent visual workers remain `PLANNED`.
- `VERIFIED`: the local Mermaid provider validates allowlisted passive source, performs one bounded format-correction retry, streams artifact lifecycle events, and lazily renders editable source as strict SVG in chat with visible generation/render failure states.
- `PLANNED`: a hardware-resource manager that leases GPU capacity, drains active inference safely, selects configured context profiles, and restores the primary Gemma provider after a model transition or failure.
- `VERIFIED`: free local ComfyUI 0.28 plus MIT-licensed HiDream-O1 Dev FP8 generates 2048x2048 PNGs through a typed provider and one-job concurrency gate. Direct RTX 5080 acceptance completed in 35.01 seconds under exclusive residency and 35.061 seconds while Gemma remained loaded at its 256k/parallel-4 profile; the immediate post-generation Gemma chat stream also completed. Live browser cancellation now interrupts the exact ComfyUI prompt, records `failed/cancelled`, clears loading, and produces no backend exception. Broader quality, crash recovery, and sustained-load benchmarks remain `PLANNED`; paid APIs, subscriptions, credits, and automatic cloud fallback remain excluded.
- `VERIFIED`: generated and uploaded images use user-scoped PostgreSQL pending/ready/failed lifecycle plus opaque atomic local storage, SHA-256/size integrity checks, owned content reads, scoped file-plus-row deletion, and sanitized invalid-input/provider failures. Automated retention/export and crash reconciliation remain `PLANNED`.
- `VERIFIED`: bounded PNG/JPEG/WebP multipart upload validation and real Gemma 4 12B image understanding are implemented. Live acceptance correctly identified a unique magenta geometric fox and its light-green circular platform; malformed bytes returned 422 and created no record. Dedicated multimodal embeddings are now `VERIFIED`: `nomic-embed-vision-v1.5`
runs locally through ONNX and is aligned to the text latent space, generated and
uploaded images are embedded at store time, and a text query retrieves them by
pixel content through `GET /api/v1/artifacts/{user_id}/search/images` and through
deterministic image recall in chat. Cross-modal scores are not comparable to
text-text scores, so image vectors keep a separate column, index, and calibrated
threshold rather than sharing one ranked list. Retrieval quality is measured
rather than assumed: an 18-query labelled evaluation returns 14/14 correct
top-1 matches and rejects 4/4 distractor queries, using a distance ceiling plus
a required best-to-runner-up margin. A committed evaluation harness equivalent
to `evaluate_memory_retrieval.py` remains `PLANNED`; the calibration run was
performed manually.
- `VERIFIED` (deterministic): threaded followup questions about any owned generated or uploaded image reuse the integrity-checked stored bytes and the same Gemma vision boundary, replay a bounded question/answer context, persist a size-bounded thread in artifact metadata, seed from a prior flat analysis, and reject unowned or non-ready images with 404 before any provider call. Deterministic Chromium plus backend/unit coverage pass; a live Gemma followup session remains `UNVERIFIED`. The thread lives only on the artifact record — chat-path image awareness and multimodal-memory retrieval of image content remain `PLANNED`.
- `VERIFIED`: deterministic and live Chromium acceptance covers diagrams, real ComfyUI image generation, multipart Gemma analysis, private image rendering, progress/cancellation, retry, 413/422/502/503 failure display, navigation and reload restoration, history, download, owned deletion, clean successful Network/Console behavior, and terminal loading state.

Gemma remains the primary logical reasoning model, but no model owns orchestration state or its own lifecycle. The application owns policy, durable jobs, resource leases, and provider recovery so specialized workers and future multi-agent graphs can scale without coupling the system to the current RTX 5080 or planned DGX Spark.

## Milestone 5: tools and specialized agents — PLANNED

- MCP client connections with explicit server trust, authentication, and per-user authorization scopes;
- real tool registry and permission model;
- semantic discovery over safe, versioned MCP tool descriptors;
- user-scoped tool preference and usage-outcome memory;
- deterministic, testable LangGraph workflows;
- privacy-preserving internet research and synthesis;
- coding, finance, and scheduling capabilities;
- reflection and multi-agent orchestration;
- traceable tool execution with user control.

The current graph still has one model-backed assistant node. The deterministic memory coordinator is a policy/service boundary, not a spawned LLM sub-agent or multi-agent graph. Researcher and tool-executor agents are not implemented.

Internet-search policy and acceptance gates:

- A deterministic policy outside the LLM must require search for explicitly current/latest/recent information; changing facts such as news, weather, prices, schedules, scores, laws, regulations, security advisories, and software versions; requested links/quotes/source verification; or a material factual uncertainty that local knowledge cannot safely resolve.
- The policy must avoid search for analysis or summarization of supplied/local content, private-memory questions, creative work, and stable questions answerable without current sources.
- Before any outbound request, classify and minimize the query. Never include credentials, tokens, private memory or conversation history, private document passages, account identifiers, or identifying medical, financial, legal, or precise-location data.
- When useful personalization requires private or materially identifying context, show the proposed sanitized query and require user approval. If the query cannot be made safe without changing the task, do not send it.
- Use a read-only, allowlisted search capability with least privilege. Treat results as untrusted data rather than instructions, preserve source provenance, cite factual claims, and prevent result content from authorizing tools or accessing memory.
- Log the decision, reason category, domains, and trace ID with redaction; do not log the sensitive source text or raw private query.
- Deterministic tests must cover required-search, no-search, sanitization, approval, denial, prompt-injection, provider failure, citation, and no-network-on-block cases. Real-browser acceptance must make search use and failures visible to the user.

Search routing and privacy enforcement are both `PLANNED`; Gemma must not receive direct unrestricted network access, and a prompt instruction alone will not satisfy these gates.

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

Safe tool-descriptor embeddings plus approved preference/sanitized outcome memory are `VERIFIED` as persistence and discovery boundaries. Live MCP connectivity, authoritative `tools/list` refresh/change notifications, permission-aware invocation, and pre-invocation registry re-resolution remain `PLANNED`; a stored descriptor never authorizes a call.

## Milestone 6: additional interfaces and automation — PLANNED

- notifications;
- calendar and email integrations;
- voice interaction;
- mobile applications;
- proactive automation with explicit permission boundaries.

Security and privacy gates in [SECURITY.md](SECURITY.md) apply before these capabilities can be considered complete.
