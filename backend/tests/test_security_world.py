"""The security investigation refuses what it was not given, and searches for
shapes before it judges.

The world reuses the reviewer's stages, so what is pinned here is what it
adds: the scope check that runs before any read, the grep stages that sit
between the reads and the findings, the flagged lines reaching the findings
step as material, and the evidence carrying the asset and the shapes.
"""

from __future__ import annotations

import pytest

from backend.agents.review.prompts import ReviewPrompts
from backend.agents.review.world import ReadDiff, ReadFile, ShowCommit, WriteFindings
from backend.agents.security.world import (
    DANGEROUS_CALL_SHAPES,
    SECRET_SHAPES,
    GrepShape,
    SecurityWorld,
    asset_of,
)
from backend.config.settings import settings
from backend.services.turn_steps import Act, Done, Unavailable

pytestmark = pytest.mark.asyncio


class _NoInvocation:
    async def invoke(self, *args, **kwargs):
        raise AssertionError("no tool may be called")


def _world(objective: str) -> SecurityWorld:
    return SecurityWorld({"id": "r", "objective": objective}, _NoInvocation(), ReviewPrompts(None))  # type: ignore[arg-type]


def test_the_asset_is_read_from_the_objective():
    assert asset_of("investigate asset: anios at abcdef1") == "anios"
    assert asset_of("asset=payments-api commit abcdef1") == "payments-api"
    assert asset_of("review commit abcdef1") == ""


async def test_an_unauthorized_or_missing_asset_is_refused_before_any_read(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_AUTHORIZED_ASSETS", "anios")
    refused = await _world("investigate asset: other-repo at abcdef1").decide([])
    assert isinstance(refused, Unavailable)
    assert "other-repo" in refused.reason
    nothing = await _world("investigate abcdef1").decide([])
    assert isinstance(nothing, Unavailable)
    monkeypatch.setattr(settings, "SECURITY_AUTHORIZED_ASSETS", "")
    none_allowed = await _world("investigate asset: anios at abcdef1").decide([])
    assert isinstance(none_allowed, Unavailable)


async def test_an_authorized_asset_follows_the_reviewers_stages_with_greps_before_findings(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_AUTHORIZED_ASSETS", "anios, payments-api")
    world = _world("investigate asset: anios at abcdef1")
    first = await world.decide([])
    assert first == Act(ShowCommit("abcdef1"))
    world.observe(ShowCommit("abcdef1"), "read", {"kind": "done", "payload": {"sha": "abcdef1", "files": [{"path": "a.py"}]}})
    assert (await world.decide([])) == Act(ReadDiff("abcdef1"))
    world.observe(ReadDiff("abcdef1"), "read", {"kind": "done", "payload": {"diff": "+x"}})
    world.state.chosen = ["a.py"]
    assert (await world.decide([])) == Act(ReadFile("a.py", "abcdef1"))
    world.observe(ReadFile("a.py", "abcdef1"), "read", {"kind": "done", "payload": {"content": "    1| x = 1"}})
    # Every shape is searched, once each, before the findings are written.
    searched = []
    for _ in range(len(SECRET_SHAPES) + len(DANGEROUS_CALL_SHAPES)):
        decision = await world.decide([])
        assert isinstance(decision, Act)
        assert isinstance(decision.action, GrepShape), decision
        searched.append(decision.action.name)
        world.observe(
            decision.action,
            "read",
            {"kind": "done", "payload": {"matches": [{"path": "a.py", "line": 1, "text": "x = 1"}] if decision.action.name == "aws_access_key" else []}},
        )
    assert set(searched) == set(SECRET_SHAPES) | set(DANGEROUS_CALL_SHAPES)
    assert (await world.decide([])) == Act(WriteFindings("abcdef1"))
    # The flagged lines reach the findings step as material beside the files.
    shown = await world._findings_contents()
    assert "a.py" in shown
    assert any("aws_access_key" in value for key, value in shown.items() if key != "a.py")
    world.observe(WriteFindings("abcdef1"), "analysis", {"kind": "done", "findings": [], "rejected": [], "summary": "clean", "unknowns": []})
    assert isinstance(await world.decide([]), Done)


async def test_a_grep_is_a_read_named_for_its_shape(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_AUTHORIZED_ASSETS", "anios")
    world = _world("investigate asset: anios at abcdef1")
    grep = GrepShape("shell_true", "shell=True", "abcdef1")
    assert world.tool_name(grep) == "repo_grep"
    assert world.arguments(grep)["shape"] == "shell_true"
    assert world.needs_approval(grep) is False
    assert world.creates(grep) is False
    assert world.tool_name(WriteFindings("abcdef1")) == "security_findings"
