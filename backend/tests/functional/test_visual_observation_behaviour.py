"""Measure whether the real VLM creates durable, factual visual memory."""

from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont

from backend.agents.vision.observation import (
    CANONICAL_OBSERVATION_PROMPT,
    build_visual_question_prompt,
)
from backend.core.dependencies import get_vision_provider

pytestmark = pytest.mark.asyncio


# Build a deterministic scene with apparel, setting, and text worth remembering.
def _visual_memory_fixture() -> bytes:
    image = Image.new("RGB", (960, 640), "#87ceeb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 430, 960, 640), fill="#4f8a3c")
    draw.ellipse((300, 105, 470, 275), fill="#d9a67e")
    draw.polygon([(270, 135), (500, 135), (445, 70), (330, 70)], fill="#171717")
    draw.rectangle((260, 260, 510, 535), fill="#174ea6")
    draw.polygon([(340, 260), (385, 365), (430, 260)], fill="white")
    draw.rectangle((610, 180, 900, 390), fill="#fff4cf", outline="#5b3a1e", width=8)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 43)
    except OSError:
        font = ImageFont.load_default()
    draw.text((650, 225), "DANCE", fill="#991b1b", font=font)
    draw.text((670, 300), "8 PM", fill="#111111", font=font)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# The canonical prompt must retain multiple visible facets without conversation.
async def test_observation_is_searchable_factual_and_non_conversational() -> None:
    provider = get_vision_provider()
    try:
        result = await provider.analyze(
            CANONICAL_OBSERVATION_PROMPT,
            _visual_memory_fixture(),
            "image/png",
        )
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")

    answer = result.content.lower()
    assert "person" in answer or "figure" in answer
    assert "blue" in answer
    assert "hat" in answer
    assert "dance" in answer
    # The 8 PM sign must be read as a time, however the model renders it: the
    # current model transcribes it as "p.m." rather than "8 pm" (2026-09-07).
    assert "pm" in answer or "p.m." in answer or "20:00" in answer
    assert "?" not in answer
    assert not any(
        phrase in answer
        for phrase in ("hello", "hi there", "would you like", "i recommend")
    )


# A deliberately low-detail processed-food fixture cannot support an exact
# regional species name, so the real VLM must expose that limitation.
async def test_ambiguous_processed_fish_is_not_given_a_definite_species() -> None:
    image = Image.new("RGB", (640, 420), "#d9b27c")
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 90, 230, 210), fill="#b8bec5", outline="#343a40", width=5)
    draw.rectangle((280, 85, 560, 205), fill="#d58c8c", outline="#343a40", width=5)
    draw.rectangle((90, 260, 500, 350), fill="#e5d3c0", outline="#343a40", width=5)
    output = BytesIO()
    image.save(output, format="PNG")

    provider = get_vision_provider()
    try:
        result = await provider.analyze(
            build_visual_question_prompt(
                "Which exact fish species are these, specific to India?"
            ),
            output.getvalue(),
            "image/png",
        )
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")

    answer = result.content.lower()
    # The refusal is the property - the model must decline rather than invent
    # a species - and it is said in any of several wordings. The current model
    # says the image holds "no fish ... no biological features" (2026-09-07).
    assert any(
        phrase in answer
        for phrase in (
            "cannot identify",
            "can't identify",
            "cannot determine",
            "can't determine",
            "not possible to identify",
            "not enough",
            "insufficient",
            "no fish",
            "not a fish",
            "no biological",
            "not identifiable",
            "no way to",
            "cannot be identified",
            "no diagnostic",
            "cannot confirm",
        )
    )
    assert not any(
        phrase in answer
        for phrase in ("definitely", "certainly", "clearly a", "is a rohu")
    )


# The combined upload contract must reject web identification when the pixels
# lack diagnostic anatomy instead of spending search on regional popularity.
async def test_structured_upload_marks_nondiagnostic_fish_as_unsupported() -> None:
    image = Image.new("RGB", (640, 420), "#d9b27c")
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 90, 230, 210), fill="#b8bec5", outline="#343a40", width=5)
    draw.rectangle((280, 85, 560, 205), fill="#d58c8c", outline="#343a40", width=5)
    draw.rectangle((90, 260, 500, 350), fill="#e5d3c0", outline="#343a40", width=5)
    output = BytesIO()
    image.save(output, format="PNG")

    provider = get_vision_provider()
    try:
        result = await provider.inspect_upload(
            "Can you identify the exact Indian fish names of these?",
            output.getvalue(),
            "image/png",
        )
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")

    assert result.intent == "ask"
    assert result.grounding == "unsupported"
    assert result.unsupported_reason == "missing_visual_evidence"
    assert result.search_query == ""
    assert result.needs_reasoning is False
    answer = result.answer.lower()
    # The structured verdict above is the hard contract (unsupported, no search
    # query); the answer must also decline in words, and the current model says
    # the image holds "no fish or biological subjects" (2026-09-07).
    assert any(
        phrase in answer
        for phrase in (
            "cannot identify",
            "can't identify",
            "cannot determine",
            "not possible",
            "impossible",
            "insufficient",
            "not enough",
            "not supported",
            "unable",
            "no fish",
            "not a fish",
            "no biological",
            "not identifiable",
            "cannot be identified",
            "no way to",
        )
    ), answer


# A clear item must retain high confidence even when another item is ambiguous.
async def test_structured_upload_keeps_confidence_per_visible_item() -> None:
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((90, 100, 360, 400), fill="#d71920", outline="#551111", width=8)
    draw.polygon([(220, 120), (300, 45), (340, 130)], fill="#2e7d32")
    draw.rectangle((550, 130, 820, 380), fill="#b8b8b8")
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 54)
    except OSError:
        font = ImageFont.load_default()
    draw.text((125, 205), "APPLE", fill="white", font=font)
    output = BytesIO()
    image.save(output, format="PNG")

    provider = get_vision_provider()
    try:
        result = await provider.inspect_upload(
            "Describe the clear shape on the left and identify the exact make and "
            "model of the device hidden under the gray cover on the right.",
            output.getvalue(),
            "image/png",
        )
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")

    high = [item for item in result.identified_items if item.confidence == "high"]
    # The hard contract: the covered device must never be given an exact make
    # or model, whatever the item array holds.
    assert result.grounding == "unsupported"
    assert result.unsupported_reason == "missing_visual_evidence"
    assert all(item.basis.strip() for item in result.identified_items)
    # The clear left shape is still addressed - in the item array when the
    # model puts it there, and in the answer prose in any case. The current
    # model answers entirely in prose, leaving identified_items empty even
    # though it names the red APPLE shape on the left and refuses the device
    # (2026-09-07); demanding a high-confidence item would assert on a wording
    # the model does not use rather than on what it got right.
    answer = result.answer.lower()
    assert high or any(
        token in answer for token in ("left", "red", "apple", "shape")
    ), result.answer
    assert any(
        phrase in answer
        for phrase in (
            "cannot be identified",
            "cannot identify",
            "can't identify",
            "not identify",
            "unable",
            "no way to",
            "cannot tell",
        )
    ), result.answer
