"""An events turn is answered by code, and the model is never asked to write it.

On 2026-08-29 an events listing reached a phone with five invented map links
and a venue's opening hours printed where a start time goes. Both came from
the same place: the reply model was handed raw search snippets and asked, in
prose, to produce a listing. No instruction catches that reliably.

So on a turn the ranker judges to be events, the listing is rendered from
typed records and streamed as the answer. This test is the wiring - that the
records really do become the reply, and that the model really is not called.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from backend.core.llm import LLMClient
from backend.search.types import SearchResult, SearchResults
from backend.services.conversation_service import ConversationService
from backend.services.main_action_selector import SearchAction
from backend.tests.doubles import (
    StubConversationRepository,
    StubMainActionSelector,
    StubMemoryService,
    StubTracer,
)

RESULTS = [
    {
        "title": "The Lawn Canggu - Sunday Sessions",
        "url": "https://www.thelawncanggu.com/whats-on",
        "content": "Sunday Sessions at The Lawn, Batu Bolong. Every Sunday from 4pm with DJ Dea. Free before 6pm.",
        "provider": "brave",
    },
    {
        "title": "La Brisa Bali",
        "url": "https://labrisabali.com/events",
        "content": "La Brisa, Echo Beach, Canggu. Open daily 11am until late, kitchen until 10pm.",
        "provider": "brave",
    },
]

# What a well-behaved extraction returns: one real night, and one record whose
# only stated time is the venue's opening hours.
EXTRACTED = {
    "events": [
        {
            "source": 1,
            "name": "Sunday Sessions",
            "venue": "The Lawn",
            "area": "Batu Bolong",
            "artist": "DJ Dea",
            "when_text": "Every Sunday from 4pm",
            "when_kind": "recurring_weekday",
            "price_text": "Free before 6pm",
            "what": "Deep house on the grass.",
        },
        {
            "source": 2,
            "name": "La Brisa",
            "venue": "La Brisa",
            "area": "Echo Beach",
            "artist": "",
            "when_text": "Open daily 11am until late",
            "when_kind": "opening_hours",
            "price_text": "",
            "what": "Beach club.",
        },
    ]
}


class EventsLLM(LLMClient):
    """Answers the two constrained calls; records whether it was asked to write."""

    def __init__(self) -> None:
        self.streamed = False

    def generate_text(self, prompt, max_tokens=512):
        return "unused"

    def chat(self, messages, max_tokens=512, schema=None, temperature=None):
        properties = set(((schema or {}).get("properties") or {}))
        if "order" in properties:
            return {
                "content": json.dumps(
                    {"order": [1, 2], "events": True, "travel": False, "on_subject": True}
                )
            }
        if "events" in properties:
            return {"content": json.dumps(EXTRACTED)}
        return {"content": "{}"}

    def stream_chat(self, messages, max_tokens=512) -> Iterator[str]:
        self.streamed = True
        yield "a listing the model wrote itself, with https://maps.app.goo.gl/xyz in it"


class EventsSearch:
    def is_enabled(self) -> bool:
        return True

    async def search(self, query: str, max_results: int | None = None) -> SearchResults:
        return SearchResults(
            query=query,
            results=tuple(
                SearchResult(
                    title=item["title"],
                    url=item["url"],
                    content=item["content"],
                    score=0.9,
                    provider="brave",
                )
                for item in RESULTS
            ),
            provider="brave",
        )


def _service(llm: EventsLLM) -> ConversationService:
    return ConversationService(
        memory=StubMemoryService(),
        llm=llm,
        repository=StubConversationRepository(),
        tracer=StubTracer(),
        search=EventsSearch(),  # type: ignore[arg-type]
        main_action_selector=StubMainActionSelector(  # type: ignore[arg-type]
            SearchAction(query="what's on in Canggu this weekend")
        ),
    )


async def _reply(service: ConversationService) -> str:
    chunks: list[str] = []
    async for event in service.process_request(
        "events_user",
        "what's on in Canggu this weekend",
        "44444444-4444-4444-8444-444444444444",
        {"source": "test"},
    ):
        if event.get("event") == "delta":
            chunks.append(event["data"]["content"])
    return "".join(chunks)


@pytest.mark.asyncio
async def test_the_answer_is_the_rendered_listing_and_the_model_never_wrote_it():
    llm = EventsLLM()
    answer = await _reply(_service(llm))

    assert "Sunday Sessions" in answer, answer
    assert "The Lawn, Batu Bolong" in answer, answer
    # Built by code from the venue, not written by a model.
    assert "https://maps.google.com/?q=The+Lawn+Batu+Bolong" in answer, answer
    assert "https://www.thelawncanggu.com/whats-on" in answer, answer
    # The model was never asked for the listing, so what it would have said -
    # invented link and all - is nowhere in the reply.
    assert llm.streamed is False
    assert "goo.gl" not in answer, answer


@pytest.mark.asyncio
async def test_the_opening_hours_record_is_dropped_and_the_drop_is_declared():
    answer = await _reply(_service(EventsLLM()))
    # La Brisa publishes hours, not an event. It must not appear as a night...
    assert "Echo Beach" not in answer, answer
    # ...and the reader must be told, or a shorter list reads as "that is all".
    assert "opening hours" in answer, answer


@pytest.mark.asyncio
async def test_a_turn_the_extraction_cannot_type_still_answers_from_the_model():
    # The fallback that keeps this from being a cliff: an extraction returning
    # nothing leaves the prose path exactly as it was, behind the link fence.
    class EmptyExtraction(EventsLLM):
        def chat(self, messages, max_tokens=512, schema=None, temperature=None):
            properties = set(((schema or {}).get("properties") or {}))
            if "order" in properties:
                return {
                    "content": json.dumps(
                        {"order": [1, 2], "events": True, "travel": False, "on_subject": True}
                    )
                }
            return {"content": json.dumps({"events": []})}

    llm = EmptyExtraction()
    answer = await _reply(_service(llm))
    assert llm.streamed is True
    # And the fence is still in front of it: the model's invented link is gone.
    assert "goo.gl" not in answer, answer
    assert "a listing the model wrote itself" in answer, answer


# Results the ranker judged off the asked subject are not typed into a
# listing: a Raleigh question listed Brooklyn puppet shows under "Nothing I
# can date this week" on 2026-09-03, with the off-subject flag on top.
class OffSubjectLLM(EventsLLM):
    def chat(self, messages, max_tokens=512, schema=None, temperature=None):
        properties = set(((schema or {}).get("properties") or {}))
        if "order" in properties:
            return {
                "content": json.dumps(
                    {"order": [1, 2], "events": True, "travel": False, "on_subject": False}
                )
            }
        return super().chat(messages, max_tokens, schema, temperature)


@pytest.mark.asyncio
async def test_off_subject_results_are_not_typed_into_a_listing():
    llm = OffSubjectLLM()
    answer = await _reply(_service(llm))
    assert "Sunday Sessions" not in answer, answer
    assert "https://maps.google.com" not in answer, answer
    # The reply is the model's own, told the results were about something else.
    assert llm.streamed is True



# A second, model-written round that drifts to another place does not cost
# the first round its answer: judged on its own, the round that carried the
# place is on subject and its listing is the reply (Raleigh, 2026-09-03).
DRIFTED = [
    {
        "title": "Bread and Puppet at the Old Stone House",
        "url": "https://www.brooklynvegan.com/puppets",
        "content": "Bread and Puppet: The Upside Down World Circus, Old Stone House, Park Slope, Brooklyn. Friday September 18.",
        "provider": "brave",
    },
]


class DriftingSearch(EventsSearch):
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, max_results: int | None = None) -> SearchResults:
        self.calls += 1
        if self.calls == 1:
            return await super().search(query, max_results)
        return SearchResults(query=query, results=tuple(SearchResult(**item) for item in DRIFTED))


class MixedIsOffSubjectLLM(EventsLLM):
    """Says the results are off subject whenever Brooklyn is among them, and
    proposes a second query when asked for one."""

    def chat(self, messages, max_tokens=512, schema=None, temperature=None):
        properties = set(((schema or {}).get("properties") or {}))
        if "order" in properties:
            text = " ".join(str(m.get("content") or "") for m in messages)
            return {
                "content": json.dumps(
                    {"order": [1, 2], "events": True, "travel": False, "on_subject": "Brooklyn" not in text}
                )
            }
        if "events" in properties:
            return {"content": json.dumps(EXTRACTED)}
        return {"content": "beach clubs Canggu September 2026"}


@pytest.mark.asyncio
async def test_a_drifted_second_round_does_not_cost_the_first_its_listing(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "SEARCH_MAX_ROUNDS", 2)
    monkeypatch.setattr(settings, "SEARCH_MIN_ROUNDS", 2)
    llm = MixedIsOffSubjectLLM()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=llm,
        repository=StubConversationRepository(),
        tracer=StubTracer(),
        search=DriftingSearch(),  # type: ignore[arg-type]
        main_action_selector=StubMainActionSelector(  # type: ignore[arg-type]
            SearchAction(query="what's on in Canggu this weekend")
        ),
    )
    answer = await _reply(service)
    assert "Sunday Sessions" in answer, answer
    assert "Bread and Puppet" not in answer, answer
