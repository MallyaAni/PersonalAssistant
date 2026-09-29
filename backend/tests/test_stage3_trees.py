"""Stage 3, M1: the LightGBM walk-forward.

What has to hold: only test rows get a forecast; a planted signal is found
out of sample; the chosen configuration and the refit rounds are the
plan's rule and are recorded; two runs agree to the bit; nothing at or
after a test block reaches the folds before it, and a block's own labels
and features never reach its model; T-I labels are winsorized at the fit
rows' quantiles only, T-S1 labels not at all; the registered grid runs on
one binned Dataset; the command line writes a forecast the contract reads.
"""

import hashlib
import json
import math
from dataclasses import replace
from functools import cache
from io import StringIO

import numpy as np
import pytest

# LightGBM lives in the research environment; the unit-gate container has
# none, and training a tree model is not what the gate is for.
pytest.importorskip("lightgbm")

from backend.cli import market_stage3_trees as cli  # noqa: E402
from backend.market import stage3_io as io  # noqa: E402
from backend.market import stage3_trees as trees  # noqa: E402

# Two configurations and two seeds keep each walk-forward here to about a
# second; the registered grid and seeds have their own test.
TINY_GRID = (
    {"num_leaves": 7, "learning_rate": 0.1, "min_data_in_leaf": 40},
    {"num_leaves": 3, "learning_rate": 0.2, "min_data_in_leaf": 80},
)
SEEDS = (0, 1)
FEATURES = ("x0", "x1", "x2", "x3")
# Per question: the synthetic dataset's shape and the walk-forward run on
# it. T-S1 gets 4 folds of 100 sessions (gap 26), T-I 3 folds of 50 (gap 6).
CASES = {
    io.S1: {
        "sessions": 700,
        "names": 20,
        "slots": 1,
        "settings": trees.Settings(
            grid=TINY_GRID,
            seeds=SEEDS,
            min_train=300,
            validation=100,
            refit=100,
            max_rounds=150,
            patience=15,
            num_threads=2,
        ),
    },
    io.TI: {
        "sessions": 300,
        "names": 4,
        "slots": 6,
        "settings": trees.Settings(
            grid=TINY_GRID,
            seeds=SEEDS,
            min_train=150,
            validation=50,
            refit=50,
            max_rounds=150,
            patience=15,
            num_threads=2,
        ),
    },
}


# A synthetic question in the export's shape: `sessions` weekdays from
# 2018-06-01, `names` names and `slots` rows a name-session, sorted by
# (date, ticker, slot); four N(0, 1) columns with 3% missing; the label
# `signal` x (x0 + 0.5 x2 [x1 > 0]) plus unit noise. With `holes`, 1% of
# labels and every label of the last 21 sessions (T-S1's unfinished
# horizon) are NaN, so the window is not one contiguous slice.
def _data(kind, sessions, names, slots, signal=1.0, seed=0, holes=False):
    rng = np.random.default_rng(seed)
    days = np.busday_offset(
        np.datetime64("2018-06-01"), np.arange(sessions), roll="forward"
    )
    dates = np.repeat(days, names * slots)
    tickers = np.tile(
        np.repeat(np.array([f"N{i:02d}" for i in range(names)]), slots), sessions
    )
    slot = np.tile(np.arange(slots, dtype=np.int8), sessions * names)
    x = rng.normal(size=(len(dates), len(FEATURES))).astype(np.float32)
    x[rng.random(x.shape) < 0.03] = np.nan
    clean = np.nan_to_num(x.astype(np.float64))
    y = signal * (clean[:, 0] + 0.5 * clean[:, 2] * (clean[:, 1] > 0))
    y = y + rng.normal(size=len(dates))
    if holes:
        y[rng.random(len(y)) < 0.01] = np.nan
        y[dates >= days[-io.S1_LABEL_REACH]] = np.nan
    return io.Stage3Data(
        kind=kind,
        dates=dates,
        tickers=tickers,
        slot=slot,
        x=x,
        feature_names=FEATURES,
        y=y.astype(np.float32),
        meta={"synthetic": True},
    )


# A question's synthetic dataset and the settings it is walked with; the
# T-S1 dataset has label holes, the T-I one none, so both row paths run.
def _case(kind):
    case = CASES[kind]
    data = _data(
        kind, case["sessions"], case["names"], case["slots"], holes=kind == io.S1
    )
    return data, case["settings"]


