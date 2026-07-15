# AniOS Roadmap

This document is the canonical milestone tracker. It records durable status at a higher level than the frequently rewritten [NEXT_SESSION.md](NEXT_SESSION.md).

## Status definitions

- `VERIFIED`: the milestone behavior passed an applicable runtime or functional check.
- `FAILED`: an attempted acceptance check failed.
- `UNVERIFIED`: adequate evidence has not been collected.
- `SCAFFOLDED`: structure exists without complete demonstrated behavior.
- `MOCKED`: placeholder behavior is wired.
- `PLANNED`: future work that is not current functionality.

## Milestone 1: stable conversational platform — FAILED

Goal: provide a locally runnable frontend and backend that complete a real chat request, stream a meaningful response, and persist the conversation.

Current evidence as of 2026-07-16:

- `VERIFIED`: PostgreSQL and Redis start in Compose; PostgreSQL reported healthy while the backend ran from current host source.
- `VERIFIED`: the documented chat payload returns `200 text/event-stream`, reaches `ConversationService`, emits the placeholder response, terminates, and creates a conversation row.
- `VERIFIED`: initial Alembic revision `20260716_0001` creates the four application tables and `alembic check` reports no pending operations.
- `VERIFIED`: real Edge browser runs covered chat success, stream termination, loading cleanup, clean Console/Network state, and a visible handled network-failure message.
- `VERIFIED`: targeted chat/API tests pass, and the frontend TypeScript/Vite production build passes.
- `FAILED`: the graph returns fixed `Thinking...` content rather than a response from a real configured model.
- `FAILED`: the complete backend suite still has four setup errors in the older async memory-service test module.
- `UNVERIFIED`: automated UI coverage; no frontend test script or committed browser automation harness exists.

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

- `SCAFFOLDED`: deterministic backend/API coverage exists for the current placeholder conversation path;
- `PLANNED`: frontend component coverage for loading, streaming, success, and failure states;
- `PLANNED`: browser end-to-end coverage for the real chat workflow;
- `PLANNED`: a separate opt-in live-LLM acceptance check.

Do not mark this milestone complete from health checks alone.

## Milestone 2: personal memory — PLANNED

Existing models, interfaces, and service classes are `SCAFFOLDED`. Planned deliverables include:

- user profile storage and retrieval;
- episodic memory with user scoping;
- semantic memory backed by embeddings and pgvector;
- migration coverage and integration tests;
- privacy controls and deletion behavior.

Begin only after the stable conversational path provides a trustworthy integration surface.

## Milestone 3: knowledge and RAG — PLANNED

- document ingestion and chunking;
- framework-independent retrieval contracts;
- semantic and metadata retrieval;
- hybrid search and reranking;
- evaluation of retrieval quality;
- optional RAGFlow, parent-document, GraphRAG, MultiQuery, and HyDE experiments.

Abstract embedding and retriever classes currently present in the repository are `SCAFFOLDED`; they do not constitute a working RAG system.

## Milestone 4: tools and specialized agents — PLANNED

- real tool registry and permission model;
- deterministic, testable LangGraph workflows;
- internet research and synthesis;
- coding, finance, and scheduling capabilities;
- reflection and multi-agent orchestration;
- traceable tool execution with user control.

The current one-node graph is `MOCKED`. Researcher and tool-executor agents are not implemented.

## Milestone 5: additional interfaces and automation — PLANNED

- notifications;
- calendar and email integrations;
- voice interaction;
- mobile applications;
- proactive automation with explicit permission boundaries.

Security and privacy gates in [SECURITY.md](SECURITY.md) apply before these capabilities can be considered complete.
