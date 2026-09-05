"""schedule_task: set something up to happen later or on a schedule."""

from typing import Any

from .actions import ScheduleTaskAction
from .base import BuiltinTool, required_text
from .contracts import EffectContract

NAME = "schedule_task"

CADENCES = ("once", "daily", "weekdays", "weekly")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instruction": {
            "type": "string",
            "description": (
                "What the assistant does each time it runs, as a complete "
                "instruction to the assistant. For a reminder the reminding "
                "is the task, so keep it: 'remind me to turn off the stove', "
                "'remind me to call mom'. For a lookup or a message, say what "
                "to send: 'text me today's weather for Arlington', 'check "
                "whether the stacking cable is in stock at Rockville and tell "
                "me'. Leave out only the schedule words (tomorrow, every day, "
                "at 5) - those are carried separately."
            ),
        },
        "cadence": {
            "type": "string",
            "enum": list(CADENCES),
            "description": (
                "once for a single time ('tomorrow at 9', 'Friday'), daily for "
                "every day, weekdays for Monday to Friday, weekly for one day "
                "each week."
            ),
        },
        "hour": {"type": "integer", "minimum": 0, "maximum": 23},
        "minute": {"type": "integer", "minimum": 0, "maximum": 59},
        "weekday": {
            "type": "integer",
            "minimum": 0,
            "maximum": 6,
            "description": "For weekly: 0 is Monday, 6 is Sunday.",
        },
        "on_date": {
            "type": "string",
            "description": (
                "For once: the calendar date as YYYY-MM-DD, resolved from "
                "today's date for words like tomorrow or Friday."
            ),
        },
    },
    "required": ["instruction", "cadence", "hour", "minute"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Scheduled tasks",
    description=(
        "Set something up to happen later or on a schedule: a reminder, a "
        "daily or weekly message, a recurring check or lookup, anything they "
        "want done at a stated time rather than now. Choose it when the "
        "request names a future time or a repetition - tomorrow, every "
        "morning, Fridays, at 7 - and the thing itself is something this "
        "assistant can do in a turn (answer, look up, search, report, "
        "remind). Resolve relative words against today's date and their "
        "local time. A question asked for right now is not a task."
    ),
    schema=_SCHEMA,
    waiting=(
        "📅 Pencilling that in…",
        "⏰ Setting the alarm…",
        "🗓️ Finding a slot for it…",
    ),
    family="scheduling",
    core=True,
    contract=EffectContract(
        effect="write",
        cost="fast",
        creates=True,
        reversible="scheduled_task",
        # Two reminders with different words are two effects; the same
        # reminder worded twice is one.
        idempotency=lambda action: "|".join(
            (
                " ".join(action.instruction.casefold().split()),
                action.cadence,
                str(action.hour),
                str(action.minute),
                str(action.weekday),
                str(action.on_date or ""),
            )
        ),
    ),
)


# The call as an action, or nothing when the model left out what the task
# is or picked a cadence the scheduler does not have.
def parse(arguments: dict[str, Any]) -> ScheduleTaskAction | None:
    instruction = required_text(arguments, "instruction")
    cadence = arguments.get("cadence")
    if instruction is None or cadence not in CADENCES:
        return None
    try:
        hour = int(arguments.get("hour", 9))
        minute = int(arguments.get("minute", 0))
        weekday = int(arguments.get("weekday") or 0)
    except (TypeError, ValueError):
        return None
    on_date = arguments.get("on_date")
    return ScheduleTaskAction(
        instruction=instruction,
        cadence=str(cadence),
        hour=hour,
        minute=minute,
        weekday=weekday,
        on_date=str(on_date) if isinstance(on_date, str) and on_date else None,
    )
