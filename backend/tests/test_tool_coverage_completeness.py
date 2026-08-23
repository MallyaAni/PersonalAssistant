"""Every tool the router can pick must be visible to the thing that measures it.

This file exists so one specific failure cannot happen twice.

`schedule_task`, `manage_tasks`, `save_skill` and `manage_skills` were added to
`backend/tools/registry.py` and offered to the router for weeks with no routing
coverage at all. That was not an oversight anybody could have spotted by
reading the eval set, because the omission concealed itself in two places:

  - `TOOL_NAMES` did not list them, and
    `test_every_case_is_labelled_with_a_tool_that_exists` rejects any case
    whose expectation `TOOL_NAMES` omits - so a case *could not* be written
    for them; the attempt failed as a typo.
  - `_ACTION_TOOL` in `backend/cli/evaluate_tool_selection.py` did not map
    their action types, so `tool_of()` returned `"none"` for every decision
    they made. Correct choices and wrong ones alike were scored as "the router
    picked no tool", which quietly *inflated* the no-tool number that the
    accuracy floors are computed from.

The consequence reached a person: asked to move a reminder, the assistant said
it had, and the row was untouched, because the operation to move one did not
exist and nothing measured whether it was ever chosen.

These assertions are structural on purpose - they need no model and no network,
so they run in the ordinary suite on every commit rather than only inside the
deploy gate. Adding a ninth tool without cases fails here, immediately, with a
message that says what to add.
"""

import pytest

from backend.cli.evaluate_tool_selection import _ACTION_TOOL, tool_of
from backend.services.tool_selection_cases import (
    PER_TOOL_ACCURACY_FLOORS,
    SELECTION_CASES,
    TOOL_NAMES,
)
from backend.tools.registry import builtin_tools

# Every gate flag on, so a capability cannot hide behind being switched off.
ALL_GATES = ("diagram", "presentation")


def _registered_names() -> set[str]:
    return {tool.name for tool in builtin_tools(ALL_GATES)}


# Each built-in must be nameable as an expectation, or no case can be written.
def test_every_registered_tool_is_a_valid_case_label():
    missing = sorted(_registered_names() - set(TOOL_NAMES))
    assert not missing, (
        f"these tools are offered to the router but are not in TOOL_NAMES, so "
        f"a labelled case naming them is rejected as a typo: {missing}. Add "
        f"them to backend/services/tool_selection_cases.py."
    )


# Each built-in must actually be exercised, not merely be nameable.
def test_every_registered_tool_has_labelled_cases():
    labelled = {case.expected for case in SELECTION_CASES}
    uncovered = sorted(_registered_names() - labelled)
    assert not uncovered, (
        f"these tools have no labelled routing case, so the matrix cannot "
        f"report whether the router ever picks them: {uncovered}. Add cases to "
        f"SELECTION_CASES covering what a person would actually say."
    )


# A capability with one case is measured; a floor makes the measurement bite.
def test_every_registered_tool_has_a_measured_floor():
    unfloored = sorted(_registered_names() - set(PER_TOOL_ACCURACY_FLOORS))
    assert not unfloored, (
        f"these tools have cases but no entry in PER_TOOL_ACCURACY_FLOORS, so "
        f"their collapse is hidden by the aggregate: {unfloored}."
    )


# The scorer must recognise what the selector returns, or every decision that
# tool makes is silently counted as "no tool" - the bug that hid the original.
def test_every_action_type_is_scored_as_itself():
    from backend.tools import registry

    unmapped = []
    for module in registry._MODULES:
        parse = getattr(module, "parse", None)
        if parse is None:
            continue
        # The action type each module produces, discovered from its own
        # annotation rather than from a list here that could drift the same way.
        produced = getattr(parse, "__annotations__", {}).get("return")
        if produced is None:
            continue
        for candidate in _ACTION_TOOL:
            if candidate.__name__ in str(produced):
                if _ACTION_TOOL[candidate] != module.NAME:
                    unmapped.append(
                        f"{candidate.__name__} maps to "
                        f"{_ACTION_TOOL[candidate]!r}, expected {module.NAME!r}"
                    )
                break
        else:
            unmapped.append(
                f"{module.NAME}: no entry in _ACTION_TOOL for {produced}"
            )

    assert not unmapped, (
        "backend/cli/evaluate_tool_selection.py scores these incorrectly, so "
        "their decisions are counted as no-tool: " + "; ".join(unmapped)
    )


# The scorer's own fallback is what made the gap silent; pin that it is a
# fallback for genuinely unknown objects, not for a tool someone forgot.
def test_unknown_actions_still_fall_back_to_no_tool():
    class NotAnAction:
        pass

    assert tool_of(NotAnAction()) == "none"
    assert tool_of(None) == "none"


# Named tools are the router's whole vocabulary; a duplicate would make one
# unreachable and the matrix would report the survivor's score for both.
def test_tool_names_are_unique():
    assert len(TOOL_NAMES) == len(set(TOOL_NAMES)), TOOL_NAMES


@pytest.mark.parametrize("tool", sorted(_registered_names()))
def test_each_tool_has_more_than_a_token_case(tool: str):
    """One case proves a tool is nameable; it does not measure a router."""
    count = sum(1 for case in SELECTION_CASES if case.expected == tool)
    assert count >= 1, f"{tool} has no cases"
