"""Does each prompt still do its job?

One test per behaviour a prompt exists to produce, asserted on properties rather
than on wording, so a reworded prompt survives and a changed behaviour does not.

The behaviours are the ones each prompt would be worthless without. They are
chosen from what the prompt claims to do, not from a list of past incidents.
"""

import pytest

from backend.agents.scout.aiming import AimPlanner
from backend.agents.scout.describing import EventDescriber
from backend.agents.scout.place_suggest import PlaceSuggester
from backend.agents.scout.reranking import MemoryReranker
from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.personal_context import PersonalContext
from backend.discovery.relevance import RankedCandidate

pytestmark = pytest.mark.asyncio


async def test_aiming_turns_a_bare_label_into_a_described_kind_of_thing(llm):
    aim = await AimPlanner(llm).plan(("Horses",), PersonalContext(), "Alexandria")

    profile = aim.vector_texts()["Horses"]
    # The point of the stage: two words cannot be matched against an event
    # description, so the profile has to say what the interest means.
    assert len(profile.split()) >= 3, profile
    assert profile.casefold() != "horses"


async def test_aiming_keeps_the_query_free_of_the_place_and_the_date(llm):
    aim = await AimPlanner(llm).plan(
        ("Live Music", "Hiking"), PersonalContext(), "Arlington, Virginia"
    )

    for item in aim.aims:
        subject = item.subject.casefold()
        # The skeleton appends the place and the month. A subject naming either
        # says it twice, which is the phrasing measured to return directories.
        assert "arlington" not in subject
        assert "virginia" not in subject
        assert not any(character.isdigit() for character in subject)


async def test_aiming_uses_an_approved_fact_when_there_is_one(llm):
    known = PersonalContext(("They run casually at weekends and never race.",))

    aimed = await AimPlanner(llm).plan(("Run Clubs",), known, "Arlington")
    plain = await AimPlanner(llm).plan(("Run Clubs",), PersonalContext(), "Arlington")

    # Personalisation has to be visible in the text, or reading memory is an
    # expensive no-op.
    assert aimed.vector_texts()["Run Clubs"] != plain.vector_texts()["Run Clubs"]


async def test_describing_names_a_find_without_the_site_boilerplate(llm):
    readable = await EventDescriber(llm).describe(
        "COLLECTIVE concert - Alexandria, The Light Horse, "
        "Oct 03, 2026, 9:30 PM | Shazam",
        "COLLECTIVE play The Light Horse in Alexandria on 3 October 2026, "
        "doors 9:30 PM.",
    )

    name = readable.title.casefold()
    # A page title is written for search engines; a name is what you would say
    # to a friend, so the site and the clock time drop out.
    assert "shazam" not in name
    assert "9:30" not in name
    assert len(readable.title) <= 70


async def test_describing_reports_a_page_that_says_it_is_over(llm):
    readable = await EventDescriber(llm).describe(
        "Spring Plant Sale",
        "Thanks to everyone who came to our Spring Plant Sale. Results are posted "
        "below and we raised over four thousand pounds. See you next year.",
    )

    assert readable.already_happened is True


async def test_describing_does_not_call_an_upcoming_thing_over(llm):
    readable = await EventDescriber(llm).describe(
        "Beginner line dancing",
        "A drop-in class every Tuesday evening. No partner needed, first session "
        "free, everyone welcome.",
    )

    # The costly direction: a false positive deletes a good find and nothing
    # downstream can tell it existed.
    assert readable.already_happened is False


async def test_describing_never_puts_a_link_in_its_own_words(llm):
    readable = await EventDescriber(llm).describe(
        "Trail cleanup",
        "Register at https://trails.example.org/signup for the cleanup on "
        "Saturday morning. Visit http://sponsor.example.com for our sponsors.",
    )

    # Links in a message come from the typed record, so a page cannot put one of
    # its choosing in front of a recipient.
    assert "http" not in (readable.description or "")


async def test_place_completion_offers_the_places_a_name_could_mean(llm):
    suggestions = await PlaceSuggester(llm).suggest("Cambridg")

    assert suggestions, "a well known name should complete to something"
    # Disambiguation is the whole feature: one answer for a name meaning several
    # places is the wrong answer.
    assert len({item.region.casefold() for item in suggestions}) >= 2, suggestions


async def test_place_completion_refuses_to_invent(llm):
    assert await PlaceSuggester(llm).suggest("Zzzqxvv") == ()


async def test_place_completion_writes_a_region_out_in_full(llm):
    suggestions = await PlaceSuggester(llm).suggest("Arlingt")

    assert suggestions
    for item in suggestions:
        # An abbreviation is ambiguous to a search engine and unhelpful to read.
        assert len(item.region) > 2, item


