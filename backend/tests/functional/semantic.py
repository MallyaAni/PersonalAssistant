"""Assert what an answer says, not which words it used.

The functional gate flaked at roughly ten percent, and every observed flake
was the same shape: a positive marker list over sampled prose. A model that
answered "making it impossible to determine the species" failed a test whose
markers were "cannot", "not possible" and "insufficient" - the behaviour the
test exists to require, failed for its phrasing. The test's own comment
records the previous round of exactly this, where "cannot determine" missed
"the fish species cannot be determined"; the list was widened once and
drifted again. A marker list over free prose is keyword routing by another
name, and this repository already retired keyword routing for the same
reason: people rarely use the word you guessed.

So the property is judged semantically, by the routing model on the engine
that enforces JSON schemas, at temperature zero. The judge never generates
prose - the schema admits only {"holds": true|false} - so there is nothing
here for a marker to miss.

What still belongs to plain `in`: exact facts and identities. "90" must
appear when 90 is the answer; an invented species name either appears or
does not. Those checks are not about meaning and do not flake. This helper
is for the assertions that were about meaning all along.
"""

import json

import pytest

from backend.core.dependencies import get_routing_llm_client

_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"holds": {"type": "boolean"}},
    "required": ["holds"],
    "additionalProperties": False,
}

_JUDGE_SYSTEM = (
    "You judge whether a statement about a text is true. Read the text as a "
    "whole; the statement is about what the text says or does, never about "
    "which words it uses. Answer only through the schema."
)


def states(answer: str, statement: str) -> bool:
    """Whether the answer, read as a whole, does what the statement says.

    Judged rather than matched, so a run is not failed by a synonym. The
    routing model is the judge because its engine enforces the schema (the
    property this repository verified before pinning six callers to it) and
    because at temperature zero the same answer gets the same verdict.
    """
    llm = get_routing_llm_client()
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Text:\n{answer}\n\n"
                f"Statement about the text: {statement}\n\n"
                "Is the statement true of the text?"
            ),
        },
    ]
    try:
        result = llm.chat(messages, 1_024, _VERDICT_SCHEMA, 0.0)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(
            f"routing model unreachable for semantic assert: {type(exc).__name__}"
        )
    try:
        return bool(json.loads(str(result.get("content") or "{}")).get("holds"))
    except json.JSONDecodeError:  # pragma: no cover - engine contract violated
        pytest.skip("routing engine returned non-JSON despite schema enforcement")
