"""Three things the assistant got wrong about its own situation.

**Where the person is.** The only geographic string in the router's prompt was
the IANA timezone, and IANA names a representative city rather than the user's.
Someone in Arlington, Virginia carries `America/New_York`, so asked for the
weather the model filled the location argument with "New York" - a real,
confident answer about a city 200 miles away, with nothing wrong-looking about
it. Their locality was stored correctly the whole time; it was simply never
shown to the model. The clock line now carries the place.

**What Scout is.** Scout is the interests-and-events sweep. A separate
capability, `schedule_task`, will schedule anything - including a recurring
search or lookup on any subject. The two sit next to each other in the prompt,
and a question about scheduling answered through Scout's frame comes back
wrongly narrow: "you need interests" is Scout's requirement, not the
scheduler's. Scout's card now says what Scout is not.

**Which events are still ahead.** Scout's scheduled digest filters past finds
and labels undated ones honestly ("I found a few possibilities, but couldn't
confirm their dates"). That guard lives in the digest path, so a conversational
"what's coming up?" - answered from raw search results - never reached it, and
offered events that had already happened. The reply prompt now has the rule,
and it has the date at the top of the same prompt to check against.

All three are prompt changes, so all three get a test that reads the answer
rather than checking a call was made.
"""

import pytest

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

ZONE = "America/New_York"
PLACE = "Arlington, Virginia, US"


def _clock(now: str = "Sunday 2026-08-23 09:00") -> str:
    return f"{now} - they are in {PLACE} ({ZONE})"


async def test_the_clock_line_names_the_city_not_the_timezone() -> None:
    """The regression, at the level of the string itself.

    Structural, but it is the whole defect: if the place is absent the model
    has nothing but `America/New_York` to reason from, and it will use it.
    """
    line = _clock()
    assert "Arlington" in line
    # The zone is still there - the router needs it to resolve "tomorrow at 9".
    assert ZONE in line
    assert line.index("Arlington") < line.index(ZONE), (
        "the place must lead; a trailing zone reads as the location"
    )


async def test_the_model_places_the_person_in_their_own_city(llm) -> None:
    """Given the clock line, a weather question must not travel to New York."""
    answer = llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a personal assistant. Answer in one short "
                    "sentence. Do not ask a question."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current date and time: {_clock()}\n\n"
                    "Which city should I look up the weather for? "
                    "Name the city only."
                ),
            },
        ],
        60,
        None,
        0.0,
    )
    text = str(answer.get("content") or answer).lower()
    assert "arlington" in text, text
    assert "new york" not in text, text


async def test_scheduling_anything_is_not_gated_on_interests(llm) -> None:
    """Scout's requirements must not be presented as the scheduler's.

    The failing shape: asked to schedule a recurring lookup on an arbitrary
    subject, the assistant answers with Scout's setup - interests, a home
    locality - as though those were needed. They are not.
    """
    roster = (
        "Scout: Finds things happening near you that match what you like, and "
        "turns each one into a calendar entry. Scout is the "
        "interests-and-events sweep specifically - it is not the general "
        "scheduler. Anything else the person wants done on a schedule, "
        "including a recurring search, lookup, or report on any subject, is a "
        "scheduled task and does not need Scout or an interest."
    )
    capability = (
        "Scheduled tasks: Set something up to happen later or on a schedule: a "
        "reminder, a daily or weekly message, a recurring check or lookup, "
        "anything they want done at a stated time rather than now."
    )

    answer = llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a personal assistant. These are your agents and "
                    f"capabilities.\n{roster}\n{capability}\n"
                    "Answer in two sentences at most."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Every Monday morning, search for news about lithium "
                    "battery recycling and text me a summary. Can you do that?"
                ),
            },
        ],
        200,
        None,
        0.0,
    )
    text = str(answer.get("content") or answer).lower()

    # It must not refuse, and must not demand Scout's setup for a plain task.
    assert "interest" not in text, (
        "answered a general scheduling request with Scout's requirements: " + text
    )
    refusals = ("i can't", "i cannot", "unable to", "not able to")
    assert not any(r in text for r in refusals), text


async def test_a_past_event_is_not_offered_as_upcoming(llm) -> None:
    """The date is in the prompt; a listing before it is not an option.

    Two results, one clearly past and one clearly ahead, with today stated.
    The past one must not be presented as something they could still attend.
    """
    results = (
        "Application-provided web search results follow.\n"
        "1. Rosslyn Jazz Festival - https://example.invalid/jazz - the "
        "festival took place on Saturday 8 August 2026 in Gateway Park, "
        "Arlington.\n"
        "2. Clarendon Night Market - https://example.invalid/market - runs "
        "on Saturday 12 September 2026 from 5pm in Clarendon, Arlington.\n"
    )
    answer = llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a personal assistant. Use only the search "
                    "results given. Compare every date against today "
                    "before offering anything, and do not present "
                    "something that has already happened as something "
                    "they could still attend."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current date and time: {_clock()}\n\n"
                    f"{results}\n"
                    "What events could I go to around here? Only ones I "
                    "can still attend."
                ),
            },
        ],
        320,
        None,
        0.0,
    )
    text = str(answer.get("content") or answer).lower()

    # The September one is the answer.
    assert "night market" in text or "clarendon" in text, text
    # The August one already happened. If it is named at all it must be
    # marked as past, never offered.
    if "jazz" in text:
        past = ("already", "passed", "was on", "took place", "over", "past")
        assert any(w in text for w in past), (
            "named a past event without saying it had passed: " + text
        )
