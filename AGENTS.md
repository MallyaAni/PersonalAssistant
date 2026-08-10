# AniOS Agent Instructions

## Source of truth

Use the current implementation, configuration, tests, and observed runtime behavior as the source of truth for what AniOS does today. Runtime evidence is authoritative only when its source revision or built artifact is known; a stale container does not override newer source code. Documentation records intent and verified knowledge, while an ADR records a decision rather than proof of implementation.

Before changing the repository, read:

- [README.md](README.md)
- [Current session handoff](docs/NEXT_SESSION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development and validation guide](docs/DEVELOPMENT_GUIDE.md)
- [Roadmap](docs/ROADMAP.md)

Read [Security](docs/SECURITY.md) when a task affects data, credentials, authentication, logging, external access, or permissions.

## Working method

- Restate the exact objective, acceptance criteria, and relevant `VERIFIED`, `FAILED`, and `UNVERIFIED` facts before editing.
- Keep work limited to the requested atomic task. A task may intentionally advance a `SCAFFOLDED` or `PLANNED` capability only when the user or approved handoff puts it in scope.
- Inspect the relevant implementation before planning or editing. Do not infer behavior from filenames, interfaces, mocks, documentation, or a health response.
- Preserve unrelated user changes and recheck files that may be changing concurrently.
- Reproduce a failure, identify the first failing boundary, test one evidence-backed hypothesis, make one targeted change, and repeat the original acceptance path.
- After three unsuccessful targeted hypotheses, stop editing and report the evidence, attempts, and next investigation needed.
- Judge a retrieval, ranking, or filtering change with `python -m backend.cli.evaluate_discovery_ranking`, not by reading a few results. Two changes were shipped here on a single example each: a cross-encoder reported as improving attribution that made the same mistake more confidently on the first real digest, and a listing filter that emptied a live one. The labelled cases are seeded judgements — correct a label rather than working around the score.
- Keep business logic separate from framework and infrastructure details where the existing architecture supports it.
- A prompt belongs to the agent whose judgement it encodes, and lives in that agent's folder under `backend/agents/<name>/`. The *mechanism* for calling a model is shared and reusable — grammar-constrained, greedy, bounded, with a deterministic fallback — but the prompt, its schema, and the validation of its output never are. Filing a prompt under the domain package it happens to act on is how Scout's four prompts ended up in `backend/discovery/` while `backend/agents/scout/` held only a status card.
- Add a brief, plain-language comment immediately above every newly written function or method explaining what it accomplishes. This includes production code, local helpers, API handlers, frontend functions, tests, CLI entry points, and migration functions. Put the comment above any decorators, and update it whenever the function's purpose changes.
- Do not hardcode production secrets or log credentials, tokens, or unnecessary personal data.
- Explicit user instructions, including read-only requests, override routine documentation-update procedures.

## Git checkpoints

Git is recoverable code history, documentation is reasoning context, and functional tests are proof of behavior. A commit is not a verified checkpoint merely because it exists.

- When Git is available, record the starting branch, `HEAD`, and working-tree state before editing, then report the final state.
- Preserve pre-existing modifications and keep task changes separable. Do not stage or commit unrelated user work.
- Create commits, tags, branches, worktrees, reverts, or other Git mutations only when authorized by the user or the requested workflow.
- Call a commit a verified checkpoint only when its exact tree passed the applicable acceptance path; record the commit SHA and evidence in `NEXT_SESSION.md` after verification.
- For recovery, prefer inspecting or branching from the verified SHA without overwriting the current worktree.
- Never run `git reset --hard`, `git clean -fd`, `git restore .`, destructive checkout commands, or force pushes without explicit approval.
- If Git is unavailable, report Git state as `UNAVAILABLE` and do not invent branch, commit, or diff information.

## Completion rule

A running process, open port, successful health check, compiled file, passing unit test, or HTTP 2xx response does not by itself prove that a task achieved its goal.

Before declaring a task complete:

1. Run the relevant startup command and identify the exact source revision or image being exercised.
2. Exercise the actual user or system acceptance path.
3. Validate expected content, state transitions, side effects, persistence, logs, and error handling—not only reachability.
4. Run relevant automated tests and builds.
5. Report every applicable criterion as `VERIFIED`, `FAILED`, or `UNVERIFIED` with concrete evidence.

User-interface behavior is `VERIFIED` only after an automated browser test or a documented manual browser session exercises the intended workflow. Serving HTML or reaching an API is insufficient. UI validation should fail on page exceptions, blocking console errors, failed required network requests, incorrect rendered content, broken interactions, or missing required persistence.

If functional validation cannot be performed, do not label the behavior verified. Follow [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md).

## Operational traps in this repository

Each of these has cost real time or real data here. They are recorded because
they are not discoverable from the code alone.

**Adding a setting means editing `docker-compose.yml`, not just `.env`.** Every
service declares an explicit environment allowlist, so a new key in `.env`
reaches nothing. This has silently broken a feature three separate times —
`DISCOVERY_PLACE_RESOLVER`, `ENCRYPTION_KEY`, and the discovery calendar base
URL. Add the key to every service that reads it, then prove it arrived:
`docker compose exec -T <service> printenv | grep <KEY>`. A value present in
`.env` is not evidence.