# One walk-forward per question, shared by the tests that only read it.
@cache
def _baseline(kind):
    data, settings = _case(kind)
    return data, trees.walk_forward(data, settings)


# Each row's session index.
def _index(data):
    return io.session_index(data.dates)[1]


# `n` consecutive calendar days from 2020-01-01, with the unit explicit.
def _days(n):
    return np.datetime64("2020-01-01") + np.arange(n, dtype="timedelta64[D]")


# Fold records without their timings, which differ run to run.
def _untimed(records):
    out = []
    for record in records:
        record = {k: v for k, v in record.items() if k != "seconds"}
        record["configs"] = [
            {k: v for k, v in c.items() if k != "seconds"} for c in record["configs"]
        ]
        out.append(record)
    return out


# Every forecast array of two runs agrees on `rows`, NaN for NaN.
def _same_forecasts(a, b, rows):
    np.testing.assert_array_equal(a.yhat[rows], b.yhat[rows])
    np.testing.assert_array_equal(a.yhat_seeds[rows], b.yhat_seeds[rows])
    np.testing.assert_array_equal(a.yhat_configs[rows], b.yhat_configs[rows])
    np.testing.assert_array_equal(a.fold[rows], b.fold[rows])


# A parameter set is the registered fixed settings, then the configuration,
# the question's bagging fraction, one seed everywhere and the threads.
def test_params_are_the_registered_settings_plus_the_configuration():
    config = io.LGBM_GRID[5]
    params = trees.lgbm_params(io.TI, config, seed=3, num_threads=7)
    for key, value in io.LGBM_FIXED.items():
        assert params[key] == value
    for key, value in config.items():
        assert params[key] == value
    assert params["bagging_fraction"] == 0.3
    assert params["seed"] == params["bagging_seed"] == 3
    assert params["feature_fraction_seed"] == 3
    assert params["num_threads"] == 7
    assert trees.lgbm_params(io.S1, config, 0, 1)["bagging_fraction"] == 0.7
    assert params["deterministic"] is True
    assert params["force_row_wise"] is True


# The choice: highest finite score; ties and NaN to the lowest index; all
# NaN (or missing) to configuration 0.
def test_choice_takes_the_highest_score_ties_and_nan_to_the_lowest_index():
    assert trees.choose_config([0.1, 0.3, 0.2]) == 1
    assert trees.choose_config([math.nan, 0.2, 0.2, 0.1]) == 1
    assert trees.choose_config([math.nan, None, math.nan]) == 0
    assert trees.choose_config([-0.5, math.nan, -0.1]) == 2


# Refit rounds: the best iteration times window rows over fit rows,
# rounded as Python rounds (half to even), never below one.
def test_refit_rounds_scale_the_best_iteration_by_window_over_fit_rows():
    assert trees.refit_rounds(100, 2000, 1000) == 200
    assert trees.refit_rounds(3, 5, 2) == 8  # 7.5 rounds to even
    assert trees.refit_rounds(1, 5, 2) == 2  # 2.5 rounds to even
    assert trees.refit_rounds(1, 1, 10) == 1
    with pytest.raises(ValueError, match="no rows"):
        trees.refit_rounds(5, 10, 0)


# Fold rows are contiguous ranges; the window keeps only labelled rows (a
# slice when every label is known, else positions), the test block every
# row, labelled or not.
def test_fold_rows_are_contiguous_and_count_only_labelled_rows():
    index = np.repeat(np.arange(10), 3)
    fold = io.Fold(test_start=8, test_end=10, window_end=7, fit_end=3, val_start=5)
    finite = np.ones(30, dtype=bool)
    rows = trees.fold_rows(fold, index, finite)
    assert rows.window == slice(0, 21)
    assert rows.n_window == 21
    assert (rows.n_fit, rows.n_validation) == (9, 6)
    assert rows.test == slice(24, 30)
    assert rows.n_test == 6
    finite[[1, 16, 25]] = False
    rows = trees.fold_rows(fold, index, finite)
    assert rows.window.tolist() == [r for r in range(21) if r not in (1, 16)]
    assert (rows.n_fit, rows.n_validation, rows.n_window) == (8, 5, 19)
    assert rows.test == slice(24, 30)
    window_index = index[rows.window]
    assert (window_index[: rows.n_fit] < fold.fit_end).all()
    assert (window_index[-rows.n_validation :] >= fold.val_start).all()


