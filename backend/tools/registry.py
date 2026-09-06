"""Every built-in tool in the order the router offers them.

Adding a tool: write its module next to these (a `TOOL` row and a `parse`
function) and add it to `_MODULES`. The router, the reply prompt's
capability list, the status line the person sees, and the iMessage
waiting bubble all read from here.
"""

import random
from collections.abc import Iterable
from types import ModuleType
from typing import Any

from . import (
    create_diagram,
    create_document,
    discuss_image,
    edit_document,
    edit_image,
    generate_image,
    manage_check_ins,
    manage_runs,
    manage_skills,
    manage_tasks,
    presentation,
    save_skill,
    schedule_task,
    scout_schedule,
    search_history,
    send_event_links,
    show_image,
)
from .actions import (
    CreateDiagramAction,
    CreateDocumentAction,
    DelegateAction,
    DiscussImageAction,
    EditDocumentAction,
    EditImageAction,
    GenerateImageAction,
    MainAction,
    ManageCheckInsAction,
    ManageRunsAction,
    ManageSkillsAction,
    ManageTasksAction,
    RecallHistoryAction,
    SaveSkillAction,
    ScheduleTaskAction,
    ScoutScheduleAction,
    SearchAction,
    SendEventLinksAction,
    ShowImageAction,
    ToolboxAction,
    UseSkillAction,
)
from .base import BuiltinTool
from .contracts import UNDECLARED, EffectContract
from .search import (
    SEARCH_CAPABILITY,
    SEARCH_CONTRACT,
    SEARCH_CREDITS_CAPABILITY,
    SEARCH_CREDITS_CONTRACT,
    SEARCH_CREDITS_TOOL,
    SEARCH_CREDITS_WAITING,
    SEARCH_TOOL,
    SEARCH_WAITING,
    TOOLBOX_WAITING,
    WEATHER_CAPABILITY,
    WEATHER_CONTRACT,
    WEATHER_TOOL,
    WEATHER_WAITING,
)

_MODULES: tuple[ModuleType, ...] = (
    generate_image,
    edit_image,
    show_image,
    discuss_image,
    create_diagram,
    create_document,
    edit_document,
    presentation,
    search_history,
    schedule_task,
    manage_tasks,
    manage_check_ins,
    scout_schedule,
    save_skill,
    manage_skills,
    manage_runs,
    send_event_links,
)

# Rows whose availability depends on a service being wired, by name.
_GATED = {
    create_diagram.NAME: "diagram",
    presentation.NAME: "presentation",
}

_BY_NAME: dict[str, ModuleType] = {module.NAME: module for module in _MODULES}

# The tools that change what is scheduled or taught, rather than answering
# the turn. A firing must not be offered these: the instruction it carries
# reads exactly like a request to schedule ("remind me every morning to
# take my meds"), so the router calls schedule_task again and the person
# receives a confirmation instead of their reminder - plus a second task,
# then four. The cancel side is worse: it hard-deletes without asking.
# What the tool catalogue needs, read off the rows rather than written out
# again here: a name repeated in two places is a rename away from silently
# meaning nothing. `search_web` is not a built-in row - it is assembled from
# the live search server - so it is named once, where its constant already is.
def core_tool_names() -> frozenset[str]:
    return frozenset({SEARCH_TOOL} | {row.name for row in builtin_tools() if row.core})


def picture_tool_names() -> frozenset[str]:
    return frozenset(row.name for row in builtin_tools() if row.needs_picture)


# Which rows need a service wired before they exist, by name. Read by the
# catalogue page, which must describe every tool this repository has rather
# than only the ones the machine it runs on happens to have wired.
def gated_tools() -> dict[str, str]:
    return dict(_GATED)


def tool_families() -> dict[str, str]:
    return {row.name: row.family for row in builtin_tools() if row.family}


AUTOMATION_TOOLS: frozenset[str] = frozenset(
    (
        schedule_task.NAME,
        manage_tasks.NAME,
        manage_check_ins.NAME,
        scout_schedule.NAME,
        save_skill.NAME,
        manage_skills.NAME,
    )
)
# Withheld from a scheduled firing along with the automation tools: a firing
# recalls nothing - its instruction is the whole message - and offered
# history recall, "Remind me to stretch" in a thread with earlier turns was
# routed to it and answered with "when would you like that reminder?"
# (2026-08-26, found by exercise_search_scenarios).
UNATTENDED_WITHHELD: frozenset[str] = AUTOMATION_TOOLS | frozenset(
    (search_history.NAME, send_event_links.NAME)
)
# Withheld when the newest message is about a draft - text being written
# together. A draft is not a picture: "make it more casual" after a drafted
# email was routed to edit_image (deploy #12's sweep, 2026-08-28) and, in an
# earlier sweep, to web search. The automation tools are withheld for the
# same reason they are for a firing: a draft turn schedules nothing.
# Creating a picture stays offered: "add a picture of the store" is explicit,
# where "make it more casual" is not.
DRAFT_WITHHELD: frozenset[str] = UNATTENDED_WITHHELD | frozenset(
    (edit_image.NAME, show_image.NAME, discuss_image.NAME)
)

