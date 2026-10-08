"""Immutable forecast admission and real funded account journeys for continuation."""

import json
from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest

from backend.cli.market_learned_entry import sha256, write_json
from backend.market import live_continuation_timing as reader
from backend.market import nonlinear_continuation_evaluation as screen
from backend.market.calendar import NEW_YORK
from backend.market.learned_entry_models import _array_hash
from backend.market.live_policy_replay import run_account
from backend.tests.test_live_policy_replay import fixture


# Write a clearly synthetic numeric transport without pretending to train a model.
def bank_fixture(directory, raw, *, means=(-0.01, 0.01), valid=None):
    directory.mkdir()
    current = raw.observation_close[:, :25].astype(np.float32)
    valid = np.isfinite(current) if valid is None else valid
    values = np.broadcast_to(means, current.shape + (2,)).copy()
    values[~valid] = np.nan
    values[:, 24] = np.nan
    arrays = {"dates": raw.dates, "symbols": np.asarray(raw.tickers),
              "valid": valid, "current_close": current, "predictions": values}
    with (directory / "bank.npz").open("xb") as handle:
        np.savez(handle, **arrays)
    receipt = {
        "schema": screen.SCHEMA, "policy": screen.POLICY,
        "status": "VERIFIED_ALL_MONTHLY_NUMERIC_FORECASTS",
        "bank_sha256": sha256(directory / "bank.npz"),
        "arrays": {key: _array_hash(value) for key, value in arrays.items()},
        "historical_publication": False, "adoption_eligible": False,
        "models_fitted": 0, "accounts_replayed": 0,
        "synthetic_transport_only": True,
    }
    write_json(directory / "receipt.json", receipt)
    return directory, sha256(directory / "receipt.json")


# Refuse altered original bytes rather than using an unauthenticated forecast fallback.
@pytest.mark.parametrize("changed", ["receipt", "bank", "fields"])
def test_transport_hashes_and_exact_fields_are_required(tmp_path, changed):
    _, raw, _ = fixture()
    folder, digest = bank_fixture(tmp_path / "bank", raw)
    if changed == "receipt":
        (folder / "receipt.json").write_text("{}")
    elif changed == "bank":
        (folder / "bank.npz").write_bytes(b"altered")
    else:
        with (folder / "bank.npz").open("wb") as handle:
            np.savez(handle, dates=raw.dates)
        receipt = json.loads((folder / "receipt.json").read_text())
        receipt["bank_sha256"] = sha256(folder / "bank.npz")
        write_json(folder / "receipt.json", receipt)
        digest = sha256(folder / "receipt.json")
    with pytest.raises(ValueError, match="hash differs|bank required|bank fields"):
        screen.ForecastBank(folder, digest)


# Alignment is mandatory and callers cannot mutate the admitted forecast bank.
def test_provider_alignment_and_detached_current_coordinate(tmp_path):
    panel, raw, cubes = fixture()
    source = screen.ForecastBank(*bank_fixture(tmp_path / "bank", raw))
    with pytest.raises(ValueError, match="Aligned continuation"):
        source.provider(1, 0, 0)
    alignment = source.align(panel, raw, cubes)
    assert alignment["available_price_observations_checked"] == 225
    assert not source.means.flags.writeable
    selected = source.provider(1, 0, 0)
    selected[:] = 123
    assert source.provider(1, 0, 0).tolist() == [-0.01, 0.01]
    for bad in ((-1, 0, 0), (1, 25, 0), (1, 0, 3), (True, 0, 0)):
        with pytest.raises(ValueError, match="coordinate"):
            source.provider(*bad)


# Reject ticker, calendar, split-scale or raw-bar mismatches before starting accounts.
@pytest.mark.parametrize("changed", ["symbols", "dates", "scale", "bar"])
def test_price_basis_and_grid_must_match(tmp_path, changed):
    panel, raw, cubes = fixture()
    source = screen.ForecastBank(*bank_fixture(tmp_path / "bank", raw))
    if changed == "symbols":
        raw = replace(raw, tickers=tuple(reversed(raw.tickers)))
    elif changed == "dates":
        raw = replace(raw, dates=raw.dates + np.timedelta64(1, "D"))
    elif changed == "scale":
        panel = replace(panel, adj_close=panel.adj_close * 10)
    else:
        observed = raw.observation_close.copy()
        observed[1, 0, 0] += 0.01
        raw = replace(raw, observation_close=observed)
    with pytest.raises(ValueError, match="differ"):
        source.align(panel, raw, cubes)


