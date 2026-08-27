"""The reply is told the person's date, not UTC's.

At 9 PM Eastern UTC is already tomorrow; told UTC's date, the reply
confirmed a reminder set "for tomorrow" as "today" (sweep_journeys,
2026-08-26).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.graph import _build_system_prompt


def test_the_persons_evening_is_still_today():
    evening = datetime(2026, 8, 26, 21, 5, tzinfo=ZoneInfo("America/New_York"))
    assert evening.astimezone(UTC).date().isoformat() == "2026-08-27"
    prompt = _build_system_prompt({"local_now": evening})
    assert "2026-08-26" in prompt and "2026-08-27" not in prompt


def test_without_a_known_zone_the_date_is_utc():
    prompt = _build_system_prompt({}, now=datetime(2026, 8, 27, 1, 0, tzinfo=UTC))
    assert "2026-08-27" in prompt
