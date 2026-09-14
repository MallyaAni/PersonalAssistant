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
        "2026-09-11T13:55:00+00:00",
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


# Browser deadlines expire on the first stale dependency, not the newest one.
def test_browser_deadline_respects_the_earlier_quote_or_snapshot_expiry():
    snap = snapshot()
    snap["quotes"]["OLDER"] = {"bar": "2026-09-11T13:35:00+00:00"}
    dates = desk_freshness.grade_expiries(snap, ["AAA", "OLDER", "MISSING"])
    assert dates == {
        "AAA": "2026-09-11T14:15:00+00:00",
        "OLDER": "2026-09-11T14:05:00+00:00",
    }
    assert desk_freshness.grade_expiries({}, ["AAA"]) == {}


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


# A plain-value reading cannot replace the recorded growth-model valuation vote.
def test_growth_model_grade_keeps_its_valuation_in_both_live_paths():
    record = {
        "provenance": {"rule": {"inputs": ["expectations-gap"]}},
        "grades": {
            "AAA": {
                "grade": "A+",
                "score": 3.0,
                "stances": {
                    "fundamental": 1,
                    "technical": 1,
                    "sentiment": 1,
                    "value": 1,
                },
                "ranks": {
                    "fundamental": 0.8,
                    "technical": 0.8,
                    "sentiment": 0.8,
                    "value": 0.8,
                },
            }
        },
        "book": [{"ticker": "AAA", "weight": 0.1}],
    }
    technical = {"AAA": {"now": 0.8, "close": 0.8, "stance": 1}}
    plain_value = {"AAA": {"now": 0.2, "close": 0.2, "stance": -1}}
    ranked = holdings.live_grades(record, technical, plain_value)["AAA"]
    board = holdings.board(
        record, [], 10000, {"AAA": {"last": 100}}, technical, plain_value
    )[0]
    for row in (ranked, board):
        assert row["grade_live"] == "A+"
        assert row["stances_live"]["value"] == 1
        assert row["ranks_live"]["value"] == 0.8
        assert row["value_now"] is None
        assert row["score_live"] == 3.0
    assert holdings.live_grades(record, {}, plain_value) == {}
