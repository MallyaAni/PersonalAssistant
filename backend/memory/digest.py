"""Compressing a stretch of conversation, with truncation underneath it.

The digest that later turns read used to be built by appending each interval's
verbatim exchanges to the digest before it. It never compressed and never
stopped growing, and the latest one is injected into every prompt. That is
fixed: `coordinator._digest` now enforces a ceiling.

A ceiling is not compression, though. Truncation keeps the newest words and
loses the oldest meaning, which is the wrong thing to lose from a conversation
someone has been having for an hour. So this asks the reply model to compress
instead, and falls back to that truncation whenever it cannot.

The ordering matters and is deliberate: the bound was built first and shipped
on its own, so this can fail - model down, timeout, empty answer - without the
old defect coming back. A summariser layered onto an unbounded digest would
have turned every outage into unbounded growth again.

**A bad summary is worse than no summary.** Truncation drops material honestly;
a weak model invents a tidy narrative, and the invention then enters every
later prompt indistinguishable from something the user actually said. That is
why this runs on the reply model rather than the small one, why the prompt
spends most of its words forbidding invention, and why an answer that comes
back suspiciously long is rejected rather than trusted.
"""

import logging
from typing import Any, Protocol

from backend.config.settings import settings
from backend.core.prompts import render

logger = logging.getLogger(__name__)

# The most of a previous digest that is carried into the compression prompt.
#
# A digest written after the ceiling shipped is a few thousand characters, but
# rows saved by the unbounded implementation this replaced can be arbitrarily
# large, and feeding one in whole would blow the prompt on exactly the
# conversations that most need compressing. The tail is the newer half of an
# append-only digest, so it is the part worth keeping.
_MAX_PREVIOUS_CHARS = 8_000


class _Summariser(Protocol):
    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str: ...


def _exchanges(turns: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- User: {str(turn.get('query', ''))[:1_000]}\n"
        f"  Assistant: {str(turn.get('response', ''))[:1_000]}"
        for turn in turns
    )


# Compress, or return None and let the caller keep its bounded truncation.
#
# Every failure path returns None rather than raising. This runs after a reply
# has already been sent, so an exception here would fail a turn the user has
# already been answered on - the worst possible trade for a background nicety.
def summarise(
    client: _Summariser | None,
    previous: str,
    turns: list[dict[str, Any]],
) -> str | None:
    if client is None or not settings.MEMORY_DIGEST_MODEL_ENABLED or not turns:
        return None

    prompt = render(
        "memory/digest",
        previous=(
            "Notes so far, which your new notes replace:\n"
            f"{previous[-_MAX_PREVIOUS_CHARS:]}\n\n"
            if previous.strip()
            else ""
        ),
        exchanges=_exchanges(turns),
        max_words=settings.MEMORY_DIGEST_MAX_WORDS,
    )
    try:
        written = client.generate_text(
            prompt, max_tokens=settings.MEMORY_DIGEST_MAX_TOKENS
        ).strip()
    except Exception:  # noqa: BLE001 - a background digest must never fail a turn
        logger.warning("Conversation digest failed; keeping truncation", exc_info=True)
        return None

    if not written:
        # A reasoning model that spends its whole budget thinking returns an
        # empty string rather than a short answer. That cost a reply in six
        # earlier today, and here it must not silently become an empty digest.
        logger.warning("Conversation digest came back empty; keeping truncation")
        return None

    # Compression that did not compress is a signal the instruction was ignored,
    # and an over-long digest is exactly the defect this replaces. Truncation is
    # the safer answer than trusting it.
    allowed = settings.MEMORY_DIGEST_MAX_WORDS * 2
    if len(written.split()) > allowed:
        logger.warning(
            "Conversation digest ran to %d words against a %d limit; "
            "keeping truncation",
            len(written.split()),
            settings.MEMORY_DIGEST_MAX_WORDS,
        )
        return None
    return written
