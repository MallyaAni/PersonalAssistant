"""The current grade must use current evidence from its own evening decision."""

from datetime import UTC, datetime

import pytest

from backend.market import desk_freshness, holdings

NOW = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)


# Supply a candle and the decision it extends, independently of wall time.
def snapshot():
    return {
        "as_of": NOW.isoformat(),
        "decision_session": "2026-09-10",
        "quotes": {"AAA": {"bar": "2026-09-11T13:45:00+00:00"}},
        "technical": {"AAA": {"now": 0.9, "close": 0.5, "stance": 1}},
        "value": {"AAA": {"now": 0.2, "close": 0.5, "stance": -1}},
    }


# A newly generated snapshot cannot disguise old, future, or undated market data.
@pytest.mark.parametrize(
    "bar",
    [
        None,
        "2026-09-10T13:45:00+00:00",
        "2026-09-11T14:15:00+00:00",
        "2026-09-11T12:00:00+00:00",
    ],
)
def test_new_snapshot_does_not_make_a_bad_candle_fresh(bar):
    snap = snapshot()
    snap["quotes"]["AAA"]["bar"] = bar
    assert desk_freshness.describe(snap, NOW)["stale"]
    assert desk_freshness.grade_inputs(snap, {"session": "2026-09-10"}, NOW) == ({}, {})


# The previous intraday calculation must not be applied to a new evening score.
@pytest.mark.parametrize("session", [None, "2026-09-09", "2026-09-11"])
def test_another_evening_decision_cannot_borrow_the_snapshot(session):
    assert desk_freshness.grade_inputs(snapshot(), {"session": session}, NOW) == (
        {},
        {},
    )


# Missing data for one stock leaves the other stock's verified grade usable.
def test_grade_inputs_are_filtered_per_stock():
    snap = snapshot()
    snap["quotes"]["OLD"] = {"bar": "2026-09-10T13:45:00+00:00"}
    snap["technical"]["OLD"] = {"now": 0.9, "close": 0.5}
    technical, value = desk_freshness.grade_inputs(snap, {"session": "2026-09-10"}, NOW)
    assert set(technical) == {"AAA"}
    assert set(value) == {"AAA"}


# The displayed votes and ranks must be the ones that produced the grade.
def test_value_only_updates_include_the_current_evidence():
    grade = {
        "stances": {"technical": 0, "fundamental": 1, "value": 0},
        "ranks": {"technical": 0.5, "value": 0.5},
        "score": 0,
    }
    read = holdings._live_grade(grade, None, {"now": 0.9, "close": 0.5, "stance": 1})
    assert read is not None
    assert read["stances"]["value"] == 1
    assert read["ranks"]["value"] == 0.9
    assert read["now"] is None
    assert read["value_now"] == 0.9
