import logging

from backend.search.classifier import QueryFreshnessClassifier
from backend.search.routing import SearchDecision, SearchRoutingPolicy

logger = logging.getLogger(__name__)


class CascadingSearchRouter:
    """Decides when a turn needs live data, cheaply first and then carefully.

    Deterministic patterns answer the obvious cases for free and cannot drift.
    Measured against FreshQA they recall only 45.6% of questions whose answers
    change, because people rarely phrase volatility explicitly: "When did
    OpenAI release GPT-5?" needs live data and contains no temporal marker.

    Anything the patterns do not match is referred to a bounded classifier that
    returns a judgement, never a tool call. Routing therefore stays owned by the
    application: the model contributes an opinion about the question, and the
    application decides what to do with it.
    """

    # Compose the free fast path with the fallback judgement.
    def __init__(
        self,
        patterns: SearchRoutingPolicy,
        classifier: QueryFreshnessClassifier | None = None,
    ) -> None:
        self.patterns = patterns
        self.classifier = classifier

    # Resolve one query, consulting the classifier only when patterns abstain.
    async def decide(self, query: str) -> SearchDecision:
        deterministic = self.patterns.decide(query)
        if deterministic.should_search:
            return deterministic
        # Blank input and a disabled policy are settled, not merely unmatched.
        if deterministic.reason != "no_signal" or self.classifier is None:
            return deterministic

        judgement = await self.classifier.requires_current_information(query)
        if judgement is None:
            # An unavailable classifier must not silently start searching every
            # turn, so the deterministic answer stands.
            return SearchDecision(should_search=False, reason="classifier_unavailable")
        if judgement:
            return SearchDecision(should_search=True, reason="classifier_yes")
        return SearchDecision(should_search=False, reason="classifier_no")
