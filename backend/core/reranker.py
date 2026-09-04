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

import asyncio
import logging
from functools import lru_cache
from typing import Any

import httpx

from backend.config.settings import settings

logger = logging.getLogger(__name__)


# Whether a reranker is configured at all; empty URL means the stage is off
# and callers keep their first-pass ordering.
# The cross-encoder this stage uses, built once and kept.
#
# Measured 2026-09-03 on five recall questions over the same six turns, warm:
#
#   served Qwen3-Reranker-0.6B   2/5 right   67.6 ms   holds ~3.6 GB
#   local ms-marco MiniLM L6     5/5 right   39.6 ms   no GPU memory
#
# The served model put the one document that named the trip *last* for "what
# did we say about the Amalfi trip?" and a sentence about a couch second. The
# local one is the cascade's own second stage, already deployed for Scout, and
# `embeddings/cross_encoder.py` argues in its own words why it belongs on the
# CPU: a resident GPU reranker takes memory from the model answering people.
# So recall uses the same encoder Scout does, and the served one is spare.
@lru_cache(maxsize=1)
def _local_encoder() -> Any | None:
    from backend.embeddings.cross_encoder import OnnxCrossEncoder

    encoder = OnnxCrossEncoder(
        model_path=settings.DISCOVERY_CROSS_ENCODER_MODEL_PATH,
        tokenizer_path=settings.DISCOVERY_CROSS_ENCODER_TOKENIZER_PATH,
        intra_op_threads=settings.DISCOVERY_CROSS_ENCODER_THREADS,
    )
    return encoder if encoder.is_enabled() else None


def reranker_enabled() -> bool:
    if settings.RECALL_RERANKER_SOURCE == "service":
        return bool(settings.RERANKER_BASE_URL.strip())
    return _local_encoder() is not None


# Scores for each document against the query, aligned by index, or None.
async def rerank(query: str, documents: list[str]) -> list[float] | None:
    if not reranker_enabled() or not documents:
        return None
    if settings.RECALL_RERANKER_SOURCE != "service":
        encoder = _local_encoder()
        if encoder is None:
            return None
        try:
            scores = await asyncio.to_thread(
                encoder.score, [(query, document) for document in documents]
            )
        except Exception:
            logger.warning("Cross-encoder unavailable; keeping first-pass order")
            return None
        return list(scores) if scores else None
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
