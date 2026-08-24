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
    edit_image,
    generate_image,
    manage_skills,
    manage_tasks,
    presentation,
    save_skill,
    schedule_task,
    search_history,
)
from .actions import (
    CreateDiagramAction,
    DelegateAction,
    EditImageAction,
    GenerateImageAction,
    MainAction,
    ManageSkillsAction,
    ManageTasksAction,
    RecallHistoryAction,
    SaveSkillAction,
    ScheduleTaskAction,
    SearchAction,
    ToolboxAction,
    UseSkillAction,
)
from .base import BuiltinTool
from .search import (
    SEARCH_CAPABILITY,
    SEARCH_TOOL,
    SEARCH_WAITING,
    TOOLBOX_WAITING,
    WEATHER_CAPABILITY,
    WEATHER_TOOL,
    WEATHER_WAITING,
)

_MODULES: tuple[ModuleType, ...] = (
    generate_image,
    edit_image,
    create_diagram,
    presentation,
    search_history,
    schedule_task,
    manage_tasks,
    save_skill,
    manage_skills,
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
AUTOMATION_TOOLS: frozenset[str] = frozenset(
    (schedule_task.NAME, manage_tasks.NAME, save_skill.NAME, manage_skills.NAME)
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
    CreateDiagramAction: create_diagram.TOOL,
    DelegateAction: presentation.TOOL,
    RecallHistoryAction: search_history.TOOL,
    ScheduleTaskAction: schedule_task.TOOL,
    ManageTasksAction: manage_tasks.TOOL,
    SaveSkillAction: save_skill.TOOL,
    ManageSkillsAction: manage_skills.TOOL,
}


# The one fact about a call worth showing next to its label.
def _detail(action: MainAction) -> str:
    if isinstance(action, GenerateImageAction):
        return action.prompt
    if isinstance(action, EditImageAction):
        return action.instruction
    if isinstance(action, RecallHistoryAction):
        return action.query
    if isinstance(action, CreateDiagramAction | DelegateAction):
        return action.subject
    if isinstance(action, ScheduleTaskAction):
        return f"{action.cadence} at {action.hour:02d}:{action.minute:02d}"
    if isinstance(action, ManageTasksAction | ManageSkillsAction):
        return action.operation
    if isinstance(action, SaveSkillAction):
        return action.name
    return ""
