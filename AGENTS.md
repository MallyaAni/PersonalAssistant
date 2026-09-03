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
- **Never write a specific case into a prompt.** A prompt states a principle that holds for anyone; the incident that prompted it belongs in the file's notes, a code comment, or the commit message, never in the text sent to a model. Wording like "a black hat edited to a straw hat", "my DGX Spark", or a particular user's phrasing teaches the model to match that case and stop reasoning about the general one, and every future failure then wants its own sentence until the prompt is a list of somebody's bad days. Prompts written this way get longer, more brittle and less intelligent — `search/compose.md` was halved and `_render_image_context` cut by a third after each had accumulated a sentence per incident. When a real failure needs fixing, ask what is true of every question of that shape, write that, and record the incident beside it rather than inside it.
- **Decide meaning with a model, never with a pattern.** Whether a message wants a picture, an edit, a search, a diagram or nothing; which picture "that one" refers to; whether something is worth remembering — these are judgements, and every regex, keyword list or bounded classifier written to make them here has been deleted after failing on phrasing its author did not anticipate. `SearchRoutingPolicy`, `CascadingSearchRouter`, `image_subject.py` and `QueryFreshnessClassifier` are all gone for this reason. Ask the model that has the conversation in front of it, and give the answer a schema, a bound and a fallback. Patterns are legitimate for *shape* — is this reply prose or a query, is this file a PNG, does this string parse as a UUID — never for intent.
- **A new tool is not shipped until the router is measured choosing it.** Every built-in the router can pick needs labelled cases in `backend/services/tool_selection_cases.py`, and its name in `TOOL_NAMES` — those two are one step, not two. `schedule_task`, `manage_tasks`, `save_skill` and `manage_skills` shipped with neither, and the omission was self-concealing: `test_every_case_is_labelled_with_a_tool_that_exists` rejects any case naming a tool `TOOL_NAMES` omits, and `evaluate_tool_selection` scored every decision those four made as "no tool". The feature was unmeasurable by construction, so the first thing that broke was silent — asked to move a reminder, the assistant said it had, and no write happened. `bash scripts/gate.sh` is what runs this now.
- **Assert the datastore changed, not that a tool was called.** A structural test proves the router fired and a handler ran; it cannot tell you the row is still exactly as it was. The reminder that never moved passed every structural check in the repository. When a turn is supposed to change something, the test reads it back — `backend/tests/functional/test_task_reschedule_behaviour.py` asserts `next_run_at` moved and that a weekdays task is still weekdays afterwards.
- **Give a capability its whole verb set, or a request will be inexpressible.** The selector makes one tool decision per turn, so a capability whose documentation says "to change it, cancel it and make a new one" cannot be used in a single turn at all. `manage_tasks` said exactly that, and the model — handed a request it had no way to carry out — answered as though it had. When adding a tool, check the set is closed over what people will actually ask: create, read, update, delete, and whatever pausing means for that thing.
- **Widening one tool narrows another, and only a measurement will show it.** Adding `reschedule` moved four Scout cases from no-tool to `manage_tasks`, and stuffing the description with time-change examples then taught the router that any mention of a time meant a reminder — two email-drafting follow-ups went with it. Both were caught by re-running the matrix and comparing cells, not the total. Change one tool, re-run `python -m backend.cli.evaluate_tool_selection --reps 3`, and compare per-category; a steady aggregate hides two failures that cancel out.
- **A turn may take several steps, and the stopping rules are the design.** `backend/services/turn_steps.py` runs decide → act → observe → decide, and it is deliberately separate from `ConversationService` so a future agent can reuse it and so a test can drive the real loop rather than a copy that drifts into passing. Two rules to keep when reusing it. Ask the model for the *next* action and treat the absence of one as the stop — never ask "is that enough?", because "nothing more" is the cheap answer to a yes/no question and it is given too readily. And do not trust the prompt to prevent repetition: told plainly never to repeat what was already done, the router scheduled the same reminder three times in a row, and `ScheduledTaskRepository.create` has no dedupe key, so every pass was another reminder nobody asked for. The instruction stays because it helps; the guards are what hold — an identical-repeat set compared on shape, a refusal to create a second thing, a step ceiling, and a wall clock.
- **Restrict a later step in code, not in the prompt.** `MainActionSelector.select(only=...)` narrows what a second decision may even see, so it cannot start a ninety-second image generation or spend a search credit however the model is asked. This is the same mechanism that withholds the automation tools from a firing scheduled task, and it is the rule from two entries above applied to a new place: when a model will not follow an instruction, make it structural.
- **A loop must be off when the turn is unattended.** A fired reminder carries the person's own words, which read like a fresh request; letting it decide again is how a reminder reschedules or re-teaches itself. That is now guarded in three independent places, and none of them replaced the others.
- **A floor that has never been seen to fail is not a floor.** Two assertions in `test_tool_selection_matrix_behaviour.py` had been failing for an unknown length of time before anything could run them. When lowering one to a measured value, record the measurement and the reason beside it — `PER_TOOL_ACCURACY_FLOORS` carries that history — and never lower one to make a run go green without saying what moved.
- When a model will not follow an instruction, make it structural rather than repeating the instruction louder. Told four different ways not to name the user's hardware in a search query, it named it every time; the working fix was to build the query in code from a category the model supplied. A fifth wording would have been the wrong move, and the fourth already was.
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
- More than one agent commits to this repository (sessions on the Mac, opencode on the Spark). GitHub `main` is the single truth: run `git pull --rebase origin main` before starting work, and push as soon as a checkpoint is verified. Unpushed commits diverge silently - on 2026-09-01 eight local commits and one on origin had to be reconciled by hand, and `scripts/deploy.sh` (ff-only pull) rightly refused to build the diverged tree. Two agents editing the same file at the same time is the one thing this rule cannot fix; split by area.
- Never run `git reset --hard`, `git clean -fd`, `git restore .`, destructive checkout commands, or force pushes without explicit approval.
- If Git is unavailable, report Git state as `UNAVAILABLE` and do not invent branch, commit, or diff information.

