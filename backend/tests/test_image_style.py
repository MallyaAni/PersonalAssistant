from collections.abc import Iterator
from typing import Any

import pytest

from backend.services.image_style_service import ImageStyleService


class StubLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def generate_text(self, prompt: str, max_tokens: int = 512) -> str:
        return ""

    def chat(self, messages: Any, max_tokens: int = 512) -> dict[str, Any]:
        return {"content": self.reply}

    def stream_chat(self, messages: Any, max_tokens: int = 512) -> Iterator[str]:
        yield ""


class StubMemory:
    def __init__(self, preferences: dict[str, Any] | None = None) -> None:
        self.preferences = preferences or {}
        self.saved: dict[str, Any] | None = None

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "name": "Ani", "preferences": dict(self.preferences)}

    async def upsert_user_profile(
        self, user_id: str, name: str | None, preferences: dict[str, Any]
    ) -> dict[str, Any]:
        self.preferences = preferences
        self.saved = {"name": name, "preferences": preferences}
        return {"preferences": preferences}


def _service(memory: StubMemory, reply: str) -> ImageStyleService:
    return ImageStyleService(memory, StubLLM(reply))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_style_reads_the_profile_preference() -> None:
    memory = StubMemory({"image_style": "warm, cinematic"})
    assert await _service(memory, "x").get_style("u") == "warm, cinematic"


@pytest.mark.asyncio
async def test_reusable_feedback_is_learned_and_saved() -> None:
    memory = StubMemory()
    learned = await _service(memory, "photorealistic, warm golden tones").learn(
        "u", "make it more realistic with warmer tones"
    )
    assert learned == "photorealistic, warm golden tones"
    assert memory.preferences["image_style"] == "photorealistic, warm golden tones"


@pytest.mark.asyncio
async def test_image_specific_feedback_is_not_learned() -> None:
    memory = StubMemory({"image_style": "warm, cinematic"})
    # The model judges "add a red hat" specific to one image and replies NONE.
    learned = await _service(memory, "NONE").learn("u", "add a red hat")
    assert learned is None
    # The existing style is untouched.
    assert memory.preferences["image_style"] == "warm, cinematic"
    assert memory.saved is None
