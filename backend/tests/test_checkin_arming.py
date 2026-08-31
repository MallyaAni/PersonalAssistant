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

from backend.core.checkin import FOLLOWING_UP, WELLBEING, CheckIn
from backend.services.checkin_arming import (
    CHECKIN_PREFIX,
    MAX_WAITING,
    arm_check_in,
    instruction_for,
    is_same_subject,
    kind_for,
    stand_down,
    waiting_subjects,
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

    async def create(self, user_id, instruction, cadence, channel, kind="reminder", subject=None):
        made = {
            "id": f"task-{len(self.created)}",
            "user_id": user_id,
            "instruction": instruction,
            "kind": kind,
            "subject": subject,
            "cadence": cadence.cadence,
            "hour": cadence.hour,
            "on_date": cadence.on_date.isoformat(),
            "timezone": cadence.timezone,
            "channel": channel,
            "enabled": True,
        }
        self.created.append(made)
        return made


def _armed(subject: str, on_date: str, kind: str = FOLLOWING_UP, enabled: bool = True) -> dict:
    check_in = CheckIn(kind, subject, f"Ask how {subject} went.", 1, 10)
    return {
        "id": subject,
        "kind": kind_for(check_in),
        "instruction": instruction_for(check_in),
        "subject": subject,
        "on_date": on_date,
        "enabled": enabled,
    }


@pytest.mark.asyncio
async def test_a_check_in_becomes_a_one_off_task_on_the_persons_own_day():
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani",
        CheckIn(FOLLOWING_UP, "the visit to National Harbor",
                "Ask how the visit to National Harbor went.", 1, 11),
        ZONE, "imessage", now=NOW,
    )
    assert outcome.armed and outcome.reason == FOLLOWING_UP
    made = tasks.created[0]
    assert made["cadence"] == "once"
    assert made["kind"] == f"{CHECKIN_PREFIX}{FOLLOWING_UP}"
    assert made["hour"] == 11
    assert made["on_date"] == "2026-08-31"
    # The judgement's own sentence, stored verbatim, and the subject stored
    # beside it rather than left to be read back out of the sentence.
    assert made["instruction"] == "Ask how the visit to National Harbor went."
    assert made["subject"] == "the visit to National Harbor"


@pytest.mark.asyncio
async def test_the_day_is_counted_in_the_persons_calendar_not_utc():
    # 23:30 in Arlington is already tomorrow in UTC. Counting "one day from
    # now" against UTC would land the question two days out, which is how a
    # follow-up stops sounding like one.
    late = datetime(2026, 8, 31, 3, 30, tzinfo=UTC)  # 2026-08-30 23:30 in NY
    tasks = _Tasks()
    await arm_check_in(
        tasks, "ani", CheckIn(FOLLOWING_UP, "the concert", "Ask how it went.", 1, 11), ZONE, "imessage", now=late
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
        tasks, "ani", CheckIn(FOLLOWING_UP, "the lunch", "Ask how it went.", 0, 11), ZONE, "imessage", now=evening
    )
    assert tasks.created[0]["on_date"] == "2026-08-31"


@pytest.mark.asyncio
async def test_a_slot_still_to_come_today_stays_today():
    morning = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)  # 09:00 in New York
    tasks = _Tasks()
    await arm_check_in(
        tasks, "ani", CheckIn(FOLLOWING_UP, "the lunch", "Ask how it went.", 0, 19), ZONE, "imessage", now=morning
    )
    assert tasks.created[0]["on_date"] == "2026-08-30"


@pytest.mark.asyncio
async def test_a_room_is_never_told_how_someone_is_feeling():
    # Their health is theirs to tell, and the room may include people who
    # were not in the conversation where they said it.
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani",
        CheckIn(WELLBEING, "not feeling well", "Check in on how they are feeling.", 2, 18),
        ZONE, "imessage_group", in_group=True, now=NOW,
    )
    assert not outcome.armed and outcome.reason == "sensitive_in_room"
    assert tasks.created == []


