import json
from typing import Any

import pytest

from backend.agents.deck import PresentationAgent
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

    # Return one new slide carrying the requested identifier.
    async def add_slide(
        self,
        deck: DeckSpec,
        brief: str,
        slide_id: str,
        after_slide_id: str | None = None,
    ) -> SlideSpec:
        template = deck.slides[0]
        return template.model_copy(
            update={
                "slide_id": slide_id,
                "title": brief,
                "elements": [
                    template.elements[0].model_copy(
                        update={"element_id": f"{slide_id}_title", "text": brief}
                    )
                ],
            }
        )

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
        self.schemas: list[dict[str, Any] | None] = []

    # Return the next compact plan without contacting the configured provider.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1_024,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.requests.append((messages, max_tokens))
        self.schemas.append(response_schema)
        return self.replies.pop(0)


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


# The planning call carries a decoding schema that forbids unknown field names
# and pins an explicitly requested slide count, so the runtime cannot represent
# the invented-field and wrong-count replies that previously needed a retry.
@pytest.mark.asyncio
async def test_compact_plan_sends_a_constraining_response_schema() -> None:
    llm = StubPlanningLLM([{"content": json.dumps(_compact_plan(6))}])
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        plan_max_tokens=2_048,
    )
    await provider.create("create a presentation on horses, 6 slides")
    schema = llm.schemas[0]
    assert schema is not None
    assert schema["additionalProperties"] is False
    assert schema["properties"]["slides"]["minItems"] == 6
    assert schema["properties"]["slides"]["maxItems"] == 6
    slide_schema = schema["$defs"]["PlannedSlide"]
    assert slide_schema["additionalProperties"] is False
    # An optional note is a string, so `notes: null` is not a decodable reply.
    assert slide_schema["properties"]["notes"]["type"] == "string"


# An unconstrained slide count leaves the array bounds to the declared model.
@pytest.mark.asyncio
async def test_compact_plan_schema_omits_bounds_without_a_requested_count() -> None:
    llm = StubPlanningLLM([{"content": json.dumps(_compact_plan(3))}])
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        plan_max_tokens=2_048,
    )
    await provider.create("create a presentation on horses")
    schema = llm.schemas[0]
    assert schema is not None
    assert schema["properties"]["slides"]["minItems"] == 1
    assert schema["properties"]["slides"]["maxItems"] == 30


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


# A revision regenerates the slide's concise content and recompiles it into
# deterministic native objects; the model never handles internal element ids.
@pytest.mark.asyncio
async def test_slide_revision_regenerates_content_deterministically() -> None:
    llm = StubPlanningLLM(
        [
            {
                "content": json.dumps(
                    {
                        "title": "A Better Opening",
                        "purpose": "Introduce the topic clearly",
                        "points": ["First point", "Second point"],
                    }
                )
            }
        ]
    )
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        plan_max_tokens=2_048,
        revision_max_tokens=1_024,
    )
    revised = await provider.revise_slide(
        _deck(),
        "slide-a",
        "The current title sounds weird",
    )

    assert revised.slide_id == "slide-a"
    assert revised.title == "A Better Opening"
    # Layout and element ids are owned by the deterministic compiler, keyed to the
    # slide id, not produced by the model.
    assert isinstance(revised.elements[0], TextElement)
    assert revised.elements[0].element_id == "slide-a_title"
    assert revised.elements[0].text == "A Better Opening"
    assert revised.elements[0].x == 0.75
    assert llm.requests[0][1] == 1_024


