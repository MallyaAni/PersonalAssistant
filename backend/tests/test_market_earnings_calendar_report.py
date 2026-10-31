"""The desk reader for the nightly forward earnings calendar."""

import json
from pathlib import Path

from backend.market import earnings_calendar_report


# One scan file with the sections the page reads.
def _scan(root: Path, asof: str, *, version: str = "earnings-calendar/1") -> Path:
    folder = root / "research" / "earnings-calendar" / f"asof={asof}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "earnings_calendar.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "asof": asof,
                "rule": {"horizon_years": 3},
                "upcoming": [
                    {"ticker": "SNPS", "current_weight": 0.09, "overdue": False},
                    {"ticker": "MU", "current_weight": 0.0, "overdue": False},
                ],
                "names": [
                    {"ticker": "SNPS", "current_weight": 0.09, "overdue": False},
                    {"ticker": "MU", "current_weight": 0.0, "overdue": False},
                    {"ticker": "MOD", "current_weight": 0.0, "overdue": True},
                ],
                "counts": {
                    "names": 3,
                    "upcoming": 2,
                    "overdue": 1,
                    "held_upcoming": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


# The newest scan is returned and carries the session it belongs to.
def test_load_returns_newest_scan(tmp_path):
    _scan(tmp_path, "2026-10-29")
    _scan(tmp_path, "2026-10-30")
    result = earnings_calendar_report.load(tmp_path, "2026-10-30")
    assert result is not None
    assert result["asof"] == "2026-10-30"
    assert result["stale"] is False
    assert result["session"] == "2026-10-30"
    assert result["counts"]["held_upcoming"] == 1
    assert result["upcoming"][0]["ticker"] == "SNPS"


# A scan for another session is reported as stale, not presented as current.
def test_load_marks_a_different_session_stale(tmp_path):
    _scan(tmp_path, "2026-10-29")
    result = earnings_calendar_report.load(tmp_path, "2026-10-30")
    assert result is not None
    assert result["asof"] == "2026-10-29"
    assert result["stale"] is True


# A corrupt newest file falls through to the previous scan rather than hiding
# the block or raising on the page.
def test_load_skips_a_corrupt_scan(tmp_path):
    _scan(tmp_path, "2026-10-29")
    newest = _scan(tmp_path, "2026-10-30")
    newest.write_text("{not json", encoding="utf-8")
    result = earnings_calendar_report.load(tmp_path, "2026-10-30")
    assert result is not None
    assert result["asof"] == "2026-10-29"
    assert result["stale"] is True


# A file written by an older or foreign scan version is not served.
def test_load_refuses_a_foreign_version(tmp_path):
    _scan(tmp_path, "2026-10-30", version="earnings-calendar/0")
    assert earnings_calendar_report.load(tmp_path, "2026-10-30") is None


# No scan directory is a missing block, not an error.
def test_load_without_a_scan_returns_none(tmp_path):
    assert earnings_calendar_report.load(tmp_path, "2026-10-30") is None