# The vectorized score equals the contract's selection score (ties, NaN,
# T-S1 dates with too few names), so importance and diagnostics measure
# what the selection measures.
@pytest.mark.parametrize("kind", [io.TI, io.S1])
def test_fast_score_is_the_contracts_selection_score(kind):
    rng = np.random.default_rng(5)
    dates = np.repeat(_days(150), 20)
    yhat = np.round(rng.normal(size=len(dates)), 1)
    y = rng.normal(size=len(dates)) + 0.3 * yhat
    yhat[rng.random(len(dates)) < 0.05] = np.nan
    y[rng.random(len(dates)) < 0.05] = np.nan
    y[dates == dates[40]] = np.nan
    y[np.flatnonzero(dates == dates[60])[:17]] = np.nan
    expected = io.selection_score(kind, yhat, y, dates)
    assert trees.fast_score(kind, yhat, y, dates) == pytest.approx(expected, rel=1e-12)
    values = yhat[np.isfinite(yhat)]
    np.testing.assert_array_equal(
        trees.average_ranks(values), io._average_ranks(values)
    )


# Permutation importance finds the one column a model reads: shuffling any
# other column leaves its forecast, and so its score, exactly unchanged; a
# long block is subsampled; the caller's rows are not touched.
def test_permutation_drops_find_the_only_column_a_model_reads():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(5000, 3)).astype(np.float32)
    y = x[:, 1] + 0.5 * rng.normal(size=5000)
    dates = np.repeat(_days(250), 20)
    before = x.copy()

    # A model that reads column 1 only.
    def predict(block):
        return block[:, 1].astype(np.float64)

    baseline, drops, rows = trees.permutation_drops(
        predict, io.TI, x, y, dates, np.random.default_rng(0), max_rows=2000
    )
    assert rows == 2000
    assert baseline > 0.8
    assert drops[1] > 0.7
    assert drops[0] == 0.0
    assert drops[2] == 0.0
    np.testing.assert_array_equal(x, before)
    again = trees.permutation_drops(
        predict, io.TI, x, y, dates, np.random.default_rng(0), max_rows=2000
    )
    np.testing.assert_array_equal(again[1], drops)


# Only test rows carry a forecast: rows before the first test block keep
# NaN and fold -1; every row of a block, labelled or not, is forecast and
# carries its fold; the forecast is the mean of the seeds.
@pytest.mark.parametrize("kind", [io.S1, io.TI])
def test_forecasts_exist_only_for_test_rows(kind):
    data, forecast = _baseline(kind)
    index = _index(data)
    folds = forecast.meta["folds"]
    before = index < folds[0]["sessions"]["test_start"]
    assert before.any()
    assert (forecast.fold[before] == -1).all()
    assert np.isnan(forecast.yhat[before]).all()
    assert np.isnan(forecast.yhat_seeds[before]).all()
    assert np.isnan(forecast.yhat_configs[before]).all()
    for number, record in enumerate(folds):
        s = record["sessions"]
        block = (index >= s["test_start"]) & (index < s["test_end"])
        assert (forecast.fold[block] == number).all()
        assert np.isfinite(forecast.yhat_seeds[block]).all()
        assert np.isfinite(forecast.yhat_configs[block]).all()
        assert record["rows"]["test"] == block.sum()
    assert folds[-1]["sessions"]["test_end"] == index.max() + 1
    np.testing.assert_allclose(forecast.yhat, forecast.yhat_seeds.mean(axis=1))
    unlabelled = ~np.isfinite(data.y) & ~before
    if kind == io.S1:
        assert unlabelled.any()
    assert np.isfinite(forecast.yhat[unlabelled]).all()


# A planted signal is found out of sample, by the plan's own metric.
@pytest.mark.parametrize("kind", [io.S1, io.TI])
def test_a_planted_signal_is_found_out_of_sample(kind):
    data, forecast = _baseline(kind)
    tested = forecast.fold >= 0
    score = io.selection_score(
        kind, forecast.yhat[tested], data.y[tested], data.dates[tested]
    )
    assert score > 0.4
    # The seeds are different models, not one model five times.
    assert not np.array_equal(
        forecast.yhat_seeds[tested, 0], forecast.yhat_seeds[tested, 1]
    )


