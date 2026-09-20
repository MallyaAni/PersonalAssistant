"""Current sizing must preserve facts, caps, freshness and policy separation."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import economist, intraday_candidate, regime
from backend.market.panel import Panel


# Supply a complete synchronized snapshot and a real risk panel with distinct returns.
def inputs():
    now = datetime(2026, 9, 14, 14, 1, tzinfo=UTC)
    names = [f"S{i}" for i in range(12)]
    tickers = tuple(names + ["SPY"])
    dates = np.arange(np.datetime64("2025-09-14"), np.datetime64("2026-09-15"))
    t = np.arange(len(dates))[:, None]
    close = 100 * np.exp(0.0003 * t + 0.03 * np.sin(t * np.arange(1, 14)[None, :] / 20))
    panel = Panel(
        dates,
        tickers,
        close,
        close,
        close,
        close,
        close,
        np.ones_like(close) * 100000,
        {n: ("ai",) for n in names},
        "SPY",
    )
    record = {
        "session": "2026-09-11",
        "regime": {"exposure": 0.8, "tightening": False},
        "grades": {
            n: {
                "grade": "A+",
                "score": 4 + i / 100,
                "stances": {
                    "technical": 1,
                    "value": 1,
                    "fundamental": 1,
                    "sentiment": 1,
                },
                "ranks": {"technical": 0.7, "value": 0.9},
            }
            for i, n in enumerate(names)
        },
        "book": [{"ticker": "S11", "weight": 0.1}],
        "provenance": {"rule": {"inputs": ["expectations-gap"]}},
    }
    snapshot = {
        "as_of": now.isoformat(),
        "decision_session": record["session"],
        "quotes": {
            n: {"last": float(close[-1, i]), "bar": "2026-09-14T13:45:00+00:00"}
            for i, n in enumerate(tickers)
        },
        "technical": {n: {"now": 0.7, "close": 0.7, "stance": 1} for n in names},
        "value": {n: {"now": 0.1, "close": 0.9, "stance": -1} for n in names},
        "technical_detail": {
            "SPY": {"short": {"daily_trend": -1}, "medium": {"weekly_trend": -1}}
        },
    }
    economic = {
        "observed_at": now.isoformat(),
        "assessment": {
            "status": "model_assessment",
            "prompt_version": economist.VERSION,
            "pressure": "building",
            "evidence_ids": ["CPIAUCSL"],
        },
    }
    return record, snapshot, economic, panel, now


# Update grades while preserving the recorded growth-model valuation.
def test_current_grades_change_targets_and_macro_caps_do_not_stack():
    record, snapshot, economic, panel, now = inputs()
    result = intraday_candidate.calculate(record, snapshot, economic, panel, now)
    # Against the constant, not a copy of it. This asserted a literal 0.5 and
    # would have gone on passing if the tightening floor moved for any reason
    # other than the one that moved it.
    assert result["macro"]["exposure"] == regime.TIGHTENING_EXPOSURE
    assert result["macro"]["defensive"]
    assert result["grades"]["S11"]["grade_live"] == "A+"
    assert max(result["targets"].values()) <= 0.15
    assert sum(result["targets"].values()) <= sum(result["technical_targets"].values())
    changed = deepcopy(snapshot)
    changed["technical"]["S11"] = {"now": 0.01, "close": 0.7, "stance": -1}
    after = intraday_candidate.calculate(record, changed, economic, panel, now)
    assert after["grades"]["S11"]["grade_live"] == "B"
    assert after["targets"]["S11"] < result["targets"]["S11"]
    record["regime"]["exposure"] = 0.4
    record["event_risk"] = {"factor": 0.5}
    guarded = intraday_candidate.calculate(record, snapshot, economic, panel, now)
    assert guarded["macro"]["exposure"] == 0.4
    assert guarded["event_paused"]


# Inflation alone cannot activate the candidate's defensive exposure rule.
def test_both_market_horizons_are_required():
    record, snapshot, economic, panel, now = inputs()
    snapshot["technical_detail"]["SPY"]["medium"]["weekly_trend"] = 1
    result = intraday_candidate.calculate(record, snapshot, economic, panel, now)
    assert result["macro"]["exposure"] == 0.8
    assert not result["macro"]["defensive"]


# Withhold sizing instead of interpreting missing data as permission to add risk.
@pytest.mark.parametrize(
    "fault",
    [
        "price",
        "technical",
        "stale",
        "economic",
        "unknown",
        "mixed_bars",
        "invalid_price",
    ],
)
def test_incomplete_evidence_withholds_the_candidate(fault):
    record, snapshot, economic, panel, now = inputs()
    if fault == "price":
        snapshot["quotes"].pop("S0")
    elif fault == "technical":
        snapshot["technical"].pop("S0")
    elif fault == "stale":
        now += timedelta(minutes=15)
    elif fault == "economic":
        economic["observed_at"] = (now - timedelta(days=2)).isoformat()
    elif fault == "unknown":
        economic["assessment"]["pressure"] = "unknown"
    elif fault == "mixed_bars":
        snapshot["quotes"]["S0"]["bar"] = "2026-09-14T13:44:00+00:00"
    else:
        snapshot["quotes"]["S0"]["last"] = float("nan")
    with pytest.raises(ValueError, match="required"):
        intraday_candidate.calculate(record, snapshot, economic, panel, now)
