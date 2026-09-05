"""A read-only window onto one git repository, as an MCP server.

The code-review agent reads code through this and nothing else, which is the
rule of ADR 0018: an outside capability enters as an MCP tool behind the
invocation boundary, or it does not enter. Every tool here is a read. There
is no tool that writes, checks out, fetches or runs anything, so the review
cannot be talked into doing more than reading however the repository text
it reads is worded.

The repository root comes from `REPO_MCP_ROOT` in the server's environment
(forwarded through `inherit_env`), never from a tool argument, so a call
cannot point the server at another directory. Paths are relative and may not
climb; commits are resolved by git itself; every output is bounded.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("AniOS Repository (read-only)")

MAX_DIFF_CHARS = 60_000
MAX_FILE_LINES = 400
MAX_GREP_MATCHES = 50
MAX_LOG_ENTRIES = 30
_GIT_TIMEOUT_SECONDS = 20
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{4,40}$|^HEAD(~\d+)?$")


class RepoToolError(ValueError):
    """A request the read-only window refuses."""


# The repository this server is rooted at, from the environment only.
def repo_root() -> Path:
    raw = os.environ.get("REPO_MCP_ROOT", "").strip()
    if not raw:
        raise RepoToolError("REPO_MCP_ROOT is not set")
    root = Path(raw).resolve()
    if not (root / ".git").exists():
        raise RepoToolError(f"{root} is not a git repository")
    return root


# Run one read-only git command at the root and return its stdout.
def _git(*args: str, root: Path | None = None) -> str:
    base = root or repo_root()
    # stdin is closed on purpose: this process talks MCP over its own stdio,
    # and a child that inherits that pipe can sit waiting on it - measured as
    # a 20 s timeout on `rev-parse` when the server was first spawned. And
    # git may never prompt: a read-only window has no credentials to offer.
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "PAGER": "cat"}
    try:
        completed = subprocess.run(
            ["git", "-C", str(base), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepoToolError(f"git failed: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise RepoToolError((completed.stderr or "git failed").strip()[:300])
    return completed.stdout


# A commit as git itself resolves it, or a refusal. Only a hash or HEAD~n is
# accepted as spelling; a branch name would let a call read a moving target.
def resolve_commit(commit: str, root: Path | None = None) -> str:
    spelled = str(commit or "").strip()
    if not _COMMIT_PATTERN.match(spelled):
        raise RepoToolError("commit must be a hash or HEAD~n")
    return _git("rev-parse", "--verify", f"{spelled}^{{commit}}", root=root).strip()


# A relative path inside the repository, or a refusal.
def safe_path(path: str) -> str:
    cleaned = str(path or "").strip().replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or cleaned.startswith("~"):
        raise RepoToolError("path must be relative")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts) or re.match(r"^[A-Za-z]:", cleaned):
        raise RepoToolError("path may not climb out of the repository")
    return "/".join(parts)


# The commit's header and the files it touched, with their line counts.
def show_commit(commit: str, root: Path | None = None) -> dict:
    sha = resolve_commit(commit, root)
    header = _git(
        "show", "-s", "--format=%H%n%an%n%aI%n%s", sha, root=root
    ).splitlines()
    numstat = _git("show", "--numstat", "--format=", sha, root=root)
    files = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, removed, path = parts
            files.append(
                {
                    "path": path,
                    "additions": int(added) if added.isdigit() else None,
                    "deletions": int(removed) if removed.isdigit() else None,
                }
            )
    return {
        "sha": header[0] if header else sha,
        "author": header[1] if len(header) > 1 else "",
        "date": header[2] if len(header) > 2 else "",
        "subject": header[3] if len(header) > 3 else "",
        "files": files,
    }


# The commit's diff against its first parent (or the empty tree for a root
# commit), bounded, optionally for one path.
def diff(commit: str, path: str | None = None, root: Path | None = None) -> dict:
    sha = resolve_commit(commit, root)
    parents = _git("rev-list", "--parents", "-n", "1", sha, root=root).split()
    base = parents[1] if len(parents) > 1 else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    args = ["diff", "--no-color", base, sha]
    if path:
        args += ["--", safe_path(path)]
    text = _git(*args, root=root)
    truncated = len(text) > MAX_DIFF_CHARS
    return {"sha": sha, "diff": text[:MAX_DIFF_CHARS], "truncated": truncated}


# A slice of one file at one commit, with line numbers, bounded.
def read_file(path: str, commit: str, start: int = 1, end: int | None = None, root: Path | None = None) -> dict:
    sha = resolve_commit(commit, root)
    clean = safe_path(path)
    text = _git("show", f"{sha}:{clean}", root=root)
    lines = text.splitlines()
    first = max(1, int(start or 1))
    last = min(len(lines), int(end) if end else first + MAX_FILE_LINES - 1, first + MAX_FILE_LINES - 1)
    numbered = [f"{number:5d}| {lines[number - 1]}" for number in range(first, last + 1)]
    return {
        "sha": sha,
        "path": clean,
        "start": first,
        "end": last,
        "total_lines": len(lines),
        "content": "\n".join(numbered),
    }


# Fixed-string search at one commit, bounded.
def grep(pattern: str, commit: str, glob: str | None = None, root: Path | None = None) -> dict:
    sha = resolve_commit(commit, root)
    needle = str(pattern or "").strip()
    if not needle:
        raise RepoToolError("pattern is required")
    args = ["grep", "-n", "-I", "--fixed-strings", needle, sha]
    if glob:
        args += ["--", safe_path(glob)]
    try:
        text = _git(*args, root=root)
    except RepoToolError as exc:
        # git grep exits 1 for "no matches", which is an answer, not a failure.
        if not str(exc):
            text = ""
        else:
            text = ""
    matches = []
    for line in text.splitlines()[:MAX_GREP_MATCHES]:
        # <sha>:<path>:<line>:<text>
        parts = line.split(":", 3)
        if len(parts) == 4:
            matches.append({"path": parts[1], "line": int(parts[2]) if parts[2].isdigit() else None, "text": parts[3][:300]})
    return {"sha": sha, "pattern": needle, "matches": matches, "truncated": len(text.splitlines()) > MAX_GREP_MATCHES}


# Recent commits, newest first, bounded.
def log(count: int = 10, root: Path | None = None) -> dict:
    limit = max(1, min(int(count or 10), MAX_LOG_ENTRIES))
    text = _git("log", f"-n{limit}", "--format=%H%x1f%aI%x1f%s", root=root)
    entries = []
    for line in text.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            entries.append({"sha": parts[0], "date": parts[1], "subject": parts[2][:200]})
    return {"commits": entries}


# ------------------------------------------------------------------ tools


# Wrap one helper as a tool: a refusal comes back as a JSON error, never as
# a stack trace the model has to read.
def _answer(function, *args, **kwargs) -> str:
    try:
        return json.dumps(function(*args, **kwargs), default=str)
    except RepoToolError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def repo_show_commit(commit: str) -> str:
    """The commit's author, date, subject and the files it changed."""
    return _answer(show_commit, commit)


@mcp.tool()
async def repo_diff(commit: str, path: str = "") -> str:
    """The commit's diff against its parent, optionally for one file. Bounded."""
    return _answer(diff, commit, path or None)


@mcp.tool()
async def repo_read_file(path: str, commit: str, start: int = 1, end: int = 0) -> str:
    """A numbered slice of one file as it was at the commit. At most 400 lines."""
    return _answer(read_file, path, commit, start, end or None)


@mcp.tool()
async def repo_grep(pattern: str, commit: str, glob: str = "") -> str:
    """Fixed-string search across the repository at the commit. At most 50 matches."""
    return _answer(grep, pattern, commit, glob or None)


@mcp.tool()
async def repo_log(count: int = 10) -> str:
    """Recent commits, newest first. At most 30."""
    return _answer(log, count)


# Run the repository server over stdio for the AniOS MCP client.
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
