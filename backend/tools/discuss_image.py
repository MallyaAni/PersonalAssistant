"""discuss_image: talk about the picture in view; change and show nothing.

Offered only "edit" and "show", the router read every sentence about the
picture as one of them - "which hat do you like better for this outfit?"
became an edit (0/9, 2026-08-26) and, once the follow-up resolver said the
message was about the picture, a re-show (0/9, 2026-08-27). A named "talk
about it" gives the router a third thing to choose, and nothing runs for it.
"""

from typing import Any

from .actions import DiscussImageAction
from .base import BuiltinTool

NAME = "discuss_image"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "about": {
            "type": "string",
            "description": "What they are asking about the picture, in a few words.",
        },
    },
    "required": [],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="About the picture",
    description=(
        "Talks about the picture currently in view without changing it or "
        "putting it back on screen: an opinion ('which hat do you like better "
        "for this outfit?'), a comparison, advice, or a question about what "
        "is in it. Nothing is generated, edited, or displayed - the answer is "
        "written from the picture. Use edit_image only when they ask to change "
        "the picture, show_image only when they ask to see one again."
    ),
    schema=_SCHEMA,
    waiting=(
        "👀 Taking a look at the picture…",
        "🖼️ Looking it over…",
    ),
)


# The call as an action; there is nothing it can lack.
def parse(arguments: dict[str, Any]) -> DiscussImageAction | None:
    about = arguments.get("about")
    return DiscussImageAction(about=about.strip() if isinstance(about, str) else "")
