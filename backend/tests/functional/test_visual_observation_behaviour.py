"""Measure whether the real VLM creates durable, factual visual memory."""

from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont

from backend.agents.vision.observation import CANONICAL_OBSERVATION_PROMPT
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
    assert "8 pm" in answer or "8:00 pm" in answer
    assert "?" not in answer
    assert not any(
        phrase in answer
        for phrase in ("hello", "hi there", "would you like", "i recommend")
    )
