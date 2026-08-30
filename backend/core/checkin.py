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

Three things here are deliberately open rather than enumerated, because
the situations worth following up on are not a list anyone can finish:

  * **The model writes the question.** An outing and an illness were the
    two examples asked for, but "waiting to hear back about the flat" and
    "nervous about Thursday's exam" are the same shape and fit neither
    template. A fixed sentence per category would silently cap what can
    ever be noticed at the categories someone thought of first.
  * **The kinds describe what governs the rules, not what happened.**
    `wellbeing` exists because it alone carries a cooldown and a privacy
    rule; everything else is one open kind. Adding a category to a schema
    enum would mean a migration and a prompt edit for something the model
    can already recognise.
  * **Whether this is already covered is asked, not computed.** The call
    is given what is already waiting and answers false if this is the same
    thing said differently. A word-overlap comparison in the caller stays
    as a backstop, but it is not what has to be right.
  * **A plan that is called off calls off its check-in.** The same call
    that notices "we're going to National Harbor on Saturday" notices "we
    cancelled the Harbor trip" and "Harbor moved to next weekend", and
    names which waiting thing the message is about. Without that the
    feature has a failure worse than silence: it asks how a trip went that
    the person had already told it was off.

The judgement is otherwise reluctant. It sees one message at a time and
remembers nothing beyond what it is handed, so the cheap failure is arming
something every turn until the thread is a stream of questions. Every
bound that keeps that from happening is in the caller, in code: this call
can say yes as often as it likes and still arm nothing.
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

# The kinds a check-in can be.
#
# `wellbeing` is its own kind because it alone is governed differently: it
# is rationed to one a week, and it is the one that must never be asked in
# a room. `following_up` is everything else - an outing, a trip, an
# appointment, an interview, a result someone is waiting on - because those
# are all governed identically and enumerating them would only ever be a
# list of the situations we happened to think of.
WELLBEING = "wellbeing"
FOLLOWING_UP = "following_up"
KINDS = (FOLLOWING_UP, WELLBEING)

# How far ahead a check-in may be armed.
#
# The cap refuses rather than clamps, which is the whole point of it being
# here. Clamping a wedding ninety days out into the fourteen-day window
# does not produce a smaller mistake, it produces "how was the wedding?"
# seventy-six days early - a check-in that is confidently wrong rather than
# absent. Six weeks is where a plan stops being reliable enough to follow
# up on unasked, and it also bounds how long one waiting check-in can hold
# a place against the caller's cap of three.
MIN_DAYS = 0
MAX_DAYS = 45
# The civil window a check-in may land in. Quiet hours are the runner's
# business, but nothing here should ever propose 3am in the first place.
# This one clamps: an hour outside the window is a matter of taste, not a
# claim about the world, so pulling it to the edge loses nothing.
FIRST_HOUR = 9
LAST_HOUR = 21

# What the model may write as the question. Long enough for a sentence with
# a subject in it, short enough that it still reads as one line in the list
# of what the person has scheduled.
MAX_QUESTION = 160
MAX_SUBJECT = 80

_MAX_TOKENS = 260

