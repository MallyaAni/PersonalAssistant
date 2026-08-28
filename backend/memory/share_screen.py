"""Which of a member's memories may be said in a group of friends.

The operator's decision (2026-08-28): in a group where everyone is approved,
a member's non-sensitive memory is known automatically - their name, what
they like, the everyday things they have told the assistant - and only what
is sensitive stays theirs to share. Sensitivity is judged by meaning, on the
routing model with a schema, not by field or by keyword: "I drive a red
Mini" is fine among friends, "I'm seeing a therapist on Tuesdays" is not,
and no list of words tells those apart. Deterministic screens still run
first (`OutboundPrivacyPolicy`: secrets, card numbers, personal framing of
medical/financial/legal topics); this decides the rest.

Fails closed: when the judgement cannot be made, nothing is shared.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any

from backend.core.prompts import load

logger = logging.getLogger(__name__)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "private": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "1-based numbers of the statements that are private.",
        }
    },
    "required": ["private"],
    "additionalProperties": False,
}
_MAX_TOKENS = 160
_MAX_STATEMENTS = 12
_CACHE_LIMIT = 4096

# Verdicts by statement, per process: a member's memories change rarely and
# a room asks often.
_verdicts: OrderedDict[str, bool] = OrderedDict()


def _key(statement: str) -> str:
    return hashlib.sha256(" ".join(statement.split()).casefold().encode("utf-8")).hexdigest()


# The statements that may be said in the room, in their original order.
async def shareable(llm: Any, statements: tuple[str, ...]) -> tuple[str, ...]:
    pending = [s for s in statements[:_MAX_STATEMENTS] if _key(s) not in _verdicts]
    if pending:
        verdict = await _judge(llm, tuple(pending))
        if verdict is None:
            # Fail closed: nothing unjudged is shared, and nothing is cached
            # as a verdict that was never made.
            return tuple(s for s in statements if _verdicts.get(_key(s)) is True)
        for statement, ok in zip(pending, verdict, strict=True):
            _remember(_key(statement), ok)
    return tuple(s for s in statements[:_MAX_STATEMENTS] if _verdicts.get(_key(s)) is True)


def _remember(key: str, ok: bool) -> None:
    _verdicts[key] = ok
    _verdicts.move_to_end(key)
    while len(_verdicts) > _CACHE_LIMIT:
        _verdicts.popitem(last=False)


# One judgement over a numbered list: which are private. None when the model
# could not be asked or answered unreadably.
async def _judge(llm: Any, statements: tuple[str, ...]) -> tuple[bool, ...] | None:
    numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(statements, start=1))
    messages = [
        {"role": "system", "content": load("memory/share_in_group")},
        {"role": "user", "content": f"Statements:\n{numbered}"},
    ]
    try:
        answer = await asyncio.to_thread(llm.chat, messages, _MAX_TOKENS, _SCHEMA, 0.0)
    except Exception:
        logger.warning("Share screen failed; sharing nothing unjudged", exc_info=True)
        return None
    private = parse_private(answer)
    if private is None:
        return None
    return tuple(index not in private for index in range(1, len(statements) + 1))


# The set of 1-based indices the model marked private, or None if unreadable.
def parse_private(answer: Any) -> set[int] | None:
    payload = answer.get("content") if isinstance(answer, dict) and "content" in answer else answer
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict) or not isinstance(payload.get("private"), list):
        return None
    try:
        return {int(item) for item in payload["private"]}
    except (TypeError, ValueError):
        return None


# For tests and for a member's "forget me": drop cached verdicts.
def forget_verdicts() -> None:
    _verdicts.clear()
