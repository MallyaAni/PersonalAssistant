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
    direct = await _observe(question)

    llm = get_llm_client()
    try:
        result = llm.chat(build_reasoning_messages(question, observation, direct), 1024)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")

    answer = str(result.get("content") or "").lower()
    assert "q1" in answer
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
        direct_answer="I cannot make out any phone number in this image.",
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