# The order of these fields is load-bearing, not cosmetic, and this shape
# was arrived at by measurement rather than taste.
#
# The engine fills fields in the order they are declared. With `check_in`
# declared first it is decided before anything that would justify it
# exists: measured 2026-08-30, "I've got a dentist appointment tomorrow
# morning" came back `check_in: false` beside a perfectly good subject,
# question, day and hour - the model had worked out exactly what to ask and
# then said no, 0/3.
#
# Moving the decision to the end fixed that case and broke a worse one. The
# schema then made every judgement pass through a kind, a subject, a
# question, a day and an hour before it could say "nothing here", and for
# the nine messages in ten that are nothing, all of that is invented under
# constraint - after which the decision agrees with whatever it invented.
# Every `following_up` case went false and every `wellbeing` case went true,
# which is a coupling to the fields, not a judgement about the message.
#
# So the first thing written is a sentence of reading, and the decision
# comes straight after it, before anything has to be made up. `nothing` is
# a cheap and honest thing to write, and the fields below it are then
# describing a decision already taken rather than standing in for one.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # One line naming what in this message could be come back to later,
        # or the single word "nothing". Written before anything is decided,
        # so the decision has something to be about.
        "reading": {"type": "string", "maxLength": 200},
        # Whether this message changes something already waiting - called
        # off, already happened, moved. Emitted here, beside the reading and
        # before the decision, because it is part of reading the message
        # rather than a consequence of the decision. Measured 2026-08-30
        # with it last: cancellations that scored 3/3 fell to 0/3 once the
        # reading step existed, because the reading said "nothing", the
        # decision agreed, and by the time this field was reached the model
        # had already settled that the message was about nothing.
        "calls_off": {"type": "string", "maxLength": MAX_SUBJECT},
        # Whether to come back to it.
        "check_in": {"type": "boolean"},
        "kind": {"type": "string", "enum": list(KINDS)},
        # What this is about, in the person's own terms: "the visit to
        # National Harbor", "the flat application". Short, and used to
        # recognise the same thing mentioned again.
        "subject": {"type": "string", "maxLength": MAX_SUBJECT},
        # The question to ask when it fires, as an instruction: "Ask how
        # the visit to National Harbor went." Written rather than chosen
        # from a template so a situation nobody anticipated still gets a
        # sentence that fits it.
        "question": {"type": "string", "maxLength": MAX_QUESTION},
        # Whole days from today until the thing itself happens, or -1 when
        # there is no single day it happens on - a result being waited for,
        # an illness. Asked separately from when to ask because the two are
        # different judgements and only one of them is arithmetic the model
        # is good at: measured 2026-08-30, from a Thursday it read "Saturday
        # evening" and answered after_days 2, which is Saturday morning -
        # asking how an evening went before the evening. Saying that
        # Saturday is two days away is easy; remembering to add one to it,
        # every time, is not. So it says when the thing is and the caller
        # does the adding.
        "happens_in_days": {"type": "integer"},
        # Whole days from today until the question should arrive. 0 means
        # later today. Used as written when the thing has no single day,
        # and as a floor otherwise.
        "after_days": {"type": "integer"},
        # The local hour to ask at, 0-23; clamped by the caller either way.
        "hour": {"type": "integer"},
    },
    "required": [
        "reading", "calls_off", "check_in", "kind", "subject", "question",
        "happens_in_days", "after_days", "hour",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class CheckIn:
    """One thing to come back to, what to ask about it, and when."""

    kind: str
    subject: str
    question: str
    after_days: int
    hour: int


@dataclass(frozen=True, slots=True)
class Judgement:
    """What this message means for check-ins: arm one, drop one, or neither.

    Both at once is a plan that moved: the old date is dropped and the new
    one armed in its place. Returned as one object rather than two calls
    because it is one decision - the model that recognises the trip is the
    only thing that can say the new message is about the same trip.
    """

    arm: CheckIn | None = None
    calls_off: str = ""

    def __bool__(self) -> bool:
        return bool(self.arm or self.calls_off)


# Clamp a value into a range. Written out rather than min(max(...)) so the
# intent - the model's number is a suggestion, the range is the rule - is
# the thing you read.
def _within(value: int, low: int, high: int) -> int:
    if value < low:
        return low
    return high if value > high else value


# One line per thing already waiting, so the call can recognise that this
# message is about one of them. Given to the model rather than compared in
# code because the same outing gets worded differently every time it comes
# up, and a comparison that has to be right about that is a comparison that
# will be wrong about the wording nobody predicted.
def _already_waiting(subjects: tuple[str, ...]) -> str:
    lines = [str(subject).strip()[:MAX_SUBJECT] for subject in subjects if str(subject).strip()]
    if not lines:
        return ""
    listed = "\n".join(f"- {line}" for line in lines)
    return (
        "\n\nAlready waiting to be asked about, so answer false if this "
        f"message is about one of them:\n{listed}"
    )


# What, if anything, is worth coming back to after this message. None for
# almost every turn, and None for every failure: a check-in is a courtesy,
# and no turn should ever be worse for one not being armed.
async def propose_check_in(
    llm: Any,
    said: str,
    reply: str = "",
    now: datetime | None = None,
    timezone: str = "",
    already_waiting: tuple[str, ...] = (),
) -> Judgement:
    said = str(said or "").strip()
    if not said:
        return Judgement()
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
                        f"{_already_waiting(already_waiting)}"
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
        return Judgement()

    # Only a subject actually on the list may be called off. The model is
    # asked to copy one back, and a value that is not one of them is a
    # paraphrase or an invention; either way the caller must not act on it,
    # since the alternative is a message silently deleting the wrong
    # check-in.
    named = " ".join(str(decision.get("calls_off") or "").split())[:MAX_SUBJECT]
    calls_off = next(
        (one for one in already_waiting if one.strip().casefold() == named.casefold()),
        "",
    ) if named else ""

    if not decision.get("check_in"):
        return Judgement(calls_off=calls_off)
    kind = str(decision.get("kind") or "")
    subject = " ".join(str(decision.get("subject") or "").split())[:MAX_SUBJECT]
    question = " ".join(str(decision.get("question") or "").split())[:MAX_QUESTION]
    # A check-in with nothing to ask about, or nothing to ask, is not a
    # check-in. These are the fields a schema can constrain the shape of
    # but not the usefulness of.
    if kind not in KINDS or not subject or not question:
        return Judgement(calls_off=calls_off)
    try:
        after_days = int(decision.get("after_days"))
        happens_in_days = int(decision.get("happens_in_days"))
        hour = int(decision.get("hour"))
    except (TypeError, ValueError):
        return Judgement(calls_off=calls_off)
    # The invariant the model kept breaking, enforced here instead: a
    # check-in never lands before the thing it asks about. A day is added
    # rather than assumed, and only when the thing has a day at all; a
    # negative value means it has none, and then when to ask is the whole
    # judgement and is used as given.
    if happens_in_days >= 0:
        after_days = max(after_days, happens_in_days + 1)
    # Refused rather than clamped: see MAX_DAYS. A negative one is the
    # model's arithmetic going wrong rather than a plan in the past, and
    # asking today about something it thinks already happened is the same
    # confident wrongness in the other direction.
    if not MIN_DAYS <= after_days <= MAX_DAYS:
        # Still drops the old one if this message called it off: "the trip
        # moved to next spring" is a cancellation whether or not the new
        # date is close enough to arm.
        logger.info("check_in_out_of_range: %s days", after_days)
        return Judgement(calls_off=calls_off)
    return Judgement(
        arm=CheckIn(
            kind=kind,
            subject=subject,
            question=question,
            after_days=after_days,
            hour=_within(hour, FIRST_HOUR, LAST_HOUR),
        ),
        calls_off=calls_off,
    )
