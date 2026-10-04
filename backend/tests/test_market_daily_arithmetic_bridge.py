"""Exercise declared evidence boundaries, carried score windows and real persistence."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_daily_arithmetic_bridge as cli
from backend.market.daily_bridge_replay import run_account


# Construct a marked return path with known compounded gain and reference excess.
def account():
    return {
        "dates": np.array(
            ["2026-09-28", "2026-09-29", "2026-09-30"], dtype="datetime64[D]"
        ),
        "nav": np.array([1.0, 1.1, 1.21]),
        "exposure": np.array([0.0, 0.5, 0.5]),
        "turnover": np.array([0.0, 0.25, 0.0]),
        "fees": np.array([0.0, 0.001, 0.0]),
    }


# Compound carried returns and subtract matched reference gains without resetting books.
def test_scores_report_matched_net_gain_and_reference_excess():
    own = account()
    reference = {**own, "nav": np.array([1.0, 1.05, 1.1025])}
    measured = cli.score(own, {"SPY": reference})
    full = measured["windows"][0]
    assert full["total_net_gain"] == pytest.approx(0.21)
    assert full["excess_gain"]["SPY"] == pytest.approx(0.1075)
    assert full["max_drawdown_loss"] == 0
    assert full["gross_trading_per_year"] == pytest.approx(31.5)
    assert full["fees_initial_nav_units"] == 0.001
    assert measured["windows"][1]["status"] == "unavailable"
    assert measured["windows"][3]["total_net_gain"] == full["total_net_gain"]


# Reject incomplete NAV or mismatched clocks instead of publishing a favorable subset.
@pytest.mark.parametrize("boundary", ["nav", "dates"])
def test_invalid_score_boundary_is_rejected(boundary):
    own, reference = account(), account()
    if boundary == "nav":
        own["nav"][1] = np.nan
    else:
        reference["dates"][1] += np.timedelta64(1, "D")
    with pytest.raises(ValueError, match="marks|dates"):
        cli.score(own, {"SPY": reference})


# Preserve null evidence while refusing unsafe nonfinite or opaque receipt values.
def test_json_numeric_conversion_preserves_missing_evidence():
    assert cli.readable_value(
        {"prices": np.array([1, np.nan]), "known": np.bool_(True)}
    ) == {"prices": [1.0, None], "known": True}
    with pytest.raises(ValueError, match="Infinite"):
        cli.readable_value(np.inf)
    with pytest.raises(ValueError, match="Unsupported"):
        cli.readable_value(object())


# Read a real account artifact back, including nested plans and missing prices.
def test_actual_account_numeric_and_receipt_persistence(tmp_path):
    prices = np.full((4, 4), 10.0)
    prices[:, 1] = np.nan
    panel = SimpleNamespace(
        dates=np.array(
            ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"],
            dtype="datetime64[D]",
        ),
        tickers=("X", "Y", "SPY", "QQQ"),
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    result = run_account(
        panel,
        np.full(prices.shape, 2),
        np.ones(prices.shape, bool),
        np.full(prices.shape, np.nan),
        method="equal",
        cost_bps=10,
        first=0,
    )
    record = cli.save_account(tmp_path, "equal", result, cli.score(result, {}))
    assert cli.digest(tmp_path / record["arrays_file"]) == record["arrays_sha256"]
    saved = cli.arrays(tmp_path / record["arrays_file"])
    np.testing.assert_array_equal(saved["nav"], result["nav"])
    np.testing.assert_array_equal(saved["shares"], result["shares"])
    assert np.isnan(saved["prices_open"][:, 1]).all()
    receipt = json.loads((tmp_path / record["receipt_file"]).read_bytes())
    assert receipt["account"]["allocation_trace"][0]["prices"][1] is None
    assert receipt["account"]["prices"] == {
        "open": "prices_open",
        "close": "prices_close",
    }
    assert receipt["score"]["windows"][0]["total_net_gain"] == pytest.approx(
        result["nav"][-1] - 1
    )


# A completed artifact cannot be replaced by a later call with a different result.
def test_persistence_refuses_existing_evidence(tmp_path):
    path = tmp_path / "receipt.json"
    cli.write_json(path, {"value": 1})
    with pytest.raises(ValueError, match="overwritten"):
        cli.write_json(path, {"value": 2})
    assert json.loads(path.read_bytes()) == {"value": 1}