## Completion rule

A running process, open port, successful health check, compiled file, passing unit test, or HTTP 2xx response does not by itself prove that a task achieved its goal.

Before declaring a task complete:

1. Run the relevant startup command and identify the exact source revision or image being exercised.
2. Exercise the actual user or system acceptance path.
3. Validate expected content, state transitions, side effects, persistence, logs, and error handling—not only reachability.
4. Run relevant automated tests and builds.
5. Add the functional proof the change needs - by what changed, not by habit:
   - **A prompt or a rule in one** - a test in `backend/tests/functional/` that runs the real model and asserts on what came back, named in the prompt's header as `pinned by:`; if it is a routing rule, a matrix case too, and `backend.cli.ablate_prompt_rules` when a category will not move.
   - **A tool (built-in or MCP)** - a live test that *calls the tool* with real inputs written from `backend.cli.real_utterances` (the phrasings people use, including the failing ones: a place the geocoder does not know, a provider that is down), plus a sweep journey so it is walked over HTTP.
   - **Anything that resolves "this", "it", "again"** - a case in `functional/test_followup_resolution_behaviour.py`; never a new place that works it out.
   - **Anything that changes state** (a reminder, Scout, a memory) - a sweep journey with a database assertion, and a receipt in the change log so "undo that" can reverse it.
   - **Anything carried in a per-turn ContextVar** - checked over HTTP (a sweep journey or harness), because an in-process test iterates the stream in one task and cannot see the boundary that lost every such value on 2026-08-26.
   - **A new tool or route** - the evaluator's numbers recorded in the CHANGELOG and a floor set one miss below them.
   A test that a model was called, or that its answer parsed, does not show that it answered well. `backend/tests/test_functional_coverage_completeness.py` fails when a tool has no live test, a capability has no sweep journey, or a prompt declares no pin - it is the mechanical form of this rule.
6. Ship only through `scripts/deploy.sh`: the unit suite and the routing gate before, the sweep and the search harness after, on the deployed system.
7. Report every applicable criterion as `VERIFIED`, `FAILED`, or `UNVERIFIED` with concrete evidence, with the numbers.

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

- **Two agents share this checkout; never rewrite `main`.** On 2026-08-26 a
  force-push from a branch that was behind removed three published commits
  from the remote until they were merged back. `git config core.hooksPath
  scripts/git-hooks` is set here so `scripts/git-hooks/pre-push` refuses a
  non-fast-forward push; fetch and merge instead. Re-run that config line
  after a fresh clone.
