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
from dataclasses import dataclass
from typing import Any

from backend.agents.trading.desk.grading import A_PLUS, A, B
from backend.core.interfaces import TextWriter
from backend.core.prompts import render

PROMPT_VERSION = "desk_brief/1"
_SYSTEM = render("trading/desk_brief")
OWN = "own"
WAIT = "wait"
AVOID = "avoid"
STANCES = (OWN, WAIT, AVOID)


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
    for analyst in ("fundamental", "technical", "sentiment", "rotation"):
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
    return head[: end + 1].rstrip() if end > limit // 2 else head.rstrip()


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
    """Write the brief for one name from the desk's evidence text."""

    # A missing runtime degrades to None rather than failing the caller.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 600) -> None:
        self.writer = writer
        self.max_tokens = max_tokens

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
