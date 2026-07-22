import asyncio
import logging
from abc import ABC, abstractmethod

from backend.core.llm import LLMClient

logger = logging.getLogger(__name__)

# Bounded instruction returning a single token. The model is asked only for a
# judgement about the question; it never selects a tool, so a compromised or
# confused answer can at worst cause one unnecessary search.
_SYSTEM = (
    "Classify whether a question needs a web search.\n"
    "YES means the correct answer can change over time: current events, "
    "prices, weather, scores, schedules, releases, statistics, or whoever "
    "currently holds a role, title or record.\n"
    "NO means the answer is already fixed and cannot change: past events with "
    "a settled outcome, mathematics, definitions, grammar, code, explanations "
    "and creative writing.\n"
    "Reply with one word: YES or NO."
)

# Few-shot examples as real conversation turns. A completion-style prompt blob
# is reinterpreted by a chat template, and a small model then answers
# conversationally instead of classifying; structured turns keep the format
# unambiguous for any chat model.
_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("What is the capital of France?", "NO"),
    ("When did OpenAI release GPT-5?", "YES"),
    ("Write a haiku about rain.", "NO"),
    ("Who holds the world record in the marathon?", "YES"),
    ("What is the derivative of x squared?", "NO"),
    ("When did Taylor Swift win her first Golden Globe?", "YES"),
    ("Explain how a b-tree works.", "NO"),
    ("How many countries use the euro?", "YES"),
)


# Build the classification conversation for one query.
def _build_messages(query: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _SYSTEM}]
    for example, answer in _EXAMPLES:
        messages.append({"role": "user", "content": example})
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": query.strip()})
    return messages


class QueryFreshnessClassifier(ABC):
    """Judges whether one question depends on post-training information."""

    # Return True or False, or None when no usable judgement was produced.
    @abstractmethod
    async def requires_current_information(self, query: str) -> bool | None: ...


class LMStudioFreshnessClassifier(QueryFreshnessClassifier):
    """Local single-token classifier backed by the configured chat model."""

    # Bound the reply hard: only the first word is ever needed.
    def __init__(self, llm: LLMClient, max_tokens: int = 4) -> None:
        self.llm = llm
        self.max_tokens = max_tokens

    # Ask for one word and accept only an unambiguous answer.
    async def requires_current_information(self, query: str) -> bool | None:
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
            logger.warning("Freshness classifier call failed", exc_info=True)
            return None

        answer = (raw or "").strip().upper()
        if answer.startswith("YES"):
            return True
        if answer.startswith("NO"):
            return False
        logger.info("Freshness classifier returned no usable answer: %r", raw[:40])
        return None
