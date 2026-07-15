# Changelog

This file is append-only history for meaningful, verified changes. It must not contain plans, active blockers, speculative work, or implementation-complete claims based only on source inspection.

## 2026-07-15 — Documentation system consolidated

- Replaced overlapping project, AI-context, engineering, debugging, completion, API, memory, RAG, and decision summaries with a ten-document system with explicit ownership.
- Added a concise root `AGENTS.md` and reduced `.clinerules/.clinerules.md` to a compatibility pointer.
- Separated volatile runtime handoff (`NEXT_SESSION.md`), durable milestone state (`ROADMAP.md`), current architecture (`ARCHITECTURE.md`), operational procedures (`DEVELOPMENT_GUIDE.md`), and verified history (this file).
- Corrected documentation claims using observed Compose, HTTP, Vite, test, build, OpenAPI, and PostgreSQL evidence.
- Removed the earlier `0.1.0` entry because it described the conversation engine and infrastructure as completed without recorded functional validation. Repository scaffolding remains documented as `SCAFFOLDED` in the architecture.

## 2026-07-15 — Agent workflow and UI verification clarified

- Restored the complete current-session handoff after it had been truncated.
- Condensed the local-model rules into an atomic evidence-driven loop with stale-artifact detection and a three-hypothesis stop condition.
- Made automated browser testing or documented manual browser execution the requirement for verified UI behavior; endpoint reachability is explicitly insufficient.
- Documented the currently absent frontend test harness as `PLANNED` without adding application dependencies or claiming runtime behavior changed.

## 2026-07-15 — Safe Git checkpoint policy documented

- Defined Git as recoverable code history while retaining functional evidence as the requirement for a verified checkpoint.
- Added starting and final branch, commit, and working-tree reporting when Git is available, with explicit `UNAVAILABLE` handling.
- Documented safe branch/worktree recovery and prohibited automatic destructive reset, clean, restore, checkout, and force-push operations.
- Added Git provenance fields to the current-session handoff without claiming that an existing commit is functionally verified.

## 2026-07-16 — Browser chat path restored

- Corrected the FastAPI chat dependency declaration so valid JSON reaches `ConversationService` and missing required fields still return intentional client errors.
- Added the initial PostgreSQL/pgvector migration, unified model metadata, aligned memory reads with the injected synchronous session, and supplied the required user ID when saving conversation turns.
- Made handled frontend request failures visible, added the missing TypeScript configuration, and restored the production build.
- Verified direct API streaming and persistence plus real Edge success and failure workflows, including rendered responses, stream termination, loading cleanup, Console/Network behavior, and user-visible failures.
- Added targeted chat API and service regression coverage; the graph remains a fixed placeholder and is not recorded as model-backed behavior.
