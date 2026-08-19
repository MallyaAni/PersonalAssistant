# Prompts

Every instruction this system sends to a model, and where it comes from.

A prompt is the part of this system most worth changing and the part least
worth editing Python to change. Files here are the live wording: edit one,
restart the backend, and the new text is what runs. There is no in-code copy
to fall back on, so a missing or empty file fails at startup rather than
quietly reverting to something nobody is reading.

## How a file is laid out

Everything above the `---` line is for you, not for the model: what the prompt
drives, which model runs it, what placeholders it must fill, and what has
actually gone wrong when its wording was off. Everything below the line is sent
verbatim.

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
| `search/another_angle.md` | The unconditional follow-up search |
| `search/refine.md` | Whether to keep searching, and for what |

## Still in Python

These have not been moved yet. They are listed so the full surface is visible;
each is a module-level constant, usually named `_SYSTEM` or `_PROMPT`.

| Where | Drives |
| --- | --- |
| `backend/agents/graph.py` | The assistant's reply prompt: date, training boundary, capabilities, agents, recalled images, search results, memory state |
| `backend/services/main_action_selector.py` | Which tool a turn uses, plus each built-in tool's description |
| `backend/services/image_refinement_service.py` | What the image editor is told to preserve or change |
| `backend/agents/vision/reasoning.py` | How an uploaded image is reasoned about after the vision pass |
| `backend/services/vision_analysis_service.py` | The one-shot inspection of a new upload |
| `backend/services/referent_resolution.py` | Which picture "that one" means |
| `backend/services/image_intent.py` | Whether an upload is a question about itself |
| `backend/agents/deck/prompts.py` | Presentation outline and per-slide writing |
| `backend/agents/scout/*.py` | Discovery: aiming, describing, digesting, place suggestion, reranking, timezones |
| `backend/memory/proposal_agent.py` | What is worth remembering from a turn |
| `backend/services/image_style_service.py` | The style suffix added to generated images |
| `backend/services/visual_search_grounding.py` | Turning an image into an outbound search subject |

Moving one here is mechanical: create the file with a header, replace the
constant with its name, and call `render()` instead of `.format()`.