- **A migration has to reach the database before the gate that tests it.**
  `scripts/deploy.sh` runs the unit gate *before* it backs up and migrates, and
  the unit suite talks to the real schema rather than one built from the
  models. So a commit that adds a column fails its own deploy: on 2026-08-30
  the `kind` column on `scheduled_tasks` failed nine task tests with
  `UndefinedColumnError` at the gate, several steps before the migration that
  would have created it. Apply it first - `bash scripts/backup-db.sh`, then
  `docker compose run --rm -e POSTGRES_HOST=db -v $PWD/migrations:/app/migrations:ro
  backend python -m alembic upgrade head` - and let the deploy's own migrate
  step re-run it as a no-op. This is only safe for an additive change the
  running code ignores; a column the old code cannot tolerate has to go out
  with its code, which means taking the outage rather than reordering these.
- **The test image is stale by design; mount, don't trust it.** The
  `functional-tests` image is built rarely. `scripts/gate.sh` mounts
  `backend/`, `bridges/`, `prompts/`, `skills/`, `docs/`, `deploy/` and
  `.env.example` from the checkout and points `REDIS_URL` at the compose
  Redis; without those, 24 tests read as stale (503 from the rate limiter,
  a budget that grants everything, an import that does not exist yet).
  `--ignore` paths must be container paths (`/app/...`): a host path is
  silently not matched, which once ran the entire real-model suite under
  `--unit`.
- **Write cases from real sentences, not imagined ones.** Run
  `python -m backend.cli.real_utterances --days 14` in the backend container
  before adding a matrix case, sweep journey or functional test: every
  incident of 2026-08-26/27 was a phrasing the tests had not imagined
  ("DC" for "Arlington", "adjust this" for "move the stretch reminder").
- **A follow-up is resolved once, in `backend/services/followup.py`, before
  the router.** Do not add another place that works out what "this", "it"
  or "again" means (a picker hint, a prompt sentence per tool): give the
  resolver a case in `functional/test_followup_resolution_behaviour.py`
  instead. Every incident of 2026-08-26/27 was one component resolving a
  referent its own way.
- **Per-turn ContextVars survive the stream only because `_with_heartbeat`
  runs every pull in one shared context.** A generator pulled by fresh
  tasks (`ensure_future(anext(...))`) loses anything a ContextVar set in an
  earlier pull; in-process tests iterate in one task and never see it. Do
  not replace that wrapper's `create_task(..., context=...)`, and when a
  behaviour depends on a ContextVar, verify it over HTTP (the sweep's
  trace check), not only in-process.
- **Deploy only through `scripts/deploy.sh`.** It runs the unit suite and
  the routing gate first and the journey sweep and search harness after.
  `docker compose up -d --build` by hand skips all of it; a build shipped
  that way carried a seven-test regression for hours.

- **A new column on a widely queried model refuses the deploy before it can
  migrate.** `scripts/deploy.sh` runs the unit gate against the live database
  *before* `alembic upgrade`. A column every query selects
  (`knowledge_documents.about_until`, 2026-09-02) fails every test that loads
  that table with `UndefinedColumnError`, and a column-presence skip in the
  new test does not help the others. Additive migrations (nullable columns,
  an index) are safe under the running build; apply them ahead of the deploy
  from a container carrying the new tree, or deploy the migration in its own
  step first. `--skip-gate` is the last resort and is the operator's decision.

Each of these has cost real time or real data here. They are recorded because
they are not discoverable from the code alone.

**`.local` names do not resolve inside a container, and fail deceptively.**
Services reach Postgres, Redis and the models as `animallya-sparkN.local`.
That is mDNS: it works on the hosts and not inside Docker, where spark1
resolves to unroutable link-local IPv6 and spark2 to nothing at all. Meanwhile
`/health` still answers 200, because it touches no dependency - so a totally
broken stack looks healthy. `docker-compose.yml` pins both Sparks by IP in the
`x-spark-hosts` anchor. Verify any migration by exercising each dependency from
inside the container, never by curling `/health`.

**A powered-off Spark needs a physical button press.** It has no BMC and no
Wake-on-LAN, so nothing brings it back remotely - keep its IP recorded
(spark1 = 172.16.8.3, spark2 = 172.16.8.5), and do not power one down unless
someone can reach it. Shutting one down on request is fine; scheduling one
for later, when nobody is watching and the request may no longer hold, is
not.

