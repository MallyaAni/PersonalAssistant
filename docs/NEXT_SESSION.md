# Next Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in [CHANGELOG.md](CHANGELOG.md), durable milestone status in [ROADMAP.md](ROADMAP.md), and stable architecture facts in [ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-16, America/New_York

## Current milestone

**Milestone 2: Personal memory — `SCAFFOLDED`**

The local chat and personal-memory acceptance path is functionally verified through structured preferred-name facts, relevance-gated pgvector retrieval, correction/export/expiry/deletion controls, optional signed user ownership, and safe MCP tool-descriptor/preference/outcome memory. Trace IDs remain per request; conversation IDs remain stable until the user or `New conversation` action rotates them. The responsive light-neutral UI uses a search-first landing state and question/result chat flow; request IDs remain available from an answer-level three-dot metadata popover. The composer inherits the shell's native system font stack. Missing or legacy placeholder browser identity migrates to `ani.mallya` with a new conversation, while custom identities remain unchanged. The active transcript survives Chat/Memory view switches, while full-reload transcript restoration remains unimplemented.

This is not fully production-grade memory. Chat capture still recognizes only preferred names; auth is optional and lacks password login/revocation; encryption, tested backup/restore, async database access, load/concurrency testing, and monitoring remain unfinished.

Internet search is not implemented. The roadmap and security guide now define a planned deterministic search decision and outbound privacy gate; Gemma is not to receive unrestricted network access.

Safe MCP tool memory is implemented, but MCP connectivity and execution are not. A stored descriptor is discovery metadata only: future invocation must refresh the live authorized registry, compare schema/permissions, and apply confirmation policy. Raw arguments, outputs, credentials, and private resources are outside this store.

## Git state

- Starting branch: `main`.
- Starting `HEAD`: `7d434f5c58274e24a26998fdcc2179a55e8db569`.
- Starting working tree: dirty only with the prior verified composer focus-style implementation, browser regression coverage, and handoff update.
- Final branch: `main`.
- Final `HEAD`: `6db1488025478cbcbcf9ec4e451e7ca2623d8820` (`Updated UI and memory sessions`), authored concurrently by Ani and also present at `origin/main`.
- Final working tree: dirty only with the `docs/CHANGELOG.md` and `docs/NEXT_SESSION.md` updates made after that concurrent commit.
- Codex performed no commit, tag, branch, stash, reset, restore, checkout, recovery, push, or Git index cleanup. The concurrent external/user commit incorporated the verified frontend source and tests along with broader existing work while this task was in progress.
- Runtime validation re-exercised the exact frontend source and tests committed at `6db1488025478cbcbcf9ec4e451e7ca2623d8820` through Playwright Chromium and a production build; backend behavior was unchanged and not re-exercised for these frontend-only tasks.

## VERIFIED

### Completed memory stages

- Semantic retrieval applies user scope, expiry, cosine distance `<=0.35`, five-result maximum, and a 4,000-character content budget. Direct user `retrieval_direct_1784254548260` returned only the relevant record at distance `0.153021`/relevance `0.846979`; Gemma returned `RETRIEVAL1784254548260` and the stream ended in `done`.
- The evaluation fixture and integration tests cover exact hits, misses, threshold edge, bounded results, cross-user isolation, prompt-injection-shaped content, and embedding-provider failure.
- Direct user controls corrected record `fdaa7871-ff45-4101-90c3-c04c27a9a7cd`, exported schema 1, deleted it, and read back zero records. Deterministic and live Chromium also corrected, downloaded export JSON, recalled the corrected value, and deleted memory with clean browser errors/network state.
- Migrations `0005` through `0007` add retention/embedding metadata, provenance idempotency, and tool-memory tables. A fresh isolated database passed `0001 → 0007 → 0004 → 0007`, no-drift, and head checks before the temporary database was dropped. New semantic records persist purpose, Nomic model/version, dimension 768, and optional expiry; expired records are retrieval-ineligible but exportable.
- Preferred-name approval is idempotent by user/key/source trace. Identical retries return the same fact; conflicting values for one trace return 409; the database uniqueness constraint is at head.
- Auth-enabled port-8001 validation returned 401 without a token, 403 for a different token subject, 200 for the owner, and a terminal authenticated chat stream. Auth-disabled trusted-local mode remains the default.
- Direct tool-memory user `tool_direct_1784255600335` embedded/retrieved a safe calendar descriptor at distance `0.199943`, stored approved preference `work calendar lookups` and sanitized outcome `success`, and deleted all records. Tests cover stale schema deactivation, cross-user/server isolation, missing live descriptor, sensitive-marker rejection, and no raw argument/output fields.
- Fresh `python debug_test.py` returned 200 SSE with trace `75032de7-2138-4031-858c-6ede7304ff98`, conversation `cbba602f-28e5-4678-bf72-d356a3d39867`, 20 deltas, and `done`. Export readback contains the exact query and complete AniOS response; backend logs show embedding/chat 200 and graph completion without an exception.
- Final gates: 53 backend tests pass; Ruff, MyPy, Black, Alembic drift, and `pip check` pass; frontend build passes; 12 deterministic and 4 live Chromium tests pass.

