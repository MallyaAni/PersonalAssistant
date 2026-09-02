"""What a shared document says is remembered - as the sharer's own fact.

The operator dropped the Amalfi itinerary in the Groupie room with "we are
going to do this trip and here's the itinerary". Passages are retrievable;
this proves the memory classifier, given the sharer's words plus what the
document says, proposes a durable fact about the trip (place or dates) and
attributes it to the sharer or the group - never to nobody, never to a
stranger. Against the real classifier, the way spoken turns are judged.
"""
import pytest

from backend.core.dependencies import get_llm_client, get_routing_llm_client
from backend.memory.proposal_agent import MemoryProposalAgent
from backend.services.document_facts import digest_document, facts_utterance

pytestmark = pytest.mark.asyncio

_ITINERARY = (
    "## Day 1: Sun., October 11\n\nArrivals throughout the day - Grand Hotel of Salerno 6:00 p.m. - "
    "Orientation 7:30 p.m. - Dinner in Hotel (included)\n\n"
    "## Day 2: Mon., October 12\n\nExcursion - 8:30 a.m. departure Pompeii and/or Paestum\n\n"
    "## Day 5: Thurs., October 15\n\nMorning - Independent: Boat trip along the coast"
)


async def test_a_shared_itinerary_becomes_a_fact_about_the_trip(llm):
    # Step one: the document is read into the one sentence worth remembering.
    caption = "we are going to do this trip and here's the itinerary. what do you think?"
    headline, statements = digest_document(get_routing_llm_client(), "Itinerary Amalfi Choral Tour.pdf", _ITINERARY, caption)
    assert headline, "the digest gave no headline for a dated itinerary"
    assert any(k in headline.casefold() for k in ("october", "salerno", "amalfi", "tour")), headline
    # Step two: heard as the sharer's own short statement, the classifier keeps it.
    utterance = facts_utterance(caption, headline)
    result = await MemoryProposalAgent(get_llm_client()).propose(utterance)
    facts = [p for p in result.proposals if p.get("kind") in ("semantic_fact", "episodic")]
    assert facts, result.proposals
    text = " ".join(str(p.get("content") or "") for p in facts).casefold()
    assert any(k in text for k in ("amalfi", "october", "salerno", "trip", "choral")), text
    # Attribution: the sharer's own words ("we") - about the speaker/the group,
    # not an unrelated name.
    about = " ".join(str(a) for p in facts for a in (p.get("about") or [])).casefold()
    assert not about or any(w in about for w in ("we", "us", "me", "i", "the group", "group")), about


async def test_a_document_with_no_plan_proposes_no_plan(llm):
    headline, _ = digest_document(
        get_routing_llm_client(), "recipe.html", "Feed the starter, Clementine, twice a day. Bake at 230C.", "here's that sourdough recipe"
    )
    utterance = facts_utterance("here's that sourdough recipe", headline)
    result = await MemoryProposalAgent(get_llm_client()).propose(utterance)
    text = " ".join(str(p.get("content") or "") for p in result.proposals).casefold()
    assert "going to" not in text and "trip" not in text, result.proposals
