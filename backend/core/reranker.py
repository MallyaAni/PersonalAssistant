"""A cross-encoder second opinion on retrieval candidates.

A bi-encoder retrieves by comparing two vectors that never saw each other; a
reranker reads query and candidate together, which is where retrieval
precision actually comes from.

It runs on the CPU, on the same ONNX cross-encoder Scout's precision ranking
uses. It used to speak to a served Qwen3-Reranker over HTTP, and both were
measured 2026-09-03 on five recall questions over the same six turns, warm:

    served Qwen3-Reranker-0.6B   2/5 right   67.6 ms   holds ~3.6 GB
    local ms-marco MiniLM L6     5/5 right   39.6 ms   no GPU memory

The served model put the one document that named the trip *last* for "what
did we say about the Amalfi trip?", and a sentence about a couch second. So
the service was retired and this is the only path; `embeddings/cross_encoder.py`
argues in its own words why it belongs on the CPU, and the short version is
that a resident GPU reranker takes memory from the model answering people.

Fail-soft is the contract: reranking improves an ordering that already
exists, so an encoder that cannot load or score returns None and the caller
keeps its cosine order. It must never cost the turn.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

from backend.config.settings import settings

logger = logging.getLogger(__name__)


# The cross-encoder this stage uses, built once and kept. None when the model
# files are absent, which leaves recall on its first-pass ordering rather than
# failing a turn.
@lru_cache(maxsize=1)
def _local_encoder() -> Any | None:
    from backend.embeddings.cross_encoder import OnnxCrossEncoder

    encoder = OnnxCrossEncoder(
        model_path=settings.DISCOVERY_CROSS_ENCODER_MODEL_PATH,
        tokenizer_path=settings.DISCOVERY_CROSS_ENCODER_TOKENIZER_PATH,
        intra_op_threads=settings.DISCOVERY_CROSS_ENCODER_THREADS,
    )
    return encoder if encoder.is_enabled() else None


# Whether the stage can run at all. Callers keep their first-pass ordering
# when it cannot.
def reranker_enabled() -> bool:
    return _local_encoder() is not None


# Scores for each document against the query, aligned by index, or None.
async def rerank(query: str, documents: list[str]) -> list[float] | None:
    if not documents:
        return None
    encoder = _local_encoder()
    if encoder is None:
        return None
    try:
        # Off the event loop: scoring is CPU-bound and a turn is waiting.
        scores = await asyncio.to_thread(
            encoder.score, [(query, document) for document in documents]
        )
    except Exception:
        logger.warning("Cross-encoder unavailable; keeping first-pass order")
        return None
    return list(scores) if scores else None
