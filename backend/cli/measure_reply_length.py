"""How long the reply model's answers run, on the questions the brevity test holds.

    docker compose --profile test run --rm --no-deps \
        -v $PWD/backend:/app/backend:ro -v $PWD/prompts:/app/prompts:ro \
        functional-tests python -m backend.cli.measure_reply_length

Prints each answer with its length and the total, so a prompt change can be
recorded as a measurement rather than an impression (the operator's
standard: every design flag says whether it was measured). Run once before
editing prompts/reply/system.md and once after; the numbers go in that
file's header.
"""

from __future__ import annotations

import sys

from backend.core.dependencies import get_llm_client
from backend.tests.functional.test_reply_brevity_behaviour import CASES, _first_sentence, _reply


def main() -> int:
    llm = get_llm_client()
    total = 0
    for question, ceiling, _first in CASES:
        text = _reply(llm, question)
        total += len(text)
        flag = "" if len(text) <= ceiling else f"  OVER by {len(text) - ceiling}"
        print(f"\n=== [{len(text)} chars, ceiling {ceiling}{flag}] {question}", flush=True)
        print(f"first sentence: {_first_sentence(text)}", flush=True)
        print(text, flush=True)
    print(f"\nTOTAL {total} chars over {len(CASES)} questions (ceilings sum {sum(c for _q, c, _f in CASES)})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
