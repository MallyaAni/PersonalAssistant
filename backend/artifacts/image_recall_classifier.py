import asyncio
import logging
from abc import ABC, abstractmethod

from backend.core.llm import LLMClient

logger = logging.getLogger(__name__)

# Bounded instruction returning a single token. The model only judges intent; it
# never selects a tool, so a confused answer can at worst cause one unnecessary
# image lookup that the retrieval policy then finds nothing for.
_SYSTEM = (
    "Classify whether the user is asking to see a specific image they already "
    "have - one they previously generated or uploaded.\n"
    "YES means they want to view or find an existing image: 'show me the car I "
    "made', 'pull up that logo', 'where's the sketch from yesterday'.\n"
    "NO means anything else, including asking to CREATE a new image ('draw a "
    "cat', 'make me a poster'), or a message that is not about a stored image at "
    "all.\n"
    "Reply with one word: YES or NO."
)

# Few-shot turns keep the format unambiguous for a small chat model.
_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("show me the car I generated earlier", "YES"),
    ("pull up that logo we worked on", "YES"),
    ("what did the sunset picture I made look like", "YES"),
    ("draw me a red sports car", "NO"),
    ("generate an image of a mountain", "NO"),
    ("my name is Ani", "NO"),
    ("what is the capital of France", "NO"),
    ("bring back the diagram from our chat yesterday", "YES"),
)


def _build_messages(query: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _SYSTEM}]
    for example, answer in _EXAMPLES:
        messages.append({"role": "user", "content": example})
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": query.strip()})
    return messages


class ImageRecallClassifier(ABC):
    """Judges whether a message asks to see a specific stored image."""

    # Return True or False, or None when no usable judgement was produced.
    @abstractmethod
    async def references_stored_image(self, query: str) -> bool | None: ...


class LMStudioImageRecallClassifier(ImageRecallClassifier):
    """Local single-token classifier backed by the configured model."""

    def __init__(self, llm: LLMClient, max_tokens: int = 4) -> None:
        self.llm = llm
        self.max_tokens = max_tokens

    async def references_stored_image(self, query: str) -> bool | None:
        try:
            # The client is synchronous, so keep it off the event loop.
            result = await asyncio.to_thread(
                self.llm.chat,
                _build_messages(query),
                self.max_tokens,
            )
            raw = str(result.get("content", ""))
        except Exception:
            # An outage must not decide routing; the caller falls back.
            logger.warning("Image-recall classifier call failed", exc_info=True)
            return None

        answer = (raw or "").strip().upper()
        if answer.startswith("YES"):
            return True
        if answer.startswith("NO"):
            return False
        logger.info("Image-recall classifier gave no usable answer: %r", raw[:40])
        return None