**`ENCRYPTION_KEY` must reach every service that writes a sealed column.** The
API and both workers write `EncryptedText` values. One service without the key
writes plaintext into a column another reads as sealed, which is worse than
neither having it.

**Never run destructive DDL against `anios_db`.** It holds real conversations,
memory, presentations, and artifacts, with `archive_mode = off` and no replica.
`DROP SCHEMA public CASCADE` was once run against it to verify a migration path
and destroyed everything permanently: migrations recreate structure and never
data, so the check passed while the loss was total. To verify migrations use
`bash scripts/verify-migrations.sh`, which builds a throwaway database and drops
it however the run exits. Before anything risky run `bash scripts/backup-db.sh`;
startup also backs up, but startup can be weeks apart.

**`verify-migrations.sh` mounts the working tree.** It previously verified
whatever migrations were baked into the last image build, so a migration added
since appeared to pass without ever running.

**Run the backend suite with `AUTH_REQUIRED=false`.** The live `.env` sets it
`true`; auth tests enable the boundary explicitly. Without the override, several
legacy anonymous API tests return 401 and look like regressions.

**Four test modules fail on a Windows host for missing optional dependencies** —
`test_telemetry`, `test_google_adk_search`, `test_internet_mcp_server`, and
`test_vision_embedding_alignment` need `opentelemetry`, `google-adk`, and
`onnxruntime`, which live in the container rather than the host venv. Their
failure is environmental, not a regression.

**`AUTH_COOKIE_SECURE` belongs with HTTPS, and only with it.** Setting it true
while the only origin is plain HTTP leaves no working login anywhere: the
browser refuses the cookie and there is no HTTPS origin yet. Change it in the
same step that makes an HTTPS origin real.

**Verify a claim against the running container, not the source.** A rebuilt
image, a stale container, and an edited file are three different states. Several
defects here were only visible by asking the live system what it actually had.

**Public access is a Cloudflare quick tunnel that dies with the machine.** Not
Tailscale — that was tried and abandoned, and `docs/NEXT_SESSION.md` records
what failed so it is not retried without new evidence. Restore the tunnel with
`bash scripts/start-tunnel.sh`. The hostname is random on every start, so the
script also rewrites `DISCOVERY_CALENDAR_BASE_URL`; a calendar invite pointing
at a dead hostname fails on the recipient's phone rather than anywhere visible
here. If the public URL stopped working, check the tunnel is still running
before suspecting anything in the stack.

**Never verify public ingress from this desktop.** Some ingress resolves back to
the local machine, so `curl` from the host returned 200 in 14 ms while the
public path was dead — and that was reported as verified. Run the check from
inside a container, which has its own network namespace, and test *every*
published address rather than letting DNS pick one:

```python
socket.create_connection((ip, 443), 10)
ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
```

**An optional field in a response grammar is a field the model will skip.** The
re-ranker's `excluded` list was never emitted at all until the schema marked it
required — three greedy runs returned only an order, so the question was not
being answered so much as skipped. If a model appears to ignore part of a
contract, check whether the grammar lets it.

**A model judging its own input needs measuring across a set, not an example.**
`summarize.py` computes `is_a_listing` and nothing acts on it, because acting on
it emptied a live digest: on a London sweep it called four of five shortlisted
finds listings, including a single Eventbrite event, while passing an index of
festivals in another city. The field stays only because the evaluation harness
needs something to tune against.

**Recreating the backend requires restarting the gateway.** Nginx resolves its
upstream once at startup, so a recreated `backend` gets a new container IP that
the gateway does not know about, and every request 502s while both containers
report healthy and the backend's own log says startup complete. `docker compose
restart gateway` after any `up -d backend`.

## Documentation ownership

- `README.md`: stable overview, entry points, and documentation map.
- `docs/ARCHITECTURE.md`: current architecture facts and explicitly labeled future design.
- `docs/DEVELOPMENT_GUIDE.md`: setup, commands, debugging, testing, and validation procedures.
- `docs/ROADMAP.md`: milestone status and planned capabilities.
- `docs/NEXT_SESSION.md`: frequently rewritten verified handoff and next atomic task.
- `docs/CHANGELOG.md`: append-only history of meaningful verified changes.
- `docs/SECURITY.md`: current security posture and planned controls.
- `docs/diagrams/`: canonical architecture-as-code sources and their generated sharing formats.
- `docs/adr/`: durable architectural decisions.

After implementation or debugging, rewrite `NEXT_SESSION.md` when runtime evidence or the next task changed. Update other documents only when facts within their ownership changed. Never record code as complete in the changelog unless its intended behavior passed functional validation.

For every modifying task, assess both the full-system view and each detailed subsystem view that owns the changed code. Update every affected canonical Mermaid source and regenerate its SVG when a change adds or removes a component, agent, persistent store, external dependency, deployment/trust boundary, ownership boundary, or cross-component data flow. If an architectural subsystem has no detailed view, add a source/rendered pair and register it in the diagram catalog and renderer suite. Do not churn diagrams for internal refactors, bug fixes, styling, tests, or implementation details that leave those relationships unchanged.

Every modifying completion report must name the result exactly as `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`. Follow the ownership map and validation procedure in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).
