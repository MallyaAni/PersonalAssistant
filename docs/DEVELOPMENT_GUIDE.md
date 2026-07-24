# AniOS Development and Validation Guide

This is the canonical source for local setup, commands, debugging, and validation. Current results belong in [NEXT_SESSION.md](NEXT_SESSION.md), not in this guide.

## Prerequisites

- Python 3.12 or later. The container uses Python 3.12.
- Node.js `^20.19.0` or `>=22.12.0`, as required by the installed Vite 8 line.
- Docker Engine with the `docker compose` subcommand.
- Git for normal development workflows. Git is not required to start the services.

The repository's `requirements.txt` contains runtime Python dependencies. Install the `dev` optional dependency set from `pyproject.toml` for pytest, Ruff, Black, and MyPy.

`pyproject.toml` pins `[tool.setuptools.packages.find]` to `backend*`. The repository root is a flat layout holding `data/`, `docker/`, `frontend/`, and `migrations/` beside the package, and without that pin setuptools auto-discovery finds multiple top-level packages and refuses to build, which breaks `pip install -e ".[dev]"` for everyone.

## Function comments

Every newly written function or method must have a brief, plain-language comment immediately above it that explains what it accomplishes. This applies to production code, local helpers, API handlers, frontend functions, tests, CLI entry points, and migration functions. Put the comment above decorators so it remains visible before the full declaration, and update the comment whenever the function's purpose changes.

Keep these comments short and purpose-focused. They should help a reader understand why the function exists without restating its signature or narrating each implementation step.

## Architecture diagram maintenance

The source of truth for the high-level system and detailed subsystem diagrams is the Mermaid suite listed in `docs/diagrams/README.md`; each `.mmd` file has a generated `.svg` sharing format. From `frontend/`, render and then verify the complete suite with:

```powershell
npm.cmd run docs:diagram
npm.cmd run docs:diagram:check
```

The commands use the pinned Mermaid CLI and the Chromium installed for Playwright. After a fresh dependency install, install that browser when it is absent:

```powershell
npx.cmd playwright install chromium
```

The renderer maintains the full-system, runtime/deployment, chat, memory, tool-memory, visual-artifact, architecture-maintenance, and frontend diagrams in one pass. The check compares a cross-platform fingerprint of each normalized source, the shared render configuration, and pinned Mermaid CLI version stored in its SVG, then performs a fresh syntax render for every source. It intentionally does not compare generated SVG bytes because renderer-generated identifiers and metadata may vary without changing the diagram.

For every modifying task, use this process:

1. Read the [diagram catalog](diagrams/README.md) and map the changed code to the full-system view and every affected detailed subsystem view.
2. Decide whether components, agents, persistent stores, external dependencies, deployment/trust boundaries, ownership boundaries, or cross-component data flows changed.
3. When they changed, edit each affected authoritative `.mmd` source. If a new architectural subsystem has no detailed view, add its `.mmd`/`.svg` pair and register its basename in the renderer suite and catalog.
4. Run `npm.cmd run docs:diagram` and `npm.cmd run docs:diagram:check` from `frontend/` so the complete checked-in suite remains synchronized.
5. Visually inspect every affected SVG for clipped text, unreadable routing, and incorrect relationships.
6. Report exactly `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`.

Gemma can create a review candidate from the current canonical source and explicitly selected implementation evidence. Run this command from the repository root, use only files needed to prove the requested relationships, and require important implementation labels:

```powershell
python -m backend.cli.generate_architecture_candidate `
  --diagram visual-artifact-subsystem `
  --request "Show the dedicated diagram agent and reviewed candidate workflow." `
  --context backend/agents/diagram.py `
  --context backend/architecture/candidates.py `
  --require-label DiagramAgent `
  --require-label ArchitectureCandidateService `
  --output "$env:TEMP\visual-artifact-subsystem.candidate.mmd"
