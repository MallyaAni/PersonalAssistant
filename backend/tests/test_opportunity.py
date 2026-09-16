"""Scores preserve their actual evidence and never imply a learned return forecast."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.market import opportunity

NOW = datetime(2026, 9, 14, 18, 30, tzinfo=UTC)


# Real nightly records store the rotation vote separately from the four analyst ranks.
def test_recorded_rotation_vote_does_not_require_an_invented_rank():
    grade = {
        "ranks": {
            name: 0.5
            for name in opportunity.grading.ANALYST_WEIGHTS
            if name != "rotation"
        },
        "stances": {"rotation": 0},
    }
    live = {
        "ranks_live": grade["ranks"],
        "technical_now": 0.5,
        "stances_live": grade["stances"],
    }
    result = opportunity.explain(
        grade,
        live,
        {"last": 100},
        (NOW + timedelta(minutes=15)).isoformat(),
        NOW,
        "2026-09-11",
    )
    assert result["score"] == pytest.approx(5)
    rotation = next(p for p in result["parts"] if p["analyst"] == "rotation")
    assert rotation["source"] == "recorded_vote"
    assert rotation["score"] == 5


# All-neutral evidence is five; stronger current technical evidence moves it upward.
def test_score_moves_with_current_evidence_and_explains_weights():
    grade = {
        "ranks": {name: 0.5 for name in opportunity.grading.ANALYST_WEIGHTS},
        "reads": {"value": ["Recorded valuation evidence"]},
    }
    live = {"ranks_live": dict(grade["ranks"]), "technical_now": 0.5}
    args = (
        {"last": 100, "bar": NOW.isoformat()},
        (NOW + timedelta(minutes=15)).isoformat(),
        NOW,
        "2026-09-11",
    )
    first = opportunity.explain(grade, live, *args)
    assert first["score"] == pytest.approx(5)
    live["ranks_live"]["technical"] = 0.9
    later = opportunity.explain(grade, live, *args)
    assert 5 < later["score"] <= 10
    assert later["valuation_current"] is False
    value = next(p for p in later["parts"] if p["analyst"] == "value")
    assert value["basis"] == "2026-09-11"
    assert value["evidence"] == ["Recorded valuation evidence"]
    assert "not a predicted return" in later["method"]


# Missing or expired evidence is unknown, not a neutral or impressive invented score.
@pytest.mark.parametrize("issue", ["missing", "expired", "no_live"])
def test_score_fails_closed_for_missing_or_expired_inputs(issue):
    grade = {"ranks": {name: 0.9 for name in opportunity.grading.ANALYST_WEIGHTS}}
    live = {"ranks_live": dict(grade["ranks"]), "technical_now": 0.9}
    deadline = NOW + timedelta(minutes=15)
    if issue == "missing":
        live["ranks_live"].pop("value")
    elif issue == "expired":
        deadline = NOW
    else:
        live = None
    result = opportunity.explain(
        grade, live, {"last": 100}, deadline.isoformat(), NOW, "2026-09-11"
    )
    assert result["score"] is None
    assert result["status"] == "unavailable"


# After the candle's deadline the score is not current, but the evidence
# still has a reading: the page shows it dated to its bar rather than
# "not scored", which read as if the name had no evidence at all.
def test_the_last_score_survives_the_deadline():
    grade = {"ranks": {name: 0.9 for name in opportunity.grading.ANALYST_WEIGHTS}}
    live = {"ranks_live": dict(grade["ranks"]), "technical_now": 0.9}
    result = opportunity.explain(
        grade,
        live,
        {"last": 100, "bar": "2026-09-14T19:45:00Z"},
        NOW.isoformat(),
        NOW,
        "2026-09-11",
    )
    assert result["score"] is None
    assert result["status"] == "unavailable"
    assert 5 < result["last_score"] <= 10
    live["ranks_live"].pop("value")
    missing = opportunity.explain(
        grade, live, {"last": 100}, NOW.isoformat(), NOW, "2026-09-11"
    )
    assert missing["last_score"] is None
