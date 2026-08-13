"""Turning a resolved lineage into the words the model is given.

The resolver is measured against a real database elsewhere, and what the model
does with the result is measured against a real model in the functional suite.
This is the seam between them: that a lineage reaches the prompt in terms a
reader can act on, that failing to resolve one costs provenance rather than the
turn — and that it never reaches the browser.

That last one is not hypothetical. Provenance was first merged into the match
records themselves, which are also streamed to the interface as JSON. A
dataclass is not JSON, so every chat turn that recalled an image died in the
encoder with "Unable to complete the chat request", while every test here
passed: they asserted on objects in memory, and the objects were fine. What was
untested was whether the stream could carry them.
"""

import json
from typing import Any

import pytest

from backend.artifacts.lineage import Lineage
from backend.services.conversation_service import (
    ConversationService,
    _image_description,
    _image_lineage,
)


class StubLineage:
    """Answer with a fixed lineage, or fail, without a database."""

    def __init__(
        self,
        answers: dict[str, Lineage] | None = None,
        fail: bool = False,
    ) -> None:
        self.answers = answers or {}
        self.fail = fail
        self.calls: list[list[str]] = []

    async def resolve_lineage(self, user_id, artifact_ids, max_depth=12):
        self.calls.append(list(artifact_ids))
        if self.fail:
            raise RuntimeError("database unavailable")
        return {k: v for k, v in self.answers.items() if k in set(artifact_ids)}


def _service(lineage: StubLineage | None) -> ConversationService:
    # Only the lineage collaborator matters here; the rest of the workflow is
    # never entered, so it is left unbuilt rather than elaborately faked.
    service = ConversationService.__new__(ConversationService)
    service.lineage = lineage
    return service


_PHOTO = Lineage(
    origin={
        "id": "a",
        "kind": "uploaded_image",
        "title": "Uploaded image",
        "description": "A man in a wide-brimmed black cowboy hat.",
    },
    edits=("give me a straw hat",),
)


# One call for the whole page of matches, not one per match.
@pytest.mark.asyncio
async def test_every_match_is_resolved_in_a_single_call() -> None:
    lineage = StubLineage({"b": _PHOTO})
    matches: list[dict[str, Any]] = [{"id": "b"}, {"id": "c"}, {"id": "d"}]

    resolved = await _service(lineage)._resolve_lineage("u", matches)

    assert lineage.calls == [["b", "c", "d"]]
    assert resolved["b"] is _PHOTO
    # An artifact that is nobody's revision is simply absent, so a caller cannot
    # mistake "no parent" for "parent unknown".
    assert "c" not in resolved


# The regression. Whatever is handed to the interface has to survive the
# encoder, and a match record is handed to the interface verbatim.
@pytest.mark.asyncio
async def test_resolving_lineage_never_touches_the_streamed_records() -> None:
    matches: list[dict[str, Any]] = [
        {"id": "b", "kind": "generated_image", "title": "Edited image"},
        {"id": "c", "kind": "uploaded_image", "title": "Uploaded image"},
    ]
    before = json.dumps(matches)

    await _service(StubLineage({"b": _PHOTO}))._resolve_lineage("u", matches)

    # Unchanged, and still encodable — the two claims that matter, because the
    # records are streamed as `image_matches` exactly as they are.
    assert json.dumps(matches) == before


# Provenance is an enrichment. Losing it must not lose the images themselves.
@pytest.mark.asyncio
async def test_a_resolver_failure_resolves_to_nothing_rather_than_raising() -> None:
    assert (
        await _service(StubLineage(fail=True))._resolve_lineage("u", [{"id": "b"}])
        == {}
    )


@pytest.mark.asyncio
async def test_no_resolver_configured_resolves_to_nothing() -> None:
    assert await _service(None)._resolve_lineage("u", [{"id": "b"}]) == {}


# The terms the model is given. `supplied_by_user` is the distinction it got
# wrong, and the edits are ordered so the origin reads as history.
def test_a_photograph_is_rendered_as_the_users_own() -> None:
    rendered = _image_lineage(_PHOTO)

    assert rendered["edited_from"]["supplied_by_user"] is True
    assert "black cowboy hat" in rendered["edited_from"]["description"]
    assert rendered["edits_applied"] == ["give me a straw hat"]
    # Rendered for a prompt that is serialized as JSON, so it has to be JSON.
    json.dumps(rendered)


