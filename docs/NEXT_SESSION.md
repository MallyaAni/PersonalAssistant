# Next Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-07-23, America/New_York

## Current milestone

**Milestone 5: tools and specialized agents — `IN PROGRESS`; Gemma-selected
MCP execution, MCP internet search, visible browser tool lifecycle, and the
local visual FastMCP capability facade are `VERIFIED`.**

The referenced-image conversation path is also `VERIFIED`: Chat can select
image generation from natural language, historical questions return to chat,
explicit web comparison uses screened image provenance, and memory-map cards
open owned details on demand.

AniOS now exposes its existing diagram, image-generation, image-followup, and
artifact-status services through a dedicated `local-capabilities` FastMCP
sidecar. The browser REST/SSE paths remain unchanged. Agent-facing tools return
artifact handles and public metadata rather than image bytes.

Application-owned user, conversation, and trace values are not part of the
model-visible tool schemas. `MCPInvocationService` forwards them as MCP request
metadata only when a configured server opts into `forward_context`; the local
visual server validates those values before service work. It is classified
`untrusted`, so explicit calls require confirmation and ordinary autonomous
chat selection does not receive these consequential tools.

## Git and runtime state

- Starting state for the referenced-image task: branch `main`, `HEAD`
  `4739fcd7a3d3694aa6b61c521de55907138ed3da`, already dirty with the preceding
  visual FastMCP work. Those changes were preserved. Git is at
  `C:\Program Files\Git\cmd\git.exe`, not on this shell's `PATH`.
- Final state: the implementation, tests, documentation, Mermaid sources, SVGs,
  and published architecture page are modified and unstaged. No commit, tag,
  branch, stash, reset, restore, checkout, push, or recovery operation was
  created.
- Final exercised backend image:
  `sha256:abd46fc192d0537861ec6e57f426b5ac1f247ac4edb3334e80fffd9b0e131601`,
  started `2026-07-23T04:35:23.719429205Z`.
- Final exercised frontend image:
  `sha256:6c49298b258f4377d7539b12616d3560ea3141ac2ea5fd433605fa5897a3b409`,
  started `2026-07-23T04:16:17.325112417Z`.
- Final exercised local-capabilities image:
  `sha256:51137f0350ed75cc71c57d70a90c5a2ee3ffcf06a9ef1c00ecc98ea1d787f50a`,
  started `2026-07-23T04:35:23.012790009Z`.
- Docker `backend`, `local-capabilities`, `frontend`, `db`, and `redis` are
  running. The sidecar listens on host port 8001 and the backend reaches it at
  `http://local-capabilities:8001/mcp`.
- LM Studio served `google/gemma-4-12b` at host port 1234. Host ComfyUI served
  `hidream_o1_image_dev_fp8_scaled.safetensors` at port 8188.
- Root `.env` (ignored) and `.env.example` register `local_utility`,
  `internet`, and `local_visual`; only `local_visual` enables
  `forward_context`.
- No database schema change was introduced.

## VERIFIED

### Referenced-image conversation and memory-map UX

- Chat-mode text `create an image of a car for me` now deterministically selects
  the existing image API instead of sending Gemma an unsupported
  `dalle.text2im`-style action request. The selected composer mode changes to
  Create image so the UI matches the action.
- A historical question such as `what car did we create an image of?` leaves
  Create image mode, uses `/api/v1/chat`, and does not issue another generation
  request.
- Ready generated artifacts retain the bounded generation prompt. Historical
  and referential image routing retrieves that artifact first and supplies the
  prompt or stored analysis as untrusted answer context.
- Explicit web comparison about a recalled image appends one bounded
  description to the normalized subject, privacy-screens the combined text,
  and invokes `internet/search_web`; it never sends image bytes. A credential
  in image provenance blocks the provider call in deterministic coverage.
- Direct live generation created ready artifact
  `bb0ffa43-dd8e-412d-96db-796f0f840ffa` with exact prompt provenance.
  Direct followup trace `dbac0f10-e835-4fbe-917d-4e8127e61b8b` emitted
  `image_matches`, answered with the cobalt sports-car prompt, and terminated.
  Direct search trace `1e486d17-812b-4471-b56f-45fde5254cf6` emitted the image
  match, sanitized search query, internet MCP lifecycle, three sources, a
  qualified comparison answer, and `done`.
