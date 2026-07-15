# AniOS Development and Validation Guide

This is the canonical source for local setup, commands, debugging, and validation. Current results belong in [NEXT_SESSION.md](NEXT_SESSION.md), not in this guide.

## Prerequisites

- Python 3.12 or later. The container uses Python 3.12.
- Node.js `^20.19.0` or `>=22.12.0`, as required by the installed Vite 8 line.
- Docker Engine with the `docker compose` subcommand.
- Git for normal development workflows. Git is not required to start the services.

The repository's `requirements.txt` contains runtime Python dependencies. It does not declare all development tools used by CI, including pytest, Ruff, Black, and MyPy. Do not assume those commands are available until the tools are installed in the active environment.

## Environment configuration

The backend reads process environment variables and an optional root `.env` file. The repository does not currently contain `.env.example`.

Key settings are:

| Variable | Code default | Local-host guidance |
| --- | --- | --- |
| `SECRET_KEY` | none; required | Set a non-production development value before importing the backend |
| `DEBUG` | `false` | Must be a valid boolean; an existing host `DEBUG` value overrides `.env` |
| `POSTGRES_USER` | `postgres` | Match the Compose database |
| `POSTGRES_PASSWORD` | `password` | Development Compose value only |
| `POSTGRES_DB` | `anios_db` | Match the Compose database |
| `POSTGRES_HOST` | `db` | Use `localhost` when the backend runs on the host |
| `POSTGRES_PORT` | `5432` | Compose host port |
| `REDIS_HOST` | `redis` | Use `localhost` when the backend runs on the host |
| `REDIS_PORT` | `6379` | Compose host port |
| `LLM_BASE_URL` | `http://localhost:1234/v1` | `SCAFFOLDED`; not used by the current conversation path |
| `LLM_MODEL` | `local-model` | `SCAFFOLDED` |
| `LLM_API_KEY` | `lm-studio` | `SCAFFOLDED` |

For host development, a minimal root `.env` is:

```dotenv
SECRET_KEY=local-development-only
DEBUG=false
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=anios_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
REDIS_HOST=localhost
REDIS_PORT=6379
```

Do not use the Compose credentials or example secret in production. Because process environment variables have precedence, inspect and correct a pre-existing `DEBUG`, `POSTGRES_HOST`, or `REDIS_HOST` variable when local imports behave unexpectedly.

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

Backend tests are located under `backend/tests`:

```bash
python -m pytest -p no:cacheprovider backend/tests
```

The `-p no:cacheprovider` option avoids writing `.pytest_cache`; it does not alter test behavior.

When the corresponding development tools are installed, the configured static checks are:

```bash
ruff check .
black --check .
mypy backend
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

The repository currently has no frontend `test` or `test:e2e` script and no browser automation framework. Browser automation is `PLANNED`; do not invent a test command or call UI behavior verified until the harness exists and the workflow passes. Until then, use the documented manual browser procedure below and report it separately from automated coverage.

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
  -d '{"user_id":"validation_user","query":"Reply with: validation ok","metadata":{}}'
```

The repository also contains a diagnostic client:

```bash
python debug_test.py
```

Validate all applicable acceptance properties:

- the request reaches the intended handler and service;
- status, headers, and body match the contract;
- response content achieves the requested behavior rather than returning a placeholder;
- a stream emits and terminates cleanly;
- logs contain no server exception;
- expected records or other side effects exist;
- invalid input produces an intentional error.

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
