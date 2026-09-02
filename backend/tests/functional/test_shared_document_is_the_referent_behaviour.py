"""A document shared in a room is what "day 1" means afterwards.

Live, 2026-09-02, in the Groupie room: an hour after "Scout we are going to
trivia at Courthouse Social today", the operator dropped the Amalfi itinerary
(unaddressed, so it was read silently) and asked "Scout whats on evening of
day 1?". The resolver, seeing no trace of the document in the thread,
completed "day 1" to "day 1 of the trivia plan at Courthouse Social" and the
reply answered about trivia. The worker now observes a silent share into the
thread by name; this proves the resolver then reads the shorthand against
the document, not the older plan.
"""
import pytest

from backend.core.dependencies import get_routing_llm_client
from backend.services.followup import resolve_followup

pytestmark = pytest.mark.asyncio

_TITLE = "Itinerary Amalfi Choral Tour.Draft.8.31.26.docx.pdf"

# History turns are {"query", "response"} pairs, as the transcript stores them;
# an observed line is a turn with no reply, which is what a silent share is.
_HISTORY = [
    {
        "query": "Scout we are going to trivia at courthouse social today - we go often",
        "response": "Nice. I saved that, and I set a reminder for 6pm today about trivia at Courthouse Social.",
    },
    {"query": f'shared a document: "{_TITLE}"', "response": ""},
]


async def test_day_one_means_the_shared_itinerary_not_the_older_plan(llm):
    resolution = await resolve_followup(
        get_routing_llm_client(), "Scout whats on evening of day 1?", _HISTORY
    )
    assert resolution is not None
    reading = " ".join(str(v) for v in resolution.as_dict().values()).casefold()
    assert "itinerary" in reading or "amalfi" in reading, resolution.as_dict()
    assert "trivia" not in reading and "courthouse" not in reading, resolution.as_dict()
