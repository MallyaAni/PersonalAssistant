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

Current evidence as of 2026-07-16:

- `VERIFIED`: PostgreSQL and Redis start in Compose; PostgreSQL reported healthy while the backend ran from current host source.
- `VERIFIED`: the documented chat payload returns `200 text/event-stream`, reaches `ConversationService` and the injected LM Studio Gemma model through LangGraph, emits multiple message deltas, terminates, and creates a conversation row with the completed response.
- `VERIFIED`: initial Alembic revision `20260716_0001` creates the four application tables and `alembic check` reports no pending operations.
- `VERIFIED`: Playwright Chromium covers deterministic chat success/failure; its opt-in live path verified a unique Gemma response, response content appearing while loading remained active, stream termination, loading cleanup, and clean Console/Network state.
- `VERIFIED`: the visible transcript survives navigation between Chat and Memory for the active conversation; starting a new conversation from Memory returns to a fresh Chat view. Full-reload transcript restoration remains planned.
- `VERIFIED`: the responsive light-neutral frontend presents an empty search-first state and an active question/result layout, keeps request identifiers behind an accessible answer-level three-dot popover, uses one native system font stack in the composer and shell, and passes deterministic narrow-viewport plus live-provider browser acceptance.
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
- `PLANNED`: component-level frontend coverage and conversation restoration after reload.

Do not mark this milestone complete from health checks alone.

## Milestone 2: personal memory — SCAFFOLDED

Current evidence as of 2026-07-16:

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
- `UNVERIFIED`: at-rest/backup encryption, tested backup/restore, token revocation/password-based login, non-blocking database access, load/concurrency behavior, and operational monitoring.
- `UNVERIFIED`: approval-based capture for durable facts other than preferred name, automatic extraction, and a general structured-memory policy.

Delivered local-development capabilities include:

- user profile storage and retrieval;
- episodic memory with user scoping;
- semantic memory backed by embeddings and pgvector;
- migration coverage and integration tests;
- privacy controls and deletion behavior.

Explicitly saved memory, bounded same-conversation recall, structured approval-based preferred-name capture, relevance-gated semantic retrieval, lifecycle controls, optional signed ownership, and the safe tool-memory store work. The milestone is not complete until normal chat supports additional approved fact types and the remaining operational/encryption gates below pass. With auth disabled, caller-supplied user IDs remain only logical scope; production-like deployment must enable auth and protect the signing secret.

Production-grade memory completion gates:

- authenticated ownership and authorization on every conversation and memory read/write/delete path;
- approval-based fact capture with provenance, confidence, purpose, and timestamps rather than silent model extraction;
- correction, versioning, contradiction handling, deduplication, export, per-record deletion, delete-all, and deletion propagation to embeddings, conversations, caches, logs, and backups;
- retention/expiry policies, storage and backup encryption, tested backup/restore, and redacted audit events;
- semantic relevance thresholds, hybrid retrieval/reranking where justified, prompt-injection isolation, and a repeatable retrieval-quality/privacy evaluation set;
- embedding-model/version metadata plus a tested re-embedding and vector-dimension migration path;
- non-blocking database access, service-level transaction boundaries, idempotent writes, indexes, concurrency/load tests, failure recovery, and operational monitoring.

These are remaining requirements, not claims about the current local scaffold. They should be delivered in separately verified atomic stages.

## Milestone 3: knowledge and RAG — PLANNED

- document ingestion and chunking;
- framework-independent retrieval contracts;
- semantic and metadata retrieval;
- hybrid search and reranking;
- evaluation of retrieval quality;
- optional RAGFlow, parent-document, GraphRAG, MultiQuery, and HyDE experiments.

The embedding-provider boundary used by personal memory does not constitute a document retriever or working RAG system.

## Milestone 4: tools and specialized agents — PLANNED

- MCP client connections with explicit server trust, authentication, and per-user authorization scopes;
- real tool registry and permission model;
- semantic discovery over safe, versioned MCP tool descriptors;
- user-scoped tool preference and usage-outcome memory;
- deterministic, testable LangGraph workflows;
- privacy-preserving internet research and synthesis;
- coding, finance, and scheduling capabilities;
- reflection and multi-agent orchestration;
- traceable tool execution with user control.

The current one-node graph is model-backed but is not multi-agent orchestration. Researcher and tool-executor agents are not implemented.

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

Safe tool-descriptor embeddings plus approved preference/sanitized outcome memory are `VERIFIED` as persistence and discovery boundaries. Live MCP connectivity, authoritative `tools/list` refresh/change notifications, permission-aware invocation, and pre-invocation registry re-resolution remain `PLANNED`; a stored descriptor never authorizes a call.

## Milestone 5: additional interfaces and automation — PLANNED

- notifications;
- calendar and email integrations;
- voice interaction;
- mobile applications;
- proactive automation with explicit permission boundaries.

Security and privacy gates in [SECURITY.md](SECURITY.md) apply before these capabilities can be considered complete.
