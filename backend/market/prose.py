"""Model-written briefs and reads, stored beside the decision, never inside it.

The nightly's record is the day's decision: grades, scores, the book,
the paper orders. The briefs and reads a model writes about it are
prose, produced by a runtime that can be slow or away, and on
2026-09-15 Codex pointed out that a blocked prose request could hold the
decision hostage. So the core record is saved first and the prose is an
enrichment: written to `prose.json` in the session's folder, linked to
the decision by session and code revision, produced under a total
budget, and merged into the record when it is read. When it is missing
the page shows the decision with prose unavailable and the deterministic
reads stand.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from backend.market import report_files

NAME = "prose.json"
DESK_KIND = "desk"
VERSION = "prose/1"


def path(root: Path, session: str) -> Path:
    """Where a session's prose lives."""
    return Path(root) / DESK_KIND / f"asof={session}" / NAME


def load(root: Path, session: str) -> dict | None:
    """Return the session's prose block, or None."""
    target = path(root, session)
    if not target.exists():
        return None
    try:
        import json

        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# Produce the prose under one total budget: each name's brief and read is
# one guarded call; past the budget the rest are skipped and said so; a
# runtime that fails every call leaves the block unavailable, not the run.
def enrich(
    brief_names: list[str],
    read_names: list[str],
    brief_one: Callable[[str], dict | None],
    read_one: Callable[[str], str | None],
    budget_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, dict], dict[str, str | None], str]:
    """Return (briefs, reads, status)."""
    deadline = clock() + budget_seconds
    briefs: dict[str, dict] = {}
    reads: dict[str, str | None] = {}
    failures: list[str] = []
    skipped = 0
    total = len(brief_names) + len(read_names)
    for kind, names, one, out in (
        ("brief", brief_names, brief_one, briefs),
        ("read", read_names, read_one, reads),
    ):
        for name in names:
            if clock() > deadline:
                skipped += 1
                continue
            try:
                result = one(name)
            except Exception as exc:  # noqa: BLE001 - prose never stops the run
                failures.append(f"{kind} {name}: {type(exc).__name__}: {exc}")
                continue
            if result is not None:
                out[name] = result
    done = len(briefs) + len(reads)
    if total and done == 0:
        reason = failures[0] if failures else "budget exhausted before the first call"
        status = f"unavailable: {reason}"
    elif skipped or failures:
        status = (
            f"partial: {done} of {total} written; {skipped} skipped past the "
            f"{budget_seconds / 60:.0f}-minute budget; {len(failures)} failed"
        )
    else:
        status = "ready"
    return briefs, reads, status


# Write the block beside the decision it belongs to; never raise.
def write(
    root: Path,
    session: str,
    code_revision: str,
    briefs: dict,
    reads: dict,
    status: str,
    elapsed_seconds: float,
    now: datetime | None = None,
) -> bool:
    """Write the prose block; True when it landed."""
    block = {
        "version": VERSION,
        "session": session,
        "code_revision": code_revision,
        "written": (now or datetime.now(tz=UTC)).isoformat(timespec="seconds"),
        "status": status,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "briefs": briefs,
        "reads": reads,
    }
    return report_files.write_json(path(root, session), block, "prose")


# The record as the page reads it: the decision plus whatever prose exists.
def merge(record: dict, block: dict | None) -> dict:
    """Return the record with the prose merged in and `prose_status` set."""
    out = dict(record)
    if block is None:
        embedded = bool(record.get("briefs")) or any(
            g.get("read") for g in (record.get("grades") or {}).values()
        )
        out["prose_status"] = "embedded" if embedded else "absent"
        return out
    out["briefs"] = {**(record.get("briefs") or {}), **(block.get("briefs") or {})}
    grades = {k: dict(v) for k, v in (record.get("grades") or {}).items()}
    for ticker, read in (block.get("reads") or {}).items():
        if ticker in grades and read:
            grades[ticker]["read"] = read
    out["grades"] = grades
    out["prose_status"] = block.get("status") or "ready"
    out["prose_written"] = block.get("written")
    if block.get("code_revision") and record.get("provenance", {}).get(
        "code_revision"
    ) not in (
        None,
        "unknown",
        block.get("code_revision"),
    ):
        out["prose_status"] += " (written by a different revision)"
    return out
