"""The desk's brief in words: one name, its grade, and why.

Every number the desk has for a name is already measured; this hands them
to the local model and asks for the explanation an operator would read
before acting. The boundary is the same as the release reader's: the
model sees only the desk's own evidence for one name, in a schema with
bounded fields, and the stance it returns must follow the grade it was
given. It cannot see a price series, so it cannot forecast one.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from backend.agents.trading.desk.grading import A_PLUS, A, B
from backend.core.interfaces import TextWriter
from backend.core.prompts import render

PROMPT_VERSION = "desk_brief/1"
_SYSTEM = render("trading/desk_brief")
_READ_SYSTEM = render("trading/desk_read")
OWN = "own"
WAIT = "wait"
AVOID = "avoid"
STANCES = (OWN, WAIT, AVOID)

# The plain words a read uses for each analyst, so a read that skips an
# analyst fails rather than passing on its own length.
_ANALYST_WORDS: dict[str, tuple[str, ...]] = {
    "fundamental": ("revenue", "sales", "growth", "grow", "margin", "earnings", "eps"),
    "technical": (
        "trend",
        "ema",
        "average",
        "stack",
        "momentum",
        "range",
        "support",
        "resistance",
        "distance",
    ),
    "sentiment": ("guidance", "tone", "demand", "pricing", "capex"),
    "value": ("value", "valuation", "price", "pe", "p/e"),
    "rotation": ("rotation", "sector", "theme", "leader"),
}
_ANALYST_LINE = re.compile(
    r"^(fundamental|technical|sentiment|value|rotation) analyst: "
    r"stance [+-]?\d+; (.*)$",
    re.MULTILINE,
)


# What a read must still mention to count as complete: each analyst that
# has data, and both levels with a distance. A gap means the model skipped
# a trigger, which is exactly what the read is forbidden to do.
def _coverage_gaps(text: str, read: str) -> list[str]:
    """Return the analysts and levels the read left out."""
    gaps: list[str] = []
    low = read.lower()
    for match in _ANALYST_LINE.finditer(text):
        analyst, cited = match.group(1), match.group(2)
        if cited.strip() in ("no data for this name",):
            continue
        if not any(word in low for word in _ANALYST_WORDS.get(analyst, ())):
            gaps.append(f"the {analyst} analyst's readings")
    for side in ("support", "resistance"):
        if re.search(rf"{side}.{{0,80}}\d+(?:\.\d+)?\s*%", low) is None:
            gaps.append(f"the nearest {side} and how far it sits")
    return gaps


@dataclass(frozen=True, slots=True)
class DeskBrief:
    """What the model wrote for one name."""

    stance: str
    verdict: str
    reasoning: str
    risks: str
    watch: str


# The stance the grade implies; the model must agree with it.
def stance_for(grade: str) -> str:
    """Return "own", "wait" or "avoid" for a letter grade."""
    if grade in (A_PLUS, A):
        return OWN
    if grade == B:
        return WAIT
    return AVOID


# The evidence handed to the model: the desk's view of one name today, as
# plain text with every number written once.
def brief_text(report, ticker: str) -> str:
    """Return the text of the desk's evidence for `ticker`."""
    view = report.brief(ticker)
    panel = report.panel
    state = report.regime.today()
    lines = [
        f"Name: {ticker} ({view['side']} side). Session: {panel.dates[-1]}.",
        f"Grade: {view['grade']}. Votes: {view['votes']:+.1f}.",
    ]
    for analyst in ("fundamental", "technical", "sentiment", "value", "rotation"):
        stance = view["stances"].get(analyst)
        if stance is None:
            continue
        cited = view["evidence"].get(analyst, {})
        if cited:
            evidence = ", ".join(f"{k} {v:+.3f}" for k, v in cited.items())
        else:
            evidence = "no data for this name"
        rank = view.get("ranks", {}).get(analyst)
        where = (
            f" (rank {rank:.2f} among the book, 1.00 is best)"
            if rank is not None and rank == rank
            else ""
        )
        lines.append(f"{analyst} analyst: stance {stance:+d}{where}; {evidence}.")
    lines.append(
        "Regime: AI participation percentile "
        f"{state.participation_percentile:.2f}, AI-vs-software correlation "
        f"{state.ai_vs_software_correlation:+.2f}, novelty z "
        f"{state.novelty_z:+.1f}, rotation leader {state.rotation_leader}, "
        f"AI basket drawdown {state.ai_drawdown:+.3f}, selection confidence "
        f"{state.selection_confidence:.2f}, exposure {state.exposure:.2f}."
    )
    if state.flags:
        lines.append("Regime flags: " + "; ".join(state.flags) + ".")
    held = [s for s in report.book if s.position.ticker == ticker]
    if held:
        lines.append(f"In today's book at weight {held[0].weight:.3f}.")
    else:
        lines.append("Not in today's book.")
    return "\n".join(lines)


