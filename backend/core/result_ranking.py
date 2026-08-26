"""Order web results by usefulness with the main model, in one constrained call.

The providers' order does not read the question, and the deployed 0.6B
cross-encoder read it badly (see prompts/search/rank.md). The model that
answers the person reads the question, the place and the dates the way they
do, so it orders the results before it sees them as evidence. One short call
at temperature zero with a schema the engine enforces; any failure - a
missing or malformed order, a refusal, a timeout - keeps the providers'
order, which is what it was anyway.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from backend.core.prompts import load

logger = logging.getLogger(__name__)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
    },
    "required": ["order"],
    "additionalProperties": False,
}
_MAX_TOKENS = 256
_CONTENT_CHARS = 400


# Pseudo-scores in the model's order (higher is more useful), one per result,
# or None when the order cannot be trusted. Shaped to slot into the same
# caller a cross-encoder's scores would.
async def order_by_usefulness(
    llm: Any,
    question: str,
    place: str,
    results: list[dict[str, Any]],
    now: datetime | None = None,
    known: tuple[str, ...] = (),
) -> list[float] | None:
    if len(results) < 2:
        return None
    today = (now or datetime.now(UTC)).strftime("%A %Y-%m-%d")
    # What the turn already retrieved about the person - interests, facts -
    # handed to the ranker as a tie-breaker only. It reorders results that
    # already answer the question; it cannot add, invent, or outrank.
    facts = [str(item).strip()[:160] for item in known if str(item).strip()][:8]
    about = (
        "What is known about the person (use only to break ties between results "
        "that answer the question equally well; it must never outrank answering "
        "the question):\n" + "\n".join(f"- {fact}" for fact in facts) + "\n"
        if facts
        else ""
    )
    listing = "\n\n".join(
        f"[{index}] {str(item.get('title') or '')[:200]}\n{str(item.get('url') or '')[:200]}\n"
        f"{str(item.get('content') or '')[:_CONTENT_CHARS]}"
        for index, item in enumerate(results, start=1)
    )
    where = f"Asked from: {place}\n" if place else "Asked from: not known\n"
    try:
        messages = [
            {"role": "system", "content": load("search/rank")},
            {
                "role": "user",
                "content": f"Question: {question}\n{where}Today: {today}\n{about}\nResults:\n\n{listing}",
            },
        ]
        answer = await asyncio.to_thread(llm.chat, messages, _MAX_TOKENS, _SCHEMA, 0.0)
    except Exception:
        logger.warning("Result ranking call failed; keeping provider order", exc_info=True)
        return None
    order = _parse_order(answer, len(results))
    if order is None:
        return None
    scores = [0.0] * len(results)
    for position, index in enumerate(order):
        scores[index - 1] = float(len(results) - position)
    return scores


# The model's order as 1-based indices, or None unless it is a permutation.
def _parse_order(answer: Any, count: int) -> list[int] | None:
    import json

    payload = answer
    if isinstance(answer, dict) and "content" in answer:
        payload = answer["content"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    order = payload.get("order") if isinstance(payload, dict) else None
    if not isinstance(order, list):
        return None
    try:
        indices = [int(value) for value in order]
    except (TypeError, ValueError):
        return None
    if sorted(indices) != list(range(1, count + 1)):
        return None
    return indices
