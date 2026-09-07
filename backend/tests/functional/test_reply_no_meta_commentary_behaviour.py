"""Does a repeated request get answered, not commented on?

A group's "try again" (2026-09-07) was answered with commentary on the
repetition instead of a redo, on a loop that lasted four turns. This pins the
reply model's own side of that: shown a prior answer and the same request
again, it must answer the request and never remark on the conversation's own
mechanics - "again?", "as I said", "you keep asking" - which are commentary on
the conversation itself rather than the answer. The assertion is on the
absence of meta-commentary and the presence of an answer, not on wording, so a
reworded prompt survives.
"""

from __future__ import annotations

import re

import pytest

from backend.agents.graph import _build_system_prompt
from backend.config.settings import settings

pytestmark = pytest.mark.asyncio

# Commentary on the conversation itself, as opposed to the answer. "try again"
# in the model's own voice when it restates the retry is tolerated; a remark
# that the same thing was asked, or that it has answered before, is not.
_META = re.compile(
    r"again\?|as i (said|mentioned)|we('| ha)ve been over|we went over|"
    r"you (already )?(asked|said) (this|that)|i already (told|answered|said)|"
    r"i told you|you keep asking|you keep saying",
    re.IGNORECASE,
)


def _reply(llm, user: str) -> str:
    system = _build_system_prompt({})
    result = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        settings.MAIN_LLM_MAX_TOKENS,
        None,
        0.0,
    )
    return str(result["content"]).strip()


async def test_a_repeated_request_is_answered_not_commented_on(llm):
    # The shape of a retry: the assistant has just answered and the person
    # asks for the same thing again.
    user = (
        'Earlier you told me: "Nothing I can date from what came back."\n\n'
        "try again - what's going on in the area this weekend?"
    )
    text = _reply(llm, user)
    assert text
    print(f"\n{text}\n")
    assert not _META.search(text), text[:300]
    # It must actually engage with the request, not bounce it back: at least a
    # substantive sentence (a bare "again?" or a request for clarification is a
    # failure of the same kind).
    assert len(text.split()) >= 10, text


async def test_an_offer_repeatedly_declined_is_not_remarked_on(llm):
    user = (
        'You suggested: "Want me to pull options for Saturday?"\n\n'
        "no, not that - just the bachata one"
    )
    text = _reply(llm, user)
    assert text
    print(f"\n{text}\n")
    assert not _META.search(text), text[:300]
