"""What every built-in tool is made of."""

from dataclasses import dataclass
from typing import Any

from .contracts import UNDECLARED, EffectContract


@dataclass(frozen=True, slots=True)
class BuiltinTool:
    """One built-in action, written down once and read by both callers.

    The reply prompt has to tell the user what AniOS can do, and the router
    has to tell the routing model when each tool fires. Those were two hand-
    written lists in two files saying the same thing in different words, which
    is a drift waiting to happen: the prompt's wording would govern what the
    assistant claims while the wording here governs what actually runs. One
    row carries both, so a tool cannot be added, removed, or disabled in
    routing while conversation goes on describing the old set.

    `label` is what to call the capability in conversation; `description` is
    the router's own account of what it does and when it applies, and is
    reused verbatim rather than paraphrased. `waiting` is what the person
    sees while the tool runs - a little play, with an emoji, the way a
    friend texts "on it" rather than "processing".
    """

    name: str
    label: str
    description: str
    schema: dict[str, Any]
    waiting: tuple[str, ...] = ()
    # What the catalogue needs to know about this tool, kept on the row for
    # the same reason `label` and `description` are: a set of tool names
    # written out in another module goes stale the day a tool is renamed,
    # and nothing fails loudly when it does.
    #
    # `family` groups a tool with its siblings, so one catalogue search that
    # matches "document" pulls the whole family - the namespacing both
    # Anthropic and OpenAI recommend for a deferred tool set.
    family: str = ""
    # Loaded on every turn rather than catalogued. True for the few tools
    # most turns actually use, measured rather than guessed.
    core: bool = False
    # Loaded only when a picture is in view. The interface state already
    # decides whether these can be used at all.
    needs_picture: bool = False
    # What the tool does to the world, read by the loop's policy: whether a
    # later step may start it, what a repeat of it is compared on, whether
    # it creates something, and whether a dropped call may be replayed. The
    # default declares nothing and so is offered to no later step; every
    # row here declares its own. See `contracts.py`.
    contract: EffectContract = UNDECLARED

    # The same row as a capability line for the reply prompt's context.
    def as_capability(self) -> dict[str, str]:
        return {"label": self.label, "description": self.description}


# Asked of the tools that otherwise take no arguments. The point is not to
# pass it on - they read the request itself - but to make the model state
# what it believes it was asked to make. A tool chosen by mistake has no
# subject to state, and the caller can see that before spending the turn on
# it instead of after, when a deck is already queued.
def subject_schema(what: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": (
                    f"What the {what} is about, in a few words, taken from the "
                    "request. Leave empty if the request does not say."
                ),
            }
        },
        "required": ["subject"],
        "additionalProperties": False,
    }


# The one argument a built-in tool cannot do without, or nothing.
#
# A tool call carrying an empty required string is not a decision the model
# made, it is a tool it picked without being able to say what for. Every
# built-in treats that as no call at all rather than acting on a blank.
def required_text(arguments: dict[str, Any], field: str) -> str | None:
    value = arguments.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
