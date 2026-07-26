import re
from dataclasses import dataclass

# Deterministic signals that a request is asking to recall a stored image
# rather than to create one. The model never selects this path: routing stays
# in the application so a recall request cannot be answered from the model's
# own imagination when a matching image exists on disk.
_RECALL_SIGNALS: tuple[tuple[str, str], ...] = (
    (
        r"\b(show|find|search|pull\s+up|bring\s+up)\s+(me\s+)?(the\s+|my\s+|any\s+)?"
        r"(image|images|picture|pictures|photo|photos|pic|pics)\b",
        "explicit_recall",
    ),
    (
        r"\b(do|did)\s+i\s+(have|save|upload|make|create|generate)\b.*"
        r"\b(image|images|picture|pictures|photo|photos|pic|pics)\b",
        "ownership_question",
    ),
    (r"\b(which|what)\s+(image|images|picture|pictures|photo|photos)\b", "which_image"),
    (r"\b(image|picture|photo)\s+(of|with|showing)\b", "descriptive_reference"),
    (r"\bmy\s+(image|images|picture|pictures|photo|photos|pic|pics)\b", "possessive"),
    (
        r"\b(this|that|the|last|previous)\s+(?:[\w-]+\s+){0,3}"
        r"(image|picture|photo|car|vehicle|object|scene)\b",
        "referential_image",
    ),
)

# Asking to see something previously generated, whatever its subject noun is:
# "show me the red sports car I generated earlier". This catches references by
# content that the image/picture keyword patterns miss. A pure creation request
# is excluded first because it has no recall verb.
_CREATED_REFERENCE_PATTERN = re.compile(
    r"\b(show|see|view|display|find|pull\s+up|bring\s+up|recall|remember|"
    r"where(?:'s|\s+is|\s+are)?|what\s+was|what\s+did)\b.{0,80}?"
    r"\b(generated?|created?|made|drew|drawn|painted|rendered|designed)\b",
    re.IGNORECASE,
)

_HISTORICAL_CREATION_PATTERN = re.compile(
    r"\b(what|which|who|where|when|why|how|did|does|do|is|are|was|were)\b.*"
    r"\b(create|created|generate|generated|make|made)\b.*"
    r"\b(image|images|picture|pictures|photo|photos|pic|pics)\b",
    re.IGNORECASE,
)

_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in _RECALL_SIGNALS
)

# Requests to produce a new image must never be answered with an old one.
_CREATION_PATTERN = re.compile(
    r"\b(generate|create|draw|make|paint|render|design)\b.{0,80}"
    r"\b(image|picture|photo|illustration|artwork)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ImageRecallDecision:
    """Application decision about whether to search stored images."""

    should_search: bool
    reason: str


class ImageRecallPolicy:
    """Deterministic policy deciding when a turn should search stored images."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    # Classify one query using ordered deterministic signals.
    def decide(self, query: str) -> ImageRecallDecision:
        if not self.enabled:
            return ImageRecallDecision(should_search=False, reason="disabled")
        if not query or not query.strip():
            return ImageRecallDecision(should_search=False, reason="empty_query")
        # Only a historical creation question precedes the creation rule.
        if _HISTORICAL_CREATION_PATTERN.search(query):
            return ImageRecallDecision(
                should_search=True,
                reason="creation_history_question",
            )
        if _CREATION_PATTERN.search(query):
            return ImageRecallDecision(should_search=False, reason="creation_request")
        if _CREATED_REFERENCE_PATTERN.search(query):
            return ImageRecallDecision(should_search=True, reason="created_reference")

        for pattern, reason in _COMPILED:
            if pattern.search(query):
                return ImageRecallDecision(should_search=True, reason=reason)

        return ImageRecallDecision(should_search=False, reason="no_signal")
