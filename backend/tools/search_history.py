"""search_history: find what was said in past conversations."""

from typing import Any

from .actions import RecallHistoryAction
from .base import BuiltinTool, required_text
from .contracts import EffectContract, normalize_words

NAME = "search_history"

TOOL = BuiltinTool(
    name=NAME,
    label="Past conversations",
    description=(
        "Search everything the user and you have said to each other, across "
        "all past conversations. Choose this when the user refers to "
        "something from before that is not visible now - a thing they "
        "mentioned once, a name they told you, when a topic came up - and "
        "answering requires finding what was actually said rather than "
        "guessing. Never for what is happening in the world now or soon - "
        "events, what's on, news, prices, schedules, the weather: those are "
        "search_web, however the question is phrased. `query` is what to "
        "look for, in a few words taken from "
        "the request. Do not choose it for a question the visible "
        "conversation or your general knowledge already answers, and never "
        "for facts about the world - it searches only this user's own "
        "history with you. A short follow-up that continues work already in "
        "view - revising, adjusting, or extending what was just written - is "
        "part of that work, not a reference to the past: answer it directly "
        "instead of searching for it."
    ),
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "What to search past conversations for, in a few words "
                    "taken from the request. Leave empty if the request does "
                    "not say."
                ),
            },
            "since": {
                "type": "string",
                "description": (
                    "Earliest date to search, as YYYY-MM-DD, only when the "
                    "request names a time period ('last week', 'in March') - "
                    "resolve it against the current date. Omit otherwise."
                ),
            },
            "until": {
                "type": "string",
                "description": (
                    "Latest date to search, as YYYY-MM-DD, only when the "
                    "request bounds one. Omit otherwise."
                ),
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    waiting=(
        "🗂️ Flipping back through our conversations…",
        "🧠 Let me think back…",
        "📖 Checking what we said…",
    ),
    family="memory",
    core=True,
    contract=EffectContract(
        effect="read",
        cost="fast",
        idempotency=lambda action: normalize_words(action.query),
    ),
)


# No query means no decision: the turn goes down the ordinary reply path,
# where the assistant asks what to look for rather than searching for nothing.
# The dates are optional and passed through as stated; whether they parse is
# judged where they are used, so a malformed date degrades to an unbounded
# search rather than to no search at all.
def parse(arguments: dict[str, Any]) -> RecallHistoryAction | None:
    query = required_text(arguments, "query")
    if query is None:
        return None
    return RecallHistoryAction(
        query,
        since=required_text(arguments, "since"),
        until=required_text(arguments, "until"),
    )