- Focused live Chromium passed in 59.6 seconds against rebuilt containers. It
  generated exactly one real ComfyUI image from Chat, showed Create image,
  routed the historical followup through chat, displayed the internet MCP
  lifecycle, received terminal `done`, cleared loading/input, and opened
  Semantic-cache details through the real owned export endpoint. Console, page,
  and required-network error collections were empty.
- Every Agent memory map card is now an accessible detail action. Durable
  records load only on click through the existing owned export boundary,
  display at most 50 readable records, and omit embeddings and storage keys.
- Calls through the shared `LMStudioLLM` client are serialized. A concurrent
  regression test proves two calls never overlap at the provider boundary.
- The final rebuilt backend repeated the documented chat payload under trace
  `778067bc-81a4-4d9a-8254-aa76faae92be`: HTTP 200
  `text/event-stream`, `image_matches`, grounded cobalt-car deltas, `done`, no
  error event, and a completed graph log with no exception.
- Scoped cleanup deleted the direct validation artifact/file and all
  `accept_image_context_20260723` plus `live_image_chat_*` conversation rows;
  direct PostgreSQL counts returned zero artifacts and zero conversations.

### Visual FastMCP boundary

- `backend/capabilities/visual_mcp.py` exposes `generate_diagram`,
  `generate_image`, `ask_about_image`, and `get_artifact` over streamable HTTP.
  It composes the same application services used by the browser APIs and opens
  one async database session per call.
- Live registry synchronization reported three healthy servers, six indexed
  tools, four `local_visual` tools, and no quarantined descriptor. A final
  list-only probe against the rebuilt images reported the same four visual
  schemas.
- Schema tests prove Gemma cannot supply user, conversation, or trace IDs.
  Result tests prove private `_storage_key` and binary content are excluded and
  long analysis remains bounded valid JSON.
- Context-forwarding tests prove request metadata reaches an opted-in server
  and is withheld from servers that do not opt in.
- An explicit unconfirmed visual call returned HTTP 409
  `confirmation_required`; no MCP request reached the tool.

### Direct live API, providers, persistence, and logs

- `POST /api/v1/tools/visual_mcp_probe/call` with a real conversation UUID and
  `confirmed=true` generated diagram artifact
  `5228aff4-f316-4307-b775-ed4381647292`. It was terminal `ready`, owned by the
  disposable user/conversation/trace, used Gemma, and persisted valid Mermaid
  from Start through MCP Facade, Existing Diagram Service, and Persisted
  Artifact.
- The same route generated image artifact
  `a3928ff4-318f-494b-a050-10f2bbae7822` through ComfyUI: terminal `ready`,
  PNG, 2048×2048, 3,198,500 bytes, SHA-256
  `94fa3f0ccc94d8e355c0c2f153ee36e9cc119f3fd60f1fa5654c2fff9e444e09`.
  The private content route returned the same byte count with
  `Cache-Control: private, no-store`.
- `ask_about_image` returned a grounded Gemma description of the generated
  bridge diagram; `get_artifact` returned its public handle without bytes or a
  storage key. The final rebuilt images repeated `get_artifact` successfully.
- Backend and sidecar logs show MCP protocol negotiation, live `tools/list`,
  each application-owned invocation, LM Studio/ComfyUI HTTP 200 responses, and
  no corresponding application exception or leaked image content.
- Scoped cleanup deleted both validation artifacts, their binary file, and all
  six disposable descriptors. API and direct PostgreSQL checks both returned
  zero remaining rows for `visual_mcp_probe`.

### Real browser and automated validation

- Focused live Chromium passed in 37.8 seconds: it created a real image, showed
  progress, rendered the private image, retained it across view navigation and
  reload, downloaded those bytes into the upload control, received a real
  Gemma analysis, rendered its Markdown, cleared loading, re-enabled/cleared
  the composer, deleted both artifacts, and observed no Console error or page
  exception.
- The browser test is now self-contained: it analyzes the image created in the
  first half instead of relying on deleted machine path
  `E:\AI\anios-direct-ui.png`.
