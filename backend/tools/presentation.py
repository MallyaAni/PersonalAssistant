"""delegate_to_presentation_agent: hand a slide deck to the specialist."""

from typing import Any

from .actions import DelegateAction
from .base import BuiltinTool, required_text, subject_schema

NAME = "delegate_to_presentation_agent"

TOOL = BuiltinTool(
    name=NAME,
    label="Presentations",
    description="Hand off to the specialist that builds slide decks.",
    schema=subject_schema("deck"),
    waiting=(
        "📊 Calling in the deck crew…",
        "🎞️ Handing this to the slide specialist…",
    ),
)


# No subject means no decision, rather than queueing a subjectless deck.
def parse(arguments: dict[str, Any]) -> DelegateAction | None:
    subject = required_text(arguments, "subject")
    return None if subject is None else DelegateAction("presentation_agent", subject)
