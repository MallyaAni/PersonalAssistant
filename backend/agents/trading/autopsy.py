"""The trading agent's autopsy: what a person's own history keeps doing.

This is the first capability of a personal trading analyst: it reads the
person's own records and names the behaviours that repeat, what they have
cost, and what to do about them. It exists because the person asked for a
system that could "deep-analyze my mistakes in trading and come up with
better plans" — and the honest first step of that is reading what actually
happened rather than theorising about trading.

The boundary is the same one every analyst prompt here keeps: the model names
patterns and a plan, and nothing numeric is invented. A cost is only stated
when a number is actually present in the passages, because a confident
invented figure in a post-mortem is worse than no figure — it becomes a
memory of a loss that never happened. The passages come from the person's
own uploaded documents (knowledge chunks), so this package depends on
nothing but the shared model-call mechanism.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from backend.core.interfaces import TextWriter
from backend.core.prompts import render

# The bounded number of passages handed to one autopsy. Enough to see a
# pattern, small enough that the model can hold every one in view at once.
MAX_PASSAGES = 12

# How much prose the model may write in one section.
MAX_PATTERN_CHARS = 400
MAX_COST_CHARS = 300
MAX_PLAN_CHARS = 200

_SYSTEM = render("trading/autopsy", MAX_PASSAGES=MAX_PASSAGES)


@dataclass(frozen=True, slots=True)
class AutopsyResult:
    """One autopsy, as the model wrote it, with its pieces held separately."""

    patterns: tuple[dict[str, str], ...]
    costs: tuple[dict[str, str], ...]
    plan: dict[str, list[str]]
    unknowns: tuple[str, ...]


def _schema() -> dict[str, Any]:
    return {
        "title": "Autopsy",
        "type": "object",
        "additionalProperties": False,
        "required": ["patterns", "costs", "plan", "unknowns"],
        "properties": {
            "patterns": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["behaviour", "evidence"],
                    "properties": {
                        "behaviour": {
                            "type": "string",
                            "minLength": 10,
                            "maxLength": MAX_PATTERN_CHARS,
                        },
                        "evidence": {
                            "type": "string",
                            "minLength": 5,
                            "maxLength": MAX_PATTERN_CHARS,
                        },
                    },
                },
            },
            "costs": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["what", "amount", "source"],
                    "properties": {
                        "what": {
                            "type": "string",
                            "minLength": 5,
                            "maxLength": MAX_COST_CHARS,
                        },
                        # A stated number from the passage, or exactly the
                        # words "not stated" — never an invented figure.
                        "amount": {
                            "type": "string",
                            "minLength": 3,
                            "maxLength": 100,
                        },
                        "source": {
                            "type": "string",
                            "minLength": 5,
                            "maxLength": MAX_COST_CHARS,
                        },
                    },
                },
            },
            "plan": {
                "type": "object",
                "additionalProperties": False,
                "required": ["stop", "start", "keep"],
                "properties": {
                    "stop": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {"type": "string", "maxLength": MAX_PLAN_CHARS},
                    },
                    "start": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {"type": "string", "maxLength": MAX_PLAN_CHARS},
                    },
                    "keep": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {"type": "string", "maxLength": MAX_PLAN_CHARS},
                    },
                },
            },
            "unknowns": {
                "type": "array",
                "maxItems": 6,
                "items": {"type": "string", "maxLength": 200},
            },
        },
    }


class TradeAutopsy:
    """Read the person's own trade-history passages and write the post-mortem."""

    # The same narrow inference contract every other agent prompt takes, so a
    # missing runtime degrades to None rather than failing the turn.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 1024) -> None:
        self.writer = writer
        self.max_tokens = max_tokens

    # Ask for the whole autopsy, or return None when the runtime is away or the
    # answer does not fit the schema. Every failure lands here; a caller that
    # gets None falls back to what it can say without the model.
    async def analyze(self, passages: list[dict[str, Any]]) -> AutopsyResult | None:
        if self.writer is None or not passages:
            return None
        content = _render_passages(passages)
        try:
            result = await asyncio.to_thread(
                self.writer.chat,
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": content},
                ],
                self.max_tokens,
                _schema(),
                # Greedy. The same history must produce the same post-mortem,
                # or a re-run reads as a different analyst with a different
                # memory of what happened.
                0.0,
            )
            payload = json.loads(result["content"])
        except Exception:
            return None
        try:
            return AutopsyResult(
                patterns=tuple(
                    {
                        "behaviour": str(item["behaviour"]),
                        "evidence": str(item["evidence"]),
                    }
                    for item in payload["patterns"]
                ),
                costs=tuple(
                    {
                        "what": str(item["what"]),
                        "amount": str(item["amount"]),
                        "source": str(item["source"]),
                    }
                    for item in payload["costs"]
                ),
                plan={
                    "stop": [str(x) for x in payload["plan"].get("stop", [])],
                    "start": [str(x) for x in payload["plan"].get("start", [])],
                    "keep": [str(x) for x in payload["plan"].get("keep", [])],
                },
                unknowns=tuple(str(x) for x in payload.get("unknowns", [])),
            )
        except Exception:
            return None


# The passages as the analyst sees them: labelled, numbered, and nothing else.
# Each one is a chunk from the person's own document, so the analyst reads
# what was actually written and cannot reach past it.
def _render_passages(passages: list[dict[str, Any]]) -> str:
    lines = []
    for index, chunk in enumerate(passages, start=1):
        title = str(chunk.get("document", {}).get("title") or "a document")
        content = str(chunk.get("content") or "").strip()
        lines.append(f"{index}. From \"{title}\":\n{content}")
    return "\n\n".join(lines)
