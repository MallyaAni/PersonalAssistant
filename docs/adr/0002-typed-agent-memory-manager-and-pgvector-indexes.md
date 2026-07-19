# ADR 0002: Typed Agent Memory Manager and pgvector HNSW Indexes

## Status

Accepted and implemented for the local-development memory system.

## Context

AniOS needs several memory forms with different lifecycle and trust rules. Exposing raw tables or a generic unrestricted store to an LLM would mix policy, persistence, and authorization. Oracle examples commonly use a central store manager plus per-store vector indexes, but AniOS runs PostgreSQL with pgvector and owns schema evolution through Alembic.

## Decision

1. `AgentMemoryManager` exposes typed stores for semantic cache, working memory, procedures, entities/relations, knowledge, and summaries.
2. `MemoryCoordinatorAgent` may plan and retrieve through those typed methods but cannot execute arbitrary SQL or authorize durable writes on behalf of the model.
3. Durable user-authored procedures, entities, knowledge, profile facts, and tool preferences remain explicit API or approval operations. Automatic writes are limited to expiring coordination state, cached query plans, conversation turns, and periodic conversation digests.
4. Vector-bearing PostgreSQL tables use 768-dimensional pgvector columns and cosine-distance retrieval.
5. Alembic owns HNSW cosine indexes. AniOS does not copy Oracle-specific IVF helpers or expose database-specific table handles to the agent.
6. Retrieved values are bounded, user-scoped, filtered for lifecycle state, and serialized into the model prompt as untrusted literal data.

## Consequences

Benefits:

- store-specific invariants, authorization, retention, and deletion remain testable;
- the coordinator can select memory without receiving raw database authority;
- HNSW supports useful approximate lookup without an IVFFlat training phase;
- database schema and runtime code stay aligned through migration drift checks.

Costs and risks:

- additional typed models, routes, migrations, and tests increase maintenance;
- synchronous SQLAlchemy and embedding calls can block under concurrent load;
- HNSW indexes consume build time and storage and still require production recall/latency measurement;
- deterministic intent routing is intentionally conservative and will need evaluation before broader automatic memory selection.

## Alternatives considered

- A single generic key/value-vector store was rejected because it would erase lifecycle and approval distinctions.
- Direct model access to a store manager or SQL was rejected because it would bypass policy and least privilege.
- Oracle Vector Search tables and IVF helper code were rejected because AniOS uses PostgreSQL/pgvector and Alembic.
- pgvector IVFFlat was not selected as the default because it needs representative data and tuning before index creation; it can be reconsidered from measured production workloads.
