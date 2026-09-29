"""Stage 3's shared contract: the folds, the files, the transforms."""

import math

import numpy as np
import pytest

from backend.market import stage3_io as io


def _dates(n: int, start: str = "2020-01-01") -> np.ndarray:
    return np.arange(np.datetime64(start), np.datetime64(start) + n).astype("datetime64[D]")


def test_registration_counts_match_the_plan():
    # 8 LightGBM and 8 sequence configurations; 8 outer candidates, 50 configuration-level.
    assert len(io.LGBM_GRID) == 8
    assert len(io.SEQ_GRID) == 8
    assert {c["num_leaves"] for c in io.LGBM_GRID} == {15, 63}
    assert {c["min_data_in_leaf"] for c in io.LGBM_GRID} == {200, 1000}
    outer = sum(2 if kind == io.TI else 1 for kind, fams in io.FAMILIES.items() for _ in fams)
    assert outer == io.OUTER_CANDIDATES == 8
    ti = (len(io.LGBM_GRID) + len(io.SEQ_GRID)) * 2
    s1 = len(io.LGBM_GRID) + 2 + len(io.SEQ_GRID)
    assert ti + s1 == io.CONFIG_TRIALS == 50
    assert io.GAP == {io.S1: 26, io.TI: 6}


def test_folds_never_let_training_or_validation_reach_the_test_block():
    n, refit, gap = 1400, 126, 6
    out = io.folds(n, refit, gap)
    assert out[0].test_start == io.MIN_TRAIN
    assert out[-1].test_end == n
    for a, b in zip(out[:-1], out[1:], strict=True):
        assert a.test_end == b.test_start
    for f in out:
        assert f.window_end == f.test_start - gap
        assert f.window_end - f.val_start == io.VALIDATION
        assert f.fit_end == f.val_start - gap
        assert 0 < f.fit_end < f.val_start < f.window_end < f.test_start


def test_folds_refuse_a_window_with_no_fit_part():
    with pytest.raises(ValueError, match="no fit sessions"):
        io.folds(600, 63, 26, min_train=250)


def test_fold_rows_selects_half_open_ranges():
    index = np.array([0, 0, 1, 2, 2, 3])
    assert io.Fold.rows(index, 1, 3).tolist() == [2, 3, 4]


def _data(kind=io.S1, rows=6):
    dates = np.repeat(_dates(rows // 2), 2)
    tickers = np.array(["A", "B"] * (rows // 2))
    return io.Stage3Data(
        kind=kind,
        dates=dates,
        tickers=tickers,
        slot=np.zeros(rows, dtype=np.int8),
        x=np.arange(rows * 3, dtype=np.float32).reshape(rows, 3),
        feature_names=("a", "b", "c"),
        y=np.linspace(-1, 1, rows).astype(np.float32),
        extra={"r": np.arange(rows, dtype=np.float32)},
        meta={"note": "unit"},
    )


def test_data_round_trips_through_npz(tmp_path):
    data = _data()
    path = io.save_data(tmp_path / "d.npz", data)
    back = io.load_data(path)
    assert back.kind == io.S1
    assert back.feature_names == ("a", "b", "c")
    np.testing.assert_array_equal(back.x, data.x)
    np.testing.assert_array_equal(back.extra["r"], data.extra["r"])
    assert back.meta["plan"] == io.PLAN and back.meta["note"] == "unit"


def test_validate_refuses_unsorted_rows_and_shape_mismatches():
    data = _data()
    shuffled = io.Stage3Data(
        data.kind, data.dates[::-1], data.tickers[::-1], data.slot, data.x, data.feature_names, data.y
    )
    with pytest.raises(ValueError, match="sorted"):
        io.validate(shuffled)
    bad = io.Stage3Data(data.kind, data.dates, data.tickers, data.slot, data.x[:, :2], data.feature_names, data.y)
    with pytest.raises(ValueError, match="expected"):
        io.validate(bad)


def test_rank_gauss_is_symmetric_per_date_and_keeps_nan():
    dates = np.repeat(_dates(2), 4)
    values = np.array([1.0, 2.0, 3.0, 4.0, 10.0, np.nan, 10.0, 30.0])
    out = io.rank_gauss(values, dates)
    assert np.allclose(out[:4], -out[:4][::-1])
    assert math.isnan(out[5])
    # Ties share the average rank: the two 10s on the second date are equal.
    assert out[4] == out[6] and out[7] > out[4]


def test_rank_gauss_panel_matches_the_per_date_transform():
    rng = np.random.default_rng(0)
    values = rng.normal(size=(3, 5, 2))
    mask = np.ones((3, 5), dtype=bool)
    mask[1, 2] = False
    out = io.rank_gauss_panel(values, mask)
    assert math.isnan(out[1, 2, 0])
    dates = np.repeat(_dates(3), 5)
    flat = np.where(mask.reshape(-1), values[:, :, 1].reshape(-1), np.nan)
    np.testing.assert_allclose(out[:, :, 1].reshape(-1), io.rank_gauss(flat, dates), equal_nan=True)


def test_selection_score_pools_for_ti_and_averages_dates_for_s1():
    dates = np.repeat(_dates(2), 6)
    y = np.tile(np.arange(6.0), 2)
    assert io.selection_score(io.TI, y, y, dates) == pytest.approx(1.0)
    yhat = np.concatenate([np.arange(6.0), -np.arange(6.0)])
    assert io.selection_score(io.S1, yhat, y, dates) == pytest.approx(0.0)


def test_forecast_round_trip_and_ti_lookup(tmp_path):
    dates = np.repeat(_dates(1), 3)
    forecast = io.Stage3Forecast(
        kind=io.TI,
        family=io.LGBM,
        dates=dates,
        tickers=np.array(["A", "A", "B"]),
        slot=np.array([0, 5, 0], dtype=np.int8),
        yhat=np.array([1.0, -2.0, 3.0], dtype=np.float32),
        yhat_seeds=np.zeros((3, len(io.SEEDS)), dtype=np.float32),
        yhat_configs=None,
        fold=np.array([0, 0, 0]),
        meta={"chosen": [3]},
    )
    back = io.load_forecast(io.save_forecast(tmp_path / "f.npz", forecast))
    assert back.family == io.LGBM and back.meta["chosen"] == [3]
    table = io.ti_lookup(back)
    vector = table[("A", np.datetime64("2020-01-01"))]
    assert vector.shape == (io.TI_SLOTS,)
    assert vector[0] == 1.0 and vector[5] == -2.0 and math.isnan(vector[1])
