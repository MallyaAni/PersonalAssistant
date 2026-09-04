"""Every measurement, kept, so "did this get worse?" is a question with an answer.

Until now a number measured here lived in a code comment - "measured 9/9 on
2026-09-02", "1 in 4", "87/96 both ways" - and comparing two runs meant
running both again and diffing them by hand. That is what the eval platforms
sell: an experiment is a dataset, a task and scorers, and its value is that
runs are *kept and compared*, not that any single run is clever. The idea
transfers; the platform does not, because the traces it would hold are real
conversations and the deployment here is two machines in a house.

So this is the same idea, local: one JSON file per run under
`data/evaluations/<name>/`, holding what was measured, on which commit, over
how many passes, and the score per category. `report()` reads them back.

Files rather than a table on purpose. Measurements are often run in the probe
clone, which has no database, and a measurement that cannot be recorded where
it is taken is a measurement that goes back into a comment.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Where runs are kept. Under `data/` with the rest of what this system owns.
ROOT = Path(os.getenv("ANIOS_EVALUATION_ROOT", "data/evaluations"))


@dataclass(frozen=True, slots=True)
class Score:
    """One category's result: how many of its cases came out as labelled."""

    name: str
    right: int
    total: int

    @property
    def rate(self) -> float:
        return self.right / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class Run:
    """One measurement of one thing, at one commit, over one or more passes."""

    name: str
    at: str
    commit: str
    reps: int
    right: int
    total: int
    floor: float | None = None
    scores: tuple[Score, ...] = ()
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def rate(self) -> float:
        return self.right / self.total if self.total else 0.0

    @property
    def passed(self) -> bool | None:
        return None if self.floor is None else self.rate >= self.floor


# The commit a measurement was taken on, or "" where git cannot say. A run
# whose commit is unknown is still worth keeping; it just cannot be blamed.
def _commit() -> str:
    try:
        found = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return found.stdout.strip() if found.returncode == 0 else ""


# Write one run down. Returns the file, or None when it could not be written -
# a measurement that cannot be filed must not fail the measurement.
def record(
    name: str,
    right: int,
    total: int,
    *,
    reps: int = 1,
    floor: float | None = None,
    scores: dict[str, tuple[int, int]] | None = None,
    notes: str = "",
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
) -> Path | None:
    moment = datetime.now(UTC)
    run = Run(
        name=name,
        at=moment.isoformat(timespec="seconds"),
        commit=_commit(),
        reps=reps,
        right=right,
        total=total,
        floor=floor,
        scores=tuple(
            Score(category, hit, seen) for category, (hit, seen) in sorted((scores or {}).items())
        ),
        notes=notes,
        extra=dict(extra or {}),
    )
    folder = (root or ROOT) / name
    try:
        folder.mkdir(parents=True, exist_ok=True)
        # Microseconds, not the seconds `at` displays: a script that records a
        # run per category writes several within one second, and a name that
        # only resolves to the second silently keeps the last of them. Fixed
        # width so that sorting the folder by name is sorting it by time.
        stamp = moment.strftime("%Y%m%dT%H%M%S%f")
        path = folder / f"{stamp}-{run.commit or 'nocommit'}.json"
        path.write_text(json.dumps(asdict(run), indent=2, sort_keys=True))
    except OSError:
        logger.warning("Could not record the %s measurement", name, exc_info=True)
        return None
    return path


# Every run of one measurement, oldest first.
def history(name: str, root: Path | None = None) -> list[Run]:
    folder = (root or ROOT) / name
    runs: list[Run] = []
    if not folder.is_dir():
        return runs
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
            runs.append(
                Run(
                    name=str(payload.get("name") or name),
                    at=str(payload.get("at") or ""),
                    commit=str(payload.get("commit") or ""),
                    reps=int(payload.get("reps") or 1),
                    right=int(payload.get("right") or 0),
                    total=int(payload.get("total") or 0),
                    floor=payload.get("floor"),
                    scores=tuple(
                        Score(str(row.get("name")), int(row.get("right", 0)), int(row.get("total", 0)))
                        for row in payload.get("scores") or []
                    ),
                    notes=str(payload.get("notes") or ""),
                    extra=dict(payload.get("extra") or {}),
                )
            )
        except (OSError, ValueError, TypeError):
            logger.warning("Skipping an unreadable measurement at %s", path)
    return runs


# What changed between the two most recent runs, by category. The whole point:
# a category that moved is worth a look, and an aggregate that held while
# categories swapped underneath it is worth knowing about too.
def compare(older: Run, newer: Run) -> list[tuple[str, float, float]]:
    before = {score.name: score.rate for score in older.scores}
    after = {score.name: score.rate for score in newer.scores}
    moved = [
        (category, before[category], after[category])
        for category in sorted(set(before) & set(after))
        if abs(after[category] - before[category]) > 1e-9
    ]
    return moved
