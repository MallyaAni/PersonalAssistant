"""scout_schedule: set or change when Scout's own sweep runs.

Scout's sweep is agent configuration, not a scheduled task. Offered only
`manage_tasks`, the router read "change the schedule to 9:25pm everyday"
after talk of Scout as a task reschedule - measured 2026-08-23, and no
wording of that tool's description moved it, because the reading was
defensible. This row gives the router two named things to choose between.
"""

from typing import Any

from .actions import ScoutScheduleAction
from .base import BuiltinTool

NAME = "scout_schedule"

# The sweep's own shapes, as backend/discovery/schedule.Cadence accepts them
# for a discovery schedule: every day, or one day a week.
CADENCES = ("daily", "weekly")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cadence": {
            "type": "string",
            "enum": list(CADENCES),
            "description": "daily for every day, weekly for one day each week.",
        },
        "hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23,
            "description": "The hour the sweep runs, 24-hour clock, in the person's own time.",
        },
        "minute": {
            "type": "integer",
            "minimum": 0,
            "maximum": 59,
            "description": "Minutes past the hour; 0 when they name a whole hour.",
        },
        "weekday": {
            "type": "integer",
            "minimum": 0,
            "maximum": 6,
            "description": "Weekly only: 0 is Monday, 6 is Sunday.",
        },
    },
    "required": ["cadence", "hour"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Scout schedule",
    description=(
        "Sets or changes when Scout's own sweep runs - the recurring check "
        "for things happening near this person, their events digest. Call it "
        "when they ask to set, change, or move that sweep's cadence or time: "
        "'run scout daily at 3pm', 'change the schedule to 9:25pm everyday' "
        "in a conversation about Scout, 'make it weekly instead' or 'adjust "
        "this to daily at 3pm' when the previous reply was about Scout's "
        "schedule. It is agent configuration: not a reminder, text, or task "
        "the person set up - those belong to schedule_task and manage_tasks - "
        "and not a question about what Scout currently has configured, which "
        "needs no tool."
    ),
    schema=_SCHEMA,
    waiting=(
        "🧭 Setting Scout's clock…",
        "🗓️ Moving the sweep to its new time…",
    ),
)


# The call as an action, or nothing when the cadence or hour is missing or
# out of range: a sweep silently set to midnight is a wrong answer that
# looks like a right one.
def parse(arguments: dict[str, Any]) -> ScoutScheduleAction | None:
    cadence = arguments.get("cadence")
    if cadence not in CADENCES:
        return None
    hour = arguments.get("hour")
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        return None
    minute = arguments.get("minute")
    minute = minute if isinstance(minute, int) and 0 <= minute <= 59 else 0
    weekday = arguments.get("weekday")
    weekday = weekday if isinstance(weekday, int) and 0 <= weekday <= 6 else 0
    return ScoutScheduleAction(
        cadence=str(cadence), hour=hour, minute=minute, weekday=weekday
    )
