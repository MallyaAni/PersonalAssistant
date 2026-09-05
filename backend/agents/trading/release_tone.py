"""Score an earnings press release for what the company says about its future.

The market research pipeline measured every price-and-volume model at zero
and found its first real signal in filings. This is the trading agent's
language capability on top of that: the local model reads each results
release and scores what the company itself states about its outlook,
demand, pricing, capital spending and supply. Each score is dated by the
release's acceptance time, so the pipeline can use it exactly as the
market could have.

The boundary is the same as the autopsy's: the model reads one document
and reports what it states, in a schema with bounded numbers. It never
sees a price, a ticker's history, or another company's release, so a score
cannot be a guess about the stock; it can only be a reading of the text.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from backend.core.interfaces import TextWriter
from backend.core.prompts import render

# Releases run to tens of thousands of characters, mostly tables. The
# outlook is in the prose at the top, so the text is cut here and the cut
# is recorded with the score.
MAX_CHARS = 24_000
PROMPT_VERSION = "release_tone/1"

_SYSTEM = render("trading/release_tone")


@dataclass(frozen=True, slots=True)
class ReleaseTone:
    """One release's scores, as the model wrote them, plus the summary."""

    guidance: float
    demand: float
    pricing: float
    capex: float
    supply_constrained: float
    summary: str
    truncated: bool


def _schema() -> dict[str, Any]:
    bounded = {"type": "number", "minimum": -1, "maximum": 1}
    return {
        "title": "ReleaseTone",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "guidance",
            "demand",
            "pricing",
            "capex",
            "supply_constrained",
            "summary",
        ],
        "properties": {
            "guidance": bounded,
            "demand": bounded,
            "pricing": bounded,
            "capex": bounded,
            "supply_constrained": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string", "minLength": 5, "maxLength": 240},
        },
    }


class ReleaseToneReader:
    """Read one press release and score what it states about the future."""

    # The same narrow inference contract every agent prompt takes: a missing
    # runtime degrades to None rather than failing the caller.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 300) -> None:
        self.writer = writer
        self.max_tokens = max_tokens

    # Score one release, or return None when the runtime is away or the
    # answer does not fit the schema.
    async def score(self, text: str) -> ReleaseTone | None:
        """Return the ReleaseTone for a release's plain text, or None."""
        return await asyncio.to_thread(self.score_sync, text)

    # The synchronous form, for a long batch run that manages its own threads.
    def score_sync(self, text: str) -> ReleaseTone | None:
        """Return the ReleaseTone for a release's plain text, or None."""
        if self.writer is None or not text.strip():
            return None
        truncated = len(text) > MAX_CHARS
        body = text[:MAX_CHARS]
        try:
            result = self.writer.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": body},
                ],
                self.max_tokens,
                _schema(),
                # Greedy: the same release must score the same every time,
                # or a feature built from it is noise about the model.
                0.0,
            )
            payload = json.loads(result["content"])
            return ReleaseTone(
                guidance=_clip(payload["guidance"], -1, 1),
                demand=_clip(payload["demand"], -1, 1),
                pricing=_clip(payload["pricing"], -1, 1),
                capex=_clip(payload["capex"], -1, 1),
                supply_constrained=_clip(payload["supply_constrained"], 0, 1),
                summary=str(payload["summary"])[:240],
                truncated=truncated,
            )
        except Exception:
            return None


# A number held inside its documented bounds.
def _clip(value: Any, low: float, high: float) -> float:
    return float(min(high, max(low, float(value))))
