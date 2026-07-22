import asyncio
import logging
from abc import ABC, abstractmethod

from backend.core.llm import LLMClient

logger = logging.getLogger(__name__)

# Bounded instruction returning a single token. The model is asked only for a
# judgement about the question; it never selects a tool, so a compromised or
# confused answer can at worst cause one unnecessary search.
_INSTRUCTION = (
    "You decide whether a question should be answered using a web search.\n"
    "Answer YES if the correct answer could have changed recently, depends on "
    "current events, or concerns anything that happened close to now. Questions "
    "about records, holders of a role, releases, prices, counts, schedules and "
    "'most recent' anything are YES even when they sound historical, because "
    "the answer may have moved since you were trained.\n"
    "Answer NO only when the answer is fixed forever: mathematics, definitions, "
    "grammar, code, creative writing, or long-settled history.\n"
    "When unsure, answer YES.\n"
    "Reply with exactly one word.\n\n"
    # Few-shot examples chosen for the hard boundary: superficially historical
    # questions whose answers still move, against genuinely fixed ones.
    "Question: What is the capital of France?\nAnswer: NO\n\n"
    "Question: When did OpenAI release GPT-5?\nAnswer: YES\n\n"
    "Question: Write a haiku about rain.\nAnswer: NO\n\n"
    "Question: Who holds the world record in the marathon?\nAnswer: YES\n\n"
    "Question: What is the derivative of x squared?\nAnswer: NO\n\n"
    "Question: When did Taylor Swift win her first Golden Globe?\nAnswer: YES\n\n"
    "Question: Explain how a b-tree works.\nAnswer: NO\n\n"
    "Question: How many countries use the euro?\nAnswer: YES\n\n"
    "Question: {query}\nAnswer:"
)


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
        prompt = _INSTRUCTION.format(query=query.strip())
        try:
            # The client is synchronous, so keep it off the event loop.
            raw = await asyncio.to_thread(
                self.llm.generate_text,
                prompt,
                self.max_tokens,
            )
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