# Each fold records the plan's choice from its own scores, the refit
# rounds as the best iteration scaled by window over fit rows, refits
# that really ran those rounds, and the row counts of every part.
@pytest.mark.parametrize("kind", [io.S1, io.TI])
def test_the_chosen_configuration_and_the_refit_rounds_are_recorded(kind):
    data, forecast = _baseline(kind)
    index = _index(data)
    finite = np.isfinite(data.y)
    for record in forecast.meta["folds"]:
        configs = record["configs"]
        assert [c["params"] for c in configs] == [dict(c) for c in TINY_GRID]
        chosen = trees.choose_config([c["score"] for c in configs])
        assert record["chosen"] == chosen
        assert record["chosen_params"] == TINY_GRID[chosen]
        assert record["best_iter"] == configs[chosen]["best_iter"] >= 1
        rows = record["rows"]
        expected = max(1, round(record["best_iter"] * rows["window"] / rows["fit"]))
        assert record["refit_rounds"] == expected
        assert record["refit_trees"] == [expected] * len(SEEDS)
        s = record["sessions"]
        assert rows["fit"] == (finite & (index < s["fit_end"])).sum()
        assert rows["window"] == (finite & (index < s["window_end"])).sum()
        validation = finite & (index >= s["val_start"]) & (index < s["window_end"])
        assert rows["validation"] == validation.sum()
        assert all(math.isfinite(c["val_l2"]) for c in configs)
    assert forecast.meta["registered"] is False
    assert forecast.meta["complete"] is True


# The same data on the same threads gives the same forecasts, bit for bit,
# and the same choices and importance.
def test_two_runs_give_identical_forecasts():
    data, settings = _case(io.TI)
    first = trees.walk_forward(data, settings, importance=True)
    second = trees.walk_forward(data, settings, importance=True)
    _same_forecasts(first, second, slice(None))
    assert _untimed(first.meta["folds"]) == _untimed(second.meta["folds"])
    assert first.meta["importance"] == second.meta["importance"]


# No leak forward: replacing the features and labels of every row at or
# after fold k's test block leaves every earlier fold's forecasts and
# choices exactly as they were (and does change fold k's, so the check
# can fail).
@pytest.mark.parametrize("kind", [io.S1, io.TI])
@pytest.mark.parametrize("k", [1, 2])
def test_nothing_at_or_after_a_test_block_reaches_earlier_folds(kind, k):
    data, base = _baseline(kind)
    _, settings = _case(kind)
    index = _index(data)
    start = base.meta["folds"][k]["sessions"]["test_start"]
    later = index >= start
    rng = np.random.default_rng(99)
    x = data.x.copy()
    y = data.y.copy()
    x[later] = rng.normal(size=(later.sum(), x.shape[1])) * 40 + 25
    y[later] = rng.normal(size=later.sum()) * 300
    y[later & (rng.random(len(y)) < 0.1)] = np.nan
    tampered = trees.walk_forward(replace(data, x=x, y=y), settings)
    _same_forecasts(tampered, base, ~later)
    assert _untimed(tampered.meta["folds"][:k]) == _untimed(base.meta["folds"][:k])
    assert not np.array_equal(tampered.yhat[later], base.yhat[later])


# A test block's own rows never reach its model: new labels in fold k's
# block leave folds 0..k unchanged (and change fold k + 1, which trains on
# them), and new features on most of the block's rows leave the forecasts
# of the untouched rows unchanged - the block is never binned. Moving the
# fold's validation features instead does change them.
@pytest.mark.parametrize("kind", [io.S1, io.TI])
def test_a_test_blocks_own_rows_never_reach_its_model(kind):
    data, base = _baseline(kind)
    _, settings = _case(kind)
    index = _index(data)
    k = 1
    s = base.meta["folds"][k]["sessions"]
    block = (index >= s["test_start"]) & (index < s["test_end"])
    through = index < s["test_end"]
    rng = np.random.default_rng(7)
    y = data.y.copy()
    y[block] = -7.0 * y[block] + 3.0
    y[block & (rng.random(len(y)) < 0.2)] = np.nan
    relabelled = trees.walk_forward(replace(data, y=y), settings)
    _same_forecasts(relabelled, base, through)
    assert not np.array_equal(relabelled.yhat[~through], base.yhat[~through])
    kept = block & (data.tickers == data.tickers[0])
    x = data.x.copy()
    x[block & ~kept] = rng.normal(size=((block & ~kept).sum(), x.shape[1])) * 50 + 40
    moved = trees.walk_forward(replace(data, x=x), settings, max_folds=k + 1)
    _same_forecasts(moved, base, kept)
    validation = (index >= s["val_start"]) & (index < s["window_end"])
    x = data.x.copy()
    x[validation] = x[validation] * 3 + 5
    control = trees.walk_forward(replace(data, x=x), settings, max_folds=k + 1)
    assert not np.array_equal(control.yhat[kept], base.yhat[kept])


