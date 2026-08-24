# Prompts

Every instruction this system sends to a model, and where it comes from.

A prompt is the part of this system most worth changing and the part least
worth editing Python to change. Files here are the live wording: edit one,
restart the backend, and the new text is what runs. There is no in-code copy
to fall back on, so a missing or empty file fails at startup rather than
quietly reverting to something nobody is reading.

## How a file is laid out

Every file is notes, then one loud separator, then the prompt:

```
...notes for whoever is editing...

===== PROMPT BELOW — everything under this line is sent to the model =====

You are AniOS, a helpful local personal assistant...
```

Everything above that line is for you, not for the model: what the prompt
drives, which model runs it, what placeholders it must fill, and what has
actually gone wrong when its wording was off. Everything below the line is sent
verbatim.

A file with no separator is refused rather than guessed at - guessing is how
notes end up being sent to a model.

Placeholders are `{name}`. A prompt that names one the caller does not supply
raises rather than reaching a model as a literal brace, so adding a placeholder
means editing the call site too.

## After editing

```bash
docker compose up -d --build backend        # the image copies this folder
python -m pytest backend/tests/test_prompt_files.py -q
```

Changing wording is not verifiable by reading it. The measurable ones:

```bash
python -m backend.cli.evaluate_tool_selection    # routing accuracy, confusion matrix
python -m pytest backend/tests/functional -q     # real model, real MCP, real ComfyUI
```

## Externalised — edit these directly

| Prompt | Drives |
| --- | --- |
| `search/compose.md` | The first web search query of a turn |
| `vision/observe.md` | The canonical description of an image; every later pass reads it instead of the pixels |
| `vision/question.md` | Answering a direct question about an image |
| `vision/reason.md` | Reasoning over what the vision pass saw, on the reply model |
| `vision/upload_inspection.md` | The one-shot inspection of a fresh upload |
| `vision/search_grounding.md` | Whether an image warrants a web search, and for what |
| `image_intent/classify.md` | Edit request or question about the picture |
| `image_intent/context.md` | Recent conversation appended when the message alone is ambiguous |
| `referent/system.md` | Which owned thing "that one" points at, across modalities |
| `style/distill.md` | Distilling a durable per-user image style from feedback |
| `memory/proposal.md` | What from one utterance is worth remembering |
| `memory/digest.md` | Compressing a stretch of conversation into notes |
| `deck/plan.md` | The outline request for a whole deck |
| `deck/slide.md` | Writing one slide from the approved outline |
| `deck/new_slide.md` | Adding a slide without disturbing the rest |
| `deck/revision.md` | Revising one slide from feedback |
| `diagram/system.md` | Turning a subject into Mermaid source |
| `scout/aim.md` | Aiming the weekly search at one person's interests |
| `scout/describe.md` | Typing the facts of one scraped happening |
| `scout/digest_message.md` | The weekly Scout message itself |
| `scout/place_suggest.md` | Completing a town or city name being typed |
| `scout/rerank.md` | Ordering the shortlist for one person |
| `scout/timezone.md` | Naming the IANA timezone of a place |
| `refinement/keep_scene.md` | What an image edit must preserve |
| `search/another_angle.md` | The unconditional follow-up search |
| `search/refine.md` | Whether to keep searching, and for what |
| `routing/select_action.md` | **What every turn does**: search, picture, edit, diagram, deck, an MCP tool, or nothing. Runs on the 4B routing model |
| `welcome/system.md` | The unprompted introduction a newly approved person receives. Written from the live capability list rather than stored, so it cannot promise a tool that stopped being offered |
| `reply/system.md` | **Every chat reply.** The assistant's whole instruction: what it may guess, when to ask, its training boundary, what AniOS can do, and what it may claim to have saved |

## Still in Python

These have not been moved yet. They are listed so the full surface is visible;
each is a module-level constant, usually named `_SYSTEM` or `_PROMPT`.

| Where | Drives |
| --- | --- |
| `backend/agents/graph.py` | The blocks rendered *into* `reply/system.md`: recalled images, search results, tool results, personal memory |
| `backend/services/main_action_selector.py` | Each built-in tool's own description - kept beside the tool so one wording serves both routing and what the assistant says it can do |

Moving one here is mechanical: create the file with a header, replace the
constant with its name, and call `render()` instead of `.format()`.
