"""Does the reply get to the point, on the real reply model?

The operator, 2026-08-28: "deepseek's responses are way too long. its good
reasoning but some of it is unwanted ... it needs to get to the point
quicker". This sends the production web prompt to the real model with
questions of different shapes and holds the answer to a length ceiling per
shape, a first sentence that answers, and no filler at either end. Ceilings
are generous on purpose - a correct answer that is a little long passes; a
preamble, a closing offer, or an essay does not. Measured before the brevity
block existed: see the numbers in prompts/reply/system.md.
"""

from __future__ import annotations

import re

import pytest

from backend.agents.graph import _build_system_prompt
from backend.config.settings import settings
from backend.tests.functional.semantic import states

pytestmark = pytest.mark.asyncio

_OPENERS = re.compile(
    r"^\s*(great|good|excellent) question|^\s*(sure|certainly|absolutely|of course)\b|"
    r"^\s*i('d| would) be (happy|glad)|^\s*let me\b|^\s*okay,|^\s*ok,",
    re.IGNORECASE,
)
_CLOSERS = re.compile(
    r"let me know if|feel free to|hope (this|that) helps|i hope this|happy to help|"
    r"if you have any (other|more|further) questions|don't hesitate",
    re.IGNORECASE,
)

# (question, ceiling in characters, what the first sentence must do)
#
# Ceilings are per shape, with headroom for the ~250 characters an answer moves
# between runs at temperature 0 on the TP=2 server (measured 2026-08-28: the
# same question came back at 620 and 844, 417 and 651). Before the brevity
# block every one of these but the first ran past its ceiling by 550-870
# characters; that gap, not the last 100 characters, is what this holds.
CASES = [
    ("what's the capital of Peru?", 220, "names Lima as the capital"),
    ("my python script says ModuleNotFoundError: No module named 'requests' - what do I do?", 650, "tells the person to install the requests package (for example with pip)"),
    ("should I use Postgres or SQLite for a personal notes app that runs on one laptop?", 900, "recommends one of the two databases"),
    ("explain what a context window is, for someone who uses chat assistants but doesn't code", 950, "states what a context window is"),
    ("how do I keep a sourdough starter healthy? I keep killing mine.", 1350, "gives the main thing that keeps a starter alive (regular feeding)"),
    ("is it safe to take ibuprofen with coffee?", 850, "answers whether it is generally safe"),
    ("plan me three days in Lisbon in October", 1700, "starts the plan itself rather than asking about preferences or introducing it"),
]


def _reply(llm, question: str) -> str:
    system = _build_system_prompt({})
    result = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": question}],
        settings.MAIN_LLM_MAX_TOKENS,
        None,
        0.0,
    )
    return str(result["content"]).strip()


# The opening as a reader meets it: the first sentence, and the one after it
# when the first is a bare word or two. "SQLite." is the whole recommendation;
# judged alone the judge wanted more words than the point needs (2026-08-28).
def _first_sentence(text: str) -> str:
    flat = " ".join(text.split())
    sentences = re.findall(r".+?[.!?](?:\s|$)", flat) or [flat[:200]]
    opening = sentences[0].strip()
    if len(opening.split()) < 4 and len(sentences) > 1:
        opening = (opening + " " + sentences[1].strip()).strip()
    return opening


@pytest.mark.parametrize("question, ceiling, first", CASES)
async def test_the_answer_leads_and_stops(llm, question: str, ceiling: int, first: str):
    text = _reply(llm, question)
    assert text
    print(f"\n[{len(text)} chars] {question}\n{text}\n")
    assert not _OPENERS.search(text), text[:120]
    assert not _CLOSERS.search(text), text[-160:]
    assert len(text) <= ceiling, (len(text), ceiling, text)
    opening = _first_sentence(text)
    assert states(opening, f"this sentence {first}") is not False, (opening, first)


async def test_the_whole_set_stays_under_its_budget(llm):
    lengths = {question: len(_reply(llm, question)) for question, _c, _f in CASES}
    total = sum(lengths.values())
    print("\n" + "\n".join(f"{n:5d}  {q}" for q, n in lengths.items()) + f"\ntotal {total}")
    # The budget is the sum of the ceilings with a little room: one long answer
    # is tolerable, a habit of them is not.
    budget = int(sum(c for _q, c, _f in CASES) * 1.1)
    assert total <= budget, (total, budget, lengths)
