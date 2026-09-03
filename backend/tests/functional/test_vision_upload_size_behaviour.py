"""A phone-sized photo is answered by the real vision model, not refused.
On 2026-09-02 a 4032x3024 picture from an iPhone was 16,809 tokens against
the model's 16,384 context; the server said 400 and the person was told "I
hit a problem". Images are now fitted to the model before they are sent.
Needs a vision model (VISION_BASE_URL as the gate passes it, or
VISION_LLM_BASE_URL); skips where neither is set.
"""
import io
import os

import pytest

from backend.config.settings import settings

pytestmark = pytest.mark.asyncio


def _phone_photo() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (4032, 3024), (200, 220, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((600, 800, 3400, 2200), fill=(180, 60, 40))
    draw.ellipse((1500, 300, 2500, 1300), fill=(250, 220, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


async def test_a_phone_photo_is_described_not_refused():
    # The gate's container is handed VISION_BASE_URL, not the settings name
    # (test_image_text_language_behaviour reads it the same way).
    base = (os.getenv("VISION_BASE_URL") or settings.VISION_LLM_BASE_URL).rstrip("/")
    if not base:
        pytest.skip("no vision model is configured here")
    from backend.vision.lm_studio import create_vision_provider

    provider = create_vision_provider(
        adapter="openai_compatible",
        base_url=base,
        model=settings.VISION_MODEL,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=settings.VISION_LLM_REASONING_EFFORT,
        max_tokens=settings.VISION_MAX_TOKENS,
    )
    inspection = await provider.inspect_upload("What is in this picture?", _phone_photo(), "image/jpeg")
    assert inspection is not None
    text = str(inspection).lower()
    assert any(word in text for word in ("red", "yellow", "circle", "rectangle", "shape", "blue")), text
