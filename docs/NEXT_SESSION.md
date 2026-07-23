# Next Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in [CHANGELOG.md](CHANGELOG.md), durable milestone status in [ROADMAP.md](ROADMAP.md), and stable architecture facts in [ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-22, America/New_York

## Current milestone

**Milestone 5: tools and specialized agents — `IN PROGRESS`; Gemma-selected MCP execution, MCP internet search, and visible browser tool lifecycle are `VERIFIED`.**

Gemma remains AniOS's primary response model. For an ordinary chat turn, the application retrieves a bounded user-scoped tool shortlist, re-resolves every candidate against its live MCP server, and gives Gemma only opaque aliases plus current schemas. Gemma may select at most one tool and provide arguments; it never receives execution authority. AniOS revalidates the plan, applies risk and outbound-privacy policy, invokes the MCP server, bounds the result as untrusted data, and supplies that result to the final response graph.

Internet search is now an MCP tool. Deterministic freshness routing and query privacy remain outside Gemma, then the fixed read-only `internet/search_web` MCP server wraps Tavily. This prevents a model-selected tool call from bypassing the decision about whether or what AniOS may send to the internet.

The browser shows `Using <tool> via <server>...` while a call is active and a terminal used/refused/failed state afterward. Arguments and raw results are not exposed in the status. Search results retain their separate source-card presentation.

## Git and runtime state

- Starting Git state: branch `main` at `df00a085621326ec746018fc003452cf5f2b68dd`; the MCP implementation and documentation were unstaged. Git was located explicitly at `C:\Program Files\Git\cmd\git.exe` because it is not on this shell's `PATH`.
- The user authorized a commit after acceptance. The verified implementation checkpoint SHA is recorded below after creation; no tag, branch, stash, reset, restore, checkout, push, or recovery operation was created.
- Final exercised backend image: `sha256:e90212c69db88bc67af3718b69aabc041166644de90339ea057410a9e8f6bcba`, started at `2026-07-23T02:34:08Z`.
- Docker `backend`, `frontend`, `db`, and `redis` were running for final acceptance. LM Studio served `google/gemma-4-12b` through `host.docker.internal:1234`.
- Root `.env` and `.env.example` select `SEARCH_PROVIDER_NAME=mcp` and configure the built-in `local_utility` and `internet` stdio servers. The search credential remains a separate environment value and is inherited by the internet child only through its variable-name allowlist.
- No database schema change was introduced by this task.

## VERIFIED

### Gemma and MCP execution boundary

- A live LM Studio probe showed `google/gemma-4-12b` returning a native OpenAI-compatible `tool_calls` decision for a supplied function, rather than AniOS parsing tool intent from prose.
- Both stdio and streamable-HTTP MCP configuration now use one parser. A regression test proves HTTP entries survive dependency assembly instead of being silently dropped.
- The application shortlists user-scoped descriptor embeddings, excludes deterministic-search tools from ordinary autonomous selection, re-reads the live description/schema/fingerprint, exposes at most five locally eligible `read_only` or `trusted` candidates, accepts at most one native Gemma call, validates JSON arguments, and invokes only through `MCPInvocationService`.
- Stdio children receive the MCP SDK's safe base environment plus only operator-named `inherit_env` values. Secret values are not placed in MCP JSON, descriptor memory, model prompts, or browser status events.
- Live registry synchronization declared and indexed exactly two tools for each acceptance user: `local_utility/current_time` and `internet/search_web`, with no quarantined descriptors.

### Direct `POST /api/v1/chat` acceptance and logs

- The documented payload contract (`user_id`, `conversation_id`, `query`, and `metadata`) was submitted directly with user `final_mcp_api_probe` and conversation `93939393-9393-4393-8393-939393939393`.
- The final image returned HTTP 200 with `text/event-stream`. The standards-correct SSE parse observed: `start`, `search_started`, internet `tool_started`, internet `tool_finished/succeeded`, `search_results`, local utility `tool_started`, local utility `tool_finished/succeeded`, response `delta` events, and terminal `done`.
- Trace `0bc09d06-8fa5-4a09-ac83-27804b00cea6` assembled the exact answer `{"timezone": "UTC", "iso8601": "2026-07-23T02:36:17+00:00", "utc_offset": "+0000"}` from the live tool result.
- Backend logs show the two MCP calls, LM Studio requests returning 200, and `graph_execution` progressing from `started` to `completed` without an associated exception.
- Scoped cleanup deleted the disposable user's two tool descriptors, two conversations, and four working-memory rows.

### Real browser chat acceptance

