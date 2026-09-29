"""Stage 4's M1 on the timing target, walked forward with LightGBM.

What has to hold (docs/research/stage4-plan-2026-09-29.md, "Models"; the
helpers come from test_stage4_models.py):

- Every model M1 trains (each configuration's fit-part model and each
  seed's refit, in every fold) trains at bagging fraction 0.7.
- Apart from that fraction, M1 is stage 3's T-I walk-forward on the rows'
  ``ti`` view: at stage 3's 0.3 it reproduces `stage3_trees.walk_forward`
  bit for bit, so the label is winsorized at the fit rows' quantiles and
  the configuration is chosen by pooled Spearman exactly as stage 3 does.
- Test blocks of 63 sessions with a gap of 11 at both boundaries; only test
  rows are forecast (NaN-labelled ones too), as the mean of the seeds, in bp.
- An unlabelled row never trains anything.
- Two runs agree to the bit.
- The command writes a forecast keyed by the export's rows with the side,
  the family, the protocol and the inputs' hashes; the registered protocol
  says so, and a smoke run says it is not.
"""

from __future__ import annotations

import dataclasses
import io as textio
from functools import cache

import numpy as np
import pytest

# LightGBM lives in the research environment; the unit-gate container has none.
lightgbm = pytest.importorskip("lightgbm")

from backend.cli import market_stage4_models as cli  # noqa: E402
from backend.market import stage3_io as io  # noqa: E402
from backend.market import stage3_trees as trees  # noqa: E402
from backend.market import stage4_models as models  # noqa: E402
from backend.tests.test_stage4_models import (  # noqa: E402
    NAMES,
    _export,
    _files,
    _sha256,
    _timing,
)

TINY = (
    {"num_leaves": 7, "learning_rate": 0.1, "min_data_in_leaf": 40},
    {"num_leaves": 3, "learning_rate": 0.2, "min_data_in_leaf": 80},
)
# Three folds of the stage-4 cadence (63 sessions, gap 11) on 300 sessions:
# the first test block at session 150, validation blocks of 50 sessions.
SESSIONS = 300
SETTINGS = trees.Settings(
    grid=TINY,
    seeds=(0, 1),
    min_train=150,
    validation=50,
    max_rounds=150,
    patience=15,
    num_threads=2,
)
ARRAYS = ("yhat", "yhat_seeds", "yhat_configs", "fold")


# The buy side's dataset and its M1 forecast, shared by the tests that only
# read them.
@cache
def _baseline():
    data = _timing(_export(SESSIONS))
    return data, models.run_lgbm(data, SETTINGS)


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


# Every model M1 trains - each configuration's fit-part model and each
# seed's refit, in every fold - trains at bagging fraction 0.7, and the
# forecast's meta says so.
def test_every_m1_model_trains_at_bagging_0_7(monkeypatch):
    data = _timing(_export(SESSIONS))
    seen = []
    real = lightgbm.train

    # Record each training call's parameters, then train as lightgbm does.
    def spy(params, *args, **kwargs):
        seen.append(dict(params))
        return real(params, *args, **kwargs)

    monkeypatch.setattr(lightgbm, "train", spy)
    forecast = models.run_lgbm(data, SETTINGS)
    assert len(forecast.meta["folds"]) == 3
    assert len(seen) == 3 * (len(TINY) + len(SETTINGS.seeds))
    assert {p["bagging_fraction"] for p in seen} == {0.7}
    assert {p["bagging_freq"] for p in seen} == {1}
    assert sorted({p["seed"] for p in seen}) == [0, 1]
    assert forecast.meta["bagging_fraction"] == 0.7
    assert forecast.meta["settings"]["bagging_fraction"] == 0.7


