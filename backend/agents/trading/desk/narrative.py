"""The desk's brief in words: one name, its grade, and why.

Every number the desk has for a name is already measured; this hands them
to the local model and asks for the explanation an operator would read
before acting. The boundary is the same as the release reader's: the
model sees only the desk's own evidence for one name, in a schema with
bounded fields, and the stance it returns must follow the grade it was
given. It cannot see a price series, so it cannot forecast one.
"""

import asyncio
import dataclasses
import json
import re
from dataclasses import dataclass
from typing import Any

from backend.agents.trading.desk import plainly
from backend.agents.trading.desk.grading import A_PLUS, A, B
from backend.core.interfaces import TextWriter
from backend.core.llm import StrictSchema
from backend.core.prompts import render
from backend.market.labels import BriefStance, ClaimVerdict, values

PROMPT_VERSION = "desk_brief/1"
_SYSTEM = render("trading/desk_brief")
_READ_SYSTEM = render("trading/desk_read")
_CHECK_SYSTEM = render("trading/desk_brief_check")
OWN = BriefStance.OWN
WAIT = BriefStance.WAIT
AVOID = BriefStance.AVOID
STANCES = tuple(BriefStance)

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
# The same analyst's measurements restated in the desk's plain words (the
# readings the board already shows), on the line under the raw figures.
# The writer is told never to copy a field name, so without this line the
# checker had to translate "the 200-day average" back to `ema200_distance`
# on its own and rejected true sentences it could not map.
_PLAIN_LINE = re.compile(
    r"^  (fundamental|technical|sentiment|value|rotation) analyst in plain words: "
    r"(.*)$",
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
        (
            m.group(1)
            for m in re.finditer(r"^Grade:\s*([A-Z][+-]?)", text, re.MULTILINE)
        ),
        "?",
    )
    votes = next(
        (m.group(1) for m in re.finditer(r"Votes:\s*([+-]?\d+(?:\.\d+)?)", text)),
        "?",
    )
    # Each analyst's line keeps its measurements (the text after the
    # stance), so the checker can verify a figure the brief cites against
    # the fact it came from rather than treating it as invented.
    lines: list[str] = []
    for match in _ANALYST_LINE.finditer(text):
        analyst, cited = match.group(1), match.group(2)
        stance = next(
            (m.group(1) for m in re.finditer(r"stance\s*([+-]?\d+)", match.group(0))),
            "0",
        )
        word = (
            "bullish"
            if int(stance) > 0
            else "bearish"
            if int(stance) < 0
            else "neutral"
        )
        # The rank is given to the writer, so a brief that says "ranks near
        # the top of the book" is citing a fact; a checker that never saw
        # the rank called that invented.
        rank = re.search(r"\(rank ([0-9.]+) among the book", match.group(0))
        placed = f", rank {rank.group(1)} among the book (1.00 is best)" if rank else ""
        if cited.strip() in ("no data for this name",):
            lines.append(f"{analyst}: {word}{placed} (no data)")
        else:
            lines.append(f"{analyst}: {word}{placed} ({cited.strip()})")
    # The plain-word readings are the vocabulary the brief was written in,
    # so the checker compares like with like instead of translating.
    for match in _PLAIN_LINE.finditer(text):
        lines.append(f"{match.group(1)}, in plain words: {match.group(2).strip()}")
    # The regime lines and the book status are facts too; a brief that
    # faithfully reports them must not look invented because the contract
    # left them out.
    regime_lines = [
        m.group(1).rstrip(".")
        for m in re.finditer(r"^Regime[^:\n]*:\s*([^\n]+)", text, re.MULTILINE)
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

    stance: BriefStance
    verdict: str
    reasoning: str
    risks: str
    watch: str


# The stance the grade implies; the model must agree with it.
def stance_for(grade: str) -> BriefStance:
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
    plain = _plain_readings(report, view)
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
        if plain.get(analyst):
            lines.append(
                f"  {analyst} analyst in plain words: " + "; ".join(plain[analyst])
            )
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


# The board's plain-word readings for one name, keyed by analyst, or nothing
# where the report cannot be scaled (a bare report in a test has no book to
# compare against). The brief must read the same as the board, so these are
# the board's own words, not a second translation.
def _plain_readings(report, view: dict) -> dict[str, list[str]]:
    """Return {analyst: [reading, ...]} in the desk's plain words."""
    try:
        return plainly.reads(view, plainly.spreads(report))
    except (AttributeError, KeyError, TypeError, ValueError):
        return {}


# Text held within `limit` characters, cut at the last sentence end inside
# the limit rather than mid-word. A text that is short but ends without
# sentence punctuation is a truncation, not a finished brief: the runtime
# stopped at its token ceiling, so the sentence must be cut back to the
# last complete one rather than shown broken. When the text has no complete
# sentence at all - a bare fragment the model stopped mid-thought - a
# bounded deterministic fallback stands in rather than an unfinished phrase
# on the board.
_FRAGMENT_FALLBACK = "The desk's read did not finish in a complete sentence."


# Keep complete sentences within the budget, or use a fallback that fits.
def _cut(text: str, limit: int) -> str:
    """Return `text` within `limit`, ending at a sentence when it must cut."""
    text = text.strip()
    if not text or limit <= 0:
        return ""
    # Inspect the following character in the original text so a decimal
    # point at the limit cannot masquerade as a completed sentence.
    ends = [
        i + 1
        for i, char in enumerate(text[:limit])
        if char in ".!?" and (i + 1 == len(text) or text[i + 1].isspace())
    ]
    if ends:
        return text[: ends[-1]].rstrip()
    for fallback in (_FRAGMENT_FALLBACK, "Read unavailable."):
        if len(fallback) <= limit:
            return fallback
    return ""


# The brief's schema, sent strict: the stance is one of the enum's words.
def _schema() -> dict[str, Any]:
    return StrictSchema(
        {
            "title": "DeskBrief",
            "type": "object",
            "additionalProperties": False,
            "required": ["stance", "verdict", "reasoning", "risks", "watch"],
            "properties": {
                "stance": {"type": "string", "enum": values(BriefStance)},
                "verdict": {"type": "string", "minLength": 5, "maxLength": 200},
                "reasoning": {"type": "string", "minLength": 20, "maxLength": 700},
                "risks": {"type": "string", "minLength": 5, "maxLength": 300},
                "watch": {"type": "string", "minLength": 5, "maxLength": 240},
            },
        }
    )


# The check's answer is one of two words; a grammar forces the choice.
def _check_schema() -> dict[str, Any]:
    return StrictSchema(
        {
            "title": "DeskBriefCheck",
            "type": "object",
            "additionalProperties": False,
            "required": ["claims"],
            "properties": {
                # One row per factual claim in the brief: the claim as written,
                # the fact it was compared with, and the verdict for that pair.
                # Grading claim by claim, with the fact quoted, is what makes the
                # checker look the measurement up instead of judging the whole
                # brief on an impression; the overall verdict is derived in code
                # from these rows, never asked for separately, because the model
                # would sometimes answer "contradicts" over rows it had all
                # marked consistent.
                "claims": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["claim", "fact", "verdict"],
                        "properties": {
                            "claim": {"type": "string", "maxLength": 240},
                            "fact": {"type": "string", "maxLength": 240},
                            "verdict": {
                                "type": "string",
                                "enum": values(ClaimVerdict),
                            },
                        },
                    },
                },
            },
        }
    )


