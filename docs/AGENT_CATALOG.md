# Agents

Every specialized agent in AniOS, what it decides, and where its parts live.

An agent here is something that **produces work a person asked for**, using a
model, and reports itself to the Agents tab. A model call that only routes — the
search-freshness classifier, the image-recall classifier — is a policy, not an
agent, and is listed at the bottom so the distinction stays deliberate rather
than accidental.

Each agent owns a folder under `backend/agents/<name>/`. The rule that puts it
there: **the mechanism for calling a model is shared and reusable; the prompt
never is.** A prompt is the agent's judgement written out, and it differs per
agent even when the calling code is identical. The domain package holds the
machinery the agent drives.

## Scout — ambient discovery

Finds things happening near you that match what you like, on a schedule, and
turns each one into something you can act on.

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

Reads each chat turn and offers typed candidates for saving.

| | |
| --- | --- |
| Registry id | not listed; it is a step in every conversation, not a thing you start |
| Diagram | [agent-memory.svg](diagrams/agent-memory.svg) · [source](diagrams/agent-memory.mmd) |
| Subsystem view | [memory-subsystem.svg](diagrams/memory-subsystem.svg) |
| Agent folder | `backend/agents/memory/` |
| Domain package | `backend/memory/` |
| Prompts | `prompts.py` — one |
| Functional tests | `test_prompt_behaviour.py`, with a positive control · `test_interest_capture_behaviour.py` |

**What the model decides:** what to offer. **What is decided for it:** whether
anything is written. It has no persistence authority; every candidate appears on
an approval card, and only approval writes a fact and its Scout projection, in
one transaction.

## Not agents — model calls that route

Both use a model and neither produces work, so neither has a folder or a card.
Listed so the distinction is a decision rather than an oversight.

| Policy | Decides | Lives in |
| --- | --- | --- |
| Search freshness | whether a turn needs the web | `backend/search/classifier.py` |
| Image recall | whether a query names a stored image | `backend/artifacts/image_recall_classifier.py` |
| Visual-memory selection | which offered owned image descriptions materially help answer the current message | `backend/agents/vision/memory.py` |

## Every model call, and what it costs

One model serves all of it: `LLM_MODEL=qwen/qwen3.5-4b` on vLLM. The
role-specific settings — `MAIN_LLM_MODEL`, `PRESENTATION_LLM_MODEL`,
`DIAGRAM_LLM_MODEL`, `MEMORY_PROPOSAL_LLM_MODEL` — all resolve to that same
model today, so the routing exists but selects nothing. Scout has no role
setting at all.

The constraint that decides this is the card: an RTX 5080 has 16 GB and the
serving stack already holds about 13 GB. There is no room for a second resident
model, so "a better model for this call" means replacing the one model for
every call, not adding one.

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
| Memory capture | `proposal_agent.py` — what to offer saving | 256 | 0.0 | yes |
| *(not an agent)* | `search/classifier.py` — does this need fresh search | 4 | 0.0 | yes |
| *(not an agent)* | `image_recall_classifier.py` — is this about an old image | 4 | 0.0 | yes |
| *(not an agent)* | `agents/vision/memory.py` — select relevant offered visual memories | 128 | 0.0 | yes |
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
