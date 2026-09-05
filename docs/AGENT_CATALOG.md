# Agents

Every specialized agent in AniOS, what it decides, and where its parts live.

An agent here is something that **produces work a person asked for**, using a
model, and reports itself to the Agents tab. A model call that only routes — the
visual-memory selector, the upload inspector — is a policy, not an agent, and
is listed at the bottom so the distinction stays deliberate rather than
accidental. (Two earlier routing classifiers, for search freshness and image
recall, were deleted once the main routing call could make those judgements
with the conversation in front of it.)

Each agent owns a folder under `backend/agents/<name>/`. The rule that puts it
there: **the mechanism for calling a model is shared and reusable; the prompt
never is.** A prompt is the agent's judgement written out, and it differs per
agent even when the calling code is identical. The domain package holds the
machinery the agent drives.

## Which agents loop

An agentic loop is a component that decides, acts, sees what happened, and
decides again. Exactly one exists today: the **turn step loop** in
`backend/services/turn_steps.py`, which runs inside a conversation turn - the
routed action first (a search, a recall, one of the person's own tools, or a
piece of bookkeeping), then whatever further steps the request needs, each
offered only the tools whose effect contracts allow a later step with the
budget left (`backend/core/effects.py`): a read, or a write to this system's
own records, that is not expensive and needs no approval. At most
`TURN_MAX_STEPS` steps, `TURN_STEP_BUDGET_SECONDS` of wall clock read before
every decision and every action, and `TURN_MAX_CREATES` new things, with a
repeat judged on each tool's own key. Drawn in
[chat-orchestration](diagrams/chat-orchestration.mmd). None of the agents
below loop; each is asked once and answers once.

That is expected to change, and two rules keep it from going wrong twice.
**`run_steps` is the loop.** An agent that wants one calls it rather than
writing its own, because the loop's five stopping rules and its handling of a
failed step each cost a real incident to discover, and a second private copy
would rediscover them privately. **A step says what happened, not what it was
for.** A loop that cannot see a step failed reports success; the outcome kinds
are carried in the line the model reads next, and
`backend/tests/functional/loops.py` is how a loop is held to that - the whole
trajectory, an injected failure, and a rate over several passes rather than
one lucky path.

A new looping agent therefore also needs its loop drawn in its own
`agent-<name>.mmd`, since a loop is a cross-component flow and not an
implementation detail.

## Scout — standing work

Scout is the scheduling agent: anything the person wants to happen on a
schedule rather than right now. Two shapes of the same job.

The first is the ambient sweep it started as - a recurring search for things
happening near you that match your interests, each turned into something you
can act on. The second is anything else asked for on a schedule: a recurring
search, lookup, report or reminder, on any subject, needing no interests and no
locality.

The mechanisms differ and that is an implementation detail, not a product
boundary. The sweep runs from `backend/discovery/` on a cadence; an arbitrary
scheduled request is carried by the `schedule_task` tool and the task runner in
`backend/workers/task_runner.py`, and fires as an ordinary turn delivered to
the person's channel. To the person asking, both are Scout, and every surface -
the agent card, this catalog, the diagrams and the assistant's own answers -
says so.

| | |
| --- | --- |
| Registry id | `discovery` |
| Diagram | [agent-scout.svg](diagrams/agent-scout.svg) · [source](diagrams/agent-scout.mmd) |
| Subsystem view | [discovery-subsystem.svg](diagrams/discovery-subsystem.svg) |
| Agent folder | `backend/agents/scout/` |
| Domain package | `backend/discovery/` |
| Prompts | `aiming.py` · `reranking.py` · `describing.py` · `digesting.py` · `place_suggest.py` · `timezones.py` |
| Card | `agents/scout/card.py` |
| Functional tests | `test_prompt_behaviour.py` · `test_aiming_behaviour.py` · `test_description_quality.py` · `test_digest_writing.py` · `test_timezone_prompt_behaviour.py` |
| Quality harness | `python -m backend.cli.evaluate_discovery_ranking` |

