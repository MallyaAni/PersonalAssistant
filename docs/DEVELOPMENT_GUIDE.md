# AniOS Development and Validation Guide

This is the canonical source for local setup, commands, debugging, and validation. Current results belong in [NEXT_SESSION.md](NEXT_SESSION.md), not in this guide.

## Prerequisites

- Python 3.12 or later. The container uses Python 3.12.
- Node.js `^20.19.0` or `>=22.12.0`, as required by the installed Vite 8 line.
- Docker Engine with the `docker compose` subcommand.
- Git for normal development workflows. Git is not required to start the services.

The repository's `requirements.txt` contains runtime Python dependencies. Install the `dev` optional dependency set from `pyproject.toml` for pytest, Ruff, Black, and MyPy.

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
| `LLM_BASE_URL` | `http://127.0.0.1:1234` | LM Studio server root; the chat and embedding adapters append their endpoint paths |
| `LLM_MODEL` | `google/gemma-4-12b` | Use the model key reported by `GET /api/v1/models` |
| `LLM_REASONING_EFFORT` | `none` | LM Studio OpenAI-compatible reasoning control; `none` is required for the current Gemma chat acceptance path |
| `LLM_API_KEY` | none | Optional Bearer token when LM Studio authentication is enabled |
| `LLM_TIMEOUT_SECONDS` | `120` | Provider request timeout in seconds |
| `EMBEDDING_MODEL` | `text-embedding-nomic-embed-text-v1.5` | LM Studio embedding model key |
| `EMBEDDING_MODEL_VERSION` | `nomic-embed-text-v1.5` | Version label persisted with new semantic/tool embeddings |
| `EMBEDDING_DIMENSION` | `768` | Must match the embedding response and pgvector column |
| `MEMORY_SEMANTIC_MAX_COSINE_DISTANCE` | `0.35` | Maximum distance admitted to semantic/tool discovery |
| `MEMORY_SEMANTIC_MAX_RESULTS` | `5` | Hard retrieval result limit |
| `MEMORY_SEMANTIC_MAX_CONTENT_CHARS` | `4000` | Hard semantic prompt-content character budget |
| `CONVERSATION_HISTORY_TURNS` | `10` | Number of newest same-user turns sent to the model; valid range is 0 through 50 |

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
LLM_BASE_URL=http://127.0.0.1:1234
LLM_MODEL=google/gemma-4-12b
LLM_REASONING_EFFORT=none
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_MODEL_VERSION=nomic-embed-text-v1.5
EMBEDDING_DIMENSION=768
MEMORY_SEMANTIC_MAX_COSINE_DISTANCE=0.35
MEMORY_SEMANTIC_MAX_RESULTS=5
MEMORY_SEMANTIC_MAX_CONTENT_CHARS=4000
CONVERSATION_HISTORY_TURNS=10
```

Do not use the Compose credentials or example secret in production. Because process environment variables have precedence, inspect and correct a pre-existing `DEBUG` or `POSTGRES_HOST` variable when local imports behave unexpectedly.

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

Compose starts `db`, `redis`, and `backend`. Re-run `docker compose up --build -d backend` after backend source changes because the container does not bind-mount the repository.

Stop the stack with:

```bash
docker compose down
```

Do not add `--volumes` unless deleting local PostgreSQL data is intentional and approved.

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

In a separate terminal:

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

Vite serves the application at `http://127.0.0.1:5173`. The API client defaults to `http://localhost:8000`; set `VITE_API_URL` before starting Vite when the backend uses another address.

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

The current migration head is `20260716_0007`. Revisions `0004` through `0007` add structured facts, retention/embedding metadata, provenance idempotency, and safe tool-memory tables. Revision `20260716_0002` intentionally refuses to change vector dimensions when legacy semantic rows exist; export or explicitly migrate those vectors instead of deleting or silently truncating them.

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

The successful chat stream is framed as `start`, zero or more `delta`, an optional non-persisted `memory_proposal`, and `done` SSE events. The frontend treats missing start/done events, malformed frames, unexpected content types, and an `error` event as failures. A server-side streaming exception must expose only the generic error message to the client.

For the supported preferred-name workflow, submit a statement such as `My preferred name is Validation Name.` The proposal does not write memory. Approve it through the browser or `POST /api/v1/memory/{user_id}/profile/preferred-name` with the proposed `name`, `source_conversation_id`, and `source_trace_id`; an optional timezone-aware future `expires_at` is accepted. Clear the value and all of its fact versions with `DELETE` on the same path. Verify the fact list/profile before rejection, after approval, after correction, after expiry, and after deletion, then start a new conversation to prove durable recall.

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

`PUT /api/v1/memory/{user_id}/{episodic|semantic}/{memory_id}` corrects an explicit record and re-embeds semantic content. `DELETE /api/v1/memory/{user_id}` removes that user's conversations, profile, facts, episodic/semantic records, and tool descriptors/preferences/outcomes. It is destructive and the UI requires confirmation. Do not expose auth-disabled mode beyond the trusted local development environment.

Tool-memory routes live below `/api/v1/memory/{user_id}/tools`. They accept only canonical safe descriptors, allowlisted approved preferences, and outcome categories; they never accept raw tool arguments or outputs. Discovery is a hint only and cannot authorize or invoke an MCP tool.

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
- remaining blockers and the next atomic task.

Rewrite [NEXT_SESSION.md](NEXT_SESSION.md) with the latest evidence. Append to [CHANGELOG.md](CHANGELOG.md) only when a meaningful change has passed functional validation.
