# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-08-20, America/New_York

## The model decision is made: DeepSeek stays — DECIDED, RECORDED

Judged blind over 46 cases (`evaluate_reply_quality`, verdicts on disk), Qwen
3.8-27B won the aggregate and lost the decision: its wins were grounding, the
real workload is comparison/trade-off and conceptual engagement where DeepSeek
wins, and every Qwen quantisation that runs on this box decodes at 4.6-8.2
tok/s against DeepSeek's 22.1. A live UI trial of the fastest Qwen was rejected
by the user as far too slow. `docs/MODEL_EVALUATION.md` is the full record and
the operating manual for the Spark - read it before touching a model or the
machine. Revisit only if: a container ships working MTP for GB10, or the second
Spark arrives (then Qwen takes the schema-bound callers and the empty
`VISION_ESCALATION_MODEL` slot with no trade-off).

## What went live on 2026-08-20

- `MAIN_LLM_MAX_TOKENS=4096`: one reply in six was empty at the old hidden
  1,024 cap (thinking ate the budget; reader renders only `content`).
- `reasoning_effort` sent as configured, withdrawn once per client when an
  engine 400s it. "none" is meaningful on ds4-server (suppresses thinking,
  20x fewer tokens) - never drop it unconditionally.
- Cache-aware prompt ordering (`CONTEXT_CACHE_ORDERING`): per-turn volatile
  blocks ride in a trailing **user** message; 8.2x on the second turn of a
  long conversation. All prompt assembly goes through
  `turn_context_messages()` - never assemble a reply prompt from
  `_build_system_prompt` alone; that is how the evaluator silently lost its
  evidence.
- Evidence budget 2500/24000 (was 1500/10000): 100% of what a search returns
  now reaches the model, was 57%.
- Context accounting on every turn (observe-only), recalled-vs-history dedup,
  digest ceiling + model compression with truncation fallback.

## Schedule anything from chat - LIVE 2026-08-22

"Remind me every weekday at 7am to check the spark temps", texted or
typed, is now a saved task that fires as a chat turn under the person's
identity and lands back on the channel it came from. Design and status:
[TASKS_ARCHITECTURE.md](TASKS_ARCHITECTURE.md). The pieces: router
built-ins `schedule_task`/`manage_tasks`, `backend/tasks/`, migration
`20260822_0005` (applied), `backend/workers/task_runner.py` in the
discovery worker process, prompt blocks `reply/scheduled_task` (firing)
and `reply/task_outcome` (confirmation), picker `tasks/pick` (which task
"the weather one" means - the model decides). Gates:
`functional/test_scheduled_task_behaviour.py` (8, all passing on the
Spark reply model; routing cases also pass on the production 4B router).

Same day, second pass: built-in tools moved to `backend/tools/` (one module
each, registry-read), skills added under `backend/skills/` + shipped packs in
`skills/` (taught in chat, invoked by meaning, schedulable), an `action` SSE
event with playful emoji waiting lines (web status line + iMessage ack), and
an Automations panel listing skills and tasks.

Gates: `functional/test_skills_behaviour.py` - all 7 pass on the Spark reply
model; the production 4B router passes 6 and misses one, choosing web search
over the shipped `quick brief` pack for "give me a quick brief on the DGX
Spark" (a miss by meaning, not a wrong answer). Taught skills invoked by name
or meaning pass on both. One more item for the routing-model upgrade.

