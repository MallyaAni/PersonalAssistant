"""A picture the user already has can be put back in front of them.

On 2026-08-25, "can you show me that image?" over iMessage found the picture
(two images were recalled into the model's context) and answered "I can't
display it here". Nothing streamed the existing artifact to a client. These
hold the new `show_image` action to the lifecycle every client renders.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from backend.core.llm import LLMClient
from backend.services.conversation_service import (
    ConversationService,
    _history_carried_pictures,
)
from backend.services.main_action_selector import MainAction
from backend.services.referent_resolution import Referent, ReferentResolution
from backend.tests.doubles import (
    StubConversationRepository,
    StubMainActionSelector,
    StubMemoryService,
    StubTracer,
)
from backend.tools.actions import ShowImageAction
from backend.tools.registry import builtin_tools, parse_builtin

CAT = Referent(
    handle=str(uuid.uuid4()),
    kind="image",
    description="a cat sleeping in a sunbeam",
    when="2026-08-17",
    title="Generated image",
)
BICYCLE = Referent(
    handle=str(uuid.uuid4()),
    kind="image",
    description="a red bicycle leaning against a brick wall",
    when="2026-08-24",
    title="Generated image",
)


class NoopLLM(LLMClient):
    # Fixed text for every contract; nothing here reaches a model.
    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        return "unused"

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        return {"content": "unused"}

    def stream_chat(
        self, messages: list[dict[str, str]], max_tokens: int = 1024
    ) -> Iterator[str]:
        yield "unused"


class CapturingConversationRepository(StubConversationRepository):
    # Capture persisted turns so the show turn's metadata can be asserted.
    def __init__(self) -> None:
        self.saved_turns: list[tuple[str, dict[str, Any]]] = []

    async def save_turn(self, conversation_id: str, turn: dict[str, Any]) -> None:
        self.saved_turns.append((conversation_id, turn))


class OwnedPictures:
    # The owned-artifact reads the show path makes, with the private key present.
    def __init__(self, user_id: str, *referents: Referent) -> None:
        self.records = {
            referent.handle: {
                "id": referent.handle,
                "user_id": user_id,
                "kind": "generated_image",
                "status": "ready",
                "mime_type": "image/png",
                "title": referent.title,
                "_storage_key": f"{user_id}/{referent.handle}.png",
            }
            for referent in referents
        }

    async def get_owned(self, user_id: str, artifact_id: str) -> dict[str, Any] | None:
        record = self.records.get(artifact_id)
        return record if record and record["user_id"] == user_id else None


class OfferedReferents:
    # What the referent source offers for any instruction.
    kind = "image"

    def __init__(self, *referents: Referent) -> None:
        self.referents = list(referents)

    async def candidates(self, user_id, reference, query_embedding):
        return list(self.referents)


class FixedResolver:
    # Resolve to a fixed set of matches, however the instruction is worded.
    def __init__(self, *matched: Referent) -> None:
        self.matched = matched

    async def resolve(self, instruction, candidates):
        return ReferentResolution(matched=tuple(self.matched))


def _service(
    user_id: str,
    action: ShowImageAction,
    offered: tuple[Referent, ...],
    matched: tuple[Referent, ...],
) -> tuple[ConversationService, CapturingConversationRepository]:
    conversations = CapturingConversationRepository()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=NoopLLM(),
        repository=conversations,
        tracer=StubTracer(),
        main_action_selector=StubMainActionSelector(action),  # type: ignore[arg-type]
        image_artifacts=OwnedPictures(user_id, *offered),  # type: ignore[arg-type]
        referent_resolver=FixedResolver(*matched),  # type: ignore[arg-type]
    )
    service.image_referents = OfferedReferents(*offered)  # type: ignore[assignment]
    return service, conversations


async def _events(service: ConversationService, user_id: str, query: str) -> list[dict]:
    return [
        event
        async for event in service.process_request(
            user_id, query, "12121212-1212-4121-8121-121212121212"
        )
    ]


def test_show_image_is_offered_beside_the_other_image_tools() -> None:
    names = [tool.name for tool in builtin_tools()]
    assert names.index("show_image") == names.index("edit_image") + 1


def test_show_image_parses_which_picture_and_refuses_a_blank() -> None:
    action = parse_builtin("show_image", {"which": " the cat picture "}, "fallback")
    assert action == ShowImageAction(which="the cat picture")
    assert parse_builtin("show_image", {"which": "   "}, "fallback") is None


@pytest.mark.asyncio
async def test_a_confident_match_streams_the_existing_picture() -> None:
    service, conversations = _service(
        "zakarya", ShowImageAction(which="that cat image"), (CAT, BICYCLE), (CAT,)
    )
    events = await _events(service, "zakarya", "can you show me that image?")
    assert [event["event"] for event in events] == [
        "start",
        "action",
        "artifact_started",
        "delta",
        "artifact_ready",
        "done",
    ]
    shown = events[-2]["data"]
    assert shown["id"] == CAT.handle
    assert shown["mime_type"] == "image/png", "the iMessage worker attaches by mime type"
    assert "_storage_key" not in shown, "the private storage key must not leave the process"
    assert events[2]["data"]["id"] == CAT.handle, "the web fills the placeholder it opened"
    assert "again" in events[3]["data"]["content"]
    assert conversations.saved_turns[0][1]["metadata"]["artifact_ids"] == [CAT.handle]


@pytest.mark.asyncio
async def test_an_ambiguous_match_shows_the_newest_and_offers_the_rest() -> None:
    service, conversations = _service(
        "zakarya", ShowImageAction(which="the picture"), (CAT, BICYCLE), (CAT, BICYCLE)
    )
    events = await _events(service, "zakarya", "show me the picture again")
    kinds = [event["event"] for event in events]
    # A show costs nothing, so the newest match is shown rather than asked
    # about, and the others are offered for the web's chooser.
    assert "image_matches" in kinds and "artifact_ready" in kinds
    offered = {item["id"] for item in events[kinds.index("image_matches")]["data"]["artifacts"]}
    assert offered == {CAT.handle, BICYCLE.handle}
    assert events[kinds.index("artifact_ready")]["data"]["id"] == BICYCLE.handle
    text = events[kinds.index("delta")]["data"]["content"]
    assert "newest" in text and "1 other picture" in text
    assert conversations.saved_turns[0][1]["metadata"]["artifact_ids"] == [BICYCLE.handle]


def test_the_newest_referent_is_chosen_by_its_date() -> None:
    from backend.services.conversation_service import _newest_referent

    assert _newest_referent(()) is None
    assert _newest_referent((CAT, BICYCLE)) is BICYCLE
    undated = Referent(handle="x", kind="image", description="undated")
    assert _newest_referent((undated, CAT)) is CAT
    assert _newest_referent((undated,)) is undated


def test_history_that_carried_a_picture_is_recognised() -> None:
    assert not _history_carried_pictures([])
    assert not _history_carried_pictures([{"query": "hi", "response": "hey", "metadata": {}}])
    assert _history_carried_pictures(
        [{"query": "make a cat", "response": "Here's the image.", "metadata": {"artifact_ids": ["x"]}}]
    )


def test_the_shown_pictures_label_fits_a_sentence() -> None:
    from backend.services.conversation_service import _short_label

    long = Referent(
        handle="x", kind="image",
        description="A lively beach club party at Fins in Canggu, Bali at dusk. A vibrant crowd dancing on a sandy dance floor.",
    )
    assert _short_label(long) == "a lively beach club party at Fins in Canggu, Bali at dusk"
    assert _short_label(Referent(handle="y", kind="image", description="a red bicycle")) == "a red bicycle"
    assert _short_label(Referent(handle="z", kind="image", description="", title="Uploaded image")) == "Uploaded image"
