import re

from backend.artifacts.image_recall_classifier import ImageRecallClassifier
from backend.artifacts.image_routing import ImageRecallDecision, ImageRecallPolicy

# Consult the classifier only for queries that plausibly name a stored image: a
# recall verb pointing at a definite/possessive reference, or explicit creation
# or upload language. This keeps unrelated turns ("my name is Ani") from ever
# paying for a model call.
_CLASSIFIER_GATE = re.compile(
    r"\b(show|see|view|display|find|pull|bring|where|recall|remember)\b"
    r".{0,40}\b(the|that|those|this|these|my|our|your|it|one)\b"
    # Creation and upload verbs only count when they point at something that
    # already exists. A bare "generate an image of a car" names nothing stored,
    # and letting it through sent a fresh request to the classifier, which
    # answered recall and refined an unrelated old image instead.
    r"|\b(made|create|created|generate|generated|drew|drawn|design|designed|"
    r"render|rendered|paint|painted|upload|uploaded|save|saved|sketch|sketched)\b"
    r".{0,40}\b(the|that|those|this|these|my|our|your|it|one|earlier|before|"
    r"previous|last|yesterday|ago)\b",
    re.IGNORECASE,
)


def _might_reference_stored_image(query: str) -> bool:
    return bool(_CLASSIFIER_GATE.search(query))


class CascadingImageRecallRouter:
    """Deterministic recall patterns, with a bounded classifier for the rest.

    The patterns answer the obvious cases for free and cannot drift. When they
    abstain on a query that still plausibly names a stored image, a single-token
    classifier judges intent, so novel phrasings resolve without every unrelated
    turn paying for a model call. Routing stays owned by the application: the
    classifier returns a judgement, never a tool call.
    """

    def __init__(
        self,
        policy: ImageRecallPolicy,
        classifier: ImageRecallClassifier | None = None,
    ) -> None:
        self.policy = policy
        self.classifier = classifier

    # Resolve one query, consulting the classifier only when patterns abstain.
    async def decide(self, query: str) -> ImageRecallDecision:
        deterministic = self.policy.decide(query)
        # A decisive pattern outcome wins: a clear recall, a creation request, or
        # a disabled/empty turn. Only a plain abstention may defer.
        if deterministic.should_search or deterministic.reason != "no_signal":
            return deterministic
        if self.classifier is None or not _might_reference_stored_image(query):
            return deterministic
        judged = await self.classifier.references_stored_image(query)
        if judged is None:
            # An unavailable classifier must not start searching on its own.
            return deterministic
        if judged:
            return ImageRecallDecision(should_search=True, reason="classifier_yes")
        return ImageRecallDecision(should_search=False, reason="classifier_no")
