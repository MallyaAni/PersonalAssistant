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

import dataclasses
import json
import multiprocessing
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from backend.market import deskrecord, report_files

NAME = "prose.json"
JOB_NAME = "prose-job.json"
RESULTS_NAME = "prose-results.jsonl"
VERSION = "prose/2"
TERMINATE_GRACE_SECONDS = 5.0


# The prose file sits in the session's folder, next to the decision it
# describes, so the two travel together and prune together.
def path(root: Path, session: str) -> Path:
    """Where a session's prose lives: beside its record."""
    return deskrecord.folder(root, session) / NAME


# The stored block, read through the shared reader so a torn or missing
# file is handled the same way as every other file beside the record.
def load(root: Path, session: str) -> dict | None:
    """Return the session's prose block, or None."""
    return report_files.read_json(path(root, session))


# Whether the parent that spawned this child is still there; a child whose
# parent died has nobody to collect for and must not keep the model busy.
def _parent_alive() -> bool:
    parent = multiprocessing.parent_process()
    return parent is None or parent.is_alive()


# A watchdog for the child: leave at once when the parent is gone.
def _watch_parent(
    alive: Callable[[], bool], stop, interval: float = 1.0, leave: Callable = os._exit
) -> None:
    while not stop.wait(interval):
        if not alive():
            leave(3)


# The child's work: one guarded model call per item, spread over
# `concurrency` clients (the provider serialises per instance), each result
# appended and flushed as soon as it exists, so a kill loses at most the
# calls in flight. A crash of the worker itself is written as a row too, so
# the block can say why. Importable at module level because the child is
# spawned.
def _worker(
    job_path: str, results_path: str, llm_url: str, llm_model: str, concurrency: int
) -> None:
    import threading
    import traceback
    from concurrent.futures import ThreadPoolExecutor

    stop = threading.Event()
    threading.Thread(
        target=_watch_parent, args=(_parent_alive, stop), daemon=True
    ).start()
    lock = threading.Lock()
    with open(results_path, "a", encoding="utf-8") as out:
        try:
            from backend.agents.trading.desk.narrative import DeskNarrator
            from backend.cli import market_tone

            job = json.loads(Path(job_path).read_text(encoding="utf-8"))
            readers, _model = market_tone.clients(
                llm_url, llm_model, max(1, concurrency)
            )
            narrators = [DeskNarrator(r.writer) for r in readers]
            items = [("brief", i) for i in job.get("briefs", [])] + [
                ("read", i) for i in job.get("reads", [])
            ]

            def run(indexed):
                index, (kind, item) = indexed
                narrator = narrators[index % len(narrators)]

                def brief():
                    return narrator.brief_sync(item["text"], item["grade"])

                def read():
                    return narrator.read_sync(item["text"])

                if kind == "brief":
                    _attempt(out, lock, kind, item["ticker"], brief, dataclasses.asdict)
                else:
                    _attempt(out, lock, kind, item["ticker"], read, str)

            with ThreadPoolExecutor(max_workers=len(narrators)) as pool:
                list(pool.map(run, enumerate(items)))
        except Exception:  # noqa: BLE001 - the crash itself becomes evidence
            with lock:
                out.write(
                    json.dumps(
                        {
                            "kind": "worker",
                            "ticker": "",
                            "error": traceback.format_exc().strip().splitlines()[-1],
                        }
                    )
                    + "\n"
                )
                out.flush()
            stop.set()
            raise SystemExit(1) from None
    stop.set()


# One guarded call, its result or its failure written as one line.
def _attempt(
    out, lock, kind: str, ticker: str, call: Callable, to_value: Callable
) -> None:
    try:
        result = call()
    except Exception as exc:  # noqa: BLE001 - one item, not the run
        row = {"kind": kind, "ticker": ticker, "error": repr(exc)}
    else:
        row = (
            {"kind": kind, "ticker": ticker, "value": to_value(result)}
            if result
            else {
                "kind": kind,
                "ticker": ticker,
                "error": f"no {kind} (runtime away, empty, or the answer did not fit)",
            }
        )
    with lock:
        out.write(json.dumps(row) + "\n")
        out.flush()


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
            who = f"{row['kind']} {row['ticker']}".strip()
            failures.append(f"{who}: {row['error']}")
        elif row["kind"] == "brief":
            briefs[row["ticker"]] = row["value"]
        elif row["kind"] == "read":
            reads[row["ticker"]] = row["value"]
    return briefs, reads, failures