- `RUN_LIVE_TOOL_TESTS=1 npx.cmd playwright test --grep '@live uses a Gemma-selected MCP tool'` passed: `1 passed` in 54.2 seconds (53.5-second workflow) against the final backend image and real Vite UI.
- Chromium submitted a unique message, observed a completed HTTP 200 SSE request, captured the transient `Using current_time via local_utility...` state with a DOM observer, rendered terminal `Used current_time via local_utility`, and displayed the UTC answer.
- The same browser session submitted an explicit latest-version search, captured transient `Using search_web via internet...`, rendered terminal `Used search_web via internet`, and displayed the `Web sources used` region.
- Both streams terminated, `Thinking...` disappeared, the composer re-enabled and cleared, and the test observed no blocking Console error or page exception.
- The live browser user was deleted through the scoped delete-all API in test cleanup.

### Automated regression and documentation

- Backend: `339 passed` in 23.79 seconds. The only warning is Starlette's upstream `TestClient`/`httpx` deprecation warning.
- Python quality: Ruff passed; Black reports all 155 files unchanged; strict MyPy reports no issues in 109 source files.
- Frontend production build passed TypeScript and Vite. The optional Mermaid chunk above 500 kB remains a non-blocking bundler advisory.
- Deterministic Chromium: all 28 workflows passed in 27.7 seconds, including visible MCP success/refusal, chat completion/failure cleanup, conversation persistence, memory controls, artifacts, image generation, upload, analysis, and image followups.
- All nine canonical Mermaid/SVG pairs and the published architecture page are synchronized. The five affected rendered views were visually inspected without clipping.
- Persistent Compose interpolation reports `SEARCH_PROVIDER_NAME: mcp` and the two built-in server definitions from root `.env`.

## FAILED evidence encountered and resolved

- Runtime dependency assembly had a second config parser that discarded HTTP MCP entries. Reusing the canonical parser fixed the first MCP transport boundary and the regression now passes.
- The internet stdio child initially lacked search configuration. An explicit environment-name allowlist fixed that boundary without copying secrets into registry metadata.
- Generic MCP result limiting truncated long search JSON mid-document, so the provider could not produce source cards. Compact server-side result serialization now stays below the generic cap and remains valid JSON.
- The first full backend rerun found one stale package-boundary assertion that omitted the new `search/mcp.py` and `search/query.py` modules. Updating that architecture assertion produced the final 339-pass run.
- Initial `npm`/`npx` invocations hit the host PowerShell script-execution policy; the documented `npm.cmd`/`npx.cmd` entry points passed unchanged.
- The first diagram check was launched from the repository root, which has no `package.json`; the correct frontend-package command passed with all nine diagrams synchronized.
- The first final direct validation used `message` instead of the documented `query` field and correctly returned 422. Repeating with the documented payload returned the verified stream above.
- An initial direct-parser script looked only inside JSON for an event type even though SSE carries it on the preceding `event:` line. A standards-correct parser captured the exact lifecycle above; the server response did not change.
- The three-failed-hypothesis threshold was not reached for any product boundary.

## FAILED / open repository evidence

- `alembic current` reports `20260721_0012 (head)`, but `alembic check` detects a proposed removal of `ix_visual_artifacts_embedding_hnsw`. This task did not change models or migrations, so the unrelated pre-existing model/metadata drift was not modified. Do not claim schema drift is clean until that index is represented consistently.

## UNVERIFIED / deliberately deferred

- MCP descriptor synchronization is still an explicit per-user CLI operation. Automatic startup/on-demand refresh, change notifications, stale-descriptor deactivation, and registry health reporting are not implemented.
- Chat selects at most one autonomous tool per turn. Multi-step tool loops, parallel tools, delegated subagents, general LangGraph multi-agent orchestration, and A2A collaboration are not implemented.
- Consequential MCP tools are withheld from autonomous selection. A visible proposal/approval/resume workflow is not implemented.
- Tool usage outcomes can be stored through the memory API, but chat execution does not yet write a durable redacted execution/audit record or learn a preference from tool success/failure.
- Tool status is part of the live SSE answer state; restoring a conversation does not currently reconstruct historical tool lifecycle badges.
- Per-server user authorization scopes, broader MCP security hardening, and remote-server credential management remain intentionally deferred to the final security subsystem.
- Sustained concurrent MCP/tool/model load, server crash recovery, retry/backoff policy, distributed workers, and DGX Spark deployment profiles have not been benchmarked.

## Next atomic task

Implement automatic MCP registry lifecycle management without adding subagents yet:

1. Refresh configured server catalogues on first use or startup under a bounded timeout.
2. Compare live identities/descriptions/schemas with user-scoped descriptors, index new/changed tools, and deactivate removed or unavailable tools.
3. Prevent stale descriptors from being selected while preserving the existing pre-invocation live revalidation.
4. Expose bounded registry health and last-refresh evidence without secrets.
5. Verify add/change/remove/unavailable behavior through backend tests plus a real browser turn that works without a manual sync command.

After that boundary is reliable, add one focused delegated-agent graph that consumes the same application-owned MCP selector/invoker; do not let subagents own credentials, permissions, persistence, or unrestricted internet access.