@pytest.mark.asyncio
async def test_a_room_can_be_asked_how_the_trip_went():
    # A shared outing is the room's business, and asking about it is what
    # anyone else in the group would do.
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "group:abc",
        CheckIn(FOLLOWING_UP, "the visit to National Harbor",
                "Ask how the visit to National Harbor went.", 1, 11),
        ZONE, "imessage_group", in_group=True, now=NOW,
    )
    assert outcome.armed, outcome
    assert tasks.created[0]["channel"] == "imessage_group"
    assert tasks.created[0]["kind"] == f"{CHECKIN_PREFIX}{FOLLOWING_UP}"


@pytest.mark.asyncio
async def test_the_same_thing_one_to_one_is_unaffected():
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani",
        CheckIn(WELLBEING, "not feeling well", "Check in on how they are feeling.", 2, 18),
        ZONE, "imessage", in_group=False, now=NOW,
    )
    assert outcome.armed, outcome


@pytest.mark.asyncio
async def test_nothing_is_armed_without_a_timezone():
    # Guessing one is how a check-in arrives at 4am.
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(FOLLOWING_UP, "the trip", "Ask how it went.", 1, 11), "", "imessage", now=NOW
    )
    assert not outcome.armed and outcome.reason == "no_timezone"


@pytest.mark.asyncio
async def test_only_three_may_be_waiting_at_once():
    waiting = [_armed(f"thing {index}", "2026-09-05") for index in range(MAX_WAITING)]
    tasks = _Tasks(waiting)
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(FOLLOWING_UP, "one more thing", "Ask how it went.", 1, 11), ZONE, "imessage", now=NOW
    )
    assert not outcome.armed and outcome.reason == "too_many_waiting"


@pytest.mark.asyncio
async def test_a_fired_check_in_no_longer_counts_against_the_cap():
    # Otherwise a person who has ever had three is never asked anything again.
    spent = [_armed(f"thing {index}", "2026-08-01", enabled=False) for index in range(MAX_WAITING)]
    tasks = _Tasks(spent)
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(FOLLOWING_UP, "something new entirely", "Ask how it went.", 1, 11), ZONE, "imessage", now=NOW
    )
    assert outcome.armed


@pytest.mark.asyncio
async def test_the_same_outing_is_not_armed_twice():
    tasks = _Tasks([_armed("the visit to National Harbor", "2026-08-31")])
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(FOLLOWING_UP, "our National Harbor visit", "Ask how it went.", 1, 11),
        ZONE, "imessage", now=NOW,
    )
    assert not outcome.armed and outcome.reason == "already_armed"


@pytest.mark.asyncio
async def test_a_second_wellbeing_check_in_waits_a_week():
    tasks = _Tasks([_armed("not feeling well", "2026-08-31", kind=WELLBEING)])
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(WELLBEING, "a rough couple of days", "Ask how it went.", 2, 18),
        ZONE, "imessage", now=NOW,
    )
    assert not outcome.armed and outcome.reason == "wellbeing_cooldown"


@pytest.mark.asyncio
async def test_an_outing_is_still_armed_while_a_wellbeing_one_is_cooling_down():
    # The cooldown is about being asked the same question twice, not about
    # going quiet altogether.
    tasks = _Tasks([_armed("not feeling well", "2026-08-31", kind=WELLBEING)])
    outcome = await arm_check_in(
        tasks, "ani", CheckIn(FOLLOWING_UP, "the dentist appointment", "Ask how it went.", 1, 11),
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
        tasks, "ani", CheckIn(FOLLOWING_UP, "the interview", "Ask how it went.", 1, 11), ZONE, "imessage", now=NOW
    )
    assert outcome.armed