# Apart from the bagging fraction, M1 is stage 3's T-I walk-forward on the
# rows' ``ti`` view: at stage 3's 0.3 it gives stage3_trees.walk_forward's
# forecasts, choices and refits bit for bit; at the plan's 0.7 they move.
def test_m1_is_stage3s_ti_walk_forward_but_for_the_bagging_fraction():
    data, planned = _baseline()
    at_stage3 = models.run_lgbm(data, SETTINGS, bagging=0.3)
    stage3 = trees.walk_forward(models.tree_data(data), models.lgbm_settings(SETTINGS))
    for name in ARRAYS:
        np.testing.assert_array_equal(getattr(at_stage3, name), getattr(stage3, name))
    assert _untimed(at_stage3.meta["folds"]) == _untimed(stage3.meta["folds"])
    assert stage3.meta["winsor_quantiles"] == list(io.WINSOR)
    assert not np.array_equal(planned.yhat_seeds, at_stage3.yhat_seeds, equal_nan=True)


# The plan's walk-forward: test blocks of 63 sessions, the window ending 11
# sessions before its block and the fit part 11 before the validation
# block. Only test rows are forecast (NaN-labelled ones too), as the mean of
# the seeds, in bp; each fold counts only labelled rows and winsorizes at
# the fit rows' 0.5%/99.5% quantiles of the raw label.
def test_m1_walks_the_plans_folds_and_forecasts_test_rows_in_bp():
    data, forecast = _baseline()
    _, index = io.session_index(data.dates)
    finite = np.isfinite(data.y)
    y = data.y.astype(np.float64)
    folds = forecast.meta["folds"]
    assert [
        (f["sessions"]["test_start"], f["sessions"]["test_end"]) for f in folds
    ] == [
        (150, 213),
        (213, 276),
        (276, 300),
    ]
    for number, record in enumerate(folds):
        s = record["sessions"]
        assert s["window_end"] == s["test_start"] - 11
        assert s["val_start"] == s["window_end"] - 50
        assert s["fit_end"] == s["val_start"] - 11
        block = (index >= s["test_start"]) & (index < s["test_end"])
        assert (forecast.fold[block] == number).all()
        assert np.isfinite(forecast.yhat_seeds[block]).all()
        fit = finite & (index < s["fit_end"])
        validation = finite & (index >= s["val_start"]) & (index < s["window_end"])
        assert record["rows"]["fit"] == fit.sum()
        assert record["rows"]["validation"] == validation.sum()
        assert record["rows"]["window"] == (finite & (index < s["window_end"])).sum()
        assert record["winsor"] == [float(v) for v in np.quantile(y[fit], io.WINSOR)]
    before = index < 150
    assert np.isnan(forecast.yhat[before]).all()
    assert (forecast.fold[before] == -1).all()
    unlabelled = ~finite & ~before
    assert unlabelled.sum() > 5
    assert np.isfinite(forecast.yhat[unlabelled]).all()
    np.testing.assert_allclose(forecast.yhat, forecast.yhat_seeds.mean(axis=1))
    tested = ~before & finite
    assert io.spearman(forecast.yhat[tested], y[tested]) > 0.3
    assert 30 < forecast.yhat[tested].std() < 300  # bp: the label's signal has sd 150
    meta = forecast.meta
    assert (meta["side"], meta["target"], meta["units"]) == ("buy", "g_buy", "bp")
    assert meta["family"] == io.LGBM
    assert forecast.kind == io.S1
    assert (meta["settings"]["refit"], meta["settings"]["gap"]) == (63, 11)
    assert meta["registered"] is False
    assert meta["complete"] is True
    assert meta["feature_names"] == ["d_signal", "d_noise", "d_grade_a"]
    np.testing.assert_array_equal(forecast.dates, data.dates)
    np.testing.assert_array_equal(forecast.tickers, data.tickers)


# An unlabelled row never trains anything: new columns on every unlabelled
# row leave every other row's forecast and every fold's choices exactly as
# they were, while a tested unlabelled row's own forecast moves.
def test_an_unlabelled_row_never_trains_m1():
    data, base = _baseline()
    unlabelled = ~np.isfinite(data.y)
    rng = np.random.default_rng(3)
    x = data.x.copy()
    x[unlabelled] = rng.normal(size=(int(unlabelled.sum()), x.shape[1])) * 30 + 10
    moved = models.run_lgbm(dataclasses.replace(data, x=x), SETTINGS)
    for name in ARRAYS:
        np.testing.assert_array_equal(
            getattr(moved, name)[~unlabelled], getattr(base, name)[~unlabelled]
        )
    assert _untimed(moved.meta["folds"]) == _untimed(base.meta["folds"])
    tested = unlabelled & (base.fold >= 0)
    assert not np.array_equal(moved.yhat[tested], base.yhat[tested])


