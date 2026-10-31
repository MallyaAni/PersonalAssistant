"""The latest nightly earnings-calendar scan, as the desk page reads it.

`backend.cli.market_earnings_calendar` writes one JSON file per session
under `research/earnings-calendar/`. This reader returns the newest one, trimmed
to the sections the page shows, and says whether it belongs to the session the
desk is displaying.

Descriptive only. No grade, target, order or prompt reads this block; the scan
is a prediction from stored 8-K item 2.02 dates written beside the live record.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

VERSION = "earnings-calendar-live/1"
SCAN_VERSION = "earnings-calendar/1"
DIRECTORY = Path("research") / "earnings-calendar"
NAME = "earnings_calendar.json"


# Every dated scan folder, newest first. An unreadable name is skipped rather
# than guessed at, so a stray directory cannot become the newest scan.
def _scans(root: Path) -> list[tuple[str, Path]]:
    """Return [(asof, folder)] for the dated scan folders, newest first."""
    folder = Path(root) / DIRECTORY
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        if not path.is_dir() or not path.name.startswith("asof="):
            continue
        asof = path.name.split("=", 1)[1]
        try:
            datetime.fromisoformat(asof)
        except ValueError:
            continue
        found.append((asof, path))
    return sorted(found, reverse=True)


# The newest usable scan, with its age against the session the page shows.
# A corrupt or foreign-version file falls through to the previous scan, which
# is then reported as stale instead of hiding the block entirely.
def load(root: Path, session: str | None = None) -> dict | None:
    """Return the newest earnings-calendar scan, or None when none is usable."""
    for asof, folder in _scans(root):
        path = folder / NAME
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if stored.get("version") != SCAN_VERSION:
            continue
        written = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        upcoming = list(stored.get("upcoming") or ())
        names = list(stored.get("names") or ())
        return {
            "version": VERSION,
            "asof": asof,
            "written": written,
            "session": session,
            "stale": session is not None and asof != session,
            "rule": stored.get("rule") or {},
            "upcoming": upcoming,
            "names": names,
            "counts": stored.get("counts")
            or {
                "names": len(names),
                "upcoming": len(upcoming),
                "overdue": sum(1 for row in names if row.get("overdue")),
                "held_upcoming": sum(
                    1 for row in upcoming if (row.get("current_weight") or 0) > 0
                ),
            },
        }
    return None
