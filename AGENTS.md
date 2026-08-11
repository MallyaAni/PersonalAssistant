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
- A new agent is not finished until it has a folder under `backend/agents/<name>/`, a diagram pair in `docs/diagrams/agent-<name>.mmd` registered in the renderer and the catalog, a functional test, and a row in `docs/AGENT_CATALOG.md`. That file states the checklist; follow it rather than copying whichever agent was written last.
- Every prompt is a feature and gets a functional test, in the same change that writes it. `backend/tests/` is layered by what a test proves: the existing modules cover structure and units, `functional/` covers what a model actually answers, and an integration test covers a path across several components. A new prompt with no functional test is an untested feature however many structural tests surround it.
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
5. If the change adds or alters a prompt, add a functional test in `backend/tests/functional/` and run it. A test that a model was called, or that its answer parsed, does not show that it answered well.
6. Report every applicable criterion as `VERIFIED`, `FAILED`, or `UNVERIFIED` with concrete evidence.

User-interface behavior is `VERIFIED` only after an automated browser test or a documented manual browser session exercises the intended workflow. Serving HTML or reaching an API is insufficient. UI validation should fail on page exceptions, blocking console errors, failed required network requests, incorrect rendered content, broken interactions, or missing required persistence.

Model behavior is `VERIFIED` only after a functional test exercises the real
prompt against the real runtime and asserts on what came back. Structural tests —
that a call happens, that a schema is shaped a certain way, that a failure
degrades safely — prove wiring and would not notice a prompt that had quietly
stopped working, which is the failure a user actually meets. `python -m pytest
backend/tests/functional -q` skips without a runtime, and a skip is not a pass.

Write those tests from what the prompt claims to do, not from the last thing
that went wrong. Assert on properties rather than wording — that an interest
becomes more than two words, that a subject carries no place or date, that a page
saying it is finished is reported as finished and a weekly class is not, that a
description carries no link — so a reworded prompt survives and a changed
behavior fails. The first suite written this way found a defect nobody had
reported, on its first run.

When one of those tests fails against a real product defect, mark it `xfail`
with the evidence in the reason. Do not delete it, and do not loosen the
assertion until it passes: that converts a finding into a false clean run.

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

**A subset of the test suite can fail where the whole suite passes.** `.env`
sets `AUTH_REQUIRED=true` and pytest reads the same file, so any test that calls
a protected route without a token gets 401. The full run only passes because
`test_auth.py` sets `settings.AUTH_REQUIRED` and restores it to false, and every
later module silently depends on that side effect. Run a `-k` subset and the
same tests 401. So: give a test its own token — `TestClient(app,
headers={"Authorization": f"Bearer {issue_user_token(user_id)}"})` — rather than
relying on the order. A cross-user request needs *that* user's token, or it
returns 403 before reaching the code, and a scoping test then passes for the
wrong reason.

**Do not write regex escapes through a shell heredoc.** A `` written that way
reached `listing_filter.py` as a literal backspace byte (0x08). Ruff, MyPy and
the tests all passed; the rule silently matched nothing, and the only sign was
an evaluation number that would not move. Use the Edit tool for regex, or
`chr(92)`, and check with `python -c "print(open(f,encoding='utf-8').read().count(chr(8)))"`.

**Verify a claim against the running container, not the source.** A rebuilt
image, a stale container, and an edited file are three different states. Several
defects here were only visible by asking the live system what it actually had.

**Do not route a user's intent with a regular expression.** Whether words about
a picture ask for an edit or a description was decided by matching the first
word against a verb list. It got "edit this image to give me a straw hat" right
and "give me a straw hat", "put a hat on me" and "draw a hat on this" all wrong,
and its one branch for polite phrasing was unreachable — "can you edit this..."
matched the edit rule and was then rejected for starting with "can". Every miss
looked like the edit feature was broken, and because the misrouted instruction
was then put to the vision model, its "I cannot edit images" was stored as that
picture's description. The decision belongs to a model answering into a
two-value enum: `backend/services/image_intent.py`, measured in
`backend/tests/functional/test_image_intent_behaviour.py`. A test that mocks the
classifier proves routing, never classification.

**Public access is a Cloudflare tunnel, and which kind decides how much else
moves.** Either kind is started with `bash scripts/start-tunnel.sh`, and if the
public URL stopped working, check the tunnel is still running before suspecting
anything in the stack.

The site is served at **`deep-matter.com`**, registered through Cloudflare so
the zone is already in the account. With `ANIOS_TUNNEL_NAME` and
`ANIOS_PUBLIC_HOSTNAME` set, the script runs the named tunnel, the hostname is
stable, and nothing downstream is rewritten. Setup is manual and one-time —
`cloudflared tunnel login` is a browser flow writing a certificate into the
operator's profile, so there is no token to configure and none should be pasted
anywhere. The procedure is in `docs/DEVELOPMENT_GUIDE.md`.

Left unset, it falls back to a quick tunnel whose hostname is random on every
start, which is why the script rewrites `DISCOVERY_CALENDAR_BASE_URL` in that
mode: an address embedded in an invite and left pointing at a dead hostname
fails on the recipient's phone rather than anywhere visible here.

**A real HTTPS origin is what makes `AUTH_COOKIE_SECURE` true**, and the two
change together. True over plain HTTP leaves no working login anywhere — the
browser refuses the cookie and there is no HTTPS origin to set it on. Nothing
else needs the hostname: the gateway serves the app and proxies `/api` on one
origin, so the browser is same-origin, and `validate_browser_origin` accepts
`https://<host>` from the request rather than from a list.

