import asyncio
import logging
import secrets
from typing import Any

from backend.artifacts.types import ImageGenerationRequest
from backend.core.llm import LLMClient
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.image_style_service import ImageStyleService

logger = logging.getLogger(__name__)

# The model rewrites the prompt; the application still owns generation, storage,
# and lineage, so a confused rewrite can at worst produce one unwanted image.
_REFINE_SYSTEM = (
    "You refine text-to-image prompts. You are given an existing prompt and the "
    "user's feedback on the image it produced. Rewrite the prompt so it keeps the "
    "original subject and scene but applies the feedback. Output only the revised "
    "prompt on a single line, with no preamble, quotes, or explanation."
)

_MAX_PROMPT_CHARS = 2000
_MAX_FEEDBACK_CHARS = 2000


class RefinementError(RuntimeError):
    """The artifact cannot be refined: missing, not owned, or not generated."""


class ImageRefinementService:
    """Regenerate a generated image from its prompt plus the user's feedback.

    This is a non-destructive revision: a new artifact is created that links to
    its parent, so the progression is preserved rather than overwritten.
    """

    def __init__(
        self,
        images: ImageArtifactService,
        llm: LLMClient,
        style_service: ImageStyleService | None = None,
        default_width: int = 2048,
        default_height: int = 2048,
        max_prompt_tokens: int = 300,
    ) -> None:
        self.images = images
        self.llm = llm
        self.style_service = style_service
        self.default_width = default_width
        self.default_height = default_height
        self.max_prompt_tokens = max_prompt_tokens

    async def refine(
        self,
        user_id: str,
        artifact_id: str,
        feedback: str,
        conversation_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        record = await self.images.get_owned_record(user_id, artifact_id)
        if record is None or record.get("kind") != "generated_image":
            raise RefinementError("No owned generated image matched the request")
        metadata = record.get("metadata") or {}
        original_prompt = str(metadata.get("generation_prompt") or "").strip()
        if not original_prompt:
            raise RefinementError("The image has no recorded prompt to refine")

        refined_prompt = await self._compose_prompt(original_prompt, feedback)
        style = ""
        if self.style_service is not None:
            style = await self.style_service.get_style(user_id)

        # A fresh seed so the feedback actually changes the image, rather than the
        # same seed reproducing it almost identically.
        revision = await self.images.generate(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            request=ImageGenerationRequest(
                prompt=refined_prompt,
                width=int(record.get("width") or self.default_width),
                height=int(record.get("height") or self.default_height),
                seed=secrets.randbelow(2**63),
            ),
            extra_metadata={
                "parent_artifact_id": artifact_id,
                "refinement_feedback": feedback.strip()[:_MAX_FEEDBACK_CHARS],
            },
            extra_style=style,
        )

        # Learn a durable style from the feedback so future images benefit; a
        # failure here must never fail the refinement the user is watching.
        if self.style_service is not None:
            try:
                learned = await self.style_service.learn(user_id, feedback)
                if learned:
                    revision.setdefault("metadata", {})["learned_style"] = learned
            except Exception:
                logger.warning("Image-style learning failed", exc_info=True)
        return revision

    # Ask the model to fold the feedback into the prompt, with a deterministic
    # merge as a fallback so a refinement never silently drops the feedback.
    async def _compose_prompt(self, original_prompt: str, feedback: str) -> str:
        messages = [
            {"role": "system", "content": _REFINE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Existing prompt: {original_prompt}\n"
                    f"Feedback: {feedback.strip()[:_MAX_FEEDBACK_CHARS]}"
                ),
            },
        ]
        refined = ""
        try:
            result = await asyncio.to_thread(
                self.llm.chat, messages, self.max_prompt_tokens
            )
            refined = str(result.get("content", "")).strip().strip('"').strip()
        except Exception:
            logger.warning("Prompt refinement call failed; using merge", exc_info=True)
        if not refined:
            refined = f"{original_prompt}, {feedback.strip()}"
        return refined[:_MAX_PROMPT_CHARS]
