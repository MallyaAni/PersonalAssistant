"""Whether something the person said is worth coming back to later.

Two things the operator asked for, on 2026-08-30: "how was the visit to
national harbor?" after an outing they had mentioned, and an occasional
"how are you doing?" when they had said they were unwell. Both are the
same shape - notice something in passing, say nothing now, come back once
at a sensible hour - and neither is a request, so the router never sees
them. The router fires on what a person asks for; this reads what they
merely mentioned.

Nothing new runs it and nothing new delivers it. A check-in is a one-off
scheduled task, which is a table, a worker, a delivery path per channel, a
silence token for a firing with nothing to say, and cancel-by-meaning that
the person already has ("cancel the national harbor one"). This module
only decides whether to arm one, and the caller in
`backend/services/checkin_arming.py` decides whether it is allowed to.

The judgement is deliberately reluctant. It sees one message at a time
with no memory of what it has already armed, so the cheap failure is
arming something every turn until the thread is a stream of questions.
Every bound that keeps that from happening is in the caller, in code:
this call can say yes as often as it likes and still arm nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.core.prompts import load

logger = logging.getLogger(__name__)

# The kinds a check-in can be. `event` follows something the person is doing
# or has just done; `wellbeing` follows how they said they were.
EVENT = "event"
WELLBEING = "wellbeing"
KINDS = (EVENT, WELLBEING)

# How far ahead a check-in may be armed. A fortnight is the outer edge of
# something a person would still recognise as following up rather than
# resurfacing; anything longer is a reminder they should have asked for.
MIN_DAYS = 0
MAX_DAYS = 14
# The civil window a check-in may land in. Quiet hours are the runner's
# business, but nothing here should ever propose 3am in the first place.
FIRST_HOUR = 9
LAST_HOUR = 21

_MAX_TOKENS = 200

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # Whether to come back to this at all. False for almost everything.
        "check_in": {"type": "boolean"},
        "kind": {"type": "string", "enum": list(KINDS)},
        # What to ask about, in the person's own terms: "the visit to
        # National Harbor", "the dentist appointment". Never a sentence.
        "subject": {"type": "string", "maxLength": 80},
        # Whole days from today. 0 means later today.
        "after_days": {"type": "integer"},
        # The local hour to ask at, 0-23; clamped by the caller either way.
        "hour": {"type": "integer"},
    },
    "required": ["check_in", "kind", "subject", "after_days", "hour"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class CheckIn:
    """One thing to come back to, and when."""

    kind: str
    subject: str
    after_days: int
    hour: int


# Clamp a value into a range. Written out rather than min(max(...)) so the
# intent - the model's number is a suggestion, the range is the rule - is
# the thing you read.
def _within(value: int, low: int, high: int) -> int:
    if value < low:
        return low
    return high if value > high else value


# What, if anything, is worth coming back to after this message. None for
# almost every turn, and None for every failure: a check-in is a courtesy,
# and no turn should ever be worse for one not being armed.
async def propose_check_in(
    llm: Any,
    said: str,
    reply: str = "",
    now: datetime | None = None,
    timezone: str = "",
) -> CheckIn | None:
    said = str(said or "").strip()
    if not said:
        return None
    moment = now or datetime.now(UTC)
    where = f" ({timezone})" if timezone else ""
    answered = f"\n\nThe assistant replied: {reply.strip()[:400]}" if reply.strip() else ""
    try:
        answer = await asyncio.to_thread(
            llm.chat,
            [
                {"role": "system", "content": load("checkin/propose")},
                {
                    "role": "user",
                    "content": (
                        f"Now: {moment.strftime('%A %Y-%m-%d %H:%M')}{where}\n\n"
                        f"They said: {said[:1000]}{answered}"
                    ),
                },
            ],
            _MAX_TOKENS,
            _SCHEMA,
            0.0,
        )
        decision = json.loads(str(answer["content"]))
    except Exception:
        logger.warning("check_in_judgement_failed", exc_info=True)
        return None

    if not decision.get("check_in"):
        return None
    kind = str(decision.get("kind") or "")
    subject = " ".join(str(decision.get("subject") or "").split())[:80]
    # A check-in with nothing to ask about is not a check-in. This is the
    # one field the schema cannot constrain into being useful.
    if kind not in KINDS or not subject:
        return None
    try:
        after_days = int(decision.get("after_days"))
        hour = int(decision.get("hour"))
    except (TypeError, ValueError):
        return None
    return CheckIn(
        kind=kind,
        subject=subject,
        after_days=_within(after_days, MIN_DAYS, MAX_DAYS),
        hour=_within(hour, FIRST_HOUR, LAST_HOUR),
    )
