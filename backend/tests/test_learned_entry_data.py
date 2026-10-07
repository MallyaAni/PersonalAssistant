"""Causality and price-unit acceptance for the learned entry dataset."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.learned_entry_data import FEATURE_NAMES, prepare
from backend.market.sip_cube import SessionCube


# Supply known prior daily context and complete raw regular-session observations.
def _fixture():
    dates = np.busday_offset(np.datetime64("2024-01-02"), np.arange(280))
    daily = np.full((280, 3), 10.0)
    panel = SimpleNamespace(dates=dates, tickers=("AAA", "SPY", "QQQ"), adj_close=daily)
    grades = np.full_like(daily, 2, dtype=int)
    eligible = np.zeros_like(daily, dtype=bool)
    eligible[:, 0] = True
    cubes = {}
    for name in panel.tickers:
        price = np.full((27, 26), 100.0)
        cubes[name] = SessionCube(
            name,
            dates[253:].copy(),
            price.copy(),
            price + 1,
            price - 1,
            price.copy(),
            np.full_like(price, 1000),
            np.full(27, 100.0),
            {"early_close": 2},
            np.full(27, 100.0),
            np.full(27, 1000.0),
        )
    return panel, grades, eligible, cubes


# Changing raw split units must preserve features, adjusted execution and labels.
def test_split_basis_equivalence():
    args = _fixture()
    baseline = prepare(*args)
    changed = deepcopy(args)
    cube = changed[3]["AAA"]
    for field in ("open", "high", "low", "close", "prior_close", "auction_open"):
        getattr(cube, field)[:13] *= 10
    result = prepare(*changed)
    np.testing.assert_allclose(result["X"], baseline["X"], equal_nan=True, atol=1e-7)
    np.testing.assert_allclose(result["y"], baseline["y"], equal_nan=True, atol=1e-7)
    np.testing.assert_allclose(
        result["next_open"], baseline["next_open"], equal_nan=True
    )
    assert result["y"][253, 0, 0, 0] == pytest.approx(0)


# Future bars and grades cannot change an already observed decision prefix.
def test_future_prefix_invariance():
    args = _fixture()
    baseline = prepare(*args)
    changed = deepcopy(args)
    cube = changed[3]["AAA"]
    cube.open[0, 4:] *= 1.2
    cube.close[0, 4:] *= 1.2
    cube.high[0, 4:] *= 1.2
    cube.low[0, 4:] *= 1.2
    changed[1][253:] = 0
    changed[0].adj_close[254:] *= 1.5
    result = prepare(*changed)
    np.testing.assert_allclose(
        result["X"][253, :4], baseline["X"][253, :4], equal_nan=True
    )
    np.testing.assert_array_equal(result["valid"][253, :4], baseline["valid"][253, :4])
    assert result["prior_grades"][253, 0] == 2
    assert not np.array_equal(result["y"][253], baseline["y"][253], equal_nan=True)


# Future official unit conversions cannot enter same-session feature decisions.
def test_future_official_close_is_never_a_feature():
    args = _fixture()
    baseline = prepare(*args)
    args[3]["AAA"].auction_open[0] *= 2
    args[0].adj_close[253, 0] *= 3
    result = prepare(*args)
    np.testing.assert_allclose(result["X"][253], baseline["X"][253], equal_nan=True)
    np.testing.assert_array_equal(result["valid"][253], baseline["valid"][253])
    assert result["next_open"][253, 0, 0] != baseline["next_open"][253, 0, 0]


# Unknown grades remain missing features and cannot create membership permission.
def test_unknown_grade_is_preserved_without_fabrication():
    args = _fixture()
    args[1][252, 0] = -1
    result = prepare(*args)
    assert result["valid"][253, 0, 0]
    assert np.isnan(result["X"][253, 0, 0, FEATURE_NAMES.index("prior_grade")])
    assert result["prior_grades"][253, 0] == -1


# Missing future labels or execution opens must not discard causal observations.
def test_prediction_rows_survive_missing_future_outcomes():
    args = _fixture()
    baseline = prepare(*args)
    changed = deepcopy(args)
    changed[0].adj_close[263, 0] = np.nan
    changed[3]["AAA"].open[0, 1] = np.nan
    result = prepare(*changed)
    np.testing.assert_allclose(
        result["X"][253, 0], baseline["X"][253, 0], equal_nan=True
    )
    assert result["valid"][253, 0, 0]
    assert np.isnan(result["next_open"][253, 0, 0])
    assert np.isnan(result["y"][253, 0, 0, 0])
    assert baseline["valid"][-1, 24, 0]
    assert np.all(np.isnan(baseline["y"][-1, :, 0, :2]))
    assert np.isnat(baseline["label_end_dates"][-1])


# Waiting at the last decision uses the next session's first completed decision.
def test_wait_label_uses_consecutive_next_session():
    args = _fixture()
    args[3]["AAA"].open[1, 1] = 110
    args[3]["AAA"].high[1, 1] = 111
    result = prepare(*args)
    assert result["y"][253, 24, 0, 2] == pytest.approx(np.log(10 / 11))
    assert result["y"][253, 24, 0, 1] == pytest.approx(0)
    missing = deepcopy(args)
    cube = missing[3]["AAA"]
    missing[3]["AAA"] = SessionCube(
        cube.ticker,
        np.concatenate((cube.dates[:1], cube.dates[2:])),
        *[
            np.concatenate((getattr(cube, field)[:1], getattr(cube, field)[2:]))
            for field in ("open", "high", "low", "close", "volume", "prior_close")
        ],
        cube.excluded,
        np.concatenate((cube.auction_open[:1], cube.auction_open[2:])),
        np.concatenate((cube.auction_volume[:1], cube.auction_volume[2:])),
    )
    assert np.isnan(prepare(*missing)["y"][253, 24, 0, 2])


# An observed malformed bar invalidates its prefix and every later decision.
def test_raw_defects_propagate_only_after_observation():
    args = _fixture()
    args[3]["AAA"].high[0, 9] = 90
    result = prepare(*args)
    assert np.all(result["valid"][253, :9, 0])
    assert not np.any(result["valid"][253, 9:, 0])
    assert np.all(result["valid"][254, :, 0])
    assert result["next_open"][253, 8, 0] == pytest.approx(10)
    assert result["y"][253, 7, 0, 2] == pytest.approx(0)


# Later execution-bar defects cannot retroactively cancel the already observed open.
def test_next_open_does_not_consult_its_future_close_or_range():
    args = _fixture()
    baseline = prepare(*args)
    args[3]["AAA"].close[0, 1] = np.nan
    args[3]["AAA"].high[0, 1] = np.nan
    result = prepare(*args)
    assert result["valid"][253, 0, 0]
    assert result["next_open"][253, 0, 0] == baseline["next_open"][253, 0, 0]
    assert not result["valid"][253, 1, 0]


# Missing cubes and prior context remain explicit unavailable observations.
def test_missing_inputs_fail_closed():
    args = _fixture()
    result = prepare(*args[:3], {})
    assert not np.any(result["valid"])
    assert np.all(np.isnan(result["y"]))
    assert result["diagnostics"]["missing_cubes"] == ["AAA", "SPY", "QQQ"]
    args[0].adj_close[250, 0] = np.nan
    result = prepare(*args)
    assert not np.any(result["valid"][:, :, 0])
    assert not np.any(result["valid"][:253])
    assert result["X"].shape == (280, 25, 3, len(FEATURE_NAMES))


# Duplicate dates and malformed shapes must be rejected rather than silently aligned.
def test_source_shapes_and_calendar_are_validated():
    args = _fixture()
    args[3]["AAA"].dates[1] = args[3]["AAA"].dates[0]
    with pytest.raises(ValueError, match="unique"):
        prepare(*args)
    args = _fixture()
    with pytest.raises(ValueError, match="boolean"):
        prepare(args[0], args[1], args[2].astype(int), args[3])


# Daily return clocks end at yesterday and the ten-session endpoint is explicit.
def test_daily_context_and_labels_use_declared_dates():
    args = _fixture()
    args[0].adj_close[:, 0] = 10 * np.exp(np.arange(280) * 0.001)
    result = prepare(*args)
    assert result["X"][253, 0, 0, FEATURE_NAMES.index("return_5")] == pytest.approx(
        0.005
    )
    assert result["X"][253, 0, 0, FEATURE_NAMES.index("return_252")] == pytest.approx(
        0.252
    )
    assert result["y"][253, 0, 0, 0] == pytest.approx(0.010)
    assert result["y"][253, 0, 0, 1] == pytest.approx(0.0001)
    assert result["label_end_dates"][253] == args[0].dates[263]