**What the model decides:** the subject of each search, the vector a candidate is
scored against, the order of an already-qualified shortlist, and how a find
reads. **What is decided for it:** what qualifies. Novelty, familiarity,
lead time, geography and the request budget are deterministic, because a sweep
runs unattended and a sampled judgement would make the same feed produce
different results on different days.

**The message is written, not assembled.** `digesting.py` composes the greeting
and one line per find; `discovery/digest.py` supplies the facts and attaches the
links. Two things stay in code because a 4B model must not hold them: the clock,
rendered in the reader's zone and required back verbatim, after a concert listed
for Oct 3 was once announced as "Fri Oct 2, 8:00pm"; and every URL, which comes
from the typed record and is never asked of the model, because this string
reaches third parties over a channel that cannot be unsent. With no runtime the
assembled shape still ships — worse to read, and it always arrives.

**The first positive signal.** A digest is sent as one message per find, so each
carries a tapback — 👍 or 👎 on the bubble itself. That is the only thing Scout
knows that means *more like that one*; dismissal means "I already knew this" and
silence means nothing at all. Reactions are recorded in `discovery_sent_finds`
against the same `item_digest` novelty and familiarity key on, and **nothing in
ranking reads them yet**: a loop trained on a handful of tapbacks would learn
noise. The cost is a burst of notifications instead of one.

**Measured weakness: aiming barely personalises.** Given an approved fact
bearing on an interest, the fact reaches the profile 2 times in 5 and the search
subject 0 times in 5. The previous prompt scored 1 and 1, and its single subject
win was "Board Games" — the label most resembling the worked example it was
taught with, "Run Clubs". Both prompts' examples were therefore doing more
priming than teaching, and the test that used to pass was rewarding it. The
examples are now interests nobody here holds, so a passing case is a general
one. The gap is recorded as a non-strict `xfail` in `test_aiming_behaviour.py`
rather than loosened, because the module's whole premise is that a sweep is
aimed at someone.

## Deck — presentations

Plans and builds editable decks in its own worker, so a long build never blocks
the conversation.

| | |
| --- | --- |
| Registry id | `presentation` |
| Diagram | [agent-deck.svg](diagrams/agent-deck.svg) · [source](diagrams/agent-deck.mmd) |
| Subsystem view | [presentation-subsystem.svg](diagrams/presentation-subsystem.svg) |
| Agent folder | `backend/agents/deck/` |
| Domain package | `backend/presentations/` |
| Prompts | `prompts.py` — five: deck plan, outline, slide content, new slide, revision |
| Card | `agents/deck/card.py` |
| Functional tests | `test_deck_prompt_behaviour.py` |

**What the model decides:** content and slide shape. **What is decided for it:**
geometry, storage, validation and promotion. Every figure must come from a
supplied source; where none supports a number, the contract asks for a layout
that needs none, because an invented statistic is the most damaging output this
system has.

## Diagram — architecture drawings

Turns a request into an editable Mermaid diagram.

| | |
| --- | --- |
| Registry id | not listed in the Agents tab |
| Diagram | [agent-diagram.svg](diagrams/agent-diagram.svg) · [source](diagrams/agent-diagram.mmd) |
| Agent folder | `backend/agents/diagram/` |
| Domain package | `backend/artifacts/` |
| Prompts | `prompts.py` — one |
| Functional tests | `test_prompt_behaviour.py` — six request shapes |

**What the model decides:** the Mermaid. **What is decided for it:** whether it
is allowed to render. The prompt asks for bounds — no HTML, no click or init
directives, no URLs, forty nodes, eighty edges — and
`validate_diagram_specification` enforces them, retrying once and refusing
rather than shipping something that will not draw.

