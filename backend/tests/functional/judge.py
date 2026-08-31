"""Judging what was actually produced, rather than the string that asked for it.

The operator's point, 2026-08-31, after a run of diagram failures: a test can
put the generated artefact back through a model and ask whether it is what
was wanted. Asserting on the router's subject string is a proxy, and a weak
one - on that thread the subject read "architecture thinking process" and
passed a test whose bar was "does not say try again", while the picture it
produced was a generic software flowchart with no aqueduct in it.

Two judges, one interface, because the two artefact kinds are different
things on the wire and the same thing to a reader:

  * `depicts` sends an image to the vision model on spark2 and asks it.
  * `describes` sends a diagram's source - mermaid text, not pixels - to the
    reply model. Rendering it first would add a browser and a screenshot to
    every assertion and answer the same question.

Both return a verdict and the model's reason, so a failure says what was
actually made and not merely that a boolean was false.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # See it, reason about it, then decide - in that order, because the
        # engine fills fields as they are declared and a verdict written
        # before its reasoning is a guess the reasoning then has to live
        # with. This judge got it wrong on its first run, with `matches`
        # ahead of `why`: it returned false about a diagram whose own `why`
        # said "this matches the expectation". Third time in one day that
        # the order of a schema decided its answer, and the first time it
        # happened inside the thing built to catch it.
        "seen": {"type": "string", "maxLength": 400},
        "why": {"type": "string", "maxLength": 300},
        "matches": {"type": "boolean"},
    },
    "required": ["seen", "why", "matches"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether the artefact is what was wanted, and what the judge saw."""

    matches: bool
    seen: str
    why: str

    def __bool__(self) -> bool:
        return self.matches

    def __str__(self) -> str:
        return f"{'matches' if self.matches else 'does not match'}: saw {self.seen!r} ({self.why})"


def _asked(expectation: str) -> str:
    return (
        "You are checking whether something a program produced is what was "
        "wanted. First write what is actually there, plainly and without "
        "guessing at intent. Then say whether it matches this expectation, "
        "and why.\n\nExpectation: " + expectation.strip()
    )


# Whether a diagram's source is about what was wanted. The source is text,
# so this is the reply model rather than the vision model.
async def describes(llm: Any, source: str, expectation: str) -> Verdict:
    import asyncio

    answer = await asyncio.to_thread(
        llm.chat,
        [
            {"role": "system", "content": _asked(expectation)},
            {"role": "user", "content": f"The diagram source:\n\n{str(source)[:4000]}"},
        ],
        400,
        _VERDICT_SCHEMA,
        0.0,
    )
    return _read(answer["content"])


# Whether an image shows what was wanted, asked of the vision model.
async def depicts(
    vision: Any, content: bytes, expectation: str, mime_type: str = "image/png"
) -> Verdict:
    analysis = await vision.analyze(_asked(expectation), content, mime_type)
    return _read(getattr(analysis, "description", "") or getattr(analysis, "text", ""))


def _read(raw: object) -> Verdict:
    text = str(raw or "").strip()
    try:
        decided = json.loads(text)
    except ValueError:
        # A vision model asked for prose returns prose. Fall back to reading
        # it rather than failing the test for the judge's formatting.
        return Verdict(matches=False, seen=text[:400], why="judge did not answer in JSON")
    return Verdict(
        matches=bool(decided.get("matches")),
        seen=str(decided.get("seen") or "")[:400],
        why=str(decided.get("why") or "")[:300],
    )
