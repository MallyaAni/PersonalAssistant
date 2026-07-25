import json
from typing import Any

import pytest

from backend.agents.presentation import PresentationAgent
from backend.presentations.provider import (
    LLMPresentationProvider,
    PresentationProvider,
)
from backend.presentations.types import DeckSpec, SlideSpec, TextElement


# Build a minimal two-slide deck with stable identifiers for revision tests.
def _deck() -> DeckSpec:
    return DeckSpec(
        title="Agent acceptance",
        slides=[
            SlideSpec(
                slide_id="slide-a",
                title="Opening",
                purpose="Introduce the topic",
                elements=[
                    TextElement(
                        element_id="title-a",
                        text="Opening",
                        x=0.7,
                        y=0.5,
                        w=5,
                        h=0.7,
                    )
                ],
            ),
            SlideSpec(
                slide_id="slide-b",
                title="Evidence",
                purpose="Show evidence",
                elements=[
                    TextElement(
                        element_id="title-b",
                        text="Evidence",
                        x=0.7,
                        y=0.5,
                        w=5,
                        h=0.7,
                    )
                ],
            ),
        ],
    )


class StubPresentationProvider(PresentationProvider):
    """Return deterministic typed plans without contacting a model."""

    # Return the fixed deck for an initial planning request.
    async def create(self, prompt: str) -> DeckSpec:
        assert prompt == "Create the acceptance deck"
        return _deck()

    # Return a replacement only for the selected slide.
    async def revise_slide(
        self,
        deck: DeckSpec,
        slide_id: str,
        feedback: str,
    ) -> SlideSpec:
        assert deck.title == "Agent acceptance"
        assert feedback == "Make the evidence clearer"
        selected = next(slide for slide in deck.slides if slide.slide_id == slide_id)
        return selected.model_copy(
            update={
                "title": "Clear evidence",
                "elements": [
                    selected.elements[0].model_copy(update={"text": "Clear evidence"})
                ],
            }
        )


class StubPlanningLLM:
    """Return compact content plans and record the requested output budgets."""

    # Keep deterministic replies and observed requests for contract assertions.
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.requests: list[tuple[list[dict[str, str]], int]] = []

    # Return the next compact plan without contacting LM Studio.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1_024,
    ) -> dict[str, Any]:
        self.requests.append((messages, max_tokens))
        return self.replies.pop(0)


class StubStreamingPlanningLLM(StubPlanningLLM):
    """Yield deterministic fragmented model records for progressive previews."""

    # Store one ordered stream and observe its configured token budget.
    def __init__(self, chunks: list[str]) -> None:
        super().__init__([])
        self.chunks = chunks
        self.stream_requests: list[tuple[list[dict[str, str]], int]] = []

    # Yield record fragments exactly as a local streamed completion would.
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1_024,
    ) -> Any:
        self.stream_requests.append((messages, max_tokens))
        yield from self.chunks


# Build concise semantic content for the requested number of slides.
def _compact_plan(slide_count: int) -> dict[str, Any]:
    return {
        "title": "Horses",
        "subtitle": "A concise introduction",
        "slides": [
            {
                "title": f"Horse topic {index}",
                "purpose": f"Explain horse topic {index}",
                "points": [
                    f"Key horse fact {index}.1",
                    f"Key horse fact {index}.2",
                    f"Key horse fact {index}.3",
                ],
                "key_message": f"Horse takeaway {index}",
                "notes": f"Speaker notes for horse topic {index}.",
            }
            for index in range(1, slide_count + 1)
        ],
    }


# Verify the focused LangGraph delegates creation and returns a typed deck.
@pytest.mark.asyncio
async def test_presentation_agent_creates_a_typed_deck() -> None:
    agent = PresentationAgent(StubPresentationProvider())
    deck = await agent.create("Create the acceptance deck")
    assert [slide.slide_id for slide in deck.slides] == ["slide-a", "slide-b"]


# Verify the focused LangGraph returns only the selected slide replacement.
@pytest.mark.asyncio
async def test_presentation_agent_revises_one_selected_slide() -> None:
    agent = PresentationAgent(StubPresentationProvider())
    slide = await agent.revise_slide(
        _deck(),
        "slide-b",
        "Make the evidence clearer",
    )
    assert slide.slide_id == "slide-b"
    assert slide.title == "Clear evidence"