# The same data on the same threads gives the same forecast, to the bit.
def test_m1_repeats_exactly():
    data, base = _baseline()
    again = models.run_lgbm(data, SETTINGS)
    for name in ARRAYS:
        np.testing.assert_array_equal(getattr(again, name), getattr(base, name))
    assert _untimed(again.meta["folds"]) == _untimed(base.meta["folds"])


# The command on the registered protocol (one fold, at session 500 of 520):
# a forecast keyed by the export's rows, on the sell label, with the plan's
# protocol, the inputs' hashes, one printed line per fold, and registered.
def test_the_command_writes_the_registered_m1_forecast(tmp_path):
    data, s1, labels = _files(tmp_path, 520, names=NAMES[:3])
    out = tmp_path / "forecast.npz"
    argv = [
        "--family",
        "lgbm",
        "--side",
        "sell",
        "--s1",
        str(s1),
        "--labels",
        str(labels),
        "--out",
        str(out),
        "--threads",
        "2",
    ]
    text = textio.StringIO()
    assert cli.main(argv, out=text) == 0
    printed = text.getvalue()
    assert "fold 0 of 1: test" in printed
    assert "; registered settings" in printed
    assert "NOT the registered settings" not in printed
    assert "NOT the registered export" in printed  # a synthetic export
    forecast = io.load_forecast(out)
    assert forecast.family == io.LGBM
    assert forecast.kind == io.S1
    np.testing.assert_array_equal(forecast.dates, data.dates)
    np.testing.assert_array_equal(forecast.tickers, data.tickers)
    meta = forecast.meta
    assert meta["registered"] is True
    assert meta["complete"] is True
    assert (meta["side"], meta["target"]) == ("sell", "g_sell")
    assert meta["labels_sha256"] == _sha256(labels)
    assert meta["s1_sha256"] == _sha256(s1)
    assert meta["export_registered"] is False
    assert meta["stage4_plan"] == models.PLAN
    assert meta["settings"] == models.lgbm_protocol()
    assert meta["num_threads"] == 2
    assert [f["path"] for f in meta["input_files"]] == [str(s1), str(labels)]
    assert meta["command"] == argv
    assert forecast.yhat_seeds.shape == (len(data), 5)
    assert forecast.yhat_configs.shape == (len(data), 8)
    _, index = io.session_index(data.dates)
    assert np.isnan(forecast.yhat[index < 500]).all()
    assert np.isfinite(forecast.yhat[index >= 500]).all()


# A smoke run (two configurations, two seeds, one fold, a smaller
# walk-forward) says it is not the registered protocol and records the cut.
def test_a_smoke_m1_run_is_marked_unregistered(tmp_path):
    _, s1, labels = _files(tmp_path, 200)
    out = tmp_path / "smoke.npz"
    argv = [
        "--family",
        "lgbm",
        "--side",
        "buy",
        "--s1",
        str(s1),
        "--labels",
        str(labels),
        "--out",
        str(out),
        "--threads",
        "2",
        "--grid-first",
        "2",
        "--seeds",
        "0,1",
        "--max-folds",
        "1",
        "--min-train",
        "120",
        "--validation",
        "40",
        "--max-rounds",
        "100",
        "--patience",
        "10",
    ]
    text = textio.StringIO()
    assert cli.main(argv, out=text) == 0
    assert "NOT the registered settings" in text.getvalue()
    meta = io.load_forecast(out).meta
    assert meta["registered"] is False
    assert meta["complete"] is False
    settings = meta["settings"]
    assert settings["grid"] == [dict(c) for c in io.LGBM_GRID[:2]]
    assert settings["seeds"] == [0, 1]
    assert settings["max_folds"] == 1
    assert (settings["refit"], settings["gap"], settings["bagging_fraction"]) == (
        63,
        11,
        0.7,
    )