- Backend: `353 passed`; only Starlette's upstream TestClient/httpx deprecation
  warning remains.
- Python quality: Ruff passed; Black reports all 158 files unchanged; strict
  MyPy reports no issues in 111 source files.
- Frontend: TypeScript/Vite production build passed. The Mermaid chunk-size
  message remains a non-blocking advisory.
- Deterministic Chromium: all 30 non-live workflows passed.
- All nine canonical Mermaid/SVG pairs and `docs/architecture.html` are
  synchronized. The full-system, runtime/deployment, tool-memory, and
  visual-artifact views were visually inspected; an SVG bounds check found
  zero overflows among 337 labels.

## FAILED evidence encountered and resolved

- The first live referenced-image browser run reached image generation,
  followup, internet MCP success, and sources, but a concurrent backend Gemma
  request caused LM Studio to emit `terminated` after the first answer token.
  Playwright network evidence proved there was no duplicate browser submit.
  Serializing the shared local chat client fixed the provider boundary.
- The next live run completed both graphs and cleared the composer, but Tavily
  returned a valid empty source set for a synthetic test description. The test
  now requires the search/tool lifecycle and terminal `done`, and requires
  source cards only when the provider returns non-empty sources. The unchanged
  full live path then passed.
- The first host test command used global Python 3.14, which lacked the MCP
  package and had a conflicting global `DEBUG=release`. Re-running in the
  documented project `.venv` produced the verified results.
- The first live browser attempt completed generation/rendering but failed at a
  deleted hardcoded upload file. Reusing the generated image fixed that
  acceptance boundary.
- The second live browser attempt completed real generation and analysis but
  searched for raw Markdown source as one text node. Verifying the rendered
  semantic analysis fixed the stale assertion; the third run passed.
- The first cleanup command interpolated the PowerShell user variable
  incorrectly and deleted no artifact. Re-resolving the exact
  `visual_mcp_probe` IDs and deleting only those records succeeded.
- The three-failed-hypothesis threshold was not reached for any product
  boundary.

## FAILED / open repository evidence

- `alembic current` reports `20260721_0012 (head)`, but `alembic check` still
  detects proposed removal of `ix_visual_artifacts_embedding_hnsw`. This task
  did not change schema/model metadata. Do not claim migration drift is clean
  until that pre-existing index mismatch is resolved.

## UNVERIFIED / deliberately deferred

- Browser chat still uses its explicit diagram REST/SSE branch and image
  composer REST APIs. It does not yet propose, approve, resume, or render a
  consequential `local_visual` MCP call selected by Gemma.
- MCP descriptor synchronization remains a manual per-user CLI operation.
  Automatic startup/on-demand refresh, add/change/remove reconciliation,
  unavailable-server health, and stale-descriptor deactivation are not
  implemented.
- Chat selects at most one autonomous read-only/trusted tool per turn.
  Multi-step tool loops, parallel tools, delegated subagents, general
  LangGraph multi-agent orchestration, and A2A collaboration are not
  implemented.
- Tool execution has trace-correlated logs and visible current-turn status, but
  no durable redacted audit record or restored historical lifecycle badges.
- Sustained concurrent MCP/tool/model load, sidecar crash recovery,
  retry/backoff, distributed workers, and DGX Spark profiles are unbenchmarked.
- Service-to-service authentication, network isolation, per-server user
  credential scopes, and broader MCP hardening remain deferred to the final
  security subsystem.

## Next atomic task

Implement automatic MCP registry lifecycle management without adding
subagents:

1. Refresh configured server catalogues on first use or startup under a bounded
   timeout.
2. Compare live identities, descriptions, and schemas with user-scoped
   descriptors; index new/changed tools and deactivate removed/unavailable
   tools.
3. Prevent stale descriptors from selection while preserving pre-invocation
   live revalidation.
4. Expose bounded registry health and last-refresh evidence without secrets.
5. Verify add/change/remove/unavailable behavior through backend tests and a
   real browser turn that succeeds without a manual sync command.

After that, implement the visible proposal/approval/resume contract for
consequential MCP calls. Only then should `local_visual` be eligible for Gemma
selection in chat; do not weaken its trust classification as a shortcut.
