"""send_event_links: deliver the map, calendar and event links a listing offered."""

from typing import Any

from .actions import SendEventLinksAction
from .base import BuiltinTool
from .contracts import EffectContract, normalize_words

NAME = "send_event_links"

# KNOWN, MEASURED: `which` is passed to the picker, so it may be the person's
# own words ("the salsa night", "the second one") rather than a name the model
# has to reproduce - a name it remembered from a listing is exactly the kind
# of thing it gets subtly wrong, and the picker has the listing in front of it.

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "which": {
            "type": "string",
            "description": (
                "Which events from the listing the person wants links for, in "
                "their words or resolved to names - 'the salsa night', 'the "
                "second one', 'the first two', 'all of them'."
            ),
        },
    },
    "required": ["which"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Send links for listed events",
    description=(
        "Sends the map, calendar and event-page links for events already "
        "shown in a listing, for exactly the ones the person asks about - "
        "'send me the links for the salsa night', 'maps for the first two', "
        "'share the calendar for all of them'. Use it when this message asks "
        "for links or a map or a calendar entry for something on a list the "
        "assistant just gave; the links are built from the typed records of "
        "that listing, so nothing is invented. Not for events that were never "
        "listed, and not for creating reminders - 'remind me about the second "
        "one' is schedule_task."
    ),
    schema=_SCHEMA,
    waiting=(
        "🔗 Pulling those links together…",
        "🧭 Finding the map and the page…",
    ),
    family="events",
    core=True,
    contract=EffectContract(
        effect="read",
        cost="fast",
        # Two turns asking for the same event's links are the same request; a
        # repeat within a turn is therefore refused rather than re-sent.
        idempotency=lambda action: f"links:{normalize_words(action.which)}",
    ),
)


# The call as an action, or nothing when the model left out what it needed.
# A blank `which` is not a decision - the tool was picked without being able
# to say what for - so it is no call at all.
def parse(arguments: dict[str, Any]) -> SendEventLinksAction | None:
    which = arguments.get("which")
    which = which.strip() if isinstance(which, str) else ""
    if not which:
        return None
    return SendEventLinksAction(which=which)