# Returned by `parse_builtin` for a name that is not a built-in at all, so the
# caller can tell "not ours" from "ours, but the model left out what it
# needed" (None).
NOT_BUILTIN = object()


# The built-in rows to offer, in presentation order, minus the ones whose
# service is switched off. One list read by both the routing call and the
# capability description, so a disabled diagram or presentation agent
# disappears from what the assistant says it can do at the same moment it
# stops being callable.
def builtin_tools(
    enabled: Iterable[str] = (), withhold: Iterable[str] = ()
) -> list[BuiltinTool]:
    on = set(enabled)
    held = set(withhold)
    return [
        module.TOOL
        for module in _MODULES
        if module.NAME not in held
        and (_GATED.get(module.NAME) is None or _GATED[module.NAME] in on)
    ]


# A built-in's call as its typed action; `NOT_BUILTIN` for any other name.
def parse_builtin(
    name: str, arguments: dict[str, Any], fallback_query: str
) -> MainAction | object:
    if name == SEARCH_TOOL:
        model_query = arguments.get("query")
        chosen_query = (
            model_query.strip()
            if isinstance(model_query, str) and model_query.strip()
            else fallback_query
        )
        max_results = arguments.get("max_results")
        return SearchAction(
            query=chosen_query,
            max_results=max_results if isinstance(max_results, int) else None,
        )
    module = _BY_NAME.get(name)
    if module is None:
        return NOT_BUILTIN
    # A parser that wants the message itself gets it: some decisions are
    # made on the words the person wrote, in code, whatever the model chose.
    if getattr(module, "PARSE_READS_MESSAGE", False):
        return module.parse(arguments, fallback_query)
    return module.parse(arguments)


# What the person is told is happening, as (label, detail): the capability
# name and the one fact about this call worth showing. None for no action.
def describe_action(action: MainAction) -> tuple[str, str] | None:
    if action is None:
        return None
    if isinstance(action, SearchAction):
        return SEARCH_CAPABILITY["label"], action.query
    if isinstance(action, ToolboxAction):
        if action.plan.tool_name == WEATHER_TOOL:
            return WEATHER_CAPABILITY["label"], ""
        if action.plan.tool_name == SEARCH_CREDITS_TOOL:
            return SEARCH_CREDITS_CAPABILITY["label"], ""
        return action.plan.tool_name, action.plan.server_id
    if isinstance(action, UseSkillAction):
        return "Skill", action.name
    row = _ROW_FOR_ACTION.get(type(action))
    if row is None:
        return None
    return row.label, _detail(action)


# A playful line for the wait, with an emoji, drawn from the tool's own pool.
def waiting_line(action: MainAction) -> str:
    if isinstance(action, SearchAction):
        return random.choice(SEARCH_WAITING)
    if isinstance(action, ToolboxAction):
        if action.plan.tool_name == WEATHER_TOOL:
            return random.choice(WEATHER_WAITING)
        if action.plan.tool_name == SEARCH_CREDITS_TOOL:
            return random.choice(SEARCH_CREDITS_WAITING)
        return random.choice(TOOLBOX_WAITING).format(tool=action.plan.tool_name)
    if isinstance(action, UseSkillAction):
        return random.choice(SKILL_WAITING).format(name=action.name)
    row = _ROW_FOR_ACTION.get(type(action)) if action is not None else None
    if row is None or not row.waiting:
        return ""
    return random.choice(row.waiting)


SKILL_WAITING: tuple[str, ...] = (
    "⚡ Running your '{name}' skill…",
    "🎯 '{name}', coming right up…",
    "🚀 Launching '{name}'…",
)

_ROW_FOR_ACTION: dict[type, BuiltinTool] = {
    GenerateImageAction: generate_image.TOOL,
    EditImageAction: edit_image.TOOL,
    ShowImageAction: show_image.TOOL,
    DiscussImageAction: discuss_image.TOOL,
    CreateDiagramAction: create_diagram.TOOL,
    CreateDocumentAction: create_document.TOOL,
    EditDocumentAction: edit_document.TOOL,
    DelegateAction: presentation.TOOL,
    RecallHistoryAction: search_history.TOOL,
    SendEventLinksAction: send_event_links.TOOL,
    ScheduleTaskAction: schedule_task.TOOL,
    ManageTasksAction: manage_tasks.TOOL,
    ManageCheckInsAction: manage_check_ins.TOOL,
    ScoutScheduleAction: scout_schedule.TOOL,
    SaveSkillAction: save_skill.TOOL,
    ManageSkillsAction: manage_skills.TOOL,
    ManageRunsAction: manage_runs.TOOL,
}


