"""Label the stored facts that are standing preferences.

    docker compose exec backend python -m backend.cli.classify_preferences
    docker compose exec backend python -m backend.cli.classify_preferences --apply

New facts are labelled as they are saved (`backend/memory/proposal_agent.py`).
This is for the ones already stored, and it exists because without it the
change does nothing for anybody today: the two memories that would most improve
the operator's recommendations - "prefers quality events with people in their
demographic, not sketchy" and "lives in Courthouse, prefers venues within
commuting distance connected by metro" - were both written months before there
was a label to put on them.

Why a label rather than a better search: measured 2026-08-30, those two sit at
cosine 0.371 and 0.467 from a recommendation-shaped question, while an
unrelated question about Peru sits at 0.499 from the same memory. Signal and
noise overlap, so no threshold divides them, and the deployed reranker divides
them worse - it scored "Ani is a Senior Machine Learning Engineer" as the best
match for "recommend a salsa night". What separates them is kind, not distance.

Dry run unless `--apply`, and it prints every decision either way. Image-derived
entries are never touched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import select

from backend.core.dependencies import get_routing_llm_client
from backend.database.session import AsyncSessionLocal
from backend.memory.purposes import (
    PREFERENCE_PURPOSE,
    PREFERENCE_PURPOSES,
    VISUAL_ANALYSIS_PURPOSE,
)
from backend.models.memory import SemanticMemory

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_preference": {"type": "boolean"},
        "why": {"type": "string", "maxLength": 90},
    },
    "required": ["is_preference", "why"],
    "additionalProperties": False,
}

# The same distinction the proposal agent is asked to make when a fact is first
# saved, worded the same way, so a backfilled row and a new one agree.
_SYSTEM = (
    "You are labelling one remembered fact about a person. Answer whether it is "
    "a standing preference - what they like, avoid, or want, including taste, "
    "tolerance, budget and constraints - as opposed to a plain fact about them "
    'or the world. "Prefers quiet places" and "will drive for something really '
    'good" are preferences. "Owns a Tesla Model 3" and "works at Ven" are not.'
    +
    "A preference is durable: it is true next month as well as today. A statement about how they feel right now or what they want on one particular day - 'feeling tired today and wants something chill', 'is busy this week' - is not a preference, however much it sounds like one, because acting on it in a month would be acting on something that stopped being true."
)


async def _is_preference(llm: Any, content: str) -> tuple[bool, str]:
    answer = await asyncio.to_thread(
        llm.chat,
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": content}],
        120,
        _SCHEMA,
        0.0,
    )
    payload = answer.get("content") if isinstance(answer, dict) else answer
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return False, "unreadable answer"
    if not isinstance(payload, dict):
        return False, "unreadable answer"
    return bool(payload.get("is_preference")), str(payload.get("why") or "")[:90]


async def run(apply: bool) -> int:
    llm = get_routing_llm_client()
    changed = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(SemanticMemory))).scalars().all()
        facts = [row for row in rows if row.purpose != VISUAL_ANALYSIS_PURPOSE]
        print(f"{len(facts)} stored facts to consider\n")
        for memory in facts:
            preference, why = await _is_preference(llm, memory.content)
            already = memory.purpose in PREFERENCE_PURPOSES
            if preference == already:
                continue
            changed += 1
            arrow = "-> preference" if preference else "-> plain fact"
            print(f"{arrow}  {memory.user_id:22} {memory.content[:66]!r}")
            print(f"{'':14}  because: {why}")
            if apply:
                # Only the label moves. The content, its embedding and its
                # history are untouched, so this is reversible by running it
                # again if the judgement is ever improved.
                memory.purpose = PREFERENCE_PURPOSE if preference else "user_explicit"
        if apply and changed:
            await db.commit()
    print(f"\n{changed} label(s) {'changed' if apply else 'would change'}")
    if not apply and changed:
        print("re-run with --apply to write them")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the labels")
    return asyncio.run(run(parser.parse_args(argv).apply))


if __name__ == "__main__":
    sys.exit(main())