```

The command reads only bounded explicit text files under approved repository roots, rejects traversal, common secret files, remote model endpoints, unsupported file types, existing outputs, and canonical output paths, then applies passive Mermaid validation, one bounded required-label correction, and the pinned Chromium render. It writes a new `.candidate.mmd` plus `.candidate.svg`; `canonical_updated` remains false. Review the source against the implementation and inspect the SVG before manually editing or promoting canonical source. Required labels prove only that named concepts are present, not that every relationship is correct.

Use this ownership map when selecting affected views:

| Changed area | Detailed view to assess | Also assess the full-system view when |
| --- | --- | --- |
| Deployment, configuration, database/session infrastructure, ports, protocols, or external processes | Runtime and deployment | A major component, external dependency, or deployment boundary changes |
| Chat API, SSE protocol, LangGraph routing, provider calls, or conversation persistence | Chat orchestration | A major component, agent, dependency, or cross-subsystem flow changes |
| Search routing, outbound minimization, research agents, provider/fallback policy, search budgets, or source provenance | Search and research | A provider, agent, external dependency, store, trust boundary, or cross-subsystem flow changes |
| Memory forms, coordinator policy, retrieval, lifecycle, vector search, or memory operations | Memory subsystem | A store, agent, dependency, ownership boundary, or cross-subsystem flow changes |
| Tool metadata, tool retrieval, or the MCP execution boundary | Tool memory | A store, external dependency, trust boundary, or cross-subsystem flow changes |
| Artifact classification, providers, persistence, lifecycle, or rendering | Visual artifacts | A component, model dependency, store, or cross-subsystem flow changes |
| Repository context collection, LLM diagram candidates, candidate validation/rendering, or canonical review | Architecture maintenance | A maintainer process, model dependency, trust boundary, or canonical ownership flow changes |
| Browser state, frontend components, API client behavior, SSE parsing, or client rendering | Frontend | A major component or frontend/backend ownership flow changes |

Internal refactors, bug fixes, styling, tests, and field-level implementation details do not trigger a diagram edit when those architectural relationships remain unchanged. The synchronization check still validates every registered pair, while visual inspection may stay limited to diagrams whose source changed.

## Search routing evaluation

Routing quality is measured against a committed labelled set rather than
asserted, because the numbers quoted in commit messages are otherwise
unverifiable and cannot fail a build:

```bash
python -m backend.cli.evaluate_search_routing --patterns-only   # deterministic, no model
python -m backend.cli.evaluate_search_routing                   # full cascade
```

Both exit non-zero below their floor, so either can gate a pipeline. The floors
follow the mode: patterns alone cannot reach the cascade's recall, and holding
them to it would fail every run. Recall is weighted above specificity on
purpose - a missed search returns a confident stale answer, while an
unnecessary one costs about a second.

Measured on the committed set: patterns alone reach 78.6% recall at 100%
specificity, and the cascade reaches 100% recall at 94.1% specificity, with the
weakness isolated to `implicit_volatile` - volatile questions carrying no
temporal marker, which patterns cannot catch by construction.

Treat those figures as a regression signal, not an absolute score. The set is
curated locally and smaller than a public benchmark; the same cascade scored
91.7% recall and 61.1% specificity against FreshQA's 600 questions. Extend
`backend/search/routing_cases.py` when a real query is routed wrongly, so the
set grows toward the traffic it actually sees.

## Module boundaries

`backend/mcp` owns the protocol, `backend/search` owns web search only,
`backend/artifacts` owns visual artifacts including image retrieval, and
`backend/core/egress` owns screening of anything leaving the machine.
Orchestration that composes them lives in `backend/services`.

`backend/tests/test_architecture_boundaries.py` enforces this: it fails when a
lower layer imports the API or a service, when a module unrelated to web search
appears under `search`, or when a second outbound-screening policy is defined
anywhere. Run it like any other test; a refactor that crosses a boundary will
fail there before review.

## Environment configuration

The backend reads process environment variables and an optional root `.env` file. Copy the tracked `.env.example` to `.env` and replace its local-development secret; `.env` is ignored by Git.

Key settings are:

| Variable | Code default | Local-host guidance |
| --- | --- | --- |
| `SECRET_KEY` | none; required | Set a non-production development value before importing the backend |
| `AUTH_REQUIRED` | `false` | Set `true` outside trusted-local mode; then every chat/memory request needs a signed user token |
| `DEBUG` | `false` | Must be a valid boolean; an existing host `DEBUG` value overrides `.env` |
| `POSTGRES_USER` | `postgres` | Match the Compose database |
| `POSTGRES_PASSWORD` | `password` | Development Compose value only |
| `POSTGRES_DB` | `anios_db` | Match the Compose database |
| `POSTGRES_HOST` | `db` | Use `localhost` when the backend runs on the host |
| `POSTGRES_PORT` | `5432` | Compose host port |
| `DATABASE_POOL_SIZE` | `5` | Persistent async connections retained by the runtime pool |
| `DATABASE_MAX_OVERFLOW` | `5` | Temporary async connections allowed above the pool size |
| `DATABASE_POOL_TIMEOUT_SECONDS` | `30` | Maximum wait for an available pooled connection |
| `DATABASE_USE_NULL_POOL` | `false` | Keep `false` in runtime; tests set it to `true` because pytest creates multiple event loops |
| `LLM_BASE_URL` | `http://127.0.0.1:1234` | LM Studio server root; the chat and embedding adapters append their endpoint paths |
| `LLM_MODEL` | `google/gemma-4-12b` | Use the model key reported by `GET /api/v1/models` |
| `LLM_REASONING_EFFORT` | `none` | LM Studio OpenAI-compatible reasoning control; `none` is required for the current Gemma chat acceptance path |
| `LLM_API_KEY` | none | Optional Bearer token when LM Studio authentication is enabled |
| `LLM_TIMEOUT_SECONDS` | `120` | Provider request timeout in seconds |
| `EMBEDDING_MODEL` | `text-embedding-nomic-embed-text-v1.5` | LM Studio embedding model key |
| `EMBEDDING_MODEL_VERSION` | `nomic-embed-text-v1.5` | Version label persisted with new semantic/tool embeddings |
| `EMBEDDING_DIMENSION` | `768` | Must match the embedding response and pgvector column |
| `EMBEDDING_MAX_CONCURRENCY` | `1` | Shared in-process LM Studio embedding request limit; increase only after provider load validation |
| `MEMORY_SEMANTIC_MAX_COSINE_DISTANCE` | `0.35` | Maximum distance admitted to semantic/tool discovery |
| `MEMORY_SEMANTIC_MAX_RESULTS` | `5` | Hard retrieval result limit |
| `MEMORY_SEMANTIC_MAX_CONTENT_CHARS` | `4000` | Hard semantic prompt-content character budget |
| `CONVERSATION_HISTORY_TURNS` | `10` | Number of newest same-user turns sent to the model; valid range is 0 through 50 |
| `CONVERSATION_SUMMARY_INTERVAL` | `10` | Completed-turn interval for rolling conversation digests; valid range is 2 through 100 |
| `IMAGE_PROVIDER_BASE_URL` | `http://127.0.0.1:8188` | Loopback ComfyUI server root; Compose uses `http://host.docker.internal:8188` |
| `IMAGE_PROVIDER_NAME` | `comfyui` | Provider label persisted with generated artifacts |
| `IMAGE_MODEL` | `hidream_o1_image_dev_fp8_scaled.safetensors` | Exact checkpoint filename exposed by ComfyUI |
| `IMAGE_PROVIDER_TIMEOUT_SECONDS` | `600` | Whole image-job timeout including queue, sampling, and output fetch |
| `IMAGE_PROVIDER_POLL_SECONDS` | `0.5` | Bounded terminal-history polling interval |
| `IMAGE_MAX_CONCURRENCY` | `1` | Shared in-process image-generation gate for the current RTX 5080 |
| `ARTIFACT_STORAGE_ROOT` | `data/artifacts` | Opaque local binary root; ignored by Git and volume-mounted in Compose |
| `IMAGE_MAX_UPLOAD_BYTES` | `10485760` | Maximum accepted uploaded image bytes |
| `IMAGE_MAX_OUTPUT_BYTES` | `41943040` | Maximum accepted generated output bytes |
| `IMAGE_MAX_PIXELS` | `20000000` | Maximum decoded pixels for uploaded/generated images |
| `VISION_MODEL` | `google/gemma-4-12b` | Local VLM model key; independently replaceable from the chat setting |
| `VISION_MAX_TOKENS` | `512` | Maximum grounded analysis output tokens |
| `SEARCH_PROVIDER_NAME` | `tavily` | Set `mcp` to route approved internet searches through the built-in read-only MCP server |
| `SEARCH_API_KEY` | none | Tavily credential inherited only by the internet MCP child when allowlisted |
| `SEARCH_MCP_SERVER_ID` | `internet` | Fixed server identity used after deterministic search routing |
| `SEARCH_MCP_TOOL_NAME` | `search_web` | Fixed read-only MCP search tool name |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | none | Either key enables the isolated Google ADK research worker; never configure both unless they identify the same intended project |
| `GOOGLE_SEARCH_MODEL` | `gemini-3.6-flash` | Request-scoped grounded research model; Gemma remains the local final-answer model |
| `GOOGLE_SEARCH_TIMEOUT_SECONDS` | `30` | Whole Google ADK research deadline before Tavily fallback |
| `GOOGLE_SEARCH_MAX_OUTPUT_TOKENS` | `1024` | Bounded worker answer used only to build attributable result snippets |
| `GOOGLE_SEARCH_DAILY_LIMIT` | `450` | Local Pacific-day safety cap; it does not guarantee provider quota or free access |
| `GOOGLE_SEARCH_QUOTA_DB_PATH` | `data/search/google_search_quota.sqlite3` | SQLite counter containing provider/day/count only; Compose maps this into `searchdata` |
| `MCP_SERVERS_JSON` | `[]` | Operator-owned stdio/HTTP connections, local trust, and optional environment-name allowlists |
| `MCP_LIST_TIMEOUT_SECONDS` | `30` | Bound for live catalogue and tool sessions |
| `TOOL_SEARCH_MAX_RESULTS` | `5` | Maximum live-validated schemas exposed to Gemma per turn |