### Structured preferred-name facts

- Migration `20260716_0004` upgraded the current database, and an isolated empty database passed upgrade, downgrade to `0003`, re-upgrade, and `alembic check` without drift.
- Direct user `facts_direct_1784254234011` rejected without a write, approved fact `4246ad33-cb0e-4a76-9db4-1ba6bd147712`, recalled `Approved1784254234011`, corrected through fact `0b9921a7-dae2-4ac5-9022-e5c3f06068a4`, and recalled `Corrected1784254234011`. Snapshot state was `2:approved,1:superseded`; every stream ended in `done`, logs completed cleanly, and cleanup removed the test memory.
- The real Chromium preferred-name reject/approve/recall/correct/recall/delete test passed against current source, PostgreSQL, LM Studio Gemma, and Nomic embeddings.
- LM Studio probes proved `reasoning_effort=none` produces visible content with zero reasoning tokens. The adapter now sends that explicit configurable value, and the approved-memory prompt distinguishes trusted keys/inclusion from untrusted literal values.

### Cleanup and first failing boundaries

- The prior dense dark console was replaced with a responsive light-neutral shell, translucent navigation, Apple-system font stack, centered search composer, and left-aligned search-result answer cards. No external images, copied brand assets, or new dependency were added.
- A single Composer instance changes position between empty and active chat so the visual transition cannot remount it mid-stream. Trace and conversation identifiers are parsed from the existing frontend envelope and exposed by an accessible three-dot metadata popover while the answer remains primary.
- The composer explicitly inherits the root native font stack, which selects Apple's SF Pro aliases on Apple platforms and `system-ui`/Segoe UI on the current Windows host. Chromium computed-style acceptance proved the root and textarea font-family values match.
- The chat composer no longer inherits the global translucent blue textarea focus outline or adds a blue focus shadow. Focused Chromium computed styles show a transparent textarea with no outline inside a white shell using only neutral border/shadow colors; the screenshot showed no blue background, Console errors, or page exceptions. Other controls retain the global accessible focus treatment.
- Chat submission now renders an accessible, gently pulsing `Thinking...` assistant row immediately after submission. The row remains through the SSE `start` metadata frame, is replaced when the first response `delta` arrives, and clears before the visible fallback error on failure.
- New browser state and the legacy placeholder `dev_user_001` now initialize as `ani.mallya`; legacy conversation identity rotates at the same boundary. Deterministic browser acceptance also proved a custom stored user/conversation pair remains unchanged. This does not turn the UI default into an authentication boundary.
- Chromium verified the search-first shell at 390 x 844 with the sidebar collapsed by default, an accessible reopen action, and no horizontal overflow. Desktop empty, active-results, and Memory screens were also visually inspected from current Vite source.
- A new Chromium regression reproduced the reported transcript loss after Chat -> Memory -> Chat navigation. `App` was unmounting `ChatWindow`, whose transcript is local state; keeping it mounted while hidden preserves the active transcript, while existing user/conversation keys still reset it intentionally.
- A second Chromium regression proved `New conversation` appeared inert from Memory because it only rotated a hidden ID. The action now opens a fresh Chat view. Conversation rotation was separated from view navigation so switching users still remains on Memory and resets the correct chat state.
- Empty Send and manual-memory buttons previously looked active but performed no action. They are now disabled until non-blank content exists. Manual episodic/semantic creation remains available for explicit seeding and validation, but is presented under `Advanced: add memory manually` using `event or experience` and `fact or preference` labels.
- The active dependency graph now contains only the memory service, LM Studio client, conversation repository, and logging tracer. Obsolete no-op service/context/tool/streamer interfaces and implementations were removed.
- Chat request validation rejects missing, blank, oversized, malformed UUID, and extra input. Successful responses use framed SSE events, require client-observed start/done termination, and expose a generic error event without provider details.
- The first deterministic browser attempt after frontend edits reached an older Vite transform. Process/source inspection identified the stale server; restarting the verified workspace Vite process made the unchanged five-test suite pass.
- The first final backend-suite attempt used the Compose-only database hostname `db` from the host and failed DNS resolution. Repeating the unchanged suite with documented `POSTGRES_HOST=127.0.0.1` passed all 27 tests; this was an environment boundary, not a source defect.
- The first current-source direct request completed correctly but log inspection showed only Uvicorn access output. `setup_logging` was not called. The targeted configuration fix enabled trace lifecycle logs and removed the caller user ID from the trace-start message; the repeated request produced start/completed events without raw prompt/body logging.

