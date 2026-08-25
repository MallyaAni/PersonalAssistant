"""Is the writing in a generated picture in English?

FLUX.2 Klein's Qwen3 text encoder letters a picture in whatever script it
drifts to when the prompt says nothing about language: on 2026-08-25 a
stakeholder-value image asked for in English came back lettered in something
else. `IMAGE_TEXT_SUFFIX` now rides on every generation prompt. This measures
the result the only way it can be measured - by generating a picture with
writing on it and asking the vision model to read it back.

It needs the desktop that hosts ComfyUI, which is off at times, so it is
deselected from `scripts/gate.sh` (where a skip is a failure) and run by hand:

    docker compose run --rm --no-deps functional-tests \
        python -m pytest backend/tests/functional/test_image_text_language_behaviour.py -q

`backend.cli.exercise_image_scenarios` makes the same check as its tenth
scenario against the running API.
"""

from __future__ import annotations

import base64
import os
import secrets

import httpx
import pytest

from backend.artifacts.types import ImageGenerationRequest
from backend.config.settings import settings
from backend.core.dependencies import _build_comfyui_image_provider

pytestmark = pytest.mark.asyncio


async def _desktop_is_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.IMAGE_PROVIDER_BASE_URL}/system_stats")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


async def _read_writing(png: bytes) -> str:
    base = (os.getenv("VISION_BASE_URL") or settings.VISION_LLM_BASE_URL).rstrip("/")
    async with httpx.AsyncClient(timeout=120.0) as client:

        payload = {
            "model": settings.VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What text is written in this image? Reply with the exact letters only.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64," + base64.b64encode(png).decode()
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 64,
            "temperature": 0,
        }
        response = await client.post(f"{base}/chat/completions", json=payload)
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


async def test_the_writing_on_a_generated_sign_reads_back_in_english() -> None:
    if not await _desktop_is_up():
        pytest.skip("the desktop hosting ComfyUI is not reachable")
    # The same construction the application uses, so the clause under test
    # is the one that ships rather than a copy of it.
    provider = _build_comfyui_image_provider()
    result = await provider.generate(
        ImageGenerationRequest(
            prompt="a wooden shop sign that says OPEN in big letters",
            width=1024,
            height=1024,
            seed=secrets.randbelow(2**63),
        )
    )
    read = await _read_writing(result.content)
    assert "open" in read.lower(), f"the vision model read {read!r}"
