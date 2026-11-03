"""scout_digest: read back what Scout already sent this person."""

from typing import Any

from .actions import ScoutDigestAction
from .base import BuiltinTool, required_text
from .contracts import EffectContract, normalize_words

NAME = "scout_digest"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "since": {
            "type": "string",
            "description": (
                "Earliest date to read, as YYYY-MM-DD, only when the request "
                "names a period ('last week', 'this month') - resolve it "
                "against the current date. Omit otherwise."
            ),
        },
        "until": {
            "type": "string",
            "description": (
                "Latest date to read, as YYYY-MM-DD, only when the request "
                "bounds one. The day named is included. Omit otherwise."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="What Scout sent",
    description=(
        "Reads back only the delivery record of Scout's push digest: the finds "
        "it has already sent this person, when each went, and whether they "
        "gave it a thumbs-up or thumbs-down. Call it when the request asks "
        "what Scout already sent, found, or recommended for them: 'what did "
        "scout send me?', 'what was in yesterday's digest?', 'did you ever "
        "send me that pottery thing?', 'which of those did I like?'. Not what "
        "someone likes, prefers, or has in common with someone else - that is "
        "search_history, even when the request names Scout. Not the sweep's "
        "schedule or when it next runs - that is scout_schedule. Not what was "
        "said in past conversations - that is search_history. Not what is "
        "happening now or soon - that is search_web, even when the request "
        "says 'find me'. Not links for a listing already shown in this "
        "conversation - that is send_event_links."
    ),
    schema=_SCHEMA,
    waiting=(
        "📬 Checking what I already sent you…",
        "🗂️ Pulling up the last digests…",
    ),
    # Grouped with the other finds tools, so one catalogue search for events
    # or digests reaches both this and send_event_links.
    family="events",
    contract=EffectContract(
        effect="read",
        cost="fast",
        # The same window asked twice in one turn is the same read.
        idempotency=lambda action: "|".join(
            normalize_words(part or "") for part in (action.since, action.until)
        ),
    ),
)


# Both bounds are optional: "what did scout send me?" is a complete request
# with no dates, so there is no argument whose absence makes this no call.
# Whether a stated date parses is judged where it is used, so a malformed one
# degrades to an unbounded read rather than to no read at all.
def parse(arguments: dict[str, Any]) -> ScoutDigestAction | None:
    return ScoutDigestAction(
        since=required_text(arguments, "since"),
        until=required_text(arguments, "until"),
    )
