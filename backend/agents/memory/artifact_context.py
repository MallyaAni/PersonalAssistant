"""Decide which owned artifact modalities a conversation actually needs."""

import asyncio
import json
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.llm import LLMClient

logger = logging.getLogger(__name__)

type ArtifactModality = Literal["image", "document", "audio", "video"]


class ArtifactContextDecision(BaseModel):
    """Artifact modalities that must be recalled to answer one message."""

    model_config = ConfigDict(extra="forbid")

    modalities: list[ArtifactModality] = Field(max_length=4)


class ArtifactContextRouter:
    """Gate owner-scoped artifact indexes before any semantic retrieval."""

    # Configure one bounded semantic decision and the modalities implemented now.
    def __init__(
        self,
        llm: LLMClient,
        available_modalities: tuple[ArtifactModality, ...],
        max_tokens: int = 96,
    ) -> None:
        self.llm = llm
        self.available_modalities = available_modalities
        self.max_tokens = max_tokens

    # Return only available modalities that materially help answer the message.
    async def required_modalities(self, query: str) -> tuple[ArtifactModality, ...]:
        if not query.strip() or not self.available_modalities:
            return ()
        messages = [
            {
                "role": "system",
                "content": (
                    "Decide whether answering the newest message requires recalling "
                    "something from the user's own saved artifacts. Return only the "
                    "artifact modalities that must be searched.\n\n"
                    "An image is required for questions about the user's appearance, "
                    "clothing, style, visible belongings or places, or a picture they "
                    "previously uploaded, generated, or edited. A document is required "
                    "when the answer depends on the contents of one of their files. "
                    "Audio or video is required when the answer depends on what can be "
                    "heard or seen in their recording.\n\n"
                    "Return no modalities for settings, schedules, agents, reminders, "
                    "plans, ordinary conversation, general knowledge, or a request to "
                    "create a brand-new artifact. Mentioning a visual subject does not "
                    "require an image: 'write about a horse' and 'create an image of a "
                    "horse' both need no saved artifact. Select a modality only when "
                    "the answer depends on content the user already owns.\n\n"
                    "Return only the required JSON object."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Available artifact modalities:\n"
                    f"{json.dumps(self.available_modalities)}\n\n"
                    f"Newest message:\n{query}"
                ),
            },
        ]
        try:
            result = await asyncio.to_thread(
                self.llm.chat,
                messages,
                self.max_tokens,
                ArtifactContextDecision.model_json_schema(),
                0.0,
            )
            parsed = ArtifactContextDecision.model_validate_json(result["content"])
        except Exception:
            logger.warning("Artifact-context routing failed", exc_info=True)
            return ()
        available = set(self.available_modalities)
        return tuple(
            modality for modality in parsed.modalities if modality in available
        )