An audit of the firing path (prompted by a reminder that answered "I can't
control a stove") found seven more defects, all now fixed and gated - the
worst being that a firing could reschedule or cancel itself, and that any
failure was silent. See the audit section in TASKS_ARCHITECTURE.md.

Open from here, in order of value:
- Carry the creating conversation's history into a firing, so an instruction
  naming an earlier discussion has something to resolve against. Today the
  reply block covers it by writing the useful version instead of reporting
  the gap, which is a patch over a missing input.
- Run history in the Automations panel (web-channel output is stored on
  `scheduled_task_runs.output`; the panel shows tasks, not their runs yet).
- Scout as a task kind (its schedule/subscribers/digest map one for one).
- WhatsApp / OpenClaw as further `Channel`s: the runner only needs an
  address lookup and a deliver path per channel.
- Edit-in-place ("make it 8 instead") is cancel + new task today; the
  prompt says so.
- Timezone needs a primary locality; with none the reply asks for the
  city and saves nothing. Consider a profile-level timezone fallback.

## START HERE: the highest-value open items

1. **Flip enforcement once the data says so - the build is done.** Trimming
   is implemented (2026-08-21): the plan applies to the turn's inputs before
   assembly, drops from each section's relevance tail, trims history by whole
   exchanges newest-kept, and never touches system or query - a window
   smaller than those sends in full with a warning. The buried_evidence gate
   (`test_context_enforcement.py`) fails any budget or floor that would lose
   a findable fact. Measurements persist across rebuilds on the telemetry
   volume. The flip procedure: run
   `docker compose exec backend python -m backend.cli.report_context_usage`;
   when it prints suggested floors (needs 25+ real turns), set them in
   `_turn_sections`, set `CONTEXT_BUDGET_ENFORCE=true` in compose, redeploy,
   and watch the report's dropped counts. Nothing else remains to build.
2. **Collect the three conceptual-engagement answers.** The category that
   explains the user's real preference exists but neither model has answered
   its cases (DeepSeek: 2 minutes, up now; Qwen: needs a swap, defer).
3. **Raise the truncation-zone token budgets** - `IMAGE_INTENT_MAX_TOKENS=16`,
   memory proposal 256, vision decision 300, routing 300. On any reasoning
   model these return garbage-as-content (ds4) or empty (vLLM); the image
   intent one was already hit once and misdiagnosed as a model capability
   problem (`get_image_intent_classifier`'s comment records the wrong lesson).
4. **Functional flakiness - FIXED 2026-08-20.** Two causes, neither of them
   needing repetition. Positive marker lists over sampled prose failed
   correct answers for their phrasing ("impossible to determine" missed a
   list holding "cannot" and "not possible") - those assertions are now
   semantic, judged by the routing model through an enforced
   {"holds": bool} schema at temperature zero
   (`backend/tests/functional/semantic.py`, calibrated 6/6 before use).
   And the gate itself now decodes greedily, because at default sampling
   the same prompt sometimes omitted a capability and sometimes did not.
   Measured: one test failing 5/6 and suite flake ~10% before; 13/13 across
   six consecutive runs after; full functional suite 283 passed. Exact
   facts and identities ("90", an invented species name) stay as plain
   `in` checks - those are identity, not meaning, and never flaked.

## Scout interest capture over-triggered on task talk - FIXED 2026-08-21

Six Scout interests landed on a real account from one chat turn about
infrastructure: the tools being set up became things a local-events agent
would search for. Root cause found by reproducing the verbatim turn
deterministically at temperature 0: aspiration phrasing ("I'd like to use it
for X and get amazing X abilities") read as enjoyment, and once one interest
fired, every tool named around it cascaded into labels of its own.

The classifier prompt (prompts/memory/proposal.md) now distinguishes a
standing pursuit enjoyed for its own sake from the work at hand, and caps a
sentence's interests at the pursuit itself - tools and infrastructure named
around it are how it is done, not further interests. One wording attempt:
the verbatim turn yields zero, all thirty functional interest cases pass
three runs straight (every positive phrasing survives, enjoyed technical
pursuits still capture), and the six junk rows were deleted from the
account. If over-capture recurs, reproduce the exact turn first - a
synthetic paraphrase of this one passed while the real wording failed.

Other accounts were not touched; discovery_b1b6fd414c93 carries 37 interests
and may be the same bug or a test account - check before cleaning.

## Scout: delivery down 9 days, and the content judge's first audit

**The iMessage bridge has been down since 08-12** - the Mac answers ping but
port 8010 is closed, so every sweep since then ranked finds into a dead
channel. The bridge is a LaunchAgent needing a logged-in GUI session and an
open lid (lid sleep overrides caffeinate). Recovery is physical: log into
the Mac; the LaunchAgent binds 8010 by itself. Verify from here with a
socket check against 172.16.8.4:8010.

**LLM-as-judge is now shared infrastructure.** backend/evals/judge.py is the
extracted core (headless Claude on the operator's subscription, batched,
tool-less, fenced-reply tolerant); the reply harness now imports it, and any
future agent eval should too. Calibrate before trusting - both existing
judges did (6/6 pairwise, 3/3 Scout rubric on Fable).

**backend/cli/evaluate_scout_content.py judged the account's real runs: 1 of
5 selected finds worth sending.** The systematic cause is one thing, not
five: **no selected find had an established date.** starts_at was null on
every item, so the lead-time/past-event guard has nothing to act on - which
is how a county fair was selected five days after it ended, matched to
"farmers markets".

**FIXED 2026-08-21 (commits 47552b6, 2608534), verified by rehearsal + judge:
4 of 5 worth sending, 5 of 5 timely.** Three stacked causes, found by running
`runner.sweep(user, profile, persist=False)` in-container and instrumenting:

1. **Dates were never transcribed.** prompts/scout/describe.md now asks for
   starts_on/ends_on as stated by the page ({today} resolves relative
   wording); deterministic `apply_described_dates` in runner.py drops
   ended finds and fills starts_at (noon UTC) for dated ones.
2. **Both runner factories charged sweeps to the guest budget.** Operator
   sweeps burned the tiny guest allowance and then searched nothing
   (requests_spent 0). `resolve_search_account(db, user_id)` in
   dependencies.py now feeds is_operator + monthly override into both
   factories; the worker resolves it per run.
3. **The describer ran on the prose writer, whose harness (ds4.c, port
   8888) ignores response_format entirely** - every describe call returned
   markdown, `json.loads` failed inside a blanket except, and sweeps
   shipped raw scraped titles with no summaries or dates. The describer
   now uses the structured client (vLLM enforces the grammar), and
   test_description_quality.py runs on a `structured_llm` fixture so the
   gate exercises the deployed role. Lesson: the functional suite had been
   passing against the *host's* fallback runtime while the container
   pointed at ds4 - when a prompt behaves in tests and not in production,
   compare `settings.MAIN_LLM_BASE_URL` host vs container first.

Rehearsal verdicts: data/model_evaluations/scout-content-rehearsal-ani.mallya-20260821.json
(baseline audit in scout-content-ani.mallya-20260821.json).

**Bridge back + first real delivery, judged 2026-08-21.** The Mac was never
down the second time - DHCP moved it from 172.16.8.4 to .2 and the config
pointed at the old address. Fixed durably: MCP servers marked
`"discover":true` in MCP_SERVERS_JSON rescan their /24 when the configured
host stops answering (backend/mcp/locate.py; token only sent to a host that
first refuses unauthenticated requests like the real bridge; confirmed
address cached in Redis). Verified live: stale config resolved the new
address in 4s. A real queued run then swept, delivered over the bridge
(delivery_count 0->1, last_error cleared, sent_finds recorded), and the
judge scored the delivered digest 3 of 5 worth sending
(scout-content-delivered-ani.mallya-20260821.json). Two content defects
remain, both now visible only because dates and delivery work:

- **Wrong Arlington - FIXED (a20441b).** A focused location call per find
  (prompts/scout/locate.md, one schema-enforced boolean) drops a find whose
  page places it away from the reader; scales to any same-named town and to
  venues known only by world knowledge. Folding the question into
  describe.md degraded the prose gates through three rewordings - separate
  calls for separate judgements is the recorded lesson.
- **Fake "8:00am" - FIXED (a20441b).** Date-only finds now stamp midnight
  UTC, the pipeline's single date-only convention; _format_when renders a
  bare date.
- **4B out of the sweep - DONE (a20441b).** Describe asks DeepSeek first
  (JSON by instruction, schema held by validation, grammar engine as
  fallback); aiming/reranking inverted the same way via
  core/structured_fallback.JSONFallbackWriter. Chat routing, memory
  proposal, presentation stay on the enforcing engine deliberately
  (schema-critical, latency-bound). Judged rehearsals after: ani 3 of 4
  worth sending (two 5/5), jenos1 2 of 3, zero location/date defects
  (scout-content-deepseek-rehearsals-20260821.json).

Still open on content quality:

- **jenos1's interests are junk** ('Social', 'Network', 'Shopping',
  single-word categories) - the ranking amplifies them (Social is
  strength 3). Their digest cannot get much better until the list is
  cleaned; needs the operator's or jenos1's say-so, rows untouched.
- **Tapback feedback loop - CLOSED (2ee5888).** discovery/feedback_loop.py
  reads recorded reactions each sweep: net thumbs shade interest strengths
  in-memory (1-3 band, stored values untouched), and the newest reactions
  join the personal context so aim/rerank weigh them as facts. Education is
  self-teaching and functional-gated: the first-ever digest invites a
  thumbs-up/down in the writer's own words; later digests may show a liked
  pick was remembered but never mention the machinery or anything disliked.
  Digest writer now runs through JSONFallbackWriter (prose model primary,
  grammar fallback) instead of degrading to the assembled form letter.

## iMessage as the conversation surface - LIVE, two open items

Built 2026-08-21 by two sessions against one negotiated contract; verified
on real traffic end to end. Bridge commits 5f380e3 (read_messages),
d4debcd (settle window), b403046 (account pin), 1d2ea8d (attachments both
ways), e562e6f (U+FFFC strip), 97f06e9 (0x82 length test); backend halves
1368e80 (chat worker), 003e6de (photo->vision), e4bc994 (lazy-download
retry); docs/diagram ddfc6ba + 1e10920. 67 bridge tests pass.

**Verified live:** text conversation both ways (rapid double-text survived
the mid-write cursor race the settle window now closes); the operator's own
texts arrive as is_from_me=0 rows post-identity-split (the self-thread
question is settled for *reading*); a real Live Photo listed as one HEIC
row, fetched as a 1.78MB ffd8ff JPEG via sips; a real outbound PNG sent
through the 4-arg AppleScript. Bodies are never logged; strangers and
group chats never leave the bridge process; an attachment id is never a
capability (ownership re-proved at fetch; all refusals read not_found).

**Open item 1 — the sending identity (needs the operator at the keyboard).**
Messages on the Mac holds ONE enabled iMessage account: the personal
mallya.ani96@gmail.com Apple ID (deep-matter@agentmail.to is NOT signed
in; mallya.a@icloud.com is signed in but disabled). Replies therefore go
out under the personal identity, and Apple's per-send alias choice
flip-flops between its email and phone-number aliases — which is why the
operator's *second* reply keeps landing in their self-thread "from their
own number". Alias choice is not scriptable. Mitigation available now:
Messages -> Settings -> iMessage -> "Start new conversations from" = the
email, on both Mac and iPhone. Real fix: sign deep-matter@agentmail.to
into Messages on the Mac, then set IMESSAGE_BRIDGE_ACCOUNT_ID to its
AppleScript account id in the LaunchAgent plist and reload — the Mac
session checks the account list and pins on request.

**Open item 2 — image answers are capped below web quality (deferred by
the operator).** First real photo question misread a shirt bulge. Two
suspected causes, unresolved: the backend's image turn replies with the
vision analysis directly (skipping the reply model the text turns use —
compare against the same photo in the web UI to confirm), and the
documented 4B vision ceiling with VISION_ESCALATION_MODEL still empty.
Transport is ruled out (full-resolution JPEG delivered).

Untested behavior worth knowing before it surprises anyone: edited and
retracted iMessages on the read path, and SMS-only senders (inbound reads
fine; the iMessage-service reply may fail — latent, both allowlisted
addresses are iMessage). Mac-side LaunchAgent env now carries
IMESSAGE_BRIDGE_READ_REACTIONS, READ_INCOMING and READ_ATTACHMENTS, all
true. Bridge source of truth remains bridges/imessage_mac/server.py in
this repo; every Mac-side change above is committed and pushed.

## Still open, lower

- **Wake-on-LAN on the Spark** - `ethtool` not installed, so "off" still means
  a physical button press. IP/MAC recorded in MODEL_EVALUATION.md. Installing
  a package on that box is the user's call.
- **Qwen tool-selection confound** - 19/38 with zero tool calls, ruled out
  parser/tool_choice/temperature/token-cap; open hypothesis is empty required
  arguments being dropped by design. Only matters if the swap is revisited.
- **~15 prompts still inline** - `prompts/README.md` lists them; move is
  mechanical, verify byte-for-byte.
- **The DGX 1am-8am schedule** - direction still ambiguous (downtime vs
  run-window), wake mechanism untested, and per AGENTS.md never schedule a
  poweroff; build nothing until the user restates what they want.
- Two review findings recorded as design calls, not fixed: the measurement
  report models the post-dedup ideal rather than the as-sent prompt, and
  `internet.py`'s fit guarantee weakens at count==1 on pathological inputs.

## Traps that bit this session (all now in AGENTS.md or MODEL_EVALUATION.md)

Read the cells, not the total - an eval aggregate misled a model decision the
per-category table had already called. Never schedule hardware shutdowns; when
an instruction's premise is false, report and stop. A synthetic benchmark can
pass while the shipped code path does nothing (cache ordering measured 16x
synthetic, 1.0x shipped, because chat templates hoist system messages).
`pkill -f` matches the ssh command line carrying it. Heredocs mangle `
` -
five separate times now; use the file tools.

## The retired routing tree is gone — VERIFIED

`SearchRoutingPolicy`, `CascadingSearchRouter`, `MainSupervisorAgent`,
`DelegationRegistry`, the bounded `QueryFreshnessClassifier`,
`evaluate_search_routing.py`, the `SEARCH_CLASSIFIER_*` settings and
`get_classifier_llm` are all deleted, with their standalone tests. Nothing in
that set was reachable from a live turn. `backend/search/routing_cases.py`
survives them on purpose: the labelled set is the measurement, not the thing
measured, and the functional gate now holds the turn's action decision to the
floor the cascade reached over the same 52 cases.

## A tool with nothing to act on no longer takes the turn — VERIFIED

`create_diagram` and `delegate_to_presentation_agent` took no arguments at all,
so a turn routed to either by mistake arrived at the caller looking exactly
like a real request and spent the whole turn on it - a deck queued about
nothing, a diagram of nothing. Both now state a `subject`, and the rule
`generate_image` and `edit_image` already applied covers all four: an empty
required argument is not a decision, so no action is returned and the ordinary
reply path answers, where the general ask rule asks for the one missing thing.
An action whose service is not configured is dropped the same way rather than
carried into the reply as a preselected action - only `SearchAction` and
`ToolboxAction` survive to the reply path, because those are the two it can
still execute.

The live model fills the new argument without prompting changes:
`evaluate_tool_selection` scores **108/108** over 36 cases at 3 reps with an
empty confusion matrix, diagram 15/15 and deck 6/6 among them.

## Known failing, deliberately marked

`test_style_opinion_applies_the_edit_to_the_source_description` is `xfail`
again, with the reason its own comment recorded for exactly this case: asked
about an image whose description states a straw-hat edit, the chat model
answers with the origin's black cowboy hat. 5/5 runs, reproduced on an
unmodified tree, so it is a model regression rather than a code one. Left as
a non-strict xfail so the day a model gets it right the run reports an
unexpected pass.

## Elliptical writing follow-ups retain their task context — VERIFIED

The latest `jenos1` email-drafting thread did not lose persisted history. The
first failing boundary was Qwen's built-in action selection: after drafting a
shift-coverage email, `More casual` was classified as an image edit, and an
earlier answer supplying the requested date and time triggered web search.

The action contract now requires short replies to continue the recent subject
before considering a new one. Supplying requested dates, times, quantities, or
deadlines for drafted material and revising the tone or wording of an email,
message, document, plan, or other text select no tool. Image editing requires
an established picture subject; words such as `casual` cannot turn an email
revision into clothing or appearance work.

The real Qwen functional matrix passes all seven tests, including four distinct
writing follow-ups. The rebuilt backend was exercised through four authenticated
`POST /api/v1/chat` turns as `testuser`: it retained Saturday 8am–7pm and one
recipient, then rewrote that same email casually. All four traces completed and
the logs contain no web-search, MCP tool execution, image-edit, or missing-image
event for the thread.

## Semantic artifact recall and calibrated vision gates — VERIFIED IN SOURCE

The legacy regex-plus-classifier image-recall path is removed. An unselected
turn now makes one structured `ArtifactContextRouter` decision before any
private artifact index; an approved image request tries aligned pixel vectors
and then the description-vector/`VisualMemorySelector` fallback. Unit coverage
proves unrelated turns query neither index and the modality decision runs once.

The vision reasoner now receives an explicit `NONE` candidate section, which
stopped DeepSeek from inventing species when the VLM supplied none. Supported
high-confidence candidates remain; weaker candidates must agree with their
visible basis and any external evidence, and contradicted candidates may be
omitted. Candidate-free uncertainty no longer spends web or main-model
reasoning, while candidate-bearing uncertainty retains deferred reasoning.

The built-in tool matrix now has per-action floors plus explicit bounds for
stray edits, no-tool loss, and diagram-to-generated-image confusion. Real model
functional validation passes 22/22; the complete non-functional backend suite
passes 1209 tests; Ruff, the frontend build, and all 19 diagram checks pass.
No browser behavior changed in this atomic task, so a new browser acceptance
run was not required to establish these backend policy and documentation facts.

## One-call upload inspection with selective specialist escalation — VERIFIED / UNVERIFIED

New image uploads now use one strict structured Qwen inspection for routing,
durable observation, immediate answer, evidence sufficiency, grounding value,
and stronger-reasoning need. Identification confidence is per visible item,
not per image: high-confidence observations can be shown and indexed, and
medium items are explicitly unconfirmed.

Low-confidence guesses are no longer categorically hidden. Hiding them
turned a partial identification into an apparent failure — asked to identify
fish, all three readings came back `low`, every one was dropped, and the reply
was "I can't reliably identify the exact name from this image" while the pass
had in fact read one of them correctly. They now appear under an explicit
"best guess only" heading and reach the reasoning pass with their confidences.
The reasoning prompt preserves supported high-confidence readings, admits a
weaker candidate only while its basis remains compatible with the neutral and
external evidence, and may omit a contradicted candidate. Durable memory still
withholds every unconfirmed name, and safety-sensitive identification still
refuses outright. Candidate-free uncertainty names nothing and does not spend
a web or main-model reasoning call; a candidate-bearing unsettled identification
can ground from visible `basis` strings and ask the one question that narrows it.

`model_uncertain` can make exactly one retry through the independently
configured `VISION_ESCALATION_*` OpenAI-compatible role. Missing pixels and
safety-sensitive cases do not spend that retry. The current host leaves the
specialist endpoint/model blank, so the real specialist runtime is
`UNVERIFIED`; enabling one requires configuration, not another code change.

Prior deployed-browser evidence: the real uploaded
2340x4160 image returned 201 in about five seconds with peeled shrimp at high
confidence, mackerel-like and eel-like items at medium confidence. Its durable observation retained only the
high-confidence shrimp evidence. The unresolved remainder was classified
`model_uncertain`; no specialist is configured. Logs show exactly one Qwen
chat completion, zero web or
DeepSeek reasoning calls, and one embedding write. The authenticated live
Chromium workflow passed in 5.7 seconds: confidence headings and Markdown list items rendered, the
private image rendered, `Image analyzed.` never appeared, loading cleared, the
composer re-enabled and emptied, and Console/page errors were empty. The newer
source-level functional and build evidence is recorded in the section above.

## Scout is now set up from conversation; delivery deliberately is not — VERIFIED

The remaining queued task from the previous handoff is done. A stated run
frequency is a `discovery_schedule` proposal with its own saver, taking the
timezone from the user's own locality rather than asking a model to infer one.
Interests, locality and cadence are all collectable in chat, including when
the user asks to *change* one that already exists — the classifier previously
read "can you change it to 9:25pm" as a question and captured nothing.

`ScheduleDecision.minute` exists because "9:25pm" would otherwise have stored
21:00, and `weekday` is required with no default because a default made the
model skip it and land every weekly schedule on Monday.

**Delivery is not auto-saved, on purpose.** `SECURITY.md` enumerates the kinds
that persist without approval and subscribers are not among them; enrollment
is `consented=False` behind an operator step. The reply says so and links to
`[Scout setup](#agents)`. Workspace views now follow the URL hash, so that
link opens the panel — the app had no routing at all before, and a reported
"the link never worked" was a browser tab loaded before the gateway rebuild.

The agent roster carries each agent's live `status`, `detail` and `facts`, and
prerequisites are rendered **only** while the agent reports `needs_setup` —
listed unconditionally they read as a to-do list, and an account whose own
line said `Interests 7, Subscribers 1, scheduled` was asked for all three
again. The prompt now also states the converse rule: a count above zero means
that part is done, so do not ask for it.

Verified live against the real account: "can you change the schedule to
10:40pm everyday?" saves `daily 22:40 America/New_York` and answers "The Scout
schedule is now set to run every day at 10:40 PM", with no search and no
images.

## Image generation is fully FLUX, and ComfyUI restarts itself — VERIFIED

The half-applied HiDream→FLUX swap did not run at all: `ComfyUIImageProvider`
assigned `self.negative_prompt` from a parameter the same change had removed,
so every construction raised `NameError`. One FLUX.2 Klein checkpoint now
serves generation and editing, loaded through
`UNETLoader`/`CLIPLoader(flux2)`/`VAELoader` — `CheckpointLoaderSimple` does
not list it.

The configuration chain was inconsistent with the code in three places, all
now fixed: `.env` still pinned `IMAGE_MODEL` to HiDream and pydantic reads
`.env` directly, so that value won on the host and in tests; `docker-compose`
passed three retired `IMAGE_EDIT_*` keys and none of the new ones; and
`presentation-worker` received no image-model setting at all despite creating
slide imagery through the same provider.

`comfyui` was the only service in the stack with **no restart policy** — which
is exactly how it behaved, the whole stack returning after a reboot and image
generation alone not. It now has `restart: unless-stopped` plus a healthcheck
against `/system_stats` rather than `/`, because a dead CUDA context still
answers `/` with 200. The probe uses `python3`/`urllib`: that image ships
neither `curl` nor `wget`.

Also: `VISION_MAX_TOKENS` was 512 while a real photograph's structured
inspection measured 488 completion tokens — 24 tokens from truncated JSON,
which fails the schema and answers a valid upload with a 502. Now 1536, and in
the environment allowlist, which it was not.

## Referents resolve semantically, across modalities — VERIFIED

An edit with nothing selected used to dead-end by telling the user to go click
something. `Referent`/`ReferentResolver`/`ReferentSource` now decide which
owned thing a message points at; one confident match is edited and **named**
in the reply, several become a question with the actual thumbnails, none says
so plainly. Nothing in the resolver knows what an image is — proved by wiring
two sources (visual observations and the `knowledge_chunks` HNSW index) and a
functional test where a document and two pictures compete and the document
wins on meaning. Video is a third source file, not a rewrite.

## The GPU handoff cannot be used on this runtime — VERIFIED

**Do not enable `GPU_HANDOFF_ENABLED` hoping to fix slow image generation.**
Generation takes 88–112 s while a *warm* run takes 6.2 s, and ComfyUI's log
shows it swapping weights every job (`Requested to load Flux2` /
`Unloaded partially: 4555 MB freed`) because it cannot hold the UNet, text
encoder and VAE beside resident vLLM on a 16 GB card. That is exactly the
problem this setting was built for, and it does not work here.

With every documented precondition satisfied — `--enable-sleep-mode`,
`VLLM_SERVER_DEV_MODE=1`, and `--kv-cache-dtype auto`, so the known FP8-KV
wake bug does not apply — `POST /sleep?level=1` hangs past 120 s, frees no GPU
memory, and leaves `EngineCore` dead. Every later request answers
`EngineDeadError` until `docker restart anios_vllm_main`, which takes about
150 s. Reproduced twice, service restored both times.

So the slow generations are not a missing handoff. The only fix available is
the card genuinely not holding both runtimes: **when the second Spark lands,
move Qwen to it and leave ComfyUI the whole 5080.** Do not move ComfyUI to a
Spark — GB10 is ~273 GB/s against the 5080's ~960 GB/s, and diffusion is
bandwidth-bound, so it would get slower.

Also fixed here: `.env.example` shipped `VLLM_MAIN_KV_CACHE_DTYPE=fp8`, the
exact value `docker-compose.yml` documents as stranding the engine asleep,
silently overriding compose's own `auto` default for anyone who copied it.

## One engine property explains four separate outages — VERIFIED

`ds4-server` accepts a JSON schema and answers in whatever shape it likes;
vLLM enforces it. That single fact caused, and was rediscovered at, four call
sites: the presentation revert on 2026-08-14, image recall returning nothing,
Scout's place suggester returning an empty tuple, and memory extraction. Each
was fixed by pinning one more caller to Qwen.

Measured rather than inferred: asked to extract a locality and interests, the
main model reads **both correctly** and emits `"locality": "Raleigh, NC"`
where the contract requires `{label, region}`, so the answer is discarded. The
4B model behind the fallback shapes its answer correctly and understands less.
Better reasoning is being thrown away for want of an enforced grammar.

`MAIN_LLM_STRUCTURED_OUTPUT` now names that engine property.
`get_reasoning_llm_client()` follows the main model for prose;
`get_structured_llm_client()` follows it only when the capability is present
and otherwise falls back to the routing role. Memory extraction, deck
planning, place suggestion, visual memory and referent resolution all resolve
through it, so a schema-enforcing main model moves them **together** rather
than one at a time. `backend/tests/test_llm_role_wiring.py` asserts the map.
`DiscoveryRunner` also took one writer for both its prose describer and its
schema-bound aimer and reranker; those are separate roles now.

## The 4B ceiling, with numbers — VERIFIED

Three capabilities are limited by model size, not by prompts. Prompt work on
each was stopped at the three-hypothesis rule; they move when the model moves.

- **Routing.** Agent-setup phrasings: 25/30 call no tool, and the residue
  scatters across `search_web`, `edit_image` *and* `generate_image` on wording
  that differs only by the time of day — "…to 10:40pm everyday?" scored 5/5
  where "…to 9:25pm everyday?" scored 1/5. Diagram-shaped requests reach
  `create_diagram` 9/12.
- **Extraction.** Raleigh 4/4, Durham 0/4, same sentence.
- **Vision.** Fine-grained identification from cut pieces is at the ceiling;
  `VISION_ESCALATION_MODEL` is the designed slot for a stronger VLM and is
  **empty**, so `model_uncertain` currently escalates nowhere.

## Prompts that still asserted a retired policy — VERIFIED

Three separate defects this session were a prompt stating a rule that had
since stopped being true. Worth checking for when behaviour contradicts code:

- `"Call create_diagram only when the user **explicitly** asks"` made the noun
  decide instead of the subject, so a labelled architecture diagram went to
  FLUX and came back with a diffusion model's imitation of writing. Judging by
  subject took diagram-shaped requests from 3/12 to 9/12 with picture-shaped
  unaffected at 12/12 and the search floor still passing.
- `"do not repeat candidate names … even to call them plausible"` in the visual
  reasoning prompt discarded readings the vision pass had actually made.
- `"do not claim to have performed the setup yourself"` outranked the save
  state once a cadence could really be recorded, so the assistant answered a
  saved schedule change with "I'm not going to change the schedule myself".

## Artifact recall is gated before vector search — VERIFIED

`ArtifactContextRouter` now makes one constrained semantic decision about
which owned artifact modalities a message needs before any artifact embedding
or candidate lookup. The current deployment offers image; the contract already
distinguishes document, audio and video for future retrieval implementations.
Visual selection remains as defense in depth after the gate, and selected rows
are collapsed by lineage and duplicate content before reaching the prompt or
browser.

Real-model functional cases pass for personal style, worn items, prior image
work, schedules, reminders, general knowledge, new-image creation, documents,
audio and video. Through the real authenticated browser path, `what do you
think of my style?` recalled two owned images, loaded both private binaries,
rendered a grounded answer, terminated and cleared loading. The exact
regression `yes id like scout for 9:40pm` emitted neither `image_matches` nor
`search_started`, rendered no image, terminated and cleared loading. The two
fresh-conversation live tests pass; the separate active-image fixture test was
skipped because no fixture IDs were supplied.

## Native tool decisions no longer sample — VERIFIED

`OpenAICompatibleInferenceProvider.chat_with_tools` now always sends
`temperature: 0.0`. Tool selection is a bounded application decision, so it
must not inherit a model runtime's creative sampling default. Before the
change, the exact persisted Scout confirmation with its real four-turn history
produced search 5/10, presentation delegation 1/10 and the correct no-tool
decision 4/10.

The real-model regression replays that confirmation five times and requires
all five to choose no external tool. It passes against the configured routing
runtime (`qwen/qwen3.5-4b`), and the existing labelled search-routing quality
floor passes in the same run. Structural provider, selector and MCP
orchestration coverage passes 27/27; Ruff passes on every changed Python file.
The backend was rebuilt and recreated from this working tree and the gateway
restarted afterward. A real authenticated `testuser` request through the
gateway completed with start/delta/done, no error, no `search_started`, and no
`image_matches`; backend trace `cbb5ca52-be65-470d-80ac-c5f6e25ce044`
completed without a web-search routing log.

The second DGX Spark does not change this immediate boundary. Once its
vLLM-compatible DeepSeek V4 Flash checkpoint is online, qualify it against the
same real-model routing suite before changing `ROUTING_LLM_*`; the current
DeepSeek server remains the prose role because it does not enforce the strict
structured/tool contract reliably.

## Image recall was silently dead on DeepSeek; bounded classifiers moved to the routing role — VERIFIED

**Read this before promoting any model to `MAIN_LLM_*` again.** Promoting
DeepSeek on 2026-08-14 also moved every bounded strict-JSON classifier that
followed the chat model, and `ds4-server` treats a supplied JSON schema as
advisory. Two real, live, user-facing breakages resulted, both failing closed
so nothing ever surfaced an error:

- `VisualMemorySelector` — DeepSeek picked the **right** picture and returned
  `{"selected": ["portrait"], "reasoning": ...}`; the schema wants
  `artifact_ids`, so pydantic raised `extra_forbidden` and the code fell back
  to "no images". Reproduced 3/3 on DeepSeek, passes 3/3 on Qwen, and Qwen is
  25x faster here (1.6s vs 42s for the same two cases). Net effect: "how do
  you feel about my dress style?" recalled nothing — the exact bug an earlier
  session fixed and recorded as VERIFIED.
- `PlaceSuggester` — returned `()` on DeepSeek every time; Qwen returns
  Raleigh/North Carolina and Raleigh/Durham County.

This is the **third** instance of one root cause. The presentation revert on
08-14 was the same `extra_forbidden` field-naming failure, and pinning
presentations to Qwen fixed that call site without anyone checking the others.

Fixed at the principle rather than the symptom: `get_classifier_llm()` and
`get_place_suggester()` now follow `ROUTING_LLM_*`, not `MAIN_LLM_*`. Every
caller is a bounded judgement returning strict JSON against an
application-owned schema — the same contract `MainActionSelector`'s
tool-calling has — so it belongs with tool-calling, not with whichever model
writes prose. `ROUTING_LLM_*` still falls back to `MAIN_LLM_*` when unset, so
an install configuring neither is unchanged.

`backend/tests/test_llm_role_wiring.py` (4 tests, new) now asserts the role map
instead of trusting it. Safe by inspection and confirmed: memory proposals and
presentations are independently pinned to Qwen, and the discovery worker still
runs Qwen, so Scout's sweep-side strict JSON (aiming, reranking, timezones) was
never affected.

Evidence: full backend suite (1177 tests) passes; Ruff passes on changed files.
Verified in the rebuilt, recreated production container (gateway restarted, 401
not 502): both roles resolve to `vllm-main`/`qwen3.5-4b`, image recall returns
`('portrait',)`, place suggestion returns both real Raleigh rows.

## Second DGX Spark makes an NVFP4 vLLM DeepSeek real — RESEARCHED, NOT STARTED

A second Spark arrives this week, and it changes the DeepSeek picture
completely. The checkpoints and a purpose-built recipe already exist:

- `nvidia/DeepSeek-V4-Flash-NVFP4` on Hugging Face — **284B total / 13B
  activated**, MoE experts re-quantized to NVFP4 by NVIDIA modelopt with
  attention, shared experts, router head and MTP left at FP8. Runs on vLLM and
  SGLang, and the card explicitly states it **supports structured JSON output
  and function/tool calling** — the exact capability `ds4-server` lacks.
- `tonyd2wild/DeepSeek-v4-Flash-0731-DSpark-1M-NVFP4-KV-2x-DGX-Spark` — a
  recipe for *precisely* this hardware: `tensor-parallel-size 2`, `nnodes 2`,
  `distributed-executor-backend mp`, RoCE/InfiniBand NCCL between the boxes,
  `max_model_len=1048576`, `nvfp4_ds_mla` KV cache, `max_num_seqs=6`,
  speculative decode at 5 draft tokens.

**Measured in that recipe, and it inverts the caution recorded elsewhere in
this file:** peak decode **84.3 tok/s** on structured output, ~22 tok/s
per-stream at concurrency 4, ~197 tok/s aggregate at concurrency 6, prefill
2,639 tok/s at 100K depth. Today's `ds4-server` does **5.7 tok/s**. So vLLM is
roughly 4x faster here, not slower — the "`--enforce-eager` on sm_121 will cost
you" worry is already priced into those numbers.

Nothing is displaced by this. Qwen serves the routing/classifier/vision roles
from the **RTX 5080** (`vllm-main`), not from a Spark, so both Sparks can go to
DeepSeek TP=2 while the split this file recommends stays intact.

Current Spark state, measured over SSH rather than assumed: 121 GB usable,
114 GB in use, 6 GB free; the GGUF is 86.7 GB
(`IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8` — ~2-bit bulk with 8-bit attention
projections, shared experts and output), plus a separate 7.0 GB
`DSpark-drafter` for speculative decode. NVFP4 is roughly double that bit
budget, so this is a quality upgrade as well as a correctness one.

**Do not plan on FP8 or BF16.** At 284B those need ~290 GB and ~580 GB of
weights against ~242 GB usable across two Sparks. NVFP4 is the only format that
fits, which is why the recipe uses it.

Open items before committing: the RoCE/InfiniBand link between the two boxes
(the guide's earlier note assumed Ray; this recipe uses `mp` with NCCL), and
matching container images on both nodes. Acceptance test should be the schema
question, not tokens/sec — hand it `VisualMemorySelection.model_json_schema()`
and check whether `artifact_ids` comes back. If it does, the role pin above
becomes optional rather than necessary (though Qwen is still 25x faster for
these bounded calls, so keeping it is defensible on latency alone).

## The capability bullets now come from MainActionSelector — VERIFIED

`_build_system_prompt` no longer writes out what AniOS can do. Each built-in
action is one `BuiltinTool` row in `main_action_selector.py` carrying the tool
name, the schema, a conversational `label`, and the `description` — and that
one description string is both what the router is offered and what the reply
prompt is told, so the wording that governs conversation and the wording that
governs routing can no longer disagree. `describe_capabilities()` reads the
same `_available_builtins()` list `select()` offers, `ConversationService`
puts it in `context["capabilities"]` beside `context["agents"]`, and
`_render_capability_context` in `graph.py` renders it.

Two things deliberately did **not** derive:

- **Search.** Its offered description belongs to the live MCP contract
  ("Research a minimized public query with bounded free-provider policy") —
  the server's interface, not the product's capability — and reading it costs
  a `list_tools` session per turn. Its routing rule already lives in `_SYSTEM`
  rather than in a tool description, so `_SEARCH_CAPABILITY` is AniOS's own
  sentence, gated on `can_auto_invoke` (in-memory, no probe).
- **Documents.** Attaching a text file is read and indexed by the composer
  directly and is never a tool the router sees, so there is no row to read. It
  stays an unconditional line.

**No routing text changed, and that was proved rather than asserted:** an AST
comparison against `HEAD` shows all four tool descriptions and `_SYSTEM`
byte-identical, and the tool payload `select()` actually builds at runtime is
`json.dumps`-identical to the one `HEAD` builds, tool order included. So
routing behaviour cannot have moved — worth knowing before re-investigating
the selector's flakiness, below.

**Evidence.** Full backend suite (1173 tests, 8 new structural) passes; Ruff
and MyPy pass on every changed file. The functional suite
(`test_capability_awareness_behaviour.py`, 7 tests, 3 new) passes 3/3
consecutive runs against DeepSeek — the model that actually writes replies —
and 4/4 against the Qwen standby. Then the real deployed path: rebuilt
`backend`, recreated it, restarted `gateway` (401 not 502 through the gateway,
per the stale-DNS trap), and sent a real authenticated `POST /api/v1/chat`
through `deep-matter.com`'s gateway asking "What can you do with images?" The
reply named creating, editing, and diagrams, quoting the actual tool
descriptions back — "brand-new picture from a text description", "picture
currently in view", "not for documents, plans, or schedules", and the exact
six diagram kinds. That last clause is the tuned `edit_image` negative
reaching conversation for the first time.

**Measured, and worth not re-deriving.** A negative control ran the same three
questions with the capability list emptied. The picture test is a real
discriminator — 4/4 with the list, 0/4 and 1/4 without, across two batches.
The diagram test is not: "diagram" appears 3 times in 4 without the list
anyway. Tightening it to also require a kind AniOS actually draws discriminates
properly (14/15 with, 1/4 without) but flaked once in fifteen, so it was left
loose deliberately — a gate that fails 7% of the time gets ignored rather than
read, and the picture test already carries the proof. That reasoning is in the
test's own comment; do not "fix" it back without re-measuring.

**Flagged, not mine, and worse than recorded:**
`test_main_action_selector_behaviour.py` is materially flakier on Qwen (the
routing model) than the 24/24-across-six-runs this file records for the
opinion-question test. Five runs here: one clean, the others failing 1-3
parametrized cases, with a *different* subset failing each time
("what do you think, straw or cowboy?", "would the cowboy hat have suited me
better?", "should I go with the straw hat instead?", and the already-documented
"let's edit this project plan..."). Given the payload is provably identical to
`HEAD`, this is either model-side drift or the original 24/24 being a lucky
window. Worth a real repeat-count measurement before anyone tunes that prompt
again on the assumption it regressed.

## DeepSeek vs Nemotron 3 Super evaluated head-to-head — genuinely mixed, no winner picked — VERIFIED

**Decision still open, deliberately not made this session.** Both models
were run through the identical three-part evaluation (tool-calling battery
x3, search-routing benchmark, real reply latency) with results pointing in
different directions - full numbers in `ROADMAP.md` Milestone 9:

| | DeepSeek-V4-Flash (ds4-server) | Nemotron 3 Super (vLLM) |
| --- | --- | --- |
| Tool-calling (63 cases) | ~90%, real haiku/limerick gap | **98.4% (62/63)**, no bias found |
| Search-routing recall | **0.8519** (passes 0.85 floor) | 0.7931 (fails the floor) |
| Search-routing specificity | 0.9565 | 1.0000 |
| Avg total reply time | **31.9s** | 57.6s |
| Avg time-to-first-token | **~0.4-1.0s** | ~17s (4.5-34s, highly variable) |

Nemotron wins tool-calling clearly; DeepSeek wins both routing recall and
felt responsiveness (its TTFT advantage matters more for perceived
speed than raw decode rate does). Neither clears every bar. **Only one can
run at a time on this Spark** (both need most of its 128 GB) - currently
Nemotron is the one loaded and running; DeepSeek's `ds4-server` was
stopped and its crontab `@reboot` entry removed to avoid a memory conflict
if the Spark reboots while Nemotron's Docker container (which does have
`--restart unless-stopped`, so it survives a reboot on its own) is what
should come back.

Real compatibility finding worth remembering regardless of which model (if
either) is ever promoted: vLLM rejects AniOS's `reasoning_effort="none"`
default outright for Nemotron (`400`, `"Input should be 'low', 'medium' or
'high'"`) - `ROUTING_LLM_REASONING_EFFORT`/`MAIN_LLM_REASONING_EFFORT` would
need an explicit value for this model, not the blank default.

Also from this session: `MainActionSelector`'s tool-calling model and the
conversational-reply model can now be configured independently
(`ROUTING_LLM_BASE_URL` etc., default-unchanged, see the entry below) - so
whichever model (if any) eventually gets promoted for one role does not
have to be promoted for both at once.

## Routing/reply split built and real latency measured: ~5x slower — VERIFIED

**Next planned step, not started:** evaluate NVIDIA's own Nemotron 3 Super
(120B total / 12.7B active) as a DGX Spark candidate instead of continuing
to invest in DeepSeek-V4-Flash specifically. Real search found it officially
supported on Spark with native vLLM + NVFP4 (not a bespoke third-party
engine), right-sized for 128GB, and leading its size class on the
Artificial Analysis Intelligence Index — a lower-risk bet on paper than
DeepSeek's community-maintained `ds4-server`. Not yet installed or tested;
no tool-calling evidence exists for it the way there now does for DeepSeek.

**What shipped this round:** `MainActionSelector`'s tool-calling model can
now be configured independently of the conversational-reply model
(`ROUTING_LLM_BASE_URL`/`MODEL`/`REASONING_EFFORT` in
`backend/config/settings.py`, wired via `get_routing_llm_client()` in
`backend/core/dependencies.py`). Falls back to `MAIN_LLM_*` when unset, so
this changes nothing by default — full 1175-test suite confirms it. Not
deployed to `docker-compose.yml`; this exists so a main-model swap for reply
quality doesn't have to also inherit that model's untested tool-calling
behavior wholesale.

**Real latency measured**, not estimated: sent the same four realistic
conversational prompts through the actual `build_assistant_graph`/
`stream_chat` code path (the literal function that streams a reply to a
user) on both Qwen and DeepSeek-V4-Flash. **Average 6.4s vs 31.9s — roughly
5x slower**, ranging 3-10x by query; full table in `ROADMAP.md` Milestone 9.
Time-to-first-token stays close for both, so DeepSeek doesn't feel stuck at
the start, but the reply visibly crawls in afterward.

Verified DeepSeek's chain-of-thought does not leak into what streams to the
user - read `stream_chat` directly, confirmed it only ever reads
`delta.content`. Chased down an apparently-garbled character in the raw
output to the exact byte and found it was a Windows-console `print()`
encoding artifact in the measurement script itself, not a real defect -
worth remembering so this isn't re-investigated from scratch later.

**Where this leaves the decision**: DeepSeek-V4-Flash's tool-calling is
genuinely decent (prior entry) and the routing risk can now be engineered
around via this split - but a ~5x reply latency cost is a real, separate
problem the split does not solve, since it's the model *generating the
words the user watches stream in*. Whether that tradeoff is worth it is
still an open, undecided call - not resolved by this entry.

## DeepSeek-V4-Flash tool-calling evaluated directly — encouraging, not yet sufficient — VERIFIED

**The actual question behind the whole DGX Spark thread**: is this engine's
native tool-calling reliable enough to ever justify `MAIN_LLM_BASE_URL`?
Answered with real evidence, not inference from the (failed) presentation
attempt: a standalone script built a real `MainActionSelector` pointed
directly at the Spark's `deepseek-v4-flash` endpoint, never touching the
running app's config. Full numbers and reasoning in `ROADMAP.md` Milestone 9
and `CHANGELOG.md`; short version:

- Search-routing benchmark (Qwen's own 52-case, 0.85/0.75 floor): **recall
  0.8519, specificity 0.9565** — passes, recall by under one case's margin.
- Every tool call made was valid JSON, no exceptions — better-behaved than
  the presentation schema failure, which needed a complex nested schema
  rather than tool-calling's flat arguments.
- Found and fixed a real gap: "write a haiku about rain" called
  `generate_image` instead of just writing it. Fixed generically (poem/
  story/description all now correctly stay text), verified against the
  *live* Qwen model too with no regressions — this fix is real and kept
  regardless of what happens with DeepSeek. A more aggressive second attempt
  at the same fix was tried, made things worse elsewhere, and was reverted -
  worth remembering as a concrete example of the overfitting risk, not just
  an abstract warning.
- **Residual, disclosed gap**: haiku and limerick specifically stayed
  materially unreliable even after the fix (4/8 and 2/8), against ~100% for
  every other case. This looks like a strong, specific training-data prior,
  not a general problem — but it is real and unresolved.

**Net position**: more encouraging than the presentation result, on real
numbers rather than optimism, but not enough to promote to
`MAIN_LLM_BASE_URL` yet. The evidence base is single-digit repeats per case.
Next step, not yet started: more repeated runs for a real confidence
interval, and a judgment call on whether the haiku/limerick-class gap is
acceptable for a model that will field creative-writing requests routinely.

Evidence: full backend suite (1175 tests) passes; Ruff passes. New permanent
test (`test_a_request_to_write_about_a_visual_subject_does_not_generate_image`)
covers the reliably-fixed cases only, deliberately not the still-flaky ones.

## Presentation role reverted to Qwen; a real, pre-existing token-budget bug found and fixed — VERIFIED

**Read this first if the entry below (DeepSeek on the Spark) looks stale.**
The user's actual first real request through the DeepSeek-on-Spark setup
failed: `pydantic.ValidationError`, `extra_forbidden` on fields like
`statistic` (schema wants `statistic_value`/`statistic_label`) — the
model's JSON was well-formed, just not in AniOS's exact field names.
`PRESENTATION_LLM_BASE_URL`/`PRESENTATION_LLM_MODEL` are back on
`vllm-main`/`qwen/qwen3.5-4b` in `docker-compose.yml`. `MAIN_LLM_BASE_URL`
was never touched either way.

Regenerating the user's exact prompt against the reverted Qwen config to
confirm the revert worked **also failed, 2 of 3 attempts** — a different
symptom (truncated JSON), a different cause: `PRESENTATION_PLAN_MAX_TOKENS`
defaulted to 2,048, and this prompt's real outline needed close to that.
**This is a real bug that predates any Spark work** — it would have hit
Qwen alone, on the original deployment. Raised the default to 4,096 in
`backend/config/settings.py`; 3 of 3 identical attempts succeeded after.
Both fixes needed a full `docker compose build` (not just `up -d` — this
one is source code, `anios_backend` does not bind-mount) +
`docker restart anios_gateway` (per the stale-DNS trap two entries below),
verified through the actual gateway path each time this time, not a
container-internal shortcut.

Currently evaluating, separately, whether DeepSeek-V4-Flash's native
tool-calling is reliable enough to ever justify promoting it to
`MAIN_LLM_BASE_URL` — the user's own framing was "maximize the intelligence
of the main model and its subagents," and the presentation schema failure
is directly relevant evidence pointing toward caution there, not away from
it. Results not yet in as of this write-up; look for a following entry or
check `git log` if this note is stale.

Evidence: full backend suite (1175 tests) passes; Ruff passes. Verified
through the real `LLMPresentationProvider` code path at production
settings — 3 consecutive real generations of the exact prompt that
originally failed, not a mock or a single lucky run.

## DeepSeek-V4-Flash now serves AniOS's presentation role, on the Spark — VERIFIED

A DGX Spark joined the network (`spark-b524.local`, GB10, 128 GB unified
memory) alongside the RTX 5080 already serving `vllm-main`/`vllm-embedding` —
addition, not replacement. Full access, the dashboard tunnel, and the
DeepSeek-V4-Flash install/serving details (including two real bugs found and
fixed — loopback-only binding, no reboot supervision) are in
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md#available-hardware-nvidia-dgx-spark).
Full story and evidence in
[ROADMAP.md](ROADMAP.md#milestone-9-local-inference-on-the-dgx-spark--in-progress).

**What actually changed in the repo:** `docker-compose.yml` —
`PRESENTATION_LLM_BASE_URL`/`PRESENTATION_LLM_MODEL` now point at
`http://spark-b524.local:8888` / `deepseek-v4-flash` for the `backend`,
`presentation-worker`, and `local-capabilities` services. `MAIN_LLM_BASE_URL`
and `MainActionSelector` were deliberately left untouched — the risk there is
the routing regressions this session already spent significant effort
chasing on the RTX 5080's model, and that risk was not taken on today.

**Verified how, and how not:** not by checking the endpoint responds — by
running the actual `LLMPresentationProvider` code path
(`get_presentation_llm_client()`) and confirming it returns a real,
non-repeating, ungrounded-statistic-free 3-slide deck. Direct
`/v1/chat/completions` call also checked by hand to confirm no leakage from
an unrelated `base_instructions` field the `/v1/models` endpoint carries (a
Codex-CLI-compatibility feature of the serving engine, confirmed harmless —
detail in `DEVELOPMENT_GUIDE.md`).

**What was not done:** `qualify_models` was not run against this model, and
its tool-calling behavior has never been tested — the presentation role
never calls a tool, so nothing here says anything about whether this model
could ever safely sit behind `MAIN_LLM_BASE_URL`. Sustained/concurrent
throughput was not measured either, only a single cold request
(~5.7 tok/s decode) — real, but not necessarily the number under load.

## edit_image opinion-question fix broadened after a real recurrence — VERIFIED, residual gap disclosed

**Read this if a picture gets edited when the user only asked a question about it.**
The first fix (below) patched the exact reported phrase ("which hat do you
like better") and shipped. The very next report, "do you recommend a straw
hat instead?", was the same underlying bug in different words, and it still
fired `edit_image`. **The lesson, stated plainly because it nearly repeats:**
a functional test that passes on the one phrase from the bug report proves
nothing about the general case — verify a batch of differently-worded
phrasings together, not the reported one in isolation.

Rewrote `edit_image`'s tool description in `main_action_selector.py` around
the actual rule (a question is never an instruction, no matter what
alternative it names) instead of enumerating comparison phrasings, and
added a parametrized test with four different opinion phrasings that must
*all* pass together. Result: 24/24 across six independent runs (up from a
single reported phrase). While iterating, discovered — via `git stash`
against the wording already live, not something this session introduced —
that "let's edit this project plan to push the deadline back a week" was
already misfiring into `edit_image` about half the time, unrelated to the
opinion-question bug. Reduced to roughly 1/6 with an explicit "even when no
other tool fits — answer directly instead of calling any tool" clause, but
**not eliminated**; expect this exact phrasing to resurface. Also: the
search-routing recall floor test failed once mid-iteration, then passed
clean on three immediate reruns with nothing changed — treated as noise
near this benchmark's known floor, not a regression, but flag it if it
recurs since the two look identical in a single run.

Full backend suite (1175 tests) passes; Ruff passes. No frontend change, so
only `docker restart anios_backend` was needed, not a gateway rebuild.

Separately, confirmed (not this session's doing) that the user's own browser
called `DELETE /api/v1/memory/ani.mallya` around 21:10 UTC on 2026-08-13,
wiping that account's full conversation/memory/artifact history — verified
via the gateway's real access log (genuine Chrome UA, real external IP, not
test traffic). Worth knowing if a "wipe memory" UI action is meant to be
scoped to memory only: the endpoint (`DELETE /api/v1/memory/{user_id}`,
`backend/memory/repository.py::delete_all_user_memory`) also deletes the
`conversations` table for that user, i.e. full chat history, not just
recall facts. Not changed this session since it wasn't confirmed to be
unwanted behavior — flagging for a product decision, not filed as a bug.

## An edit no longer echoes an unasked description, and stopped re-editing on an opinion question — VERIFIED (mostly)

**The description leak** was reported live: "can you edit this to a straw
hat?" edited cleanly, but also surfaced an unrequested "Describe this image"
card underneath it. Root cause: `ImageRefinementService.refine` calls
`VisionAnalysisService.observe_artifact` after every edit purely so the
revision stays semantically findable (this was added in an earlier session
to fix edited images being unrecallable) — but that write lands in the same
`metadata.analysis` key the *upload* flow uses when the browser's
caption-less default question is answered, and the frontend's
`readAnalysisThread` legacy fallback (`frontend/src/services/api.ts`) cannot
tell the two apart: `analysis` set with no `analysis_thread` always renders
as a "Describe this image" card. Fixed by marking the reindex-only write
`analysis_user_facing: false` and having the frontend check that flag before
falling back to the legacy display. Confirmed with a real repro: the new
Playwright test fails against the unfixed `api.ts` (analysis text visible)
and passes against the fix; `test_vision_memory_indexing.py` asserts the new
flag directly.

**The re-edit-on-opinion bug**: pulled the actual trace (conversation
`3d463775`, 2026-08-13 19:51–19:54) straight from the database rather than
guessing. After the model described a black cowboy hat and it was edited to
straw, "amazing! which hat do you like better for this outfit?" made
`MainActionSelector` choose `edit_image` again, synthesizing a paraphrased
instruction ("Replace the black cowboy hat with a straw hat") that silently
redid the same edit — the response was "Here's the edited image.", not an
answer to the comparison. The user resent the identical message 8 seconds
later and that time got a real comparative answer, once the botched edit was
sitting in history. **Worth remembering:** my first guess at which tool
misfired was wrong — I assumed `generate_image` from "it starts regenerating
another image," wrote a description fix and a test for that tool, and only
the direct database trace (`extra_data.refinement_feedback` on the two
generated-image rows) showed it was actually `edit_image` re-firing. Reverted
the `generate_image` change before committing. Clarified `edit_image`'s own
tool description (not the shared `_SYSTEM` prompt, per the established
lesson that widening that degrades search-routing recall) to exclude an
opinion/comparison/preference question about the picture, even when it names
the same subject a recent edit changed. **Caveat, same shape as the location
fix below:** a functional test replays the live trace verbatim, but could
not be forced to fail again against the unfixed description (12/12 passed)
— treat as a sound, best-effort guardrail, not a proven fix, if this
recurs. The full `test_main_action_selector_behaviour.py` suite (17 tests,
including the search-routing recall floor) stayed stable across three runs
with the fix in place.

Evidence: full backend suite (1175 tests) passes; Ruff passes on every
changed file.

## The gateway was a day-stale static build; recall showed one photo three times — VERIFIED

**Read this first if a "fixed" frontend change is reported as not working.**
`gateway` (port 8080, what the tunnel/deep-matter.com actually serves) bakes
`frontend/dist` into its nginx image once at Docker *build* time and never
watches the source tree again — `docker restart` or `up -d` alone changes
nothing. It was found a full day stale, meaning an entire session's worth of
frontend fixes had been invisible to the user throughout, and every hard
refresh they tried was correctly fetching fresh bytes of the same stale
build (`Cache-Control: no-store`, so it was never a browser-cache problem).
Redeploy with `docker compose build gateway && docker compose up -d
--no-deps gateway`, and verify with content, not timestamps —
`docker exec anios_gateway grep -l "<string only in new code>"
/usr/share/nginx/html/assets/*.js`. Documented in `AGENTS.md`'s Operational
traps. Separately, even after a real gateway rebuild, one more report turned
out to be a stale open *browser tab* specifically (confirmed by reading the
exact persisted response text back out of the database, which proved the
extra text the user saw was never generated server-side) — a tab keeps
running its already-loaded JS regardless of the server, until it is actually
reloaded.

With the deploy pipeline no longer the confound, a real bug surfaced:
asking a style question recalled the same uploaded photo three times as
three separate "matches." Not a selection bug — the same file had genuinely
been uploaded across three separate conversations while testing, so three
real, independent, `sha256`-identical rows all legitimately matched. Added
`collapse_duplicate_content` in `backend/artifacts/image_lineage.py` (a
sibling to the existing `collapse_revision_chains`, but for independent rows
provably the same file rather than a parent/child edit chain) and wired it
into both image-recall paths. Full backend suite (1175 tests, 5 new) passes;
Ruff passes. No frontend change this round, so no gateway rebuild was
needed — only `docker restart anios_backend`.

## Dark-mode white bar fixed; the model stopped inventing a location — VERIFIED

Two more reports from the same live-testing thread. **The dark-mode bug** was
a real gap in `theme.css`'s hand-maintained `.dark` overrides: an
opacity-suffixed colour (`bg-[#f5f5f7]/90`, the composer bar's blur
background) and a `hover:`-prefixed one each compile to their own distinct
Tailwind class, so mapping the plain colour does not cover them — the
composer bar stayed solid white. Fixed both, swapped two more unmapped
colours for already-covered equivalents, and added a `theme.spec.ts` test
that reads the actual computed `background-color` (confirmed it fails
unfixed first). **Worth remembering:** this hand-maintained file's own header
comment claims "a test reads the palette, scans the components, and fails
when one is unmapped" — that test does not exist anywhere in the repo. Any
new arbitrary-colour Tailwind class, especially with an opacity suffix or a
`hover:`/`focus:` prefix, should be checked against `theme.css` by hand until
that real generator/validator gets built.

**The location hallucination** ("Do you have a preferred proximity to a city
(like Milwaukee, where you seem based)", asked of a freshly wiped account
with zero stored profile/facts/locality and no search having run) was traced
conclusively to the text-generation call itself, not routing — confirmed via
the trace (no search call) and the database (no stored fact named a city).
Added an explicit instruction to `_build_system_prompt` in `graph.py`: never
present a guess about the user's own personal facts as if it were known.
**Caveat, stated plainly:** the new functional test
(`test_it_does_not_invent_the_users_location`) could not be made to
reliably fail against the unmodified prompt (4/4 attempts passed) — this
looks like real-model non-determinism at the edge of a large shared prompt,
not something fully under this repo's control. The instruction is kept
because it is a sound guardrail on its own merits, but treat this fix as
best-effort, not proven, if the report recurs. A genuine side effect:
`test_style_opinion_applies_the_edit_to_the_source_description`, previously
`xfail(strict=True)` for a known Qwen limitation, now XPASSes consistently
(3/3) — the xfail marker was removed.

Also confirmed (no code change) that the earlier `/images/intent` bypass and
stale-`artifact_started`-validation reports are both actually resolved on
current code — a fresh trace for a repeat of the same message went through
`/api/v1/chat` correctly end to end. Remaining sightings of either are a
stale browser tab, not a live bug.

Evidence: full backend suite (1170 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes; `theme.spec.ts` (6 tests, 1 new)
and a full `chat.spec.ts` run (56/59, same three pre-existing failures
confirmed via `git stash`) both pass.

## Recalled photos display compactly; editing explains a missing target — VERIFIED

Direct follow-up feedback on the same day's "keeps showing the image" fix
below: the dedup was the wrong fix. The user's actual complaint was the
*size* of the card, not the repetition — "is it feasible to have it show 1
matching image every time it references it? the uploaded image card is
huge." Reverted the dedup entirely (`freshly_shown`, `_resolve_display`,
`_render_image_prompt_context`, and their tests all removed) and instead
gave `ImageArtifact` a `compact` prop: a recalled match now renders as a
small thumbnail chip that expands to the full 620px card with its
download/retry/delete toolbar on click, and collapses back on demand. Only
`MessageBubble.tsx`'s `imageMatches` path uses it — a freshly generated,
uploaded, or edited picture still shows full-size immediately, per the
user's own framing ("the image comes with the full llm response on the
first time the image was created").

Two more real bugs surfaced in the same exchange, both fixed:

1. **Deleting an image silently disabled auto-follow for the rest of the
   conversation.** `handleVisualDeleted` reset `selectedImageId` to `null`
   when the deleted image was the active one — the same value a deliberate
   "clear image context" click uses (see the comment at its declaration:
   "null records that the user deliberately cleared image context").
   Deletion is not that choice. Changed to `undefined`, which resumes
   following the newest visible image automatically. Verified end-to-end in
   `chat.spec.ts`'s `keeps auto-following the newest image after deleting
   the active one`: generate, delete, generate a second image, ask a
   followup — the second image's id reaches `active_image_artifact_id`
   without any click.
2. **An edit request with nothing selected answered as if it were never
   asked.** `edit_image` was only ever offered to the model when the
   frontend already had an active image, so a message like "make it black
   and white" with nothing selected fell straight through to an ordinary
   reply that never mentioned a picture — reading as the feature being
   broken. `edit_image` is now offered every turn; `ConversationService`
   checks the real selection itself (the model cannot) and, when the model
   judged this an edit but nothing is active, replies with explicit
   guidance instead of guessing.

That second fix needed two real-model-measured prompt iterations, both
worth remembering for next time:

- A wordy exclusion example added to the *shared* `_SYSTEM` prompt fixed a
  genuine false positive (the real model calling `edit_image` on "edit my
  resume to remove my last job") but measurably dropped the search-routing
  benchmark's recall to 0.79 against its 0.85 floor. Confirmed causally: the
  clean tree passed, restoring the addition reproduced the drop. **Lesson:**
  this selector makes one shared decision from one shared prompt across
  every action; adding text to one tool's guidance can silently degrade an
  unrelated tool's accuracy, even in a short, seemingly-isolated addition.
- Moving the identical clarification into `edit_image`'s own tool
  `description` field (not the shared instructions block) fixed the false
  positive with no measurable effect on search routing — three consecutive
  real-model benchmark runs all passed. Prefer the tool's own description
  field over the shared system prompt when a per-tool correction is needed.

Evidence: full backend suite (1170 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes; non-live `chat.spec.ts` (59
tests, two new) passes. New real-model functional tests:
`test_an_edit_request_with_a_recent_picture_chooses_edit_image` and
`test_an_unrelated_edit_request_does_not_choose_edit_image` in
`test_main_action_selector_behaviour.py`, run 3x for the search-routing
benchmark specifically to confirm the fix held. Four pre-existing e2e
failures (dark-mode color assertion, diagram-reload timeout, one flaky
`net::ERR_FILE_NOT_FOUND` console error, a "Sign out" click racing a
detached DOM node) confirmed present on unmodified `HEAD` via `git stash`
and unrelated. Diagram impact: NONE — internal refinement to existing
components, no new component/store/boundary.

## Chat memory proposals auto-save; a recalled photo stops repeating — VERIFIED

Two independent requests this session: "automatically save things about a
user in memory without asking them... it may become bothersome" (design
decision: blanket auto-save, chosen over tiered-by-confidence when offered
the choice), and, from a live look at `ani.mallya`'s real conversation
history, "it keeps showing the image every time it says it recalls it" plus
a reported "Artifact start event is invalid" error.

**Auto-save.** Every proposal `MemoryProposalAgent` classifies from a chat
turn is now persisted by `ConversationService._persist_memory_proposals`
immediately, before the reply is generated — no approval round-trip, for any
of the nine kinds the agent actually emits (`preferred_name`,
`response_style`, `discovery_locality`, `discovery_interests`, `entity`,
`procedure`, `knowledge`, `semantic_fact`, `episodic`). A dispatch table
(`self._memory_proposal_savers`) maps each kind to its own `_save_*_proposal`
method, mirroring the exact calls the retired REST approval endpoints used to
make (`approve_preferred_name`, `approve_fact`, `approve_discovery_interests`,
`save_semantic_memory`, `save_episodic_memory` on `MemoryService`;
`entities.upsert`, `procedures.approve`, `knowledge.ingest` on
`AgentMemoryManager` — newly wired into `ConversationService` as
`agent_memory`, since it had no reference to it before and entity/
procedure/knowledge proposals had no persistence path at all). A per-item
save failure is caught, logged, and dropped — it costs only that one
candidate, never the turn's answer or any other candidate saved alongside
it (covered by `test_conversation_service_a_failed_save_does_not_block_the_rest`).
`_render_save_state` in `graph.py` now tells the model "the following was
saved" instead of "a save card is displayed, nothing is stored yet" —
verified against the real model in `test_memory_save_state_behaviour.py`,
which took two prompt revisions: the first "nothing was saved" wording still
produced "I've noted that ..." from the real model despite an explicit ban
on the word, and needed a worked positive/negative example to actually hold.
The frontend's whole approve/reject queue was removed (`ChatWindow.tsx`:
`saveMemoryProposal`, `approveMemoryProposal`, `approveAllMemoryProposals`,
`rejectMemoryProposal`, the turn-based retirement grace period and its
`turnRef`; `api.ts`: the ten `approve*` REST wrapper functions) and replaced
with a read-only "Saved X as Y memory" notice that clears on the next
question — nine `chat.spec.ts` tests were rewritten from
approval-button-click assertions to auto-save display assertions.

**Repeated image display.** Root cause, found by decrypting and reading
`ani.mallya`'s actual conversation rows in the dev DB (read-only, via the
running backend's own `FieldCipher` — see `backend/core/crypto.py`):
`_load_visual_memory_matches` is a real semantic-recall model call (not
regex) that correctly judges relevance on every turn merely *about* what a
stored photo shows — so a multi-turn conversation about one outfit
re-attached the same photo to almost every reply, true in isolation, noisy
in aggregate. Fixed in `_stream_retrieved_context`
(`conversation_service.py`): that semantic-fallback path is now deduplicated
against artifact ids this conversation already displayed, tracked via the
persisted turn's `extra_data.artifact_ids` (a new `context["shown_image_ids"]`
side-channel carries this from retrieval to the persist call). An explicit
recall ("show me that photo again") is never deduplicated — only the
soft/incidental path is. Each prompt image now carries a `freshly_shown`
flag; `_render_image_context` in `graph.py` was updated so the model never
claims a picture "just appeared" when it is a repeat.

**"Artifact start event is invalid".** Already fixed by the prior session's
`d849522` (widened the frontend's `artifact_started` kind validation to
accept `generated_image`, not only `diagram`). Confirmed live in the running
dev container: `docker exec anios_frontend` showed `api.ts`'s mtime already
reflected the fix before the reported chat turns happened. No new code
needed. If it recurs, it is almost certainly a stale browser tab from before
that fix — a hard refresh should clear it.

**Resolved since:** the regex-plus-classifier `CascadingImageRecallRouter` and
`ImageRecallPolicy` have been removed from the live path and repository. One
structured `ArtifactContextRouter` decision now runs before either the aligned
pixel-vector lookup or description-vector fallback, so an ordinary turn makes
one modality decision and private candidates load only when it returns image.

Evidence: full backend suite (1170 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes; the non-live `chat.spec.ts` suite
passes (57 tests), including the nine rewritten memory-proposal tests and a
new `clears the saved-memory notice on the next question` test; three
pre-existing failures (a dark-mode `shellBackground` color assertion, a
diagram-restore-after-reload timeout, one flaky `net::ERR_FILE_NOT_FOUND`
console error) were confirmed present on unmodified `HEAD` via `git stash`
and are unrelated. `docs:diagram:check` reports all 19 diagrams
synchronized after editing `memory-overview.mmd`, `memory-subsystem.mmd`,
`chat-orchestration.mmd`, and `agent-memory.mmd` to remove the retired
"visible approval"/"Consent" gate nodes. Committed as `660229a` (image
redisplay fix, pushed) plus the auto-save change (commit pending at time of
writing — see git log for the actual SHA once pushed).

## Turn routing became one native tool-calling decision — VERIFIED

Two reports started this: a "suggestions for a bachata event tonight" request
returned results from unrelated cities with no location ever asked for, and a
"can you make me wear a straw hat here?" edit changed the picture with no
reply and no trace in conversation history. Both traced to the same root
cause — search routing, diagram detection, presentation delegation, and image
generation were each decided by a separate deterministic gate (a
regex-plus-classifier cascade, two plain regexes, and a browser-side keyword
regex) running before the model that actually answers the user ever saw the
request, and image generation/editing were client-triggered REST calls
invisible to `conversations`.

`MainActionSelector` (`backend/services/main_action_selector.py`) replaces all
four with one native tool-calling decision made by the main model itself:
`search_web` (live schema, model-authored query), `generate_image`,
`edit_image` (offered only with an image in view), `create_diagram`,
`delegate_to_presentation_agent`, and the user's own semantically shortlisted
MCP tools, offered together in a single `chat_with_tools` call. It refuses to
act on any name that round did not actually offer — defense against a
malformed or unexpected provider response, not just an offline concern.
`ConversationService.process_request` now calls it once and dispatches;
`generate_image`/`edit_image` run inside the chat stream through the same
`ImageArtifactService`/`ImageRefinementService` the retired REST endpoints
used, emitting the same `artifact_started`/`artifact_ready`/`artifact_error`
lifecycle a diagram already used — so the exchange is persisted and an edit
gets a visible reply where it previously got neither.

The routing prompt explicitly tells the model not to guess a missing personal
detail (concretely, location) and call the tool with an assumption; it should
call no tool instead, so the reply can ask. This is model behavior, not a
separate feature — there is no code path that detects "location is missing"
outside the model's own judgement in that one decision.

Evidence: the full backend suite (1166 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes for the frontend. Thirteen functional
tests (`backend/tests/functional/test_main_action_selector_behaviour.py`) ran
against the real vLLM runtime and the real `internet` MCP server (spawned
live, no mocks) and all thirteen passed, including a labelled-benchmark test
that holds the new decision to the exact recall/specificity floor
`evaluate_search_routing.py` already held the retired cascade to. That test
failed on its first real run — recall 0.759 against a 0.85 floor, missing
implicit-officeholder questions like "who is the prime minister of Canada" —
which is the kind of thing this rule exists to catch; naming that category
explicitly in the prompt and telling the model to prefer calling the tool
when genuinely unsure fixed it. The non-live browser suite (61 tests) passed
against a real Chromium instance and a real frontend dev server, including
every image-generation/edit test rewritten to mock the chat SSE stream
instead of the retired direct REST calls. One of those rewrites caught a real
bug before it shipped: the stream parser rejected any `artifact_started`
`kind` other than `"diagram"`, which would have broken every chat-initiated
image turn in the browser. Five pre-existing browser-suite failures
(a theme/color assertion, a diagram-reload timing test, and three
`presentations.spec.ts` tests) were confirmed present on unmodified `HEAD`
via `git stash` and are unrelated.

Known unverified: the three `@live` image tests that exercise real ComfyUI
generation were mechanically updated to the new event-stream shape but could
not be run in this environment — ComfyUI was not started (GPU-backed, profile
-gated). They are updated in good faith, not exercised. A single combined
real-browser-to-real-backend run (as opposed to a real browser against a
mocked backend, and the real backend against a real model via the functional
suite separately) was not performed either: `AUTH_REQUIRED=true` on the live
account and no credential was available or attempted, correctly.

Retiring the client-side routing surfaced a second gap while adapting its own
test: chat-initiated image generation had no way to be cancelled mid-flight,
because the "Cancel visual request" button and its `AbortController` were
wired only to the retired client-triggered visual paths. Fixed by threading
an `AbortSignal` through `streamChat` and widening the composer's cancel
affordance to any in-flight chat request, not only the old visual ones.

A third fidelity gap surfaced while updating `DEVELOPMENT_GUIDE.md`, not by a
test: chat-initiated generation/edit failures used a generic message instead
of naming an unreachable ComfyUI specifically, which is exactly the failure
this repository's own operational notes warn reads as a declined request
rather than an outage. `_image_provider_failure_message` in
`conversation_service.py` now matches the retired REST endpoints' wording.

`MainSupervisorAgent`, `DelegationRegistry`, `CascadingSearchRouter`, and
`SearchRoutingPolicy` were left in the tree at the time, still tested
standalone but unreachable from a live turn. They have since been deleted
along with their tests and `evaluate_search_routing.py`; the labelled set they
were scored on (`backend/search/routing_cases.py`) was kept and now measures
the tool selector instead.

Diagrams: `chat-orchestration.mmd` redrawn around `MainActionSelector`, plus
the generated architecture page's metrics strip and orchestration-contract
paragraph. `visual-artifact-subsystem.mmd` deliberately left unchanged — its
"Owned visual API" boundary and internal relationships did not change, only
who calls into it. `npm run docs:diagram` regenerated all 19 SVGs and
`architecture.html`; `npm run docs:diagram:check` confirms the full set and
the published page are synchronized.

## Delete all personal memory now removes visual artifacts — VERIFIED

The reported failure reproduced with a disposable owner and a real stored PNG:
`DELETE /api/v1/memory/{user_id}` returned 200, reported no artifact count, and
left both the `visual_artifacts` row and opaque file reachable. The first
failing boundary was the memory endpoint, which coordinated personal, agent,
tool, conversation, and discovery deletion but never invoked artifact
lifecycle cleanup.

The endpoint now calls a lightweight `ArtifactDeletionService` after its memory
stores are cleared. PostgreSQL deletes and returns every owned visual-artifact
storage key, including rows without files such as diagrams; the service removes
the corresponding opaque files and surfaces incomplete filesystem cleanup
instead of falsely reporting success. Derived visual semantic records are also
removed, and the response names the `artifacts` count. Cross-user tests prove
another profile's artifact row and file remain intact.

Evidence: 24 focused memory, artifact-lifecycle, discovery-coverage,
agent-memory, and authorization tests pass; Ruff passes; the frontend production
build passes. A rebuilt backend (`personalassistant-backend`, manifest
`05c24d1f998e...`) was exercised with one owner and one control user: the owner
changed from one artifact/file/visual memory to zero, while the control stayed
at one artifact and one file. Backend logs show the exact DELETE and follow-up
reads with no exception. A real Chromium run through `https://deep-matter.com`
uploaded a valid PNG, clicked **Delete all personal memory**, received 200 with
an artifact count, rendered the empty memory state, and observed an empty
artifact API with no Console or page errors. All 19 canonical diagrams and the
published architecture page are synchronized.

Known unrelated validation failure: a focused MyPy invocation still reports
the existing Pillow `LANCZOS`, conversation-service `Any`/optional embedder, and
reaction-callback typing errors outside this change. It is not counted as a
passing static gate.

## Visual style memory survives tab and conversation context — VERIFIED

The exact `ani.mallya` question **how do you feel about my dress style?** twice
received a denial even though the uploaded portrait had a stored Qwen analysis.
The first failing boundary was the derived semantic shortlist: eight visual
memories whose artifact rows had already been deleted ranked ahead of the live
portrait. The semantic selector chose a relevant outfit description, but the
required owner/readiness check rejected its missing handle, leaving generation
with no image context.

Visual-memory retrieval now joins each derived description to a ready image
artifact owned by the same user before applying its result limit. Artifact
deletion also removes its matching derived analysis row in the same PostgreSQL
commit. Existing orphan rows are therefore inert without destructively changing
the user's database. The image-memory prompt now answers appearance and style
opinions directly from recalled evidence while treating one outfit as evidence,
not a permanent wardrobe preference.

The same investigation exposed that the straw-hat child had never been observed
after FLUX finished, so its current pixels had no analysis of their own. Image
refinement now sends the ready child to local Qwen vision, stores the child's
analysis, and indexes that current description. A VLM failure preserves the
valid edit and logs the degraded state. The text-lineage fallback remains a
recorded `xfail`: Qwen can still prefer the origin's black-hat description over
an explicit straw-hat delta when no child observation exists.

Evidence: 34 focused repository, indexing, context, refinement, and real-Qwen
tests pass, with one strict `xfail` for the documented no-observation fallback.
The passing real-Qwen coverage includes semantic portrait selection, unrelated
query rejection, lineage, and exact style-opinion behavior. After rebuilding
backend image `9f817189f639...` and restarting the gateway, a direct authenticated
chat request with no active image ID emitted `image_matches`, described the
black cowboy hat, dark blue bomber jacket and white T-shirt, and terminated with
`done`. An authenticated Chromium run through `https://deep-matter.com` restored
the owned edited image, sent its exact artifact ID, rendered a grounded style
answer, cleared loading, and completed without Console or required-Network
failures.

Live refine-observe acceptance then created temporary child
`436002dc-c5aa-4253-b46b-c2cf9b3d4bf0` in 35 seconds. FLUX returned ready
pixels, Qwen stored a current analysis naming the wide-brimmed straw cowboy hat,
dark bomber jacket and white shirt, and direct chat answered from those current
details. The public Chromium path passed with that exact child selected. Deleting
the temporary child returned 200 and atomically changed both its artifact count
and derived semantic-memory count from one to zero.
The user's existing straw-hat child
`24970e16-006f-46a9-b10e-74b891fcbe0f` was then observed once through the same
Qwen boundary so it is no longer a legacy unobserved revision. Its current
analysis names the straw hat, dark bomber jacket, white shirt and waterside
sunset; the exact style question now answers from those details, and the public
Chromium path passes with that artifact selected.

## One image target in the main composer — VERIFIED

The image card's persistent follow-up textarea was removed. The newest visible
image now appears as a removable thumbnail reference above the main composer,
and every visible image exposes **Ask or edit** so the user can explicitly
switch the target when several images exist. Questions stream through `/chat`
with that exact `active_image_artifact_id`; edit-shaped instructions use the
same selected source and replace its visible card with the immutable child.
Clearing the reference sends `active_image_artifact_id = null`.

The explicit selection is an override, not the memory design. When no artifact
is explicitly supplied, owner-scoped semantic visual candidates may be selected
by the bounded Qwen visual-memory policy and are owner/readiness checked again
before their descriptions and lineage enter the answer prompt. The durable
target is type-neutral: generated, uploaded, or discussed artifacts share an
owned handle, provenance and derived semantics; video observation and parsed
PDF/RAG chunks remain planned additions to that contract.

Evidence: five focused Chromium image workflows pass, including two-image
selection/switch/clear, exact request-body IDs, ordinary questions, and
generated/uploaded refinements. The frontend production build passes. A broad
67-test Chromium run produced 61 passes and six unrelated failures in existing
authentication/theme/navigation tests; rerunning those six serially reproduced
them, so the broad suite remains `FAILED` and is not attributed to this image
change. All 19 canonical diagrams and the published architecture page were
rendered and synchronized after updating the three affected views.

The first public deployment check was insufficient: `deep-matter.com` returned
200, but the six-hour-old gateway image still served `index-C6UAPirx.js`, which
contained the removed follow-up box. The Vite frontend container had the new
source, but Cloudflare never points at port 5173; it points through the named
`anios` tunnel to the gateway's compiled bundle on loopback port 8080. The
gateway was rebuilt and recreated. Both published Cloudflare IPv4 addresses now
serve `index-DdjG7VDH.js`; that exact public asset contains **Ask or edit** and
**Using in chat**, does not contain **Ask about or refine this image**, and is
returned with `Cache-Control: no-store` plus Cloudflare `DYNAMIC/BYPASS` status.
An authenticated Chromium session then opened `https://deep-matter.com`,
restored the owned uploaded image, displayed the main-composer image reference,
sent the exact artifact ID to `/api/v1/chat`, received a grounded style answer,
terminated streaming, and cleared loading with no Console, page, or required
Network failures. The test's short-lived bearer is scoped to `/api/` requests
so Cloudflare-injected third-party assets never receive it.

The exact `ani.mallya` refinement **can you make it a straw hat instead?** then
exposed a separate terminal-state defect. Artifact
`24970e16-006f-46a9-b10e-74b891fcbe0f` became ready and replaced parent
`5276e37b-2efc-4203-825b-b78ac8c977db`, and the refine request returned 201,
but the browser retained the independent **Creating your image locally.** /
**Generating image...** placeholder. Refinement completion now removes exactly
the newest matching generation placeholder, and ready image cards replace
transient starting copy with **Image ready.** or **Image updated.** Two focused
Chromium workflows pass for generated and uploaded refinements, including
terminal copy, cleared activity, and an enabled composer. The production build
passes, and both public Cloudflare edges serve the rebuilt bundle containing
those terminal states with `Cache-Control: no-store`.

Next atomic task is to repair the
browser suite's auth/theme isolation before treating its broad result as a
clean regression gate.

## Documentation reconciled with the code — VERIFIED for the docs, INHERITED for the rest

An audit of the agent documentation against `HEAD` found six drifts, all now
repaired. They are listed because most were introduced by the very commit that
changed the thing they describe — the code and one document moved, and the
neighbouring document did not. That is the pattern to watch for:

- `AGENT_CATALOG.md` still called the diagram agent's tests `xfail` and its
  defect "intermittent", in the same file whose later section already recorded
  the fix. The commit that fixed the defect updated the new table and left the
  agent's own section behind.
- The diagram catalog said Scout's model decides "only how a find reads", three
  commits after it started aiming search subjects and reranking shortlists. The
  `.mmd` was updated; the row above it was not.
- Scout's and memory capture's rows omitted
  `test_timezone_prompt_behaviour.py` and `test_interest_capture_behaviour.py`.
  A catalog under-reporting its own functional coverage is the wrong direction
  to be wrong in, given that a prompt without one is an untested feature.
- `ARCHITECTURE.md` listed three agent folders where there are four, and
  described the published page as 15 canonical views when 19 sources exist.
- The four agent diagrams were registered in the renderer and the catalog but
  never added to `architecture-page.mjs`, so no agent view was reachable from
  the manager-facing page while its own metric read `15 / 15 synchronized`.

All 19 views are now published. The count is read from the `.mmd` files on disk
rather than hardcoded, and folded into the page fingerprint, so a diagram added
to the catalog and not published now fails `docs:diagram:check` instead of
leaving the page printing a reassuring number.

Evidence from this session: `npm run docs:diagram` rendered 19 diagrams and the
page; `npm run docs:diagram:check` reports **19 architecture diagrams are
synchronized** and **Published architecture page is synchronized**; the four
`agent-*` sections and the `19 / 19` metric are present in `architecture.html`.

Everything else recorded below and in the changelog for 2026-08-10 is inherited
from the commit record rather than re-verified here — no backend suite, browser
session, or model run was executed in this session. The next task that touches
runtime behavior should re-establish its own evidence rather than trusting this
line.

Known and deliberately unrepaired: asked for a **state machine** the diagram
agent returns `"source": "stateDiagram-v2"` with no body. Flowcharts, which is
nearly every request, run 6/6.

Next atomic Scout task remains the Mac recipient-grant repair described below.

## Memory meaning is selected semantically, not by regex — VERIFIED

The first fix for `hi my name is Jen and i like acting, theater, networking
events` bounded a preferred-name regex. That contradicted the established
requirement that memory understand the user's meaning rather than accumulate
phrase rules. The production regex proposal module and its tests have now been
removed.

One local `MemoryProposalAgent` backed by `qwen/qwen3.5-4b` reads the whole
current utterance and returns grammar-constrained typed candidates for preferred
name, response style, locality, interests, entity relationship, workflow,
titled reference, semantic fact, and episodic event. Application code only
validates bounds and safe field shapes, attaches conversation/trace provenance,
and routes visible user approval; the model still has no persistence authority.
Profile facts may coexist, while general memory keeps one best candidate to
limit noisy proposals. The previous dedicated interest agent was removed.

Real Qwen evidence:

- the exact reported sentence returned `preferred_name = Jen` and `acting`,
  `theater`, `networking events`;
- `Everyone knows me as Jen. Stage performance and professional mixers are my
  thing.` returned the same preferred name and semantically mapped the interests
  onto the existing `testuser` labels instead of creating duplicates;
- `Would someone named Jen enjoy theater?` returned no proposal.
- the first semantic-fact rehearsal exposed an over-conservative/misclassified
  pet fact; after tightening the semantic contract, three different ways of
  saying the dog is called Biscuit all returned `semantic_fact`, `I love
  training dogs` returned only interest `dog training`, and the dog-name
  question still returned nothing.

The rebuilt backend and real authenticated Chromium path as `testuser` showed
both exact proposals, **Approve all 2** issued preferred-name 200 and interests
201, and readback returned `Jen` plus all three interests. Loading cleared, the
composer re-enabled, and browser Console, page, failed-network, and backend
exception checks were empty. The container received the increased 256-token
structured-output budget.

- Regression: 82 focused backend tests pass; Ruff passes; two focused
  Playwright tests and the frontend production build pass; 17 architecture diagrams
  and the published architecture page are synchronized.
- MyPy reached two pre-existing errors in `backend/discovery/link_graph.py`.
- Next atomic Scout task remains the Mac recipient-grant repair described below.

## One introduction now captures name and Scout interests — VERIFIED

The exact `testuser` message `hi my name is Jen and i like acting, theater,
networking events` exposed two boundaries. Preferred-name extraction consumed
the following `and I ...` clause, producing `Jen and i like acting`, and the
conversation service allowed only one memory proposal per turn, so that bad
name proposal suppressed the semantic interest result. The focused Qwen
classifier itself was correct and returned `acting`, `theater`, and `networking
events` before any code changed.

Name extraction now ends before a following `and I` or `but I` clause. A chat
turn may emit every compatible profile proposal (name, response style,
locality, and Scout interests), while general semantic/episodic memory keeps
the existing single-best rule. The frontend queues the streamed proposals so
each remains independently approval-gated rather than the last event replacing
the first.

The backend image was rebuilt from the working tree, `backend` was recreated,
and the gateway restarted. Through the real authenticated HTTP path as
`testuser`, the exact message streamed `preferred_name = Jen` followed by the
three Scout interests; approvals returned 200 and 201. Readback returned
profile name `Jen` and all three interests. A real headless Chromium session as
`testuser` rendered both cards in order, approved them, cleared the queue and
loading state, and recorded no Console, page, or failed-network errors. Backend
logs contain the chat and both approval requests with no exception.

- Regression: 72 focused backend tests pass; Ruff passes; three focused
  Playwright proposal regressions pass; the frontend production build passes.
- `FAILED` validation command: a broad title-based Playwright grep did not
  finish within 180 seconds and emitted no result. This does not invalidate the
  exact deterministic browser test or the real integrated Chromium acceptance,
  both of which passed.
- Next atomic Scout task remains the Mac recipient-grant repair described below;
  after delivery is verified, add deterministic geographic result rejection.

### Follow-up: multi-fact consent is now explicit — VERIFIED

The user then cleared `testuser` memory and repeated the same sentence. Runtime
logs showed the chat completed but the browser submitted only the Scout-interest
approval; no preferred-name request reached the backend. A read-only Chromium
replay proved the name was correctly first in the queue, but the card described
the second fact only as `1 more memory proposal waiting`, making it easy to skip
one fact and assume the other approval covered the sentence.

The approval card now previews every queued value and offers **Approve all 2**
while retaining per-item approval and dismissal. Batch UX saves each typed
endpoint in order; if a later request fails, already saved facts are reported,
the failed and unattempted proposals remain actionable, and the error is shown.
A real Chromium run as `testuser` submitted the exact sentence and used that
single action. Network evidence was preferred name 200 plus Scout interests
201; readback was name `Jen` and all three interests. The card and loading state
cleared, the composer enabled, and Console, page, and network-failure lists were
empty. The focused Playwright regression and production frontend build pass.

## Scout's prompts now live with Scout

Done. `agents/scout/` holds `aiming.py`, `reranking.py`, `describing.py` and
`place_suggest.py` — every prompt Scout injects. `discovery/` keeps the
machinery: the sweep, ranking, novelty, familiarity, delivery, and the
deterministic half of describing (`clean_title`,
`summarize_deterministically`, `text_from_html`), which never invents and which
several modules share.

Three things made it work, and are worth not undoing:

- `TextWriter` moved to `core/interfaces.py`. It had lived inside Scout's
  describe module, so every agent-shaped module imported that module for a type
  unrelated to Scout;
- `InterestAim` and `SweepAim` moved to `discovery/types.py`. They are data, so
  `precision.py` and `runner.py` take them from the domain and no type drags the
  agent layer in behind it;
- `runner.py` imports three classes from `agents/scout/`. That is the one edge
  from domain to agent, and it is deliberate: the runner *is* Scout's sweep
  body. There is no cycle — `agents/registry.py` reaches only
  `discovery/reachability.py`, which imports nothing back.

Deck is done too: `agents/deck/prompts.py` holds all five — the four contract
builders and the preambles that open each call — and `presentations/provider.py`
keeps the machinery, the JSON extraction, the per-layout schema and the view
builders that decide what a slide looks like to the model.

Diagram and memory capture are done too — `agents/diagram/prompts.py` and
`agents/memory/prompts.py`. Memory capture has no registry card because it is
not something the workspace lists; it is a step in every conversation, and the
folder exists only so its prompt sits with it.

Every agent prompt now lives with its agent. `presentations/provider.py` holds
none: the slide-content preamble became `slide_content_preamble(index, total,
deck_title)` in `agents/deck/prompts.py`, parameterised because it is the only
call that tells the model where in the deck it is.

A codebase audit found **no unused modules at all**. Seventeen public
definitions read as unreferenced and all but two were false positives — pydantic
validators, FastAPI routes, MCP tool decorators, protocols used in string
annotations, and one aliased import. `get_owned_record` and `clear_style` were
genuinely dead and are gone. `apply_slide_edit` is still unreferenced and is
deliberately left: the roadmap records slide editing as verified, so it is
either an edit path nothing applies or a gap in that claim, and deleting it
would hide the question.

**Not moved on purpose:** `search/classifier.py` and
`artifacts/image_recall_classifier.py`. Both call a model, and both route rather
than produce work — they decide whether to search or to look for an image.
Treating a routing policy as an agent would put a folder round something the
workspace will never list. Decide that before moving them. Search routing and image recall are in
`search/classifier.py` and `artifacts/image_recall_classifier.py`, and those two
may be policies rather than agents — decide that before moving them.

## Schedules now take their zone from the user's place — half fixed

`PUT /schedule` no longer reads the caller's timezone. It takes the zone from the
user's primary locality, and refuses with 409 when there is no locality yet:
a time means nothing without the zone it is in, so the place has to come first.
The request still accepts a `timezone` field and ignores it, so existing clients
do not break on an unknown key.

**What is still wrong.** The locality's own zone can be wrong, so the schedule
now faithfully inherits a wrong zone. `projection.py` hardcodes
`America/New_York` when a place is created from a chat approval, which is how an
account in Canggu, Bali holds a locality — and therefore now a schedule — in
Virginia time. Existing rows are unchanged: arsalon's schedule still reads
America/New_York and will until his locality does.

The remaining work is resolving a place to a zone: the Nominatim resolver
already returns coordinates that map to one, or a bundled table. Until then the
Scout panel is the only path that stores a true zone, because the browser sends
`Intl.DateTimeFormat().resolvedOptions().timeZone`.

## Original diagnosis

Diagnosed, not fixed. The scheduling mechanism is timezone-aware — each row in
`discovery_schedules` carries a `timezone` and `next_run_at` is computed from
the local hour in it — but the timezone is never derived from where the user is:

| user | locality | schedule tz | correct? |
| --- | --- | --- | --- |
| jenos1 | Alexandria, Virginia | America/New_York | yes |
| ani.mallya | Virginia | America/New_York | yes |
| arsalon | **Canggu, Bali, Indonesia** | **America/New_York** | **no** |

arsalon's schedule reads 11:15. It fires at 11:15 New York, which is 15:15 UTC
and 23:15 in Bali, so a morning digest arrives at eleven at night.

`projection.py` hardcodes `timezone="America/New_York"` when it creates a
locality, and a place approved from chat goes through that path — the label
"Canggu, Bali, Indonesia" is stored while the clock stays in Virginia. The same
default appears in `api/v1/discovery.py`, `delivery.py` and `digest.py`. Each is
reasonable alone; together they mean the system assumes everyone is on the US
East Coast and nothing ever contradicts it.

`PUT /localities` does better: the frontend sends
`Intl.DateTimeFormat().resolvedOptions().timeZone`, so a place typed into the
Scout panel picks up the browser's zone. The chat-approval path has no browser
timezone to pass, which is the path that produced this.

Two parts, and the second is the real one:

1. stop the projection inventing a zone — make the column nullable and resolve
   at read time, so a wrong clock is visible rather than assumed;
2. derive it from the place. "Canggu, Bali, Indonesia" to `Asia/Makassar` needs
   a lookup: either the Nominatim resolver, which already returns coordinates
   that map to a zone, or a bundled place-to-timezone table. The browser zone is
   a fair proxy and is wrong for anyone travelling — which is exactly the case
   Scout already models with travel mode, so it cannot be the whole answer.

Until then, setting a place through the Scout panel from a browser in the right
country stores the real zone, and re-saving the schedule picks it up.

## A functional suite, and what it found immediately

`backend/tests/functional/` sends each prompt to the real model and asserts on
the answer. Fifteen behaviours, chosen from what each prompt claims to do rather
than from past incidents: an interest becomes matchable text, a subject carries
no place or date, personalisation is visible when a fact exists, a finished page
is reported as finished and a weekly class is not, a description never carries a
link, a shared place name completes to more than one region, a nonsense name
completes to nothing, ordering follows the facts, a weak match is not excluded,
and capture ignores a question or another person's preference.

Fourteen pass. One is marked `xfail` and is a **real product defect, not a flaky
test**: asked for a three-step pipeline, the diagram model returned
`<!template>flowchart TD:[order[]((Order Received))]...` — markup the renderer
cannot draw — and on retry failed validation outright, so that request produces
nothing at all. The prompt already forbids HTML and requires the source to start
with its declaration; the model ignores both on this shape of request. The fix
is a worked example in the prompt or a repair pass before validation, and it
needs measuring across several requests rather than the one.

Two things to keep doing here. Assert on properties, not wording, so a reworded
prompt survives and a changed behaviour does not. And write the test from what
the prompt claims, not from what has gone wrong before — this suite was written
that way and found a defect nobody had reported.

## Where the prompts are

Every prompt Scout injects, so they can be read in one place:

| What it decides | File |
| --- | --- |
| Search subject and ranking vector per interest | `backend/discovery/aiming.py:147` |
| Order of the qualified shortlist against memory | `backend/discovery/reranking.py:102` |
| A find's name, its one-line description, and whether the page says it is over | `backend/discovery/summarize.py:183` |
| Place-name completion while typing | `backend/discovery/place_suggest.py:83` |

`docs/ARCHITECTURE.md` has the table of when each runs and what it costs.

Two of these are load-bearing in ways that are not obvious. `aiming.py` runs
even when memory is empty, which is every account today, because a two-word
interest cannot be matched against an event description at all. And
`summarize.py`'s `already_happened` is asked but no longer trusted alone: a
stated deadline is read deterministically in `url_dates.deadline_has_passed`,
after a digest offered a vote that closed a week earlier.

## Scout: where it stands and what is next

`python -m backend.cli.evaluate_discovery_ranking` scores the pipeline against
21 items that reached real digests. Baseline: **listing recall 0.46, happening
retention 1.00**. The seven listings still getting through are named in the
output — that is the work queue, not an aggregate to admire. `--with-model` also
scores attribution through the aiming and cross-encoder stages.

Ranking is a three-stage cascade: embeddings for recall (`relevance.py`), a
local ONNX cross-encoder for precision and attribution (`precision.py`), then
the model for what memory states (`reranking.py`). Only the first decides
eligibility. All of it is deployed; a fresh checkout must fetch the
cross-encoder weights (`DEVELOPMENT_GUIDE.md`) or that stage disables itself.

Queued, in priority order:

1. **Audience restrictions, deterministically.** `summarize.py` already reads
   page text and already drops finds, so add a restricted-audience field there.
   Say it in the digest name first so the user can judge; filter only in code,
   only against an explicitly stated fact. Do not push this into the re-ranker's
   prompt — measured, and it inferred gender from nothing.
2. **Geographic rejection.** Visible in the labelled cases:
   `concertfix.com/concerts/arlington-tx` reached an Arlington, Virginia digest,
   and a chamber-of-commerce index for Alexandria Bay, New York reached an
   Alexandria, Virginia one. Deterministic, cheap, and long overdue.
3. **Route listings to the feed proposer rather than the bin.** `feed_finder`
   and `LinkGraphExpander` already propose sources from discovered pages. "Movie
   showtimes near Alexandria" is a bad digest item and a good source candidate.
4. **A structured event source.** Ticketmaster, Eventbrite, or Songkick return
   events with start times and coordinates, removing the listing/happening
   distinction, the date parsing, and the geography problem at once. Feeds are
   already the design's "source of record"; almost nobody configures one, so web
   search does all the work and fights this fight every sweep.
5. **Earn back or delete `is_a_listing`.** It is computed and unused.

Volatile state: **`DISCOVERY_NOVELTY_ENABLED=false`** in `.env`, so digests
repeat until it is turned back on — it must be on before anything runs
unattended. Seen items were purged for `ani.mallya`. The Mac bridge grants work.
`jenos1` has "Social" and "Network" as separate interests, almost certainly one
phrase split at capture, and it will keep producing odd matches until corrected.

## Scout searches and ranks for the person — VERIFIED in source, NOT DEPLOYED

A sweep used to be handed a two-word interest label and a city, so the query was
`{label} {place} {month year}` and the vector a candidate was scored against was
the embedding of `label`. Approved memory reached neither. Three new modules
close that:

- `discovery/personal_context.py` reads one account's **approved, unexpired**
  facts and remembered sentences, skips the interest and locality projections
  (already typed into the profile), drops `preferred_name` and `response_style`,
  screens every statement through the same `OutboundPrivacyPolicy` that guards
  chat search, and bounds the result to 12 statements of 200 characters;
- `discovery/aiming.py` asks Qwen once per sweep to turn each interest plus
  those facts into a **search subject** and a **ranking profile**. The skeleton
  `{subject} {place} {month year}` and the query budget are unchanged. A subject
  carrying a digit, a month, the place, query syntax, or anything the egress
  screen would rewrite is rejected and the bare label used instead;
- `discovery/reranking.py` ranks a shortlist twice as wide as the digest and has
  Qwen order it against the same facts. It can never admit what deterministic
  ranking rejected, and if it excluded everything the deterministic order ships.

Both stages are behind `DISCOVERY_PERSONAL_QUERIES_ENABLED` and
`DISCOVERY_MEMORY_RERANK_ENABLED` (default true, added to the Compose allowlist
for `backend` and `discovery-worker`, verified present in `docker compose
config`). With either off, or with no model, no memory, or an unparseable reply,
the sweep searches and ranks exactly as it did before.

### Measured against the live runtime, read-only, no search budget spent

Real vLLM (`qwen/qwen3.5-4b`) and the real embedding service, for a person whose
approved facts said they run casually at weekends, are a man, prefer
beginner-friendly things they can attend alone, like live jazz and dislike
stadium shows, and do not drink:

```
Run Clubs    -> casual weekend group runs   Hiking  -> beginner-friendly hikes
Concerts     -> live jazz and blues         Line Dancing / Wine Tasting -> unchanged
```

Best-interest margins, bare label vs aimed vector:

| candidate | bare | aimed |
| --- | --- | --- |
| Saturday Morning Social Run | 0.633, margin 0.071 | 0.757, **margin 0.132** |
| Live Jazz Trio at Blues Alley | 0.644, margin 0.054 | 0.737, **margin 0.118** |
| Beginner Line Dancing Social | 0.768, margin 0.208 | 0.843, margin 0.206 |
| Stadium Tour: Arena Rock | 0.640, margin 0.119 | 0.690, margin 0.159 |

Genuine matches separate roughly twice as far — which is what
`MIN_ATTRIBUTION_MARGIN` (0.035) exists to cope with. **And enrichment cannot
encode exclusion**: the stadium show scored *higher* after enrichment for
someone whose facts say they dislike stadium shows. That is the case for having
both stages rather than either.

The re-ranker put the social run, the jazz trio and the beginner class first and
pushed the stadium show, the wine festival and a women-only race last — correct
for this person, deterministic across repeated greedy runs.

### The women-only defect is mitigated, not fixed

The re-ranker ranked the stated women-only race last and did **not** exclude it,
for a person whose facts state they are a man. Strengthening the wording was
tried and measured, and is recorded in `reranking.py`: with a worked example it
excluded all three restricted-or-disliked items — turning two *preferences* into
eligibility bars — and on a control context with **no fact about gender** it
still excluded the women-only race. That is the inference this must never make.
The conservative wording stayed. Audience restriction still needs the
deterministic route: a restricted-audience field read out of the page in
`summarize.py`, said in the digest, filtered by code against an explicit fact.

### The binding constraint is upstream: memory is empty

`memory_facts` holds exactly three non-projection rows across the whole
database, all `preferred_name` (which this deliberately never reads), and
`semantic_memory` holds one row belonging to a throwaway test account. So for
`ani.mallya` the personal context reads empty, the planner is not called, and
every query is the bare label — verified by running the planner against that
real account. The plumbing is in place and has nothing to carry. Making Scout
personal from here is a memory-capture problem, not a discovery problem.

- Regression: **1020 backend tests pass** with `AUTH_REQUIRED=false`, including
  28 new ones; Ruff and strict MyPy clean on `backend/discovery` (two
  pre-existing `link_graph.py` errors untouched); 17 diagrams synchronized.
- `UNVERIFIED`: no sweep has run through the built containers. The images were
  not rebuilt and `backend`/`discovery-worker` were not recreated, because doing
  so drops live users on the tunnel. Rebuild both, then `docker compose restart
  gateway`, before claiming live behaviour.


## Scout account isolation restored at the live runtime — VERIFIED

A report that a `jenos1` 9:30 PM subscription triggered the primary user's
phone exposed two separate facts. PostgreSQL already held distinct owners:
`ani.mallya` owns the 9:30 PM schedule and five interests, while `jenos1` now
owns a 10:00 PM schedule and twelve different interests. Their subscriber address
digests are also different, and the 9:30 delivery belongs to the
`ani.mallya` run and subscriber. The worker reads the run's `user_id` and uses
that same owner for profile retrieval and subscriber selection.

The first failing boundary was nevertheless security-critical: the live
backend was a stale container with `AUTH_REQUIRED=false`, even though `.env`
and the current Compose rendering both specify `true`. In trusted-local mode
the ownership dependency intentionally accepts caller-supplied user IDs. The
backend was recreated from current Compose configuration and the gateway was
restarted. Direct live bearer requests now prove:

- both owners can read their own profile and schedule (HTTP 200);
- the interest sets are separate and disjoint (five vs. twelve);
- an `ani.mallya` token cannot read `/discovery/jenos1` (HTTP 403);
- an anonymous request cannot read `/discovery/ani.mallya` (HTTP 401);
- backend logs record those 403/401 decisions without an exception.

The phone UI also hid the signed-in identity and represented logout only as an
unlabeled compact-header icon. The mobile navigation drawer now shows
`Signed in as <user>` beside a labeled **Sign out** action. Playwright at
390x844 exercised both the deterministic app and the rebuilt production
gateway: it opened the drawer, confirmed the live authenticated account,
received HTTP 204 from logout, and reached the login screen with no Console or
page errors or failed network requests.

Regression evidence: the auth, delivery, schedule, and worker suites pass 45
tests, including a new two-user delivery assertion that only the requested
owner's approved address is selected; two focused mobile browser tests pass;
and the production frontend build passes.

### `jenos1` phone delivery — FAILED at the Mac grant boundary

The current Mac MCP bridge advertises both `send_imessage` and
`allow_recipient`, but an idempotent grant for the already consented and
operator-approved `jenos1` subscriber returns a tool error that explicitly
identifies bridge grants as disabled. The subscriber remains deliverable in
AniOS but has zero successful deliveries and `recipient_not_allowed`; nothing
was redirected to `ani.mallya`.

The latest 10:00 PM run fetched five candidates and persisted five selected
future/undated items. Its `delivered_at` field is only the claim-before-send
marker and is not evidence of receipt: the subscriber row was not touched and
the user received nothing. A read-only replay of that stored digest through the
current delivery logic selects exactly the one `jenos1` subscriber and would
make one channel call. Do not replay the old message; its durable retry payload
has already been cleared.

The Mac LaunchAgent must persist `IMESSAGE_BRIDGE_ALLOW_GRANTS=true` (and may
set an explicit writable `IMESSAGE_BRIDGE_GRANTS` path), then reload/restart
the bridge. Re-approve the existing subscription or invoke the idempotent grant
again, confirm `granted`, and validate a new owned digest reaches only the
masked `jenos1` destination.

### Next atomic Scout task after delivery is verified

Add and validate geographic result rejection. The live Arlington, Virginia
rehearsal correctly found local basketball/baseball results but also admitted a
college-baseball result explicitly located at Globe Life Field in Arlington,
Texas. Reject an explicit place that contradicts the active locality/region
before it can enter the digest — deterministically, in code: this is a string
comparison against a stated place, not a judgement.

## Scout rejects explicitly past search results — VERIFIED

The live `ani.mallya` rehearsal reproduced two user-visible problems: Scout
returned a prior line-dancing event as an undated possibility, and its message
opened with the mechanical phrase `Worth a look — no date given`. The first
failure was at web-result conversion: an explicit date before today and no
date at all both became `None`, so relevance treated the past event as an
undated mention.

`WebEventSource` now preserves the distinction long enough to reject an
explicit date before today. Current and future explicit dates retain their
typed value; genuinely undated results remain bounded mentions. The fixed
digest renderer now says either `I found this, but couldn't confirm the date`
or the plural equivalent instead of implying an undated result is confirmed
upcoming.

Live authenticated evidence on the rebuilt backend:

- the same non-persisting `ani.mallya` rehearsal exercised four MCP
  `internet/search_web` calls through Tavily, Nomic embedding/ranking, and the
  digest renderer with no backend exception;
- the candidate pool fell from 27 to 26 because the explicitly past result was
  rejected before ranking;
- the returned message used the new uncertainty wording and contained no old
  heading;
- Chromium opened the real signed-in `ani.mallya` Scout panel, ran **Try it**,
  rendered the new wording, and reported no blocking Console or page errors;
- 286 discovery backend tests, Ruff, strict MyPy, five focused Scout browser
  tests (two passed and three correctly skipped without live credentials), the
  separately credentialed live browser acceptance, and the frontend production
  build passed.

At the user's request, all 28 `discovery_seen_items` rows owned by
`ani.mallya` were deleted after validation so another real test starts clean.
The scoped count is now zero; `jenos1` and `del_2a87abb15636` rows were left
unchanged. Interests, locality, schedules, subscriptions, familiar-item
dismissals, memory, and run history were not deleted.

## Semantic chat interests configure Scout — VERIFIED, generalized

The original `testuser` failure was at chat capture, not Scout retrieval. That
focused interest classifier has since been generalized into the typed
`MemoryProposalAgent` described at the top of this handoff. It still sends only
the current utterance and existing interest catalogue to local Qwen, has no
persistence or tool capability, and returns up to eight validated labels.
Approval writes every selected interest fact and Scout projection in one
database transaction; a capacity or projection failure rolls the batch back.

Live authenticated evidence on the rebuilt backend:

- direct `POST /api/v1/chat` returned a complete SSE stream with one
  `discovery_interests` proposal containing basketball, soccer, baseball, and
  hiking;
- direct approval returned 201 and the owned Scout profile contained exactly
  those four `user_explicit` interests;
- Chromium repeated the conversation, approved the card, opened Agents → Scout
  → Configure, and saw all four strength controls; streaming terminated, the
  composer re-enabled, and post-login Console/page errors were empty;
- another profile remained empty in the integration test;
- a live non-persisting Scout rehearsal in Arlington, Virginia spent four MCP
  `internet/search_web` requests, each reached Tavily with HTTP 200, Nomic
  embedded/ranked the candidates, and Qwen produced the visible descriptions.

The browser run also found and fixed an adjacent authenticated Scout UI defect:
subscription read/write/delete used bare `fetch`, omitted the session cookie,
and emitted 401s. They now use the shared authenticated request boundary.

Validation: 127 relevant backend tests passed; Ruff and strict MyPy passed; two
deterministic Scout browser tests passed; the authenticated live Scout browser
test passed; the frontend production build passed; all 17 canonical diagrams
and `architecture.html` are synchronized. A combined full-backend/full-browser
run exceeded its 10-minute orchestration ceiling and ended with a Playwright
EPIPE, so the complete suites are `UNVERIFIED` for this tree rather than failed.

## Scout's iMessage channel — VERIFIED working end to end

The bridge (`bridges/imessage_mac/`) is running on a real Mac (not AniOS's
Windows host) and a message sent through it was confirmed received on the
allowlisted phone. Both the header-auth transport fix (`d3001d9`) and the
backend's own missing `docker-compose.yml` allowlist entries for
`DISCOVERY_IMESSAGE_SERVER_ID`/`DISCOVERY_IMESSAGE_TOOL` (`6e77969` — the
fourth instance of the environment-allowlist trap this session) were needed
before this worked; either alone left it silently broken.

What the Mac side needed, none of which is obvious from the bridge's own code:

- **Python 3.10+, not the system `python3`.** A stock macOS install (and this
  Mac specifically) ships an ancient `python3` (3.7 here) via an old
  python.org installer; `mcp` requires 3.10+ and fails at `pip install` with
  "no matching distribution found for mcp", which names the package rather
  than the interpreter as the cause. Installing a newer Python via Homebrew on
  an unsupported-for-bottles macOS version (this Mac: Ventura 13.7, Intel)
  means several dependencies build from source, and that build fails outright
  if Xcode Command Line Tools are older than Xcode 15.2 — this Mac's shipped
  CLT was from 2019 (`clang 11.0.0`) and needed
  `sudo rm -rf /Library/Developer/CommandLineTools && sudo xcode-select --install`
  before Homebrew's `openssl@3`/`readline` builds would even compile.
- **The Automation permission prompt is silent when nobody can answer it.**
  The first `osascript` call to Messages/System Events from a non-interactive
  or remote-controlled shell hangs for the AppleEvent timeout
  (`-1712`) and never surfaces a clickable dialog. It only works once someone
  runs an AppleScript call to Messages from an interactive Terminal window
  they're physically at, and clicks Allow.
- **The bridge needs the Mac to actually stay up.** `pmset -g` shows battery
  `sleep 1` (one minute); its existing AC settings are `sleep 0` and
  `disksleep 0`. `caffeinate -s` is AC-only, so it cannot keep this laptop awake
  on battery. A separate LaunchAgent at
  `~/Library/LaunchAgents/com.anios.imessage-bridge-awake.plist` now runs
  `caffeinate -i` with `RunAtLoad` + `KeepAlive`. It was verified on 2026-08-08:
  the assertion appeared as `PreventUserIdleSystemSleep`, killing it made
  launchd respawn it with a new PID, and the bridge continued to return its
  expected unauthenticated `401`. A laptop's lid still forces sleep regardless
  of this assertion unless it is in clamshell mode with an external display
  attached.
- **The process itself needs to survive logout/crash, which `nohup` does
  not.** It now runs as a `launchd` LaunchAgent at
  `~/Library/LaunchAgents/com.anios.imessage-bridge.plist`
  (`RunAtLoad` + `KeepAlive`, verified by `kill -9`-ing the process and
  watching it respawn under a new PID within seconds). This only starts once
  the Mac's user account is actually logged into a GUI session — it is a
  LaunchAgent, not a LaunchDaemon, because Messages automation needs a real
  Aqua session, not just a booted machine.

**The Mac's LAN IP is the address in `MCP_SERVERS_JSON`, and it can move.**
Same failure shape as the tunnel hostname below: if this Mac's DHCP lease
changes, the configured `url` silently points at nothing and AniOS-side
delivery starts failing with no signal pointing at the address as the cause.
Consider a static DHCP reservation for this Mac if the bridge is meant to be
depended on rather than just demoed.

**The shared bridge token has already been rotated once** after an earlier
value was pasted into a chat transcript relaying setup instructions between
the two machines. Treat any token that has appeared in a conversation as
burned; regenerate rather than reuse.

## Public access is deep-matter.com — VERIFIED

Live as of 2026-08-11. Tunnel `anios`
(`2a9093ad-4b7a-4fb2-8166-6f8de1eef5a4`), config in the operator's
`.cloudflared/config.yml`, ingress validating `OK`, DNS already routed.

Verified from inside a container rather than the desktop: DNS resolves to two
Cloudflare edge addresses, both complete a TLS handshake, `/healthz` returns 200
`ok`, `/` serves the compiled application, and `/api/v1/agents/{user}` returns
401 from FastAPI — the last of which is what proves the tunnel reaches the app
rather than just the edge.

**Cloudflare answers a non-browser client with error 1010** (browser integrity
check), so a scripted request without an ordinary user agent reports 403 on
every path and looks exactly like a dead site. That cost a round here. Send a
normal `User-Agent` or the check measures the bot rule instead of AniOS.

**The tunnel runs as a Scheduled Task, not a Windows service.** The service was
abandoned after six attempts: it installed, reported `Running`, and registered no
connector, because Windows recorded its ImagePath as the bare executable with no
arguments. With nothing to run it started, exited, and retried — and `sc.exe
config` would not attach arguments, `service install` refused to touch an
existing registration, and `service uninstall` left the key marked for deletion
behind a process that would not die.

The task is `DeepMatter tunnel`, registered to run as SYSTEM at startup and to
restart itself every minute if cloudflared stops.

### ComfyUI does not restart itself either — same reboot, same cause

After the 08:49 reboot nothing was listening on 8188, so every image request
failed while every container reported healthy. ComfyUI is a host process at
`COMFYUI_HOST_PATH`, not a Compose service, so `restart: unless-stopped` never
applied to it.

It now has a `DeepMatter ComfyUI` logon task running the same command
`start-anios.sh` uses. Unlike the tunnel's SYSTEM task, this one is readable
from a non-elevated shell — action, arguments and working directory all verified
— but it has still not survived an actual reboot, and that is the claim that
already failed once here.

The symptom is worth remembering: it presents as the assistant refusing, not as
an outage. An edit typed into the main composer became an ordinary chat turn and
the model answered that it could not edit images. That routing is fixed, and the
first check for any image failure is `http://127.0.0.1:8188`.

### The tunnel now runs from a user logon task — TESTED, not assumed

`DeepMatter tunnel (user)` runs cloudflared at sign-in as the logged-in user.
Registered without elevation, which is the point: it can be read, started and
stopped from an ordinary shell, so it can be *tested*. The SYSTEM task and the
`cloudflared` service could be neither read nor repaired without admin, and both
silently did nothing.

The task now starts `scripts/run-tunnel.ps1`, a small supervisor around
cloudflared. This replaced reliance on Task Scheduler's `RestartCount`: killing
the connector produced result `0xFFFFFFFF`, and Windows left the task stopped
instead of retrying. With the supervisor installed, killing only cloudflared
kept the task running and registered a replacement connector in about 15
seconds.

Proven rather than inferred on 2026-08-12: the task was installed from the
repository, started with `LastTaskResult` 267009, its connector was killed, and
the replacement served both Cloudflare IPv4 addresses. From inside the backend
container, `/healthz` and `/` returned 200 and
`/api/v1/agents/ani.mallya` returned the expected 401 on each address. Docker
Desktop's `AutoStart` setting is also true. An actual Windows reboot after this
supervisor change remains **UNVERIFIED** because verification did not interrupt
the operator's machine.

Signing in at logon rather than at boot is deliberate now, not a compromise.
Docker Desktop starts at sign-in, so a tunnel that starts at boot spends the gap
serving 502s to the world with no origin behind it. Both halves now wake
together.

`LastTaskResult` of `267009` (0x41301) means "currently running" and is the
correct state for this task, not a failure.

Still needing an elevated shell, and now only as tidying: `sc.exe delete
Cloudflared` for the dead service, and removing the old SYSTEM `DeepMatter
tunnel` task. Neither is harmful — both use the same corrected config, so if the
old task ever does fire it registers a second connector, which Cloudflare treats
as ordinary redundancy.

### The earlier attempt, and why it failed

The machine rebooted at 2026-08-11 08:49 and `deep-matter.com` served error
**1033** — no connector registered — with no cloudflared process running at all.
Docker came back correctly; the tunnel did not. The site was restored by hand
with a user-space `cloudflared tunnel run anios`. That failure led to the
user-level supervised task described above.

"The tunnel survives a reboot" was asserted from the task existing, never from a
reboot. The reboot has now happened and disproved it. Nothing about durable
public access should be believed here again without a reboot behind it.

Diagnosing it needs an elevated shell, which was unavailable when this was
found:

```powershell
schtasks /query /tn "DeepMatter tunnel" /v /fo LIST | findstr /i "TaskName Status Last"
```

`Last Result` distinguishes the three cases: `0x0` with nothing running means
cloudflared started and exited cleanly — most likely the boot race, where
networking is not ready, it cannot reach Cloudflare, and quits. `-RestartCount`
does not cover that, because it only fires when a task *fails*. A non-zero result
names the failure. Task-not-found means it needs recreating.

The likely fix is a startup delay plus restarting on any exit rather than only on
failure. The `Cloudflared` service is still registered, `Stopped / Automatic`,
and should be removed with `sc.exe delete Cloudflared` so two mechanisms are not
competing.

Note that a non-elevated shell can read neither `Get-ScheduledTask` nor
`schtasks /query` for a SYSTEM-principal task — both return access denied — so
the task's existence cannot be confirmed without elevation, only its effects.

**One connector is not evidence.** Every check for an hour showed a healthy
connector that was a foreground process started by hand; the service contributed
nothing the entire time. `cloudflared tunnel info anios` must show the connector
whose timestamp matches when the task started, and the only conclusive test is
stopping every other connector and confirming the site still serves.

`deep-matter.com` is registered through Cloudflare, so the zone is already in
the account and DNS can point at a tunnel without moving nameservers.

`scripts/start-tunnel.sh` runs a named tunnel when `ANIOS_TUNNEL_NAME` and
`ANIOS_PUBLIC_HOSTNAME` are set, and falls back to a quick tunnel otherwise. The
one-time setup is in [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) — it needs a
browser login to the Cloudflare account, so it is done by hand on the serving
machine, and there is no token to configure.

Until that setup is done the address is still a `trycloudflare.com` quick
tunnel, which **does not survive a reboot and takes a new random hostname every
time**. The script rewrites `DISCOVERY_CALENDAR_BASE_URL` to match in that mode;
recreate `backend` and `discovery-worker` afterwards so they read the new value.
A named tunnel rewrites nothing, because nothing changes.

`AUTH_COOKIE_SECURE` becomes true in the same step that makes the HTTPS origin
real, and not before: true over plain HTTP leaves no working login anywhere.

Docker services now carry `restart: unless-stopped`, so the stack itself
returns when Docker Desktop starts. ComfyUI and local-capabilities deliberately
do not — they hold the GPU. Installing the tunnel as a service is what makes the
public address survive a reboot too.

### Verify ingress from outside, never from this desktop

Some ingress resolves its own hostnames back locally, so `curl` from the host
returned 200 in ~14 ms while the public path was dead. That produced a false
"verified working" report that cost several rounds. Use a TLS handshake from
inside a container, which has its own network namespace, and check **every**
published address:

```python
socket.create_connection((ip, 443), 10)
ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
```

## The three reported defects are fixed; one is only reduced

All three were reproduced, changed, and re-exercised against the running stack.
Details in [CHANGELOG.md](CHANGELOG.md).

### 1. Explicit "remember this" — VERIFIED fixed

Was: the former phrase extractors returned no proposal for "Remember that my
dog is called Biscuit.", and the assistant claimed a save anyway. The current
typed semantic agent selects `semantic_fact` without a phrase rule, while the
pre-answer save-state prompt keeps the reply honest.

Re-run of the original reproduction, through the API with auth on:

```
CHAT 1 >  "...I cannot store this myself, just approve the save card below."
          memory_proposal: kind=semantic_fact "my dog is called Biscuit."
approve -> 201        semantic count 0 -> 1
CHAT 2 (new conversation) >  "Your dog's name is **Biscuit**."
```

The honesty half needed two attempts, which is worth remembering: told only
that it could not write to memory, the model answered "your personal memory has
been updated". A blanket prohibition invites a passive rephrasing. What worked
was deciding the proposal **before** generating the answer and stating the
turn's real save state in the prompt, with the sentence to write.

### 2. Presentation slides render empty — VERIFIED fixed

The mechanism was narrower than recorded. `statistic`, `quote`, `comparison`,
`chart`, and `table` already degraded to bullets through `_effective_layout`,
and the grammar already promotes each layout's fields to required. **`section`
was the only layout still discarding its points**, and it produces exactly the
reported symptom: a rule, a title, a purpose, nothing else. Confirmed by
compiling one directly (3 elements, both points gone) before changing anything.

Section slides now carry their points. Verified on three real generated decks:
12 slides, 0 rendering only a title and a purpose.

### 3. Deck content is ungrounded — reduced, not eliminated

`DeckResearch` runs one privacy-screened search per deck at outline time and
quotes bounded sources into the outline and every slide request. Verified live
inside `presentation-worker`: MCP → Tavily returned NASA and Smithsonian
sources, and the same brief sent verbatim had returned a slideware marketing
page until the brief was reduced to its subject.

Same brief, same model, measured:

| | ungrounded | grounded |
| --- | --- | --- |
| crewed landings | "seven" | "six" (correct) |
| dates | "Apollo 11 December 1969", "285-day intervals", "21-year span" | Apollo 8 December 1968 (correct) |
| crews | Apollo 12 crew wrong | Apollo 12 and 14 crews correct |

Two errors survived: the Apollo 11 module as "Eagles", and Charles Duke placed
on Apollo 15 (he flew Apollo 16). **Do not record this as solved.** Grounding
is wired, screened, metered, and degrades safely, but Qwen 3.5 4B with 1,024
tokens per slide still misreads its sources. The next lever is the slide token
budget or a stronger presentation role, not more prompt wording — that was
already tried here and is what the contract now says.

## Pin `mcp` below 2.0, and know why

`requirements.txt` had `mcp>=1.0.0` open-ended. Rebuilding the image today
resolved **mcp 2.0.0**, which removes `mcp.server.fastmcp` — imported by both
built-in stdio servers and the local-capabilities sidecar. The result: web
search and every MCP server broke in the containers while the host venv stayed
on 1.28.1 and the full test suite still passed. It is the rug-pull the MCP
guidance warns about, arriving through a Python dependency rather than a server.
Now pinned `<2.0.0` in both `requirements.txt` and `pyproject.toml`, verified as
1.29.0 with `fastmcp OK` in backend, presentation-worker, and
local-capabilities.

If MCP or search breaks after a rebuild, check the installed `mcp` version in
the container first.

## Things that look wrong and are not

- **`max_distance=0.96`** for image recall in `conversation_service.py`. It is
  not comparable to discovery's `0.08` novelty or `0.16` familiarity — those
  measure text embeddings, this measures image embeddings, where genuine
  matches sit around 0.90–0.94. Tightening it to 0.45 disabled recall and broke
  three tests. Any change needs the real distance distribution measured first.
- **Memory has no cross-user leakage.** Verified: zero nullable `user_id`
  columns in the schema, every retrieval filters on owner, and a guest asking
  for another account's data gets 403 rather than an empty list.

## Recently landed and verified

- Sign-up records an access request carrying the chosen username and password
  (hashed on arrival); approval creates the account outright. Verified through
  the public URL: request `201 pending` → login `401` → approve → login `200`.
- Accounts can be revoked (sessions destroyed immediately) or deleted. Deletion
  discovers its tables from `information_schema` rather than a hand-written
  list, because a hand-written list already shipped here missing eight
  discovery tables.
- Interactive search is metered per account, with a shared monthly pool sized
  to the real Tavily allowance and reconciled against their usage endpoint
  (which reported 37 credits spent the local counter knew nothing about).
  Usage is visible to the person spending it, not only the operator.
- Conversations are listed and deleted from the server; history no longer lives
  in one browser's `localStorage`.
- The sidebar opens as an overlay below 768px, so history is reachable on a
  phone.
- Scout's discovery profile is no longer injected into ordinary chat turns. A
  standing list of interests in every prompt bent unrelated answers toward
  them. Guarded by a test in `test_architecture_boundaries.py`.
- Image generation sends the subject rather than the sentence, and the global
  style suffix no longer names skin and hair — that wording put a person in
  every image, which is why a request for a car returned a woman leaning out of
  one.

## Search-routing recall is below its own floor - pre-existing, now measured

Found while gating the weather tool (2026-08-21), FIXED the same day
(8ba3f8e): recall was 0.793-0.827 against the 0.85 floor. Two principles
in select_action.md closed it, measured across three iterations: recency
phrasing (newest/latest, releases, outcomes, today/as-of-now) is live
even when an answer feels memorized - with the distant past explicitly
carved back out after "what happened in 1999" became a false alarm - and
the hold-back-to-ask rule applies only to gaps in the user's own context,
never to an unnamed thing in the world. After: recall 0.897, specificity
1.0, all 34 selector + matrix gates green. Lesson kept: run these gates
with MCP_SERVERS_JSON and SEARCH_API_KEY exported - ANIOS_TEST_MODE
deliberately ignores .env, so the gate silently skips on a bare host run,
which is how the regression went unmeasured.

## iMessage channel: remaining asks

- Bubbles + texting tone SHIPPED (a9e57df): the worker declares
  channel=imessage in /chat metadata, the graph appends
  prompts/reply/imessage_style for that channel only (web prompt pinned
  byte-identical by a gate), verified against the deployed DeepSeek
  runtime; long replies split at paragraph bounds into up to four paced
  bubbles, tail merged never dropped.
- Weather routing, ack variety, markdown flattening, session-by-lull all
  shipped and deployed 2026-08-21 (3abde89).
- Images over iMessage: outbound (generate-and-send as attachment) is
  backend-only work - the worker ignores artifact_ready events today and
  send_imessage already carries attachments. Inbound photos (upload/edit
  from the phone) need bridge v2: read_messages returns text only by
  contract, so attachments require the Mac session's counterpart work
  plus an ingestion path to active_image_artifact_id.

## iMessage channel: audit notes from the bridge session (2026-08-22)

- Attachment fetches retry not_found (3 attempts, growing backoff): iCloud
  lazy-downloads attachments, and the bridge's probe defense deliberately
  makes "not yet downloaded" indistinguishable from "never existed". An id
  from a listing we just read is trustworthy; other refusals are final.
- Edited/retracted iMessages are UNTESTED on the read path. If a weird
  duplicate or empty turn appears in the chat worker, suspect that first.
- An SMS-only sender's inbound reads fine but the iMessage-service reply
  may fail (latent; both current allowlisted addresses are iMessage).
- Outbound attachment path live-verified with a real PNG through Messages.

## The attachment saga, closed (2026-08-22, bridge 962f335)

Root cause of invisible outbound attachments: Messages.app is SANDBOXED
and a scripted send hands it a bare file path it must be entitled to
read. It reads ~/Pictures; it does not read hidden home folders or temp
trees - so every scripted attachment send in this bridge's history
queued a transfer stuck status=waiting forever while AppleScript
reported "sent with attachment". Spool now lives at
~/Pictures/anios-outbox. Implication: historical digest .ics
attachments likely never delivered either (moot for current digests,
which stopped attaching calendars, but explains any old reports of
missing invites). One ghost remains: the 00:45:53Z send failure - an
actual error, which the sandbox failure mode never produces - is
unattributed; verbose reply-failure logging (c14b989) stands watch.

Identity: deep-matter@agentmail.to signed in, sole enabled iMessage
account, pinned via IMESSAGE_BRIDGE_ACCOUNT_ID. The alias-flip and
self-thread classes of confusion are closed.

## Attachment saga, final chapter (2026-08-22 early AM)

After the sandbox/spool fix, images still arrived as dead bubbles. Three
operator-run experiments isolated it: PNG and JPEG through the tool path
both dead; a GUI-dragged photo from the same sole-account Mac uploads
fine; the one scripted send that ever displayed (rainbow) predated the
b403046 account pin. The pinned-account AppleScript send queues the file
transfer without initiating the upload. Workaround live: the pin is
BLANKED in the LaunchAgent - safe while deep-matter@agentmail.to is the
only enabled iMessage account, which the identity work guarantees today.
Owed on the bridge side: a pinned send that actually uploads, then
re-pin. Until then, adding any second iMessage account to that Mac
reintroduces identity flip risk - don't.

Visually confirmed end to end by the operator: format test pair, then
the real hummingbird (jenos1) and whiteboard (operator) delivered.

## Attachment saga, ACTUAL root cause (supersedes both prior chapters)

Fifteen ledger-driven experiments on the Mac (bridge fb8d449) isolated
it: an AppleScript path arriving via `on run argv` and sent as bare
`POSIX file filePath` queues the transfer "waiting" forever; coerced
`as alias` it uploads. EVERY image the bridge ever sent was a dead
bubble - size, spool location, account pin, and JPEG handling were all
innocent (the pin unpinning "working" was coincidental timing with the
Mac session's successful direct-form shell tests). The GUI drag worked
because Finder hands Messages a resolved file. Follow-ups: the account
pin can be RESTORED (it was exonerated); nine zombie "waiting" transfers
sit in Messages' ledger and should be cleaned so they never late-deliver.

## Queued: reply-to as explicit image targeting (operator-designed)

Shipped default: the latest image (sent or generated) is the thread's
picture-in-view, on the session's idle clock - matches texting intuition,
zero education needed. Known limits: recency can pick the wrong target
when two images are in play, and the pointer expires with the lull.
Enhancement agreed with the operator: an iMessage NATIVE reply to a
specific image bubble overrides recency and pins that image as the
ask/edit target. Needs: bridge exposes the replied-to guid in
read_messages (thread originator in chat.db), send path records guid ->
artifact so the worker can map bubble to image. Recency remains the
default for everyone who just types.

## Retention: the processes in play (2026-08-22, operator directive)

What users do cannot clog this machine: chat is text (whole DB 22MB),
per-turn context is bounded (last 10 exchanges + budgeted recall), Redis
state expires, vector recall is per-user over indexed sets. The growth
was operational, and each source now has a bound:

- Container logs: capped in compose (json-file 20m x 3 per service).
- Docker build cache + dangling images: weekly Task Scheduler job "AniOS
  Maintenance" (scripts/maintenance.ps1, Sundays 03:30) prunes cache
  beyond 5GB and dangling images. First run reclaimed 21.5GB (manual) +
  cache bounded thereafter.
- ComfyUI outputs (E:/AI/ComfyUI/output): every generation kept forever,
  redundant with the artifact store. The weekly job prunes anios_* files
  older than 7 days; first run freed 711MB/230 files. Non-anios files
  are never touched.
- The job writes data/maintenance-report.txt (overwritten each run) with
  docker sizes, DB size, and ComfyUI dir size - the quarterly-glance
  numbers in one place.
- Deliberately NOT auto-pruned: the artifact volume (user images are
  user data; retention is the operator's call) and the Mac's spool (the
  bridge cleans its own after an hour).

## NEXT MAJOR: AniOS off the desktop, onto the Sparks (queued 2026-08-22)

Operator decision: the assistant must not depend on the desktop. A second
DGX Spark arrives 2026-08-22; the Spark-to-Spark ConnectX cable is NOT
in hand yet, so the two boxes are independent LAN hosts (no pooled
memory, no tensor-parallel) until it is.

Phase 1 - the assistant survives the desktop going dark:
- Build arm64 images (python:3.12-slim, graphviz, Pillow are arm64-ready;
  verify resvg-py aarch64 wheel; any other native wheel in requirements).
- Move backend, Postgres (pg_dump/restore - the dev DB holds real user
  data and has no backups: back up FIRST, restore SECOND, verify row
  counts BEFORE cutting over), Redis, gateway/frontend, discovery +
  iMessage workers, presentation services, and the deep-matter.com
  tunnel to Spark #2. Windows-specific bits become Linux: the Task
  Scheduler maintenance job -> cron, E:/AI/ComfyUI -> a Linux path.
- Spark #1 keeps DeepSeek (ds4.c, 87GB). Spark #2 hosts vLLM for the
  Qwen 4B router/enforcer + embeddings + VLM (~12GB) and ComfyUI/FLUX
  (~15-25GB) - all inside 128GB unified, so the vLLM-sleeps-for-ComfyUI
  GPU handoff is no longer needed on that box.
- Point MAIN_LLM_BASE_URL at Spark #1, ROUTING/DIAGRAM/embedding at
  Spark #2, MCP_SERVERS_JSON's bridge entry stays (discovery handles the
  Mac moving). Re-run the full functional gates on the new hosts - today's
  lesson: gates pass against the wrong runtime look identical to gates
  passing against the right one.
- Expected regression: Spark decode bandwidth is a fraction of the
  5080's. Measure 4B routing latency and FLUX seconds-per-image with the
  judge harness before declaring the desktop retired; the ack bubble
  covers texting, the web chat is where it will show.

Phase 2 - when the ConnectX cable arrives: evaluate pooling (a larger
DeepSeek quant or a bigger VLM for the VISION_ESCALATION_MODEL slot
across 256GB), and whether the router can move up from 4B without losing
grammar enforcement.

Desktop afterwards: a GPU appliance at most, or off. Memory note:
anios-dgx-spark-hardware.md records Spark #1's address/key; add #2's.

## Reply-prompt gates: run them against the real reply model

The host's `llm` fixture falls back to the local 4B when MAIN_LLM_* is
unset, and the 4B fails honesty behaviors DeepSeek passes (it could not
produce "here's how to check Rockville yourself" - DeepSeek could). The
runtime-faithful run for any prompts/reply/* change:

    MAIN_LLM_BASE_URL=http://spark-b524.local:8888 \
    MAIN_LLM_MODEL=deepseek-v4-flash MAIN_LLM_REASONING_EFFORT=none \
    ROUTING_LLM_BASE_URL=http://127.0.0.1:8003 ROUTING_LLM_MODEL=qwen/qwen3.5-4b \n    pytest backend/tests/functional/test_evidence_honesty_behaviour.py \
           backend/tests/functional/test_no_invented_search_behaviour.py \
           backend/tests/functional/test_imessage_reply_style.py

The ROUTING_LLM_* pin matters: without it the semantic judge (semantic.py,
{holds} grammar) follows MAIN_LLM to the Spark, where ds4.c enforces no
schema, and the judge skips or flakes - seen as 5/6 then 4/6 before the
pin, 6/6 twice after. Same class of lesson as MCP_SERVERS_JSON for the
selector gates: a gate
passing against the wrong runtime looks identical to one passing against
the right one.

## Deploy discipline, restated after the fourth in-flight casualty

14:40:34Z: a texting user got "I hit a problem answering that" -
ConnectError, no address for `backend` - because the backend container
was being recreated mid-turn. Four times in one day a rebuild during a
live conversation cost a visible turn. Until graceful drain exists, treat
`docker compose up --build backend` as a user-visible event: check worker
logs for activity in the last minutes first, batch prompt/code changes,
and rebuild once.