### Direct API and logs

- Direct preferred-name acceptance used user `pname_direct_1784252931944` across conversations `163e6881-10b7-497d-b6fe-46dc0445987e`, `979ce68b-764b-4bff-89f7-b6f32026264b`, and `b1a9689d-5a9b-4234-be00-741944274925`.
- Five documented chat requests returned `200 text/event-stream` and terminal `done` events. Rejection left no name, approval stored `Approved1784252931944`, a new conversation returned exactly that value, correction stored `Corrected1784252931944`, another new conversation returned exactly the correction, another user saw no name, and deletion persisted `null`.
- The first five-call attempt reached LM Studio but its final response spent the 512-token budget without visible message output, producing the expected safe SSE error. Raising the default output budget to 1,024 tokens made the identical repeated path pass.
- Backend logs show all five repeated graph/provider paths completed without a server exception or raw personal-content logging.

- `python debug_test.py` submitted the documented `user_id`/`conversation_id`/`query`/`metadata` payload directly to `POST http://127.0.0.1:8000/api/v1/chat`.
- The response was `200 text/event-stream; charset=utf-8` with trace `ba635c1e-6db3-4262-b3c4-d63662d47503`, conversation `8532f6cd-0148-423b-a597-351568a37d28`, 21 content deltas, and a terminal `done` event.
- The accumulated response was `My name is AniOS. I am your helpful local personal assistant. How can I help you today?`
- Backend logs show the trace start, LM Studio embedding/chat requests returning 200, graph `started`, and graph `completed`. They contain no raw request body or user ID for this request.

### Real browser and persistence acceptance

- Current live preferred-name acceptance used `pname_live_1784253033582`. Chromium rejected `Rejected1784253033582` without a profile write, approved and recalled `Approved1784253033582` in a new conversation, corrected and recalled `Corrected1784253033582` in another new conversation, verified another user had no name, and deleted the preferred name.
- Network observed completed chat SSE responses plus successful approval/deletion requests; proposal and chat controls recovered after each operation. There were zero blocking Console errors and zero page exceptions.
- PostgreSQL retains the five exact conversation queries/responses under three conversation IDs and contains no profile row for the cleaned-up live user after deletion.

- `ANIOS_E2E_LIVE=1 npm.cmd run test:e2e:live` opened the current frontend in Playwright Chromium and passed all four live tests against the current backend, PostgreSQL, LM Studio Gemma, and Nomic embedding model.
- The unique UI query `Reply with exactly: LIVE_GEMMA_1784249602162` rendered `Response: LIVE_GEMMA_1784249602162`. Network returned `200 text/event-stream`, the request finished, the textarea remained disabled while content streamed and then re-enabled/cleared, and the empty send button disabled until new content was entered.
- The repeated live Gemma test uses a disposable isolated user, navigates through its real memory snapshot request, observes HTTP 200 with no visible error, returns to Chat, finds the exact user query and assistant response still rendered, and deletes the isolated data. The complete four-test live suite records no blocking Console errors or page exceptions without adding validation conversations to `ani.mallya`.
- After the theme change, all four live Chromium workflows again passed against current PostgreSQL, LM Studio Gemma, and Nomic embeddings; the new result-card selectors observed complete real answers, stream termination, loading cleanup, memory approval/lifecycle controls, and clean browser errors.
- The same-conversation test used user `live_history_1784249607119` and conversation `64bd9164-c54e-4868-ba72-3c8dd32e67e5`; the second prompt omitted the unique name and rendered `BrowserName1784249607119`.
- The memory test created/reloaded semantic memory for `live_memory_1784249619179`, Gemma returned `MEMORY_1784249619179`, and the UI deleted the memory. Backend logs show completed traces and no server exception.
- All live tests recorded zero blocking Console errors and zero page exceptions. The deterministic failure test renders `Unable to send message. Please try again.` and clears loading state.
- PostgreSQL readback exactly matched the live Gemma token, two same-conversation history turns, and live memory recall response under their observed users/conversation IDs.

