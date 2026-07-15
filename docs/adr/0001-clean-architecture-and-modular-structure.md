# ADR 0001: Clean Architecture and Modular Structure

## Status

Accepted design direction. Implementation is `SCAFFOLDED` and only partially conforms.

## Context

AniOS is intended to grow across conversation, memory, retrieval, and agent capabilities. Direct coupling among FastAPI routes, databases, model providers, and orchestration frameworks would make those components difficult to test or replace.

## Decision

AniOS will apply clean-architecture principles proportionally to implemented needs:

1. Business workflows depend on explicit contracts rather than concrete databases, model providers, or external services.
2. API routes handle transport concerns and delegate workflow behavior to services.
3. Services coordinate domain and infrastructure collaborators without owning framework setup.
4. Memory, retrieval, LLM, tool, and repository implementations remain replaceable behind focused interfaces.
5. LangGraph may orchestrate workflows but must not own AniOS memory, retrieval, user profiles, or domain policy.
6. New abstractions must correspond to a real boundary or test need; speculative interfaces are not required merely for architectural symmetry.

## Consequences

Benefits:

- infrastructure can be replaced with less impact on workflow logic;
- services and graph nodes can be tested with controlled collaborators;
- ownership boundaries reduce duplicated business behavior;
- future capabilities can be added without beginning as separate microservices.

Costs and risks:

- interfaces and dependency assembly add boilerplate;
- sync/async or model-contract mismatches can be hidden behind superficially clean layers;
- unused abstractions can imply capabilities that do not exist;
- conformance requires tests and runtime evidence, not directory names alone.

## Alternatives considered

- Standard framework-centric layering was rejected as the long-term default because business behavior could become coupled to FastAPI or SQLAlchemy.
- Microservices were rejected for the current stage because they would add operational complexity before stable in-process boundaries exist.

## Implementation note

The repository currently contains presentation, service, interface, and infrastructure modules, but several implementations are `SCAFFOLDED` or `MOCKED`, and some contracts are inconsistent. [The architecture document](../ARCHITECTURE.md) is authoritative for current implementation facts; this ADR records the intended direction.
