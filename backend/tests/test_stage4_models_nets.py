"""Stage 4's M2 (the JKX I20 CNN) and M3 (the sequence model) on the timing target.

Everything runs on the CPU with tiny synthetic data (the helpers come from
test_stage4_models.py), through the code the registered run uses. What has
to hold (docs/research/stage4-plan-2026-09-29.md, "Models"):

- M2 is stage 3's I20 network with one regression output; its loss is MSE
  on the label winsorized at the fit rows' 0.5%/99.5% quantiles and divided
  by their standard deviation; its forecasts are that output times the
  standard deviation, in bp.
- M3 is stage 3's T-S1 network and windows with T-I's target scaling
  (stage 3 would train a T-S1 label as it is), forecasts back in bp.
- Both choose by pooled Spearman on the validation block, walk forward with
  test blocks of 252 sessions and a gap of 11 at both boundaries, forecast
  only test rows (NaN-labelled ones too) and repeat to the bit.
- An unlabelled row never trains anything; a row without an input gets no
  forecast and is counted.
- The fold loop is stage 3's own: given stage 3's score it reproduces
  `stage3_nn.run_seq` bit for bit.
- The command writes both families' forecasts with the side, the protocol
  and the inputs' hashes.
"""

from __future__ import annotations

import dataclasses
import io as textio

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from backend.cli import market_stage4_models as cli  # noqa: E402
from backend.market import stage3_io as io  # noqa: E402
from backend.market import stage3_nn as nn3  # noqa: E402
from backend.market import stage4_models as models  # noqa: E402
from backend.tests.test_stage4_models import (  # noqa: E402
    NAMES,
    _days,
    _export,
    _labels,
    _sha256,
    _timing,
    _write_labels,
)

CHANNELS = len(io.SEQ_CHANNELS)
STEPS = io.STEPS_PER_SESSION
TWO = (
    {"lr": 3e-3, "dropout": 0.0, "width": 8},
    {"lr": 1e-3, "dropout": 0.1, "width": 8},
)
# The sequence case's sessions.
SESSIONS = 70
ARRAYS = ("yhat", "yhat_seeds", "fold")


# A random sequence tensor, as stage 3's tests build one: N(0, 1) channels
# in float16, the gap-step flag on each session's gap step.
def _tensor(names, sessions, seed=0):
    rng = np.random.default_rng(seed)
    shape = (len(names), len(sessions), STEPS, CHANNELS)
    seq = rng.normal(size=shape).astype(np.float16)
    seq[..., -1] = 0
    seq[:, :, 0, -1] = 1
    return io.SeqTensor(
        np.asarray(names), np.asarray(sessions), seq, np.ones(shape[:2], dtype=bool)
    )


# Random-walk daily bars for the names over `dates`, as stage 3's tests draw them.
def _bars(dates, names, seed=3):
    rng = np.random.default_rng(seed)
    shape = (len(dates), len(names))
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=shape), axis=0))
    open_ = close * np.exp(rng.normal(0, 0.01, size=shape))
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.01, size=shape)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.01, size=shape)))
    volume = rng.uniform(0.8, 1.2, size=shape) * 1e6
    return io.DailyOHLCV(
        np.asarray(names), np.asarray(dates), open_, high, low, close, volume
    )


# The chart case: 60 export sessions of four names whose bars start 30
# sessions earlier, so every row has its 20-day image.
def _chart_case(side="buy"):
    bar_dates = _days(90, start="2018-11-01")
    data = _timing(_export(60, names=NAMES[:4], start=str(bar_dates[30])), side)
    return data, _bars(bar_dates, NAMES[:4])


# Small CPU settings with the stage-4 cadence and gap: one seed, two epochs,
# a first test block at 40 and a 10-session validation block.
def _settings(**overrides):
    base = {
        "seeds": (0,),
        "max_epochs": 2,
        "patience": 2,
        "batch": 32,
        "device": "cpu",
        "min_train": 40,
        "validation": 10,
    }
    return nn3.Settings(**{**base, **overrides})


