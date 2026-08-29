"""generate_image: a brand-new picture from a description."""

from typing import Any

from .actions import GenerateImageAction
from .base import BuiltinTool, required_text

NAME = "generate_image"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "Exactly what to draw, as a self-contained subject.",
        },
        # Asked here because the model already knows it, and the alternative
        # was a word list. `mentions_a_person` matched "my", "me", "i", "her"
        # among others, so "draw me a picture of my car" was a person and got
        # skin-and-hair styling applied to a car.
        "depicts_a_person": {
            "type": "boolean",
            "description": (
                "True when the picture would show a person or people. False "
                "for objects, places, animals, food, or diagrams."
            ),
        },
    },
    "required": ["prompt", "depicts_a_person"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="New images",
    description=(
        "Create a brand-new picture from a text description, when the user "
        "asks for an image, picture, drawing, or artwork to be made. Writing "
        "is not drawing: a request to write a poem, haiku, song, story, "
        "caption, description, or any other text is never this tool, however "
        "visual its subject - 'write a haiku about rain' is answered in words "
        "and nothing is drawn. Call this tool only when the thing being asked "
        "for is itself a picture."
    ),
    schema=_SCHEMA,
    waiting=(
        "🎨 Mixing the paints…",
        "🖌️ Sketching that out…",
        "✨ Conjuring pixels…",
        "🖼️ Stretching a fresh canvas…",
    ),
)


# The call as an action, or nothing when the model left out what to draw.
def parse(arguments: dict[str, Any]) -> GenerateImageAction | None:
    prompt = required_text(arguments, "prompt")
    if prompt is None:
        return None
    return GenerateImageAction(
        prompt=prompt,
        depicts_a_person=bool(arguments.get("depicts_a_person")),
    )
