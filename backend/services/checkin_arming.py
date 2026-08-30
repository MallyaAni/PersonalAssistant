"""Whether a proposed check-in is allowed to become a scheduled task.

The judgement in `backend/core/checkin.py` reads one message and has no
memory of what it has already proposed. That is fine as long as nothing
downstream trusts it to be sparing, so everything that keeps a check-in
from becoming a nuisance lives here, in code, where it can be read and
tested without a model:

  * at most three waiting at once, so a chatty afternoon cannot fill the
    thread with questions arriving days later;
  * one wellbeing check-in a week, because the second "how are you
    feeling?" in three days reads as nagging rather than care;
  * nothing armed twice for the same subject, however the second message
    happened to word it;
  * one-to-one threads only. A room is not the place to ask one member
    how their health is, and the group's own thread already tells
    everyone what everyone said.

An armed check-in is an ordinary one-off scheduled task, so the person
lists it, cancels it and undoes it with the words they already use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.core.checkin import WELLBEING, CheckIn
from backend.discovery.schedule import Cadence

logger = logging.getLogger(__name__)

# The task kind stored on the row, so a check-in can be counted and capped
# by a query rather than by reading the prose of an instruction. The kind
# carries which sort it is too - "checkin:event", "checkin:wellbeing" - so
# the wellbeing cooldown is a comparison rather than a prefix match on an
# instruction that gets reworded the moment anyone improves it.
CHECKIN_PREFIX = "checkin:"


def kind_for(check_in: CheckIn) -> str:
    """The kind column's value for a check-in of this sort."""
    return f"{CHECKIN_PREFIX}{check_in.kind}"


def is_check_in(task: dict[str, Any]) -> bool:
    """Whether a task row is a check-in rather than a reminder."""
    return str(task.get("kind") or "").startswith(CHECKIN_PREFIX)

# How many may be waiting to fire at once.
MAX_WAITING = 3
# How long after one wellbeing check-in before another may be armed.
WELLBEING_COOLDOWN_DAYS = 7


@dataclass(frozen=True, slots=True)
class Armed:
    """What happened, for the trace. `task` is set only when one was created."""

    armed: bool
    reason: str
    task: dict[str, Any] | None = None


# A subject reduced to what makes it the same subject: lowercase words, no
# punctuation, no articles. "The visit to National Harbor" and "our National
# Harbor visit" collapse together, which is the point - a person who mentions
# an outing twice should be asked about it once.
_NOISE = frozenset({"the", "a", "an", "to", "our", "my", "at", "in", "on", "for", "of", "with"})


def _shape(subject: str) -> frozenset[str]:
    letters = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in subject.casefold()
    )
    return frozenset(word for word in letters.split() if word not in _NOISE)


# Whether two subjects name the same thing. Not a string comparison: the
# model words the same outing differently on different days, and an armed
# check-in the person never sees is exactly the thing that would slip
# through an equality test.
def is_same_subject(one: str, other: str) -> bool:
    first, second = _shape(one), _shape(other)
    if not first or not second:
        return False
    if first == second:
        return True
    shared = first & second
    # Every word of the shorter subject appearing in the longer one means the
    # shorter is the same thing said tersely: "national harbor" against "the
    # visit to national harbor".
    return len(shared) == min(len(first), len(second))


# The day a check-in should land on, in the person's own calendar.
#
# Local rather than UTC: at 23:00 in Arlington it is already tomorrow in
# UTC, and "the day after" would silently become two.
#
# And never in the past. A `once` slot that has already gone is returned by
# `next_run_at` as it stands - deliberately, since a person who asks for a
# past time meant it - so an armed check-in for 11am when it is already 6pm
# would fire the moment the runner next looked. Nobody asked for this one,
# so the same day next reasonable slot is tomorrow.
def _landing_day(after_days: int, hour: int, zone: str, now: datetime | None = None) -> date:
    moment = now or datetime.now(UTC)
    try:
        local = moment.astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        local = moment
    landing = local.date() + timedelta(days=max(0, after_days))
    if landing <= local.date() and hour <= local.hour:
        return landing + timedelta(days=1)
    return landing


# What the task says. This is shown to the person when they list what is
# scheduled, so it is one plain sentence and nothing else. How a check-in
# should be written - short, warm, no searching - is the runner's business
# and travels with the task's kind, because a person reading their own
# reminders should not have to read instructions addressed to a model.
def instruction_for(check_in: CheckIn) -> str:
    if check_in.kind == WELLBEING:
        return f"Check in on how they are doing after {check_in.subject}."
    return f"Ask how {check_in.subject} went."


# Arm a check-in, or say why not. Never raises into the turn: a check-in is
# a courtesy and no reply should ever be worse for one not being armed.
async def arm_check_in(
    tasks: Any,
    user_id: str,
    check_in: CheckIn,
    timezone: str,
    channel: str,
    in_group: bool = False,
    now: datetime | None = None,
) -> Armed:
    if in_group:
        return Armed(False, "group")
    if not timezone:
        # Without a timezone there is no hour to land on, and guessing one
        # is how a check-in arrives at 4am.
        return Armed(False, "no_timezone")
    try:
        existing = await tasks.list_for_user(user_id, enabled_only=False)
    except Exception:
        logger.warning("check_in_arming_could_not_read_tasks", exc_info=True)
        return Armed(False, "unreadable")

    check_ins = [task for task in existing if is_check_in(task)]
    waiting = [task for task in check_ins if task.get("enabled")]
    if len(waiting) >= MAX_WAITING:
        return Armed(False, "too_many_waiting")
    if any(is_same_subject(check_in.subject, _subject_of(task)) for task in check_ins):
        return Armed(False, "already_armed")

    landing = _landing_day(check_in.after_days, check_in.hour, timezone, now)
    if check_in.kind == WELLBEING and _asked_recently(check_ins, landing):
        return Armed(False, "wellbeing_cooldown")

    try:
        cadence = Cadence(
            cadence="once",
            hour=check_in.hour,
            minute=0,
            weekday=landing.weekday(),
            timezone=timezone,
            on_date=landing,
        )
        task = await tasks.create(
            user_id,
            instruction_for(check_in),
            cadence,
            channel,
            kind=kind_for(check_in),
        )
    except Exception:
        logger.warning("check_in_arming_failed", exc_info=True)
        return Armed(False, "failed")
    return Armed(True, check_in.kind, task)


# The subject of an already-armed check-in, recovered from its instruction.
# The instruction is what is stored; the subject is not a column because it
# only ever matters here, and a column that exists for one comparison is a
# column that goes stale.
def _subject_of(task: dict[str, Any]) -> str:
    instruction = str(task.get("instruction") or "")
    for opener, closer in (("Ask how ", " went."), ("Check in on how they are doing after ", ".")):
        if instruction.startswith(opener) and closer in instruction:
            return instruction[len(opener) : instruction.index(closer, len(opener))]
    return ""


# Whether a wellbeing check-in was already asked, or is already waiting,
# close enough to this one that a second would be nagging.
def _asked_recently(check_ins: list[dict[str, Any]], landing: date) -> bool:
    for task in check_ins:
        if str(task.get("kind") or "") != f"{CHECKIN_PREFIX}{WELLBEING}":
            continue
        when = task.get("on_date")
        if not when:
            continue
        try:
            asked = date.fromisoformat(str(when))
        except ValueError:
            continue
        if abs((landing - asked).days) < WELLBEING_COOLDOWN_DAYS:
            return True
    return False