def test_an_edited_generation_is_not_rendered_as_the_users_own() -> None:
    generated = Lineage(
        origin={
            "id": "a",
            "kind": "generated_image",
            "title": "Generated image",
            "description": "a cobalt sports car",
        },
        edits=("make it red",),
    )

    assert _image_lineage(generated)["edited_from"]["supplied_by_user"] is False


def test_a_match_with_no_lineage_renders_nothing() -> None:
    assert _image_lineage(None) == {}


# Historical rows whose flat analysis was overwritten recover the neutral first turn.
def test_image_description_prefers_the_canonical_thread_seed() -> None:
    assert (
        _image_description(
            {
                "metadata": {
                    "analysis": "Here is the straw-hat change you requested.",
                    "analysis_thread": [
                        {
                            "prompt": "Describe this image.",
                            "answer": "A person wearing a black cowboy hat and jacket.",
                        },
                        {
                            "prompt": "Give me a straw hat instead.",
                            "answer": "Here is the requested change.",
                        },
                    ],
                }
            }
        )
        == "A person wearing a black cowboy hat and jacket."
    )


class StubRecall:
    async def decide(self, query):
        class Decision:
            should_search = True
            reason = "descriptive_reference"

        return Decision()


class StubSearch:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self.hits = hits

    async def search_by_embedding(self, user_id, embedding, limit, max_distance):
        return self.hits


class StubMemory:
    async def embed_query(self, query):
        return [0.0, 0.0]


class KeepAll:
    def select(self, ranked):
        return ranked


class StubOwnedArtifacts:
    """Return only the image owned by the requested account."""

    def __init__(self, owner: str, artifact: dict[str, Any]) -> None:
        self.owner = owner
        self.artifact = artifact

    # Enforce the same ownership result as the repository boundary.
    async def get_owned(self, user_id: str, artifact_id: str):
        if user_id != self.owner or artifact_id != self.artifact["id"]:
            return None
        return self.artifact


class StubVisualMemory:
    """Expose one broad visual-memory candidate without a database."""

    # Return an already embedded visual description for semantic selection.
    async def get_visual_memory_candidates(self, user_id, query_embedding):
        return [
            {
                "content": "A person wearing a tailored navy jacket.",
                "extra_data": {"artifact_id": "active"},
            }
        ]


class StubVisualSelector:
    """Select the one offered visual candidate by meaning."""

    # Return the candidate that a real semantic selector would choose.
    async def select(self, query, candidates):
        return ("active",) if "style" in query else ()


# The failure exactly as it reached the user: a chat turn that recalls an image
# emits `image_matches`, the API encodes every event as JSON, and an object that
# is not JSON kills the stream — reported as "Unable to complete the chat
# request", with no clue that provenance was the cause.
#
# So this drives the real retrieval branch and encodes every event it yields,
# which is what the transport does.
@pytest.mark.asyncio
async def test_every_streamed_retrieval_event_survives_the_json_encoder() -> None:
    upload = {
        "id": "a",
        "kind": "uploaded_image",
        "title": "Uploaded image",
        "metadata": {"analysis": "A man in a black cowboy hat."},
        "parent_artifact_id": None,
    }
    edit = {
        "id": "b",
        "kind": "generated_image",
        "title": "Edited image",
        "metadata": {"refinement_feedback": "give me a straw hat"},
        "parent_artifact_id": "a",
    }

    service = ConversationService.__new__(ConversationService)
    service.memory = StubMemory()
    service.image_recall = StubRecall()
    service.image_search = StubSearch([upload, edit])
    service.image_retrieval = KeepAll()
    service.image_search_limit = 5
    service.lineage = StubLineage({"b": _PHOTO})
    service.search = None
    service.tool_orchestration = None

    context: dict[str, Any] = {}
    events = [
        event
        async for event in service._stream_retrieved_context(
            context, "u", "remember the cowboy image?", "trace", None, None
        )
    ]

    # What the transport does to every event, and what used to raise.
    for event in events:
        json.dumps(event["data"])

    # The edit still reached the prompt knowing it was made from a photograph.
    assert context["images"][0]["edited_from"]["supplied_by_user"] is True
    assert context["images"][0]["edits_applied"] == ["give me a straw hat"]
    assert "straw hat" in context["images"][0]["description"]
    assert "black cowboy hat" in context["images"][0]["edited_from"]["description"]