# The block's state from what happened, and the sentence that explains it.
def status_of(
    done: int, total: int, failures: list[str], timed_out: bool, budget_seconds: float
) -> tuple[str, str]:
    """Return (state, detail): ready, partial, timed_out or unavailable."""
    minutes = budget_seconds / 60
    if timed_out:
        return "timed_out", (
            f"timed out after {minutes:.0f} min: {done} of {total} written; "
            "the request in flight was terminated"
        )
    if total and done == 0:
        return "unavailable", failures[0] if failures else "the runtime wrote nothing"
    if failures:
        attempted = done + sum(1 for f in failures if not f.startswith("worker"))
        left = max(0, total - attempted)
        detail = f"{done} of {total} written; {len(failures)} failed"
        if left:
            detail += f"; {left} not attempted"
        return "partial", detail
    return "ready", f"{done} of {total} written"


# Run the job in a child process under a wall-clock deadline; terminate it
# at the deadline and keep what it wrote. The job file is removed once read;
# the results file is kept only when something went wrong, as a trace.
def run_with_deadline(
    job: dict,
    folder: Path,
    budget_seconds: float,
    llm_url: str,
    llm_model: str,
    concurrency: int = 1,
) -> tuple[dict[str, dict], dict[str, str], tuple[str, str], list[str]]:
    """Return (briefs, reads, (state, detail), failures)."""
    total = len(job.get("briefs", [])) + len(job.get("reads", []))
    if total == 0:
        return {}, {}, ("ready", "none requested"), []
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    job_path, results_path = folder / JOB_NAME, folder / RESULTS_NAME
    job_path.write_text(json.dumps(job), encoding="utf-8")
    if results_path.exists():
        results_path.unlink()
    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_worker,
        args=(str(job_path), str(results_path), llm_url, llm_model, concurrency),
        daemon=True,
    )
    child.start()
    child.join(budget_seconds)
    alive = child.is_alive()
    if alive:
        child.terminate()
        child.join(TERMINATE_GRACE_SECONDS)
        if child.is_alive():
            child.kill()
            child.join(TERMINATE_GRACE_SECONDS)
    briefs, reads, failures = collect(results_path)
    done = len(briefs) + len(reads)
    # A child still winding down after writing every row is complete, not
    # timed out; only work left undone at the deadline is.
    timed_out = alive and done + len(failures) < total
    if not alive and child.exitcode not in (0, None):
        failures.insert(0, f"worker exited with {child.exitcode}")
    job_path.unlink(missing_ok=True)
    if not timed_out and not failures:
        results_path.unlink(missing_ok=True)
    status = status_of(done, total, failures, timed_out, budget_seconds)
    return briefs, reads, status, failures


# The block records what was produced, under which status, for which
# decision (session and code revision) and how long it took.
def write(
    root: Path,
    session: str,
    code_revision: str,
    briefs: dict,
    reads: dict,
    status: tuple[str, str],
    elapsed_seconds: float,
    now: datetime | None = None,
) -> bool:
    """Write the prose block; True when it landed."""
    state, detail = status
    block = {
        "version": VERSION,
        "session": session,
        "code_revision": code_revision,
        "written": (now or datetime.now(tz=UTC)).isoformat(timespec="seconds"),
        "state": state,
        "detail": detail,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "briefs": briefs,
        "reads": reads,
    }
    return report_files.write_json(path(root, session), block, "prose")


# The record as the page reads it: the decision plus whatever prose exists,
# with a state the page can switch on and a sentence it can show.
def merge(record: dict, block: dict | None) -> dict:
    """Return the record with the prose merged in and its state set."""
    if block is None:
        embedded = bool(record.get("briefs")) or any(
            g.get("read") for g in (record.get("grades") or {}).values()
        )
        return {**record, "prose_state": "embedded" if embedded else "absent"}
    # Prose written before the decision it sits beside belongs to an earlier
    # run of the same session: a forced rerun killed between saving the
    # record and enriching it would otherwise serve last run's briefs, about
    # the old grades, as ready.
    written, theirs_written = record.get("written"), block.get("written")
    if written and theirs_written and str(theirs_written) < str(written):
        return {
            **record,
            "prose_state": "absent",
            "prose_status": "absent: prose on file predates this decision",
        }
    grades = {k: dict(v) for k, v in (record.get("grades") or {}).items()}
    for ticker, read in (block.get("reads") or {}).items():
        if ticker in grades and read:
            grades[ticker]["read"] = read
    state = block.get("state") or "ready"
    detail = block.get("detail") or ""
    revision = (record.get("provenance") or {}).get("code_revision")
    theirs = block.get("code_revision")
    if revision and theirs and revision != theirs:
        detail = (detail + "; written by a different revision").strip("; ")
    return {
        **record,
        "briefs": block.get("briefs") or {},
        "grades": grades,
        "prose_state": state,
        "prose_status": f"{state.replace('_', ' ')}: {detail}" if detail else state,
        "prose_written": block.get("written"),
    }
