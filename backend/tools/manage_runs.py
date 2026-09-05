"""manage_runs: the person's say over the runs working for them - a yes or a
no to a run waiting on their permission, or a look at what is running."""
from typing import Any

from .actions import ManageRunsAction
from .base import BuiltinTool
from .contracts import EffectContract, normalize_words

NAME = "manage_runs"
MODES = ("approve", "deny", "status")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": list(MODES),
            "description": (
                "approve when they give a waiting run permission to go on "
                "('yes, go ahead', 'send it', 'that's fine'); deny when they "
                "refuse it ('no', 'don't send that', 'stop'); status when they "
                "ask what is running or waiting for them."
            ),
        },
        "which": {
            "type": "string",
            "description": (
                "When more than one run is waiting: the one they mean, as the "
                "number from the list they were shown or the words they used "
                "for it. Empty when there is only one or they did not say."
            ),
        },
    },
    "required": ["mode"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Background runs",
    description=(
        "Background runs: work the assistant is finishing on its own after a "
        "turn ran out of time, or an agent's review or investigation. A run "
        "that is about to send, spend or change something outside this "
        "system stops and asks the person first. Choose this when they answer "
        "such a request - a yes or a no to a run the conversation shows "
        "waiting for their permission - or when they ask what is running or "
        "waiting for them in the background. A yes or no that answers a "
        "question the assistant just asked in conversation, with no run "
        "waiting, is not this."
    ),
    schema=_SCHEMA,
    waiting=(
        "🗂️ Checking on that run…",
        "✅ Passing that along…",
    ),
    family="scheduling",
    contract=EffectContract(
        effect="write",
        cost="fast",
        reversible="none",
        creates=lambda action: False,
        idempotency=lambda action: "|".join((action.mode, normalize_words(action.which))),
    ),
)


# The call as an action, or nothing when the mode is not one of ours.
def parse(arguments: dict[str, Any]) -> ManageRunsAction | None:
    mode = str(arguments.get("mode") or "").strip().lower()
    if mode not in MODES:
        return None
    which = " ".join(str(arguments.get("which") or "").split())
    return ManageRunsAction(mode=mode, which=which)
