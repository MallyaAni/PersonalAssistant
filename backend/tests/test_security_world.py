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
from backend.agents.review.prompts import Finding
from backend.agents.security.prompts import Judgement, render_hit
from backend.agents.security.world import (
    DANGEROUS_CALL_SHAPES,
    MAX_JUDGEMENT_ATTEMPTS,
    SECRET_SHAPES,
    GrepShape,
    JudgeHits,
    SecurityWorld,
    asset_of,
    covered,
    hit_for,
)
from backend.config.settings import settings
from backend.services.turn_steps import Act, Done, Refused, Unavailable

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
    assert isinstance(refused, Refused)
    assert "other-repo" in refused.reason
    nothing = await _world("investigate abcdef1").decide([])
    assert isinstance(nothing, Refused)
    monkeypatch.setattr(settings, "SECURITY_AUTHORIZED_ASSETS", "")
    none_allowed = await _world("investigate asset: anios at abcdef1").decide([])
    assert isinstance(none_allowed, Refused)


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
    # The findings left the flagged line out, so it goes to the judgement
    # before the run is done; dismissed with a reason, the run completes and
    # the report carries the dismissal.
    world.observe(WriteFindings("abcdef1"), "analysis", {"kind": "done", "findings": [], "rejected": [], "summary": "clean", "unknowns": []})
    judged = await world.decide([])
    assert judged == Act(JudgeHits("abcdef1"))
    assert world.tool_name(judged.action) == "security_judge_hits"
    world.observe(
        JudgeHits("abcdef1"), "analysis",
        {"kind": "done", "findings": [], "rejected": [], "dismissed": [{"path": "a.py", "line": 1, "reason": "a constant, not a key"}], "unjudged": []},
    )
    assert isinstance(await world.decide([]), Done)
    verification = await world.verify(None, {})
    assert verification.evidence["dismissed"] == [{"path": "a.py", "line": 1, "reason": "a constant, not a key"}]
    assert verification.evidence["unjudged"] == []