This was learned by doing it. Asked to replace a 30-minute shutdown with a
two-hour one, every scheduling mechanism was checked - `shutdown /a`, systemd,
`atq`, both crontabs - and **no shutdown existed**. A shutdown was created
anyway, on a machine serving the live site. The Spark went down and could not
be brought back: it had only ever been reached by mDNS name, so no IP or MAC
was retained. It took a physical press of the power button.

The general rule the specific one comes from: **when the premise of an
instruction turns out to be false, report that and stop - do not construct the
thing you were asked to modify.**

**Before touching a model, an inference server, or the Spark, read
[docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md).** It holds what the
running models actually are rather than what their cards say, the numbers
measured on this hardware, the restore path for a service that has no systemd
unit, and the failures that only appear at runtime. Two of them would have
taken the whole assistant down: `reasoning_effort="none"` is accepted by
ds4-server and 400s on every vLLM request, and a reasoning model under a small
`max_tokens` returns an empty string rather than a short answer.

**Never decide a model swap from published benchmarks.** They describe
unquantised weights, and the DeepSeek deployed here is a **2-bit** quantisation
— 86.7 GB for ~284B parameters. Aggregators also disagree with the models' own
cards; one reported a 35-point LiveCodeBench lead that the official figures
reverse. Measure it with `evaluate_reply_quality` against
`backend/services/reply_quality_cases.py`, and capture everything from the
incumbent *before* offloading it, because one 128 GB box holds one large model
and a challenger can only be measured in the space the incumbent vacates.

**`.env` beats the compose default, so raising a default may change nothing.**
Compose writes `KEY=${KEY:-new_default}`, and a `KEY=old_value` still sitting in
`.env` wins. Raising `VISION_MAX_TOKENS` in `settings.py` *and* in
`docker-compose.yml` left the container reading the old 512 because `.env` also
set it; `IMAGE_MODEL` did the same, keeping HiDream after the code moved to
FLUX. Pydantic reads `.env` directly too, so the host and the test suite can
disagree with the container about the same setting. Change the value in every
place that sets it, then read it back from the running container.

**A prompt outlives the policy it was written for.** Three separate defects here
were a prompt still asserting a rule that had stopped being true: "call
create_diagram only when the user *explicitly* asks" sent labelled architecture
diagrams to a diffusion model that can only imitate writing; "do not repeat
candidate names, even to call them plausible" discarded identifications the
vision pass had actually made; "do not claim to have performed the setup
yourself" outranked the save state once a cadence really could be recorded, so
the assistant disowned a change it had just made. When behaviour contradicts
what the code does, read the prompt for a sentence that used to be right.

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

**The test suite no longer reads `.env`, and that is deliberate.** The live
file sets `AUTH_REQUIRED=true` and `AUTH_COOKIE_SECURE=true`, and settings are
built once at import, so those governed every run on a real workstation while a
clean checkout behaved differently. This entry used to say "run the suite with
`AUTH_REQUIRED=false`" and the failures kept being investigated as regressions
anyway. `conftest.py` now sets `ANIOS_TEST_MODE` before anything imports
settings, which makes `Settings` skip the file; `test_environment_isolation.py`
fails if any setting starts following it again. `ENCRYPTION_KEY` is the one
exception, passed through narrowly, because several tests read rows in the
shared development database that were sealed with the deployed key. Switching
the file off immediately exposed a test that had been passing for the wrong
reason: it reused one HTTP client across a registration, and only survived
because `AUTH_COOKIE_SECURE=true` made httpx drop the cookie that would have
re-identified it as the new guest.

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

**Edit files with the file tools, not with a shell heredoc.** Four separate
times in one session, a Python edit script piped through a heredoc turned `\n`
inside a string literal into a real newline and produced a file that would not
parse — in `search_planner.py`, in `graph.py` twice, and in `api.py`. Ruff
caught each one, so the cost was time rather than a bad deploy, but the fix is
not to be more careful: use Edit/Write for anything containing an escape, a
regex, or a quote. The related failure is a `str.replace` that matches nothing
and reports success — every scripted edit asserts the old text was found, or it
silently does nothing and gets reported as done, which happened twice here.