@pytest.mark.asyncio
async def test_a_repository_that_fails_does_not_take_down_the_turn():
    class _Broken(_Tasks):
        async def list_for_user(self, user_id: str, enabled_only: bool = True):
            raise RuntimeError("no database today")

    outcome = await arm_check_in(
        _Broken(), "ani", CheckIn(FOLLOWING_UP, "the trip", "Ask how it went.", 1, 11), ZONE, "imessage", now=NOW
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


def test_the_instruction_is_the_question_the_judgement_wrote():
    # Not a template with the subject slotted in: "Ask whether they heard
    # back about the flat." is not "Ask how X went." with a different X, and
    # a fixed sentence per kind caps what can ever be followed up at the
    # situations someone thought of first.
    written = instruction_for(
        CheckIn(FOLLOWING_UP, "the flat application", "Ask whether they heard back about the flat.", 5, 11)
    )
    assert written == "Ask whether they heard back about the flat."


def test_a_judgement_with_no_question_still_produces_a_usable_sentence():
    # The caller rejects a questionless judgement before this is reached, so
    # this is about the function being total rather than about a case that
    # happens.
    assert instruction_for(CheckIn(FOLLOWING_UP, "the trip", "", 1, 11)) == "Ask how the trip went."
    assert instruction_for(CheckIn(WELLBEING, "the migraine", "", 2, 18)) == (
        "Check in on how they are doing after the migraine."
    )


def test_the_instruction_carries_no_directions_addressed_to_a_model():
    # It is what the person sees when they list what is scheduled.
    for text in (
        instruction_for(CheckIn(FOLLOWING_UP, "the trip", "Ask how the trip went.", 1, 11)),
        instruction_for(CheckIn(WELLBEING, "the migraine", "Ask how they are feeling.", 2, 18)),
    ):
        for directive in ("do not search", "one short", "warm line"):
            assert directive not in text.casefold(), text


# The runner's half of the same decision: the manner lives with the kind.
def test_only_a_check_in_firing_is_told_how_to_say_it():
    from backend.workers.task_runner import _asked

    reminder = {"instruction": "Text me the Spark temps.", "kind": "reminder"}
    assert _asked(reminder) == "Text me the Spark temps."

    check_in = {
        "instruction": "Ask how the visit to National Harbor went.",
        "kind": "checkin:following_up",
    }
    asked = _asked(check_in)
    assert asked.startswith("Ask how the visit to National Harbor went.")
    assert "one short, warm line" in asked
    assert "do not mention that this was scheduled" in asked

    # A row written before the column existed reads as a reminder, not as a
    # check-in with no manner attached.
    assert _asked({"instruction": "Do the thing.", "kind": None}) == "Do the thing."


# The scenarios nobody had seen when this was written, which is the point.
@pytest.mark.asyncio
async def test_a_situation_that_is_neither_an_outing_nor_an_illness_still_arms():
    # "waiting to hear back about the flat" is the same shape as an outing -
    # a thing with an outcome at a knowable time - and fitted neither of the
    # two templates this feature was first written around.
    tasks = _Tasks()
    outcome = await arm_check_in(
        tasks, "ani",
        CheckIn(FOLLOWING_UP, "the flat application",
                "Ask whether they heard back about the flat.", 5, 11),
        ZONE, "imessage", now=NOW,
    )
    assert outcome.armed
    made = tasks.created[0]
    assert made["instruction"] == "Ask whether they heard back about the flat."
    assert made["subject"] == "the flat application"
    assert made["kind"] == f"{CHECKIN_PREFIX}{FOLLOWING_UP}"


@pytest.mark.asyncio
async def test_a_cancelled_check_in_is_not_quietly_armed_again():
    # Someone who cancelled "how was National Harbor?" has said what they
    # want. Mentioning the outing again must not bring it back, so the
    # duplicate check reads disabled rows too.
    tasks = _Tasks([_armed("the visit to National Harbor", "2026-08-31", enabled=False)])
    outcome = await arm_check_in(
        tasks, "ani",
        CheckIn(FOLLOWING_UP, "the National Harbor visit", "Ask how it went.", 1, 11),
        ZONE, "imessage", now=NOW,
    )
    assert not outcome.armed and outcome.reason == "already_armed"


@pytest.mark.asyncio
async def test_what_is_waiting_is_offered_to_the_judgement_by_subject():
    # The judgement is what has to recognise "that Harbor thing" as the
    # outing already waiting. It can only do that if it is told, and it is
    # told the subjects rather than the instructions.
    tasks = _Tasks([
        _armed("the visit to National Harbor", "2026-08-31"),
        _armed("the flat application", "2026-09-03"),
        {"id": "r", "kind": "reminder", "instruction": "Call the bank.", "enabled": True},
    ])
    waiting = await waiting_subjects(tasks, "ani")
    assert waiting == ("the visit to National Harbor", "the flat application")


@pytest.mark.asyncio
async def test_an_unreadable_task_list_offers_nothing_rather_than_failing():
    class _Broken(_Tasks):
        async def list_for_user(self, user_id: str, enabled_only: bool = True):
            raise RuntimeError("no database today")

    assert await waiting_subjects(_Broken(), "ani") == ()


# Standing one down: the code half, which is about not taking down the wrong
# thing rather than about recognising which thing.
def _recording(tasks: _Tasks) -> list[str]:
    """Record what stand_down removes, and fail loudly if it removes wrongly."""
    removed: list[str] = []

    async def delete_owned(user_id: str, task_id: str) -> bool:
        removed.append(task_id)
        return True

    tasks.delete_owned = delete_owned
    return removed


@pytest.mark.asyncio
async def test_standing_down_removes_the_matching_check_in():
    tasks = _Tasks([
        _armed("the visit to National Harbor", "2026-08-31"),
        _armed("the flat application", "2026-09-03"),
    ])
    removed = _recording(tasks)
    assert await stand_down(tasks, "ani", "the visit to National Harbor")
    assert removed == ["the visit to National Harbor"]


@pytest.mark.asyncio
async def test_a_plan_that_fell_through_can_be_armed_again_if_it_comes_back():
    # The reason stand_down removes the row instead of disabling it. A
    # person who cancels the *question* is saying stop asking, and a
    # disabled row keeps that promise. A plan falling through says nothing
    # of the sort, and a trip that is back on deserves its check-in back.
    tasks = _Tasks([_armed("the visit to National Harbor", "2026-08-31")])
    _recording(tasks)
    await stand_down(tasks, "ani", "the visit to National Harbor")
    tasks.existing = []  # what removing the row leaves behind
    outcome = await arm_check_in(
        tasks, "ani",
        CheckIn(FOLLOWING_UP, "the visit to National Harbor", "Ask how it went.", 3, 11),
        ZONE, "imessage", now=NOW,
    )
    assert outcome.armed


@pytest.mark.asyncio
async def test_standing_down_something_not_waiting_touches_nothing():
    tasks = _Tasks([_armed("the flat application", "2026-09-03")])
    removed = _recording(tasks)
    assert not await stand_down(tasks, "ani", "the Chicago trip")
    assert not await stand_down(tasks, "ani", "")
    assert removed == []


@pytest.mark.asyncio
async def test_standing_down_never_touches_a_reminder():
    # Reminders and check-ins share a table. A message about a trip must not
    # be able to remove "remind me to take my medication".
    tasks = _Tasks([
        {"id": "r", "kind": "reminder", "instruction": "Take the medication.",
         "subject": "the medication", "enabled": True}
    ])
    removed = _recording(tasks)
    assert not await stand_down(tasks, "ani", "the medication")
    assert removed == []


# The arithmetic the caller took over from the model.
def test_a_check_in_never_lands_before_the_thing_it_asks_about():
    from backend.core.checkin import _SCHEMA

    # Declared, and declared before `after_days`, because the order is what
    # makes the model answer it as a fact about the thing rather than as a
    # restatement of when to ask.
    fields = list(_SCHEMA["properties"])
    assert "happens_in_days" in fields
    assert fields.index("happens_in_days") < fields.index("after_days")
    # And the decision is read before anything has to be invented for it.
    assert fields.index("reading") < fields.index("check_in")
    assert fields.index("calls_off") < fields.index("check_in")
    assert fields.index("check_in") < fields.index("subject")
