"""What the referent contract guarantees, independent of any model.

The resolver decides which owned thing a message points at. These prove the
boundaries around that decision - that it never returns a handle it was not
offered, that it fails closed rather than guessing, and that the sources
re-check ownership rather than trusting a semantic index that can outlive the
row it describes.
"""

import json

import pytest

from backend.core.llm import LLMClient
from backend.services.referent_resolution import (
    Referent,
    ReferentResolution,
    ReferentResolver,
)
from backend.services.referent_sources import (
    DocumentReferentSource,
    ImageReferentSource,
)

PORTRAIT = Referent(
    handle="portrait",
    kind="image",
    description="A person in a navy jacket and a straw hat by the water.",
    when="2026-08-10T12:00:00+00:00",
    title="Uploaded image",
)
BICYCLE = Referent(
    handle="bicycle",
    kind="image",
    description="A red bicycle leaning against a brick wall.",
    when="2026-08-09T12:00:00+00:00",
    title="Uploaded image",
)


class FixedLLM(LLMClient):
    """Return one controlled selection and record what was actually asked."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.messages: list[dict] = []

    def generate_text(self, prompt, max_tokens=1024):
        return "unused"

    def chat(self, messages, max_tokens=1024, schema=None, temperature=None):
        self.messages = messages
        return {"content": json.dumps(self.payload)}

    def stream_chat(self, messages, max_tokens=1024):
        yield "unused"


class FailingLLM(LLMClient):
    def generate_text(self, prompt, max_tokens=1024):
        return "unused"

    def chat(self, messages, max_tokens=1024, schema=None, temperature=None):
        raise RuntimeError("runtime unreachable")

    def stream_chat(self, messages, max_tokens=1024):
        yield "unused"


@pytest.mark.asyncio
async def test_one_match_is_confident_and_carries_the_referent():
    resolver = ReferentResolver(FixedLLM({"handles": ["portrait"]}))

    resolution = await resolver.resolve("make the hat black", [PORTRAIT, BICYCLE])

    assert resolution.is_confident
    assert resolution.only == PORTRAIT


@pytest.mark.asyncio
async def test_several_matches_are_ambiguous_rather_than_a_guess():
    resolver = ReferentResolver(FixedLLM({"handles": ["portrait", "bicycle"]}))

    resolution = await resolver.resolve("make it black and white", [PORTRAIT, BICYCLE])

    assert resolution.is_ambiguous
    assert resolution.only is None
    assert len(resolution.matched) == 2


# The same defence tool-calling uses: a name that was never offered is refused
# rather than trusted, so a malformed reply cannot reach an unowned row.
@pytest.mark.asyncio
async def test_a_handle_that_was_never_offered_is_discarded():
    resolver = ReferentResolver(FixedLLM({"handles": ["someone-elses-artifact"]}))

    resolution = await resolver.resolve("edit it", [PORTRAIT, BICYCLE])

    assert resolution.is_empty


# Acting on the wrong thing is worse than asking, so every failure path lands
# on "nothing matched", which the caller renders as a question.
@pytest.mark.asyncio
async def test_a_model_failure_fails_closed_to_no_match():
    resolver = ReferentResolver(FailingLLM())

    resolution = await resolver.resolve("edit it", [PORTRAIT, BICYCLE])

    assert resolution.is_empty


@pytest.mark.asyncio
async def test_no_candidates_needs_no_model_call():
    llm = FixedLLM({"handles": ["portrait"]})
    resolver = ReferentResolver(llm)

    resolution = await resolver.resolve("edit it", [])

    assert resolution.is_empty
    assert llm.messages == []


# The commonest case by far. Spending a model call to confirm the only option
# would add latency to every "edit it" with one picture on file.
@pytest.mark.asyncio
async def test_a_single_candidate_resolves_without_asking_the_model():
    llm = FixedLLM({"handles": []})
    resolver = ReferentResolver(llm)

    resolution = await resolver.resolve("make it black and white", [PORTRAIT])

    assert resolution.is_confident
    assert resolution.only == PORTRAIT
    assert llm.messages == []


# Descriptions are content, and content is untrusted; the prompt must say so
# in the same breath it hands them over.
@pytest.mark.asyncio
async def test_candidate_descriptions_are_framed_as_untrusted_data():
    llm = FixedLLM({"handles": ["portrait"]})

    await ReferentResolver(llm).resolve("edit it", [PORTRAIT, BICYCLE])

    system = llm.messages[0]["content"]
    assert "untrusted" in system
    assert "never" in system
    assert "instructions" in system


class StubArtifacts:
    """Return owned artifact rows, or None for anything not owned."""

    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows

    async def get_owned(self, user_id, artifact_id):
        return self.rows.get(artifact_id)


class StubMemory:
    """Return one semantic candidate list without embedding anything."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def embed_query(self, query):
        return [0.0]

    async def get_visual_memory_candidates(self, user_id, vector):
        return self.rows