# Text held within `limit` characters, cut at the last sentence end inside
# the limit rather than mid-word.
def _cut(text: str, limit: int) -> str:
    """Return `text` within `limit`, ending at a sentence when it must cut."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    end = max(head.rfind(". "), head.rfind(".\n"), head.rfind("; "))
    if end > limit // 2:
        return head[: end + 1].rstrip()
    clause = max(head.rfind(", "), head.rfind(" "))
    return (head[:clause] if clause > limit // 2 else head).rstrip(" ,;")


def _schema() -> dict[str, Any]:
    return {
        "title": "DeskBrief",
        "type": "object",
        "additionalProperties": False,
        "required": ["stance", "verdict", "reasoning", "risks", "watch"],
        "properties": {
            "stance": {"type": "string", "enum": list(STANCES)},
            "verdict": {"type": "string", "minLength": 5, "maxLength": 200},
            "reasoning": {"type": "string", "minLength": 20, "maxLength": 700},
            "risks": {"type": "string", "minLength": 5, "maxLength": 300},
            "watch": {"type": "string", "minLength": 5, "maxLength": 240},
        },
    }


class DeskNarrator:
    """Write the brief and the read for one name from the desk's evidence."""

    # A missing runtime degrades to None rather than failing the caller.
    def __init__(
        self,
        writer: TextWriter | None,
        max_tokens: int = 600,
        read_max_tokens: int = 600,
    ) -> None:
        self.writer = writer
        self.max_tokens = max_tokens
        self.read_max_tokens = read_max_tokens

    # Write the brief for a name in a report, or None when the runtime is
    # away, the answer does not fit the schema, or the stance contradicts
    # the grade.
    async def brief(self, report, ticker: str) -> DeskBrief | None:
        """Return the DeskBrief for `ticker`, or None."""
        text = brief_text(report, ticker)
        grade = report.brief(ticker)["grade"]
        return await asyncio.to_thread(self.brief_sync, text, grade)

    # The synchronous form, from the evidence text and the grade it states.
    def brief_sync(self, text: str, grade: str) -> DeskBrief | None:
        """Return the DeskBrief for an evidence text, or None."""
        if self.writer is None or not text.strip():
            return None
        try:
            result = self.writer.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ],
                self.max_tokens,
                _schema(),
                # Greedy: the same evidence must read the same every time.
                0.0,
            )
            payload = json.loads(result["content"])
            brief = DeskBrief(
                stance=str(payload["stance"]),
                verdict=_cut(str(payload["verdict"]), 200),
                reasoning=_cut(str(payload["reasoning"]), 700),
                risks=_cut(str(payload["risks"]), 300),
                watch=_cut(str(payload["watch"]), 240),
            )
        except Exception:
            return None
        if brief.stance != stance_for(grade):
            return None
        return brief

    # Write the read for a name in a report, or None when the runtime is
    # away or the answer comes back empty.
    async def read(self, report, ticker: str) -> str | None:
        """Return the desk's read for `ticker`, or None."""
        text = brief_text(report, ticker)
        return await asyncio.to_thread(self.read_sync, text)

    # The synchronous form, from the evidence text. The read is prose, not
    # a decision, so it is asked for without a schema: a grammar would force
    # a shape onto what is meant to be plain language. A read that left a
    # trigger out is asked for once more with the gap named; if it still
    # will not cover it, None comes back and the caller shows the complete
    # deterministic readings instead.
    def read_sync(self, text: str) -> str | None:
        """Return the desk's read for an evidence text, or None."""
        if self.writer is None or not text.strip():
            return None
        try:
            result = self.writer.chat(
                [
                    {"role": "system", "content": _READ_SYSTEM},
                    {"role": "user", "content": text},
                ],
                self.read_max_tokens,
                None,
                # Greedy: the same evidence must read the same every time.
                0.0,
            )
            read = str(result["content"]).strip()
        except Exception:
            return None
        gaps = _coverage_gaps(text, read)
        if gaps:
            try:
                result = self.writer.chat(
                    [
                        {"role": "system", "content": _READ_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"{text}\n\nYou left out: {', '.join(gaps)}. "
                                "Cover those too, and every other measurement "
                                "you were given."
                            ),
                        },
                    ],
                    self.read_max_tokens,
                    None,
                    0.0,
                )
                read = str(result["content"]).strip()
            except Exception:
                return None
            if _coverage_gaps(text, read):
                return None
        return _cut(read, 1600) or None
