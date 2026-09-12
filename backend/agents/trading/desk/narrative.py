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
_CHECK_SYSTEM = render("trading/desk_brief_check")
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
# One analyst's line in the evidence. The rank sits between the stance and
# the semicolon (`stance +1 (rank 0.95 among the book, 1.00 is best);`), so
# the pattern allows it - a ranked input used to break the match and leave
# that analyst completely outside the coverage check.
_ANALYST_LINE = re.compile(
    r"^(fundamental|technical|sentiment|value|rotation) analyst: "
    r"stance [+-]?\d+(?: \([^)]*\))?; (.*)$",
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


# The facts the contradiction check can rely on, read deterministically
# from the evidence rather than trusted to a model: each analyst's stance
# and the key measurements behind it, plus the grade it was told to
# explain. The reviewer's complaint was that the check received raw
# numbers and free prose it could not reliably adjudicate; handing it the
# clean contract the brief was written to match makes "consistent" the
# verdict for a faithful brief and only a stated direction the facts
# contradict becomes "contradicts".
def _check_facts(text: str) -> str:
    """Return the stances, grade and key figures in `text` as a fact list."""
    grade = next(
        (m.group(1) for m in re.finditer(r"^Grade:\s*([A-Z][+-]?)", text, re.MULTILINE)),
        "?",
    )
    votes = next(
        (
            m.group(1)
            for m in re.finditer(r"Votes:\s*([+-]?\d+(?:\.\d+)?)", text)
        ),
        "?",
    )
    # Each analyst's line keeps its measurements (the text after the
    # stance), so the checker can verify a figure the brief cites against
    # the fact it came from rather than treating it as invented.
    lines: list[str] = []
    for match in _ANALYST_LINE.finditer(text):
        analyst, cited = match.group(1), match.group(2)
        stance = next(
            (
                m.group(1)
                for m in re.finditer(r"stance\s*([+-]?\d+)", match.group(0))
            ),
            "0",
        )
        word = "bullish" if int(stance) > 0 else "bearish" if int(stance) < 0 else "neutral"
        if cited.strip() in ("no data for this name",):
            lines.append(f"{analyst}: {word} (no data)")
        else:
            lines.append(f"{analyst}: {word} ({cited.strip()})")
    # The regime lines and the book status are facts too; a brief that
    # faithfully reports them must not look invented because the contract
    # left them out.
    regime_lines = [
        m.group(1).rstrip(".") for m in re.finditer(r"^Regime[^:\n]*:\s*([^\n]+)", text, re.MULTILINE)
    ]
    regime = " | ".join(regime_lines)
    book = "in today's book" if "In today's book" in text else "not in today's book"
    return (
        f"Grade: {grade}. Votes: {votes}.\n"
        + "\n".join(lines)
        + f"\nRegime: {regime.strip()}.\nBook: {book}."
    )


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
# the limit rather than mid-word. A text that is short but ends without
# sentence punctuation is a truncation, not a finished brief: the runtime
# stopped at its token ceiling, so the sentence must be cut back to the
# last complete one rather than shown broken. When the text has no complete
# sentence at all - a bare fragment the model stopped mid-thought - a
# bounded deterministic fallback stands in rather than an unfinished phrase
# on the board.
_FRAGMENT_FALLBACK = "The desk's read did not finish in a complete sentence."


def _cut(text: str, limit: int) -> str:
    """Return `text` within `limit`, ending at a sentence when it must cut."""
    text = text.strip()
    if not text:
        return text
    if len(text) <= limit:
        if text.endswith((".", "!", "?")):
            return text
        # Short but unfinished: cut back to the last complete sentence. A
        # one-clause fragment with no sentence end cannot be made complete
        # by cutting, so the bounded fallback replaces it.
        end = max(text.rfind(". "), text.rfind(".\n"), text.rfind("; "))
        return text[: end + 1].rstrip() if end > 0 else _FRAGMENT_FALLBACK
    # A cut that lands before any sentence boundary would end mid-sentence,
    # so widen the search to the whole text before accepting a fragment:
    # the last complete sentence anywhere wins, and only a text with no
    # sentence end at all falls back.
    head = text[:limit]
    end = max(head.rfind(". "), head.rfind(".\n"), head.rfind("; "))
    if end > limit // 2:
        return head[: end + 1].rstrip()
    end = max(text.rfind(". "), text.rfind(".\n"), text.rfind("; "))
    if end > 0:
        return text[: end + 1].rstrip()
    return _FRAGMENT_FALLBACK


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


# The check's answer is one of two words; a grammar forces the choice.
def _check_schema() -> dict[str, Any]:
    return {
        "title": "DeskBriefCheck",
        "type": "object",
        "additionalProperties": False,
        "required": ["consistency"],
        "properties": {
            "consistency": {"type": "string", "enum": ["consistent", "contradicts"]},
        },
    }


class DeskNarrator:
    """Write the brief and the read for one name from the desk's evidence."""

    # A missing runtime degrades to None rather than failing the caller.
    def __init__(
        self,
        writer: TextWriter | None,
        max_tokens: int = 900,
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
        if self._contradicts(text, brief):
            return None
        return brief

    # Whether the brief contradicts the facts the desk measured. A
    # judgement, so it is a model decision into a two-value schema; a check
    # that fails to answer never discards a good brief. The facts it judges
    # against are the clean stances and measurements read from the evidence
    # in code, not the raw prose a model could not reliably adjudicate. The
    # engine is not strictly deterministic at temperature 0, so one call
    # can say "contradicts" on a good brief; a brief is dropped only when a
    # majority of three independent calls say so, which a genuinely wrong
    # brief produces and a right one almost never does.
    def _contradicts(self, text: str, brief: DeskBrief) -> bool:
        """Return whether the brief contradicts the evidence."""
        if self.writer is None:
            return False
        brief_lines = (
            f"stance: {brief.stance}\n"
            f"verdict: {brief.verdict}\n"
            f"reasoning: {brief.reasoning}\n"
            f"risks: {brief.risks}\n"
            f"watch: {brief.watch}"
        )
        disagree = 0
        for _ in range(3):
            try:
                result = self.writer.chat(
                    [
                        {"role": "system", "content": _CHECK_SYSTEM},
                        {
                            "role": "user",
                            "content": f"FACTS:\n{_check_facts(text)}\n\nBRIEF:\n{brief_lines}",
                        },
                    ],
                    32,
                    _check_schema(),
                    0.0,
                )
                payload = json.loads(result["content"])
                if str(payload.get("consistency") or "consistent") == "contradicts":
                    disagree += 1
            except Exception:
                continue
        return disagree >= 2

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
