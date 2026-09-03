"""Has the person finished, does it call for a reply, or accept an offer?

People text in fragments: "ok" / "thai then" / "friday?". A timer cannot
tell a pause for thought from the end of a thought, and it was rejected for
that reason (2026-08-28). This asks the routing model, with a schema, the
judgements that decide what the worker does with what has arrived so
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
        "accepts_offer": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 160},
    },
    "required": ["complete", "needs_reply", "accepts_offer", "reason"],
    "additionalProperties": False,
}
_MAX_TOKENS = 120
_MAX_FRAGMENTS = 12
_PREVIOUS_CHARS = 600


@dataclass(frozen=True, slots=True)
class Readiness:
    """Completion, reply need, and unambiguous acceptance of an offer."""

    complete: bool
    needs_reply: bool
    reason: str = ""
    accepts_offer: bool = False


# Fail open: when the model cannot be asked, the person is answered, which
# is the behaviour before this judgement existed.
FAIL_OPEN = Readiness(
    complete=True,
    needs_reply=True,
    reason="judgement unavailable",
    accepts_offer=False,
)


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
        "tapback": (
            "The person left a positive heart or thumbs-up tapback on exactly "
            "the assistant message shown below."
        ),
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
    verdict = parse_readiness(answer)
    # A tapback is complete by its nature: it is one reaction on one bubble
    # and nothing more is coming. Whether it accepts an offer is the model's
    # call; whether the burst is finished is not - asked, the model called a
    # heart on "Thai or pizza?" ambiguous once in three runs (2026-09-03).
    if addressed_by == "tapback" and not verdict.complete:
        return Readiness(
            complete=True,
            needs_reply=verdict.needs_reply or verdict.accepts_offer,
            reason=verdict.reason,
            accepts_offer=verdict.accepts_offer,
        )
    return verdict


# The model's answer as a Readiness; unreadable answers fail open.
def parse_readiness(answer: Any) -> Readiness:
    payload = answer.get("content") if isinstance(answer, dict) and "content" in answer else answer
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return FAIL_OPEN
    if (
        not isinstance(payload, dict)
        or "complete" not in payload
        or "needs_reply" not in payload
        or "accepts_offer" not in payload
    ):
        return FAIL_OPEN
    return Readiness(
        complete=bool(payload.get("complete")),
        needs_reply=bool(payload.get("needs_reply")),
        reason=str(payload.get("reason") or "")[:160],
        accepts_offer=bool(payload.get("accepts_offer")),
    )
