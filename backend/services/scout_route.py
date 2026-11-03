"""Whether a message is about Scout's own record, or about people.

The router is a model, and a Scout tool is a strong match for any message
that names the assistant. On the live sweep of 2026-11-03 "Scout, what do
we both like?" took the digest route 2 times in 10 against the running
selector even after the tool's description said preferences belong to
search_history; with the digest withheld it took the schedule route
instead. The description and the routing prompt are prompts, and a single
passing probe hid the near-tie. So the guard is one small judgement with a
schema, the same pattern as readiness and the follow-up resolver. It is
asked only after the router has already chosen a Scout tool, so an
ordinary turn pays nothing for it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.core.prompts import load

logger = logging.getLogger(__name__)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "about_scout_record": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 160},
    },
    "required": ["about_scout_record", "reason"],
    "additionalProperties": False,
}
_MAX_TOKENS = 120


# Fail open: when the model cannot be asked, the router's choice stands. This
# is an improvement on a near-tie, not a safety refusal, and a legitimate
# digest or schedule question must not be lost because the judge was
# unavailable.
FAIL_OPEN = True


# Whether the message is really about what Scout sent or when it runs, rather
# than about what people like or share. `history` is the same bounded recent
# conversation the router saw, so a short follow-up is judged in its thread.
async def judge_scout_record(llm: Any, message: str, history: str = "") -> bool:
    asked = " ".join(str(message or "").split())
    if not asked:
        return FAIL_OPEN
    context = f"Recent conversation:\n{history}\n\n" if history.strip() else ""
    messages = [
        {"role": "system", "content": load("routing/scout_record")},
        {"role": "user", "content": f"{context}Newest message: {asked}"},
    ]
    try:
        answer = await asyncio.to_thread(
            llm.chat, messages, _MAX_TOKENS, _SCHEMA, 0.0
        )
    except Exception:
        logger.warning(
            "Scout record judgement failed; keeping the router's choice",
            exc_info=True,
        )
        return FAIL_OPEN
    return parse_scout_record(answer)


# The model's answer as a boolean; unreadable answers fail open.
def parse_scout_record(answer: Any) -> bool:
    payload = (
        answer.get("content")
        if isinstance(answer, dict) and "content" in answer
        else answer
    )
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return FAIL_OPEN
    if not isinstance(payload, dict) or "about_scout_record" not in payload:
        return FAIL_OPEN
    return bool(payload.get("about_scout_record"))
