"""manage_skills: list or delete saved skills."""

from typing import Any

from .actions import ManageSkillsAction
from .base import BuiltinTool
from .contracts import EffectContract, normalize_words

NAME = "manage_skills"

OPERATIONS = ("list", "delete")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": list(OPERATIONS)},
        "which": {
            "type": "string",
            "description": (
                "Which skill, in the person's words, when deleting - 'the "
                "morning one', 'weekly wrap-up'. Empty for list."
            ),
        },
    },
    "required": ["operation"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Manage skills",
    description=(
        "List or delete the skills they already taught. Choose it when they "
        "ask what skills they have, or to forget or remove one. Changing what "
        "a skill does is a new save_skill with the same name."
    ),
    schema=_SCHEMA,
    waiting=(
        "📚 Opening the playbook…",
        "🗂️ Looking through your skills…",
    ),
    family="skills",
    contract=EffectContract(
        effect="write",
        cost="fast",
        idempotency=lambda action: "|".join(
            (action.operation, normalize_words(action.which))
        ),
    ),
)


# The call as an action, or nothing for an unknown operation.
def parse(arguments: dict[str, Any]) -> ManageSkillsAction | None:
    operation = arguments.get("operation")
    if operation not in OPERATIONS:
        return None
    which = arguments.get("which")
    return ManageSkillsAction(
        operation=str(operation), which=which.strip() if isinstance(which, str) else ""
    )
