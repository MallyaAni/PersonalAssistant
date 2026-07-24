# Next Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-23, America/New_York

## Current milestone

**Milestone 5: tools and specialized agents — `IN PROGRESS`.**

Gemma-selected MCP execution, the local visual FastMCP facade, and
privacy-screened internet MCP search are implemented. AniOS also has one narrow
request-scoped Google ADK research subagent behind `SearchProvider`. This is not
general LangGraph multi-agent orchestration or A2A.

## Current implemented search/research boundary

- `ConversationService` owns deterministic freshness routing, query
  normalization, outbound privacy screening, tool/search SSE lifecycle, and the
  final handoff to local Gemma.
- `internet/search_web` is a read-only stdio FastMCP tool.
  `HybridSearchProvider` prefers Google when configured, falls back to Tavily
  when Google is disabled/failed/empty/over budget, and uses both only for
  explicit verify/cross-check language.
- Google uses pinned `google-adk==2.5.0`, the current default
  `gemini-3.6-flash`, native `google_search`, and ADK-required root-agent
  `mode="chat"`. Every call still creates a random in-memory one-request session
  with prior contents disabled.
- The Google worker receives only the normalized and privacy-screened public
  query under the constant worker identity `public-research`. It receives no
  AniOS user/conversation ID, history, personal memory, documents, image bytes,
  MCP credentials, or execution authority.
- Google output must contain grounding metadata and attributable sources.
  Otherwise Tavily fallback can run.
- `SQLiteDailySearchQuota` stores provider, Pacific date, and count only in the
  Compose `searchdata` volume. Its 450/day default is a local safety ceiling,
  not proof of Google quota or free access.
- Provider attribution survives MCP JSON, local result validation, prompt
  context, SSE, and browser source cards.

## Git and runtime state

- Baseline: branch `main`, `HEAD`
  `3db833ebae5205c643bc26ed00fb49bafb84725d`; the worktree already contained the
  unstaged hybrid-search implementation and documentation.
- This task additionally changed the Google ADK mode, current model default,
  related tests, configuration guidance, architecture facts, roadmap status,
  ADR qualification, and this handoff.
- Root `.env` remains ignored. The supplied key was used for the live checks and
  then removed from the active environment because every Google attempt failed;
  Tavily remains configured.
- No commit, tag, branch, stash, reset, restore, checkout, push, or recovery
  operation was created.
- The rebuilt backend image is
  `sha256:31673ecd4d93933c8928ab1f682f085118dedbd190f9a364bfa1fd3807691f0a`,
  started `2026-07-23T23:09:11.423898123Z`.
- `backend`, `frontend`, `local-capabilities`, PostgreSQL, and Redis are running.
  LM Studio serves local Gemma/Nomic on host port 1234.

## VERIFIED

### Deterministic provider behavior

- Focused Google, hybrid, quota, and internet MCP tests pass: `16 passed`.
- ADK isolation, grounded-source rejection, quota refusal, Google-primary
  selection, Tavily fallback, cross-check merging, and compact MCP serialization
  remain covered.
- Google ADK 2.5 accepts the rebuilt request after changing the root agent from
  invalid `mode="single_turn"` to required `mode="chat"`; isolation remains
  request-scoped through a fresh random in-memory session and
  `include_contents="none"`.

### Direct current-source runtime

- Rebuilt image `7467f508...` accepted the documented payload at
  `POST /api/v1/chat` and returned `200 text/event-stream`.
- Final free-model trace `c32ff9d8-8133-4ff1-90cf-6f0c3a617a53` emitted
  `start`, `search_started`, `tool_started`, successful `tool_finished`, five
  provider-attributed Tavily sources, answer deltas, and terminal `done`.
- Backend logs show the Google failure, real Tavily `200`, local Gemma `200`,
  and graph completion. The user still receives a response when Google is
  unavailable.
- Final safe-state trace `22fe0d7c-8c94-4be4-acb5-df8bfaadbf66` exercised the
  final rebuilt image with Google disabled: five Tavily sources, successful
  tool lifecycle, answer deltas, terminal `done`, and no Google HTTP request.
- The content-free quota database contains exactly
  `provider/quota_day/request_count`; four attempted Google reservations
  produced `('google', '2026-07-23', 4)` and stored no query or result text.

### Regression evidence

- Current full backend: `368 passed`; focused Black and Ruff checks pass; strict
  MyPy passes over 114 source files; Compose configuration is valid.
- `pip check` was not rerun in this task; the prior verified result reported no
  broken requirements and no dependency changed during the live-key fix.
- Frontend before this live-key task: production build passed; 31 deterministic
  Chromium workflows and the focused live Tavily workflow passed.
- Tavily browser trace `5604e820-b892-482a-b8ac-587dbb827bb3` showed visible
  tool lifecycle, provider-attributed sources, terminal streaming, cleared
  loading/composer state, and no blocking browser errors.

## FAILED

- Initial live trace `3a5a00c3-fbba-4979-9258-8312b1fcb9d0` reached the Google
  provider but ADK 2.5 rejected root-agent `mode="single_turn"`. The targeted
  mode fix advanced the request to Google HTTP.
- Trace `545c36b0-e6f1-4bbc-ada3-f59af1500f1b` used
  `gemini-2.5-flash`; Google returned `404 NOT_FOUND` because that model is no
  longer available to new users.
- Trace `e9aba2fb-53b7-4363-a180-f3e5c538ee06` used current
  `gemini-3.5-flash-lite`; Google returned `429 RESOURCE_EXHAUSTED` and directed
  the operator to plan/billing quota details. Tavily fallback completed.
- Trace `c32ff9d8-8133-4ff1-90cf-6f0c3a617a53` tested the last free-only
  candidate, `gemini-2.5-flash-lite`; Google returned `404 NOT_FOUND` because it
  is also unavailable to new users. Tavily fallback completed.
- The host system Python test attempt failed at collection because it lacks
  Google ADK/MCP packages, and the runtime-image attempt lacked pytest. The
  repository `.venv` was then used successfully for the focused suite.

## UNVERIFIED

- A real Google-grounded source is unverified and currently blocked for this
  free-only account. Gemini 2.5 free-grounding models reject new users, while
  Gemini 3.5 Flash-Lite recognizes the key/model but exposes no usable Search
  Grounding quota under the current account plan.
- Google provider attribution, result quality, successful no-Tavily primary
  behavior, and real-browser Google source cards remain unverified.
- No Google browser test was run after the direct backend boundary failed; a
  browser fallback test would not prove Google success and would spend another
  failed reservation.
- The SQLite budget coordinates only the current local/Compose deployment; a
  distributed global rate limit is not implemented.
- General multi-agent scheduling, A2A, durable research sessions, multi-step
  tool loops, and tool-executor agents remain unimplemented.
- Automatic MCP registry refresh/change/remove reconciliation, consequential
  call approval/resume, durable redacted tool audit, and security hardening
  remain planned.

## Next atomic task

Under the user's free-only constraint, leave Google disabled and resume automatic
MCP registry lifecycle management: bounded refresh, add/change/remove/unavailable
reconciliation, stale-descriptor deactivation, health evidence, and a browser
turn that succeeds without manual descriptor sync.

Only reopen Google live verification if an API project has confirmed usable
Search Grounding quota without violating the no-payment requirement. Then set
one key in ignored `.env`, rebuild the backend, require `provider:"google"`
sources with no Tavily request, verify one content-free quota increment, and
repeat through the focused browser acceptance.
