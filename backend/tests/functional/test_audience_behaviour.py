"""Does the audience judge drop what a fact rules out, and keep everything else?

The prompt is `prompts/scout/audience.md`. It exists because a digest sent the
same speed-dating evening eleven times to someone whose approved, user-stated
fact was that they are not single, and nothing in the sweep read a stated
audience.

Asserted on properties rather than wording. The bar the prompt sets is
asymmetric on purpose - a restriction must be stated *and* a fact must
contradict it - so the keep cases outnumber the drop case here, and they are
held strictly. Excluding wrongly costs a find and teaches the reader the digest
is arbitrary; including wrongly costs one line they can scroll past.

Each case runs several times. Greedy decoding is not deterministic on this
runtime, so a single pass proves nothing about a judgement that will run
unattended every sweep - see the repeated measurements recorded in
`prompts/memory/proposal.md` for the same lesson.
"""

import asyncio

import pytest

from backend.agents.scout.describing import EventDescriber

pytestmark = pytest.mark.asyncio

# How many times each case is asked. Enough to see a judgement that only
# sometimes holds, few enough that the file stays runnable in a gate.
RUNS = 3

NOT_SINGLE = "1. The user is not single and is an adult."

SPEED_DATING = (
    "Speed Dating at Astro Beer Hall. Our singles night is back. Tickets are "
    "sold to single people only, in two age brackets - 40s and 50s. Every "
    "attendee is matched for six rounds of five-minute conversations and "
    "leaves with a card of mutual matches. Please do not book if you are "
    "attending as a couple."
)


# Ask one case `RUNS` times and return how many runs said "rules out".
async def _rate(describer: EventDescriber, title: str, source: str, facts: str) -> int:
    answers = await asyncio.gather(
        *(describer._audience_rules_out(title, source, facts) for _ in range(RUNS))
    )
    return sum(1 for answer in answers if answer)


@pytest.fixture
def describer(llm, structured_llm):
    return EventDescriber(llm, structured_llm)


async def test_a_stated_restriction_a_fact_contradicts_rules_the_person_out(describer):
    hits = await _rate(describer, "Speed Dating at Astro Beer Hall", SPEED_DATING, NOT_SINGLE)

    # The behaviour the prompt exists for. Held as a majority rather than as
    # every run, because the judgement is a model's and this runtime varies.
    assert hits >= 2, f"stated singles-only restriction was acted on {hits}/{RUNS} times"


async def test_the_same_page_rules_nobody_out_when_no_fact_speaks_to_it(describer):
    hits = await _rate(describer, "Speed Dating at Astro Beer Hall", SPEED_DATING, "1. They like live music and breweries.")

    # The inference this must never make. Measured on the reranker, the same
    # question answered with a worked example excluded a women-only race for a
    # person whose facts said nothing about gender at all.
    assert hits == 0, f"excluded on no relevant fact {hits}/{RUNS} times"


async def test_an_audience_that_welcomes_rather_than_bars_keeps_the_find(describer):
    hits = await _rate(
        describer,
        "Beginner line dancing",
        "A drop-in class for beginners, every Tuesday evening. No partner "
        "needed, first session free, everyone welcome.",
        "1. They have been line dancing for fifteen years and compete.",
    )

    # "For beginners" names an audience and closes the door on nobody. Reading
    # a welcome as a bar is how a filter starts eating the digest.
    assert hits == 0, f"treated a welcome as a bar {hits}/{RUNS} times"


async def test_a_taste_mismatch_is_not_an_eligibility_bar(describer):
    hits = await _rate(
        describer,
        "Old Town Wine Festival",
        "Forty regional wineries pour in Market Square from noon. Tasting "
        "glasses are included with entry and food trucks run all afternoon.",
        "1. They do not drink alcohol.",
    )

    # Theirs to decline, not the assistant's to hide. The page states no
    # restriction, and a preference is not an eligibility rule.
    assert hits == 0, f"dropped on taste rather than eligibility {hits}/{RUNS} times"


async def test_a_page_that_names_no_audience_keeps_the_find(describer):
    hits = await _rate(
        describer,
        "Alexandria Oktoberfest at John Carlyle Square",
        "Live music, German food and a stein-holding contest in the square "
        "from midday on Saturday. Free entry.",
        NOT_SINGLE,
    )

    assert hits == 0, f"excluded a page naming no audience {hits}/{RUNS} times"


async def test_the_sweep_path_carries_the_verdict(describer):
    # The wiring, not the judgement: `describe` is what the sweep calls, and a
    # ruled-out find has to come back marked so `_make_readable` can drop it.
    readable = await describer.describe(
        "Speed Dating at Astro Beer Hall",
        SPEED_DATING,
        facts=NOT_SINGLE,
    )

    assert readable.audience_rules_out is True


async def test_a_person_with_no_facts_is_never_ruled_out(describer):
    # No memory, no screening, and no model call spent on it either.
    readable = await describer.describe("Speed Dating at Astro Beer Hall", SPEED_DATING)

    assert readable.audience_rules_out is False
