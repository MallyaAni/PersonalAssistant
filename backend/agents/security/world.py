"""The security investigation as a durable run.

Built on the reviewer's world: the same fixed stages (summary, diff, chosen
files, findings), the same read-only window, the same evidence check that
drops a finding whose quoted line is not there. Three things differ.

**Scope is checked before anything is read.** A run names the asset it may
investigate; the world refuses a run whose asset is not one the operator
authorized (`SECURITY_AUTHORIZED_ASSETS`), with `Refused` and a reason,
before a single tool is called. The repo server's root is set by
environment, so even a run that got past this could read only that
repository; this check is what makes "out of scope" a recorded refusal
rather than a silent success on the wrong thing.

**Shapes are found by code and judged by the model.** Before the findings
step the world greps the commit for lines shaped like a secret or a
dangerous call. A pattern is legitimate for shape - "does this string look
like a key" - and never for intent; whether a flagged line is a weakness is
the model's judgement with the surrounding code in front of it, and the
evidence check still applies to what it reports.

**Every flagged line is accounted for.** A flagged line the findings step
left out is put back in front of the model, with the code around it, for a
verdict: a finding, checked like every other, or a dismissal with a reason.
Nothing a grep found leaves the report unmentioned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.agents.review.prompts import Finding, Review, ReviewPrompts
from backend.agents.review.world import (
    EVIDENCE_TOLERANCE_LINES,
    ReviewWorld,
    WriteFindings,
    _lines_of,
)
from backend.agents.security.prompts import MAX_JUDGED_HITS, HitJudge, render_hit
from backend.config.settings import settings
from backend.services.turn_steps import Act, Decision, Done, Refused

KIND = "security_review"

# Shapes worth showing the model, by name. Each is a fixed string git grep
# can search for; the world runs them all and hands the model what matched.
SECRET_SHAPES: dict[str, str] = {
    "aws_access_key": "AKIA",
    "private_key_block": "-----BEGIN",
    "openai_style_key": "sk-",
    "github_token": "ghp_",
    "slack_token": "xox",
    "bearer_literal": "Bearer ",
    # The egress screen withholds any argument carrying "password" or
    # "api_key" as credential-shaped, so those words cannot be searched for
    # through the boundary; these two shapes are the nearest it lets pass.
    "secret_key_assignment": "secret_key",
    "token_assignment": "token=",
}
DANGEROUS_CALL_SHAPES: dict[str, str] = {
    "shell_true": "shell=True",
    "eval": "eval(",
    "exec": "exec(",
    "pickle_loads": "pickle.loads",
    "yaml_load": "yaml.load(",
    "verify_false": "verify=False",
    "os_system": "os.system(",
}

# How many times the judgement step may fail before the report goes out
# with the hits marked unjudged instead.
MAX_JUDGEMENT_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class GrepShape:
    """One deterministic search of the commit for a shape."""

    name: str
    pattern: str
    commit: str


@dataclass(frozen=True, slots=True)
class JudgeHits:
    """One judgement over the flagged lines the findings left out."""

    commit: str


# The asset a run names, from its objective: "investigate <asset> at <sha>".
def asset_of(objective: str) -> str:
    match = re.search(r"\basset[:=\s]+([A-Za-z0-9_./-]+)", str(objective or ""))
    return match.group(1) if match else ""


# The assets the operator authorized, as a set; empty means none.
def authorized_assets() -> frozenset[str]:
    raw = str(getattr(settings, "SECURITY_AUTHORIZED_ASSETS", "") or "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


# Whether a kept finding covers a flagged line: same file, within the
# evidence tolerance, so a finding corrected by a line still counts.
def covered(hit: dict[str, Any], findings: tuple[Finding, ...]) -> bool:
    path = str(hit.get("path") or "")
    line = int(hit.get("line") or 0)
    return any(
        finding.file == path and abs(finding.line - line) <= EVIDENCE_TOLERANCE_LINES
        for finding in findings
    )


# A hit as the report names it: where it is and what shape flagged it.
def _named(hit: dict[str, Any]) -> dict[str, Any]:
    return {"path": hit.get("path"), "line": hit.get("line"), "shape": hit.get("shape")}


# The shown hit a judgement is about. The judge answers about lines the
# world gave it, so the identity of each is the world's: an exact path and
# line wins; a path written the way the rendering names it (`file.py:12`)
# is read back; and when the model answered once per hit, in order, the
# position decides. None when the answer is about nothing shown.
def hit_for(
    path: str, line: int, index: int, shown: list[dict[str, Any]], answered: int
) -> dict[str, Any] | None:
    for hit in shown:
        if str(hit.get("path")) == path and int(hit.get("line") or 0) == line:
            return hit
    for hit in shown:
        if path == f"{hit.get('path')}:{hit.get('line')}":
            return hit
    if answered == len(shown) and 0 <= index < len(shown):
        return shown[index]
    return None


class SecurityWorld(ReviewWorld):
    """A read-only security investigation of one commit."""

    def __init__(self, run: dict[str, Any], invocation: Any, prompts: ReviewPrompts, server_id: str = "repo") -> None:
        super().__init__(run, invocation, prompts, server_id)
        self.asset = asset_of(str(run.get("objective") or ""))
        self.shapes_done: set[str] = set()
        self.shape_hits: list[dict[str, Any]] = []
        self.judge = HitJudge(prompts.writer, prompts.max_tokens)
        # None until the judgement step has run; then what it dismissed, and
        # separately what it was not shown or did not answer.
        self.dismissed: list[dict[str, Any]] | None = None
        self.unjudged: list[dict[str, Any]] = []

    # The flagged lines no kept finding covers, in files that were read.
    def unaccounted_hits(self) -> list[dict[str, Any]]:
        findings = self.state.review.findings if self.state.review else ()
        return [
            hit for hit in self.shape_hits
            if not covered(hit, findings) and str(hit.get("path") or "") in self.state.contents
        ]

    # Refuse an unauthorized asset before any read; then the reviewer's
    # stages, with the shape greps between the reads and the findings, and
    # the judgement of unaccounted hits after the findings.
    async def decide(self, lines: list[str]) -> Decision:
        allowed = authorized_assets()
        if not self.asset:
            return Refused("the run names no asset to investigate")
        if self.asset not in allowed:
            return Refused(f"asset {self.asset} is not authorized for investigation")
        decision = await super().decide(lines)
        if isinstance(decision, Act) and isinstance(decision.action, WriteFindings):
            for name, pattern in {**SECRET_SHAPES, **DANGEROUS_CALL_SHAPES}.items():
                if name not in self.shapes_done:
                    return Act(GrepShape(name, pattern, self.commit))
        if isinstance(decision, Done) and self.dismissed is None and self.unaccounted_hits():
            pending = JudgeHits(self.commit)
            if self.state.failures.get(self._base_key(pending), 0) >= MAX_JUDGEMENT_ATTEMPTS:
                # The judgement could not be had; the report marks the hits
                # unjudged rather than pretending they were cleared.
                return decision
            return Act(pending)
        return decision

    async def apply(self, action: Any) -> tuple[str, dict[str, Any]] | None:
        if isinstance(action, GrepShape):
            outcome = await self._call("repo_grep", {"pattern": action.pattern, "commit": action.commit})
            return "read", outcome
        if isinstance(action, JudgeHits):
            hits = self.unaccounted_hits()
            shown, rest = hits[:MAX_JUDGED_HITS], hits[MAX_JUDGED_HITS:]
            rendered = [render_hit(hit, _lines_of(self.state.contents[str(hit["path"])])) for hit in shown]
            judgements = await self.judge.judge(rendered)
            if judgements is None:
                return "analysis", {"kind": "failed", "error": "the model did not answer"}
            # Each verdict is bound to the hit it is about, and a reported
            # weakness is placed at that hit's file and line; only the quoted
            # evidence is the model's, and the check still judges it.
            bound: list[tuple[dict[str, Any], Any]] = []
            for index, judgement in enumerate(judgements):
                hit = hit_for(judgement.path, judgement.line, index, shown, len(judgements))
                if hit is not None:
                    bound.append((hit, judgement))
            reported = tuple(
                Finding(
                    str(hit["path"]), int(hit["line"]), j.finding.severity,
                    j.finding.title, j.finding.explanation, j.finding.evidence,
                )
                for hit, j in bound if j.finding is not None
            )
            kept, rejected = self._check(Review(reported, "", ()))
            dismissed = [
                {"path": hit.get("path"), "line": hit.get("line"), "reason": j.reason or "not a weakness"}
                for hit, j in bound if j.finding is None
            ]
            answered = {id(hit) for hit, _ in bound}
            unanswered = [_named(hit) for hit in shown if id(hit) not in answered]
            return "analysis", {
                "kind": "done",
                "findings": [finding.as_dict() for finding in kept],
                "rejected": rejected,
                "dismissed": dismissed,
                "unjudged": unanswered + [_named(hit) for hit in rest],
            }
        return await super().apply(action)

    def observe(self, action: Any, kind: str, outcome: dict[str, Any]) -> None:
        if isinstance(action, GrepShape):
            self.shapes_done.add(action.name)
            payload = outcome.get("payload") if str(outcome.get("kind")) == "done" else None
            for match in (payload or {}).get("matches") or []:
                self.shape_hits.append({"shape": action.name, **match})
            return
        if isinstance(action, JudgeHits):
            if str(outcome.get("kind")) != "done":
                super().observe(action, kind, outcome)
                return
            review = self.state.review or Review((), "", ())
            added = tuple(Finding(**item) for item in outcome.get("findings") or [])
            self.state.review = Review(review.findings + added, review.summary, review.unknowns)
            self.state.rejected.extend(outcome.get("rejected") or [])
            self.dismissed = list(outcome.get("dismissed") or [])
            self.unjudged = list(outcome.get("unjudged") or [])
            return
        super().observe(action, kind, outcome)

    def tool_name(self, action: Any) -> str:
        if isinstance(action, GrepShape):
            return "repo_grep"
        if isinstance(action, JudgeHits):
            return "security_judge_hits"
        if isinstance(action, WriteFindings):
            return "security_findings"
        return super().tool_name(action)

    def arguments(self, action: Any) -> dict[str, Any]:
        if isinstance(action, GrepShape):
            return {"pattern": action.pattern, "commit": action.commit, "shape": action.name}
        return super().arguments(action)

    def describe(self, action: Any, kind: str, outcome: dict[str, Any] | None) -> str:
        went = str((outcome or {}).get("kind") or "") if outcome else ""
        suffix = "" if not outcome or went == "done" else f" [{went}]"
        if isinstance(action, GrepShape):
            hits = len(((outcome or {}).get("payload") or {}).get("matches") or []) if outcome else 0
            return f"repo_grep {action.name} ({hits} matches){suffix}"
        if isinstance(action, JudgeHits):
            detail = ""
            if outcome:
                detail = (
                    f" ({len(outcome.get('findings') or [])} reported, "
                    f"{len(outcome.get('dismissed') or [])} dismissed)"
                )
            return f"security_judge_hits{detail}{suffix}"
        return super().describe(action, kind, outcome)

    # The findings step sees the flagged lines beside the files.
    async def _findings_contents(self) -> dict[str, str]:
        contents = dict(self.state.contents)
        if self.shape_hits:
            flagged = "\n".join(
                f"{hit['shape']}: {hit.get('path')}:{hit.get('line')}: {str(hit.get('text') or '')[:200]}"
                for hit in self.shape_hits[:60]
            )
            contents["(pattern search: lines shaped like a secret or a dangerous call)"] = flagged
        return contents

    async def verify(self, result, run):
        verification = await super().verify(result, run)
        evidence = dict(verification.evidence)
        evidence["asset"] = self.asset
        evidence["shapes_searched"] = sorted(self.shapes_done)
        evidence["shape_hits"] = self.shape_hits[:60]
        evidence["dismissed"] = list(self.dismissed or [])
        # Hits neither reported nor dismissed - not shown to the judgement,
        # not answered by it, or the judgement never happened - are named,
        # never silently absent.
        unjudged = list(self.unjudged)
        if self.dismissed is None:
            unjudged.extend(_named(hit) for hit in self.unaccounted_hits())
        evidence["unjudged"] = unjudged
        return type(verification)(verification.accepted, evidence, verification.summary)
