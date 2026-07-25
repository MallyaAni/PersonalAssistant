import asyncio
import logging
from typing import Any, Protocol

from backend.core.llm import LLMClient

logger = logging.getLogger(__name__)

# The model distills durable style from feedback; the application decides how it
# is stored and applied, so a confused reply can at worst add a style word.
_DISTILL_SYSTEM = (
    "You maintain a user's durable visual style preference for AI-generated "
    "images. You are given the current style (which may be empty) and new "
    "feedback the user gave on one image. If the feedback expresses a general, "
    "reusable visual preference - lighting, realism, colour mood, medium, or "
    "overall look - that should apply to future images, reply with the updated "
    "concise comma-separated style descriptor. If the feedback is specific to a "
    "single image's content (adding or removing a particular object or subject) "
    "and is not a reusable style, reply with exactly NONE. Reply with only the "
    "descriptor or NONE and nothing else."
)

_MAX_STYLE_CHARS = 300


class ProfileStore(Protocol):
    async def get_user_profile(self, user_id: str) -> dict[str, Any]: ...
    async def upsert_user_profile(
        self, user_id: str, name: str | None, preferences: dict[str, Any]
    ) -> dict[str, Any]: ...


class ImageStyleService:
    """Learn a durable per-user image style from feedback and apply it.

    Reusable style feedback (realism, lighting, colour mood) is folded into a
    per-user descriptor stored on the profile and appended to future
    generations; feedback specific to one image's content is not learned. The
    descriptor is ordinary profile data, so it is visible and clearable.
    """

    def __init__(
        self, memory: ProfileStore, llm: LLMClient, max_tokens: int = 160
    ) -> None:
        self.memory = memory
        self.llm = llm
        self.max_tokens = max_tokens

    async def get_style(self, user_id: str) -> str:
        profile = await self.memory.get_user_profile(user_id)
        preferences = profile.get("preferences") or {}
        return str(preferences.get("image_style") or "").strip()

    async def clear_style(self, user_id: str) -> None:
        await self._save(user_id, "")

    # Fold reusable feedback into the durable style; return the new descriptor or
    # None when the feedback was image-specific and nothing was learned.
    async def learn(self, user_id: str, feedback: str) -> str | None:
        existing = await self.get_style(user_id)
        descriptor = await self._distill(existing, feedback)
        if descriptor is None:
            return None
        await self._save(user_id, descriptor)
        return descriptor

    async def _save(self, user_id: str, style: str) -> None:
        profile = await self.memory.get_user_profile(user_id)
        preferences = dict(profile.get("preferences") or {})
        cleaned = style.strip()[:_MAX_STYLE_CHARS]
        if cleaned:
            preferences["image_style"] = cleaned
        else:
            preferences.pop("image_style", None)
        await self.memory.upsert_user_profile(user_id, profile.get("name"), preferences)

    async def _distill(self, existing: str, feedback: str) -> str | None:
        messages = [
            {"role": "system", "content": _DISTILL_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Current style: {existing or '(none)'}\n"
                    f"Feedback: {feedback.strip()}"
                ),
            },
        ]
        try:
            result = await asyncio.to_thread(self.llm.chat, messages, self.max_tokens)
            reply = str(result.get("content", "")).strip().strip('"').strip()
        except Exception:
            logger.warning("Image-style distillation failed", exc_info=True)
            return None
        if not reply or reply.upper().startswith("NONE"):
            return None
        return reply[:_MAX_STYLE_CHARS]