**Do not write regex escapes through a shell heredoc.** A `` written that way
reached `listing_filter.py` as a literal backspace byte (0x08). Ruff, MyPy and
the tests all passed; the rule silently matched nothing, and the only sign was
an evaluation number that would not move. Use the Edit tool for regex, or
`chr(92)`, and check with `python -c "print(open(f,encoding='utf-8').read().count(chr(8)))"`.

**Verify a claim against the running container, not the source.** A rebuilt
image, a stale container, and an edited file are three different states. Several
defects here were only visible by asking the live system what it actually had.

**The `gateway` service is a one-shot static build, not the live app —
`docker restart gateway` redeploys nothing.** `frontend`
(`localhost:5173`) is the Vite dev server with the source bind-mounted, and
hot-reloads on every save. `gateway` (`docker-compose.yml`'s `gateway`
service, `Dockerfile.gateway`, port 8080 — what the tunnel and
`deep-matter.com` actually point at) instead runs `npm run build` once
*during its Docker image build* and bakes the resulting `dist/` into an
nginx image; nothing about it watches the source tree afterward. A whole
session's worth of frontend fixes were repeatedly reported as "still
happening" — hard-refreshing changed nothing, because the browser really
was getting fresh bytes (`Cache-Control: no-store` on that route) of a
build frozen from a day earlier. Verify: `docker inspect anios_gateway
--format '{{.Created}}'` against the last relevant commit's timestamp, or
`docker exec anios_gateway grep -l "<a string only in the new code>"
/usr/share/nginx/html/assets/*.js`. Redeploy with
`docker compose build gateway && docker compose up -d --no-deps gateway` —
a plain `docker restart` or `up -d` alone reuses the old image and changes
nothing. If the user reports a frontend fix as not taking effect after a
hard refresh, suspect this before suspecting the browser.

**Recreating `anios_backend` used to break `gateway` until `gateway` was
also restarted — fixed, and worth knowing why.** `nginx.gateway.conf` proxies `/api/` to `http://backend:8000`
and resolves that hostname to an IP once, when its worker processes start —
it does not re-resolve on a schedule. `docker compose up -d --no-deps
backend` (needed for any `docker-compose.yml` environment change, per the
first trap above) gives the recreated container a new Docker-internal IP;
`gateway`, still running from before, keeps proxying to the old one and
every request through `deep-matter.com` gets a `502` with `connect() failed
(111: Connection refused)` in `docker logs anios_gateway`, while `docker
exec anios_backend` and `curl localhost:8000` from the host both work fine
— because both of those bypass the gateway's stale resolution entirely and
so cannot reveal the break. Restart `gateway` (a plain `docker restart
anios_gateway`) was the manual cure, and this entry said so for months. It
still happened: two backend rebuilds in one day, no reload, and the site
answered `502` to everyone for hours. A trap that requires remembering
something is a trap that eventually fires, so the config was changed instead.
`/api/` now reaches the backend through a variable against Docker's embedded
DNS (`resolver 127.0.0.11`), which forces a fresh lookup per request; the
request URI has to be appended explicitly, because nginx cannot work out which
prefix to replace once the upstream is a variable. Two guards hold it:
`test_gateway_config.py` asserts the shape, and
`functional/test_gateway_follows_the_backend.py` proves the property by parking
a placeholder on the backend's address so it cannot return to it, restarting
it, and asserting the gateway still answers without ever being reloaded. Still
verify through the gateway path rather than a direct one when in doubt:
`curl -H "Host: deep-matter.com" http://localhost:8080/api/v1/auth/session`
should read `401`, not `502`.

**Files outlive the rows that point at them, and always will.** Deleting a row
and deleting its bytes cannot be made one atomic act across a database and a
filesystem, so every call site can be correct and storage still leaks. It had
reached 460 MB of 556 MB — 83% unreachable, mostly rendered decks whose rows
were long gone. `backend/artifacts/collection.py` sweeps it;
`python -m backend.cli.collect_storage` reports by default and needs `--apply`
to delete. Before trusting a sweep, check that referenced files found equals
keys on record — if they differ, the reference set is not what you think it is.
The scheduled sweep is under the `maintenance` profile, which is **not enabled
by default**, so neither it nor `memory-maintenance` is running unless someone
turned the profile on.