def _ranked(*titles: str) -> tuple[RankedCandidate, ...]:
    return tuple(
        RankedCandidate(
            candidate=ScoredCandidate(
                event=DiscoveredEvent(
                    source_id="web-search",
                    external_id=f"e{index}",
                    title=title,
                    starts_at=None,
                    ends_at=None,
                    place="Arlington, Virginia",
                    url=f"https://example.org/e{index}",
                    summary=title,
                ),
                embedding=None,
            ),
            score=0.5,
            matched_interest=None,
        )
        for index, title in enumerate(titles)
    )


async def test_reranking_puts_what_the_facts_support_first(llm):
    shortlist = _ranked(
        "Advanced ultramarathon, qualifying time required",
        "Beginner-friendly social 5k, all paces welcome",
    )
    context = PersonalContext(("They run casually and have never raced.",))

    ordered = await MemoryReranker(llm).order(shortlist, context)

    assert ordered[0].event.title.startswith("Beginner-friendly")


async def test_reranking_does_not_drop_what_is_merely_a_weak_match(llm):
    shortlist = _ranked("A pottery class", "A jazz evening", "A guided walk")
    context = PersonalContext(("They enjoy quiet evenings indoors.",))

    ordered = await MemoryReranker(llm).order(shortlist, context)

    # Nothing here is forbidden to anyone. Exclusion is for a stated restriction
    # a fact contradicts, never for a weak match.
    assert len(ordered) == len(shortlist)


async def test_reranking_keeps_an_age_marked_thing_without_a_contradicting_fact(llm):
    # An age-restricted find with no fact about the person's age stays:
    # absence is not contradiction, and the conservative wording excludes
    # nothing it does not have to (measured in reranking.py).
    shortlist = _ranked("21+ tasting event", "A guided walk")
    context = PersonalContext(("They enjoy quiet evenings indoors.",))

    ordered = await MemoryReranker(llm).order(shortlist, context)

    assert len(ordered) == len(shortlist)


# Flowcharts, which is what almost every request asks for. This was xfailed as
# "a real defect" and the defect turned out to be serialization, not reasoning:
# inside a JSON string the model joined its Mermaid lines with <br/> instead of
# escaped newlines, and the whole reply was rejected. The graph underneath was
# correct every time. Normalizing the break took eight varied requests from 3/8
# to 7/8; making the call greedy made the score reproducible at all.
#
# State diagrams are the one shape still unfixed: asked for a video player the
# model returns `"source": "stateDiagram-v2"` with no body. That is the model
# failing the task rather than mis-encoding it, so it is recorded rather than
# repaired, and it is not in the set below.
@pytest.mark.parametrize(
    "request_text",
    [
        "a three step order pipeline: receive, pack, ship",
        "a login flow with success and failure branches",
        "the lifecycle of a support ticket",
        "a CI pipeline: build, test, deploy",
        "user signs up, verifies email, then onboards",
        "data flows from sensors to a queue to storage to a dashboard",
    ],
)
async def test_diagram_returns_renderable_mermaid_within_bounds(llm, request_text):
    from backend.artifacts.diagram import LLMDiagramProvider

    specification = await LLMDiagramProvider(llm, "test").generate(request_text)

    source = specification.source
    assert (
        source.splitlines()[0]
        .strip()
        .startswith(("flowchart", "graph", "sequenceDiagram", "stateDiagram"))
    ), source
    # A diagram that will not render is worse than none, so the prompt forbids
    # what this renderer refuses.
    assert "<" not in source
    assert "click " not in source
    assert "```" not in source


def _kinds(result) -> set[str]:
    return {str(p.get("kind")) for p in result.proposals}


async def test_memory_capture_takes_a_name_and_interests_from_one_message(llm):
    from backend.memory.proposal_agent import MemoryProposalAgent

    result = await MemoryProposalAgent(llm).propose(
        "Hi my name is Arsalon and I like surfing, motorbikes and coffee"
    )

    # The positive control. Without it the two tests below pass whenever the
    # agent returns nothing at all, which is exactly how they were first
    # written — asserting absence against an attribute that never existed, so
    # they were green while proving nothing.
    assert _kinds(result) == {"preferred_name", "discovery_interests"}, result.proposals
    labels = next(
        p["labels"] for p in result.proposals if p["kind"] == "discovery_interests"
    )
    # A comma-separated list is several interests, not one.
    assert len(labels) >= 3, labels


async def test_memory_capture_ignores_a_question(llm):
    from backend.memory.proposal_agent import MemoryProposalAgent

    result = await MemoryProposalAgent(llm).propose("What is my dog called?")

    # A question is not a fact. Capturing one puts words in the user's mouth on
    # an approval card.
    assert result.proposals == (), result.proposals


async def test_memory_capture_does_not_take_someone_elses_preference(llm):
    from backend.memory.proposal_agent import MemoryProposalAgent

    result = await MemoryProposalAgent(llm).propose(
        "My daughter loves ballet, but I have never been interested in it."
    )

    assert "ballet" not in str(result.proposals).casefold(), result.proposals
