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
# A schema bound is part of the prompt contract, so a change to one must
# bump this: the tone cache carries scores forward only while the stored
# frame's prompt version matches, and a net loss clamped to zero by the
# old bounds is still cached under "release_tone/2" until the version
# moves and the nightly run re-scores the book.
PROMPT_VERSION = "release_tone/3"

_SYSTEM = render("trading/release_tone")


@dataclass(frozen=True, slots=True)
class ReleaseTone:
    """One release's scores, as the model wrote them, plus the summary.

    The financials are the quarter the release itself reports, so the
    fundamental layer can read the release's own numbers instead of the
    last 10-Q's. A field is None when the release does not state it.
    """

    guidance: float
    demand: float
    pricing: float
    capex: float
    supply_constrained: float
    summary: str
    truncated: bool
    quarter_end: str | None = None
    revenue_usd_m: float | None = None
    eps_usd: float | None = None
    net_income_usd_m: float | None = None
    gross_margin_pct: float | None = None


def _schema() -> dict[str, Any]:
    bounded = {"type": "number", "minimum": -1, "maximum": 1}
    optional = {
        "type": ["number", "null"],
        "minimum": 0,
        "maximum": 1_000_000,
    }
    # A signed amount or margin can be negative: a net loss or a negative
    # gross margin is a real reading, not a defect, and must not clamp to 0
    # or the desk thinks the company broke even. The lower bounds here are
    # generous because the numbers are read from a release, not measured.
    net_income = {"type": ["number", "null"], "minimum": -100_000, "maximum": 1_000_000}
    margin = {"type": ["number", "null"], "minimum": -1000, "maximum": 100}
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
            "quarter_end",
            "revenue_usd_m",
            "eps_usd",
            "net_income_usd_m",
            "gross_margin_pct",
        ],
        "properties": {
            "guidance": bounded,
            "demand": bounded,
            "pricing": bounded,
            "capex": bounded,
            "supply_constrained": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string", "minLength": 5, "maxLength": 240},
            "quarter_end": {"type": ["string", "null"], "format": "date"},
            "revenue_usd_m": optional,
            "eps_usd": {"type": ["number", "null"]},
            "net_income_usd_m": net_income,
            "gross_margin_pct": margin,
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
                quarter_end=payload.get("quarter_end"),
                revenue_usd_m=_opt(payload.get("revenue_usd_m"), 0, 1_000_000),
                eps_usd=_opt(payload.get("eps_usd"), -1000, 100_000),
                net_income_usd_m=_opt(payload.get("net_income_usd_m"), -100_000, 1_000_000),
                gross_margin_pct=_opt(payload.get("gross_margin_pct"), -1000, 100),
            )
        except Exception:
            return None


# A number held inside its documented bounds.
def _clip(value: Any, low: float, high: float) -> float:
    return float(min(high, max(low, float(value))))


# An optional number: None in, None out; otherwise clipped into bounds.
def _opt(value: Any, low: float, high: float) -> float | None:
    if value is None:
        return None
    return float(min(high, max(low, float(value))))
