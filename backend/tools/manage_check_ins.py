"""manage_check_ins: check-ins on request - turned on, turned off, armed once
for one named thing, or listed. Off for everyone until they ask."""
from typing import Any

from backend.core.checkin import FIRST_HOUR, FOLLOWING_UP, KINDS, LAST_HOUR, MAX_DAYS, MIN_DAYS

from .actions import ManageCheckInsAction
from .base import BuiltinTool

NAME = "manage_check_ins"
MODES = ("on", "off", "once", "status")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": list(MODES),
            "description": (
                "on when they want the assistant to come back later, on its "
                "own, to things they mention from now on; off when they want "
                "that to stop; once when they name one thing to be asked "
                "about later ('check in with me Friday about the interview'); "
                "status when they ask what is waiting."
            ),
        },
        "subject": {
            "type": "string",
            "description": "For once: the thing, in a few words - 'the interview', 'the trip to Lisbon'.",
        },
        "question": {
            "type": "string",
            "description": "For once: what to ask, as one short line in their words - 'How did the interview go?'",
        },
        "after_days": {
            "type": "integer",
            "minimum": MIN_DAYS,
            "maximum": MAX_DAYS,
            "description": "For once: how many days from today to ask, resolved from words like Friday or next week.",
        },
        "hour": {
            "type": "integer",
            "minimum": FIRST_HOUR,
            "maximum": LAST_HOUR,
            "description": "For once: the local hour to ask at, when they say one.",
        },
        "kind": {
            "type": "string",
            "enum": list(KINDS),
            "description": "For once: following_up asks how a thing went; wellbeing asks how they are after something hard.",
        },
    },
    "required": ["mode"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Check-ins",
    description=(
        "Check-ins: the assistant coming back later, on its own, to ask how "
        "something went - a trip, an interview, a hard week. Off unless the "
        "person asks. Choose it when they ask to be checked in on, followed "
        "up with, or asked later about something ('check in with me Friday "
        "about the interview', 'from now on follow up on things I mention'), "
        "when they ask for that to stop, or when they ask what check-ins are "
        "waiting. Not for reminders they phrase as reminders, and not for "
        "something merely mentioned in passing."
    ),
    schema=_SCHEMA,
    waiting=(
        "📝 Making a note to ask…",
        "🔔 Setting that up…",
    ),
)


# The call as an action, or nothing when the mode is not one of ours or a
# once has no subject to come back to. Numbers outside the check-in bounds
# are clamped later by the same code that clamps the judgement's.
def parse(arguments: dict[str, Any]) -> ManageCheckInsAction | None:
    mode = str(arguments.get("mode") or "").strip().lower()
    if mode not in MODES:
        return None
    subject = " ".join(str(arguments.get("subject") or "").split())
    question = " ".join(str(arguments.get("question") or "").split())
    if mode == "once" and not subject and not question:
        return None
    kind = str(arguments.get("kind") or FOLLOWING_UP)
    if kind not in KINDS:
        kind = FOLLOWING_UP
    after_days: int | None = None
    hour: int | None = None
    try:
        if arguments.get("after_days") is not None:
            after_days = int(arguments["after_days"])
        if arguments.get("hour") is not None:
            hour = int(arguments["hour"])
    except (TypeError, ValueError):
        return None
    return ManageCheckInsAction(
        mode=mode,
        subject=subject or question,
        question=question,
        after_days=after_days,
        hour=hour,
        kind=kind,
    )