For host development, a minimal root `.env` is:

```dotenv
SECRET_KEY=local-development-only
AUTH_REQUIRED=false
DEBUG=false
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=anios_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=5
DATABASE_POOL_TIMEOUT_SECONDS=30
DATABASE_USE_NULL_POOL=false
LLM_BASE_URL=http://127.0.0.1:1234
LLM_MODEL=google/gemma-4-12b
LLM_REASONING_EFFORT=none
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_MODEL_VERSION=nomic-embed-text-v1.5
EMBEDDING_DIMENSION=768
EMBEDDING_MAX_CONCURRENCY=1
MEMORY_SEMANTIC_MAX_COSINE_DISTANCE=0.35
MEMORY_SEMANTIC_MAX_RESULTS=5
MEMORY_SEMANTIC_MAX_CONTENT_CHARS=4000
CONVERSATION_HISTORY_TURNS=10
CONVERSATION_SUMMARY_INTERVAL=10
```

Do not use the Compose credentials or example secret in production. Because process environment variables have precedence, inspect and correct a pre-existing `DEBUG` or `POSTGRES_HOST` variable when local imports behave unexpectedly.

FastAPI request handling uses SQLAlchemy's async engine and `asyncpg`. Runtime uses a
bounded async queue pool configured by the four database-pool variables above. The
synchronous psycopg2 engine remains only for Alembic and explicit inspection code.
Pytest selects `NullPool` before importing backend settings so independently created
test event loops never reuse an async connection owned by another loop.

Confirm and, when needed, load both LM Studio models through its local management API:

```powershell
Invoke-RestMethod 'http://127.0.0.1:1234/api/v1/models'
$chatModel = @{ model = 'google/gemma-4-12b' } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:1234/api/v1/models/load' -Method Post -ContentType 'application/json' -Body $chatModel
$embeddingModel = @{ model = 'text-embedding-nomic-embed-text-v1.5' } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:1234/api/v1/models/load' -Method Post -ContentType 'application/json' -Body $embeddingModel
```

The management response must report `status: loaded`; the model catalog alone does not prove an instance is loaded.

### Install and run the free local image provider

The verified Windows host uses ComfyUI 0.28.0, Python 3.14, PyTorch CUDA 13.0, and the official HiDream-O1 Dev FP8 checkpoint. Keep this runtime outside the repository and bound to loopback:

```powershell
$comfyRoot = 'E:\AI\ComfyUI'
git clone https://github.com/Comfy-Org/ComfyUI.git $comfyRoot
C:\Python314\python.exe -m venv "$comfyRoot\.venv"
$env:PIP_CACHE_DIR = 'E:\AI\pip-cache'
& "$comfyRoot\.venv\Scripts\python.exe" -m pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130
& "$comfyRoot\.venv\Scripts\python.exe" -m pip install -r "$comfyRoot\requirements.txt"

$env:HF_HOME = 'E:\AI\huggingface-cache'
$env:HF_XET_CACHE = 'E:\AI\huggingface-xet-cache'
& "$comfyRoot\.venv\Scripts\hf.exe" download Comfy-Org/HiDream-O1-Image checkpoints/hidream_o1_image_dev_fp8_scaled.safetensors --local-dir "$comfyRoot\models"
& "$comfyRoot\.venv\Scripts\hf.exe" download Comfy-Org/gemma-4 text_encoders/gemma4_e4b_it_fp8_scaled.safetensors --local-dir "$comfyRoot\models"
```

Verify the checkpoint SHA-256 is `7cbf53a475e0a13f92f2ec08bcffdb9b9de4305ef3b6f35cdd784d09dcd8d0cc` and the prompt encoder is `bf0b4fa2e41a25684dc9e9b256cd505564f02fed09be3da95ce024e653e2c52b`. Start the runtime without opening a visible helper window:

```powershell
$comfyArgs = @('main.py', '--listen', '127.0.0.1', '--port', '8188', '--disable-auto-launch')
Start-Process -FilePath "$comfyRoot\.venv\Scripts\python.exe" -ArgumentList $comfyArgs -WorkingDirectory $comfyRoot -WindowStyle Hidden -RedirectStandardOutput "$comfyRoot\comfyui.stdout.log" -RedirectStandardError "$comfyRoot\comfyui.stderr.log"
Invoke-RestMethod 'http://127.0.0.1:8188/system_stats'
```

`/system_stats` must report the NVIDIA device and CUDA PyTorch runtime. Reachability alone does not verify generation. ComfyUI can release cached weights through `POST /free` with `{"unload_models":true,"free_memory":true}`; do not unload LM Studio or ComfyUI during an active request.

## Git checkpoints and recovery

Git stores code history; it does not prove that a revision works. Tests and runtime acceptance evidence determine whether a commit is a verified checkpoint.

### Inspect before editing