# Verify an invalid reply receives one bounded correction and then succeeds.
@pytest.mark.asyncio
async def test_slide_revision_retries_one_invalid_reply() -> None:
    llm = StubPlanningLLM(
        [
            {"content": "this is not json"},
            {
                "content": json.dumps(
                    {
                        "title": "Corrected opening",
                        "purpose": "Introduce the topic",
                        "points": ["Alpha", "Beta"],
                    }
                )
            },
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
    assert "failed validation" in llm.requests[1][0][0]["content"]


# A revision rewrites text but must not drop an image already on the slide.
@pytest.mark.asyncio
async def test_slide_revision_preserves_an_attached_image() -> None:
    from uuid import uuid4

    from backend.presentations.types import ImageElement

    artifact_id = uuid4()
    base = _deck()
    with_image = base.slides[0].model_copy(
        update={
            "elements": [
                *base.slides[0].elements,
                ImageElement(
                    element_id="img-a",
                    artifact_id=artifact_id,
                    alt_text="an attached chart",
                    x=1.0,
                    y=1.0,
                    w=3.0,
                    h=2.0,
                ),
            ]
        }
    )
    deck = base.model_copy(update={"slides": [with_image, base.slides[1]]})
    llm = StubPlanningLLM(
        [
            {
                "content": json.dumps(
                    {
                        "title": "Reworded opening",
                        "purpose": "Introduce the topic",
                        "points": ["First", "Second"],
                    }
                )
            }
        ]
    )
    provider = LLMPresentationProvider(
        llm,  # type: ignore[arg-type]
        max_tokens=8_192,
        revision_max_tokens=1_024,
    )

    revised = await provider.revise_slide(deck, "slide-a", "reword the title")

    images = [
        element for element in revised.elements if isinstance(element, ImageElement)
    ]
    assert len(images) == 1
    assert images[0].artifact_id == artifact_id
    assert revised.title == "Reworded opening"


# Verify each independently planned slide becomes visible before the deck completes.
@pytest.mark.asyncio
async def test_progressive_plan_compiles_each_scheduled_slide() -> None:
    llm = StubPlanningLLM(
        [
            {
                "content": json.dumps(
                    {
                        "title": "Progressive horses",
                        "subtitle": "Visible while planning",
                        "slides": [
                            {
                                "title": "Origins",
                                "purpose": "Introduce equine history",
                            },
                            {
                                "title": "Modern roles",
                                "purpose": "Explain current uses",
                            },
                        ],
                    }
                )
            },
            {
                "content": json.dumps(
                    {
                        "title": "Origins",
                        "purpose": "Introduce equine history",
                        "points": ["Early evolution", "Domestication"],
                        "visual_prompt": "A cinematic portrait of early horses",
                        "visual_priority": 3,
                        "notes": "Open with context.",
                    }
                )
            },
            {
                "content": json.dumps(
                    {
                        "title": "Modern roles",
                        "purpose": "Explain current uses",
                        "points": ["Sport", "Therapy"],
                        "notes": "Close with modern impact.",
                    }
                )
            },
        ]
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
    assert drafts[0].specification.slides[0].visual_prompt == (
        "A cinematic portrait of early horses"
    )
    assert drafts[0].specification.slides[0].visual_priority == 3
    assert drafts[1].specification.slides[1].title == "Modern roles"
    assert all(draft.expected_slide_count == 2 for draft in drafts)
    assert [request[1] for request in llm.requests] == [1_024, 1_024, 1_024]
    assert (
        "never prefix a field name with optional_" in llm.requests[1][0][0]["content"]
    )


# Verify an explicit null optional note is normalized before deterministic compilation.
@pytest.mark.asyncio
async def test_progressive_plan_normalizes_null_notes() -> None:
    llm = StubPlanningLLM(
        [
            {
                "content": json.dumps(
                    {
                        "title": "Null notes",
                        "slides": [
                            {"title": "Overview", "purpose": "Explain the topic"}
                        ],
                    }
                )
            },
            {
                "content": json.dumps(
                    {
                        "title": "Overview",
                        "purpose": "Explain the topic",
                        "points": ["First", "Second"],
                        "notes": None,
                    }
                )
            },
        ]
    )
    provider = LLMPresentationProvider(llm, max_tokens=8_192)  # type: ignore[arg-type]

    drafts = [
        draft
        async for draft in provider.create_progress(
            "Create a concise presentation with exactly 1 slide"
        )
    ]

    assert drafts[0].specification.slides[0].notes == ""


# Verify an invalid outline receives one correction before slide microtasks run.
@pytest.mark.asyncio
async def test_progressive_plan_corrects_one_invalid_outline() -> None:
    llm = StubPlanningLLM(
        [
            {"content": "not json"},
            {
                "content": json.dumps(
                    {
                        "title": "Progressive horses",
                        "subtitle": "Visible while planning",
                        "slides": [
                            {"title": "Origins", "purpose": "Explain origins"},
                            {"title": "Roles", "purpose": "Explain roles"},
                        ],
                    }
                )
            },
            {
                "content": json.dumps(
                    {
                        "title": "Origins",
                        "purpose": "Explain origins",
                        "points": ["Evolution", "Domestication"],
                    }
                )
            },
            {
                "content": json.dumps(
                    {
                        "title": "Roles",
                        "purpose": "Explain roles",
                        "points": ["Sport", "Therapy"],
                    }
                )
            },
        ]
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
    assert len(llm.requests) == 4
    assert "failed validation" in llm.requests[1][0][0]["content"]
    assert "never prefix one with optional_" in llm.requests[1][0][0]["content"]


# Adding a slide must leave every existing slide byte-for-byte intact. The whole
# reason "add another slide" failed before was that the only mutation available
# rewrote the selected slide.
@pytest.mark.asyncio
async def test_agent_adds_a_slide_without_touching_the_existing_ones() -> None:
    agent = PresentationAgent(StubPresentationProvider())
    deck = _deck()

    added = await agent.add_slide(deck, "Closing summary", "slide_003")

    assert added.slide_id == "slide_003"
    assert added.title == "Closing summary"
    # The source deck is untouched; insertion is the service's decision.
    assert [slide.slide_id for slide in deck.slides] == ["slide-a", "slide-b"]


# The new slide is planned from the deck's shape, not its full contents, so the
# model cannot rewrite accepted slides through the addition path.
@pytest.mark.asyncio
async def test_added_slide_prompt_carries_only_titles_and_purposes() -> None:
    llm = StubPlanningLLM(
        [
            {
                "content": json.dumps(
                    {
                        "title": "Closing",
                        "purpose": "Summarize the argument",
                        "points": ["First point", "Second point"],
                        "notes": "",
                    }
                )
            }
        ]
    )
    provider = LLMPresentationProvider(llm, max_tokens=8_192)  # type: ignore[arg-type]

    slide = await provider.add_slide(_deck(), "Add a closing slide", "slide_003")

    assert slide.slide_id == "slide_003"
    sent = llm.requests[0][0][1]["content"]
    assert "Add a closing slide" in sent
    assert "Opening" in sent
    assert "Introduce the topic" in sent
    # Element identifiers and geometry never reach the model.
    assert "title-a" not in sent
    assert "slide_003_title" not in sent


def test_new_slide_identifier_never_collides_with_an_existing_one() -> None:
    from backend.services.presentation_service import _next_slide_id

    deck = DeckSpec(
        title="Deck",
        slides=[
            SlideSpec(
                slide_id=f"slide_{index:03d}",
                title=f"S{index}",
                purpose="p",
                elements=[
                    TextElement(
                        element_id=f"t{index}", text="x", x=0.5, y=0.5, w=4, h=0.5
                    )
                ],
            )
            for index in (1, 2, 7)
        ],
    )

    minted = _next_slide_id(deck)

    assert minted == "slide_008"
    assert minted not in {slide.slide_id for slide in deck.slides}