# Verify compact model content becomes an exact-count native editable deck.
@pytest.mark.asyncio
async def test_compact_plan_compiles_six_slides_with_a_small_budget() -> None:
    llm = StubPlanningLLM([{"content": json.dumps(_compact_plan(6))}])
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        plan_max_tokens=2_048,
    )
    deck = await provider.create("create a presentation on horses, 6 slides")
    assert len(deck.slides) == 6
    assert [slide.slide_id for slide in deck.slides] == [
        f"slide_{index:03d}" for index in range(1, 7)
    ]
    assert all(len(slide.elements) >= 8 for slide in deck.slides)
    assert llm.requests[0][1] == 2_048
    assert "Produce exactly 6 slides" in llm.requests[0][0][0]["content"]


# Verify a wrong slide count receives one bounded compact-plan correction.
@pytest.mark.asyncio
async def test_compact_plan_retries_one_wrong_slide_count() -> None:
    llm = StubPlanningLLM(
        [
            {"content": json.dumps(_compact_plan(5))},
            {"content": json.dumps(_compact_plan(6))},
        ]
    )
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        plan_max_tokens=2_048,
    )
    deck = await provider.create("Build exactly 6 slides about horses")
    assert len(deck.slides) == 6
    assert len(llm.requests) == 2
    assert "Expected exactly 6 slides" in llm.requests[1][0][0]["content"]


# Verify selected-slide feedback sends only a compact edit with a small budget.
@pytest.mark.asyncio
async def test_compact_slide_edit_preserves_layout_and_updates_title() -> None:
    llm = StubPlanningLLM(
        [{"content": json.dumps({"title": "A Better Opening"})}]
    )
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        plan_max_tokens=2_048,
        revision_max_tokens=1_024,
    )
    before = _deck()
    revised = await provider.revise_slide(
        before,
        "slide-a",
        "The current title sounds weird",
    )

    assert revised.title == "A Better Opening"
    assert isinstance(revised.elements[0], TextElement)
    assert revised.elements[0].text == "A Better Opening"
    assert revised.elements[0].x == before.slides[0].elements[0].x
    assert revised.elements[0].element_id == "title-a"
    assert llm.requests[0][1] == 1_024
    assert "never reproduce coordinates" in llm.requests[0][0][0]["content"]


# Verify an invalid element reference receives one bounded compact correction.
@pytest.mark.asyncio
async def test_compact_slide_edit_retries_unknown_element_reference() -> None:
    llm = StubPlanningLLM(
        [
            {
                "content": json.dumps(
                    {
                        "text_updates": [
                            {"element_id": "missing", "text": "Wrong target"}
                        ]
                    }
                )
            },
            {"content": json.dumps({"title": "Corrected opening"})},
        ]
    )
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        revision_max_tokens=1_024,
    )
    revised = await provider.revise_slide(
        _deck(),
        "slide-a",
        "Improve the title",
    )

    assert revised.title == "Corrected opening"
    assert len(llm.requests) == 2
    assert "wrong editable type" in llm.requests[1][0][0]["content"]


# Verify each complete semantic slide becomes visible before the model stream ends.
@pytest.mark.asyncio
async def test_progressive_plan_compiles_each_streamed_slide() -> None:
    records = "".join(
        [
            json.dumps(
                {
                    "type": "deck",
                    "title": "Progressive horses",
                    "subtitle": "Visible while planning",
                    "slide_count": 2,
                }
            ),
            json.dumps(
                {
                    "type": "slide",
                    "index": 1,
                    "title": "Origins",
                    "purpose": "Introduce equine history",
                    "points": ["Early evolution", "Domestication"],
                    "notes": "Open with context.",
                }
            ),
            json.dumps(
                {
                    "type": "slide",
                    "index": 2,
                    "title": "Modern roles",
                    "purpose": "Explain current uses",
                    "points": ["Sport", "Therapy"],
                    "notes": "Close with modern impact.",
                }
            ),
            json.dumps({"type": "done"}),
        ]
    )
    llm = StubStreamingPlanningLLM(
        [records[:47], records[47:131], records[131:]]
    )
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        plan_max_tokens=2_048,
    )

    drafts = [
        draft
        async for draft in provider.create_progress(
            "Create a presentation on horses, 2 slides"
        )
    ]

    assert [len(draft.specification.slides) for draft in drafts] == [1, 2]
    assert drafts[0].specification.slides[0].title == "Origins"
    assert drafts[1].specification.slides[1].title == "Modern roles"
    assert all(draft.expected_slide_count == 2 for draft in drafts)
    assert llm.stream_requests[0][1] == 2_048
