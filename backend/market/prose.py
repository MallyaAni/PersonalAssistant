"""Model-written briefs and reads, stored beside the decision, never inside it.

The nightly's record is the day's decision: grades, scores, the book,
the paper orders. The briefs and reads a model writes about it are
prose, produced by a runtime that can be slow, away, or worse, one that
keeps sending bytes so no inactivity timeout ever fires. On 2026-09-15
Codex pointed out that such a request could hold the decision hostage.

So the core record is saved first and the prose is an enrichment that
runs in a child process under a wall-clock deadline. The parent writes
the job (the evidence texts and grades) to a file, the child calls the
model and appends each finished brief or read to a results file as it
completes, and at the deadline the parent terminates the child, which
releases its sockets with it, and keeps whatever the child had written.
The prose block lands in `prose.json` beside the record, linked to the
decision by session and code revision, marked ready, partial, timed out
or unavailable, and is merged into the record when it is read. The
decision is never rewritten; the nightly's lock is released by the
parent as always.
"""

from __future__ import annotations

import json
import multiprocessing
import time
from datetime import UTC, datetime
from pathlib import Path

from backend.market import report_files

NAME = "prose.json"
JOB_NAME = "prose-job.json"
RESULTS_NAME = "prose-results.jsonl"
DESK_KIND = "desk"
VERSION = "prose/2"
TERMINATE_GRACE_SECONDS = 5.0


def path(root: Path, session: str) -> Path:
    """Where a session's prose lives."""
    return Path(root) / DESK_KIND / f"asof={session}" / NAME


def load(root: Path, session: str) -> dict | None:
    """Return the session's prose block, or None."""
    target = path(root, session)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# The child's work: one guarded model call per item, each result appended
# and flushed as soon as it exists, so a kill loses at most the call in
# flight. Importable at module level because the child is spawned.
def _worker(job_path: str, results_path: str, llm_url: str, llm_model: str) -> None:
    from backend.agents.trading.desk.narrative import DeskNarrator
    from backend.cli import market_tone

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    readers, _model = market_tone.clients(llm_url, llm_model, 1)
    narrator = DeskNarrator(readers[0].writer)
    with open(results_path, "a", encoding="utf-8") as out:

        def emit(row: dict) -> None:
            out.write(json.dumps(row) + "\n")
            out.flush()

        for item in job.get("briefs", []):
            try:
                brief = narrator.brief_sync(item["text"], item["grade"])
            except Exception as exc:  # noqa: BLE001 - one item, not the run
                emit({"kind": "brief", "ticker": item["ticker"], "error": repr(exc)})
                continue
            if brief is None:
                emit({"kind": "brief", "ticker": item["ticker"], "error": "no brief"})
                continue
            emit(
                {
                    "kind": "brief",
                    "ticker": item["ticker"],
                    "fields": {
                        "stance": brief.stance,
                        "verdict": brief.verdict,
                        "reasoning": brief.reasoning,
                        "risks": brief.risks,
                        "watch": brief.watch,
                    },
                }
            )
        for item in job.get("reads", []):
            try:
                read = narrator.read_sync(item["text"])
            except Exception as exc:  # noqa: BLE001
                emit({"kind": "read", "ticker": item["ticker"], "error": repr(exc)})
                continue
            if not read:
                emit({"kind": "read", "ticker": item["ticker"], "error": "no read"})
                continue
            emit({"kind": "read", "ticker": item["ticker"], "text": read})


# What the child managed to write, whether or not it finished.
def collect(results_path: Path) -> tuple[dict[str, dict], dict[str, str], list[str]]:
    """Return (briefs, reads, failures) from the results file."""
    briefs: dict[str, dict] = {}
    reads: dict[str, str] = {}
    failures: list[str] = []
    if not Path(results_path).exists():
        return briefs, reads, failures
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a line cut off by the kill
        if row.get("error"):
            failures.append(f"{row['kind']} {row['ticker']}: {row['error']}")
        elif row["kind"] == "brief":
            briefs[row["ticker"]] = row["fields"]
        elif row["kind"] == "read":
            reads[row["ticker"]] = row["text"]
    return briefs, reads, failures


# The block's status from what happened.
def status_of(
    done: int, total: int, failures: list[str], timed_out: bool, budget_seconds: float
) -> str:
    """Return ready, partial, timed out or unavailable, with the reason."""
    minutes = budget_seconds / 60
    if timed_out:
        return (
            f"timed out after {minutes:.0f} min: {done} of {total} written; "
            "the request in flight was terminated"
        )
    if total and done == 0:
        return "unavailable: " + (
            failures[0] if failures else "the runtime wrote nothing"
        )
    if failures:
        return f"partial: {done} of {total} written; {len(failures)} failed"
    return "ready"


# Run the job in a child process under a wall-clock deadline; terminate it
# at the deadline and keep what it wrote.
def run_with_deadline(
    job: dict,
    folder: Path,
    budget_seconds: float,
    llm_url: str,
    llm_model: str,
) -> tuple[dict[str, dict], dict[str, str], str]:
    """Return (briefs, reads, status)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    job_path, results_path = folder / JOB_NAME, folder / RESULTS_NAME
    job_path.write_text(json.dumps(job), encoding="utf-8")
    if results_path.exists():
        results_path.unlink()
    total = len(job.get("briefs", [])) + len(job.get("reads", []))
    if total == 0:
        return {}, {}, "none requested"
    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_worker,
        args=(str(job_path), str(results_path), llm_url, llm_model),
        daemon=True,
    )
    child.start()
    child.join(budget_seconds)
    timed_out = child.is_alive()
    if timed_out:
        child.terminate()
        child.join(TERMINATE_GRACE_SECONDS)
        if child.is_alive():
            child.kill()
            child.join(TERMINATE_GRACE_SECONDS)
    briefs, reads, failures = collect(results_path)
    done = len(briefs) + len(reads)
    if not timed_out and child.exitcode not in (0, None):
        failures.insert(0, f"worker exited with {child.exitcode}")
    return briefs, reads, status_of(done, total, failures, timed_out, budget_seconds)


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
    revision = record.get("provenance", {}).get("code_revision")
    if block.get("code_revision") and revision not in (
        None,
        "unknown",
        block.get("code_revision"),
    ):
        out["prose_status"] += " (written by a different revision)"
    return out


def elapsed_since(started: float) -> float:
    """Seconds since a `time.monotonic()` reading."""
    return time.monotonic() - started
