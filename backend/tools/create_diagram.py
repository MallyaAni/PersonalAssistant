"""create_diagram: a technical diagram with real text in it."""

from typing import Any

from .actions import CreateDiagramAction
from .base import BuiltinTool, required_text, subject_schema
from .contracts import EffectContract

NAME = "create_diagram"

TOOL = BuiltinTool(
    name=NAME,
    label="Diagrams",
    description=(
        "Draft a technical diagram (flowchart, architecture diagram, sequence, "
        "state, class, or entity-relationship). What decides this is the kind "
        "of thing they asked for, not the subject they asked about: choose it "
        "when they name a diagram, chart, flowchart or one of the forms above. "
        "A technical subject does not by itself make the request a diagram - "
        "someone asking for an image or a picture of an architecture wants a "
        "picture of it, and generate_image is right even though the subject is "
        "technical. When they do ask for a diagram, this renders real text "
        "where a generated picture can only imitate writing."
    ),
    schema=subject_schema("diagram"),
    waiting=(
        "📐 Lining up the boxes and arrows…",
        "🧭 Charting that out…",
        "🗺️ Drawing the map…",
    ),
    family="diagrams",
    contract=EffectContract(effect="write", cost="expensive", creates=True),
)


# No subject means no decision: the turn goes down the ordinary reply path
# where the assistant asks for the one thing it is missing, rather than
# drawing a diagram of nothing.
def parse(arguments: dict[str, Any]) -> CreateDiagramAction | None:
    subject = required_text(arguments, "subject")
    return None if subject is None else CreateDiagramAction(subject)
