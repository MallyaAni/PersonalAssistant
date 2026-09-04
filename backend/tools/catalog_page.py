"""The tool catalogue as a page, rendered from the rows themselves.

A hand-written list of what this assistant can do is stale the first time a
tool is renamed, and nothing fails when it happens: the page just quietly
describes a system that no longer exists. Fifteen built-in tools were spread
across nine documents by mention, with no page that named them all and no
check that any mention was still true.

So the page is generated. `render()` reads the same `BuiltinTool` rows the
router is offered and the reply prompt describes itself from, and a test
compares the committed file against a fresh render. Renaming a tool without
regenerating fails that test, which is the only version of this document that
stays true.
"""
from __future__ import annotations

from backend.tools.base import BuiltinTool
from backend.tools.registry import (
    builtin_tools,
    core_tool_names,
    gated_tools,
    picture_tool_names,
)
from backend.tools.search import SEARCH_TOOL

HEADING = """# What the assistant can do

Generated from `backend/tools/registry.py` by
`python -m backend.cli.generate_tool_catalog`. Do not edit by hand: a test
compares this file against a fresh render, so an edit here is a failure there.

Every row below is one tool the router may call for a turn. The router is
offered them all and picks at most one per step; calling none is a normal
outcome and means the turn is answered as an ordinary reply.
"""

LEGEND = """
## How to read the columns

- **Loaded** says when the tool's full definition is put in front of the
  router. `always` is the handful most turns actually use. `with a picture`
  loads only when one is in view, since the interface state already decides
  whether the tool can be used. `catalogued` means it is represented by a
  one-line index entry and fetched on demand, which is what keeps accuracy
  from falling away as this list grows.
- **Arguments** are what the model must fill in. A tool that takes a subject
  or an instruction is one the model has to state its reading of the request
  for, which is what makes a mistaken choice visible before the turn is spent.
"""


# When the router is shown this tool's full definition.
def _loaded(row: BuiltinTool, core: frozenset[str], pictures: frozenset[str]) -> str:
    if row.name in core:
        return "always"
    if row.name in pictures:
        return "with a picture"
    return "catalogued"


def _arguments(row: BuiltinTool) -> str:
    properties = (row.schema or {}).get("properties") or {}
    return ", ".join(f"`{name}`" for name in sorted(properties)) or "none"


# One sentence of the router's own account of the tool. The full text is the
# router's prompt and runs to paragraphs; the page names where to read it
# rather than reprinting it and drifting from it.
def _gist(row: BuiltinTool) -> str:
    first = row.description.strip().split(". ")[0].strip().rstrip(".")
    return " ".join(first.split())


def render() -> str:
    rows = builtin_tools(enabled=tuple(gated_tools().values()))
    core = core_tool_names()
    pictures = picture_tool_names()
    gated = gated_tools()

    families: dict[str, list[BuiltinTool]] = {}
    for row in rows:
        families.setdefault(row.family or "other", []).append(row)

    parts = [HEADING, LEGEND]
    parts.append(
        "\n## Searching the web\n\n"
        f"`{SEARCH_TOOL}` is not a built-in row. It is assembled from whichever "
        "search server is wired at the time, so it is always offered and never "
        "catalogued, and its arguments come from that server rather than from "
        "this repository.\n"
    )
    for family in sorted(families):
        parts.append(f"\n## {family.capitalize()}\n")
        parts.append("| tool | what it does | arguments | loaded |")
        parts.append("| --- | --- | --- | --- |")
        for row in sorted(families[family], key=lambda item: item.name):
            note = f" *(needs the {gated[row.name]} service)*" if row.name in gated else ""
            parts.append(
                f"| `{row.name}`{note} | {_gist(row)} | {_arguments(row)} "
                f"| {_loaded(row, core, pictures)} |"
            )
        parts.append("")
    parts.append(
        "\n## Skills\n\n"
        "A person's saved skills are offered as tools too, one per skill, named "
        "`skill__<name>`. They are not listed here because they differ per "
        "person: `save_skill` creates one and `manage_skills` lists or removes "
        "them.\n"
    )
    return "\n".join(parts).rstrip() + "\n"
