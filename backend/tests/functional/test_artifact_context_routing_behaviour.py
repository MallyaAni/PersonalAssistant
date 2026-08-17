"""Measure whether the real routing model gates multimodal artifact recall."""

import pytest

from backend.agents.memory.artifact_context import ArtifactContextRouter

pytestmark = pytest.mark.asyncio


# Personal visual questions need image memory even without image vocabulary.
@pytest.mark.parametrize(
    "query",
    [
        "what do you think of my style?",
        "what kind of hat was I wearing?",
        "what car did we create an image of?",
    ],
)
async def test_visual_questions_require_owned_image_context(
    llm: object, query: str
) -> None:
    router = ArtifactContextRouter(llm, ("image", "document", "audio", "video"))

    assert "image" in await router.required_modalities(query)


# Unrelated or generative work must never search the user's private artifacts.
@pytest.mark.parametrize(
    "query",
    [
        "yes id like scout for 9:40pm",
        "remind me about the dentist tomorrow",
        "explain how binary search works",
        "create an image of a horse",
    ],
)
async def test_non_artifact_questions_require_no_owned_context(
    llm: object, query: str
) -> None:
    router = ArtifactContextRouter(llm, ("image", "document", "audio", "video"))

    assert await router.required_modalities(query) == ()


# The contract already distinguishes future artifact sources without regex.
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("what does my uploaded lease say about subletting?", "document"),
        ("what did they say in my voice recording?", "audio"),
        ("which dance move am I doing in my uploaded clip?", "video"),
    ],
)
async def test_each_multimodal_reference_selects_its_source(
    llm: object, query: str, expected: str
) -> None:
    router = ArtifactContextRouter(llm, ("image", "document", "audio", "video"))

    assert expected in await router.required_modalities(query)
