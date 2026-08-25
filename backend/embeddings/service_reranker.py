"""The Scout cross-encoder served remotely, on the local ONNX contract.

Precision ranking speaks RerankProvider: synchronous score(pairs), log-odds,
higher is better, typically negative. The vLLM reranker answers /v2/rerank
with yes/no probabilities instead, so this adapter converts each probability
back to its log-odds (ln(p/(1-p))) - the quantity the classifier head
computed before its softmax - which keeps every downstream constant
meaningful, MIN_ATTRIBUTION_MARGIN above all.

Failure raises. PrecisionRanker already treats a scoring failure as absence
and keeps the embedding order; that decision belongs there, not here, and a
silent zero from this layer would rank instead of abstaining.
"""

from __future__ import annotations

import math

import httpx

from backend.config.settings import settings
from backend.core.interfaces import RerankProvider

# Probabilities at exactly 0 or 1 would produce infinite log-odds; the clamp
# bounds them near +/-13.8, comfortably outside the -11..+3 band the local
# model produces, so a saturated answer still wins or loses by a margin.
_EPSILON = 1e-6


class ServiceCrossEncoder(RerankProvider):
    """Score (query, document) pairs against the vLLM reranker service."""

    # The transport hook exists for tests; production constructs the default.
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    # Mirrors the local provider's missing-weights convention: an empty base
    # URL means the stage is absent, and callers already know what absence means.
    def is_enabled(self) -> bool:
        return bool(settings.RERANKER_BASE_URL.strip())

    # One request per distinct query, because /v2/rerank ranks many documents
    # under a single query while this contract scores arbitrary pairs - and
    # precision ranking builds its pairs as profiles x documents, so grouping
    # collapses the call count to the number of aimed interests.
    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = [0.0] * len(pairs)
        by_query: dict[str, list[int]] = {}
        for position, (query, _) in enumerate(pairs):
            by_query.setdefault(query, []).append(position)
        with httpx.Client(
            timeout=settings.RERANKER_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            for query, positions in by_query.items():
                documents = [pairs[position][1] for position in positions]
                answer = client.post(
                    f"{settings.RERANKER_BASE_URL.rstrip('/')}/v2/rerank",
                    json={
                        "model": settings.RERANKER_MODEL,
                        "query": query,
                        "documents": documents,
                    },
                )
                answer.raise_for_status()
                results = answer.json().get("results") or []
                if len(results) != len(documents):
                    raise ValueError(
                        "reranker returned a different number of scores "
                        "than documents sent"
                    )
                for item in results:
                    scores[positions[int(item["index"])]] = _log_odds(
                        float(item["relevance_score"])
                    )
        return scores


# The inverse of the sigmoid the service applied, restoring the raw logit.
def _log_odds(probability: float) -> float:
    clamped = min(max(probability, _EPSILON), 1.0 - _EPSILON)
    return math.log(clamped / (1.0 - clamped))