# The verdict for one check from its claim rows. A contradicting row sinks
# the brief and is named; a row the checker could not place (a conditional
# risk, a watch item, a sentence about an analyst the evidence does not
# carry) is "uncertain" and does not, because the brief is checked for what
# it asserts against the facts, and omission or hedging is not assertion.
# An answer with no rows judged nothing, which is not approval.
def _check_verdict(payload: dict[str, Any]) -> tuple[ClaimVerdict, list[str]]:
    """Return (consistency, the claims that contradict)."""
    rows = payload.get("claims")
    if not isinstance(rows, list) or not rows:
        return ClaimVerdict.UNCERTAIN, []
    # A row's verdict is parsed: a word outside the vocabulary fails the check
    # attempt rather than reading as "not a contradiction".
    verdicts = [ClaimVerdict(row.get("verdict")) for row in rows]
    named = [
        str(row.get("claim", "")).strip()
        for row, verdict in zip(rows, verdicts, strict=True)
        if verdict is ClaimVerdict.CONTRADICTS and str(row.get("claim", "")).strip()
    ]
    if ClaimVerdict.CONTRADICTS in verdicts:
        return ClaimVerdict.CONTRADICTS, named
    return ClaimVerdict.CONSISTENT, []


# Why a brief was not written, in the words the nightly log and the prose
# block carry. Each value names the gate that dropped it; the earlier wording
# ("runtime away, empty, or the answer did not fit") lumped four different
# failures into one sentence, so a night of checker rejections read exactly
# like a night with the model switched off.
NO_RUNTIME = "no runtime"
NO_ANSWER = "the runtime returned no answer"
BAD_SHAPE = "the answer did not fit the brief schema"
WRONG_STANCE = "the stance disagreed with the grade"
CONTRADICTED = "the checker rejected every attempt"


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
        return self.brief_outcome(text, grade)[0]

    # The brief with the reason it was dropped when it was: (brief, None) on
    # success, (None, reason) otherwise. The reason names the gate, and for a
    # checker rejection carries the claims the checker named and the last
    # rejected brief, so a failed night can be read without re-running it.
    def brief_outcome(
        self, text: str, grade: str
    ) -> tuple[DeskBrief | None, dict[str, Any] | None]:
        """Return (brief, None) or (None, {"reason", "claims", "rejected"})."""
        if self.writer is None:
            return None, {"reason": NO_RUNTIME}
        if not text.strip():
            return None, {"reason": NO_ANSWER}
        # A brief is written and checked, and a slip the checker catches is
        # rewritten and re-checked, up to a bound. The engine is not
        # strictly deterministic at temperature 0, so one bad sentence in a
        # field can trip the checker on an otherwise good brief; a bounded
        # rewrite that is told which claim was rejected fixes it while a
        # genuinely wrong brief keeps contradicting and is dropped.
        claims: list[str] = []
        rejected: DeskBrief | None = None
        for attempt in range(3):
            brief, failure = self._write_brief(text, claims if attempt else None)
            if brief is None:
                return None, {"reason": failure or BAD_SHAPE}
            if brief.stance != stance_for(grade):
                return None, {
                    "reason": WRONG_STANCE,
                    "detail": f"{brief.stance} for grade {grade}",
                    "rejected": dataclasses.asdict(brief),
                }
            named = self._check(text, brief)
            if named is None:
                return brief, None
            claims.extend(c for c in named if c and c not in claims)
            rejected = brief
        return None, {
            "reason": CONTRADICTED,
            "claims": claims,
            "rejected": dataclasses.asdict(rejected) if rejected else None,
        }

    # One write of the brief from the evidence: (brief, None), or (None,
    # reason) when the runtime is away or the answer does not fit the schema.
    # A retry (`rejected` is a list, possibly empty) asks the model to stick
    # strictly to the evidence and name the average or trend it means rather
    # than generalising, because the contradictions the checker catches are
    # a summary sentence that overstated one measurement; when the checker
    # named the claims, the retry quotes them, since a rewrite that is told
    # only "something disagreed" tends to reproduce the same sentence.
    def _write_brief(
        self, text: str, rejected: list[str] | None = None
    ) -> tuple[DeskBrief | None, str | None]:
        """Return (DeskBrief, None) for an evidence text, or (None, reason)."""
        if self.writer is None:
            return None, NO_RUNTIME
        if not text.strip():
            return None, NO_ANSWER
        if rejected is None:
            user = text
        else:
            named = (
                "The checker named these claims as the ones the evidence "
                "disagrees with:\n"
                + "\n".join(f"- {claim}" for claim in rejected)
                + "\n\n"
                if rejected
                else ""
            )
            user = (
                f"{text}\n\nThe previous brief was dropped because it stated "
                f"something the evidence disagrees with. {named}The desk's own "
                "fact contract, which every sentence of the brief must agree "
                f"with, is:\n{_check_facts(text)}\n\nRewrite the brief so "
                "every direction, comparison and claim comes straight from "
                "those facts. State each measurement's direction as the facts "
                "give it, make no relative claim (rank, high or low among the "
                "book) the facts do not state, and never write one blanket "
                "direction for the whole price action that a specific "
                "measurement contradicts."
            )
        try:
            result = self.writer.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user},
                ],
                self.max_tokens,
                _schema(),
                # Greedy: the same evidence must read the same every time.
                0.0,
            )
        except Exception as exc:  # noqa: BLE001 - the reason is the evidence
            return None, f"{NO_ANSWER} ({type(exc).__name__})"
        try:
            payload = json.loads(result["content"])
            brief = DeskBrief(
                stance=BriefStance(payload["stance"]),
                verdict=_cut(str(payload["verdict"]), 200),
                reasoning=_cut(str(payload["reasoning"]), 700),
                risks=_cut(str(payload["risks"]), 300),
                watch=_cut(str(payload["watch"]), 240),
            )
        except Exception as exc:  # noqa: BLE001 - the reason is the evidence
            return None, f"{BAD_SHAPE} ({type(exc).__name__})"
        return brief, None

    # Whether the brief contradicts the facts the desk measured. A
    # judgement, so it is a model decision into a two-value schema. Publication
    # requires two valid consistency approvals; an unavailable check is unknown.
    # The facts it judges
    # against are the clean stances and measurements read from the evidence
    # in code, not the raw prose a model could not reliably adjudicate. The
    # engine is not strictly deterministic at temperature 0, so one call
    # can disagree between calls; the bounded majority is a consistency check,
    # not proof that the model cannot be wrong.
    def _contradicts(self, text: str, brief: DeskBrief) -> bool:
        """Return whether the brief lacks majority approval against its evidence."""
        return self._check(text, brief) is not None

    # The check itself: None when the brief has majority approval, otherwise
    # the claims the dissenting checks named (possibly empty, when the
    # checker gave no claim or the check could not run).
    def _check(self, text: str, brief: DeskBrief) -> list[str] | None:
        """Return None for an approved brief, else the claims that were named."""
        if self.writer is None:
            return []
        brief_lines = (
            f"stance: {brief.stance}\n"
            f"verdict: {brief.verdict}\n"
            f"reasoning: {brief.reasoning}\n"
            f"risks: {brief.risks}\n"
            f"watch: {brief.watch}"
        )
        consistent = 0
        claims: list[str] = []
        for _ in range(3):
            try:
                result = self.writer.chat(
                    [
                        {"role": "system", "content": _CHECK_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"FACTS:\n{_check_facts(text)}\n\nBRIEF:\n{brief_lines}"
                            ),
                        },
                    ],
                    # Room for one row per claim in a four-field brief.
                    1200,
                    _check_schema(),
                    0.0,
                )
                verdict, named = _check_verdict(json.loads(result["content"]))
                if verdict is ClaimVerdict.CONSISTENT:
                    consistent += 1
                for claim in named:
                    if claim not in claims:
                        claims.append(claim)
            except Exception:
                continue
        return None if consistent >= 2 else claims

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