# Actual nightly planning, sender, settlement and fees share one funded account path.
def test_authenticated_bank_drives_actual_funded_journey(tmp_path):
    panel, raw, cubes = fixture()
    source = screen.ForecastBank(*bank_fixture(tmp_path / "bank", raw))
    source.align(panel, raw, cubes)
    result = run_account(
        panel, raw, cubes, tmp_path / "account", 1, 2, 10,
        reader_builder=reader.build_reader, provider=source.provider,
    )
    assert result["fills"][0]["price"] == 99
    assert result["fills"][0]["filled_qty"] == 250
    assert result["sessions"][1]["nav"] == pytest.approx(100225.25)
    assert result["broker"]["holdings"] == {"AAA": 250}
    assert result["broker"]["cash"] >= 0
    assert result["forecast_decisions"][0]["state"] == "execute"
    assert result["forecast_decisions"][0]["policy"] == reader.POLICY
    assert result["forecast_decisions"][0]["is_calibrated_confidence"] is False
    assert result["adoption_eligible"] is False


# A predicted wait bypasses the percent dip and preserves the original terminal clock.
def test_authenticated_wait_uses_shared_final_without_one_percent_fallback(tmp_path):
    panel, raw, cubes = fixture()
    source = screen.ForecastBank(*bank_fixture(
        tmp_path / "bank", raw, means=(0.01, -0.01)
    ))
    source.align(panel, raw, cubes)
    result = run_account(
        panel, raw, cubes, tmp_path / "account", 1, 1, 10,
        reader_builder=reader.build_reader, provider=source.provider,
    )
    assert len(result["forecast_decisions"]) == 24
    assert all(row["state"] == "wait" for row in result["forecast_decisions"])
    attempted = datetime.fromisoformat(result["attempts"][0]["at"]).astimezone(NEW_YORK)
    assert (attempted.hour, attempted.minute) == (15, 45)
    assert result["fills"][0]["price"] == 101
    assert result["fills"][0]["filled_qty"] == 250
    assert result["sessions"][-1]["nav"] == pytest.approx(99724.75)


# Missing next-open prices remain unfilled rather than borrowing a profitable later bar.
def test_admitted_forecast_does_not_replace_missing_fill(tmp_path):
    panel, raw, cubes = fixture(missing_fill=True)
    source = screen.ForecastBank(*bank_fixture(tmp_path / "bank", raw))
    source.align(panel, raw, cubes)
    result = run_account(
        panel, raw, cubes, tmp_path / "account", 1, 1, 10,
        reader_builder=reader.build_reader, provider=source.provider,
    )
    assert result["fills"][0]["filled_qty"] == 0
    assert result["fills"][0]["reason"] == "missing_execution_price"
    assert result["broker"]["holdings"] == {}
    assert result["sessions"][-1]["nav"] == 100000


# Retain an excluded early-close session without fabricating complete forecasts.
def test_early_close_is_retained_unavailable(tmp_path):
    panel, raw, cubes = fixture(("2026-11-25", "2026-11-27", "2026-11-30"))
    source = screen.ForecastBank(*bank_fixture(tmp_path / "bank", raw))
    source.align(panel, raw, cubes)
    result = run_account(
        panel, raw, cubes, tmp_path / "account", 1, 1, 10,
        reader_builder=reader.build_reader, provider=source.provider,
    )
    assert len(result["observations"]) == 13
    assert result["broker"]["holdings"] == {}
    assert all(row["state"] == "unavailable" for row in result["forecast_decisions"])


# The fixed screen cannot select an easier account or omit a costly arm.
def test_predeclared_grid_has_only_three_costs_and_start_zero():
    from backend.cli import market_actual_policy_timing as engine

    dates = np.arange("2018-01-31", "2026-10-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)]
    rows = screen.account_grid(engine, dates)
    assert [row["id"] for row in rows] == [
        "continuation-0-0", "continuation-10-0", "continuation-25-0"
    ]
    assert all(row["first_session"] == "2018-02-01" for row in rows)
    assert all(row["start"] == 0 and str(dates[row["last"]]) == "2026-09-30"
               for row in rows)


# Independent decision validation catches changed means, directions and coordinates.
@pytest.mark.parametrize("changed", [None, "mean", "direction", "day", "intent"])
def test_saved_trace_validation_is_independent_of_trade_producer(tmp_path, changed):
    panel, raw, cubes = fixture()
    bank = screen.ForecastBank(*bank_fixture(tmp_path / "bank", raw))
    bank.align(panel, raw, cubes)
    account = run_account(
        panel, raw, cubes, tmp_path / "account", 1, 1, 10,
        reader_builder=reader.build_reader, provider=bank.provider,
    )
    row = account["forecast_decisions"][0]
    if changed is None:
        assert screen.check_trace(account, bank)["execute"] == 1
        return
    if changed == "mean":
        row["continuation_mean"] *= -1
    elif changed == "direction":
        row["state"] = "wait"
    elif changed == "day":
        row["day"] = -1
    else:
        row["desired_qty"] += 1
    with pytest.raises(ValueError, match="decision.*differ"):
        screen.check_trace(account, bank)
