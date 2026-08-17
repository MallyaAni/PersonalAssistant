"""Measure whether reasoning over what the VLM saw beats the VLM's own answer.

The point of the reasoning pass is not that it produces text - it is that a
question needing judgement gets answered by the strongest configured model
instead of by a model chosen for describing pixels. These tests therefore run
both models for real and assert on what actually came back, per this repo's rule
that a structural test cannot tell you the answer got worse.
"""

import re
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from backend.agents.vision.reasoning import build_reasoning_messages
from backend.core.dependencies import get_llm_client, get_vision_provider

pytestmark = pytest.mark.asyncio


# A scene with a real, decidable question in it: two clearly different chart
# bars, so "which quarter did better and by how much" has one correct answer
# that requires reading the image and then reasoning about it.
def _chart_fixture() -> bytes:
    image = Image.new("RGB", (720, 520), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 60, 80 + 120, 420), fill="#2f6f5e")
    draw.rectangle((300, 220, 300 + 120, 420), fill="#9a5b12")
    draw.line((60, 420, 660, 420), fill="#111111", width=4)
    draw.text((110, 440), "Q1: 90", fill="#111111")
    draw.text((330, 440), "Q2: 50", fill="#111111")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def _observe(prompt: str) -> str:
    provider = get_vision_provider()
    try:
        result = await provider.analyze(prompt, _chart_fixture(), "image/png")
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")
    return result.content


# The reasoning pass must answer the arithmetic the question actually asks,
# which is a step beyond the description the VLM returns.
async def test_reasoning_answers_a_question_the_description_only_implies() -> None:
    question = "Which quarter was higher, and by what percentage did it beat the other?"
    observation = await _observe(
        "Describe this chart, including every number you can read."
    )

    llm = get_llm_client()
    try:
        result = llm.chat(build_reasoning_messages(question, observation), 1024)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")

    answer = str(result.get("content") or "").lower()
    assert "90" in answer
    assert "50" in answer
    # 90 vs 50 is an 80% increase; accept the common correct phrasings without
    # demanding one exact spelling of the number.
    assert any(token in answer for token in ("80%", "80 percent", "80.0%"))


# The reasoning model must never dress up a detail it was never given. This is
# the failure mode that makes a description-based answer worse than the VLM's,
# so it is asserted directly rather than assumed from the prompt's wording.
async def test_reasoning_refuses_to_invent_detail_it_was_not_given() -> None:
    llm = get_llm_client()
    messages = build_reasoning_messages(
        question="What is the exact phone number printed on the sign?",
        observation="A green park bench beside a gravel path. No text is legible.",
    )
    try:
        result = llm.chat(messages, 512)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")

    answer = str(result.get("content") or "").lower()
    # A fabricated phone number is the specific failure this guards against, so
    # assert no digit sequence long enough to read as one appears at all.
    assert not re.search(r"\d[\d\s().-]{5,}", answer)
    assert any(
        phrase in answer
        for phrase in (
            "no phone number",
            "not visible",
            "cannot",
            "can't",
            "no text",
            "not legible",
            "isn't",
            "is not",
            "unable",
        )
    )


# Web evidence must be usable for identification without becoming a claim about
# the pixels. This is the specific failure the labelled section guards: given a
# search result, the model must name the device and still not assert that the
# name was legible in the photograph.
async def test_search_results_identify_without_being_reported_as_seen() -> None:
    llm = get_llm_client()
    messages = build_reasoning_messages(
        question="What is this device?",
        observation=(
            "A small champagne-gold desktop computer with a dense perforated "
            "metal front panel, roughly the footprint of a paperback book. No "
            "legible branding or model text is visible on the chassis."
        ),
        search_results=(
            "The NVIDIA DGX Spark is a compact desktop AI supercomputer with a "
            "distinctive gold-coloured chassis and a dense perforated front "
            "grille. It is roughly 150mm square and sits on a desk rather than "
            "in a rack."
        ),
    )
    try:
        result = llm.chat(messages, 800)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")

    answer = str(result.get("content") or "").lower()
    assert "dgx spark" in answer
    # It must not claim the name was readable on the device; the notes said the
    # opposite, and inventing legible branding is the hallucination this whole
    # labelling scheme exists to prevent.
    assert not any(
        phrase in answer
        for phrase in (
            "badge reads",
            "label reads",
            "text on the front reads",
            "branding reads",
            "logo reads",
        )
    )


# Neutral visual evidence that lacks diagnostic anatomy must produce an honest
# limitation without importing regional species guesses from world knowledge.
async def test_reasoning_rejects_unsupported_species_candidates() -> None:
    llm = get_llm_client()
    messages = build_reasoning_messages(
        question="Can you identify which fish these are specific to India?",
        observation=(
            "Several containers hold whole silver fish, cut fish steaks, "
            "unlabelled pale fillets, and shrimp. The cuts obscure diagnostic "
            "features, so the fish species cannot be determined from the image."
        ),
    )
    try:
        result = llm.chat(messages, 700)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")

    answer = str(result.get("content") or "").lower()
    # Asserted as the property rather than one phrasing of it: the answer must
    # say the identification cannot be made. Pinned to "cannot determine" it
    # failed three runs in four on "the fish species cannot be determined",
    # which is the behaviour this test exists to require.
    assert "cannot" in answer or "can't" in answer or "not possible" in answer
    assert any(word in answer for word in ("determin", "identif", "confirm", "tell"))
    # The guarantee that actually matters, and the one hedging must not erode:
    # with no candidate offered by the vision pass, no species may be supplied
    # from world knowledge however strongly the question suggests a region.
    assert not any(
        candidate in answer
        for candidate in ("rohu", "catla", "indian eel", "snakehead", "hilsa")
    )


# A hard identification must come back as hedged readings plus the one question
# that would settle it, not as a refusal.
#
# Reported live: asked to identify fish in a photograph of prepared seafood, the
# reply withheld every reading and offered nothing to do next, while the vision
# pass had in fact read three of them.
async def test_unsettled_identifications_are_offered_and_a_question_is_asked() -> None:
    llm = get_llm_client()
    messages = build_reasoning_messages(
        question="identify and label the fish in this image",
        observation=(
            "Raw fish in containers and cut pieces on a wooden board, with "
            "peeled shrimp in a bowl."
        ),
        candidates=[
            {
                "label": "Whole silvery fish (likely mackerel)",
                "confidence": "low",
                "basis": "visible silvery scales, fins and body shape",
            },
            {
                "label": "Peeled shrimp",
                "confidence": "high",
                "basis": "whole peeled shrimp are visibly recognizable",
            },
        ],
    )
    try:
        result = llm.chat(messages, 900)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")
    answer = str(result.get("content") or "")
    lowered = answer.lower()

    # The confident reading survives, and so does the hedged one.
    assert "shrimp" in lowered
    assert "mackerel" in lowered
    # Hedged, never asserted as settled.
    assert any(
        word in lowered
        for word in ("low confidence", "likely", "not certain", "uncertain", "possibly")
    )
    # And it asks for what would actually narrow it.
    assert "?" in answer
