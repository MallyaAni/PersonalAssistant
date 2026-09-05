"""The review as a durable run: what it reads, in what order, and what counts.

The stages are a fixed sequence in code - the commit's summary, its diff, the
files worth reading, the findings - because that order is not a judgement.
The two judgements (which files, what is wrong) are the prompts'. Every
read goes through the `repo` MCP server behind the invocation boundary, so
the review can touch nothing it was not given.

**Completion is evidence.** A finding is kept only when the file it names was
read at this commit, the line exists, and the quoted evidence is that line
(whitespace aside). Anything else is recorded as rejected, with the reason.
The run is accepted when the summary, the diff and every chosen file were
read and the findings were written and checked - a sound change with no
findings is a completed review.

Prompt injection is met by construction rather than by wording: the world
has only read tools, the stages cannot be reordered by anything the model
says, and text inside the repository reaches the prompts framed as material
under review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from backend.agents.review.prompts import Finding, Review, ReviewPrompts
from backend.mcp.invocation import MCPInvocationError
from backend.runs.worlds import Verification
from backend.services.mcp_invocation_service import MCPInvocationService
from backend.services.turn_steps import Act, Decision, Done, TurnResult, Unavailable

# ------------------------------------------------------------------ actions


@dataclass(frozen=True, slots=True)
class ShowCommit:
    commit: str


@dataclass(frozen=True, slots=True)
class ReadDiff:
    commit: str


@dataclass(frozen=True, slots=True)
class ReadFile:
    path: str
    commit: str


@dataclass(frozen=True, slots=True)
class WriteFindings:
    commit: str


ReviewAction = ShowCommit | ReadDiff | ReadFile | WriteFindings

_TOOLS = {
    ShowCommit: "repo_show_commit",
    ReadDiff: "repo_diff",
    ReadFile: "repo_read_file",
    WriteFindings: "review_findings",
}

# The tools this world may ever call, by construction.
READ_TOOLS: frozenset[str] = frozenset({"repo_show_commit", "repo_diff", "repo_read_file"})


# How many times one step may fail before the review gives up on it.
MAX_STEP_ATTEMPTS = 3


# Whitespace-insensitive comparison of a quoted line with the code.
def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


# How far from the cited line a quote may sit and still count.
EVIDENCE_TOLERANCE_LINES = 2


# The line at or near `number` whose text the quote is (or holds), nearest
# first; None when the quote is at none of them.
def _nearby(lines: dict[int, str], number: int, evidence: str) -> int | None:
    wanted = _squash(evidence)
    if not wanted:
        return None
    for distance in range(EVIDENCE_TOLERANCE_LINES + 1):
        for candidate in (number - distance, number + distance):
            shown = lines.get(candidate)
            if shown is None:
                continue
            squashed = _squash(shown)
            if wanted in squashed or (squashed and squashed in wanted):
                return candidate
    return None


# A file's numbered slice, as the repo server writes it, back into lines.
def _lines_of(content: str) -> dict[int, str]:
    lines: dict[int, str] = {}
    for raw in str(content or "").splitlines():
        number, _, text = raw.partition("| ")
        if number.strip().isdigit():
            lines[int(number)] = text
    return lines


@dataclass
class ReviewState:
    """What the review has learned so far, rebuilt from observed outcomes."""

    summary: dict[str, Any] | None = None
    diff: str | None = None
    chosen: list[str] | None = None
    contents: dict[str, str] = field(default_factory=dict)
    review: Review | None = None
    rejected: list[dict[str, Any]] = field(default_factory=list)
    # How many times each step has come back failed, so a transient failure
    # - the model timing out, the server dropping a read - is tried again a
    # bounded number of times under a fresh key, and a persistent one ends
    # the review with its reason rather than tripping the repeat guard.
    failures: dict[str, int] = field(default_factory=dict)
    last_error: str = ""


class ReviewWorld:
    """A read-only review of one commit, driven by the run controller."""

    def __init__(
        self,
        run: dict[str, Any],
        invocation: MCPInvocationService,
        prompts: ReviewPrompts,
        server_id: str = "repo",
    ) -> None:
        self.run = run
        self.commit = str(run.get("objective") or "").split()[-1] if run.get("objective") else ""
        objective = run.get("objective") or ""
        match = re.search(r"\b[0-9a-fA-F]{7,40}\b", str(objective))
        if match:
            self.commit = match.group(0)
        self.invocation = invocation
        self.prompts = prompts
        self.server_id = server_id
        self.state = ReviewState()

    # ---------------------------------------------------------- the stages

    async def decide(self, lines: list[str]) -> Decision:
        state = self.state
        if not self.commit:
            return Unavailable("no commit in the objective")
        pending: Any = None
        if state.summary is None:
            pending = ShowCommit(self.commit)
        elif state.diff is None:
            pending = ReadDiff(self.commit)
        else:
            if state.chosen is None:
                state.chosen = await self.prompts.choose_files(state.summary, state.diff)
            for path in state.chosen:
                if path not in state.contents:
                    pending = ReadFile(path, self.commit)
                    break
            if pending is None and state.review is None:
                pending = WriteFindings(self.commit)
        if pending is None:
            return Done("review written")
        if state.failures.get(self._base_key(pending), 0) >= MAX_STEP_ATTEMPTS:
            return Unavailable(
                f"{self.tool_name(pending)} failed {MAX_STEP_ATTEMPTS} times: {state.last_error}"
            )
        return Act(pending)

    async def apply(self, action: Any) -> tuple[str, dict[str, Any]] | None:
        if isinstance(action, ShowCommit):
            return "read", await self._call("repo_show_commit", {"commit": action.commit})
        if isinstance(action, ReadDiff):
            return "read", await self._call("repo_diff", {"commit": action.commit})
        if isinstance(action, ReadFile):
            return "read", await self._call(
                "repo_read_file", {"path": action.path, "commit": action.commit}
            )
        if isinstance(action, WriteFindings):
            state = self.state
            if state.summary is None or state.diff is None:
                return "analysis", {"kind": "failed", "error": "nothing read yet"}
            review = await self.prompts.findings(
                state.summary, state.diff, await self._findings_contents()
            )
            if review is None:
                return "analysis", {"kind": "failed", "error": "the model did not answer"}
            kept, rejected = self._check(review)
            return "analysis", {
                "kind": "done",
                "findings": [finding.as_dict() for finding in kept],
                "rejected": rejected,
                "summary": review.summary,
                "unknowns": list(review.unknowns),
            }
        return None

    # What the findings step is shown beside the diff: the files read, and
    # whatever else a variant of this world gathered (the security agent adds
    # its pattern hits). Anything added here is material, never a finding.
    async def _findings_contents(self) -> dict[str, str]:
        return dict(self.state.contents)

    # One read through the boundary; a refusal is a failed step, not a crash.
    async def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self.invocation.invoke(self.server_id, tool, arguments)
        except MCPInvocationError as exc:
            return {"kind": "refused", "error": exc.reason}
        if result.is_error:
            return {"kind": "failed", "error": result.content[:200]}
        try:
            payload = json.loads(result.content)
        except ValueError:
            return {"kind": "failed", "error": "unreadable answer"}
        if isinstance(payload, dict) and payload.get("error"):
            return {"kind": "failed", "error": str(payload["error"])[:200]}
        return {"kind": "done", "payload": payload}

    # Learn from every outcome, fresh or replayed; count the failures.
    def observe(self, action: Any, kind: str, outcome: dict[str, Any]) -> None:
        if str(outcome.get("kind")) != "done":
            base = self._base_key(action)
            self.state.failures[base] = self.state.failures.get(base, 0) + 1
            self.state.last_error = str(outcome.get("error") or outcome.get("kind") or "")
            return
        payload = outcome.get("payload")
        state = self.state
        if isinstance(action, ShowCommit) and isinstance(payload, dict):
            state.summary = payload
        elif isinstance(action, ReadDiff) and isinstance(payload, dict):
            state.diff = str(payload.get("diff") or "")
        elif isinstance(action, ReadFile) and isinstance(payload, dict):
            state.contents[action.path] = str(payload.get("content") or "")
        elif isinstance(action, WriteFindings):
            state.review = Review(
                findings=tuple(Finding(**item) for item in outcome.get("findings") or []),
                summary=str(outcome.get("summary") or ""),
                unknowns=tuple(outcome.get("unknowns") or ()),
            )
            state.rejected = list(outcome.get("rejected") or [])

    # ------------------------------------------------------------ the check

    # Keep a finding only when the code it cites is there to be read.
    def _check(self, review: Review) -> tuple[list[Finding], list[dict[str, Any]]]:
        kept: list[Finding] = []
        rejected: list[dict[str, Any]] = []
        changed = {str(item.get("path")) for item in (self.state.summary or {}).get("files") or []}
        for finding in review.findings:
            reason = None
            if finding.file not in changed:
                reason = "names a file the commit did not change"
            elif finding.file not in self.state.contents:
                reason = "names a file the review did not read"
            else:
                lines = _lines_of(self.state.contents[finding.file])
                if finding.line not in lines:
                    reason = "names a line outside what was read"
                else:
                    # The quote may sit a line or two from the number the
                    # model wrote - a statement that wraps, an off-by-one in
                    # counting - and is still evidence when it is there. The
                    # finding is corrected to the line that holds it; a quote
                    # found nowhere near is not evidence at all. Measured on
                    # the pilot review of 7cdd4af4: seven of eight findings
                    # were rejected for a quote one line from its number.
                    where = _nearby(lines, finding.line, finding.evidence)
                    if where is None:
                        reason = "quotes evidence that is not at or near that line"
                    elif where != finding.line:
                        finding = Finding(
                            finding.file, where, finding.severity, finding.title,
                            finding.explanation, finding.evidence,
                        )
            if reason is None:
                kept.append(finding)
            else:
                rejected.append({**finding.as_dict(), "rejected": reason})
        return kept, rejected

    # ---------------------------------------------------------- the contract

    def tool_name(self, action: Any) -> str:
        return _TOOLS.get(type(action), "unknown")

    def arguments(self, action: Any) -> dict[str, Any]:
        return {name: getattr(action, name) for name in getattr(action, "__dataclass_fields__", {})}

    # The step's key without its attempt number.
    def _base_key(self, action: Any) -> str:
        return f"{self.tool_name(action)}:{json.dumps(self.arguments(action), sort_keys=True)}"

    # A retried step is a new key, so the repeat guard - which is for a
    # router asking for the same thing twice - does not stop a bounded retry
    # of a read or an analysis that failed for a transient reason.
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
        if isinstance(action, ReadFile):
            detail = f" {action.path}"
        if isinstance(action, WriteFindings) and outcome:
            detail = f" ({len(outcome.get('findings') or [])} findings, {len(outcome.get('rejected') or [])} rejected)"
        suffix = "" if went == "done" else f" [{went}]"
        return f"{what}{detail}{suffix}"

    def needs_approval(self, action: Any) -> bool:
        return False

    def approval_summary(self, action: Any) -> str:
        return ""

    # A read that was dispatched and never heard from can simply be done
    # again: nothing outside this system changed.
    async def reconcile(self, action: Any, prior: dict[str, Any]) -> dict[str, Any] | None:
        return {"kind": "failed", "error": "redone after an interrupted read"}

    async def verify(self, result: TurnResult, run: dict[str, Any]) -> Verification:
        state = self.state
        read_all = state.summary is not None and state.diff is not None and state.chosen is not None and all(
            path in state.contents for path in state.chosen
        )
        written = state.review is not None
        accepted = bool(read_all and written)
        evidence = {
            "commit": (state.summary or {}).get("sha") or self.commit,
            "subject": (state.summary or {}).get("subject", ""),
            "files_changed": [item.get("path") for item in (state.summary or {}).get("files") or []],
            "files_read": sorted(state.contents),
            "findings": [finding.as_dict() for finding in (state.review.findings if state.review else ())],
            "rejected": state.rejected,
            "unknowns": list(state.review.unknowns) if state.review else [],
            "read_only_tools": sorted(READ_TOOLS),
        }
        summary = state.review.summary if state.review else "the review did not finish"
        return Verification(accepted, evidence, summary)
