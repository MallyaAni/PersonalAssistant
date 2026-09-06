"""The experience review as a durable run.

Fixed stages in code - read the day's turns, one judgement over them, then
the fixes, then the report - because that order is not a judgement. The one
judgement (where did the experience degrade, and why) is the prompt's; every
finding it writes is checked against the turn it names before anyone reads
it: the quoted words must be in that exchange, and the cause it claims must
agree with the turn's own record - a "missing attachment" on a turn that
had a picture in view is downgraded to what the record supports.

What it puts right itself is bounded by what can be undone: a memory saved
from an exchange the review found wrong is proposed for forgetting, and the
run parks for the person's yes on each (answerable from chat). Everything
else - a dropped attachment, a reminder read as a habit, a misrouted turn -
is reported with the exchanges that show it, so the defect reaches the
people who change code with its evidence attached, the same day.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from backend.agents.experience.prompts import ExperiencePrompts, Finding, Judgement
from backend.agents.experience.sources import Saved, Turn, render_turns, rooms_of, saved_after, turns_since
from backend.runs.worlds import Verification
from backend.services.turn_steps import Act, Decision, Done, TurnResult, Unavailable

KIND = "experience_review"
# How many times one step may fail before the review gives up on it.
MAX_STEP_ATTEMPTS = 3
# How far back a review reads when the objective names no start.
DEFAULT_WINDOW_HOURS = 24
# Friction kinds whose turn's saved memories are proposed for forgetting:
# what a misread or a corrected exchange taught the assistant is suspect. A
# wrong subject is a routing fault, not a wrong lesson, and is not here: the
# first live run proposed forgetting a picture's description because the
# turn beside it was misrouted (2026-09-05).
FORGETTABLE_KINDS = frozenset({"correction", "unresolved_reference", "wrong_memory"})
# Only what the person stated about themself may be proposed for forgetting.
# A memory derived from a picture is the index that lets a later turn find
# that picture; forgetting it would remove exactly the context the review
# exists to protect.
FORGETTABLE_PURPOSES = frozenset({"user_explicit", "user_preference", "user_constraint"})


@dataclass(frozen=True, slots=True)
class ReadTurns:
    since: str


@dataclass(frozen=True, slots=True)
class Judge:
    since: str


@dataclass(frozen=True, slots=True)
class ForgetMemory:
    memory_id: str
    owner: str
    content: str
    because: str


@dataclass(frozen=True, slots=True)
class WriteReport:
    since: str


_TOOLS = {ReadTurns: "turns_read", Judge: "experience_judge", ForgetMemory: "memory_forget", WriteReport: "experience_report"}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


# The start of the window a run's objective names ("review experience for
# <user> since <iso>"), or the default window back from now.
def since_of(objective: str, now: datetime | None = None) -> datetime:
    match = re.search(r"since\s+(\S+)", str(objective or ""))
    if match:
        try:
            parsed = datetime.fromisoformat(match.group(1))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return (now or datetime.now(UTC)) - timedelta(hours=DEFAULT_WINDOW_HOURS)


@dataclass
class ReviewState:
    turns: list[Turn] = field(default_factory=list)
    rooms: tuple[str, ...] = ()
    read: bool = False
    judgement: Judgement | None = None
    kept: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[ForgetMemory] = field(default_factory=list)
    fixes: list[dict[str, Any]] = field(default_factory=list)
    reported: bool = False
    failures: dict[str, int] = field(default_factory=dict)
    last_error: str = ""


class ExperienceWorld:
    """One day of one person's exchanges, reviewed and put right where it can be."""

    def __init__(self, run: dict[str, Any], sessions: Callable[[], Any], prompts: ExperiencePrompts) -> None:
        self.run = run
        self.user_id = str(run["user_id"])
        self.since = since_of(str(run.get("objective") or ""))
        self.sessions = sessions
        self.prompts = prompts
        self.state = ReviewState()

    # ---------------------------------------------------------- the stages

    async def decide(self, lines: list[str]) -> Decision:
        state = self.state
        since = self.since.isoformat()
        pending: Any = None
        if not state.read:
            pending = ReadTurns(since)
        elif state.judgement is None:
            pending = Judge(since)
        else:
            for proposal in state.proposals:
                if not any(fix["memory_id"] == proposal.memory_id for fix in state.fixes):
                    pending = proposal
                    break
            if pending is None and not state.reported:
                pending = WriteReport(since)
        if pending is None:
            return Done("review written")
        if state.failures.get(self._base_key(pending), 0) >= MAX_STEP_ATTEMPTS:
            return Unavailable(f"{self.tool_name(pending)} failed {MAX_STEP_ATTEMPTS} times: {state.last_error}")
        return Act(pending)

    async def apply(self, action: Any) -> tuple[str, dict[str, Any]] | None:
        state = self.state
        if isinstance(action, ReadTurns):
            async with self.sessions() as db:
                rooms = await rooms_of(db, self.user_id)
                turns = await turns_since(db, self.user_id, self.since, rooms)
            return "read", {"kind": "done", "count": len(turns), "rooms": list(rooms), "turns": [asdict(t) | {"when": t.when.isoformat() if t.when else None} for t in turns]}
        if isinstance(action, Judge):
            if not state.turns:
                return "analysis", {"kind": "done", "findings": [], "rejected": [], "summary": "No exchanges in the window; nothing to review.", "proposals": []}
            judgement = await self.prompts.judge(render_turns(state.turns))
            if judgement is None:
                return "analysis", {"kind": "failed", "error": "the model did not answer"}
            kept, rejected = self._check(judgement)
            proposals = await self._forgettable(kept)
            return "analysis", {
                "kind": "done",
                "findings": [f.as_dict() | {"turn_id": self._turn(f.turn).id if self._turn(f.turn) else None} for f in kept],
                "rejected": rejected,
                "summary": judgement.summary,
                "proposals": [asdict(p) for p in proposals],
            }
        if isinstance(action, ForgetMemory):
            from backend.memory.repository import MemoryRepository

            async with self.sessions() as db:
                gone = await MemoryRepository(db).delete_memory(action.owner, "semantic", action.memory_id)
            return "write", {"kind": "done" if gone else "not_found", "memory_id": action.memory_id, "content": action.content}
        if isinstance(action, WriteReport):
            return "analysis", {"kind": "done", "summary": self._summary()}
        return None

    # A finding is kept when its quote is in the exchange it names and its
    # cause agrees with the record; otherwise it is rejected with the reason,
    # or its cause corrected to what the record supports.
    def _check(self, judgement: Judgement) -> tuple[list[Finding], list[dict[str, Any]]]:
        kept: list[Finding] = []
        rejected: list[dict[str, Any]] = []
        for finding in judgement.findings:
            turn = self._turn(finding.turn)
            if turn is None:
                rejected.append(finding.as_dict() | {"rejected": "names an exchange that was not read"})
                continue
            exchange = _squash(f"{turn.said} {turn.replied}")
            if _squash(finding.quote) not in exchange:
                rejected.append(finding.as_dict() | {"rejected": "quotes words that are not in that exchange"})
                continue
            record = turn.record()
            cause = finding.cause
            if cause == "missing_attachment" and record["picture_in_view"]:
                cause = "model"
            if cause == "reminder_read_as_habit" and not any(t.record()["reminder_firing"] for t in self.state.turns):
                cause = "unknown"
            if finding.kind == "empty_reply" and (turn.replied.strip() or not turn.addressed):
                rejected.append(finding.as_dict() | {"rejected": "the assistant did reply, or was not addressed"})
                continue
            kept.append(Finding(finding.turn, finding.kind, finding.quote, cause, finding.explanation))
        return kept, rejected

    # The memories saved from the exchanges the review found wrong, each a
    # proposal to forget that needs the person's yes.
    async def _forgettable(self, kept: list[Finding]) -> list[ForgetMemory]:
        proposals: list[ForgetMemory] = []
        owners = (self.user_id, *self.state.rooms)
        seen: set[str] = set()
        async with self.sessions() as db:
            for finding in kept:
                if finding.kind not in FORGETTABLE_KINDS:
                    continue
                turn = self._turn(finding.turn)
                if turn is None:
                    continue
                for saved in await saved_after(db, turn, owners):
                    if saved.id in seen or saved.purpose not in FORGETTABLE_PURPOSES:
                        continue
                    seen.add(saved.id)
                    proposals.append(ForgetMemory(saved.id, saved.owner, saved.content[:200], f"saved from exchange {finding.turn}: {finding.kind} - {finding.explanation[:120]}"))
        return proposals

    def _turn(self, number: int) -> Turn | None:
        for turn in self.state.turns:
            if turn.number == number:
                return turn
        return None

    # The words for the person: the judgement's summary, then what was done.
    def _summary(self) -> str:
        state = self.state
        base = state.judgement.summary if state.judgement and state.judgement.summary else "Nothing degraded in this window."
        forgotten = sum(1 for fix in state.fixes if fix.get("status") == "done")
        waiting = len(state.proposals) - len(state.fixes)
        notes = []
        if forgotten:
            notes.append(f"{forgotten} wrong memor{'y' if forgotten == 1 else 'ies'} forgotten")
        if waiting > 0:
            notes.append(f"{waiting} waiting for your yes")
        if state.kept:
            causes = sorted({f['cause'] for f in state.kept})
            notes.append(f"{len(state.kept)} finding{'s' if len(state.kept) != 1 else ''} ({', '.join(causes)})")
        return base + (" " + "; ".join(notes) + "." if notes else "")

    # ------------------------------------------------------------ observe

    def observe(self, action: Any, kind: str, outcome: dict[str, Any]) -> None:
        state = self.state
        went = str(outcome.get("kind") or "")
        if went not in ("done", "not_found"):
            base = self._base_key(action)
            state.failures[base] = state.failures.get(base, 0) + 1
            state.last_error = str(outcome.get("error") or went)
            return
        if isinstance(action, ReadTurns):
            state.rooms = tuple(outcome.get("rooms") or ())
            state.turns = [
                Turn(**{**item, "when": datetime.fromisoformat(item["when"]) if item.get("when") else None})
                for item in outcome.get("turns") or []
            ]
            state.read = True
        elif isinstance(action, Judge):
            state.kept = list(outcome.get("findings") or [])
            state.rejected = list(outcome.get("rejected") or [])
            state.judgement = Judgement((), str(outcome.get("summary") or ""))
            state.proposals = [ForgetMemory(**item) for item in outcome.get("proposals") or []]
        elif isinstance(action, ForgetMemory):
            state.fixes.append({"memory_id": action.memory_id, "content": action.content, "status": went, "because": action.because})
        elif isinstance(action, WriteReport):
            state.reported = True

    # ---------------------------------------------------------- the contract

    def tool_name(self, action: Any) -> str:
        return _TOOLS.get(type(action), "unknown")

    def arguments(self, action: Any) -> dict[str, Any]:
        return {name: getattr(action, name) for name in getattr(action, "__dataclass_fields__", {})}

    def _base_key(self, action: Any) -> str:
        import json

        return f"{self.tool_name(action)}:{json.dumps(self.arguments(action), sort_keys=True)}"

    def key(self, action: Any) -> str | None:
        base = self._base_key(action)
        attempt = self.state.failures.get(base, 0)
        return base if attempt == 0 else f"{base}#{attempt}"

    def creates(self, action: Any) -> bool:
        return False

    def describe(self, action: Any, kind: str, outcome: dict[str, Any] | None) -> str:
        went = str((outcome or {}).get("kind") or "")
        what = self.tool_name(action)
        detail = ""
        if isinstance(action, ReadTurns) and outcome:
            detail = f" ({outcome.get('count', 0)} turns)"
        if isinstance(action, Judge) and outcome:
            detail = f" ({len(outcome.get('findings') or [])} findings, {len(outcome.get('rejected') or [])} rejected, {len(outcome.get('proposals') or [])} to forget)"
        if isinstance(action, ForgetMemory):
            detail = f" {action.content[:60]!r}"
        suffix = "" if went == "done" else f" [{went}]"
        return f"{what}{detail}{suffix}"

    # Forgetting is the one thing here that changes the person's record, and
    # it never happens without their yes.
    def needs_approval(self, action: Any) -> bool:
        return isinstance(action, ForgetMemory)

    def approval_summary(self, action: Any) -> str:
        if isinstance(action, ForgetMemory):
            return f"forget the memory {action.content[:120]!r} ({action.because[:100]})"
        return ""

    # A read or a judgement never heard from is simply done again; a delete
    # is looked up: gone means it happened.
    async def reconcile(self, action: Any, prior: dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(action, ForgetMemory):
            from sqlalchemy import select

            from backend.models.memory import SemanticMemory

            async with self.sessions() as db:
                row = await db.scalar(select(SemanticMemory).where(SemanticMemory.id == action.memory_id))
            if row is None:
                return {"kind": "done", "memory_id": action.memory_id, "content": action.content}
            return {"kind": "failed", "error": "the delete did not land; done again"}
        return {"kind": "failed", "error": "redone after an interrupted read"}

    async def verify(self, result: TurnResult, run: dict[str, Any]) -> Verification:
        state = self.state
        accepted = bool(state.read and state.judgement is not None and state.reported)
        evidence = {
            "user_id": self.user_id,
            "since": self.since.isoformat(),
            "rooms": list(state.rooms),
            "turns_reviewed": len(state.turns),
            "findings": state.kept,
            "rejected": state.rejected,
            "fixes": state.fixes,
            "proposed": [asdict(p) for p in state.proposals],
        }
        return Verification(accepted, evidence, self._summary() if accepted else "the review did not finish")