# A derived description can outlive the artifact it describes, so ownership and
# readiness are re-checked per row rather than trusted from the index.
@pytest.mark.asyncio
async def test_the_image_source_drops_unowned_and_unready_rows():
    memory = StubMemory(
        [
            {"extra_data": {"artifact_id": "kept"}, "content": "a straw hat"},
            {"extra_data": {"artifact_id": "deleted"}, "content": "an orphan row"},
            {"extra_data": {"artifact_id": "pending"}, "content": "still rendering"},
        ]
    )
    artifacts = StubArtifacts(
        {
            "kept": {
                "id": "kept",
                "status": "ready",
                "kind": "uploaded_image",
                "title": "Uploaded image",
                "created_at": "2026-08-10T00:00:00+00:00",
                "metadata": {"analysis": "A straw hat by the water."},
            },
            "pending": {
                "id": "pending",
                "status": "generating",
                "kind": "generated_image",
                "metadata": {},
            },
        }
    )

    found = await ImageReferentSource(memory, artifacts).candidates(
        "u", "the hat", None
    )

    assert [item.handle for item in found] == ["kept"]
    assert found[0].description == "A straw hat by the water."
    assert found[0].kind == "image"


class StubKnowledge:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def search(self, user_id, query, top_k, query_embedding=None):
        return self.rows


class StubAgentMemory:
    def __init__(self, knowledge) -> None:
        self.knowledge = knowledge


# The user refers to "the contract", not to its fourth paragraph. Offering
# every matching chunk would manufacture ambiguity that does not exist.
@pytest.mark.asyncio
async def test_the_document_source_collapses_chunks_to_one_per_document():
    knowledge = StubKnowledge(
        [
            {
                "content": "Pricing is billed monthly.",
                "document": {"id": "contract", "title": "Contract", "created_at": "1"},
            },
            {
                "content": "Termination requires 30 days notice.",
                "document": {"id": "contract", "title": "Contract", "created_at": "1"},
            },
            {
                "content": "Team offsite agenda.",
                "document": {"id": "agenda", "title": "Agenda", "created_at": "2"},
            },
        ]
    )

    found = await DocumentReferentSource(StubAgentMemory(knowledge)).candidates(
        "u", "what does it say about pricing", None
    )

    assert [item.handle for item in found] == ["contract", "agenda"]
    # The best-matching chunk is what identifies the document to the resolver.
    assert found[0].description == "Pricing is billed monthly."
    assert found[0].kind == "document"


# Nothing in the resolver knows what an image is; a document resolves through
# exactly the same call, which is what makes video an indexer and not a rewrite.
@pytest.mark.asyncio
async def test_the_resolver_is_indifferent_to_modality():
    contract = Referent(
        handle="contract",
        kind="document",
        description="Pricing is billed monthly.",
        when="2026-08-01T00:00:00+00:00",
        title="Contract",
    )
    resolver = ReferentResolver(FixedLLM({"handles": ["contract"]}))

    resolution = await resolver.resolve(
        "what does it say about pricing", [contract, PORTRAIT]
    )

    assert resolution.is_confident
    assert resolution.only is not None
    assert resolution.only.kind == "document"


def test_an_empty_resolution_is_neither_confident_nor_ambiguous():
    empty = ReferentResolution(matched=())

    assert empty.is_empty
    assert not empty.is_confident
    assert not empty.is_ambiguous
    assert empty.only is None


class StubArtifactsWithListing(StubArtifacts):
    """Owned rows plus the newest-first listing the repository offers."""

    async def list_for_user(self, user_id, limit=100):
        rows = sorted(self.rows.values(), key=lambda r: r.get("created_at", ""), reverse=True)
        return rows[:limit]


# "This picture" carries nothing similarity can match, so the newest owned
# pictures must be offered even when the semantic index returns nothing -
# otherwise the resolver's "no detail means the most recent" rule has no
# candidate to apply to. Measured 2026-08-25: an edit right after an upload
# landed on an older picture because the upload was never offered.
@pytest.mark.asyncio
async def test_the_newest_pictures_are_offered_even_when_similarity_finds_nothing():
    memory = StubMemory([])
    artifacts = StubArtifactsWithListing(
        {
            "older": {
                "id": "older",
                "status": "ready",
                "kind": "generated_image",
                "title": "New image",
                "created_at": "2026-08-25T04:20:00+00:00",
                "metadata": {"generation_prompt": "a red bicycle against a brick wall"},
            },
            "newest": {
                "id": "newest",
                "status": "ready",
                "kind": "uploaded_image",
                "title": "Uploaded image",
                "created_at": "2026-08-25T04:27:00+00:00",
                "metadata": {"analysis": "A flag with a yellow circle."},
            },
            "pending": {
                "id": "pending",
                "status": "generating",
                "kind": "generated_image",
                "created_at": "2026-08-25T04:30:00+00:00",
                "metadata": {},
            },
        }
    )

    found = await ImageReferentSource(memory, artifacts).candidates(
        "user", "make the background of this picture purple", None
    )

    assert [item.handle for item in found] == ["newest", "older"], found
    assert found[0].when > found[1].when