Known defect, narrowed: asked for a **state machine** the model returns
`"source": "stateDiagram-v2"` with no body, so the request produces nothing.
That is the model failing the task rather than mis-encoding it, so it is
recorded and excluded from the test set rather than papered over. Flowcharts,
which is what nearly every request asks for, run 6/6.

What this used to say — that the failure was intermittent — was itself the bug.
The call ran at the provider default temperature, so the same eight requests
scored 0/8 and then 3/8 with nothing changed, which reads as flakiness. Made
greedy, the real defect was visible in one run: inside a JSON string the model
joins its Mermaid lines with `<br/>` rather than escaped newlines, and a
structurally correct graph was rejected whole. Normalizing that break, as `\r\n`
and code fences already were, took the set to 7/8.

## Memory capture — what is worth remembering

Reads each chat turn and classifies typed candidates, auto-saved with no
approval step.

| | |
| --- | --- |
| Registry id | not listed; it is a step in every conversation, not a thing you start |
| Diagram | [agent-memory.svg](diagrams/agent-memory.svg) · [source](diagrams/agent-memory.mmd) |
| Subsystem view | [memory-subsystem.svg](diagrams/memory-subsystem.svg) |
| Agent folder | `backend/agents/memory/` |
| Domain package | `backend/memory/` |
| Prompts | `prompts.py` — one |
| Functional tests | `test_prompt_behaviour.py`, with a positive control · `test_interest_capture_behaviour.py` · `test_memory_save_state_behaviour.py` |

**What the model decides:** what to classify as worth remembering. **What is
decided for it:** whether anything is written. It has no persistence
authority; `ConversationService` writes each candidate to its typed store and
projects a Scout fact where applicable, in the same turn, before the reply is
generated — no approval step gates the write. A per-candidate save failure is
dropped and logged, costing only that one candidate.

## Trading — the personal autopsy

Reads a person's own trading history — uploaded statements, journals, notes —
and names what repeats, what it has cost, and what to stop, start, and keep.