# An independent re-implementation of the protocol agrees bit for bit:
# rows by boolean masks, the fit and validation Datasets built on the
# window's bin mappers with `reference=` rather than as its subsets, the
# T-I bounds, the raw-label scores, the choice and the refit recomputed
# here. The labels are heavy-tailed, so T-I clipping changes the labels
# trained on and a score read from clipped labels would not match.
@pytest.mark.parametrize("kind", [io.S1, io.TI])
def test_an_independent_reimplementation_agrees_bit_for_bit(kind):
    lgb = pytest.importorskip("lightgbm")
    data, settings = _case(kind)
    tails = np.random.default_rng(3).random(len(data.y)) < 0.01
    data = replace(data, y=np.where(tails, 25 * data.y, data.y).astype(np.float32))
    forecast = trees.walk_forward(data, settings, max_folds=2)
    index = _index(data)
    finite = np.isfinite(data.y)
    raw = data.y.astype(np.float64)
    threads = settings.num_threads
    for record in forecast.meta["folds"]:
        s = record["sessions"]
        window = finite & (index < s["window_end"])
        fit = finite & (index < s["fit_end"])
        validation = finite & (index >= s["val_start"]) & (index < s["window_end"])
        test = (index >= s["test_start"]) & (index < s["test_end"])
        label = raw
        if kind == io.TI:
            label = np.clip(raw, *np.quantile(raw[fit], io.WINSOR))
        params = {**trees.DATASET_PARAMS, "num_threads": threads}
        bins = lgb.Dataset(
            data.x[window], label=label[window], params=params, free_raw_data=False
        ).construct()
        fit_set = lgb.Dataset(
            data.x[fit], label=label[fit], reference=bins, params=params
        )
        val_set = lgb.Dataset(
            data.x[validation], label=label[validation], reference=bins, params=params
        )
        scores, bests = [], []
        for c, config in enumerate(settings.grid):
            booster = lgb.train(
                trees.lgbm_params(kind, config, 0, threads),
                fit_set,
                num_boost_round=settings.max_rounds,
                valid_sets=[val_set],
                callbacks=[lgb.early_stopping(settings.patience, verbose=False)],
            )
            bests.append(booster.best_iteration)
            fitted = booster.predict(
                data.x[validation], num_iteration=bests[-1], num_threads=threads
            )
            scores.append(
                io.selection_score(
                    kind, fitted, raw[validation], data.dates[validation]
                )
            )
            np.testing.assert_array_equal(
                forecast.yhat_configs[test, c],
                booster.predict(
                    data.x[test], num_iteration=bests[-1], num_threads=threads
                ),
            )
        assert [c["best_iter"] for c in record["configs"]] == bests
        assert [c["score"] for c in record["configs"]] == scores
        chosen = int(np.argmax(np.nan_to_num(scores, nan=-np.inf)))
        assert record["chosen"] == chosen
        rounds = max(1, round(bests[chosen] * window.sum() / fit.sum()))
        for i, seed in enumerate(settings.seeds):
            booster = lgb.train(
                trees.lgbm_params(kind, settings.grid[chosen], seed, threads),
                bins,
                num_boost_round=rounds,
            )
            np.testing.assert_array_equal(
                forecast.yhat_seeds[test, i],
                booster.predict(data.x[test], num_threads=threads),
            )


