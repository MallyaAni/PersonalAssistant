"""Desk records: reading them back and the changes between two days."""

import json
from pathlib import Path

from backend.market import deskrecord


def _write(root: Path, session: str, grades: dict, book: list, flags: list) -> None:
    path = root / "desk" / f"asof={session}" / "desk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "session": session,
        "regime": {"flags": flags, "selection_confidence": 0.5, "exposure": 1.0},
        "grades": {t: {"grade": g} for t, g in grades.items()},
        "book": [{"ticker": t, "weight": w} for t, w in book],
    }
    path.write_text(json.dumps(record), encoding="utf-8")


# Sessions come back sorted, the latest pair is the last two, and a missing
# record is None.
def test_sessions_and_latest_pair(tmp_path):
    assert deskrecord.sessions(tmp_path) == []
    assert deskrecord.latest_pair(tmp_path) == (None, None)
    _write(tmp_path, "2026-09-04", {"SNDK": "A+"}, [("SNDK", 0.08)], [])
    _write(tmp_path, "2026-09-03", {"SNDK": "A"}, [("SNDK", 0.06)], [])
    assert deskrecord.sessions(tmp_path) == ["2026-09-03", "2026-09-04"]
    latest, previous = deskrecord.latest_pair(tmp_path)
    assert latest["session"] == "2026-09-04"
    assert previous["session"] == "2026-09-03"
    assert deskrecord.load(tmp_path, "2026-01-01") is None


# Upgrades, downgrades, the orders that turn one book into the next, and
# the flags that changed; with no previous record every held name is a buy.
def test_changes_between_records(tmp_path):
    previous = {
        "session": "2026-09-03",
        "regime": {"flags": ["participation below its two-year median"]},
        "grades": {
            "SNDK": {"grade": "A"},
            "MU": {"grade": "A+"},
            "CRWV": {"grade": "C"},
        },
        "book": [{"ticker": "SNDK", "weight": 0.06}, {"ticker": "MU", "weight": 0.07}],
    }
    latest = {
        "session": "2026-09-04",
        "regime": {"flags": ["theme co-movement structure has changed shape"]},
        "grades": {
            "SNDK": {"grade": "A+"},
            "MU": {"grade": "B"},
            "CRWV": {"grade": "C"},
        },
        "book": [
            {"ticker": "SNDK", "weight": 0.08},
            {"ticker": "ANET", "weight": 0.05},
        ],
    }
    changes = deskrecord.changes(latest, previous)
    assert changes.since == "2026-09-03"
    assert changes.upgrades == [{"ticker": "SNDK", "from": "A", "to": "A+"}]
    assert changes.downgrades == [{"ticker": "MU", "from": "A+", "to": "B"}]
    actions = {o.ticker: o.action for o in changes.orders}
    assert actions == {"MU": "sell", "ANET": "buy", "SNDK": "add"}
    assert changes.orders[0].ticker == "MU"  # the largest move first
    assert changes.flags_raised == ["theme co-movement structure has changed shape"]
    assert changes.flags_cleared == ["participation below its two-year median"]
    first = deskrecord.changes(latest, None)
    assert first.since is None
    assert first.upgrades == []
    assert {o.action for o in first.orders} == {"buy"}
    data = changes.to_dict()
    assert data["orders"][0]["reason"].startswith("leaves the book")


# The summary counts the grades and lists the book.
def test_summary():
    record = {
        "session": "2026-09-04",
        "regime": {"flags": ["x"], "selection_confidence": 0.5, "exposure": 1.0},
        "grades": {
            "SNDK": {"grade": "A+"},
            "MU": {"grade": "B"},
            "CRWV": {"grade": "C"},
        },
        "book": [
            {"ticker": "SNDK", "weight": 0.076},
            {"ticker": "PANW", "weight": 0.063},
        ],
    }
    s = deskrecord.summary(record)
    assert s["counts"] == {"A+": 1, "A": 0, "B": 1, "C": 1}
    assert s["gross"] == 0.139
    assert s["names"] == ["SNDK", "PANW"]
    assert s["flags"] == ["x"]
