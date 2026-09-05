"""The read-only repository window, and the review's evidence check.

The repo server is the only way the reviewer touches code, so what it
refuses matters as much as what it returns: no path may climb, no commit may
be a moving name, every output is bounded. The review keeps a finding only
when the quoted line is actually at that line of a file it read; these pin
both halves without a model.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.agents.review.prompts import Finding, Review, ReviewPrompts
from backend.agents.review.world import ReadFile, ReviewWorld, ShowCommit, WriteFindings
from backend.mcp.servers import repo as repo_server


# A tiny repository with two commits, the second changing one file.
@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
            env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@x", "PATH": __import__("os").environ["PATH"],
                 "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
        ).stdout

    git("init", "-q")
    (root / "calc.py").write_text("def average(xs):\n    return sum(xs) / len(xs)\n", encoding="utf-8")
    (root / "README.md").write_text("calc\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "first")
    (root / "calc.py").write_text(
        "def average(xs):\n    if not xs:\n        return 0\n    return sum(xs) / len(xs)\n\n\n"
        "def last(items):\n    return items[len(items)]\n",
        encoding="utf-8",
    )
    git("add", ".")
    git("commit", "-q", "-m", "guard empty; add last")
    sha = git("rev-parse", "HEAD").strip()
    return root, sha


def test_show_commit_and_diff_are_bounded_and_named(repository):
    root, sha = repository
    shown = repo_server.show_commit(sha, root=root)
    assert shown["sha"] == sha
    assert [item["path"] for item in shown["files"]] == ["calc.py"]
    changed = repo_server.diff(sha, root=root)
    assert "+def last(items):" in changed["diff"]
    assert changed["truncated"] is False
    only = repo_server.diff(sha, path="calc.py", root=root)
    assert "calc.py" in only["diff"]


def test_read_file_numbers_lines_and_bounds_the_slice(repository):
    root, sha = repository
    read = repo_server.read_file("calc.py", sha, root=root)
    assert read["total_lines"] == 8
    assert read["content"].splitlines()[0].startswith("    1| def average")
    sliced = repo_server.read_file("calc.py", sha, start=7, end=8, root=root)
    assert sliced["start"] == 7
    assert sliced["end"] == 8
    assert "items[len(items)]" in sliced["content"]


def test_grep_and_log(repository):
    root, sha = repository
    found = repo_server.grep("len(items)", sha, root=root)
    assert found["matches"]
    assert found["matches"][0]["path"] == "calc.py"
    assert found["matches"][0]["line"] == 8
    assert len(repo_server.log(5, root=root)["commits"]) == 2


@pytest.mark.parametrize("path", ["../secrets", "/etc/passwd", "C:/Windows/x", "~/.ssh/id"])
def test_a_path_that_climbs_or_is_absolute_is_refused(path):
    with pytest.raises(repo_server.RepoToolError):
        repo_server.safe_path(path)


def test_a_commit_must_be_a_hash_not_a_moving_name(repository):
    root, _ = repository
    with pytest.raises(repo_server.RepoToolError):
        repo_server.resolve_commit("main", root=root)
    with pytest.raises(repo_server.RepoToolError):
        repo_server.resolve_commit("HEAD; rm -rf /", root=root)
    assert len(repo_server.resolve_commit("HEAD", root=root)) == 40


def test_the_root_comes_only_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("REPO_MCP_ROOT", raising=False)
    with pytest.raises(repo_server.RepoToolError):
        repo_server.repo_root()
    monkeypatch.setenv("REPO_MCP_ROOT", str(tmp_path))
    with pytest.raises(repo_server.RepoToolError):
        repo_server.repo_root()


# ------------------------------------------------------------ the check


class _NoInvocation:
    async def invoke(self, *args, **kwargs):
        raise AssertionError("the check must not call anything")


def _world() -> ReviewWorld:
    world = ReviewWorld(
        {"id": "r", "objective": "review commit abcdef1"},
        _NoInvocation(),  # type: ignore[arg-type]
        ReviewPrompts(None),  # type: ignore[arg-type]
    )
    world.observe(
        ShowCommit("abcdef1"),
        "read",
        {"kind": "done", "payload": {"sha": "abcdef1", "files": [{"path": "calc.py"}]}},
    )
    world.observe(
        ReadFile("calc.py", "abcdef1"),
        "read",
        {
            "kind": "done",
            "payload": {
                "content": "    1| def last(items):\n    2|     return items[len(items)]\n"
            },
        },
    )
    return world


def _finding(**overrides) -> Finding:
    base = {
        "file": "calc.py",
        "line": 2,
        "severity": "high",
        "title": "off by one",
        "explanation": "indexes one past the end, IndexError on every call",
        "evidence": "return items[len(items)]",
    }
    base.update(overrides)
    return Finding(**base)


def test_a_finding_whose_evidence_is_the_cited_line_is_kept():
    kept, rejected = _world()._check(Review((_finding(),), "", ()))
    assert len(kept) == 1
    assert rejected == []


def test_whitespace_does_not_decide_the_evidence():
    kept, _ = _world()._check(Review((_finding(evidence="  return   items[len(items)]  "),), "", ()))
    assert len(kept) == 1


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"file": "other.py"}, "did not change"),
        ({"line": 9}, "outside what was read"),
        ({"evidence": "return items[len(items) - 1]"}, "near that line"),
    ],
)
def test_a_finding_without_evidence_in_the_code_is_rejected(overrides, reason):
    kept, rejected = _world()._check(Review((_finding(**overrides),), "", ()))
    assert kept == []
    assert reason in rejected[0]["rejected"]


def test_a_finding_about_a_changed_file_that_was_not_read_is_rejected():
    world = _world()
    world.state.summary["files"].append({"path": "README.md"})
    kept, rejected = world._check(Review((_finding(file="README.md", line=1, evidence="calc"),), "", ()))
    assert kept == []
    assert "did not read" in rejected[0]["rejected"]


def test_the_world_only_ever_names_read_tools_and_the_findings_step():
    world = _world()
    assert world.tool_name(ShowCommit("x")) == "repo_show_commit"
    assert world.tool_name(ReadFile("a", "x")) == "repo_read_file"
    assert world.tool_name(WriteFindings("x")) == "review_findings"
    assert world.needs_approval(WriteFindings("x")) is False
    assert world.creates(WriteFindings("x")) is False


# A step that failed for a transient reason is tried again under a fresh key
# - the repeat guard is for a router asking twice, not for a dropped read -
# and a step that keeps failing ends the review with its reason.
@pytest.mark.asyncio
async def test_a_failed_step_is_retried_under_a_fresh_key_then_given_up():
    from backend.agents.review.world import MAX_STEP_ATTEMPTS, WriteFindings
    from backend.services.turn_steps import Act, Unavailable

    world = _world()
    world.observe(
        ReadFile("calc.py", "abcdef1"), "read", {"kind": "done", "payload": {"content": ""}}
    )
    world.state.diff = "+x"
    world.state.chosen = ["calc.py"]
    first = world.key(WriteFindings("abcdef1"))
    world.observe(WriteFindings("abcdef1"), "analysis", {"kind": "failed", "error": "timed out"})
    second = world.key(WriteFindings("abcdef1"))
    assert first != second
    assert isinstance(await world.decide([]), Act)
    for _ in range(MAX_STEP_ATTEMPTS - 1):
        world.observe(WriteFindings("abcdef1"), "analysis", {"kind": "failed", "error": "timed out"})
    decision = await world.decide([])
    assert isinstance(decision, Unavailable)
    assert "timed out" in decision.reason


# A quote one or two lines from the number the model wrote is still evidence,
# and the finding is corrected to the line that holds it; a quote found
# nowhere near is not.
def test_a_quote_within_two_lines_is_kept_and_corrected():
    world = _world()
    world.observe(
        ReadFile("calc.py", "abcdef1"),
        "read",
        {"kind": "done", "payload": {"content": "    1| def last(items):\n    2|     total = 0\n    3|     return items[len(items)]\n    4| \n    5| x = 1\n"}},
    )
    kept, rejected = world._check(Review((_finding(line=2, evidence="return items[len(items)]"),), "", ()))
    assert rejected == []
    assert kept[0].line == 3
    kept, rejected = world._check(Review((_finding(line=1, evidence="return items[len(items)]"),), "", ()))
    assert kept[0].line == 3
    _, rejected = world._check(Review((_finding(line=5, evidence="def last(items):"),), "", ()))
    assert rejected and "near" in rejected[0]["rejected"]
