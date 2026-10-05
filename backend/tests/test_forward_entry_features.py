"""Historical/live feature parity and actual completed-prefix acceptance."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market.forward_entry_features import observe
from backend.market.learned_entry_data import prepare
from backend.market.sip_cube import SessionCube


# Supply identical prior context and distinct raw stock paths on a reviewed calendar.
def fixture(session="2023-11-27"):
    _, calendar = exchange.reviewed_sessions()
    dates = np.arange("2022-01-03", np.datetime64(session) + np.timedelta64(1, "D"))
    dates = dates[np.is_busday(dates, busdaycal=calendar)]
    rng = np.random.default_rng(842)
    prices = 20 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(dates), 4)), axis=0))
    panel = SimpleNamespace(
        dates=dates, tickers=("AAA", "BBB", "SPY", "QQQ"), adj_close=prices
    )
    grades = rng.integers(0, 4, prices.shape)
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, 2:] = False
    cubes = {}
    for stock, symbol in enumerate(panel.tickers):
        closing = (100 + stock * 10 + np.cumsum(rng.normal(0, 0.5, 26)))[None, :]
        opening = np.concatenate(([100 + stock * 10], closing[0, :-1]))[None, :]
        cubes[symbol] = SessionCube(
            symbol,
            dates[-1:].copy(),
            opening,
            np.maximum(opening, closing) + 0.2,
            np.minimum(opening, closing) - 0.2,
            closing,
            rng.integers(100, 1000, (1, 26)),
            np.array([99 + stock * 10.0]),
            {},
            np.array([np.nan]),
            np.array([np.nan]),
        )
    return panel, grades, eligible, cubes


# Strip unavailable current prices and supply only actually completed raw bars.
def current(args, count, *, delay=0):
    panel, grades, eligible, cubes = args
    session = panel.dates[-1].astype(object)
    opening = datetime.combine(session, exchange.REGULAR_OPEN, exchange.NEW_YORK)
    completed = opening + timedelta(minutes=15 * count)
    prior = SimpleNamespace(
        dates=panel.dates[:-1], tickers=panel.tickers, adj_close=panel.adj_close[:-1]
    )
    records = {
        symbol: {
            **{
                name: getattr(cube, name)[0, :count].copy()
                for name in ("open", "high", "low", "close", "volume")
            },
            "prior_close": cube.prior_close[0],
            "starts": [
                opening + timedelta(minutes=15 * index) for index in range(count)
            ],
            "published_at": completed + timedelta(seconds=delay),
        }
        for symbol, cube in cubes.items()
    }
    return (prior, grades[:-1], eligible[:-1], records), {
        "observed_at": completed + timedelta(seconds=delay),
        "daily_as_of": datetime.combine(
            panel.dates[-2].astype(object),
            exchange.session_close(panel.dates[-2].astype(object)),
            exchange.NEW_YORK,
        ),
    }


# Original stock/clock features must agree without current official prices.
@pytest.mark.parametrize("count", range(1, 26))
def test_all_regular_prefixes_match_actual_historical_builder(count):
    args = fixture()
    expected = prepare(*args)
    inputs, clocks = current(args, count)
    actual = observe(*inputs, **clocks)
    np.testing.assert_array_equal(actual["features"], expected["X"][-1, count - 1])
    np.testing.assert_array_equal(actual["valid"], expected["valid"][-1, count - 1])
    assert actual["symbols"] == args[0].tickers
    assert actual["clock"] == count - 1
    assert not {"labels", "next_open", "target", "orders"} & set(actual)


# Raw split units and unseen bars/prices cannot alter an observed feature vector.
def test_split_units_and_future_prefix_invariance():
    args = fixture()
    inputs, clocks = current(args, 4)
    before = observe(*inputs, **clocks)
    changed = deepcopy(args)
    changed[0].adj_close[-1] *= 9
    cube = changed[3]["AAA"]
    for name in ("open", "high", "low", "close"):
        getattr(cube, name)[0, :4] *= 10
        getattr(cube, name)[0, 4:] = 1000
    cube.prior_close[:] *= 10
    changed[1][-1] = -1
    changed_inputs, changed_clocks = current(changed, 4)
    after = observe(*changed_inputs, **changed_clocks)
    np.testing.assert_array_equal(before["features"], after["features"])
    np.testing.assert_array_equal(before["valid"], after["valid"])
    assert before["identity"]["prefixes"]["AAA"] != after["identity"]["prefixes"]["AAA"]


# Real publication delay is recorded without mislabelling a forming candle as completed.
def test_actual_publication_delay_retains_completed_clock():
    inputs, clocks = current(fixture(), 2, delay=3)
    result = observe(*inputs, **clocks)
    assert result["completed_at"] == "2023-11-27T10:00:00-05:00"
    assert result["observed_at"] == "2023-11-27T10:00:03-05:00"
    assert result["timing_supported"]
    assert (
        result["identity"]["prefixes"]["AAA"]["published_at"] == result["observed_at"]
    )


# Missing names and defective observed bars remain unavailable rather than invented.
def test_missing_and_invalid_stock_inputs_are_retained():
    inputs, clocks = current(fixture(), 3)
    del inputs[3]["BBB"]
    inputs[3]["AAA"]["high"][1] = 1
    result = observe(*inputs, **clocks)
    assert not result["valid"][0]
    assert not result["valid"][1]
    assert np.isnan(result["features"][1]).all()
    assert result["valid"][2:].all()
    assert result["features"].shape == (4, 21)


# Unknown grades remain missing features; missing daily history affects stock validity.
def test_unknown_grade_and_daily_missingness():
    inputs, clocks = current(fixture(), 3)
    inputs[1][-1, 0] = -1
    inputs[0].adj_close[-20, 1] = np.nan
    result = observe(*inputs, **clocks)
    assert result["valid"][0]
    assert np.isnan(result["features"][0, 8])
    assert not result["valid"][1]


# Timestamp gaps, forming bars and unpublished source records cannot enter prediction.
@pytest.mark.parametrize(
    "defect", ["gap", "forming", "future_publication", "old_publication"]
)
def test_prefix_clock_defects_are_rejected(defect):
    inputs, clocks = current(fixture(), 3)
    record = inputs[3]["AAA"]
    if defect == "gap":
        record["starts"][1] += timedelta(minutes=15)
    elif defect == "forming":
        record["close"] = np.append(record["close"], 99)
    else:
        record["published_at"] += timedelta(
            seconds=1 if defect == "future_publication" else -1
        )
    with pytest.raises(ValueError, match="prefix"):
        observe(*inputs, **clocks)


# Missing exchange dates and incomplete daily publication cannot create prior context.
def test_prior_calendar_and_actual_daily_clock_rejected():
    inputs, clocks = current(fixture(), 3)
    with pytest.raises(ValueError, match="prior history"):
        observe(
            *inputs,
            **{**clocks, "daily_as_of": clocks["observed_at"] + timedelta(seconds=1)},
        )
    inputs[0].dates = np.delete(inputs[0].dates, 20)
    inputs[0].adj_close = np.delete(inputs[0].adj_close, 20, axis=0)
    with pytest.raises(ValueError, match="prior history"):
        observe(
            inputs[0],
            np.delete(inputs[1], 20, axis=0),
            np.delete(inputs[2], 20, axis=0),
            inputs[3],
            **clocks,
        )


# Early closes use actual support and refuse a nonexistent afternoon regular prefix.
def test_early_close_support_and_after_close_rejected():
    args = fixture("2023-11-24")
    inputs, clocks = current(args, 13)
    result = observe(*inputs, **clocks)
    assert result["valid"].all()
    assert result["completed_at"] == "2023-11-24T12:45:00-05:00"
    assert not result["timing_supported"]
    inputs, clocks = current(args, 15)
    with pytest.raises(ValueError, match="regular observation"):
        observe(*inputs, **clocks)
