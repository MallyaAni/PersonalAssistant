"""manage_check_ins: stored preferences and requested future questions.

pinned by: functional/test_check_in_request_behaviour.py
           functional/test_tool_selection_matrix_behaviour.py
"""
import re
from typing import Any

from backend.core.checkin import FIRST_HOUR, FOLLOWING_UP, KINDS, LAST_HOUR, MAX_DAYS, MIN_DAYS

from .actions import ManageCheckInsAction
from .base import BuiltinTool
from .contracts import EffectContract, normalize_words

NAME = "manage_check_ins"
MODES = ("on", "off", "once", "status")
PARSE_READS_MESSAGE = True

# What a request for check-ins sounds like. A statement about the person's
# day ("I put an offer in on a car this morning") carries none of these, and
# the router sent exactly that to this tool 3/3 right after they had asked
# for check-ins, whatever the description said (measured 2026-09-02). So
# the words decide, in code: no ask, no action, and the judgement that
# handles mentions runs as it would have.
_ASKS = re.compile(
    r"check[- ]?ins?\b|check (?:in )?on (?:me|us)|follow[- ]?up|keep tabs|ask (?:me|us)\b"
    r"|stop checking|checking (?:in|on)|remind me to tell you|see how i",
    re.IGNORECASE,
)

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
        "Read or change check-ins: future questions that the assistant initiates "
        "about how something went or how a person is doing. Choose this tool for "
        "an explicit request to enable or disable these questions, schedule one, "
        "or inspect what is pending. Enabling and disabling both write a stored "
        "preference; do not replace an explicit request with an assumption about "
        "the current or default setting. A report about someone's day is not a "
        "check-in request. Reminders to perform an action use the reminder/task tools."
    ),
    schema=_SCHEMA,
    waiting=(
        "📝 Making a note to ask…",
        "🔔 Setting that up…",
    ),
    family="scheduling",
    contract=EffectContract(
        effect="write",
        cost="fast",
        reversible="scheduled_task",
        # Only arming one check-in makes a new thing; on, off and
        # status change a setting or read one.
        creates=lambda action: action.mode == "once",
        idempotency=lambda action: "|".join(
            (action.mode, normalize_words(action.subject))
        ),
    ),
)


# The call as an action, or nothing when the mode is not one of ours or a
# once has no subject to come back to. Numbers outside the check-in bounds
# are clamped later by the same code that clamps the judgement's.
def parse(arguments: dict[str, Any], message: str = "") -> ManageCheckInsAction | None:
    mode = str(arguments.get("mode") or "").strip().lower()
    if mode not in MODES:
        return None
    if message and not _ASKS.search(message):
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
