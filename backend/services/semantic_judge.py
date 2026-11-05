"""Ask a reasoning model whether an answer does what a statement says.

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

Why the reply model and not the routing model: the routing client runs with
reasoning off (ROUTING_LLM_REASONING_EFFORT=none) because it only has to pick
a label. Judging entailment is not label-picking. Measured on the deployed
runtime 2026-11-04: the routing client answered false to six plainly true
statements - a forecast with Saturday and Sunday, current console prices, a
store's Sunday hours, a game result with the NFL link, and "I'll ask you
Friday" for a check-in - and failed the post-deploy sweep. The reply client
has thinking on, and the same statements come back true. The judge is a test
and sweep tool, not a chat path, so its extra seconds are paid only there.

The question is passed in when the caller has it: a statement like "gives a
forecast for Washington, DC" asks about something the reply does not always
name, and the question is what makes the place part of the answer. Statements
are also written to allow alternatives ("from live sources or says it could
not check"); the prompt says one supported alternative is enough, because a
judge that requires every clause failed every disjunctive journey.
"""

from __future__ import annotations

import json
from typing import Any

from backend.core.dependencies import get_reply_llm_client

# The only shape the judge may answer in. The engine enforces it.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"holds": {"type": "boolean"}},
    "required": ["holds"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = (
    "You check whether a statement is true of a reply to a person's question. "
    "The statement is true when the reply supports it. A statement that offers "
    "alternatives joined by 'or' is true when the reply supports any one of "
    "them. The statement is false only when the reply contradicts it or does "
    "not support it. Judge what the reply says, not the words it uses. Answer "
    "only through the schema."
)

# Thinking runs before the verdict, and 1,024 tokens was consumed by reasoning
# on one measured call, leaving no message output at all. The cap is a ceiling,
# not a target, so the larger budget costs nothing on the calls that answer
# quickly.
JUDGE_MAX_TOKENS = 4_096


def _ask(llm, messages: list[dict[str, str]]) -> dict[str, Any]:
    """One schema-constrained verdict, retrying a message-less choice once."""
    try:
        return llm.chat(messages, JUDGE_MAX_TOKENS, VERDICT_SCHEMA, 0.0)
    except ValueError as exc:
        # The provider occasionally returns a choice with no message after a
        # long reasoning block. One retry separates that from an outage.
        if "message output" not in str(exc):
            raise
        return llm.chat(messages, JUDGE_MAX_TOKENS, VERDICT_SCHEMA, 0.0)


# One verdict, raised rather than skipped: the caller decides whether an
# unreachable judge is a skip (tests) or a failure (the sweep).
def judge_answer(answer: str, statement: str, question: str | None = None) -> bool:
    llm = get_reply_llm_client()
    parts = []
    if question:
        parts.append(f"Question: {question}")
    parts.append(f"Reply:\n{answer}")
    parts.append(f"Statement about the reply: {statement}")
    parts.append("Is the statement true of the reply?")
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    result = _ask(llm, messages)
    try:
        payload = json.loads(str(result.get("content") or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "the judge engine returned non-JSON despite schema enforcement"
        ) from exc
    if "holds" not in payload:
        raise ValueError("the judge engine returned no verdict")
    return bool(payload["holds"])
