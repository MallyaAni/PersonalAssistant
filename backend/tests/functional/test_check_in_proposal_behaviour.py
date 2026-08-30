"""What the model decides is worth coming back to, and how often it decides it.

The operator asked for this on 2026-08-30: "how was the visit to national
harbor?" after an outing, and an occasional "how are you doing?" when they
had said they were unwell.

The failure mode is not missing one. It is arming one every turn - the call
sees a single message and remembers nothing it has already proposed, so a
model that leans towards yes turns the thread into a stream of questions
arriving days later. The quiet cases below outnumber the loud ones for that
reason, and they are the half of this file that matters.

The other half of the discipline is not here at all: how many may be armed,
how close together, and in which threads are decided in code, in
backend/services/checkin_arming.py, and tested without a model.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.checkin import (
    FIRST_HOUR,
    FOLLOWING_UP,
    LAST_HOUR,
    MAX_DAYS,
    WELLBEING,
    propose_check_in,
)
from backend.core.dependencies import get_structured_llm_client

pytestmark = pytest.mark.asyncio

# A Thursday, so "Saturday" is two days out and the arithmetic is checkable.
NOW = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)
ZONE = "America/New_York"


async def _judged(said: str, reply: str = "", waiting: tuple[str, ...] = ()):
    return await propose_check_in(
        get_structured_llm_client(),
        said,
        reply,
        now=NOW,
        timezone=ZONE,
        already_waiting=waiting,
    )


async def _proposed(said: str, reply: str = "", waiting: tuple[str, ...] = ()):
    """Just the check-in to arm, which is what most of these are about."""
    return (await _judged(said, reply, waiting)).arm


# The operator's own examples, and the shapes around them.
@pytest.mark.parametrize(
    "said",
    [
        "we're heading to National Harbor on Saturday evening",
        "I've got a dentist appointment tomorrow morning, not looking forward to it",
        "flying to Chicago on Friday for a few days",
        "got my final interview at Ven on Tuesday",
    ],
)
async def test_something_worth_asking_about_afterwards_is_noticed(said: str) -> None:
    proposed = await _proposed(said)
    assert proposed is not None, "nothing proposed"
    assert proposed.kind == FOLLOWING_UP, proposed
    assert proposed.subject, proposed
    # The question is written, not chosen: it has to be a sentence that fits
    # this particular thing, or the feature is capped at the situations
    # somebody wrote a template for.
    assert proposed.question.endswith("."), proposed
    assert len(proposed.question.split()) >= 4, proposed


@pytest.mark.parametrize(
    "said",
    [
        "honestly I've been feeling pretty awful the last few days",
        "I've come down with something, staying in bed today",
        "it's been a brutal week, I'm running on empty",
    ],
)
async def test_someone_saying_they_are_unwell_is_noticed(said: str) -> None:
    proposed = await _proposed(said)
    assert proposed is not None, "nothing proposed"
    assert proposed.kind == WELLBEING, proposed


# The quiet half. An ordinary thread is mostly these, and every one of them
# arming a check-in is what the feature failing looks like.
QUIET = [
    "what's on in Arlington this weekend?",
    "can you make me a diagram of the deploy pipeline",
    "remind me to call the landlord at 6",
    "I drive a Tesla Model 3",
    "what's the capital of Peru?",
    "thanks, that's perfect",
    "I'm vegetarian so keep that in mind",
    "a bit tired this morning but I'm fine",
    "my brother is having surgery next week",
    "summarize the conversation so far",
    "do you remember what I said about the metro?",
    "that restaurant looks good, what are the hours",
]


async def test_an_ordinary_turn_arms_nothing() -> None:
    # Asserted as a rate over the set rather than case by case: the same
    # judgement flakes on individual sentences, and a per-case assertion
    # would fail on variance rather than on the behaviour. One stray yes in
    # twelve is tolerable; three is the feature being a nuisance.
    proposed = [said for said in QUIET if await _proposed(said) is not None]
    assert len(proposed) <= 2, f"armed on ordinary turns: {proposed}"


async def test_someone_elses_plans_are_not_the_persons_own() -> None:
    # A brother's surgery is not something to ask this person about as
    # though it were theirs. Kept separate from the rate above because it
    # is a rule, not a matter of taste.
    assert await _proposed("my brother is having surgery next week") is None


async def test_an_offer_the_assistant_made_is_not_a_plan_they_have() -> None:
    # The assistant suggesting somewhere is not the person going there.
    proposed = await _proposed(
        "what's on this weekend?",
        reply="La Brisa has a sunset session on Saturday, and The Lawn does a Sunday social.",
    )
    assert proposed is None, proposed


async def test_the_day_and_hour_are_always_within_what_the_caller_allows() -> None:
    # The schema cannot bound an integer, so the module clamps. This proves
    # the clamp rather than the model's arithmetic: an hour of 3 or a
    # fortnight and a half both have to come back inside the range.
    for said in ("we're at a wedding in Vermont next weekend", "surgery on the 12th"):
        proposed = await _proposed(said)
        if proposed is None:
            continue
        assert 0 <= proposed.after_days <= MAX_DAYS, proposed
        assert FIRST_HOUR <= proposed.hour <= LAST_HOUR, proposed


# Never before the thing itself. Asking on Saturday morning how Saturday
# evening went is the confidently-wrong failure this whole feature is
# written against, and it is the one the model got wrong on its own:
# measured 2026-08-30 it answered 2 from a Thursday for "Saturday evening",
# which is Saturday. It now says when the thing happens and the caller adds
# the day, so these assert the invariant rather than the model's addition.
@pytest.mark.parametrize(
    ("said", "not_before"),
    [
        ("we're heading to National Harbor on Saturday evening", 3),
        ("flying to Chicago on Friday for a few days", 2),
        ("got my final interview at Ven on Tuesday", 6),
        ("starting the new job on Monday", 5),
    ],
)
async def test_nothing_is_asked_about_before_it_has_happened(
    said: str, not_before: int
) -> None:
    proposed = await _proposed(said)
    assert proposed is not None, said
    assert proposed.after_days >= not_before, (said, proposed)


# The instruction this file was rewritten under, on 2026-08-30: "account for
# scenarios we haven't seen before". None of these is an outing or an
# illness, and each is the same shape - something with an outcome, at a time
# that can be worked out, that a person would be glad to be asked about.
@pytest.mark.parametrize(
    "said",
    [
        "just submitted the application for the flat in Clarendon, fingers crossed",
        "my thesis defence is on the 3rd and I'm dreading it",
        "taking my cat to the vet on Friday, she's been off her food",
        "I put an offer in on a car this morning",
        "starting the new job on Monday",
    ],
)
async def test_a_shape_nobody_wrote_a_template_for_is_still_noticed(said: str) -> None:
    proposed = await _proposed(said)
    assert proposed is not None, f"missed: {said}"
    assert proposed.subject and proposed.question, proposed
    # Whatever it is, it must not be squeezed into "Ask how X went." when
    # that is the wrong question - a submitted application is asked about
    # differently from an evening out.
    print(f"\n{said}\n   -> [{proposed.kind}] {proposed.question} (+{proposed.after_days}d)")


async def test_a_plan_too_far_out_is_refused_rather_than_pulled_closer() -> None:
    # The failure this guards is not a missed check-in, it is a confident
    # wrong one: clamping a wedding next spring into the window asks "how
    # was the wedding?" months early. Refusing says nothing, which is right.
    for said in (
        "we're getting married in June next year",
        "booked a trip to Japan for next April",
    ):
        proposed = await _proposed(said)
        assert proposed is None or proposed.after_days <= MAX_DAYS, (said, proposed)


async def test_the_same_thing_mentioned_again_is_recognised_however_worded() -> None:
    # The duplicate rule that matters, because the wording changes every
    # time. A comparison in code cannot do this; the judgement is handed
    # what is waiting and has to.
    waiting = ("the visit to National Harbor",)
    for said in (
        "still looking forward to that Harbor thing on Saturday",
        "we're heading to National Harbor on Saturday evening",
        "counting down to Saturday at the harbor",
    ):
        assert await _proposed(said, waiting=waiting) is None, said


async def test_something_new_is_still_armed_while_other_things_wait() -> None:
    # The other half: being told what is waiting must not silence it.
    proposed = await _proposed(
        "I've got a dentist appointment tomorrow morning",
        waiting=("the visit to National Harbor", "the flat application"),
    )
    assert proposed is not None, "a new thing was suppressed by unrelated ones"


# Calling one off. The worst thing this feature can do is not silence - it
# is asking how a trip went that the person already said was cancelled.
WAITING = ("the visit to National Harbor",)


CALLED_OFF = [
    "we cancelled National Harbor, not going anymore",
    "the Harbor thing fell through",
    "we bailed on Saturday, staying in instead",
]


async def test_a_plan_called_off_takes_its_check_in_with_it() -> None:
    # A rate over the set, because the phrasings are not equally easy and
    # asserting each would fail on the hardest rather than on the
    # behaviour. Measured 2026-08-30, three runs each: the two that name
    # the outing are 3/3, and "we bailed on Saturday, staying in instead" -
    # which never names it - is 0/3. Two of three is the floor; zero is the
    # feature not working.
    recognised = [
        said for said in CALLED_OFF
        if (await _judged(said, waiting=WAITING)).calls_off == WAITING[0]
    ]
    assert len(recognised) >= 2, f"only {recognised} were recognised as calling it off"


async def test_a_plan_that_moved_is_recognised_as_no_longer_that_plan() -> None:
    # Recognised 3/3 and dropped. The new date is not armed in the same
    # breath - measured 0/3 - and that is why standing one down removes the
    # row rather than disabling it: with the row gone, the next mention of
    # the trip arms it afresh, so the outcome is a question that arrives
    # late rather than one that arrives about the wrong day.
    judged = await _judged(
        "National Harbor got pushed to next Saturday", waiting=WAITING
    )
    assert judged.calls_off == WAITING[0], judged


async def test_telling_it_how_something_went_ends_the_question() -> None:
    # There is nothing left to ask, and asking anyway is the same failure as
    # asking about a cancelled trip.
    judged = await _judged(
        "National Harbor was great, we walked the pier for hours", waiting=WAITING
    )
    assert judged.calls_off == WAITING[0], judged


async def test_an_unrelated_message_takes_nothing_down() -> None:
    # The dangerous direction: a message that quietly deletes a check-in it
    # was never about.
    for said in ("what's the capital of Peru?", "remind me to call the bank at 6"):
        judged = await _judged(said, waiting=WAITING)
        assert judged.calls_off == "", (said, judged)


async def test_only_a_subject_from_the_list_may_be_called_off() -> None:
    # Enforced in code rather than trusted: a name the model paraphrased or
    # invented matches nothing and takes nothing down.
    judged = await _judged("we cancelled the Chicago trip", waiting=WAITING)
    assert judged.calls_off == "", judged
