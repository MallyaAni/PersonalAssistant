"""A cross-encoder second opinion on retrieval candidates.

A bi-encoder retrieves by comparing two vectors that never saw each other; a
reranker reads query and candidate together, which is where retrieval
precision actually comes from. This client speaks vLLM's Cohere-shaped
/v1/rerank endpoint (Qwen3-Reranker served with `--runner pooling`).

Fail-soft is the contract: reranking improves an ordering that already
exists, so an unreachable or misbehaving reranker returns None and the
caller keeps its cosine order. It must never cost the turn - vLLM's /score
family has a recorded hang on specific inputs, so the timeout is the guard,
not politeness.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.config.settings import settings

logger = logging.getLogger(__name__)


# Whether a reranker is configured at all; empty URL means the stage is off
# and callers keep their first-pass ordering.
def reranker_enabled() -> bool:
    return bool(settings.RERANKER_BASE_URL.strip())


# Scores for each document against the query, aligned by index, or None.
async def rerank(query: str, documents: list[str]) -> list[float] | None:
    if not reranker_enabled() or not documents:
        return None
    payload: dict[str, Any] = {
        "model": settings.RERANKER_MODEL,
        "query": query,
        "documents": documents,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.RERANKER_TIMEOUT_SECONDS
        ) as client:
            # /v2/rerank, measured on the deployed build: /v1/rerank and
            # /rerank are registered but reset the connection there, while
            # /v2 answers - and it is the JinaAI-conformant shape the server
            # itself points clients at.
            answer = await client.post(
                f"{settings.RERANKER_BASE_URL.rstrip('/')}/v2/rerank", json=payload
            )
            answer.raise_for_status()
            body = answer.json()
    except Exception:
        logger.warning("Reranker unavailable; keeping first-pass order")
        return None
    scores = [0.0] * len(documents)
    seen = 0
    for item in body.get("results") or []:
        index = item.get("index")
        score = item.get("relevance_score")
        if isinstance(index, int) and 0 <= index < len(documents):
            try:
                scores[index] = float(score)
                seen += 1
            except (TypeError, ValueError):
                continue
    # A response that scored nothing is a malfunction, not an ordering.
    return scores if seen else None