### Regression and quality gates

- `POSTGRES_HOST=127.0.0.1 python -m pytest -p no:cacheprovider backend/tests -q`: 37 passed with one upstream Starlette/httpx deprecation warning.
- `npm.cmd run test:e2e`: 12 passed, including the responsive 390 x 844 search shell, native composer font, hidden/open metadata behavior, legacy-default migration and custom-user preservation, proposal rejection/approval, visible approval failure, visible thinking-state success/failure transitions, stream success/failure, conversation rotation, transcript preservation across view navigation, new-conversation navigation, honest disabled states, user isolation, and memory management.
- The focused-composer browser regression specifically asserts a transparent textarea, no textarea outline, a white shell, and no Apple-blue value in the focused shell border or shadow.
- `ANIOS_E2E_LIVE=1 npm.cmd run test:e2e:live`: 4 passed.
- `npm.cmd run build`: TypeScript and Vite 8.1.4 passed; 1,385 modules transformed.
- `python -m black --check backend migrations debug_test.py`: 47 files unchanged.
- `python -m ruff check backend migrations debug_test.py`: all checks passed.
- `python -m mypy backend`: no issues in 33 source files.
- `python -m pip check`: no broken requirements.
- `npm.cmd ls --depth=0` contains only declared dependencies; `npm.cmd audit --omit=dev` found zero vulnerabilities.
- `python -m alembic check`: no new upgrade operations detected.

## FAILED

- The first structured-fact repeat reached recall but LM Studio consumed its 1,024-token budget as reasoning and emitted no visible message. The supported `reasoning_effort=none` change made the repeated provider and full paths terminate with answers.
- The next recall said no name was available although PostgreSQL and the profile projection contained it. An exact-prompt probe reproduced Gemma treating the entire memory block as ignorable; the narrowed trust-label wording made both the provider probe and repeated end-to-end path return the approved value.

- Initial browser regression failed because an existing Vite process served stale transformed source. No application hypothesis was changed; the same suite passed after the identified process was restarted from the workspace.
- Initial final backend regression produced 2 failures and 6 setup errors because a host process tried to resolve PostgreSQL as `db`. The documented host override fixed all eight on the first hypothesis.
- Initial direct acceptance did not emit application trace logs because logging setup was unused. Calling it at application assembly fixed logging on the first source hypothesis.
- A composite Alembic recheck inherited host `DEBUG=release` and no `SECRET_KEY`; the explicitly configured repeat reported no migration drift.
- The first local-link script unintentionally recursed into dependency READMEs and reported their package-internal missing targets. Restricting the unchanged check to repository-owned Markdown found no broken local links.
- The first five-call preferred-name acceptance ended its final stream with a safe error because LM Studio produced reasoning but no visible message within 512 tokens. The 1,024-token hypothesis passed the identical full path; the three-failed-hypothesis limit was not reached.
- The initial transcript-navigation and new-conversation-from-Memory browser tests failed at the expected UI boundaries; each passed after its single targeted state-lifetime/navigation fix.
- The first full frontend regression after disabling blank actions had four failures: three stale assertions expected an empty Send button to be enabled, and user switching inherited the header action's Chat navigation. Updating the assertions and separating rotation from header navigation made all 10 tests pass.
- The first themed production build failed because the installed Lucide version does not export `LoaderCircle`. Replacing it with the supported `Loader2` icon made the unchanged theme build pass on the first compatibility hypothesis.
- No final acceptance criterion failed, and the three-failed-hypothesis rule was not reached.
- The first independent post-fix browser probe used the textarea placeholder incorrectly and timed out without exercising focus. Inspecting the rendered control showed that `Message AniOS` is its accessible label; the corrected role/label probe passed without an application change.
- The initial thinking-state browser assertions failed at the expected boundary because loading state was private to `Composer`; both success and failure paths passed after lifting that state to the transcript and distinguishing SSE `start` metadata from answer `delta` content.
- The first post-change production build rejected `Array.prototype.at` under the project's TypeScript target. Replacing that one expression with compatible indexed access made the unchanged full browser-and-build gate pass.

