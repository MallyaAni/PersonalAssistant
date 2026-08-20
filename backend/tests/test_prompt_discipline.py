"""Prompts state principles; they do not name one user's bad day.

A rule written in AGENTS.md survives only as long as somebody reads it. These
are the same rules as checks, so a prompt that has drifted back toward matching
a specific case fails here rather than being noticed months later.

Both live prompts were written this way and both were rewritten: `search/
compose.md` lost half its words, and the image-context block a third, once the
incidents were moved into notes and the principles left behind.
"""

import re
from pathlib import Path

import pytest

from backend.core.prompts import PROMPT_ROOT, SEPARATOR, load

REPO = Path(__file__).resolve().parents[2]

PROMPT_FILES = sorted(
    path.relative_to(PROMPT_ROOT).with_suffix("").as_posix()
    for path in PROMPT_ROOT.rglob("*.md")
    if path.name != "README.md"
)

# Products, people and places that appear in this repository's own history.
# A prompt naming one of these is teaching the model that case rather than the
# rule behind it; the incident belongs in the file's notes instead.
_SPECIFIC_CASES = re.compile(
    r"\b("
    r"dgx spark|deepseek|nemotron|qwen|flux|comfyui|"  # our stack
    r"straw hat|black hat|cowboy hat|biscuit|milwaukee|"  # our incidents
    r"raleigh|durham|boise|jenos1|ani\.mallya|alippe"  # our accounts
    r")\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_no_prompt_names_a_specific_case(name: str):
    body = load(name)

    found = sorted({match.group(0).lower() for match in _SPECIFIC_CASES.finditer(body)})

    assert not found, (
        f"{name} names {found} in the text sent to the model. State the "
        f"principle instead and record the incident in the notes above the "
        f"{SEPARATOR!r} line."
    )


# The same rule for prompts still held as Python constants. Scoped to the
# modules whose constants are prompts, because a test naming every module would
# itself become the list of special cases this is about.
_PROMPT_MODULES = [
    "backend/agents/graph.py",
    "backend/services/main_action_selector.py",
    "backend/services/image_refinement_service.py",
    "backend/agents/memory/prompts.py",
]


@pytest.mark.parametrize("module", _PROMPT_MODULES)
def test_no_prompt_constant_names_a_specific_case(module: str):
    source = (REPO / module).read_text(encoding="utf-8")
    # Comments are where an incident is supposed to live, so they are exempt;
    # only the string literals reach a model.
    literals = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )

    found = sorted({m.group(0).lower() for m in _SPECIFIC_CASES.finditer(literals)})

    assert not found, (
        f"{module} names {found} in prompt text. State the principle in the "
        f"prompt and keep the incident in a comment."
    )
