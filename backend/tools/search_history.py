"""search_history: find what was said in past conversations."""

from typing import Any

from .actions import RecallHistoryAction
from .base import BuiltinTool, required_text

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
        "guessing. `query` is what to look for, in a few words taken from "
        "the request. Do not choose it for a question the visible "
        "conversation or your general knowledge already answers, and never "
        "for facts about the world - it searches only this user's own "
        "history with you."
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
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    waiting=(
        "🗂️ Flipping back through our conversations…",
        "🧠 Let me think back…",
        "📖 Checking what we said…",
    ),
)


# No query means no decision: the turn goes down the ordinary reply path,
# where the assistant asks what to look for rather than searching for nothing.
def parse(arguments: dict[str, Any]) -> RecallHistoryAction | None:
    query = required_text(arguments, "query")
    return None if query is None else RecallHistoryAction(query)