When Git is available, record this baseline before changing files:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
git diff --stat
git log --oneline --decorate -n 10
```

If the tree is dirty, identify which changes predate the task. Do not stage, discard, hide, or combine those changes with the agent's work. If Git is unavailable, report `UNAVAILABLE` and continue only when the task can be completed safely without Git metadata.

### Create a verified checkpoint

A commit becomes a verified checkpoint only when all of the following are true:

1. its scope is atomic and understood;
2. unrelated changes are excluded;
3. the applicable functional acceptance path passed against that exact tree;
4. relevant regression tests and builds passed or are explicitly recorded as `UNVERIFIED`;
5. the commit SHA and validation evidence are recorded in `NEXT_SESSION.md`.

Creating a commit requires user or workflow authorization. When authorized, stage explicit paths rather than the entire tree:

```bash
git add <path-1> <path-2>
git diff --cached
git commit -m "<atomic verified change>"
git rev-parse HEAD
```

If verification occurs after the commit, record that commit as the code checkpoint in a subsequent handoff update. The later documentation commit does not change which code SHA was functionally tested.

### Recover safely

Before recovery, inspect `git status --short` and determine what would be overwritten. Never assume uncommitted changes are disposable.

With approval, the safest inspection method is a separate worktree at the verified SHA:

```bash
git worktree add <separate-recovery-path> <verified-sha>
```

When a separate worktree is unsuitable and the current tree is safe to leave, create a recovery branch only with approval:

```bash
git switch -c recovery/<name> <verified-sha>
```

For a committed regression on a shared branch, an authorized `git revert <bad-sha>` is generally safer than rewriting history. Re-run the functional acceptance path after any recovery.

Do not automatically run:

```text
git reset --hard
git clean -fd
git restore .
git checkout -- <path>
git push --force
```

These operations can destroy user work or shared history and require explicit approval with a clear impact statement.

## Install dependencies

Backend runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

Backend development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Frontend dependencies:

```bash
cd frontend
npm ci
```

Use `npm install` instead of `npm ci` only when intentionally changing the dependency lockfile.

## Choose one backend mode

Do not run both backend modes on port 8000.

### Mode A: backend in Compose

From the repository root:

```bash
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 backend
```

Compose starts `db`, `redis`, `backend`, and the `frontend` dev container. Re-run `docker compose up --build -d backend` after backend source changes because the backend container does not bind-mount the repository. The `frontend` container **does** bind-mount `./frontend` and hot-reloads, so frontend source changes need no rebuild. The container backend reaches host LM Studio at `http://host.docker.internal:1234`.

Multimodal image retrieval needs local encoder weights, which are not committed.
Download them once into the gitignored `data/` tree:

```bash
mkdir -p data/models/nomic-embed-vision-v1.5
curl -L -o data/models/nomic-embed-vision-v1.5/model.onnx   https://huggingface.co/nomic-ai/nomic-embed-vision-v1.5/resolve/main/onnx/model.onnx
```

Without the file the provider reports `is_enabled() == False`, images are simply
never embedded, and every other path still works. After adding it, backfill any
images stored earlier:

```bash
docker compose exec backend python -m backend.cli.backfill_image_embeddings   --user-id <user> --apply
```

Image retrieval bounds are calibrated, not derived. `VISION_SEARCH_MAX_COSINE_DISTANCE`
is a coarse ceiling and `VISION_SEARCH_MIN_MARGIN` is the discriminator that
separates a real match from the merely nearest image; see the architecture notes
for the measured bands. Re-measure both after the stored library grows
substantially, using a labelled set of visually distinct images plus deliberate
distractor queries that should return nothing.

The routing classifier runs on the configured chat model by default
(`SEARCH_CLASSIFIER_ENABLED`, `SEARCH_CLASSIFIER_MAX_TOKENS`). It is a
`QueryFreshnessClassifier` behind a contract, so pointing it at a smaller,
faster local model is a constructor change rather than a rewrite; a sub-billion
parameter model is ample for a one-word judgement and frees the chat model.
Set `SEARCH_CLASSIFIER_ENABLED=false` to fall back to patterns alone.

MCP servers are configured as a JSON array in `MCP_SERVERS_JSON`. Each entry
gives a `server_id`, an operator-assigned `risk_classification`, and a
transport. A `stdio` server gives `command` and `args` and is launched as a
subprocess, so its runtime (for example Node, for `npx` servers) must be
available wherever the backend runs. `inherit_env` may name only the process
variables that child needs; values stay outside JSON and are not indexed or
shown to Gemma. An `http` server gives a `url` and optional
`headers` and connects to an already-running service, which is the transport to
use for a deployed sibling container or a remote vendor and needs nothing extra
in the image. `forward_context` defaults to `false`. Set it only for an
application-owned local server that requires AniOS user, conversation, and
trace metadata outside its model-visible tool schema; do not enable it for an
arbitrary remote server. Discover and index configured tools with:

```bash
docker compose exec backend python -m backend.cli.sync_mcp_tools --user-id <user>
docker compose exec backend python -m backend.cli.sync_mcp_tools --user-id <user> --list-only
```

`--list-only` reports the live catalogue without writing anything.

To use the built-in free read-only servers and MCP-backed web search, configure:

```dotenv
SEARCH_PROVIDER_NAME=mcp
GOOGLE_API_KEY=
GEMINI_API_KEY=
GOOGLE_SEARCH_MODEL=gemini-3.6-flash
GOOGLE_SEARCH_DAILY_LIMIT=450
MCP_SERVERS_JSON=[{"server_id":"local_utility","command":"python","args":["-m","backend.mcp.servers.local_utility"],"risk_classification":"read_only"},{"server_id":"internet","command":"python","args":["-m","backend.mcp.servers.internet"],"inherit_env":["SEARCH_API_KEY","SEARCH_BASE_URL","SEARCH_MAX_RESULTS","SEARCH_TIMEOUT_SECONDS","SEARCH_MAX_CONTENT_CHARS","SEARCH_MIN_SCORE","SEARCH_DEPTH","GOOGLE_API_KEY","GEMINI_API_KEY","GOOGLE_SEARCH_MODEL","GOOGLE_SEARCH_TIMEOUT_SECONDS","GOOGLE_SEARCH_MAX_OUTPUT_TOKENS","GOOGLE_SEARCH_DAILY_LIMIT","GOOGLE_SEARCH_QUOTA_DB_PATH"],"risk_classification":"read_only"}]
```

The default example also registers the Compose `local-capabilities` sidecar:

```dotenv
MCP_SERVERS_JSON=[{"server_id":"local_visual","transport":"http","url":"http://local-capabilities:8001/mcp","forward_context":true,"risk_classification":"untrusted"}]
```

It exposes `generate_diagram`, `generate_image`, `ask_about_image`, and
`get_artifact` over streamable HTTP while reusing the existing application
services and shared artifact volume. The tool schemas contain no user,
conversation, or trace fields, and results contain public artifact metadata
only. It is intentionally `untrusted`: explicit calls require
`confirmed=true`, and ordinary Gemma chat selection does not receive these
consequential tools until approval/resume UI exists.

Compose passes these settings into the backend. Rebuild it, then sync descriptors
for each chat user before expecting Gemma selection; fixed deterministic internet
routing does not depend on descriptor sync:

