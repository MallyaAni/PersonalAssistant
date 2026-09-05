"""The security investigation as a durable run.

Built on the reviewer's world: the same fixed stages (summary, diff, chosen
files, findings), the same read-only window, the same evidence check that
drops a finding whose quoted line is not there. Two things differ.

**Scope is checked before anything is read.** A run names the asset it may
investigate; the world refuses a run whose asset is not one the operator
authorized (`SECURITY_AUTHORIZED_ASSETS`), with `Unavailable` and a reason,
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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.agents.review.prompts import ReviewPrompts
from backend.agents.review.world import ReviewWorld, WriteFindings
from backend.config.settings import settings
from backend.services.turn_steps import Act, Decision, Unavailable

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
    "password_assignment": "password=",
    "secret_assignment": "secret=",
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


@dataclass(frozen=True, slots=True)
class GrepShape:
    """One deterministic search of the commit for a shape."""

    name: str
    pattern: str
    commit: str


# The asset a run names, from its objective: "investigate <asset> at <sha>".
def asset_of(objective: str) -> str:
    match = re.search(r"\basset[:=\s]+([A-Za-z0-9_./-]+)", str(objective or ""))
    return match.group(1) if match else ""


# The assets the operator authorized, as a set; empty means none.
def authorized_assets() -> frozenset[str]:
    raw = str(getattr(settings, "SECURITY_AUTHORIZED_ASSETS", "") or "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


class SecurityWorld(ReviewWorld):
    """A read-only security investigation of one commit."""

    def __init__(self, run: dict[str, Any], invocation: Any, prompts: ReviewPrompts, server_id: str = "repo") -> None:
        super().__init__(run, invocation, prompts, server_id)
        self.asset = asset_of(str(run.get("objective") or ""))
        self.shapes_done: set[str] = set()
        self.shape_hits: list[dict[str, Any]] = []

    # Refuse an unauthorized asset before any read; then the reviewer's
    # stages, with the shape greps between the reads and the findings.
    async def decide(self, lines: list[str]) -> Decision:
        allowed = authorized_assets()
        if not self.asset:
            return Unavailable("the run names no asset to investigate")
        if self.asset not in allowed:
            return Unavailable(f"asset {self.asset} is not authorized for investigation")
        decision = await super().decide(lines)
        if isinstance(decision, Act) and isinstance(decision.action, WriteFindings):
            for name, pattern in {**SECRET_SHAPES, **DANGEROUS_CALL_SHAPES}.items():
                if name not in self.shapes_done:
                    return Act(GrepShape(name, pattern, self.commit))
        return decision

    async def apply(self, action: Any) -> tuple[str, dict[str, Any]] | None:
        if isinstance(action, GrepShape):
            outcome = await self._call("repo_grep", {"pattern": action.pattern, "commit": action.commit})
            return "read", outcome
        return await super().apply(action)

    def observe(self, action: Any, kind: str, outcome: dict[str, Any]) -> None:
        if isinstance(action, GrepShape):
            self.shapes_done.add(action.name)
            payload = outcome.get("payload") if str(outcome.get("kind")) == "done" else None
            for match in (payload or {}).get("matches") or []:
                self.shape_hits.append({"shape": action.name, **match})
            return
        super().observe(action, kind, outcome)

    def tool_name(self, action: Any) -> str:
        if isinstance(action, GrepShape):
            return "repo_grep"
        if isinstance(action, WriteFindings):
            return "security_findings"
        return super().tool_name(action)

    def arguments(self, action: Any) -> dict[str, Any]:
        if isinstance(action, GrepShape):
            return {"pattern": action.pattern, "commit": action.commit, "shape": action.name}
        return super().arguments(action)

    def describe(self, action: Any, kind: str, outcome: dict[str, Any] | None) -> str:
        if isinstance(action, GrepShape):
            hits = len(((outcome or {}).get("payload") or {}).get("matches") or []) if outcome else 0
            went = str((outcome or {}).get("kind") or "")
            return f"repo_grep {action.name} ({hits} matches)" + ("" if went == "done" else f" [{went}]")
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
        return type(verification)(verification.accepted, evidence, verification.summary)
