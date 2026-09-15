"""The record's standing against the last completed session.

What has to hold: before the close the expected session is the previous
one and after it is today; a weekend expects Friday; a record for the
expected session is current, an older one is pending until the next
morning and late after it; with no ledger the observation is late
once the morning has passed.
"""

import json
from datetime import datetime
from pathlib import Path

from backend.market import record_status
from backend.market.record_status import NEW_YORK


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=NEW_YORK)


def test_the_expected_session_follows_the_close_and_the_weekend():
    assert (
        record_status.last_completed_session(_at("2026-09-15T09:00")).isoformat()
        == "2026-09-14"
    )
    assert (
        record_status.last_completed_session(_at("2026-09-15T16:00")).isoformat()
        == "2026-09-15"
    )
    assert (
        record_status.last_completed_session(_at("2026-09-13T12:00")).isoformat()
        == "2026-09-11"
    )


def test_standing_is_pending_until_the_morning_then_late():
    expected = record_status.last_completed_session(_at("2026-09-14T20:00"))
    assert (
        record_status.standing("2026-09-14", expected, _at("2026-09-14T20:00"))
        == "current"
    )
    assert (
        record_status.standing("2026-09-11", expected, _at("2026-09-14T20:00"))
        == "pending"
    )
    assert (
        record_status.standing("2026-09-11", expected, _at("2026-09-15T08:00"))
        == "late"
    )
    assert record_status.standing(None, expected, _at("2026-09-15T08:00")) == "late"
    assert record_status.standing(None, expected, _at("2026-09-14T20:00")) == "pending"


def test_describe_reads_the_store(tmp_path):
    root = Path(tmp_path)
    (root / "desk" / "asof=2026-09-11").mkdir(parents=True)
    (root / "desk" / "asof=2026-09-11" / "desk.json").write_text(
        json.dumps({"session": "2026-09-11"}), encoding="utf-8"
    )
    out = record_status.describe(root, _at("2026-09-15T09:00"))
    assert out["expected"] == "2026-09-14"
    assert out["record"] == {"session": "2026-09-11", "status": "late"}
    assert out["ml_forward"] == {"session": None, "status": "late"}
    assert out["due_at"].startswith("2026-09-15T07:00")
