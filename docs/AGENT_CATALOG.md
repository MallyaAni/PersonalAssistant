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
| Prompts | `aiming.py` · `reranking.py` · `describing.py` · `place_suggest.py` |
| Card | `agents/scout/card.py` |
| Functional tests | `backend/tests/functional/test_prompt_behaviour.py` |
| Quality harness | `python -m backend.cli.evaluate_discovery_ranking` |

**What the model decides:** the subject of each search, the vector a candidate is
scored against, the order of an already-qualified shortlist, and how a find
reads. **What is decided for it:** what qualifies. Novelty, familiarity,
lead time, geography and the request budget are deterministic, because a sweep
runs unattended and a sampled judgement would make the same feed produce
different results on different days.

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
| Functional tests | `backend/tests/functional/test_deck_prompt_behaviour.py` |

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
| Functional tests | `test_prompt_behaviour.py`, currently `xfail` |

**What the model decides:** the Mermaid. **What is decided for it:** whether it
is allowed to render. The prompt asks for bounds — no HTML, no click or init
directives, no URLs, forty nodes, eighty edges — and
`validate_diagram_specification` enforces them, retrying once and refusing
rather than shipping something that will not draw.

Known defect: on some requests the model returns markup the renderer cannot
draw, and the retry fails validation outright, so the request produces nothing.
It is intermittent rather than constant.

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
| Functional tests | `test_prompt_behaviour.py`, with a positive control |

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
