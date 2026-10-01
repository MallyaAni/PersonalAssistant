"""Read eight anonymised quarters of filed facts and call the next quarter.

The A2 study's model step (`docs/research/llm-statements-plan-2026-10-01.md`):
the model reads one standardised statement block built by
`backend.market.statements` — numbers only, labelled Q1..Q8, no company,
no dates — and answers whether net income in the next quarter will be
above the same quarter a year earlier, with a probability and a
three-sentence rationale. The probability less one half becomes a
point-in-time stance on the book.

The boundary is the tone reader's: the model reads one block and reports
what it concludes from it, in a schema with bounded numbers. It never
sees a name, a date, a price or another company's block. The block is
anonymised so that memorised facts have as little to hold on to as
possible; this limits the model's inputs but does not rule out a series
being recognised, which is why the plan says the post-cutoff window
decides.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from backend.core.interfaces import TextWriter
from backend.core.prompts import render

# The prompt, its schema and its bounds are one contract: a change to any
# of them bumps this, and the store starts the name over under the new
# version (a stored frame is compatible only when its version matches).
PROMPT_VERSION = "statements/1"
UP = "up"
DOWN = "down"
MAX_RATIONALE = 600

_SYSTEM = render("trading/statement_reader")


@dataclass(frozen=True, slots=True)
class StatementCall:
    """One block's answer, as the model wrote it."""

    direction: str
    probability: float
    rationale: str

    # The stance the study scores: the probability less one half.
    @property
    def stance(self) -> float:
        return self.probability - 0.5

    # Whether the stated direction sits on the probability's side of 0.5.
    @property
    def consistent(self) -> bool:
        return (self.direction == UP) == (self.probability >= 0.5)


# The response schema: a direction, a probability on [0, 1] and a bounded
# rationale, every field required (an optional field is one the model
# skips).
def schema() -> dict[str, Any]:
    """Return the JSON schema the model's answer must fit."""
    return {
        "title": "StatementCall",
        "type": "object",
        "additionalProperties": False,
        "required": ["direction", "probability", "rationale"],
        "properties": {
            "direction": {"type": "string", "enum": [UP, DOWN]},
            "probability": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {
                "type": "string",
                "minLength": 20,
                "maxLength": MAX_RATIONALE,
            },
        },
    }


class StatementReader:
    """Read one statement block and call the next quarter's direction."""

    # The same narrow inference contract every agent prompt takes: a missing
    # runtime degrades to None rather than failing the caller.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 500) -> None:
        self.writer = writer
        self.max_tokens = max_tokens

    # Call one block, or return None when the runtime is away or the answer
    # does not fit the schema.
    async def call(self, block: str) -> StatementCall | None:
        """Return the StatementCall for a block, or None."""
        return await asyncio.to_thread(self.call_sync, block)

    # The synchronous form, for a long batch run that manages its own threads.
    def call_sync(self, block: str) -> StatementCall | None:
        """Return the StatementCall for a block, or None."""
        if self.writer is None or not block.strip():
            return None
        try:
            result = self.writer.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": block},
                ],
                self.max_tokens,
                schema(),
                # Greedy: the study registers one deterministic reading per
                # block; the store keeps the first answer by quarter.
                0.0,
            )
            payload = json.loads(result["content"])
            direction = str(payload["direction"]).strip().lower()
            if direction not in (UP, DOWN):
                return None
            probability = float(payload["probability"])
            if not 0.0 <= probability <= 1.0:
                return None
            return StatementCall(
                direction=direction,
                probability=probability,
                rationale=str(payload["rationale"]).strip()[:MAX_RATIONALE],
            )
        except Exception:
            return None


__all__ = [
    "DOWN",
    "MAX_RATIONALE",
    "PROMPT_VERSION",
    "UP",
    "StatementCall",
    "StatementReader",
    "schema",
]
