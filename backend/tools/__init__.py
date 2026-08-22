"""Built-in tools, one module each, read by the router and the reply prompt.

A tool here is something the model can choose for a turn: its row (name,
label, router description, argument schema, waiting lines) and its parser
from a tool call to a typed action. Adding a tool is adding a module and a
line in `registry.py`; nothing else changes. Skills - instruction packs the
model invokes by meaning - live in `backend/skills/` and are offered to the
same router alongside these.
"""

from .actions import (
    CreateDiagramAction,
    DelegateAction,
    EditImageAction,
    GenerateImageAction,
    MainAction,
    ManageSkillsAction,
    ManageTasksAction,
    SaveSkillAction,
    ScheduleTaskAction,
    SearchAction,
    ToolboxAction,
    UseSkillAction,
)
from .base import BuiltinTool
from .registry import (
    AUTOMATION_TOOLS,
    NOT_BUILTIN,
    SEARCH_CAPABILITY,
    SEARCH_TOOL,
    WEATHER_CAPABILITY,
    WEATHER_TOOL,
    builtin_tools,
    describe_action,
    parse_builtin,
    waiting_line,
)

__all__ = [
    "AUTOMATION_TOOLS",
    "NOT_BUILTIN",
    "SEARCH_CAPABILITY",
    "SEARCH_TOOL",
    "WEATHER_CAPABILITY",
    "WEATHER_TOOL",
    "BuiltinTool",
    "CreateDiagramAction",
    "DelegateAction",
    "EditImageAction",
    "GenerateImageAction",
    "MainAction",
    "ManageSkillsAction",
    "ManageTasksAction",
    "SaveSkillAction",
    "ScheduleTaskAction",
    "SearchAction",
    "ToolboxAction",
    "UseSkillAction",
    "builtin_tools",
    "describe_action",
    "parse_builtin",
    "waiting_line",
]