**Provenance is a property of the artifact, not a result of the query.** Image
recall drops an original when one of its own revisions also matches, so the same
picture is not offered twice — and everything the original knew went with it. A
photograph the user uploaded and then edited survived only as a
`generated_image` titled "Edited image", and asked about the hat in their own
photo the assistant described the hat from the *edit* as the one they had
uploaded: a confident false statement about the user's own belongings, with the
true description sitting in the database.

The first fix carried the dropped original onto the survivor, which only worked
when the original happened to match the same query — that is, when it was least
needed. An answer assembled from whatever else retrieval returned is only ever
as complete as the query was lucky. `parent_artifact_id` is a real indexed
column now, and `ArtifactLineageStore.resolve_lineage` walks it in one bounded
recursive query for a whole page of matches, enforcing ownership at every hop.
`collapse_revision_chains` went back to deciding only what is shown. Postgres
does not index a foreign key for you, and `ON DELETE SET NULL` scans the table
on every artifact delete without one.

Anywhere else that dedupes, ask what the dropped row was the only record of —
and resolve that from the thing itself, not from its neighbours.

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

**Frontend changes reach Cloudflare only through a rebuilt gateway.** Port 5173
is the bind-mounted Vite development container, but `deep-matter.com` terminates
at the gateway image, whose Dockerfile compiles and copies its own immutable
frontend bundle. Rebuilding or restarting `frontend` does not change that
bundle. After a frontend change run `docker compose build gateway` followed by
`docker compose up -d gateway`, then fetch the public hashed JavaScript asset
from inside a container and prove it contains the new behavior. A public 200
can still be stale UI.

- **A conditional prompt block must leave the prompt byte-identical when it
  is absent.** Adding `SYSTEM + " " + block + rest` for a new feature put one
  extra space into every prompt that had no block - and at temperature 0 that
  space flipped the memory classifier on a pinned case (a remark about the
  system stored as a user fact: 6/6 wrong with the space, 6/6 right without,
  measured 2026-08-28). Give each optional block its own trailing separator
  and concatenate with none, and pin the no-block prompt byte for byte.
