"""save_skill: teach a named skill - "when I say X, do Y"."""

from typing import Any

from .actions import SaveSkillAction
from .base import BuiltinTool, required_text

NAME = "save_skill"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "The short name the person will use to invoke it - 'morning "
                "brief', 'weekly wrap-up' - exactly as they said it."
            ),
        },
        "instruction": {
            "type": "string",
            "description": (
                "What to do when the skill is invoked, rewritten as a "
                "complete, self-contained instruction in the person's own "
                "terms: every step they listed, in order, with the places, "
                "names and details they gave. Nothing about when or how they "
                "trigger it - only what happens."
            ),
        },
    },
    "required": ["name", "instruction"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Skills",
    description=(
        "Save a named routine the person can invoke later by name or by "
        "meaning: choose it when they are teaching one - 'when I say morning "
        "brief, give me the weather and my tasks', 'make a skill called "
        "weekly wrap-up that...', 'remember this as my standup routine'. The "
        "message defines what the routine does; it is not asking for it to "
        "run now. A skill can be scheduled afterwards like any task."
    ),
    schema=_SCHEMA,
    waiting=(
        "🧠 Learning that routine…",
        "📝 Writing it into the playbook…",
        "⚡ Wiring up a new skill…",
    ),
    family="skills",
)


# The call as an action, or nothing when the model left out the name or
# what the skill does.
def parse(arguments: dict[str, Any]) -> SaveSkillAction | None:
    name = required_text(arguments, "name")
    instruction = required_text(arguments, "instruction")
    if name is None or instruction is None:
        return None
    return SaveSkillAction(name=name, instruction=instruction)
