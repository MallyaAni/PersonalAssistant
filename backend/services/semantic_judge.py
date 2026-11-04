"""Ask the routing model whether an answer does what a statement says.

Shared by two callers that must agree on the verdict: the functional tests,
which turn an unreachable judge into a skip, and the live journey sweep,
which turns it into a failed journey. The judge lives here rather than in
`backend/tests/functional/semantic.py` because the sweep runs inside the
runtime container, which does not install pytest - importing the test-side
helper there raised ModuleNotFoundError, and every statement was reported
"judge unavailable" while the replies themselves were fine (deploy #2026-11-04).

The verdict is schema-constrained to {"holds": true|false} at temperature
zero, so the judge never writes prose and the same answer gets the same
verdict. Exact facts still belong to plain `in` checks in the callers.
"""

from __future__ import annotations

import json
from typing import Any

from backend.core.dependencies import get_routing_llm_client

# The only shape the judge may answer in. The routing engine enforces it.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"holds": {"type": "boolean"}},
    "required": ["holds"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = (
    "You judge whether a statement about a text is true. Read the text as a "
    "whole; the statement is about what the text says or does, never about "
    "which words it uses. Answer only through the schema."
)


# One verdict, raised rather than skipped: the caller decides whether an
# unreachable judge is a skip (tests) or a failure (the sweep).
def judge_answer(answer: str, statement: str) -> bool:
    llm = get_routing_llm_client()
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Text:\n{answer}\n\n"
                f"Statement about the text: {statement}\n\n"
                "Is the statement true of the text?"
            ),
        },
    ]
    result = llm.chat(messages, 1_024, VERDICT_SCHEMA, 0.0)
    try:
        payload = json.loads(str(result.get("content") or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "the routing engine returned non-JSON despite schema enforcement"
        ) from exc
    if "holds" not in payload:
        raise ValueError("the routing engine returned no verdict")
    return bool(payload["holds"])
