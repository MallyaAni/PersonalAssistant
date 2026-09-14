"""Prove immutable storage, expiry and forward-only funded accounting."""

import json
from datetime import timedelta

import pytest

from backend.agents.trading.desk.intraday_candidate import calculate
from backend.market import funding, intraday_evaluation, intraday_research
from backend.tests.test_intraday_candidate import inputs


# Keep the first decision, reject a changed evening record, and expire stale previews.
def test_archive_is_immutable_and_preview_is_bound_to_its_inputs(tmp_path, monkeypatch):
    record, snapshot, economic, panel, now = inputs()
    result = calculate(record, snapshot, economic, panel, now)
    result["record_sha256"] = intraday_research.record_hash(record)
    monkeypatch.setattr(intraday_research, "build", lambda *args: dict(result))
    first = intraday_research.publish(tmp_path, record, snapshot)
    before = next(tmp_path.rglob("decision-*.json")).read_bytes()
    result["targets"] = {"S0": 0.01}
    assert intraday_research.publish(tmp_path, record, snapshot) == first
    assert next(tmp_path.rglob("decision-*.json")).read_bytes() == before
    loaded = intraday_research.load(tmp_path, record["session"], now)
    assert loaded["status"] == "available"
    assert intraday_research.candidate_record(record, loaded)["book"]
    with pytest.raises(ValueError, match="different evening"):
        intraday_research.candidate_record({**record, "regime": {}}, loaded)
    assert (
        intraday_research.load(
            tmp_path, record["session"], now + timedelta(minutes=30)
        )["status"]
        == "unavailable"
    )
    assert (
        intraday_research.load(tmp_path, record["session"], now - timedelta(minutes=1))[
            "status"
        ]
        == "unavailable"
    )


# Mark storage failures unavailable without exposing filesystem details.
def test_storage_failure_withholds_preview(tmp_path, monkeypatch):
    # Simulate a failed source read without changing the persistence implementation.
    def broken(*args):
        raise OSError("private path")

    monkeypatch.setattr(intraday_research, "build", broken)
    result = intraday_research.publish(tmp_path, {}, {})
    assert result["status"] == "unavailable"
    assert "private" not in json.dumps(result)


# Fill after the recommendation, account for fees, and keep cash nonnegative.
def test_forward_tracker_uses_next_prices_and_real_cash():
    rows = []
    _, _, _, _, now = inputs()
    for i, price in enumerate((10, 20, 30)):
        start = now + timedelta(minutes=15 * i)
        rows.append(
            {
                "bar": start.isoformat(),
                "as_of": (start + timedelta(minutes=16)).isoformat(),
                "valid_until": (start + timedelta(minutes=30)).isoformat(),
                "prices": {"AAA": price},
                "baseline_targets": {"AAA": 1},
                "technical_targets": {"AAA": 0.5},
                "targets": {"AAA": 0},
            }
        )
    one = intraday_evaluation.evaluate(rows[:2])
    assert one["arms"]["baseline_targets"]["return"] < 0  # fees, no same-bar gain
    result = intraday_evaluation.evaluate(rows)
    assert result["fill_intervals"] == 2
    assert 0.49 < result["arms"]["baseline_targets"]["return"] < 0.5
    assert result["arms"]["targets"]["return"] == 0
    assert all(arm["cash"] >= 0 for arm in result["arms"].values())
    assert intraday_evaluation.evaluate([])["status"] == "insufficient_forward_data"
    rows[-1]["prices"] = {}
    with pytest.raises(ValueError, match="Missing next-candle"):
        intraday_evaluation.evaluate(rows)


# Keep fractional reductions separate from available cash and respect event pauses.
def test_reductions_do_not_fund_additions():
    rows = [
        {
            "ticker": "AAA",
            "action": "trim",
            "last": 10,
            "shares": 10.5,
            "target_weight": 0.05,
        },
        {
            "ticker": "BBB",
            "action": "buy",
            "last": 10,
            "shares": 0,
            "target_weight": 0.1,
        },
    ]
    assert funding.reductions(rows, 1000)[0]["reduction_shares"] == 5.5
    assert funding.preview(rows, 1000, 0)["estimated_cost"] == 0
    rows[0]["event_paused"] = True
    assert funding.reductions(rows, 1000) == []