# A style question carries the image the browser is visibly discussing even
# though its wording contains no image-recall vocabulary.
@pytest.mark.asyncio
async def test_active_owned_image_reaches_chat_context_without_recall_words() -> None:
    upload = {
        "id": "active",
        "user_id": "owner",
        "kind": "uploaded_image",
        "status": "ready",
        "title": "Uploaded image",
        "metadata": {"analysis": "A person wearing a tailored navy jacket."},
    }
    service = ConversationService.__new__(ConversationService)
    service.image_artifacts = StubOwnedArtifacts("owner", upload)
    service.image_recall = None
    service.image_search = None
    service.lineage = None
    service.search = None

    context: dict[str, Any] = {}
    events = [
        event
        async for event in service._stream_retrieved_context(
            context,
            "owner",
            "what do you think of my style?",
            "trace",
            None,
            None,
            "active",
        )
    ]

    assert events == []
    assert context["images"][0]["description"] == (
        "A person wearing a tailored navy jacket."
    )


# Supplying another account's identifier must add no visual context.
@pytest.mark.asyncio
async def test_active_image_from_another_user_never_reaches_chat_context() -> None:
    upload = {
        "id": "active",
        "kind": "uploaded_image",
        "status": "ready",
        "metadata": {"analysis": "Private description."},
    }
    service = ConversationService.__new__(ConversationService)
    service.image_artifacts = StubOwnedArtifacts("owner", upload)
    service.image_recall = None
    service.image_search = None
    service.lineage = None
    service.search = None

    context: dict[str, Any] = {}
    async for _event in service._stream_retrieved_context(
        context,
        "other-user",
        "what do you think of my style?",
        "trace",
        None,
        None,
        "active",
    ):
        pass

    assert "images" not in context


# An older image can be recovered semantically when no visual is active.
@pytest.mark.asyncio
async def test_visual_memory_recalls_style_without_image_keywords() -> None:
    upload = {
        "id": "active",
        "kind": "uploaded_image",
        "status": "ready",
        "metadata": {"analysis": "A person wearing a tailored navy jacket."},
    }
    service = ConversationService.__new__(ConversationService)
    service.memory = StubVisualMemory()
    service.visual_memory = StubVisualSelector()
    service.image_artifacts = StubOwnedArtifacts("owner", upload)
    service.image_recall = None
    service.image_search = None
    service.lineage = None
    service.search = None

    context: dict[str, Any] = {}
    events = [
        event
        async for event in service._stream_retrieved_context(
            context,
            "owner",
            "what do you think of my style?",
            "trace",
            [0.1, 0.2],
            None,
        )
    ]

    assert context["images"][0]["description"].endswith("navy jacket.")
    assert events[0]["event"] == "image_matches"
    assert context["images"][0]["freshly_shown"] is True


# The same semantic recall, but the picture was already displayed earlier in
# this conversation. The description must still reach the model - answering
# the question does not stop - but the picture is not re-attached, and the
# model is told so, since re-attaching it on every adjacent turn is exactly
# the noise this dedup exists to remove.
@pytest.mark.asyncio
async def test_visual_memory_recall_is_not_redisplayed_once_already_shown() -> None:
    upload = {
        "id": "active",
        "kind": "uploaded_image",
        "status": "ready",
        "metadata": {"analysis": "A person wearing a tailored navy jacket."},
    }
    service = ConversationService.__new__(ConversationService)
    service.memory = StubVisualMemory()
    service.visual_memory = StubVisualSelector()
    service.image_artifacts = StubOwnedArtifacts("owner", upload)
    service.image_recall = None
    service.image_search = None
    service.lineage = None
    service.search = None

    context: dict[str, Any] = {}
    history = [{"metadata": {"artifact_ids": ["active"]}}]
    events = [
        event
        async for event in service._stream_retrieved_context(
            context,
            "owner",
            "what do you think of my style?",
            "trace",
            [0.1, 0.2],
            None,
            None,
            history,
        )
    ]

    assert context["images"][0]["description"].endswith("navy jacket.")
    assert context["images"][0]["freshly_shown"] is False
    assert events == []
    assert "shown_image_ids" not in context
