"""edit_image: one change to the picture in view."""

from typing import Any

from .actions import EditImageAction
from .base import BuiltinTool, required_text
from .contracts import EffectContract

NAME = "edit_image"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instruction": {
            "type": "string",
            "description": "The single change to make to the picture in view.",
        },
        # Asked of the model because only the request says which kind of edit
        # this is, and the two need opposite instructions to the image model.
        # Every edit used to be sent with "do not add, remove, or move
        # anything", which is right for recolouring a hat and self-defeating
        # for "make it look like it came in its original packaging" - that one
        # cannot be done without adding something, so the picture came back
        # unchanged.
        "restages_the_scene": {
            "type": "boolean",
            "description": (
                "True when carrying out the edit means changing the setting or "
                "introducing things that are not in the picture yet - putting "
                "the subject in packaging or another place, changing the "
                "season, weather, or time of day, or restyling the whole "
                "image. False for a change confined to something already "
                "visible, such as recolouring, removing, or relabelling one "
                "object, where everything else must stay exactly as it is."
            ),
        },
    },
    "required": ["instruction", "restages_the_scene"],
    "additionalProperties": False,
}

# Offered unconditionally, unlike generate_image's implicit sibling: a request
# to change "the picture" can arrive before the application's own idea of what
# is active agrees, and the only way to find that out is to let the model
# decide edit intent from the conversation, then let the caller check whether
# anything is actually in view - otherwise a missing selection answered as an
# ordinary chat turn with no explanation, which read as the feature being
# broken rather than a picture nobody had picked.
TOOL = BuiltinTool(
    name=NAME,
    label="Image edits",
    description=(
        "Change the picture currently in view, including adding labels or "
        "annotations to it. Never for a resume, document, "
        "email, message, plan, or schedule, including a short request to make "
        "that text more casual, formal, friendly, concise, or professional. "
        "Even when the message says 'edit' and no other "
        "tool fits that request - answer those directly instead of calling "
        "any tool. Only for a request to change the picture, never for a "
        "question about it, including one that names the alternative it is "
        "asking about: asking whether something would look better, which of "
        "two is preferable, or what you would recommend is asking what you "
        "think, not telling you to change anything, even when the same "
        "subject was just edited - answer it directly from what is already "
        "visible instead. A request made politely is still a request: 'can "
        "you add labels to this?', 'could you make it brighter?' and 'can you "
        "generate a labelled version of this?' each ask for the picture in "
        "view to be changed, and are this tool."
    ),
    schema=_SCHEMA,
    waiting=(
        "✂️ Touching that up…",
        "🪄 Waving the retouch wand…",
        "🎛️ Tweaking the pixels…",
    ),
    family="pictures",
    needs_picture=True,
    contract=EffectContract(effect="write", cost="expensive", creates=True),
)


# The call as an action, or nothing when the model left out the change.
def parse(arguments: dict[str, Any]) -> EditImageAction | None:
    instruction = required_text(arguments, "instruction")
    if instruction is None:
        return None
    return EditImageAction(
        instruction=instruction,
        restages_the_scene=bool(arguments.get("restages_the_scene")),
    )