# The one fact about a call worth showing next to its label.
def _detail(action: MainAction) -> str:
    if isinstance(action, GenerateImageAction):
        return action.prompt
    if isinstance(action, EditImageAction):
        return action.instruction
    if isinstance(action, ShowImageAction):
        return action.which
    if isinstance(action, DiscussImageAction):
        return action.about
    if isinstance(action, RecallHistoryAction):
        return action.query
    if isinstance(action, SendEventLinksAction):
        return action.which
    if isinstance(action, CreateDiagramAction | DelegateAction):
        return action.subject
    if isinstance(action, CreateDocumentAction | EditDocumentAction):
        return f"{action.title} ({action.format})"
    if isinstance(action, ScoutScheduleAction) and action.operation == "show":
        return "show"
    if isinstance(action, ScoutScheduleAction):
        return f"{action.cadence} at {action.hour:02d}:{action.minute:02d}"
    # The instruction rides with the time. This detail is the line the router
    # reads back before its next decision, and without the words it could not
    # tell which reminder was already set: asked for 6pm mum and 8pm gym it
    # wrote "call mum" twice, at both times (measured 2026-09-05, 3 of 3).
    if isinstance(action, ScheduleTaskAction):
        return (
            f"{action.cadence} at {action.hour:02d}:{action.minute:02d} - "
            f"{action.instruction}"
        )
    if isinstance(action, ManageTasksAction):
        parts = [action.operation]
        if action.which:
            parts.append(action.which)
        if action.operation == "reschedule":
            parts.append(f"to {action.hour:02d}:{action.minute:02d}")
        return " ".join(parts)
    if isinstance(action, ManageSkillsAction):
        return action.operation
    if isinstance(action, ManageCheckInsAction):
        return f"{action.mode} {action.subject}".strip()
    if isinstance(action, ManageRunsAction):
        return f"{action.mode} {action.which}".strip()
    if isinstance(action, SaveSkillAction):
        return action.name
    return ""


# ------------------------------------------------------------------ policy
#
# The loop's policy questions, each answered off the tool's own contract so a
# new tool is covered the day it declares one and a renamed one cannot fall
# out of a set of names kept elsewhere.

# The contract governing one action. A toolbox action's contract belongs to
# its MCP tool and is looked up by the caller who knows the server; it is
# passed in here so this module does not reach into the invocation service.
def contract_for_action(
    action: MainAction, toolbox_contract: EffectContract | None = None
) -> EffectContract:
    if action is None:
        return UNDECLARED
    if isinstance(action, SearchAction):
        return SEARCH_CONTRACT
    if isinstance(action, ToolboxAction):
        if action.plan.tool_name == WEATHER_TOOL:
            return WEATHER_CONTRACT
        if action.plan.tool_name == SEARCH_CREDITS_TOOL:
            return SEARCH_CREDITS_CONTRACT
        return toolbox_contract or UNDECLARED
    row = _ROW_FOR_ACTION.get(type(action))
    return row.contract if row is not None else UNDECLARED


# The natural key of one action, or None when its tool declares none. What a
# repeat within a turn is compared on.
def action_key(
    action: MainAction, toolbox_contract: EffectContract | None = None
) -> str | None:
    if action is None:
        return None
    contract = contract_for_action(action, toolbox_contract)
    key = contract.key(action)
    if key is None:
        return None
    return f"{tool_name_of(action)}:{key}"


# Whether carrying out this action would make a new thing.
def action_creates(
    action: MainAction, toolbox_contract: EffectContract | None = None
) -> bool:
    return contract_for_action(action, toolbox_contract).is_creation(action)


# The tool name an action resolves to, for keys and step records.
def tool_name_of(action: MainAction) -> str:
    if isinstance(action, SearchAction):
        return SEARCH_TOOL
    if isinstance(action, ToolboxAction):
        return action.plan.tool_name
    if isinstance(action, UseSkillAction):
        return f"skill:{action.skill_id}"
    row = _ROW_FOR_ACTION.get(type(action)) if action is not None else None
    return row.name if row is not None else ""


# The built-in tools a later step may start with this much of the budget
# left, read off every row's contract. The three internet tools are not rows
# and are included by their own contracts.
def later_step_tools(remaining_seconds: float) -> frozenset[str]:
    names = {
        row.name
        for row in (module.TOOL for module in _MODULES)
        if row.contract.allows_later_step(remaining_seconds)
    }
    for name, contract in (
        (SEARCH_TOOL, SEARCH_CONTRACT),
        (WEATHER_TOOL, WEATHER_CONTRACT),
        (SEARCH_CREDITS_TOOL, SEARCH_CREDITS_CONTRACT),
    ):
        if contract.allows_later_step(remaining_seconds):
            names.add(name)
    return frozenset(names)