## UNVERIFIED

- Approval-based capture for fact types other than preferred name and automatic fact extraction.
- Production memory requirements still unverified: at-rest/backup encryption, tested backup/restore and deletion propagation into backups/logs, password/account management and token revocation, additional approved fact types/contradiction policy, async database access, load/concurrency testing, and operational monitoring.
- Internet-search routing, privacy classification/minimization, approval, allowlisting, result isolation, citation enforcement, and redacted decision auditing; these are roadmap requirements only.
- MCP connectivity, live tool-registry refresh notifications, permission-aware invocation, pre-invocation re-resolution, and a separate execution audit. Safe descriptor embeddings and user preferences/outcomes are verified persistence boundaries only.
- CI, a rebuilt Compose backend image, cleanup of artifacts already tracked by Git, and a functionally verified Git commit.
- Live provider chat and backend tests were not rerun for these frontend-only focus/thinking tasks; the deterministic Chromium suite and production frontend build were rerun.
- RAG/document ingestion, real tools, Redis application use, and multi-agent/sub-agent workflows.

## Files changed through the memory-hardening stages

- Backend/API/runtime: `backend/memory/proposals.py`, `backend/models/schemas.py`, `backend/services/conversation_service.py`, `backend/services/postgres_memory_service.py`, `backend/api/v1/memory.py`, and `backend/core/llm.py`.
- Tests: `backend/tests/test_memory_proposals.py`, `backend/tests/test_chat_api.py`, `backend/tests/test_memory_api.py`, `backend/tests/test_llm.py`, and `frontend/e2e/chat.spec.ts`.
- Frontend: `frontend/src/index.css`, `frontend/src/App.tsx`, `frontend/src/services/api.ts`, `frontend/src/components/Sidebar/Sidebar.tsx`, `frontend/src/components/Composer/Composer.tsx`, `frontend/src/components/ChatWindow/ChatWindow.tsx`, `frontend/src/components/MessageList/MessageList.tsx`, `frontend/src/components/MessageBubble/MessageBubble.tsx`, and `frontend/src/components/MemoryPanel/MemoryPanel.tsx`.
- Documentation: `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/ROADMAP.md`, `docs/SECURITY.md`, `docs/CHANGELOG.md`, and this handoff.
- Structured facts: `backend/models/memory.py`, `backend/memory/repository.py`, `migrations/env.py`, and `migrations/versions/20260716_0004_structured_memory_facts.py`.
- Provider/context stabilization: `backend/config/settings.py`, `backend/core/dependencies.py`, `backend/core/llm.py`, `backend/agents/graph.py`, `.env.example`, and their backend tests.
- Retrieval/lifecycle: `backend/memory/retrieval.py`, `backend/memory/errors.py`, migrations `20260716_0005` and `0006`, retrieval fixtures/tests, export/correction UI, and expanded live browser coverage.
- Auth/tool memory: `backend/core/auth.py`, `backend/cli/issue_token.py`, `backend/models/tool_memory.py`, `backend/services/tool_memory_service.py`, `backend/api/v1/tool_memory.py`, migration `20260716_0007`, `backend/tests/test_auth.py`, and `backend/tests/test_tool_memory_api.py`.

## Exact next atomic task

Add a second approval-based structured fact type (a low-risk explicit preference such as response style) using the existing proposal/version/provenance/expiry/idempotency lifecycle. Do not add automatic silent extraction, live MCP invocation, internet search, or orchestration in this stage.

## Acceptance criteria for the next atomic task

- A deterministic chat proposal recognizes only a narrow explicit preference statement and writes nothing before approval.
- Approval creates a versioned, idempotent structured fact with purpose/provenance/expiry; correction supersedes it, rejection writes nothing, and deletion removes its versions/projection.
- Only the current approved non-expired value reaches Gemma; cross-user and auth-enabled ownership checks pass.
- Direct API and real Chromium reject/approve/recall/correct/delete paths terminate cleanly, and all current regression gates remain green.
