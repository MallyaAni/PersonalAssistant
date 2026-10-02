"""Causal data and inference-contract checks; fake forecasts are not model proof."""

import copy
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.market import open_source_forecasts as forecasts


# Construct completed-session fixture data with explicitly assumed availability.
def payload():
    days = [
        (datetime(2025, 10, 1) + timedelta(days=i)).date().isoformat()
        for i in range(280)
    ]
    rows = [
        {
            "symbol": symbol,
            "session": day,
            "available_at": day + "T20:00:00Z",
            "open": 100 + i,
            "high": 102 + i,
            "low": 99 + i,
            "close": 101 + i,
            "volume": 1000,
        }
        for symbol in ("AAPL", "SPY")
        for i, day in enumerate(days)
    ]
    return {
        "calendar": days,
        "decisions": [days[260]],
        "rows": rows,
        "price_basis": "adjusted_ohlcv",
        "source_revision": "synthetic-test",
        "availability_mode": "session_close_assumed",
        "volume_basis": "provider_reported",
        "data_mode": "reconstructed_snapshot",
    }


class Fake:
    # Return an explicitly mocked finite forecast to isolate data-contract behavior.
    def predict(self, rows, future):
        return np.repeat(rows[-1]["close"] * 1.01, len(future))


# Appending arbitrary future price rows cannot change a causal context or forecast.
def test_future_prefix_invariance():
    data = payload()
    first = forecasts.run(data, "chronos2", ["AAPL", "SPY"], forecaster=Fake())
    other = copy.deepcopy(data)
    for row in other["rows"]:
        if row["session"] > other["decisions"][0]:
            row["close"] = 999999
    assert first == forecasts.run(other, "chronos2", ["AAPL", "SPY"], forecaster=Fake())


# Require the caller to disclose publication assumptions and adjusted price units.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price_basis", "raw"),
        ("availability_mode", None),
        ("volume_basis", None),
        ("data_mode", None),
    ],
)
def test_provenance_is_required(field, value):
    data = payload()
    data[field] = value
    result = forecasts.run(data, "chronos2", ["AAPL"], forecaster=Fake())
    assert result["records"][0]["status"] == "unavailable"


# Missing and duplicated bars remain unavailable rather than being interpolated.
@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_history(duplicate):
    data = payload()
    if duplicate:
        data["rows"].append(copy.deepcopy(data["rows"][100]))
    else:
        data["rows"].pop(100)
    assert (
        forecasts.run(data, "chronos2", ["AAPL"], forecaster=Fake())["records"][0][
            "status"
        ]
        == "unavailable"
    )


# Later publication excludes the bar even when its session falls in the context.
def test_original_publication_time_is_not_observation_time():
    data = payload()
    data["rows"][260]["available_at"] = "2027-01-01T00:00:00Z"
    assert (
        forecasts.run(data, "chronos2", ["AAPL"], forecaster=Fake())["records"][0][
            "status"
        ]
        == "unavailable"
    )


# Checkpoint availability is enforced before a model can score historical rows.
def test_checkpoint_not_available():
    data = payload()
    result = forecasts.run(
        data, "timesfm3", ["AAPL"], research_only=True, forecaster=Fake()
    )
    assert result["records"][0]["reason"] == "checkpoint_not_available"


# The restricted model cannot be constructed for production or commercial use.
def test_noncommercial_gate():
    with pytest.raises(ValueError, match="noncommercial"):
        forecasts.Forecaster("timesfm3")


# A common scaled price basis leaves relative return predictions unchanged.
def test_scale_equivalence():
    data = payload()
    base = forecasts.run(data, "chronos2", ["AAPL"], forecaster=Fake())
    for row in data["rows"]:
        for field in ("open", "high", "low", "close"):
            row[field] *= 10
    changed = forecasts.run(data, "chronos2", ["AAPL"], forecaster=Fake())
    assert (
        base["records"][0]["predicted_excess_return"]
        == changed["records"][0]["predicted_excess_return"]
    )


# Naive timestamps are refused instead of silently assigning local time.
def test_timezone_required():
    with pytest.raises(ValueError, match="timezone"):
        forecasts.aware("2026-10-01T16:00:00")
    assert forecasts.aware("2026-10-01T20:00:00Z").tzinfo == UTC


# Missing optional model dependencies create an explicit retained error opportunity.
def test_missing_runtime_is_explicit():
    class Missing:
        # Simulate an unavailable dependency without pretending to run a model.
        def predict(self, rows, future):
            raise ImportError("optional dependency missing")

    record = forecasts.run(payload(), "chronos2", ["AAPL"], forecaster=Missing())[
        "records"
    ][0]
    assert record["status"] == "model_error"
    assert record["reason"] == "ImportError"


# Invalid model output is an inference failure, not a fabricated data gap.
def test_model_failure_is_distinct_from_input_failure():
    class Invalid:
        # Reject a malformed inference tensor as the real adapter would.
        def predict(self, rows, future):
            raise ValueError("model returned invalid forecast shape")

    record = forecasts.run(payload(), "chronos2", ["AAPL"], forecaster=Invalid())[
        "records"
    ][0]
    assert record["status"] == "model_error"
    assert record["reason"] == "ValueError"


# Risk diagnostics retain their units and cannot be mistaken for return forecasts.
def test_ttm_risk_target_stays_separate():
    result = forecasts.run(payload(), "ttm", ["AAPL"], forecaster=Fake())
    record = result["records"][0]
    assert result["checkpoint"]["target"] == "mean_squared_log_return"
    assert record["predicted_risk"] > 0
    assert "predicted_excess_return" not in record
    assert result["production_eligible"] is False
