"""manage_tasks: list, cancel, pause, resume, or reschedule scheduled tasks."""

from typing import Any

from .actions import ManageTasksAction
from .base import BuiltinTool

NAME = "manage_tasks"

OPERATIONS = ("list", "cancel", "pause", "resume", "reschedule", "undo")

# KNOWN, MEASURED: the "not for Scout" sentence in the description below does
# not work. Adding `reschedule` took the four `agent_config` cases in
# tool_selection_cases.py from 4/4 to 0/4 - "change the schedule to 9:25pm"
# after talk of Scout now routes here instead of to no tool. Two wordings were
# tried, leading and trailing, and neither moved it, because the reading is
# defensible: the person did ask to change a schedule.
#
# The fix is structural, not prompt text. Either agent configuration gets its
# own tool so the model chooses between two named things, or Scout's sweep
# becomes an ordinary scheduled task and there is only one concept.
#
# 2026-08-26: the first of those landed - `scout_schedule.py` is Scout's own
# row - after "adjust this to daily at 3pm", said about Scout, came here and
# moved a stretch reminder. Measured the same evening (evaluate_tool_selection,
# 3 reps): scout_schedule 18/18, manage_tasks 23/24, none 43/66 = 0.65 against
# the 0.47 recorded above. The picker is also offered "none" now, so a
# referent that is not a task moves nothing even when the route is wrong.

# The cadences reschedule accepts, kept identical to schedule_task's so moving
# a task between shapes - a one-off becoming a daily - needs no second call.
CADENCES = ("once", "daily", "weekdays", "weekly")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": list(OPERATIONS)},
        "which": {
            "type": "string",
            "description": (
                "Which task, in the person's words, when cancelling, pausing, "
                "resuming or rescheduling - 'the weather one', 'the Friday "
                "reminder', 'the tesla one'. Empty for list."
            ),
        },
        # Reschedule carries the new timing itself. It used to be advertised as
        # "cancel it and schedule a new one", which is two calls where only one
        # is available per turn - so the request could not be carried out, and
        # was answered as though it had been.
        "cadence": {
            "type": "string",
            "enum": list(CADENCES),
            "description": (
                "Reschedule only: the new cadence. once for a single time, "
                "daily for every day, weekdays for Monday to Friday, weekly "
                "for one day each week. Keep the task's existing cadence when "
                "only the time is changing."
            ),
        },
        "hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23,
            "description": "Reschedule only: the new hour, 24-hour clock.",
        },
        "minute": {
            "type": "integer",
            "minimum": 0,
            "maximum": 59,
            "description": "Reschedule only: the new minute.",
        },
        "weekday": {
            "type": "integer",
            "minimum": 0,
            "maximum": 6,
            "description": "Reschedule only, for weekly: 0 is Monday, 6 is Sunday.",
        },
        "on_date": {
            "type": "string",
            "description": (
                "Reschedule only, for once: the new calendar date as "
                "YYYY-MM-DD, resolved from today's date for words like "
                "tomorrow or Friday. For a time later today, today's date."
            ),
        },
        "instruction": {
            "type": "string",
            "description": (
                "Reschedule only, and only when what the task says should "
                "change too. Leave it out to keep the existing wording."
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
        "Acts on a reminder or scheduled message this person already set up. "
        "It requires that such a task exists and that this message refers to "
        "it - a time or a date appearing in a message is not enough, and is "
        "usually part of whatever else is being discussed. "
        "list: what they have scheduled. cancel, pause, resume: stop or "
        "restart one they name. reschedule: move one to a new time, carrying "
        "that time - 'change the tesla reminder to 5 minutes from now'. "
        "Rescheduling is a single call; never answer as though a reminder "
        "moved without making it. undo: put back the most recent change to "
        "their reminders or to Scout's schedule - 'undo that', 'put it back', "
        "'never mind, restore the stretch reminder' - the application knows "
        "which change was last. "
        "The events sweep's OWN cadence - how often Scout looks for things "
        "near them - belongs to scout_schedule, not here. Everything else the "
        "person has scheduled, including any recurring search or report, is a "
        "task and belongs here."
    ),
    schema=_SCHEMA,
    waiting=(
        "🗂️ Flipping through your schedule…",
        "📋 Checking the task list…",
    ),
)


# The call as an action, or nothing for an unknown operation. Reschedule
# without an hour is rejected rather than defaulted: a silent midnight is
# indistinguishable from a working answer until the reminder does not arrive.
def parse(arguments: dict[str, Any]) -> ManageTasksAction | None:
    operation = arguments.get("operation")
    if operation not in OPERATIONS:
        return None
    which = arguments.get("which")
    which = which.strip() if isinstance(which, str) else ""
    if operation != "reschedule":
        return ManageTasksAction(operation=str(operation), which=which)

    hour = arguments.get("hour")
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        return None
    minute = arguments.get("minute")
    minute = minute if isinstance(minute, int) and 0 <= minute <= 59 else 0
    weekday = arguments.get("weekday")
    weekday = weekday if isinstance(weekday, int) and 0 <= weekday <= 6 else None
    cadence = arguments.get("cadence")
    cadence = cadence if cadence in CADENCES else None
    on_date = arguments.get("on_date")
    instruction = arguments.get("instruction")
    return ManageTasksAction(
        operation="reschedule",
        which=which,
        cadence=cadence,
        hour=hour,
        minute=minute,
        weekday=weekday,
        on_date=on_date.strip() if isinstance(on_date, str) and on_date.strip() else None,
        instruction=(
            instruction.strip()
            if isinstance(instruction, str) and instruction.strip()
            else None
        ),
    )