- **A command inside `while read` eats the loop's input.** `docker compose
  exec -T`, `ssh`, and anything else that reads stdin will consume the
  here-string the loop is iterating, so the loop runs once and stops -
  silently. Deploy #25's retry re-checked one of two failing journeys and
  called the sweep green. Redirect the inner command's stdin (`</dev/null`)
  and assert the loop reached every item.
- **`deploy.sh` runs the version it started with.** The script pulls main
  while it is executing, and bash keeps reading the file it opened - so a
  change to `deploy.sh` (the retry-once for flaky journeys, 2026-08-28) takes
  effect on the *next* deploy, not the one that carried the commit. Read the
  deployed log with that in mind before concluding a deploy.sh change did
  nothing.
- **A launch agent's plist env is loaded at bootstrap, not at restart.** Editing
  `~/Library/LaunchAgents/com.anios.imessage-bridge.plist` and running
  `launchctl kickstart -k` restarts the bridge with the *old* environment; a
  new key is silently missing and the bridge refuses what the plist plainly
  allows. Reload it: `launchctl bootout gui/$(id -u)/com.anios.imessage-bridge`
  then `launchctl bootstrap gui/$(id -u) <plist>`, and check with
  `launchctl print ... | grep IMESSAGE_BRIDGE_`. (2026-08-28, first group send.)

- **The memory coordinator rebuilds the reply context; a key set during
  retrieval can vanish before the prompt.** `ConversationService.process`
  fills `context` (document passages, history search, images) and then
  rebinds it to what `prepare_context` returns - a copy in which every store
  the plan chose is searched again and assigned outright. On 2026-09-02 that
  replaced an archived itinerary's passages with an active-only search, so
  the turn trace listed three passages the prompt never held and the reply
  invented a hotel. The plan is a model judgement, which made it
  intermittent. `knowledge` is now kept when non-empty; `entities`,
  `working`, and `summaries` are still assigned outright. When a trace shows
  something the prompt lacks, capture the prompt (`ANIOS_TRACE_PROMPTS`) and
  read `backend/memory/coordinator.py` before touching any framing.

- **`deploy.sh` pulls into the shared checkout, and the other agent's
  uncommitted work blocks the pull without stopping the deploy.** On
  2026-09-02 three queued deploys each hit "Your local changes would be
  overwritten by merge", then went on to rebuild and verify the *old*
  commit and print `DONE: 0`. Deploy from a clean clone instead:
  `~/deploy/anios` on the Spark (the directory name gives compose the same
  project, `anios`, so it recreates the running containers; `data` and
  `secrets` are symlinks to the shared checkout's). Never stash or move the
  other agent's files to get a pull through.
- **Docker's build log says `DONE` on every layer.** A waiter that greps a
  deploy log for the bare word fires mid-build, and the next deploy in the
  chain collides with the one still building. Key waiters and pollers on
  the chain's own marker, `<nth> DONE: <code>`, never on `DONE`, `refused`,
  or `failed` alone (test names contain those words too).

## Documentation ownership

- `README.md`: stable overview, entry points, and documentation map.
- `docs/ARCHITECTURE.md`: current architecture facts and explicitly labeled future design.
- `docs/DEVELOPMENT_GUIDE.md`: setup, commands, debugging, testing, and validation procedures.
- `docs/ROADMAP.md`: milestone status and planned capabilities.
- `docs/NEXT_SESSION.md`: frequently rewritten verified handoff and next atomic task.
- `docs/CHANGELOG.md`: append-only history of meaningful verified changes.
- `docs/SECURITY.md`: current security posture and planned controls.
- `docs/diagrams/`: canonical architecture-as-code sources and their generated sharing formats.
- `backend/tools/`: the built-in tools the router can choose, one module each (a
  `BuiltinTool` row, a `parse` function, and the playful waiting lines the person
  sees); `registry.py` is the only list. The router, the reply prompt's capability
  list, the web status line, and the iMessage waiting bubble all read from it.
  A new capability is a new module here, or an MCP server, which needs nothing here.
- `backend/skills/` and `skills/`: skills are named routines the model invokes by
  meaning - taught in conversation (`user_skills`) or shipped as markdown packs in
  `skills/`. Each is offered to the router as its own tool; invoking one routes the
  skill's instruction again with the ordinary tools. Design and status in
  `docs/TASKS_ARCHITECTURE.md`.
- `docs/AGENT_CATALOG.md`: every specialized agent, what its model decides, where its
  prompt and card live, and what is deliberately decided for it. A new agent adds a
  row here and a diagram pair; the file states the whole checklist.
- `docs/MODEL_EVALUATION.md`: how a candidate model is decided here, the numbers
  measured on this hardware rather than quoted from a card, and the runtime
  traps that no amount of reading the source would reveal. Update it whenever a
  model, quantisation, or inference server changes, and whenever a new failure
  is found by running something rather than by reading it.
- `docs/ML_SYSTEM_DESIGN.md` and `docs/diagrams/ml-serving-design.mmd`: the ML
  systems decisions of the serving stack - which model at which quantisation,
  the KV-cache dtype and pool, tensor parallelism, context length against
  memory, utilisation ceilings, speculative decoding, the embedding/reranker
  sizing, every retrieval threshold and how it was derived, the context
  budget, and the decoding policy - each as the options considered, what was
  measured, the choice, and what would change it. Update it in the same
  change as any serving flag, quantisation, model, cache, context, threshold,
  or token-budget change, and record what was tried and rejected with its
  numbers; a decision whose evidence lives only in a commit message is not
  documented. Every serving flag in it carries its origin - measured here (with
  the number), inherited from a named reference configuration, or the runtime
  default - and the measurement that would change it; a flag with no origin is
  a flag nobody can defend or safely change.
- `docs/adr/`: durable architectural decisions.

After implementation or debugging, rewrite `NEXT_SESSION.md` when runtime evidence or the next task changed. Update other documents only when facts within their ownership changed. Never record code as complete in the changelog unless its intended behavior passed functional validation.

For every modifying task, assess both the full-system view and each detailed subsystem view that owns the changed code. Update every affected canonical Mermaid source and regenerate its SVG when a change adds or removes a component, agent, persistent store, external dependency, deployment/trust boundary, ownership boundary, or cross-component data flow. If an architectural subsystem has no detailed view, add a source/rendered pair and register it in the diagram catalog and renderer suite. Do not churn diagrams for internal refactors, bug fixes, styling, tests, or implementation details that leave those relationships unchanged.

Every modifying completion report must name the result exactly as `Diagram impact: UPDATED — <diagram names>` or `Diagram impact: NONE — <reason>`. Follow the ownership map and validation procedure in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).
