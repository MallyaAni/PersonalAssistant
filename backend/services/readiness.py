"""Has the person finished, and does it call for a reply?

People text in fragments: "ok" / "thai then" / "friday?". A timer cannot
tell a pause for thought from the end of a thought, and it was rejected for
that reason (2026-08-28). This asks the routing model, with a schema, the
two questions that decide what the worker does with what has arrived so
far: is the person done saying what they mean, and does what they said want
an answer. Not done: keep listening. Done and wanting one: answer the whole
burst at once. Done and wanting none ("sounds good, thanks"): stay quiet.
Same pattern as the follow-up resolver - one small judgement, one reading.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from backend.core.prompts import load

logger = logging.getLogger(__name__)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "complete": {"type": "boolean"},
        "needs_reply": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 160},
    },
    "required": ["complete", "needs_reply", "reason"],
    "additionalProperties": False,
}
_MAX_TOKENS = 120
_MAX_FRAGMENTS = 12
_PREVIOUS_CHARS = 600


@dataclass(frozen=True, slots=True)
class Readiness:
    """The judgement: finished or not, and whether an answer is wanted."""

    complete: bool
    needs_reply: bool
    reason: str = ""


# Fail open: when the model cannot be asked, the person is answered, which
# is the behaviour before this judgement existed.
FAIL_OPEN = Readiness(complete=True, needs_reply=True, reason="judgement unavailable")


# Judge what has arrived so far against the assistant's previous bubble.
# `fragments` are the person's messages since that bubble, oldest first.
async def judge_readiness(
    llm: Any, previous_reply: str, fragments: list[str], *, in_group: bool = False, addressed_by: str = ""
) -> Readiness:
    pieces = [" ".join(str(item or "").split()) for item in fragments[-_MAX_FRAGMENTS:]]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return Readiness(complete=True, needs_reply=False, reason="nothing said")
    said = " ".join(previous_reply.split())[-_PREVIOUS_CHARS:]
    numbered = "\n".join(f"{index}. {piece}" for index, piece in enumerate(pieces, start=1))
    setting = "a group chat with several people" if in_group else "a one-to-one text conversation"
    # How the message reached the assistant: a reply to its own bubble is a
    # deliberate address ("we are a groupie!!" as a reply wants an answer;
    # judged as a closing remark it got none, 2026-08-28).
    how = {
        "reply": "The person sent this as a reply to the assistant's own message (tap-and-hold reply).",
        "mention": "The person mentioned the assistant by name to send this.",
        "name": "The person addressed the assistant by name.",
    }.get(addressed_by, "")
    messages = [
        {"role": "system", "content": load("routing/readiness")},
        {
            "role": "user",
            "content": (
                f"Setting: {setting}. {how}\n"
                f"The assistant's previous message: {said or '(none)'}\n\n"
                f"What the person has sent since, in order:\n{numbered}"
            ),
        },
    ]
    try:
        answer = await asyncio.to_thread(llm.chat, messages, _MAX_TOKENS, _SCHEMA, 0.0)
    except Exception:
        logger.warning("Readiness judgement failed; answering the person", exc_info=True)
        return FAIL_OPEN
    return parse_readiness(answer)


# The model's answer as a Readiness; unreadable answers fail open.
def parse_readiness(answer: Any) -> Readiness:
    payload = answer.get("content") if isinstance(answer, dict) and "content" in answer else answer
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return FAIL_OPEN
    if not isinstance(payload, dict) or "complete" not in payload or "needs_reply" not in payload:
        return FAIL_OPEN
    return Readiness(
        complete=bool(payload.get("complete")),
        needs_reply=bool(payload.get("needs_reply")),
        reason=str(payload.get("reason") or "")[:160],
    )
