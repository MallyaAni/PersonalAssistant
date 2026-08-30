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

from backend.core.checkin import EVENT, WELLBEING, FIRST_HOUR, LAST_HOUR, MAX_DAYS, propose_check_in
from backend.core.dependencies import get_structured_llm_client

pytestmark = pytest.mark.asyncio

# A Thursday, so "Saturday" is two days out and the arithmetic is checkable.
NOW = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)
ZONE = "America/New_York"


async def _proposed(said: str, reply: str = ""):
    return await propose_check_in(
        get_structured_llm_client(), said, reply, now=NOW, timezone=ZONE
    )


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
    assert proposed.kind == EVENT, proposed
    assert proposed.subject, proposed


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


async def test_an_evening_out_is_asked_about_after_it_is_over() -> None:
    # The whole point of knowing the time: asking on Saturday afternoon how
    # Saturday evening went is worse than not asking.
    proposed = await _proposed("we're heading to National Harbor on Saturday evening")
    assert proposed is not None
    # Thursday + 2 is Saturday, so anything at or before 2 asks too early.
    assert proposed.after_days >= 3, proposed