# T-I winsorization bounds are the fit rows' quantiles: exactly those of
# the fit labels, unmoved by huge labels in the gap or the validation
# block, and moved by huge labels in the fit part.
def test_ti_winsor_bounds_come_from_the_fit_rows_only():
    data, settings = _case(io.TI)
    base = trees.walk_forward(data, settings, max_folds=1)
    record = base.meta["folds"][0]
    s = record["sessions"]
    index = _index(data)
    fit = index < s["fit_end"]
    expected = np.quantile(data.y[fit].astype(np.float64), io.WINSOR)
    assert record["winsor"] == [float(v) for v in expected]
    after_fit = np.flatnonzero((index >= s["fit_end"]) & (index < s["window_end"]))
    y = data.y.copy()
    y[after_fit[::20]] = 1e6
    outside = trees.walk_forward(replace(data, y=y), settings, max_folds=1)
    assert outside.meta["folds"][0]["winsor"] == record["winsor"]
    y = data.y.copy()
    y[np.flatnonzero(fit)[::20]] = 1e6
    inside = trees.walk_forward(replace(data, y=y), settings, max_folds=1)
    assert inside.meta["folds"][0]["winsor"][1] > record["winsor"][1] * 100


# T-I trains on labels clipped at the fit bounds, so a few huge fit labels
# cannot drag its forecasts; T-S1 takes its labels as they are, and the
# same labels drag its forecasts far.
def test_ti_trains_on_clipped_labels_and_s1_on_raw_ones():
    results = {}
    for kind in (io.TI, io.S1):
        data, settings = _case(kind)
        index = _index(data)
        fit_end = trees.walk_forward(data, settings, max_folds=1).meta["folds"][0][
            "sessions"
        ]["fit_end"]
        fit_rows = np.flatnonzero((index < fit_end) & np.isfinite(data.y))
        y = data.y.copy()
        y[fit_rows[::500]] = 1e6
        forecast = trees.walk_forward(replace(data, y=y), settings, max_folds=1)
        results[kind] = (forecast.meta["folds"][0]["winsor"], forecast)
    bounds, forecast = results[io.TI]
    assert bounds[1] < 10
    assert np.abs(forecast.yhat[forecast.fold == 0]).max() < 20
    bounds, forecast = results[io.S1]
    assert bounds is None
    assert np.abs(forecast.yhat[forecast.fold == 0]).max() > 1000


# --max-folds stops after the first folds, forecasts them exactly as the
# full run does, and says the run is partial.
def test_max_folds_stops_early_and_says_so():
    data, base = _baseline(io.S1)
    _, settings = _case(io.S1)
    forecast = trees.walk_forward(data, settings, max_folds=2)
    assert forecast.meta["folds_run"] == 2
    assert forecast.meta["folds_total"] == 4
    assert forecast.meta["complete"] is False
    assert sorted(set(forecast.fold.tolist())) == [-1, 0, 1]
    _same_forecasts(forecast, base, base.fold <= 1)
    with pytest.raises(ValueError, match="at least 1"):
        trees.walk_forward(data, settings, max_folds=0)


# The registered grid and seeds run on one binned Dataset: all eight
# configurations (min_data_in_leaf 200 and 1000 on the same bins), NaN
# scores where a configuration cannot split, the choice among the rest.
# Settings know whether they are the registered ones, threads aside.
def test_the_registered_grid_and_seeds_share_one_binned_dataset():
    data = _data(io.S1, sessions=440, names=8, slots=1)
    settings = trees.Settings(
        min_train=300,
        validation=100,
        refit=100,
        max_rounds=60,
        patience=10,
        num_threads=2,
    )
    forecast = trees.walk_forward(data, settings, max_folds=1)
    record = forecast.meta["folds"][0]
    assert [c["params"] for c in record["configs"]] == [dict(c) for c in io.LGBM_GRID]
    assert forecast.yhat_configs.shape[1] == 8
    assert forecast.yhat_seeds.shape[1] == 5
    for config in record["configs"]:
        if config["params"]["min_data_in_leaf"] == 1000:
            assert config["score"] is None  # 1,184 fit rows: no split is possible
    assert record["chosen_params"]["min_data_in_leaf"] == 200
    assert record["refit_trees"] == [record["refit_rounds"]] * 5
    assert forecast.meta["registered"] is False
    assert trees.Settings().registered(io.TI)
    assert trees.Settings().registered(io.S1)
    assert trees.Settings(num_threads=3).registered(io.S1)
    assert not trees.Settings(seeds=(0,)).registered(io.S1)
    assert not trees.Settings(refit=64).registered(io.S1)


