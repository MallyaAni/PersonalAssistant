"""Failure-first economics and causality checks for the fixed timing diagnostic."""

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.cli.market_entry_exit_study import main
from backend.market import entry_exit_study as study
from backend.market.sip_cube import SessionCube


# Declare a rising or falling complete session with an independent official close.
def cube(closes, opens=None, lows=None):
    closes = np.r_[closes, np.repeat(closes[-1], 26 - len(closes))].astype(float)
    opens = (
        np.r_[100.0, closes[:-1]] if opens is None else np.asarray(opens, dtype=float)
    )
    lows = (
        np.minimum(opens, closes) - 0.2
        if lows is None
        else np.asarray(lows, dtype=float)
    )
    return SessionCube(
        "AAA",
        np.array(["2016-01-05"], dtype="datetime64[D]"),
        opens[None],
        np.maximum(opens, closes)[None] + 0.2,
        lows[None],
        closes[None],
        np.ones((1, 26)),
        np.array([100.0]),
        {},
        np.array([closes[-1]]),
        np.array([1.0]),
    )


# Demonstrate the unchanged pop rule sells before a continuing rise on this path.
def test_trailing_exit_waits_for_observed_weakness_without_peeking():
    opens = np.array([100.0, 101.0, 103.0, 105.0, 107.0])
    closes = np.array([101.0, 103.0, 105.0, 107.0, 104.0])
    lows = np.array([99.0, 100.0, 102.0, 104.5, 103.0])
    assert study.signal_slot(opens, lows, closes, "sell", study.CONTROL) == 0
    assert (
        study.signal_slot(opens[:-1], lows[:-1], closes[:-1], "sell", study.EXIT)
        is None
    )
    assert study.signal_slot(opens, lows, closes, "sell", study.EXIT) == 4


# Require a later completed confirmation rather than buying the falling dip bar.
def test_entry_confirmation_can_fail_on_a_continuing_fall():
    opens = np.array([100.0, 98.0, 96.0, 94.0])
    closes = np.array([98.0, 96.0, 94.0, 96.0])
    lows = np.array([97.0, 95.0, 93.0, 93.0])
    assert study.signal_slot(opens, lows, closes, "buy", study.CONTROL) == 0
    assert study.signal_slot(opens, lows, closes, "buy", study.ENTRY) is None
    closes[-1] = 97.5
    assert study.signal_slot(opens, lows, closes, "buy", study.ENTRY) == 3


# Keep a confirmed signal identical when unrelated future bars are appended.
@pytest.mark.parametrize(("arm", "side"), [(study.ENTRY, "buy"), (study.EXIT, "sell")])
def test_confirmed_signal_is_future_prefix_invariant(arm, side):
    opens, lows, closes = (
        np.array([100.0, 98.0, 101.0]),
        np.array([97.0, 97.0, 96.0]),
        np.array([98.0, 102.0, 96.5]),
    )
    prefix = study.signal_slot(opens, lows, closes, side, arm)
    assert prefix is not None
    assert (
        study.signal_slot(
            np.r_[opens, 1000.0], np.r_[lows, 1.0], np.r_[closes, 500.0], side, arm
        )
        == prefix
    )


# Reject malformed evidence instead of treating it as a real price signal.
@pytest.mark.parametrize("defect", ["nan", "low", "length", "side", "arm"])
def test_invalid_prefix_is_refused(defect):
    opens, lows, closes = (
        np.array([100.0, 99.0]),
        np.array([98.0, 97.0]),
        np.array([99.0, 98.0]),
    )
    side, arm = "buy", study.ENTRY
    if defect == "nan":
        opens[0] = np.nan
    elif defect == "low":
        lows[0] = 101
    elif defect == "length":
        closes = closes[:1]
    elif defect == "side":
        side = "unknown"
    else:
        arm = "unknown"
    with pytest.raises(ValueError, match="required"):
        study.signal_slot(opens, lows, closes, side, arm)


