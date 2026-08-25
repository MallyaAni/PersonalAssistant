"""show_image: a picture the user already has, shown or sent again.

Recalled pictures used to reach only the reply model, as descriptions in its
context, and never the person: asked "can you show me that image?" over
iMessage on 2026-08-25, the assistant had the picture in front of it and
answered that it could not display it here. There was no action that put an
existing picture back in front of the user - generation and editing both
stream `artifact_ready`, which every client renders or attaches, but nothing
did so for a picture that already existed. This tool is that action.
"""

from typing import Any

from .actions import ShowImageAction
from .base import BuiltinTool, required_text

NAME = "show_image"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "which": {
            "type": "string",
            "description": (
                "Which picture they mean, in their own words - 'that image', "
                "'the cat picture', 'the stakeholder value one', 'the photo I "
                "uploaded' - so the right one can be found among the pictures "
                "they have."
            ),
        },
    },
    "required": ["which"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Showing a picture again",
    description=(
        "Show or send again a picture the user already has here - one made, "
        "edited, or uploaded earlier in this conversation or their history - "
        "when they ask to see it, bring it back, pull it up, look at it again, "
        "or have it sent to them. Never for making a new picture or changing "
        "one, and never for a question about what is in a picture - answer "
        "those in words."
    ),
    schema=_SCHEMA,
    waiting=(
        "🔍 Finding that picture…",
        "🗂️ Pulling that one back out…",
        "📎 Fetching it for you…",
    ),
)


# The call as an action, or nothing when the model could not say which picture.
def parse(arguments: dict[str, Any]) -> ShowImageAction | None:
    which = required_text(arguments, "which")
    if which is None:
        return None
    return ShowImageAction(which=which)