**ComfyUI can be running with a dead CUDA context.** Its web UI keeps answering
`/` with 200 while every GPU call fails with `torch.AcceleratorError: CUDA error:
unknown error`, so it looks healthy from anywhere that checks the port or the
page. `/system_stats` is the endpoint that tells the truth — it returns 500. A
context cannot recover from this and the process must be restarted. It happened
when vLLM restarted and reclaimed the card, which the GPU handoff makes routine,
so expect it after any image job that coincides with a vLLM restart.

**ComfyUI is a host process and nothing restarts it.** It runs from
`COMFYUI_HOST_PATH` rather than in Compose — the host install is far lighter than
the CUDA container image, and Qwen is quantized to FP8 specifically to leave GPU
headroom for it. So `restart: unless-stopped` does not apply, and after a reboot
every image request fails while every container reports healthy. Started by
`scripts/start-anios.sh`, by the `DeepMatter ComfyUI` logon task, or by hand;
`docker compose --profile comfyui up -d` runs the containerized alternative.

The failure reads as a refusal rather than an outage. The backend does return
"The image generation backend (ComfyUI) isn't running", but an edit typed into
the main composer used to become an ordinary chat turn, and the model — having
no image tool — replied that it could not edit images. Check
`http://127.0.0.1:8188` before believing the assistant declined anything.

**A reaction made on a phone, in a thread with yourself, cannot be linked.**
Sending to your own Apple ID gives the phone a *different* message object from
the one the Mac sent. React there and the tapback references the phone's copy —
a row the Mac never stored — so it syncs across pointing at nothing. Verified:
two reactions arrived as types 2001 and 2002 whose targets both reported
`found: false` against the Messages database. No matching strategy fixes this,
because the tapback-to-message link *is* that identifier. The same two reactions
made in Messages **on the Mac** recorded immediately. Subscribers are unaffected:
a normal recipient's reaction references the sender's own message. It is the
owner's own thread that cannot work, which is the one every test uses.

**Match a reaction by the message body, never by Apple's identifier.** There is
no identifier handed back at send time, and every way of recovering one
afterwards failed on a real Mac: never captured, captured but pointing at the
wrong message, and pointing at a copy this machine never stored. The body is
composed here, identifies the message rather than the row, and is shared by
every copy of it. Note that recent macOS keeps most bodies in `attributedBody`
rather than `text` — 54 of 64 in one sample — so anything matching on `text`
alone matches almost nothing.

**Prefer a user logon task to a SYSTEM one for anything here.** A task
registered without elevation can be read, started and stopped from an ordinary
shell, so it can be tested; a SYSTEM task cannot even be listed without admin,
which is how one sat broken for a day while looking registered. Both host
processes — `DeepMatter tunnel (user)` and `DeepMatter ComfyUI` — run at logon
for that reason, and because Docker Desktop starts at sign-in too: a tunnel that
starts at boot spends the gap serving 502s with no origin behind it. A
`LastTaskResult` of `267009` (0x41301) means "currently running", not a failure.

**A Windows service reporting `Running` proves nothing.** The tunnel service
installed cleanly, reported `Running`, and registered no connector for an hour,
because Windows recorded its ImagePath as the bare executable with no arguments:
it started, had nothing to run, exited, retried. `sc.exe config` would not attach
arguments, `service install` refused to touch an existing registration, and
`service uninstall` left the key marked for deletion behind a process that would
not die. The tunnel now runs as the `DeepMatter tunnel` Scheduled Task as SYSTEM
at startup, which starts at boot rather than sign-in, restarts on failure, and
reports a real `LastTaskResult`.

**One connector is not evidence either.** Every check during that hour showed a
healthy connector — it was a foreground process someone had started by hand.
`cloudflared tunnel info anios` must show the connector whose timestamp matches
when the task started, and the only conclusive test is stopping every other
connector and confirming the site still serves.

**Cloudflare answers a non-browser client with error 1010.** The browser
integrity check refuses a plain scripted request on every path, which reads
exactly like a dead site — 403 on `/`, `/healthz`, everything. Send an ordinary
`User-Agent` or the check measures the bot rule rather than AniOS. The test that
proves the tunnel reaches the *application* is an API route returning 401, not a
static page returning 200.

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
- `docs/AGENT_CATALOG.md`: every specialized agent, what its model decides, where its
  prompt and card live, and what is deliberately decided for it. A new agent adds a
  row here and a diagram pair; the file states the whole checklist.
- `docs/adr/`: durable architectural decisions.

After implementation or debugging, rewrite `NEXT_SESSION.md` when runtime evidence or the next task changed. Update other documents only when facts within their ownership changed. Never record code as complete in the changelog unless its intended behavior passed functional validation.

For every modifying task, assess both the full-system view and each detailed subsystem view that owns the changed code. Update every affected canonical Mermaid source and regenerate its SVG when a change adds or removes a component, agent, persistent store, external dependency, deployment/trust boundary, ownership boundary, or cross-component data flow. If an architectural subsystem has no detailed view, add a source/rendered pair and register it in the diagram catalog and renderer suite. Do not churn diagrams for internal refactors, bug fixes, styling, tests, or implementation details that leave those relationships unchanged.

Every modifying completion report must name the result exactly as `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`. Follow the ownership map and validation procedure in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).
