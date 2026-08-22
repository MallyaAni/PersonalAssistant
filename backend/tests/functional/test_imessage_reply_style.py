"""Does the reply actually read like a text when it lands in one?

The reply model writes for the web UI - markdown, headings, thoroughness -
and delivered to a phone that arrived as asterisks around good answers.
The channel style block tells it where its words land; these send the real
appended prompt to the real model and assert the answer changed shape, not
just that a string was concatenated. The web default is pinned byte-level:
no channel means no block, so browser replies cannot drift from here.
"""

import re

import pytest

from backend.agents.graph import _build_system_prompt

pytestmark = pytest.mark.asyncio

_BULLET = re.compile(r"^\s*[-*•]\s+\S", re.MULTILINE)
_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)

# A question that reliably tempts the default register into a bulleted
# listicle, which is exactly what a text message must not be.
_LISTY_QUESTION = (
    "what are some good ways to keep a sourdough starter healthy? I keep killing mine."
)


def test_the_web_prompt_is_unchanged_when_no_channel_is_set():
    assert _build_system_prompt({}) == _build_system_prompt({"channel": ""})
    assert "text message" not in _build_system_prompt({})


async def test_an_imessage_reply_reads_like_a_text_not_a_page(llm):
    system = _build_system_prompt({"channel": "imessage"})

    result = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": _LISTY_QUESTION},
        ],
        400,
        None,
        0.0,
    )
    text = str(result["content"])

    assert text.strip(), "the style block must not suppress the answer"
    assert not _HEADING.search(text), text
    assert not _BULLET.search(text), text
    assert "**" not in text, text
    # Short enough to read as a text or two, not a wall. The prompt asks for
    # one or two short paragraphs; triple that is the failure line.
    assert len(text) <= 1_200, (len(text), text)