async def test_a_grep_is_a_read_named_for_its_shape(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_AUTHORIZED_ASSETS", "anios")
    world = _world("investigate asset: anios at abcdef1")
    grep = GrepShape("shell_true", "shell=True", "abcdef1")
    assert world.tool_name(grep) == "repo_grep"
    assert world.arguments(grep)["shape"] == "shell_true"
    assert world.needs_approval(grep) is False
    assert world.creates(grep) is False
    assert world.tool_name(WriteFindings("abcdef1")) == "security_findings"


# ------------------------------------------------- the judgement of hits


# A world past its reads with one flagged line in a read file.
async def _judging_world(monkeypatch, findings=()):
    monkeypatch.setattr(settings, "SECURITY_AUTHORIZED_ASSETS", "anios")
    world = _world("investigate asset: anios at abcdef1")
    world.observe(ShowCommit("abcdef1"), "read", {"kind": "done", "payload": {"sha": "abcdef1", "files": [{"path": "a.py"}]}})
    world.observe(ReadDiff("abcdef1"), "read", {"kind": "done", "payload": {"diff": "+x"}})
    world.state.chosen = ["a.py"]
    world.observe(
        ReadFile("a.py", "abcdef1"), "read",
        {"kind": "done", "payload": {"content": '    1| import os\n    2| KEY = "AKIAEXAMPLE"\n    3| \n    4| def f():\n    5|     return 1\n'}},
    )
    for name, pattern in {**SECRET_SHAPES, **DANGEROUS_CALL_SHAPES}.items():
        world.observe(
            GrepShape(name, pattern, "abcdef1"), "read",
            {"kind": "done", "payload": {"matches": [{"path": "a.py", "line": 2, "text": 'KEY = "AKIAEXAMPLE"'}] if name == "aws_access_key" else []}},
        )
    world.observe(
        WriteFindings("abcdef1"), "analysis",
        {"kind": "done", "findings": [f.as_dict() for f in findings], "rejected": [], "summary": "s", "unknowns": []},
    )
    return world


def test_a_hit_is_covered_by_a_finding_within_the_evidence_tolerance():
    hit = {"path": "a.py", "line": 2}
    assert covered(hit, (Finding("a.py", 3, "high", "t", "e", "x"),))
    assert not covered(hit, (Finding("a.py", 9, "high", "t", "e", "x"),))
    assert not covered(hit, (Finding("b.py", 2, "high", "t", "e", "x"),))


async def test_a_hit_the_findings_covered_is_not_judged_again(monkeypatch):
    world = await _judging_world(monkeypatch, (Finding("a.py", 2, "high", "key", "hard-coded key", 'KEY = "AKIAEXAMPLE"'),))
    assert world.unaccounted_hits() == []
    assert isinstance(await world.decide([]), Done)


async def test_a_hit_reported_by_the_judgement_passes_the_evidence_check_and_joins_the_findings(monkeypatch):
    world = await _judging_world(monkeypatch)
    seen = []

    async def judge(rendered):
        seen.extend(rendered)
        return [Judgement("a.py", 2, Finding("a.py", 2, "high", "Hard-coded key", "a live-looking key in source", "KEY = "), "")]

    world.judge.judge = judge  # type: ignore[method-assign]
    kind, outcome = await world.apply(JudgeHits("abcdef1"))
    assert kind == "analysis"
    # The flagged line was shown with the code around it, marked.
    assert ">>    2| KEY" in seen[0]
    assert "    1| import os" in seen[0]
    assert outcome["findings"][0]["evidence"] == 'KEY = "AKIAEXAMPLE"'
    assert outcome["dismissed"] == [] and outcome["unjudged"] == []
    world.observe(JudgeHits("abcdef1"), "analysis", outcome)
    assert [f.title for f in world.state.review.findings] == ["Hard-coded key"]
    assert isinstance(await world.decide([]), Done)


async def test_a_judgement_that_invents_its_evidence_is_rejected_not_kept(monkeypatch):
    world = await _judging_world(monkeypatch)

    async def judge(rendered):
        return [Judgement("a.py", 2, Finding("a.py", 2, "high", "t", "explained here", "SECRET = 'nothing like it'"), "")]

    world.judge.judge = judge  # type: ignore[method-assign]
    _, outcome = await world.apply(JudgeHits("abcdef1"))
    assert outcome["findings"] == []
    assert "near" in outcome["rejected"][0]["rejected"]


async def test_a_hit_the_judgement_did_not_answer_is_named_unjudged(monkeypatch):
    world = await _judging_world(monkeypatch)

    async def judge(rendered):
        return []

    world.judge.judge = judge  # type: ignore[method-assign]
    _, outcome = await world.apply(JudgeHits("abcdef1"))
    assert outcome["unjudged"] == [{"path": "a.py", "line": 2, "shape": "aws_access_key"}]


async def test_a_judgement_that_keeps_failing_ends_with_the_hits_marked_unjudged(monkeypatch):
    world = await _judging_world(monkeypatch)

    async def judge(rendered):
        return None

    world.judge.judge = judge  # type: ignore[method-assign]
    for _ in range(MAX_JUDGEMENT_ATTEMPTS):
        decision = await world.decide([])
        assert decision == Act(JudgeHits("abcdef1"))
        kind, outcome = await world.apply(decision.action)
        assert outcome["kind"] == "failed"
        world.observe(decision.action, kind, outcome)
    assert isinstance(await world.decide([]), Done)
    verification = await world.verify(None, {})
    assert verification.evidence["dismissed"] == []
    assert verification.evidence["unjudged"] == [{"path": "a.py", "line": 2, "shape": "aws_access_key"}]


def test_the_rendered_hit_marks_its_line_and_bounds_the_context():
    lines = {n: f"line {n}" for n in range(1, 40)}
    shown = render_hit({"shape": "eval", "path": "a.py", "line": 20}, lines)
    assert shown.startswith("flagged as eval: a.py:20")
    assert ">>   20| line 20" in shown
    assert "line 14" in shown and "line 26" in shown
    assert "line 13" not in shown and "line 27" not in shown


# The judge's answer is about a line the world gave it, so a path written
# the way the rendering names it, or a wrong line beside the right order,
# still lands on that hit; an answer about nothing shown lands nowhere.
def test_a_judgement_is_bound_to_the_hit_it_is_about():
    shown = [{"path": "a.py", "line": 2, "shape": "aws_access_key"}, {"path": "b.py", "line": 9, "shape": "eval"}]
    assert hit_for("a.py", 2, 1, shown, 2) is shown[0]
    assert hit_for("b.py:9", 9, 0, shown, 2) is shown[1]
    assert hit_for("a.py", 3, 0, shown, 2) is shown[0]
    assert hit_for("a.py", 3, 0, shown, 1) is None
    assert hit_for("zzz.py", 1, 5, shown, 2) is None


async def test_a_reported_weakness_lands_at_its_hit_even_when_the_path_carries_the_line(monkeypatch):
    world = await _judging_world(monkeypatch)

    async def judge(rendered):
        return [Judgement("a.py:2", 2, Finding("a.py:2", 2, "high", "Hard-coded key", "a key in source", 'KEY = "AKIAEXAMPLE"'), "")]

    world.judge.judge = judge  # type: ignore[method-assign]
    _, outcome = await world.apply(JudgeHits("abcdef1"))
    assert outcome["rejected"] == []
    assert (outcome["findings"][0]["file"], outcome["findings"][0]["line"]) == ("a.py", 2)
    assert outcome["unjudged"] == []