```powershell
docker compose up -d --build local-capabilities backend
docker compose exec backend python -m backend.cli.sync_mcp_tools --user-id ani.mallya
```

**Pin server versions.** Fetching a server with `npx -y <package>` resolves to
whatever is published at that moment, which is the rug-pull vector: a server
approved once is not the same server after an update. Pin an exact version in
`args`. The descriptor fingerprint covers the tool description as well as its
schema, so a rewritten description changes the fingerprint and is visible as a
new descriptor rather than silently replacing the approved one.

Web research is opt-in. Set `SEARCH_PROVIDER_NAME=mcp`, configure
`SEARCH_API_KEY` for Tavily fallback, and optionally set either
`GOOGLE_API_KEY` or `GEMINI_API_KEY` for Google-first grounded research.
Without a Google key, current behavior remains Tavily-only. Without either
provider key, search is disabled. Ordinary queries call only the first
successful provider; explicit verify/cross-check wording calls both configured
providers once and merges URL-deduplicated sources.

The Google worker uses a fresh in-memory ADK session for every one-request call
and receives only the normalized, privacy-screened public query. Never add
history, user identity, personal memory, private documents, or image bytes to
that boundary. Google's
[unpaid-service terms](https://ai.google.dev/gemini-api/terms) say submitted
content and responses may be used to improve products and may be human
reviewed. The local default of 450 reservations/day is only a safety ceiling.
Check the current
[Google pricing](https://ai.google.dev/gemini-api/docs/pricing) and the API
project's rate-limit page before enabling the worker: Gemini 3 Search Grounding
may require a billing-enabled project even when Google advertises an included
allowance. AniOS does not enable billing, paid usage, or overages.

After configuring a Google key, rebuild the backend and prove the primary
branch through both the direct and browser paths:

```powershell
docker compose up -d --build backend
$payload = @{
  user_id = 'google_search_validation'
  conversation_id = '89898989-8989-4989-8989-898989898989'
  query = 'Search online for the latest stable Python release and cite the source.'
  metadata = @{}
} | ConvertTo-Json -Compress
Invoke-WebRequest 'http://localhost:8000/api/v1/chat' -Method Post `
  -ContentType 'application/json' -Body $payload -TimeoutSec 180
docker compose logs --since 5m backend
```

The stream must contain `search_started`, `tool_started`,
provider-attributed sources with `"provider":"google"`, answer deltas, and
terminal `done`. Then run the live browser search acceptance with
`RUN_LIVE_TOOL_TESTS=1`; a `200`, health response, or Tavily fallback does not
verify the Google branch.

Compose requires a root `.env` with `SECRET_KEY` set; it is interpolated rather than hardcoded, so a missing value fails the run instead of silently signing tokens with a placeholder. `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are interpolated too and fall back to their local defaults. The remaining container values stay literal in `docker-compose.yml` because `.env` holds host-oriented equivalents (`POSTGRES_HOST=localhost`, loopback `LLM_BASE_URL`) that would break container networking if passed through.

Stop the stack with:

```bash
docker compose down
```

Do not add `--volumes` unless deleting local PostgreSQL data is intentional and approved.

#### Optional: ComfyUI image generation in Compose (`comfyui` profile)

ComfyUI is opt-in because its image build downloads a multi-GB Blackwell-capable CUDA 12.8 PyTorch base and requires an NVIDIA GPU. Point `COMFYUI_HOST_PATH` at your existing ComfyUI install (default `E:/AI/ComfyUI`; it is bind-mounted read-write with its custom nodes and the HiDream checkpoint), then:

```bash
docker compose --profile comfyui up --build -d comfyui
docker compose logs --tail 100 comfyui
```

The first boot also `pip install`s the mounted install's `requirements.txt` (excluding torch) into the container, so it can take a while and may need per-custom-node dependency fixes. Requirements:

- **Free space on the Docker Desktop disk** (the WSL2 image, by default on `C:`) — the CUDA/PyTorch layers are several GB; a full disk causes an `input/output error` build failure and can crash Docker Desktop.
- The `nvidia` container runtime available to Docker (`docker info` lists it) and a working `nvidia-smi` on the host.

When the `comfyui` service is running, the container backend uses `IMAGE_PROVIDER_BASE_URL=http://comfyui:8188` (already set in Compose). When you instead run ComfyUI directly on the host, a container backend uses `http://host.docker.internal:8188` and a host-source backend uses `http://127.0.0.1:8188`.

### Mode B: infrastructure in Compose, backend on the host

Set the local-host environment values above, then run:

```bash
docker compose up -d db redis
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Use port 8001 for a side-by-side diagnostic only when another backend legitimately owns port 8000:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

## Run the frontend

Mode A already runs the `frontend` dev container (bind-mounted, hot-reloading) at `http://127.0.0.1:5173`, so a separate command is not needed there. For Mode B, or to run the console on the host without Docker, use a separate terminal:

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

Do not run the host Vite and the `frontend` container at the same time; they both bind port `5173`. Vite serves the application at `http://127.0.0.1:5173`. The API client defaults to `http://localhost:8000`; set `VITE_API_URL` before starting Vite when the backend uses another address.

Starting Vite successfully is only a startup check. Open the application in a browser and inspect both the Console and Network panels before reporting frontend behavior verified.

## Builds, tests, and static checks

Frontend build:

```bash
cd frontend
npm run build
```

Install the Playwright browser once after frontend dependencies are installed:

```bash
cd frontend
npx playwright install chromium
```

Run deterministic browser chat coverage:

```bash
cd frontend
npm run test:e2e
```

With the backend and a configured LM Studio model running, opt into the live-provider path:

```powershell
$env:ANIOS_E2E_LIVE='1'
npm.cmd run test:e2e:live
```

Backend tests are located under `backend/tests`:

```powershell
$env:POSTGRES_HOST='127.0.0.1'
python -m pytest -p no:cacheprovider backend/tests
```

The `-p no:cacheprovider` option avoids writing `.pytest_cache`; it does not alter test behavior.

When the corresponding development tools are installed, the configured static checks are:

```bash
python -m ruff check backend migrations debug_test.py
python -m black --check backend migrations debug_test.py
python -m mypy backend
```

Do not substitute `pytest tests/`; there is no root `tests/` directory.

## Test strategy

Tests must prove behavior at the lowest useful layer and must collectively cover the user-visible goal.

### Backend tests

- Unit tests isolate service decisions and error handling.
- API integration tests validate request schemas, dependency assembly, response contracts, streaming termination, and intentional error responses.
- Persistence integration tests inspect actual records rather than mocking the repository under test.
- A deterministic fake LLM may validate orchestration, streaming, and failure handling, but it cannot verify live-provider connectivity.

### Frontend tests

- Component tests should cover rendering, input, loading, success, empty, streaming, and failure states.
- Browser end-to-end tests must open the application, perform the real interaction, observe required network traffic, assert rendered results, and fail on page exceptions or blocking console errors.
- When persistence is part of the goal, browser tests must reload or navigate and confirm that expected state is restored.
- For assistant formatting changes, stream a controlled CommonMark fixture and require semantic heading, emphasis, and list elements rather than visible marker characters. Include raw HTML in the fixture and prove that it neither creates an element nor executes an event handler. Keep user-message rendering literal.
- Endpoint reachability, static HTML, module transformation, API-only tests, and DOM snapshots without interaction are insufficient proof of UI functionality.

The repository has Playwright `test:e2e` and `test:e2e:live` scripts. The deterministic suite intercepts the chat boundary for repeatability; the live suite is skipped unless `ANIOS_E2E_LIVE=1` and must contact the configured backend/provider. Passing deterministic tests does not prove live-model connectivity.

### Deterministic and live LLM validation

Keep these checks separate:

1. Deterministic CI tests use a controlled provider to prove application logic, UI behavior, streaming, and error handling.
2. An explicit live acceptance check proves the configured provider was contacted and returned non-placeholder output.

Passing the deterministic suite does not verify a live model. Passing a live provider request does not replace deterministic regression coverage.

## Database and migrations

Alembic is configured at the repository root:

```bash
alembic upgrade head
alembic current
```

A successful Alembic command does not prove application tables exist. Verify the actual schema:

```bash
docker compose exec -T db psql -U postgres -d anios_db -c "\dt"
```

The current migration head is `20260718_0011`. Revision `0011` adds generated/uploaded artifact kinds plus opaque storage key, byte size, SHA-256, width, and height. Revision `0010` adds user-scoped visual artifacts with pending/ready/failed lifecycle, conversation/trace provenance, provider/model metadata, editable source, and indexes. Revision `0009` adds source-conversation provenance to procedures plus approval and source-request provenance to knowledge documents. Revision `0008` adds semantic-cache, working-memory, procedure, entity/relation, knowledge-document/chunk, and conversation-summary tables plus pgvector HNSW cosine indexes for vector-bearing memory. Revisions `0004` through `0007` add structured facts, retention/embedding metadata, provenance idempotency, and safe tool-memory tables. Revision `20260716_0002` intentionally refuses to change vector dimensions when legacy semantic rows exist; export or explicitly migrate those vectors instead of deleting or silently truncating them.

Create or reset migrations only as part of an explicitly approved schema task. Treat deletion of the `pgdata` volume as destructive.

## Runtime and functional validation

Use the narrowest checks that prove the requested goal. Record each result as `VERIFIED`, `FAILED`, or `UNVERIFIED`.

### 1. Startup evidence

```bash
docker compose ps
docker compose logs --tail 100 backend
```

For host processes, retain the terminal output. Confirm there are no startup exceptions or restart loops.

### 2. Availability evidence

```bash
curl -i http://localhost:8000/health
curl -i http://localhost:8000/api/v1/
```

On PowerShell:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health
```

Availability checks prove routing only. They do not prove chat, streaming, model use, or persistence.

### 3. Functional API evidence

Exercise the actual chat request:

```bash
curl -i -N -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"validation_user","conversation_id":"11111111-1111-4111-8111-111111111111","query":"Reply with: validation ok","metadata":{}}'
```

The repository also contains a diagnostic client:

```bash
python debug_test.py
```

To validate auth-enabled mode, set `AUTH_REQUIRED=true`, issue a short-lived token, and expose the same token to the frontend process:

```powershell
$token = python -m backend.cli.issue_token --user dev_user_001 --ttl-seconds 3600
$env:VITE_AUTH_TOKEN = $token
```

Send `Authorization: Bearer <token>` on direct API requests. The token subject must exactly match the body/path `user_id`; never commit or log a real token.

Validate all applicable acceptance properties:

- the request reaches the intended handler and service;
- status, headers, and body match the contract;
- response content achieves the requested behavior rather than returning a placeholder;
- a stream emits and terminates cleanly;
- logs contain no server exception;
- expected records or other side effects exist;
- invalid input produces an intentional error.

The successful chat stream is framed as `start`, zero or more `delta`, an optional non-persisted `memory_proposal`, optional `artifact_started`/`artifact_ready`/`artifact_error`, and `done` SSE events. The frontend treats missing start/done events, malformed frames, unexpected content types, and an `error` event as failures. A server-side streaming exception must expose only the generic error message to the client.

For a diagram acceptance, change the query to an explicit request such as `Create a flowchart showing DiagramStart to ValidateArtifact to DiagramComplete.` Verify `artifact_started` precedes either `artifact_ready` or `artifact_error`, `done` terminates the stream, and the artifact list reflects the terminal lifecycle:

```text
GET /api/v1/artifacts/{user_id}/conversations/{conversation_id}
GET /api/v1/artifacts/{user_id}
DELETE /api/v1/artifacts/{user_id}/{artifact_id}
```

Then submit a unique diagram request through Chromium. Require a rendered SVG, editable Mermaid source, visible generation failure behavior, enabled/cleared composer after termination, retention while switching views, the expected chat network response, and no blocking Console or page errors. Reload the page and require `GET /api/v1/conversations/{user_id}/{conversation_id}` to restore the persisted question, response, rendered diagram, and editable source without a visible restoration failure. Open Visual Artifacts, verify the owned history request, download both `.mmd` and `.svg`, delete the record, and require the empty state.

For disconnect recovery, open the chat stream with a client that can stop reading immediately after the `artifact_started` data frame. Close the response, then list the scoped artifacts and require the new record to be `failed` with `error_code=cancelled`, no source, and no remaining `pending` record. Inspect logs for the same trace's `cancelled` lifecycle entry and delete the scoped validation record.

For raster generation, keep both LM Studio and ComfyUI running and submit an allowlisted HiDream training resolution. The body is piped to `curl.exe` because Windows PowerShell 5 can mishandle large or completed `Invoke-WebRequest` responses:

```powershell
$imageBody = @{
  user_id = 'image_validation'
  conversation_id = '33333333-3333-4333-8333-333333333333'
  prompt = 'A cobalt glass apple on a white pedestal, studio lighting, no text'
  width = 2048
  height = 2048
  seed = 7182026
} | ConvertTo-Json -Compress
$imageBody | curl.exe -sS -D - -X POST 'http://127.0.0.1:8000/api/v1/images/generate' -H 'Content-Type: application/json' --data-binary '@-'
```

Require HTTP 201, `kind=generated_image`, terminal `status=ready`, `content_available=true`, provider/model/job metadata, `metadata.generation_prompt`, dimensions, byte size, and SHA-256. Fetch `GET /api/v1/artifacts/{user_id}/{artifact_id}/content`, verify its decoded image and hash, require another user to receive 404, and delete through `DELETE /api/v1/artifacts/{user_id}/{artifact_id}`. Confirm both the exact file and row are gone. Unsupported resolutions must return 422 before a provider request.

For real image understanding, upload a validated image to Gemma:

```powershell
curl.exe -sS -D - -X POST 'http://127.0.0.1:8000/api/v1/vision/analyze' `
  -F 'user_id=vision_validation' `
  -F 'conversation_id=44444444-4444-4444-8444-444444444444' `
  -F 'prompt=State the main subject, dominant color, material, and setting.' `
  -F 'image=@E:\AI\validation.png;type=image/png'
```

Require HTTP 201, `kind=uploaded_image`, ready binary integrity metadata, `analysis_status=ready`, the configured vision model, and grounded content unique to the image. Fake bytes, animation, MIME mismatch, excess size, or excess pixels must return a visible 413/422 and create no artifact. A provider failure returns 502 with the preserved upload artifact ID and `analysis_status=failed`.

For browser acceptance, also submit `create an image of ...` while Chat is selected. Require exactly one `/images/generate` request and the selected mode to change to Create image. Without changing that mode manually, ask a historical question such as `what car did we create an image of?`; require `/chat`, no second generation request, a grounded answer, terminal `done`, and cleared loading/input. Then explicitly ask to search the internet for that image, require image recall before the visible internet MCP lifecycle, and require source cards only when the provider returned non-empty results. Inspect Network and Console throughout. The Memory screen must not fetch the full export before a map-card click; selecting Semantic cache must return the owned export and display a bounded detail region without embedding vectors.

Use Create image and Analyze image for the remaining visual checks. Require visible progress, a terminal ready image and grounded analysis, enabled/cleared controls, navigation and full-reload restoration, artifact-history rendering, download/deletion, visible 413/422/502/503 errors, and successful retry. Run the reusable live provider checks explicitly:

```powershell
cd frontend
npx.cmd playwright test --grep "@live visual generation"
npx.cmd playwright test --grep "@live cancelled image"
npx.cmd playwright test --grep "image conversation routes through generation"
```

The cancellation check waits until the owned row is `pending`, presses Cancel, then requires `failed` with `error_code=cancelled`, a matching ComfyUI `/interrupt`, no backend exception, cleared UI loading, and scoped cleanup.

For the supported preferred-name workflow, submit a statement such as `My preferred name is Validation Name.` For response style, use a narrow statement such as `Please be concise.` Neither proposal writes memory. Approve through the browser; preferred names use `/profile/preferred-name`, while response style uses the generic `/facts` endpoint. Verify rejection-without-write, approval, correction/supersession, projection, expiry, and deletion.

To validate conversation history, send two requests with the same `user_id` and `conversation_id`, put a unique fact only in the first query, and require the second response to reproduce it. Confirm the two rows share that conversation ID, the traces differ per request, and the second prompt itself does not contain the expected fact.

Personal-memory examples for the local development user:

```powershell
$profile = @{
  name = 'Ani'
  preferences = @{ response_style = 'concise' }
} | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri 'http://localhost:8000/api/v1/memory/dev_user_001/profile' -ContentType 'application/json' -Body $profile

$memory = @{
  content = 'The user prefers jasmine tea.'
  metadata = @{ source = 'manual' }
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/memory/dev_user_001/semantic' -ContentType 'application/json' -Body $memory

Invoke-RestMethod 'http://localhost:8000/api/v1/memory/dev_user_001'
Invoke-RestMethod 'http://localhost:8000/api/v1/memory/dev_user_001/search?query=preferred%20tea&top_k=5'
Invoke-RestMethod 'http://localhost:8000/api/v1/memory/dev_user_001/export'
```

`POST /api/v1/memory/{user_id}/facts` explicitly approves a structured fact. Repeating a normalized value deduplicates; a contradictory value creates a superseding version. `PUT /facts/{fact_id}` corrects, `DELETE /facts/{fact_id}` removes one version, and `DELETE /facts/key/{fact_key}` removes the key history and supported profile projection. `PUT /api/v1/memory/{user_id}/{episodic|semantic}/{memory_id}` corrects an explicit record and re-embeds semantic content. `GET /api/v1/memory/{user_id}/agent` returns typed-store counts. `DELETE /api/v1/memory/{user_id}` removes that user's conversations and all personal, tool, and agent-memory records. It is destructive and the UI requires confirmation.

Tool-memory routes live below `/api/v1/memory/{user_id}/tools`. They accept only canonical safe descriptors, allowlisted approved preferences, and outcome categories; they never accept raw tool arguments or outputs. Discovery is a hint only. Chat re-resolves shortlisted schemas, lets Gemma return at most one native tool call, and then sends the application-owned plan through the same live contract, risk, argument, and privacy gates as `POST /api/v1/tools/{user_id}/call`.

Run deterministic and real-browser MCP acceptance with:

```powershell
cd frontend
npx.cmd playwright test --grep "MCP tool|MCP refusal"
$env:RUN_LIVE_TOOL_TESTS='1'
$env:ANIOS_LIVE_TOOL_USER='live_tool_browser_user'
npx.cmd playwright test --grep "@live uses a Gemma-selected MCP tool"
```

The live user must have fresh descriptors from `sync_mcp_tools`. Require the
transient and terminal tool states, HTTP 200 SSE responses, terminal `done`,
source cards for internet search, cleared Thinking/composer state, and no page
or blocking Console errors.

For direct local-visual MCP acceptance, use a disposable user and a real UUID
conversation, then call the same public invocation boundary:

```powershell
$conversationId = [guid]::NewGuid()
$body = @{
  server_id = 'local_visual'
  tool_name = 'generate_diagram'
  arguments = @{
    prompt = 'Create a flowchart from Agent to MCP Facade to Artifact Service.'
  }
  conversation_id = $conversationId
  confirmed = $true
} | ConvertTo-Json -Depth 5
Invoke-RestMethod `
  -Method Post `
  -Uri 'http://localhost:8000/api/v1/tools/visual_validation/call' `
  -ContentType 'application/json' `
  -Body $body
```

Require a non-error result containing a terminal ready artifact handle, then
read the owned artifact through `/api/v1/artifacts/visual_validation`. Repeat
with `generate_image`, fetch the private content, and use its artifact ID with
`ask_about_image` and `get_artifact`. Confirm that omitting `confirmed=true`
returns HTTP 409, no MCP result contains bytes or `_storage_key`, backend and
sidecar logs contain no credential or raw image content, and scoped cleanup
removes the disposable artifacts.

Agent-memory route groups are:

- `/agent/cache` for expiring cached coordinator plans;
- `/agent/working` for expiring conversation-scoped session state;
- `/agent/procedures` for explicitly approved versioned workflows;
- `/agent/entities` and `/agent/entity-relations` for approved entity memory;
- `/agent/knowledge` for plain-text ingestion, deterministic chunking, semantic search, and document deletion;
- `/agent/summaries` for conversation digests.
- `/agent/retention/purge` for scoped dry-run/apply expiry cleanup;
- `/agent/reembedding` for stale-vector inventory and scoped batch migration;
- `/agent/operations` for counts, backlog, vector, invariant, and DB state;
- `/agent/operations/metrics` for Prometheus-compatible non-content gauges.

Operational commands default to safe/read-only behavior where applicable:

```powershell
python -m backend.cli.purge_memory --user-id ani.mallya
python -m backend.cli.purge_memory --user-id ani.mallya --apply
python -m backend.cli.reembed_memory --user-id ani.mallya
python -m backend.cli.reembed_memory --user-id ani.mallya --apply --batch-size 50
python -m backend.cli.migrate_vector_dimension --target-dimension 768 --target-model text-embedding-nomic-embed-text-v1.5 --target-version nomic-embed-text-v1.5
python -m backend.cli.check_memory_operations --user-id ani.mallya --strict
python -m backend.cli.run_memory_maintenance --user-id ani.mallya --strict
python -m backend.cli.run_memory_maintenance --all-users --strict --interval-seconds 3600
python -m backend.cli.soak_memory --duration-seconds 60 --concurrency 4 --chat-every 20
python -m backend.cli.evaluate_memory_retrieval --user-id ani.mallya --query 'unique query' --expected-content 'expected text'
```

Apply across all users requires the explicit `--all-users` flag. Re-embedding is resumable by stale metadata and rejects provider dimensions other than the configured 768 before committing a batch. The maintenance command applies retention, optionally re-embeds with `--reembed`, performs final health inspection, emits one non-content JSON event per cycle, survives transient failures in interval mode, and returns monitoring-friendly exit codes in one-shot mode. `docker compose --profile maintenance up` enables the opt-in hourly runner. Deployments can scrape the metrics route and alert on `anios_memory_healthy == 0`; delivery to a particular external alert service remains deployment configuration.

The soak command uses an isolated user, mixes real SSE chat with public working-memory reads/writes and operations inspection, checks every stream for `delta` plus terminal `done`, reports latency/failures as JSON, and deletes its scoped data unless `--keep-data` is supplied.

### Change vector dimensions

Dimension migration is a maintenance-window operation across all seven vector-bearing stores. First run the command above without `--apply`; it inventories the declared live and resumable shadow dimensions and calls no embedding provider. To migrate:

1. Load and probe the target embedding model in LM Studio.
2. Stop every chat, memory, maintenance, and ingestion writer.
3. Run the migration command with the new model, version, and dimension plus `--apply --confirm-offline`.
4. If embedding fails, leave the shadow columns in place, correct the provider, and repeat the same command; committed batches resume while the old `embedding` columns remain authoritative.
5. After a successful atomic switch, set `EMBEDDING_MODEL`, `EMBEDDING_MODEL_VERSION`, and `EMBEDDING_DIMENSION` to the target values and restart the application.
6. Run Alembic drift, operations inventory, retrieval evaluation, direct chat, and browser acceptance before reopening writers.

The final switch locks all affected tables and, in one PostgreSQL transaction, verifies every shadow value, replaces the old columns, updates vector metadata, and recreates every HNSW cosine index. Do not use `--confirm-offline` while writers are still active.

Normal chat manages cache, working state, and periodic rolling summaries automatically. Durable procedures, entities, knowledge, persona facts, and tool preferences require explicit user/API action; the model does not receive arbitrary store or SQL access.

Chat offers approval cards for these explicit forms:

- `My preferred name is Ani.` or `Call me Ani.`
- `Please be concise.` or `I prefer responses to be detailed.`
- `Remember that Avery Chen is my dentist.`
- `Remember this workflow: Morning launch. Steps: Open dashboard; review alerts.`
- `Remember this reference: Studio access | The marker is violet seven.`

Nothing durable is written until the user presses the proposal's approval button. `Not now` dismisses it without a memory API write. The entity, procedure, and knowledge approvals retain the source conversation and trace identifiers. This explicit grammar is intentional: AniOS does not silently extract arbitrary model-inferred facts.

### 4. Frontend evidence

- Load the application in a browser.
- Confirm the Console has no blocking exception.
- Send a message through the composer.
- Inspect the chat request and streamed response in Network tools.
- Confirm the UI renders the complete expected response and exposes failures to the user.
- Refresh or navigate as required by the task to validate persistence or state restoration.

An HTTP 200 for `/` or a successfully transformed JavaScript module does not prove the rendered application works.

### 5. Persistence evidence

When a task claims persistence, inspect the database after the functional request. Confirm the correct table, user, content, and record count. Do not infer persistence from a repository method being present in source.

### 6. Regression evidence

Run the relevant build, tests, and a representative existing workflow. Report skipped checks as `UNVERIFIED`, including the reason.

## Debugging workflow

1. Reproduce the failure with the smallest relevant command.
2. Capture the response, logs, browser errors, process state, and persisted data.
3. Identify the failing boundary: frontend, API validation, dependency assembly, service, database, LLM, or infrastructure.
4. Form one evidence-backed hypothesis.
5. Make one targeted change.
6. Repeat the original functional check and relevant regression checks.

Do not make several speculative fixes at once. If three targeted attempts fail, summarize the evidence and hypotheses before continuing.

## Completion report

Every implementation handoff should state:

- objective and acceptance criteria;
- files created, modified, and deleted;
- `VERIFIED`, `FAILED`, and `UNVERIFIED` checks;
- functional evidence, not only startup evidence;
- documentation updated;
- `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`;
- remaining blockers and the next atomic task.

Rewrite [NEXT_SESSION.md](NEXT_SESSION.md) with the latest evidence. Append to [CHANGELOG.md](CHANGELOG.md) only when a meaningful change has passed functional validation.
