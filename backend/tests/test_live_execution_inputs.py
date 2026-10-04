"""Raw conversion uses dated splits and preserves unsupported execution inputs."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from backend.market import live_execution_inputs as adapter
from backend.market.panel import Panel
from backend.market.sip_cube import SessionCube


# Supply matching split-adjusted daily and unconverted raw intraday prices.
def inputs():
    dates = np.array(["2026-09-14", "2026-09-15"], dtype="datetime64[D]")
    daily = np.full((2, 2), 50.0)
    panel = Panel(
        dates,
        ("AAA", "SPY"),
        daily.copy(),
        daily + 1,
        daily - 1,
        daily.copy(),
        daily - 2,
        np.ones_like(daily),
        {},
        "SPY",
    )
    cube = cube_fixture("AAA", dates, [100.0, 50.0])
    return dict(
        panel=panel,
        grades=np.array([[2, 0], [3, 0]], dtype=np.int16),
        eligible=np.ones((2, 2), dtype=bool),
        cubes={"AAA": cube},
        actions={
            "AAA": [{"date": "2026-09-15", "kind": "split", "value": 2.0}],
            "SPY": [],
        },
        basis_as_of={"AAA": "2026-09-15", "SPY": "2026-09-15"},
        complete_through={"AAA": "2026-09-15", "SPY": "2026-09-15"},
        dividend_price_basis="raw_ex_date_share_dollars",
        provenance={
            "daily_source": "synthetic-original",
            "actions_source": "synthetic-dated",
        },
    )


# Split-adjusted dividends must become ex-date dollars before multiplying raw shares.
def test_dividend_amount_basis_is_required_and_dated_splits_recover_raw_cash():
    args = inputs()
    del args["dividend_price_basis"]
    args["actions"]["AAA"].insert(
        0, {"date": "2026-09-14", "kind": "dividend", "value": 0.2}
    )
    with pytest.raises(ValueError, match="dividend.*basis"):
        adapter.prepare(**args)
    args["dividend_price_basis"] = "split_adjusted_archive_share_dollars"
    result = adapter.prepare(**args)
    assert result.actions["AAA"][0]["value"] == pytest.approx(0.4)
    assert result.actions["AAA"][0]["source_value"] == 0.2
    args["dividend_price_basis"] = "raw_ex_date_share_dollars"
    raw = adapter.prepare(**args)
    assert raw.actions["AAA"][0]["value"] == 0.2
    assert args["actions"]["AAA"][0]["value"] == 0.2


# Convert compounded future splits without treating a same-day split as prior shares.
@pytest.mark.parametrize(
    ("ex_day", "expected"), [("2026-09-14", 1.2), ("2026-09-15", 0.6)]
)
def test_dividend_conversion_compounds_only_strictly_later_splits(ex_day, expected):
    args = inputs()
    args["basis_as_of"] = args["complete_through"] = "2026-10-01"
    args["dividend_price_basis"] = "split_adjusted_archive_share_dollars"
    args["actions"]["AAA"].extend([
        {"date": ex_day, "kind": "dividend", "value": 0.2},
        {"date": "2026-10-01", "kind": "split", "value": 3.0},
    ])
    args["actions"]["AAA"].sort(key=lambda row: row["date"])
    result = adapter.prepare(**args)
    dividend = next(row for row in result.actions["AAA"] if row["kind"] == "dividend")
    assert dividend["value"] == pytest.approx(expected)
    assert dividend["source_value"] == 0.2
    assert result.actions["SPY"] == ()


# Construct regular raw cubes without a fabricated opening or auction price.
def cube_fixture(ticker, dates, prices):
    opening = np.broadcast_to(np.array(prices)[:, None], (len(dates), 26)).copy()
    return SessionCube(
        ticker,
        dates.copy(),
        opening.copy(),
        opening + 2,
        opening - 2,
        opening.copy(),
        np.ones_like(opening),
        np.array(prices),
        {"early_close": 0, "incomplete": 0, "no_prior_close": 0},
        np.array(prices) + 1,
        np.ones(len(dates)),
    )


# Recover raw daily high, low and close using the same dated split factor.
def test_dated_split_recovery_and_raw_cube_clocks():
    args = inputs()
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(result.daily_close[:, 0], [100.0, 50.0])
    np.testing.assert_array_equal(result.daily_high[:, 0], [102.0, 51.0])
    np.testing.assert_array_equal(result.daily_low[:, 0], [98.0, 49.0])
    np.testing.assert_array_equal(result.split_factors[:, 0], [2.0, 1.0])
    np.testing.assert_array_equal(
        result.observation_close[:, :, 0], args["cubes"]["AAA"].close[:, :25]
    )
    np.testing.assert_array_equal(
        result.next_open[:, :, 0], args["cubes"]["AAA"].open[:, 1:26]
    )
    np.testing.assert_array_equal(result.session_open[:, 0], [100.0, 50.0])
    assert not np.array_equal(result.daily_close[:, 0], args["panel"].adj_close[:, 0])
    assert np.isnan(result.next_open[:, :, 1]).all()
    assert np.all(result.status[:, 1] == "missing_cube_session")


# Dividends remain explicit cash actions and never scale raw dollars.
def test_dividend_not_used_as_split_or_price_ratio():
    args = inputs()
    args["actions"]["AAA"].append(
        {"date": "2026-09-15", "kind": "dividend", "value": 3.0}
    )
    args["panel"] = replace(args["panel"], adj_close=np.full((2, 2), 1.0))
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(result.daily_close[:, 0], [100.0, 50.0])
    assert [row["kind"] for row in result.actions["AAA"]] == ["split", "dividend"]
    assert result.actions["AAA"][1]["value"] == 3.0


# A coherently revised archive basis leaves historical raw decisions unchanged.
def test_future_split_is_only_archive_unit_conversion():
    original = inputs()
    initial = adapter.prepare(**original)
    revised = inputs()
    revised["panel"] = replace(
        revised["panel"],
        **{
            name: getattr(revised["panel"], name) / 2
            for name in ("open", "high", "low", "close", "adj_close")
        },
    )
    revised["actions"]["AAA"].append(
        {"date": "2026-10-01", "kind": "split", "value": 2.0}
    )
    # SPY's archived dollar basis is unchanged even when its coverage is newer.
    for name in ("open", "high", "low", "close", "adj_close"):
        getattr(revised["panel"], name)[:, 1] *= 2
    revised["basis_as_of"] = "2026-10-01"
    revised["complete_through"] = "2026-10-01"
    later = adapter.prepare(**revised)
    for name in (
        "daily_close",
        "daily_open",
        "daily_high",
        "daily_low",
        "observation_close",
        "next_open",
        "grades",
        "eligible",
    ):
        np.testing.assert_array_equal(getattr(initial, name), getattr(later, name))
    assert later.provenance["future_actions"].startswith("archive_units")


# A future split must not be hidden when the caller leaves prices on a newer basis.
def test_omitted_future_split_is_not_repaired_with_cube_price_ratios():
    args = inputs()
    baseline = adapter.prepare(**args)
    args["actions"]["AAA"].append({"date": "2026-10-01", "kind": "split", "value": 2.0})
    args["basis_as_of"] = args["complete_through"] = "2026-10-01"
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(
        result.daily_close[:, 0], baseline.daily_close[:, 0] * 2
    )
    np.testing.assert_array_equal(result.next_open, baseline.next_open)


# Keep original missing fields while allowing a next open independently of later OHLC.
def test_missing_bars_remain_missing_without_future_close_fill_veto():
    args = inputs()
    args["panel"].high[0, 0] = np.nan
    args["cubes"]["AAA"].close[0, 7] = np.nan
    args["cubes"]["AAA"].open[0, 4] = np.nan
    result = adapter.prepare(**args)
    assert np.isnan(result.daily_high[0, 0])
    assert np.isnan(result.observation_close[0, 7, 0])
    assert result.next_open[0, 6, 0] == 100.0
    assert np.isnan(result.next_open[0, 3, 0])
    assert result.status[0, 0] == "provided_missing_bars"
    np.testing.assert_array_equal(result.dates, args["panel"].dates)


# Preserve early-close daily sessions and never fabricate their excluded regular grid.
def test_early_close_sessions_remain_explicitly_unavailable():
    args = inputs()
    dates = np.array(["2026-11-25", "2026-11-27"], dtype="datetime64[D]")
    args["panel"] = replace(args["panel"], dates=dates)
    args["cubes"]["AAA"] = cube_fixture("AAA", dates[:1], [50.0])
    args["actions"] = {"AAA": [], "SPY": []}
    args["basis_as_of"] = args["complete_through"] = "2026-11-27"
    result = adapter.prepare(**args)
    np.testing.assert_array_equal(result.full_session, [True, False])
    assert np.all(result.status[1] == "unsupported_early_close")
    assert np.isnan(result.observation_close[1]).all()
    assert np.isnan(result.next_open[1]).all()
    assert result.daily_close[1, 0] == 50.0


# Reject duplicate or descending cube sessions instead of choosing an arbitrary row.
@pytest.mark.parametrize("kind", ["duplicate", "descending", "ticker", "shape"])
def test_malformed_cube_grid_refused(kind):
    args = inputs()
    cube = args["cubes"]["AAA"]
    if kind == "duplicate":
        cube = replace(cube, dates=np.repeat(cube.dates[:1], 2))
    elif kind == "descending":
        cube = replace(cube, dates=cube.dates[::-1])
    elif kind == "ticker":
        cube = replace(cube, ticker="OTHER")
    else:
        cube = replace(cube, close=cube.close[:, :25])
    args["cubes"]["AAA"] = cube
    with pytest.raises(ValueError, match="cube|Cube"):
        adapter.prepare(**args)


# Require explicit action types, units, complete coverage and chronological facts.
@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "conflict",
        "negative",
        "unknown",
        "order",
        "absent",
        "coverage",
        "basis",
        "units",
    ],
)
def test_invalid_action_or_basis_contract_refused(kind):
    args = inputs()
    action = args["actions"]["AAA"][0]
    if kind in ("duplicate", "conflict"):
        args["actions"]["AAA"].append(
            {**action, "value": 3.0 if kind == "conflict" else 2.0}
        )
    elif kind == "negative":
        action["value"] = -2
    elif kind == "unknown":
        action["kind"] = "price_adjustment"
    elif kind == "order":
        args["actions"]["AAA"].append(
            {"date": "2026-09-14", "kind": "dividend", "value": 1.0}
        )
    elif kind == "absent":
        del args["actions"]["SPY"]
    elif kind == "coverage":
        args["complete_through"]["AAA"] = "2026-09-14"
    elif kind == "basis":
        args["basis_as_of"]["AAA"] = "2026-09-14"
    else:
        args["daily_price_basis"] = "already_raw"
    with pytest.raises(
        ValueError, match="action|basis|units|coverage|completeness|split-adjusted"
    ):
        adapter.prepare(**args)


# Returned execution grids and nested source metadata cannot mutate supplied sources.
def test_source_nonmutation_and_immutable_outputs():
    args = inputs()
    before = deepcopy(args)
    result = adapter.prepare(**args)
    for field in ("open", "high", "low", "close", "adj_close"):
        np.testing.assert_array_equal(
            getattr(args["panel"], field), getattr(before["panel"], field)
        )
    np.testing.assert_array_equal(
        args["cubes"]["AAA"].open, before["cubes"]["AAA"].open
    )
    assert args["actions"] == before["actions"]
    assert args["provenance"] == before["provenance"]
    with pytest.raises(ValueError, match="read-only"):
        result.next_open[0, 0, 0] = 1
    with pytest.raises(TypeError):
        result.actions["AAA"][0]["value"] = 9
    with pytest.raises(TypeError):
        result.provenance["supplied"]["daily_source"] = "changed"