# The one fold the small settings walk over `n` sessions, with the stage-4
# gap of 11 at both boundaries: fit [0, 8), validation [19, 29), test [40, n).
def _fold_sessions(n):
    return {"fit": [0, 8], "validation": [19, 29], "test": [40, n]}


# The fold the small settings walk, and its fit and validation units.
def _first_fold(task, data, settings):
    sessions, index = io.session_index(data.dates)
    fold = models.folds_for(
        task.family,
        len(sessions),
        min_train=settings.min_train,
        validation=settings.validation,
    )[0]
    fit, val, test = nn3._split(task, index[task.units.first], fold)
    return fold, sessions, fit, val, test


# The expected training targets: the labels winsorized at the fit units'
# quantiles and divided by the std of those winsorized labels.
def _scaled(y, fit):
    fit_labels = y[fit][np.isfinite(y[fit])]
    low, high = np.quantile(fit_labels, io.WINSOR)
    scale = np.clip(fit_labels, low, high).std()
    return np.clip(y, low, high) / scale, scale, (low, high)


# Fold records without their timings, which differ run to run.
def _untimed(value):
    if isinstance(value, dict):
        return {
            k: _untimed(v)
            for k, v in value.items()
            if k not in ("seconds", "seconds_per_epoch")
        }
    if isinstance(value, list):
        return [_untimed(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# M2: the chart CNN
# ---------------------------------------------------------------------------


# M2's network is stage 3's I20 network with one output: the same blocks,
# the fully connected layer Linear(46,080 -> 1) with a zero bias, and one
# fewer output's parameters than stage 3's two-class head.
def test_m2_is_stage3s_i20_network_with_one_regression_output():
    torch.manual_seed(0)
    model = models.JKXRegressor(io.CNN_I20).eval()
    stage3 = nn3.JKXNet(io.CNN_I20)
    head = model.classify[-1]
    assert isinstance(head, torch.nn.Linear)
    assert (head.in_features, head.out_features) == (46_080, 1)
    assert float(head.bias.detach().abs().sum()) == 0.0
    bound = (6.0 / (46_080 + 1)) ** 0.5  # Xavier-uniform
    assert float(head.weight.detach().abs().max()) <= bound
    assert nn3.parameter_count(model) == nn3.parameter_count(stage3) - 46_081 == 662_785
    shapes = [tuple(p.shape) for p in model.features.parameters()]
    assert shapes == [tuple(p.shape) for p in stage3.features.parameters()]
    assert model.classify[1].p == 0.5
    with torch.no_grad():
        assert tuple(model(torch.zeros(2, 1, 64, 60)).shape) == (2, 1)


# M2's target and loss: the fold's targets are the labels winsorized at the
# fit units' quantiles over their std; the loss is the squared error summed
# over the finite targets with their count; a forecast is the output times
# the std, in bp. The images are stage 3's I20 images.
def test_m2_trains_mse_on_the_standardized_winsorized_label_and_forecasts_bp():
    data, bars = _chart_case()
    settings = _settings()
    task = models.TimingChartTask(data, bars, settings)
    assert task.family == io.CNN_I20
    assert task.kind == io.S1
    assert task.usable.all()
    assert task.counts["images"] == len(data)
    np.testing.assert_array_equal(task.labelled, np.isfinite(data.y))
    images, has, _ = nn3.chart_images(bars, data.dates, data.tickers, io.CNN_I20)
    np.testing.assert_array_equal(task.images, images)
    fold, sessions, fit, val, _ = _first_fold(task, data, settings)
    y = data.y.astype(np.float64)
    expected, scale, bounds = _scaled(y, fit)
    state = task.prepare(fold, sessions, fit, "cpu")
    assert state.y_scale == pytest.approx(scale, rel=1e-12)
    assert state.record["winsor_bp"] == pytest.approx(list(bounds), rel=1e-12)
    np.testing.assert_allclose(state.targets[:, 0], expected, rtol=1e-6, equal_nan=True)
    idx = np.r_[fit[:3], val[:3], np.flatnonzero(~task.labelled)[:2]]
    (pixels,), targets = task.batch(state, idx, "cpu")
    assert tuple(pixels.shape) == (len(idx), 1, 64, 60)
    np.testing.assert_array_equal(pixels.numpy()[:, 0] * nn3.PIXEL, images[idx])
    np.testing.assert_array_equal(targets.numpy(), state.targets[idx])
    raw = torch.linspace(-1.0, 1.0, len(idx))[:, None]
    total, count = task.loss(raw, targets)
    finite = np.isfinite(state.targets[idx, 0])
    assert int(count) == finite.sum() == len(idx) - 2
    error = raw.numpy()[finite, 0] - state.targets[idx, 0][finite]
    assert float(total) == pytest.approx(
        float((error.astype(np.float64) ** 2).sum()), rel=1e-5
    )
    torch.manual_seed(1)
    model = task.build({"lr": 1e-5}).eval()
    predicted = nn3._predict(task, state, model, idx, 4, "cpu")
    with torch.no_grad():
        direct = model(pixels).numpy() * state.y_scale
    np.testing.assert_allclose(predicted, direct, rtol=1e-5)
    assert task.architecture()["head"] == "Flatten, Dropout 0.5, Linear(flattened -> 1)"


# M2 walked forward: test rows only, gap 11 at both boundaries and one
# fold of 252 sessions, every labelled fit and validation row trained on
# and every test row forecast (NaN-labelled ones too), the seeds averaged,
# no configuration columns, and a second run the same to the bit.
def test_m2_walks_forward_and_repeats_exactly():
    data, bars = _chart_case("sell")
    settings = _settings(seeds=(0, 1), max_epochs=1)
    first = models.run_cnn(data, bars, settings)
    second = models.run_cnn(data, bars, settings)
    for name in ARRAYS:
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
    _, index = io.session_index(data.dates)
    test = index >= 40
    assert np.isfinite(first.yhat[test]).all()
    assert np.isnan(first.yhat[~test]).all()
    assert (first.fold[test] == 0).all()
    assert (first.fold[~test] == -1).all()
    np.testing.assert_allclose(first.yhat, first.yhat_seeds.mean(axis=1), rtol=1e-6)
    assert first.yhat_configs is None
    meta = first.meta
    record = meta["folds"][0]
    assert record["sessions"] == _fold_sessions(len(np.unique(data.dates)))
    labelled = np.isfinite(data.y)
    assert record["units"]["fit"] == (labelled & (index < 8)).sum()
    assert (
        record["units"]["validation"] == (labelled & (index >= 19) & (index < 29)).sum()
    )
    assert record["units"]["test"] == test.sum()
    assert (~labelled & test).sum() > 0
    assert (
        record["scaling"]["y_scale"] > 50
    )  # bp: the label's scale, not a unit variance
    assert [s["seed"] for s in record["seeds"]] == [0, 1]
    assert (meta["model"], meta["family"], meta["kind"]) == ("M2", io.CNN_I20, io.S1)
    assert (meta["side"], meta["target"], meta["units"]) == ("sell", "g_sell", "bp")
    assert meta["registered"] is False
    assert (meta["settings"]["refit"], meta["settings"]["gap"]) == (252, 11)
    assert meta["settings"]["grid"] == [{"lr": 1e-5}]
    assert meta["settings"]["metric"] == "pooled_spearman"
    assert meta["architecture"]["flattened"] == 46_080


# ---------------------------------------------------------------------------
# M3: the sequence model
# ---------------------------------------------------------------------------


# M3's task is stage 3's T-S1 task (one unit per row, sixty-session
# windows, the attention-pooling network, the same channel and daily
# scaling) with T-I's target scaling, where stage 3 would train the label
# as it is; a forecast is the output times the std, in bp.
def test_m3_is_stage3s_s1_network_with_ti_target_scaling_in_bp():
    data = _timing(_export(SESSIONS))
    tensor = _tensor(NAMES, _days(SESSIONS))
    settings = _settings(grid=TWO)
    task = models.TimingSeqTask(data, tensor, settings)
    stage3 = nn3._SeqTask(data, tensor, settings)
    assert task.kind == io.S1
    assert task.window == 60
    np.testing.assert_array_equal(task.units.rows[:, 0], np.arange(len(data)))
    np.testing.assert_array_equal(task.units.targets[:, 0], data.y.astype(np.float64))
    model = task.build(TWO[0])
    assert isinstance(model, nn3.SeqNet)
    assert model.kind == io.S1
    assert tuple(model.session_position.weight.shape) == (60, 8)
    assert tuple(model.query.shape) == (8,)
    fold, sessions, fit, val, _ = _first_fold(task, data, settings)
    state = task.prepare(fold, sessions, fit, "cpu")
    theirs = stage3.prepare(fold, sessions, fit, "cpu")
    np.testing.assert_array_equal(state.median.numpy(), theirs.median.numpy())
    np.testing.assert_array_equal(state.scale.numpy(), theirs.scale.numpy())
    np.testing.assert_array_equal(state.daily, theirs.daily)
    assert theirs.y_scale == 1.0  # stage 3 takes a T-S1 label as it is
    y = data.y.astype(np.float64)
    expected, scale, bounds = _scaled(y, fit)
    assert state.y_scale == pytest.approx(scale, rel=1e-12)
    assert state.record["winsor_bp"] == pytest.approx(list(bounds), rel=1e-12)
    np.testing.assert_allclose(state.targets[:, 0], expected, rtol=1e-6, equal_nan=True)
    idx = np.r_[fit[:4], val[:4]]
    torch.manual_seed(2)
    model = task.build(TWO[1]).eval()
    predicted = nn3._predict(task, state, model, idx, 3, "cpu")
    inputs, _ = task.batch(state, idx, "cpu")
    with torch.no_grad():
        direct = model(*inputs).numpy() * state.y_scale
    np.testing.assert_allclose(predicted, direct, rtol=1e-5)
    assert task.architecture()["target"] == models.TARGET_SCALING


# M3 chooses each fold's configuration by pooled Spearman: the score is
# taken once per configuration on the validation units, with the
# configuration's forecasts in bp against the raw labels, and the best one
# (ties to the earlier) is the one kept.
def test_m3_chooses_its_configuration_by_pooled_spearman(monkeypatch):
    data = _timing(_export(SESSIONS))
    tensor = _tensor(NAMES, _days(SESSIONS))
    settings = _settings(grid=TWO, seeds=(0, 1))
    calls = []
    real = models.pooled_score

    # Record every score the walk-forward takes, then take it as stage 4 does.
    def spy(task, data_, units, forecast):
        value = real(task, data_, units, forecast)
        calls.append((units.copy(), forecast.copy(), value))
        return value

    monkeypatch.setattr(models, "pooled_score", spy)
    forecast = models.run_seq(data, tensor, settings)
    record = forecast.meta["folds"][0]
    assert len(calls) == len(TWO)
    task = models.TimingSeqTask(data, tensor, settings)
    _, _, _, val, _ = _first_fold(task, data, settings)
    y = data.y.astype(np.float64)
    for units, predicted, value in calls:
        np.testing.assert_array_equal(units, val)
        assert value == pytest.approx(io.spearman(predicted[:, 0], y[units]), rel=1e-12)
    scores = [c["score"] for c in record["configs"]]
    assert scores == pytest.approx([value for _, _, value in calls], rel=1e-12)
    assert record["chosen"] == int(np.argmax(scores))
    assert forecast.meta["settings"]["metric"] == "pooled_spearman"


# M3 walked forward: gap 11 and a 252-session block, only test rows with a
# window forecast (NaN-labelled ones too), the chosen configuration's
# first-seed column in yhat_configs, the scale in bp, a row whose ticker
# the tensor lacks never trained or forecast and counted, and a second run
# the same to the bit.
def test_m3_walks_forward_and_repeats_exactly():
    data = _timing(_export(SESSIONS), "sell")
    tensor = _tensor(NAMES[:4], _days(SESSIONS))
    settings = _settings(grid=TWO, seeds=(0, 1))
    first = models.run_seq(data, tensor, settings)
    second = models.run_seq(data, tensor, settings)
    for name in (*ARRAYS, "yhat_configs"):
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
    _, index = io.session_index(data.dates)
    windowed = data.tickers != "EEE"
    test = (index >= 40) & windowed
    assert np.isfinite(first.yhat[test]).all()
    assert np.isnan(first.yhat[~test]).all()
    assert (first.fold[~test] == -1).all()
    assert (~np.isfinite(data.y) & test).sum() > 0
    record = first.meta["folds"][0]
    assert record["sessions"] == _fold_sessions(len(np.unique(data.dates)))
    labelled = np.isfinite(data.y) & windowed
    assert record["units"]["fit"] == (labelled & (index < 8)).sum()
    assert (
        record["units"]["validation"] == (labelled & (index >= 19) & (index < 29)).sum()
    )
    assert record["scaling"]["y_scale"] > 50
    chosen = record["chosen"]
    np.testing.assert_array_equal(
        first.yhat_configs[test, chosen], first.yhat_seeds[test, 0]
    )
    assert first.yhat_configs.shape == (len(data), 2)
    np.testing.assert_allclose(first.yhat, first.yhat_seeds.mean(axis=1), rtol=1e-6)
    meta = first.meta
    assert meta["inputs"]["rows_no_ticker"] == SESSIONS
    assert (meta["model"], meta["family"], meta["kind"]) == ("M3", io.SEQ, io.S1)
    assert (meta["side"], meta["target"]) == ("sell", "g_sell")
    assert (meta["settings"]["refit"], meta["settings"]["gap"]) == (252, 11)
    assert meta["registered"] is False


# An unlabelled row never trains M3: new daily columns on every unlabelled
# row leave every other row's forecast exactly as it was, while a tested
# unlabelled row's own forecast moves.
def test_an_unlabelled_row_never_trains_m3():
    data = _timing(_export(SESSIONS))
    tensor = _tensor(NAMES, _days(SESSIONS))
    settings = _settings(grid=TWO)
    base = models.run_seq(data, tensor, settings)
    unlabelled = ~np.isfinite(data.y)
    rng = np.random.default_rng(4)
    x = data.x.copy()
    x[unlabelled] = rng.normal(size=(int(unlabelled.sum()), x.shape[1])) * 30 + 10
    moved = models.run_seq(dataclasses.replace(data, x=x), tensor, settings)
    for name in ARRAYS:
        np.testing.assert_array_equal(
            getattr(moved, name)[~unlabelled], getattr(base, name)[~unlabelled]
        )
    tested = unlabelled & (base.fold >= 0)
    assert tested.any()
    assert not np.array_equal(moved.yhat[tested], base.yhat[tested])


# M3 learns a timing label planted in a daily column, out of sample, and
# its forecasts come back on the label's own scale in bp: a forecast left in
# training units would be about 200 times too small.
def test_m3_learns_a_planted_timing_signal_in_bp():
    names = np.array([f"N{i:02d}" for i in range(16)])
    data = _timing(_export(90, names=names, seed=5), seed=6)
    tensor = _tensor(names, _days(90), seed=7)
    settings = _settings(
        grid=({"lr": 3e-3, "dropout": 0.0, "width": 8},),
        max_epochs=25,
        patience=5,
        batch=64,
        min_train=60,
        validation=16,
    )
    forecast = models.run_seq(data, tensor, settings)
    test = np.isfinite(forecast.yhat) & np.isfinite(data.y)
    assert test.sum() > 350  # 25 labelled test sessions x 16 names, less ~3%
    y = data.y.astype(np.float64)
    assert io.spearman(forecast.yhat[test], y[test]) > 0.3
    ratio = forecast.yhat[test].std() / y[test].std()
    assert 0.3 < ratio < 1.5, ratio


# The networks' fold loop is stage 3's own procedure: handed stage 3's T-S1
# task and score, it reproduces stage3_nn.run_seq's forecasts, choices and
# training records bit for bit.
def test_the_network_loop_is_stage3s_fold_procedure():
    data = _export(SESSIONS)
    tensor = _tensor(NAMES, _days(SESSIONS))
    settings = _settings(grid=TWO, seeds=(0, 1), refit=252, gap=11)
    stage3 = nn3.run_seq(data, tensor, settings)
    ours = models.walk_nets(
        nn3._SeqTask(data, tensor, settings), data, settings, score=nn3._score
    )
    for name in (*ARRAYS, "yhat_configs"):
        np.testing.assert_array_equal(getattr(ours, name), getattr(stage3, name))
    assert _untimed(ours.meta["folds"]) == _untimed(stage3.meta["folds"])
    assert ours.meta["settings"]["metric"] == "_score"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


# The command trains M3 and M2 from files on a smoke protocol and writes
# forecasts keyed by the export's rows, with the side, the protocol, the
# inputs' hashes and the command line, saying they are not registered.
def test_the_command_writes_both_networks_forecasts(tmp_path):
    bar_dates = _days(90, start="2018-11-01")
    data = _export(60, names=NAMES[:4], start=str(bar_dates[30]))
    s1 = io.save_data(tmp_path / "stage3_s1.npz", data)
    g_buy, g_sell = _labels(data)
    labels = _write_labels(
        tmp_path / "stage4_labels.npz",
        data.dates,
        data.tickers,
        g_buy,
        g_sell,
        _sha256(s1),
    )
    seq = io.save_seq(
        tmp_path / "stage3_seq.npz", _tensor(NAMES[:4], np.unique(data.dates))
    )
    ohlcv = io.save_ohlcv(tmp_path / "stage3_ohlcv.npz", _bars(bar_dates, NAMES[:4]))
    smoke = [
        "--device",
        "cpu",
        "--seeds",
        "0,1",
        "--max-epochs",
        "1",
        "--min-train",
        "40",
        "--validation",
        "10",
        "--batch",
        "32",
    ]
    runs = (
        (io.SEQ, "sell", ["--seq", str(seq), "--grid-first", "1"], seq),
        (io.CNN_I20, "buy", ["--ohlcv", str(ohlcv)], ohlcv),
    )
    for family, side, extra, source in runs:
        out = tmp_path / f"{family}_{side}.npz"
        argv = [
            "--family",
            family,
            "--side",
            side,
            "--s1",
            str(s1),
            "--labels",
            str(labels),
            "--out",
            str(out),
            *extra,
            *smoke,
        ]
        text = textio.StringIO()
        assert cli.main(argv, out=text) == 0
        printed = text.getvalue()
        assert "fold 1/1: test" in printed
        assert "NOT the registered settings" in printed
        forecast = io.load_forecast(out)
        assert forecast.family == family
        assert forecast.kind == io.S1
        np.testing.assert_array_equal(forecast.dates, data.dates)
        np.testing.assert_array_equal(forecast.tickers, data.tickers)
        assert forecast.yhat_seeds.shape == (len(data), 2)
        _, index = io.session_index(data.dates)
        assert np.isfinite(forecast.yhat[index >= 40]).all()
        meta = forecast.meta
        assert meta["registered"] is False
        assert meta["side"] == side
        assert meta["labels_sha256"] == _sha256(labels)
        assert meta["s1_sha256"] == _sha256(s1)
        assert [f["path"] for f in meta["input_files"]] == [
            str(s1),
            str(labels),
            str(source),
        ]
        assert meta["command"] == argv
        assert meta["settings"]["seeds"] == [0, 1]
        assert meta["settings"]["max_epochs"] == 1
        assert meta["settings"]["device"] == "cpu"