| | |
| --- | --- |
| Registry id | `trading` |
| Diagram | [agent-trading.svg](diagrams/agent-trading.svg) · [source](diagrams/agent-trading.mmd) |
| Agent folder | `backend/agents/trading/` |
| Domain package | `backend/memory/` (reads the person's knowledge store) |
| Prompts | `prompts/trading/autopsy.md` — one |
| Card | `agents/trading/card.py` |
| Functional tests | `test_trading_autopsy_behaviour.py` |

**What the model decides:** the behaviours that repeat in a person's record,
which of their stated costs belong to which behaviour, and the stop/start/keep
plan. **What is decided for it:** nothing numeric. A cost may only be stated
when a number is actually present in the passages; a behaviour only counts as a
pattern when it appears more than once. The numbers in the post-mortem come
from the record, never from the model.

**Why it is structured this way.** A single loss proves nothing; a behaviour
that shows up again and again is what a person can change. The prompt is
written to name the behaviour ("cut winners early", "added to a losing
position"), not the person's character, because a post-mortem that reads as
blame is one nobody acts on. It decides nothing for the person and trades
nothing — it reports what their own record keeps doing.

## Not agents — model calls that route

Both use a model and neither produces work, so neither has a folder or a card.
Listed so the distinction is a decision rather than an oversight.

| Policy | Decides | Lives in |
| --- | --- | --- |
| Visual-memory selection | which offered owned image descriptions materially help answer the current message | `backend/agents/vision/memory.py` |
| Upload inspection | edit versus question, per-item visual confidence/evidence, durable observation, immediate answer, evidence sufficiency, grounding value, and stronger-reasoning need | `backend/agents/vision/upload.py` |

## Every model call, and what it costs

One text model serves all of it: DeepSeek-V4-Flash, served by vLLM
tensor-parallel across the two DGX Sparks. The role-specific settings —
`MAIN_LLM_MODEL`, `ROUTING_LLM_MODEL`, `PRESENTATION_LLM_MODEL`,
`DIAGRAM_LLM_MODEL`, `MEMORY_PROPOSAL_LLM_MODEL` — are pinned to it
explicitly in compose so that changing one never silently moves another;
Scout has no role setting and follows the main role. Vision is the one
separate model (Qwen3-VL-8B on spark2), because DeepSeek cannot read pixels.

The constraint that decides this is memory: DeepSeek holds about 97 GiB on
*each* Spark, so "a better model for this call" still means replacing the one
model for every text call, not adding one - and nothing moves a model at
request time, because over-allocating a Spark hangs it (ADR 0015). Every
decision call below decodes at temperature 0 inside a grammar; the memory
classifier's budget was raised from 256 to 1,024 tokens after real turns
were truncated mid-JSON.

| Agent | Call | Tokens | Temp | Grammar |
| --- | --- | --- | --- | --- |
| Scout | `aiming.py` — search subjects and vectors | 1024 | 0.0 | yes |
| Scout | `reranking.py` — order a qualified shortlist | 256 | 0.0 | yes |
| Scout | `describing.py` — how a find reads | 160 | 0.0 | yes |
| Scout | `digesting.py` — the message a subscriber gets | 700 | 0.0 | yes |
| Scout | `place_suggest.py` — place completion | 220 | 0.0 | yes |
| Scout | `timezones.py` — place to IANA zone | 32 | 0.0 | yes |
| Deck | `provider.py` — plan, outline, slide, new slide, revision | caller | **default** | yes |
| Diagram | `diagram.py` — Mermaid source | 2048 | 0.0 | yes |
| Memory capture | `proposal_agent.py` — what to save (never a schedule: Scout's cadence has one writer, the `scout_schedule` tool); sees the assistant's previous reply only to resolve "this" | 1024 | 0.0 | yes |
| Trading | `autopsy.py` — what a person's own history keeps doing, its costs, and the stop/start/keep plan | 1024 | 0.0 | yes |
| *(not an agent)* | `agents/vision/memory.py` — select relevant offered visual memories | 128 | 0.0 | yes |
| *(not an agent)* | `agents/vision/upload.py` — one structured primary image inspection | 512 | 0.0 | yes |
| *(not an agent)* | optional specialist retry after `model_uncertain` | 512 | 0.0 | yes |
| *(not an agent)* | `image_style_service.py` — style from profile | 160 | default | no |

**Temp matters more than it looks.** Everything reproducible runs greedy.
Deck's two call sites and the image-style call still run at the provider
default, so the same request can produce a different deck each time. Diagram
did too, and it hid a real defect: eight identical requests scored 0/8 and then
3/8 with nothing changed, which reads as flakiness rather than as a bug.

**Where the model is genuinely weak.** Diagram is the only call with a measured
failure that survives a correct prompt: asked for a state machine it returns
`"source": "stateDiagram-v2"` with no body. Flowcharts, which is what nearly
every request is, run 6/6 in the functional tests. Everything else here is held
by functional tests against the running model.

## Reviewer — a read-only review of one commit

The first agent to run on the durable-run runtime
([RUNS_ARCHITECTURE.md](RUNS_ARCHITECTURE.md)). Given a commit, it reads
the summary, the diff and the files worth reading in full - every read
through the `repo` MCP server, which is rooted by environment at one
repository and exposes nothing but reads - then writes findings and keeps
only those whose quoted evidence is actually the cited line of a file it
read. It changes nothing.

| | |
| --- | --- |
| Registry id | `review` |
| Run kind | `code_review` (`backend/workers/run_worker.py::WORLDS`) |
| Diagram | [agent-review.svg](diagrams/agent-review.svg) · [source](diagrams/agent-review.mmd) |
| Agent folder | `backend/agents/review/` |
| Domain package | `backend/runs/` (the runtime) · `backend/mcp/servers/repo.py` (the window) |
| Prompts | `prompts/review/choose_files.md` · `prompts/review/findings.md` |
| Card | `agents/review/card.py` |
| Functional tests | `test_code_review_behaviour.py` |
| Entry point | `REPO_MCP_ROOT=<repo> python -m backend.cli.review_commit --commit <sha> --user <id>` |

**What the model decides:** which changed files need reading in full, and
what is wrong with the change - file, line, severity, and the line of code
that shows it. **What is decided for it:** the order of the stages, that
every read is a read, and whether a finding stands: `ReviewWorld._check`
drops one that names a file the commit did not change or the review did not
read, a line outside what was read, or evidence that is not that line, and
records why. An injected instruction in the repository can change none of
that, because the world has no other tools and the stages cannot be
reordered; the prompts additionally frame repository text as material under
review.

**Not yet:** a trigger from chat or from a repository event (the CLI creates
the run), a report artifact beyond the run's result, and the measured
precision floor on a labelled corpus of diffs the plan calls for.

## Security — a scoped, read-only investigation of one commit

The first shape of the security agent (Phase 6 of
[AGENT_PLATFORM_PLAN.md](AGENT_PLATFORM_PLAN.md)): the reviewer's stages
with a different question - does this change widen what an attacker can do -
plus deterministic searches of the commit for lines shaped like a secret or
a dangerous call, which the model then judges with the code around them.
The scope is checked before anything is read: a run naming an asset not in
`SECURITY_AUTHORIZED_ASSETS` fails with the refusal recorded and no tool
called.

| | |
| --- | --- |
| Registry id | `security` |
| Run kind | `security_review` (`backend/workers/run_worker.py::WORLDS`) |
| Diagram | [agent-security.svg](diagrams/agent-security.svg) · [source](diagrams/agent-security.mmd) |
| Agent folder | `backend/agents/security/` |
| Domain package | `backend/runs/` · `backend/mcp/servers/repo.py` · the reviewer's stages in `backend/agents/review/world.py` |
| Prompts | `prompts/security/findings.md`, `prompts/security/judge_hits.md` (the reviewer's `review/choose_files` for which files to read) |
| Card | `agents/security/card.py` |
| Functional tests | `test_security_review_behaviour.py` |
| Entry point | `python -m backend.cli.review_commit --kind security_review --asset <name> --commit <sha> --user <id>` |

**What the model decides:** which files to read in full, whether each
flagged line and each hunk is a weakness, and - for any flagged line its
findings left out - a verdict on that line with the code around it: a
finding, checked like every other, or a dismissal with a reason
(`security/judge_hits`). **What is decided for it:** the scope, the stages,
that every tool is a read, which shapes are searched (`SECRET_SHAPES`,
`DANGEROUS_CALL_SHAPES` - shapes, never intent), whether a finding stands
(the reviewer's evidence check), and that every flagged line appears in the
report as reported, dismissed or unjudged. The card reads `needs_setup`
until an asset is authorized.

**Not yet:** alert enrichment and an asset inventory beyond the repositories
the repo server can be rooted at; remediation tools (they will carry
`approval: always`); a labelled corpus and a precision floor.

## Adding an agent

1. `backend/agents/<name>/` with `prompts.py`, and `card.py` if it belongs in the
   Agents tab.
2. Register the card in `agents/registry.py` — one entry in `DESCRIBERS`.
3. Do **not** re-export from the package `__init__`. A re-export makes importing
   the prompts pull the agent, which pulls the provider that imports the
   prompts; that cycle has already broken this repository once.
4. Add `docs/diagrams/agent-<name>.mmd`, register it in
   `frontend/scripts/architecture-diagram.mjs` and in
   [the diagram catalog](diagrams/README.md), and render.
5. Add a functional test in `backend/tests/functional/`. A prompt without one is
   an untested feature, however many structural tests surround it.
6. Add a row here.