# Verify next-open execution and unit equivalence across a synthetic split basis.
def test_grids_use_next_bar_open_and_do_not_mix_price_bases():
    raw = cube([98.0, 99.0, 100.0])
    panel = SimpleNamespace(
        dates=raw.dates, tickers=("AAA",), adj_close=np.array([[10.0]])
    )
    grids, available = study.grids(panel, {"AAA": raw})
    assert available[0, 0]
    assert grids[study.CONTROL]["buy_slot"][0, 0] == 1
    assert grids[study.ENTRY]["buy_slot"][0, 0] == 2
    assert grids[study.CONTROL]["buy"][0, 0] == pytest.approx(9.8)
    assert grids[study.ENTRY]["buy"][0, 0] == pytest.approx(9.9)
    raw.open[:] *= 10
    raw.high[:] *= 10
    raw.low[:] *= 10
    raw.close[:] *= 10
    raw.auction_open[:] *= 10
    equivalent, _ = study.grids(panel, {"AAA": raw})
    for arm in study.ARMS:
        assert np.array_equal(equivalent[arm]["buy_slot"], grids[arm]["buy_slot"])
        assert np.allclose(equivalent[arm]["buy"], grids[arm]["buy"])


# Retain a missing session as an explicit common close assumption in every arm.
def test_missing_cube_is_common_close_fallback_not_a_fabricated_signal():
    panel = SimpleNamespace(
        dates=np.array(["2016-01-05"], dtype="datetime64[D]"),
        tickers=("AAA",),
        adj_close=np.array([[120.0]]),
    )
    grids, available = study.grids(panel, {})
    assert not available.any()
    for arm in study.ARMS:
        assert grids[arm]["sell"][0, 0] == 120
        assert grids[arm]["sell_slot"][0, 0] == 26


# Reserve earlier sale proceeds from buys under the declared night-cash budget.
def test_shared_ledger_reserves_sale_cash_and_charges_actual_fills():
    book = simulate._Book(2, 1.0, 25.0, None, None, None)
    book.shares[:] = (0.01, 0.0)
    book.cash = 0.0
    budget, _ = study.fill_batch(
        book, np.array([0.0, 0.0]), np.array([110.0, np.nan]), 1, 0.0
    )
    assert book.cash == pytest.approx(1.1 * 0.9975)
    assert budget == 0
    study.fill_batch(book, np.array([0.0, 0.01]), np.array([np.nan, 100.0]), 1, budget)
    assert book.shares[1] == 0
    assert book.cash == pytest.approx(1.1 * 0.9975)
    assert book.traded == pytest.approx(1.1)


# Exercise the continuous funded runner with downgrade exits and price-only missingness.
def test_funded_account_exits_downgrade_and_keeps_inputs_unchanged():
    dates = np.array(
        ["2016-01-04", "2016-01-05", "2016-01-06", "2016-01-07"], dtype="datetime64[D]"
    )
    values = np.full((4, 3), 100.0)
    panel = SimpleNamespace(
        dates=dates,
        tickers=("AAA", "SPY", "QQQ"),
        open=values.copy(),
        close=values.copy(),
        adj_close=values.copy(),
    )
    grades = np.full((4, 3), 2)
    grades[1:, 0] = 1
    eligible = np.zeros((4, 3), dtype=bool)
    eligible[:, 0] = True
    grids, available = study.grids(panel, {})
    result = study.account(
        panel,
        grades,
        eligible,
        grids[study.CONTROL],
        available,
        first=0,
        phase=0,
        cost=10.0,
        line=study.CONTROL,
    )
    assert result["opportunities"] == 2
    assert result["missing_cube_close_fallbacks"] == 2
    assert result["fees"].sum() == pytest.approx(0.0005)
    assert result["nav"][-1] == pytest.approx(0.9995)
    assert result["cash"][-1] == pytest.approx(result["nav"][-1])
    assert np.array_equal(panel.adj_close, values)


