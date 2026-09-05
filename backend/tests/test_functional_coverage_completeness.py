"""Everything built has its functional proof - mechanically.

The weather tool had no test that called it with real inputs; every prompt
was pinned by habit or not at all; two capabilities were never walked over
HTTP. This fails a build the moment a tool, a capability, or a prompt has
no proof of the kind AGENTS.md's completion rule names. Debt is allowed only
when it is declared out loud: a prompt whose header says
`pinned by: none yet - <reason>` is listed, not hidden.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.cli.sweep_journeys import JOURNEYS
from backend.tools import registry

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONAL = ROOT / "backend" / "tests" / "functional"
PROMPTS = ROOT / "prompts"
INTERNET_TOOLS = ("search_web", "get_weather", "search_credits")

# Capabilities the sweep cannot walk as a guest turn, with the reason and
# where they are proven instead.
JOURNEY_EXEMPT = {
    "Edits to a shared file": "needs a Word file shared in the conversation; the sweep uploads nothing - walked by the live acceptance (scripts kept on the Spark) and the router functional test",
    "Presentations": "a deck build runs minutes in the presentation worker; frontend/e2e/presentations.spec.ts walks it",
    "Background runs": "needs a run parked on an approval, which the sweep cannot stage over HTTP; the router and reply are walked by functional/test_run_answers_behaviour.py and the answer path by test_run_answers.py on the real schema",
}


def _functional_sources() -> dict[str, str]:
    return {p.name: p.read_text() for p in FUNCTIONAL.glob("test_*.py")}


def _ways_to_name(module) -> set[str]:
    names = {module.NAME, module.TOOL.label}
    produced = str(getattr(getattr(module, "parse", None), "__annotations__", {}).get("return", ""))
    # "ShowImageAction | None" as a string, or a typing object whose text
    # carries the module path: keep the class name either way.
    for part in produced.replace("|", " ").replace("[", " ").replace("]", " ").replace(",", " ").split():
        leaf = part.strip().strip("'\"").rsplit(".", 1)[-1]
        if leaf.endswith("Action"):
            names.add(leaf)
    return names


def test_every_tool_has_a_live_functional_test():
    sources = _functional_sources()
    missing = [
        module.NAME
        for module in registry._MODULES
        if not any(any(way in body for way in _ways_to_name(module)) for body in sources.values())
    ] + [name for name in INTERNET_TOOLS if not any(name in body for body in sources.values())]
    assert not missing, (
        f"no functional test names these tools: {missing} - add a test that calls "
        "the tool with real inputs (backend.cli.real_utterances for the phrasings)"
    )


def test_every_capability_is_walked_by_a_sweep_journey():
    walked = {label for journey in JOURNEYS for label in journey.expect_action if label}
    labels = [module.TOOL.label for module in registry._MODULES]
    missing = [label for label in labels if label not in walked and label not in JOURNEY_EXEMPT]
    assert not missing, f"no sweep journey expects these routes over HTTP: {missing}"


def _sent_prompts() -> list[Path]:
    # README.md documents the marker; it is not a prompt.
    return sorted(p for p in PROMPTS.rglob("*.md") if p.name != "README.md" and "===== PROMPT BELOW" in p.read_text())


@pytest.mark.parametrize("prompt", _sent_prompts(), ids=lambda p: p.relative_to(PROMPTS).as_posix())
def test_every_prompt_declares_its_functional_pin(prompt: Path):
    header = prompt.read_text().split("===== PROMPT BELOW")[0]
    match = re.search(r"^pinned by:\s*(.+)$", header, flags=re.M)
    assert match, f"{prompt.relative_to(ROOT)}: no 'pinned by:' line in the header"
    declared = match.group(1).strip()
    if declared.startswith("none yet"):
        assert " - " in declared, "declare the reason: 'pinned by: none yet - <reason>'"
        return
    files = re.findall(r"test_[a-z0-9_]+\.py", declared)
    assert files, f"{prompt.relative_to(ROOT)}: 'pinned by:' names no test file"
    for name in files:
        assert (FUNCTIONAL / name).exists(), f"{prompt.relative_to(ROOT)}: pinned by {name}, which does not exist"


def test_declared_debt_is_visible():
    debt = []
    for prompt in _sent_prompts():
        header = prompt.read_text().split("===== PROMPT BELOW")[0]
        match = re.search(r"^pinned by:\s*none yet - (.+)$", header, flags=re.M)
        if match:
            debt.append(f"{prompt.relative_to(PROMPTS).with_suffix('').as_posix()}: {match.group(1).strip()}")
    # Not a failure - a list. It must match what NEXT_SESSION admits to.
    next_session = (ROOT / "docs" / "NEXT_SESSION.md").read_text()
    for item in debt:
        name = item.split(":")[0]
        assert name in next_session, f"{name} is unpinned but NEXT_SESSION does not say so"
