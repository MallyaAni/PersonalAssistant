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


class ForbiddenVisualMemory:
    """Fail if an unrelated turn reaches embedding or candidate retrieval."""

    # Prove the modality gate runs before query embedding.
    async def embed_query(self, query):
        raise AssertionError("unrelated turn reached artifact embedding")

    # Prove the modality gate runs before the owner-scoped vector index.
    async def get_visual_memory_candidates(self, user_id, query_embedding):
        raise AssertionError("unrelated turn reached visual candidates")


class StubVisualSelector:
    """Select the one offered visual candidate by meaning."""

    # Return the candidate that a real semantic selector would choose.
    async def select(self, query, candidates):
        return ("active",) if "style" in query else ()


class StubArtifactContextRouter:
    """Return a fixed semantic decision before artifact retrieval."""

    # Configure whether the conversation requires owned image context.
    def __init__(self, needs_image: bool = True) -> None:
        self.needs_image = needs_image
        self.calls = 0

    # Return the image modality only for visual-context requests.
    async def required_modalities(self, query):
        self.calls += 1
        return ("image",) if self.needs_image else ()


class StubOwnedArtifactsById:
    """Return artifacts from a fixed id-to-record map, honoring ownership."""

    def __init__(self, owner: str, artifacts: dict[str, dict[str, Any]]) -> None:
        self.owner = owner
        self.artifacts = artifacts

    async def get_owned(self, user_id: str, artifact_id: str):
        if user_id != self.owner:
            return None
        return self.artifacts.get(artifact_id)


class StubVisualSelectorReturningMany:
    """Select several offered candidates, simulating one file recalled three ways."""

    def __init__(self, artifact_ids: tuple[str, ...]) -> None:
        self.artifact_ids = artifact_ids

    async def select(self, query, candidates):
        return self.artifact_ids


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
    router = StubArtifactContextRouter()
    service.artifact_context_router = router
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
    router = StubArtifactContextRouter()
    service.artifact_context_router = router
    service.image_artifacts = StubOwnedArtifacts("owner", upload)
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
    assert router.calls == 1


# A schedule confirmation must stop before embeddings or private candidates load.
@pytest.mark.asyncio
async def test_unrelated_turn_skips_the_visual_vector_index() -> None:
    service = ConversationService.__new__(ConversationService)
    service.memory = ForbiddenVisualMemory()
    service.visual_memory = StubVisualSelector()
    router = StubArtifactContextRouter(needs_image=False)
    service.artifact_context_router = router
    service.image_artifacts = StubOwnedArtifactsById("owner", {})

    service.image_search = None
    service.lineage = None
    service.search = None

    context: dict[str, Any] = {}
    events = [
        event
        async for event in service._stream_retrieved_context(
            context,
            "owner",
            "yes id like scout for 9:40pm",
            "trace",
            None,
            None,
        )
    ]

    assert events == []
    assert "images" not in context
    assert router.calls == 1


# The exact scenario reported live: the same photo, uploaded across three
# separate conversations while testing, all matched one style question and
# were all shown as if they were three different recalled images.
@pytest.mark.asyncio
async def test_the_same_uploaded_file_recalled_more_than_once_is_shown_once() -> None:
    same_digest = "a" * 64
    artifacts = {
        artifact_id: {
            "id": artifact_id,
            "kind": "uploaded_image",
            "status": "ready",
            "sha256": same_digest,
            "created_at": created_at,
            "metadata": {"analysis": "A person wearing a black cowboy hat."},
        }
        for artifact_id, created_at in (
            ("first", "2026-08-13T17:53:26"),
            ("second", "2026-08-13T18:03:19"),
            ("third", "2026-08-13T18:07:13"),
        )
    }
    service = ConversationService.__new__(ConversationService)
    service.memory = StubVisualMemory()
    service.visual_memory = StubVisualSelectorReturningMany(
        ("first", "second", "third")
    )
    service.artifact_context_router = StubArtifactContextRouter()
    service.image_artifacts = StubOwnedArtifactsById("owner", artifacts)
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

    shown = next(
        event["data"]["artifacts"]
        for event in events
        if event["event"] == "image_matches"
    )
    # The newest copy survives, matching how a revision chain keeps the latest.
    assert [item["id"] for item in shown] == ["third"]


# One selected revision family renders only its latest child, not parent and edit.
@pytest.mark.asyncio
async def test_visual_memory_collapses_an_uploaded_image_and_its_edit() -> None:
    artifacts = {
        "original": {
            "id": "original",
            "kind": "uploaded_image",
            "status": "ready",
            "parent_artifact_id": None,
            "sha256": "a" * 64,
            "created_at": "2026-08-13T18:03:19",
            "metadata": {"analysis": "A person wearing a black cowboy hat."},
        },
        "edit": {
            "id": "edit",
            "kind": "generated_image",
            "status": "ready",
            "parent_artifact_id": "original",
            "sha256": "b" * 64,
            "created_at": "2026-08-13T18:07:13",
            "metadata": {"refinement_feedback": "replace it with a straw hat"},
        },
    }
    service = ConversationService.__new__(ConversationService)
    service.memory = StubVisualMemory()
    service.visual_memory = StubVisualSelectorReturningMany(("original", "edit"))
    service.artifact_context_router = StubArtifactContextRouter()
    service.image_artifacts = StubOwnedArtifactsById("owner", artifacts)

    matches = await service._load_visual_memory_matches(
        "owner", "which hat suited me better?", [0.1, 0.2]
    )

    assert [item["id"] for item in matches] == ["edit"]