# Prove trailing a continuing rise changes funded net wealth, not just a signal label.
def test_exit_candidate_changes_funded_wealth_on_independent_rising_path():
    dates = np.array(
        ["2016-01-04", "2016-01-05", "2016-01-06", "2016-01-07"], dtype="datetime64[D]"
    )
    values = np.full((4, 3), 100.0)
    values[2:, 0] = 110.0
    panel = SimpleNamespace(
        dates=dates,
        tickers=("AAA", "SPY", "QQQ"),
        open=values.copy(),
        close=values.copy(),
        adj_close=values.copy(),
    )
    raw = cube([101.0, 103.0, 105.0, 110.0])
    raw.dates[0] = dates[2]
    grades = np.full((4, 3), 2)
    grades[1:, 0] = 1
    eligible = np.zeros((4, 3), dtype=bool)
    eligible[:, 0] = True
    grids, available = study.grids(panel, {"AAA": raw})
    accounts = {
        arm: study.account(
            panel,
            grades,
            eligible,
            grids[arm],
            available,
            first=0,
            phase=0,
            cost=25.0,
            line=arm,
        )
        for arm in (study.CONTROL, study.EXIT)
    }
    assert accounts[study.EXIT]["nav"][-1] > accounts[study.CONTROL]["nav"][-1]
    assert accounts[study.EXIT]["nav"][-1] == pytest.approx(
        0.75 - 0.25 * 0.0025 + 0.275 * 0.9975
    )
    assert accounts[study.CONTROL]["nav"][-1] == pytest.approx(
        0.75 - 0.25 * 0.0025 + 0.2525 * 0.9975
    )
    assert (
        accounts[study.EXIT]["opportunities"]
        == accounts[study.CONTROL]["opportunities"]
        == 2
    )


    assert accounts[study.EXIT]["intraday_fills"] == 0
    assert accounts[study.CONTROL]["intraday_fills"] == 1


# Run the actual CLI, bind source bytes and refuse overwriting research evidence.
def test_actual_cli_prices_both_costs_and_preserves_immutable_inputs(tmp_path):
    snapshot, metadata, output = (
        tmp_path / name for name in ("source.npz", "source.json", "result.json")
    )
    dates = np.array(
        ["2016-01-04", "2016-01-05", "2016-01-06", "2016-01-07"], dtype="datetime64[D]"
    )
    prices = np.full((4, 3), 100.0)
    eligible = np.zeros((4, 3), dtype=bool)
    eligible[:, 0] = True
    np.savez(
        snapshot,
        dates=dates,
        symbols=np.array(["AAA", "SPY", "QQQ"]),
        open=prices,
        close=prices,
        adj_close=prices,
        grades=np.full((4, 3), 2),
        eligible=eligible,
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    metadata.write_text(
        json.dumps(
            {
                "snapshot_sha256": digest,
                "price_basis": "close-ratio-adjusted",
                "eligibility_mode": "conditional-price-only",
                "source_hashes": {"fixture": "a" * 64},
            }
        )
    )
    cubes = tmp_path / "cubes"
    cubes.mkdir()
    args = [
        "--snapshot",
        str(snapshot),
        "--provenance",
        str(metadata),
        "--cubes",
        str(cubes),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    result = json.loads(output.read_text())
    assert result["adoption_eligible"] is False
    assert [item["cost_bps"] for item in result["costs"]] == [10.0, 25.0]
    assert len(result["costs"][0]["phases"]) == 20
    phase = result["costs"][0]["phases"][0]["results"]
    assert phase[0]["missing_cube_close_fallbacks"] > 0
    assert phase[0]["windows"] == phase[1]["windows"] == phase[2]["windows"]
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == digest
    prior = output.read_bytes()
    with pytest.raises(SystemExit):
        main(args)
    assert output.read_bytes() == prior
