"""manage_tasks: list, cancel, pause, or resume scheduled tasks."""

from typing import Any

from .actions import ManageTasksAction
from .base import BuiltinTool

NAME = "manage_tasks"

OPERATIONS = ("list", "cancel", "pause", "resume")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": list(OPERATIONS)},
        "which": {
            "type": "string",
            "description": (
                "Which task, in the person's words, when cancelling, pausing "
                "or resuming - 'the weather one', 'the Friday reminder'. "
                "Empty for list."
            ),
        },
    },
    "required": ["operation"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Manage scheduled tasks",
    description=(
        "List, cancel, pause, or resume the tasks they already scheduled. "
        "Choose it when they ask what is scheduled, or to stop, pause, or "
        "restart one - 'cancel the weather texts', 'what do I have "
        "scheduled?'. Changing a time or what a task does is a cancel and a "
        "new schedule_task."
    ),
    schema=_SCHEMA,
    waiting=(
        "🗂️ Flipping through your schedule…",
        "📋 Checking the task list…",
    ),
)


# The call as an action, or nothing for an unknown operation.
def parse(arguments: dict[str, Any]) -> ManageTasksAction | None:
    operation = arguments.get("operation")
    if operation not in OPERATIONS:
        return None
    which = arguments.get("which")
    return ManageTasksAction(
        operation=str(operation), which=which.strip() if isinstance(which, str) else ""
    )