# The permutation importance ranks the planted column first, keeps every
# fold's drops, and for T-I scores at most IMPORTANCE_ROWS rows.
def test_importance_ranks_the_planted_column_first(monkeypatch):
    data, settings = _case(io.S1)
    forecast = trees.walk_forward(data, settings, importance=True, max_folds=2)
    ranking = forecast.meta["importance"]
    assert [r["rank"] for r in ranking] == [1, 2, 3, 4]
    assert ranking[0]["feature"] == "x0"
    assert ranking[0]["drop"] > 0.2
    assert ranking[0]["folds"] == 2
    noise = next(r for r in ranking if r["feature"] == "x3")
    assert abs(noise["drop"]) < 0.05
    for record in forecast.meta["folds"]:
        assert len(record["importance"]["drops"]) == len(FEATURES)
    monkeypatch.setattr(trees, "IMPORTANCE_ROWS", 500)
    data, settings = _case(io.TI)
    forecast = trees.walk_forward(data, settings, importance=True, max_folds=1)
    assert forecast.meta["folds"][0]["importance"]["rows"] == 500


# Diagnostics: the out-of-sample score for every calendar year of test
# rows and on each window, per seed and per configuration, and every
# column's univariate IC on 2016-2019 and 2020-2023; plain JSON.
def test_diagnostics_report_oos_years_and_univariate_ic():
    data, forecast = _baseline(io.S1)
    report = trees.diagnostics(data, forecast)
    json.dumps(report, allow_nan=False)
    tested = forecast.fold >= 0
    years = data.dates[tested].astype("datetime64[Y]").astype(int) + 1970
    assert set(report["oos"]["by_year"]) == {str(y) for y in np.unique(years)}
    assert all(v["score"] > 0.4 for v in report["oos"]["by_year"].values())
    choosing = report["oos"]["windows"]["choosing"]
    assert choosing["ensemble"]["score"] > 0.4
    assert len(choosing["seeds"]) == 2
    assert len(choosing["configs"]) == 2
    assert report["oos"]["windows"]["later"]["ensemble"]["pairs"] == 0
    columns = {c["feature"]: c for c in report["univariate_ic"]["columns"]}
    assert columns["x0"]["2016-2019"] > 0.4
    assert columns["x0"]["2020-2023"] > 0.4
    assert abs(columns["x3"]["2016-2019"]) < 0.05
    data, forecast = _baseline(io.TI)
    report = trees.diagnostics(data, forecast)
    assert report["univariate_ic"]["windows"]["2020-2023"]["rows"] == 0
    assert report["univariate_ic"]["columns"][0]["2020-2023"] is None
    with pytest.raises(ValueError, match="not the dataset"):
        trees.diagnostics(_baseline(io.S1)[0], forecast)


# The command line, on the registered protocol: reads a dataset file,
# prints a line per fold, writes a forecast the contract reads back with
# the file's hash, the importance and the diagnostics.
def test_the_cli_writes_a_forecast_the_contract_reads_back(tmp_path):
    data = _data(io.S1, sessions=530, names=8, slots=1, signal=0.0)
    path = io.save_data(tmp_path / "s1.npz", data)
    out = StringIO()
    args = cli.build_parser().parse_args(
        [
            "--data",
            str(path),
            "--out",
            str(tmp_path / "forecast.npz"),
            "--threads",
            "2",
            "--max-folds",
            "1",
            "--importance",
            "--diagnostics",
            str(tmp_path / "diagnostics.json"),
        ]
    )
    assert cli.run(args, out=out) == 0
    text = out.getvalue()
    assert "fold 0 of 1: test" in text
    assert "; registered settings" in text
    assert "NOT the registered" not in text
    forecast = io.load_forecast(tmp_path / "forecast.npz")
    assert forecast.family == io.LGBM
    assert forecast.kind == io.S1
    assert forecast.meta["registered"] is True
    assert forecast.meta["complete"] is True
    assert forecast.meta["num_threads"] == 2
    assert (
        forecast.meta["dataset_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert forecast.meta["dataset_meta"]["synthetic"] is True
    assert len(forecast.meta["importance"]) == len(FEATURES)
    assert forecast.yhat_seeds.shape == (len(data), 5)
    assert forecast.yhat_configs.shape == (len(data), 8)
    np.testing.assert_array_equal(forecast.dates, data.dates)
    report = json.loads((tmp_path / "diagnostics.json").read_text(encoding="utf-8"))
    assert set(report) == {"kind", "family", "oos", "univariate_ic"}
