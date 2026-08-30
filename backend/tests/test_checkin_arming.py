"""The limits that keep a check-in a courtesy rather than a nuisance.

The judgement that proposes a check-in reads one message and remembers
nothing, so it will happily propose one every turn. None of what stops
that lives in a prompt: it is all here, where it can be read without a
model and cannot drift when the wording changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.core.checkin import EVENT, WELLBEING, CheckIn
from backend.services.checkin_arming import (
    CHECKIN_PREFIX,
    MAX_WAITING,
    arm_check_in,
    instruction_for,
    is_same_subject,
    kind_for,
)

# Marked per test rather than for the module: three of these are ordinary
# functions, and a module-level asyncio mark warns on every one of them.
NOW = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
ZONE = "America/New_York"


class _Tasks:
    """A task repository that records what it was asked to create."""

    def __init__(self, existing: list[dict[str, Any]] | None = None):
        self.existing = existing or []
        self.created: list[dict[str, Any]] = []

    async def list_for_user(self, user_id: str, enabled_only: bool = True):
        return [
            task
            for task in self.existing
            if task.get("user_id", user_id) == user_id
            and (task.get("enabled") or not enabled_only)
        ]

    async def create(self, user_id, instruction, cadence, channel, kind="reminder"):
        made = {
            "id": f"task-{len(self.created)}",
            "user_id": user_id,
            "instruction": instruction,
            "kind": kind,
            "cadence": cadence.cadence,
            "hour": cadence.hour,
            "on_date": cadence.on_date.isoformat(),
            "timezone": cadence.timezone,
            "channel": channel,
            "enabled": True,
        }
        self.created.append(made)
        return made


def _armed(subject: str, on_date: str, kind: str = EVENT, enabled: bool = True) -> dict:
    check_in = CheckIn(kind, subject, 1, 10)
    return {
        "id": subject,
        "kind": kind_for(check_in),
        "instruction": instruction_for(check_in),
        "on_date": on_date,
        "enabled": enabled,
    }


@pytest.mark.asyncio
async def test_a_check_in_becomes_a_one_off_task_on_the_persons_own_day():
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "the visit to National Harbor", 1, 11),
        ZONE, "imessage", now=NOW,
    )
    assert outcome.armed and outcome.reason == EVENT
    made = tasks.created[0]
    assert made["cadence"] == "once"
    assert made["kind"] == f"{CHECKIN_PREFIX}{EVENT}"
    assert made["hour"] == 11
    assert made["on_date"] == "2026-08-31"
    assert "National Harbor" in made["instruction"]


@pytest.mark.asyncio
async def test_the_day_is_counted_in_the_persons_calendar_not_utc():
    # 23:30 in Arlington is already tomorrow in UTC. Counting "one day from
    # now" against UTC would land the question two days out, which is how a
    # follow-up stops sounding like one.
    late = datetime(2026, 8, 31, 3, 30, tzinfo=UTC)  # 2026-08-30 23:30 in NY
    tasks = _Tasks()
    await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "the concert", 1, 11), ZONE, "imessage", now=late
    )
    assert tasks.created[0]["on_date"] == "2026-08-31"


@pytest.mark.asyncio
async def test_a_slot_that_has_already_passed_today_moves_to_tomorrow():
    # `next_run_at` returns a past `once` slot as it stands - deliberately,
    # since a person who asks for a past time meant it. Nobody asked for
    # this one, so an 11am check-in proposed at 6pm would otherwise fire the
    # moment the runner next looked, seconds after the message that caused it.
    evening = datetime(2026, 8, 30, 22, 0, tzinfo=UTC)  # 18:00 in New York
    tasks = _Tasks()
    await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "the lunch", 0, 11), ZONE, "imessage", now=evening
    )
    assert tasks.created[0]["on_date"] == "2026-08-31"


@pytest.mark.asyncio
async def test_a_slot_still_to_come_today_stays_today():
    morning = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)  # 09:00 in New York
    tasks = _Tasks()
    await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "the lunch", 0, 19), ZONE, "imessage", now=morning
    )
    assert tasks.created[0]["on_date"] == "2026-08-30"


@pytest.mark.asyncio
async def test_nothing_is_armed_in_a_group():
    # A room is not the place to ask one member how their health is.
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(WELLBEING, "not feeling well", 2, 18),
        ZONE, "imessage_group", in_group=True, now=NOW,
    )
    assert not outcome.armed and outcome.reason == "group"
    assert tasks.created == []


@pytest.mark.asyncio
async def test_nothing_is_armed_without_a_timezone():
    # Guessing one is how a check-in arrives at 4am.
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "the trip", 1, 11), "", "imessage", now=NOW
    )
    assert not outcome.armed and outcome.reason == "no_timezone"


@pytest.mark.asyncio
async def test_only_three_may_be_waiting_at_once():
    waiting = [_armed(f"thing {index}", "2026-09-05") for index in range(MAX_WAITING)]
    tasks = _Tasks(waiting)
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "one more thing", 1, 11), ZONE, "imessage", now=NOW
    )
    assert not outcome.armed and outcome.reason == "too_many_waiting"


@pytest.mark.asyncio
async def test_a_fired_check_in_no_longer_counts_against_the_cap():
    # Otherwise a person who has ever had three is never asked anything again.
    spent = [_armed(f"thing {index}", "2026-08-01", enabled=False) for index in range(MAX_WAITING)]
    tasks = _Tasks(spent)
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "something new entirely", 1, 11), ZONE, "imessage", now=NOW
    )
    assert outcome.armed


@pytest.mark.asyncio
async def test_the_same_outing_is_not_armed_twice():
    tasks = _Tasks([_armed("the visit to National Harbor", "2026-08-31")])
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "our National Harbor visit", 1, 11),
        ZONE, "imessage", now=NOW,
    )
    assert not outcome.armed and outcome.reason == "already_armed"


@pytest.mark.asyncio
async def test_a_second_wellbeing_check_in_waits_a_week():
    tasks = _Tasks([_armed("not feeling well", "2026-08-31", kind=WELLBEING)])
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(WELLBEING, "a rough couple of days", 2, 18),
        ZONE, "imessage", now=NOW,
    )
    assert not outcome.armed and outcome.reason == "wellbeing_cooldown"


@pytest.mark.asyncio
async def test_an_outing_is_still_armed_while_a_wellbeing_one_is_cooling_down():
    # The cooldown is about being asked the same question twice, not about
    # going quiet altogether.
    tasks = _Tasks([_armed("not feeling well", "2026-08-31", kind=WELLBEING)])
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "the dentist appointment", 1, 11),
        ZONE, "imessage", now=NOW,
    )
    assert outcome.armed


@pytest.mark.asyncio
async def test_a_reminder_the_person_asked_for_is_not_a_check_in():
    # Reminders and check-ins share a table. Counting reminders against the
    # check-in cap would silence check-ins for anyone who uses reminders.
    reminders = [
        {"id": str(index), "kind": "reminder", "instruction": "Text me about the gym.",
         "on_date": "2026-09-01", "enabled": True}
        for index in range(5)
    ]
    tasks = _Tasks(reminders)
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(EVENT, "the interview", 1, 11), ZONE, "imessage", now=NOW
    )
    assert outcome.armed


@pytest.mark.asyncio
async def test_a_repository_that_fails_does_not_take_down_the_turn():
    class _Broken(_Tasks):
        async def list_for_user(self, user_id: str, enabled_only: bool = True):
            raise RuntimeError("no database today")

    outcome = await arm_check_in(
        _Broken(), "ani", CheckIn(EVENT, "the trip", 1, 11), ZONE, "imessage", now=NOW
    )
    assert not outcome.armed and outcome.reason == "unreadable"


# The subject comparison on its own, since it is what stops a person being
# asked twice about one evening.
@pytest.mark.parametrize(
    ("one", "other", "same"),
    [
        ("the visit to National Harbor", "our National Harbor visit", True),
        ("the visit to National Harbor", "National Harbor", True),
        ("the dentist appointment", "the dentist", True),
        ("the visit to National Harbor", "the trip to Chicago", False),
        ("the concert", "the dentist appointment", False),
        ("", "the concert", False),
        ("the concert!", "The Concert", True),
    ],
)
def test_two_subjects_naming_the_same_thing_are_recognised(one, other, same):
    assert is_same_subject(one, other) is same


def test_the_instruction_is_one_plain_sentence_a_person_would_want_to_read():
    # It is what they see when they list what is scheduled. How the check-in
    # should be worded is the runner's business, not theirs to read.
    event = instruction_for(CheckIn(EVENT, "the visit to National Harbor", 1, 11))
    assert event == "Ask how the visit to National Harbor went."
    wellbeing = instruction_for(CheckIn(WELLBEING, "not feeling well", 2, 18))
    assert wellbeing == "Check in on how they are doing after not feeling well."
    for text in (event, wellbeing):
        for directive in ("do not", "one short", "line"):
            assert directive not in text.casefold(), text


# The runner's half of the same decision: the manner lives with the kind.
def test_only_a_check_in_firing_is_told_how_to_say_it():
    from backend.workers.task_runner import _asked

    reminder = {"instruction": "Text me the Spark temps.", "kind": "reminder"}
    assert _asked(reminder) == "Text me the Spark temps."

    check_in = {
        "instruction": "Ask how the visit to National Harbor went.",
        "kind": "checkin:event",
    }
    asked = _asked(check_in)
    assert asked.startswith("Ask how the visit to National Harbor went.")
    assert "one short, warm line" in asked
    assert "do not mention that this was scheduled" in asked

    # A row written before the column existed reads as a reminder, not as a
    # check-in with no manner attached.
    assert _asked({"instruction": "Do the thing.", "kind": None}) == "Do the thing."
