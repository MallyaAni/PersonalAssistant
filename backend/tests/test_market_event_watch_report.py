"""The desk reader for the nightly event-watch scan."""

import json
from pathlib import Path

from backend.market import event_watch_report


# One scan file with the sections the page reads.
def _scan(root: Path, asof: str, *, version: str = "event-watch/1") -> Path:
    folder = root / "research" / "event-watch" / f"asof={asof}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "event_watch.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "asof": asof,
                "rule": {"qoq_drop": -0.2},
                "calendar": {"next_election": "2026-11-03"},
                "shocks": [{"ticker": "GOOGL", "age_sessions": 1}],
                "price_shocks": [{"ticker": "FFIV"}],
                "contagion": [{"trigger": {"ticker": "GOOGL"}}],
                "names": [{"ticker": "GOOGL"}, {"ticker": "INTC"}],
            }
        ),
        encoding="utf-8",
    )
    return path


# The newest scan is returned and carries the session it belongs to.
def test_load_returns_newest_scan(tmp_path):
    _scan(tmp_path, "2026-10-29")
    _scan(tmp_path, "2026-10-30")
    result = event_watch_report.load(tmp_path, "2026-10-30")
    assert result is not None
    assert result["asof"] == "2026-10-30"
    assert result["stale"] is False
    assert result["session"] == "2026-10-30"
    assert result["counts"] == {"names": 2, "shocks": 1, "price_shocks": 1}
    assert result["shocks"][0]["ticker"] == "GOOGL"


# A scan for another session is reported as stale, not presented as current.
def test_load_marks_a_different_session_stale(tmp_path):
    _scan(tmp_path, "2026-10-29")
    result = event_watch_report.load(tmp_path, "2026-10-30")
    assert result is not None
    assert result["asof"] == "2026-10-29"
    assert result["stale"] is True


# A corrupt newest file falls through to the previous scan rather than hiding
# the block or raising on the page.
def test_load_skips_a_corrupt_scan(tmp_path):
    _scan(tmp_path, "2026-10-29")
    newest = _scan(tmp_path, "2026-10-30")
    newest.write_text("{not json", encoding="utf-8")
    result = event_watch_report.load(tmp_path, "2026-10-30")
    assert result is not None
    assert result["asof"] == "2026-10-29"
    assert result["stale"] is True


# A file written by an older or foreign scan version is not served.
def test_load_refuses_a_foreign_version(tmp_path):
    _scan(tmp_path, "2026-10-30", version="event-watch/0")
    assert event_watch_report.load(tmp_path, "2026-10-30") is None


# No scan directory is a missing block, not an error.
def test_load_without_a_scan_returns_none(tmp_path):
    assert event_watch_report.load(tmp_path, "2026-10-30") is None
