"""Stage 4's model adapters without LightGBM or torch: rows, labels, protocol, command.

What has to hold (docs/research/stage4-plan-2026-09-29.md, "Rows and the
timing target" and "Models"; backend/market/stage4_models.py):

- A stage-4 dataset is the export's T-S1 rows in order with y = g_buy or
  g_sell in bp. Labels whose keys are not the export's rows, that were made
  from another export, or that are infinite are refused. NaN stays NaN, and
  the stage-3 relative return never comes along.
- M1's view is a ``ti`` dataset of the same rows over the daily columns, so
  stage 3's T-I path winsorizes and chooses by pooled Spearman.
- The walk-forward starts at session 500 with a gap of 11 at both
  boundaries and test blocks of 63 sessions (M1) or 252 (M2, M3).
- `registered` is true only when every protocol setting is the plan's.
- M1's bagging fraction reaches every LightGBM training call as 0.7.
- The networks choose by pooled Spearman, not by the mean daily IC.
- The command refuses a run it cannot describe, and labels that are not the
  export's, before anything trains; it accepts a file the labels command wrote.

The model runs themselves are in test_stage4_models_lgbm.py (LightGBM) and
test_stage4_models_nets.py (torch); both import the helpers below.
"""

from __future__ import annotations

import contextlib
import hashlib
import io as textio
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_stage4_labels as labels_cli
from backend.cli import market_stage4_models as cli
from backend.market import stage3_io as io
from backend.market import stage3_nn as nn3
from backend.market import stage3_trees as trees
from backend.market import stage4_models as models

NAMES = np.array(["AAA", "BBB", "CCC", "DDD", "EEE"])
DAILY = ("d_signal", "d_noise", "d_grade_a")


# `n` weekdays from `start`.
def _days(n, start="2019-01-02"):
    return np.busday_offset(np.datetime64(start, "D"), np.arange(n), roll="forward")


# A stage-3 T-S1 export in its file's shape: a row per (session, name),
# sorted; three daily columns (a signal, noise, a grade flag) and one
# intraday-named column only M1's view leaves out; the stage-3 label (a
# rank-Gauss) and its extras, the relative return and the grade.
def _export(sessions, names=NAMES, seed=0, start="2019-01-02"):
    rng = np.random.default_rng(seed)
    count = sessions * len(names)
    dates = np.repeat(_days(sessions, start), len(names))
    x = np.stack(
        [
            rng.normal(size=count),
            rng.normal(size=count),
            (rng.random(count) < 0.5).astype(float),
            rng.normal(size=count),
        ],
        axis=1,
    ).astype(np.float32)
    r = 0.08 * rng.normal(size=count)
    return io.Stage3Data(
        kind=io.S1,
        dates=dates,
        tickers=np.tile(np.asarray(names), sessions),
        slot=np.zeros(count, dtype=np.int8),
        x=x,
        feature_names=(*DAILY, "i_other"),
        y=io.rank_gauss(r, dates).astype(np.float32),
        extra={
            "r": r.astype(np.float32),
            "grade": rng.integers(0, 4, count).astype(np.int8),
        },
        meta={"synthetic": True},
    )


# Timing labels for an export's rows, in bp: g_buy grows with the signal
# column, g_sell falls with it, both with heavy-tailed noise; NaN on the
# rows of the last five sessions (their window is unfinished) and on 3% of
# the others (a missing cube session).
def _labels(data, seed=1):
    rng = np.random.default_rng(seed)
    signal = data.x[:, 0].astype(np.float64)
    g_buy = 150.0 * signal + 100.0 * rng.standard_t(4, size=len(data))
    g_sell = -90.0 * signal + 120.0 * rng.standard_t(4, size=len(data))
    sessions = np.unique(data.dates)
    missing = (data.dates >= sessions[-5]) | (rng.random(len(data)) < 0.03)
    g_buy[missing] = np.nan
    g_sell[missing] = np.nan
    return g_buy, g_sell


# One side's stage-4 dataset for an export, from `_labels`.
def _timing(data, side="buy", seed=1):
    g_buy, g_sell = _labels(data, seed)
    return models.timing_data(data, data.dates, data.tickers, g_buy, g_sell, side)


# A file's sha256.
def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Write a labels file as market_stage4_labels writes it: the export's keys,
# both labels as float32 and a JSON meta naming the export's sha256.
def _write_labels(path, dates, tickers, g_buy, g_sell, s1_sha256):
    meta = {
        "plan": "docs/research/stage4-plan-2026-09-29.md",
        "window": 5,
        "s1_sha256": s1_sha256,
    }
    with path.open("wb") as handle:
        np.savez(
            handle,
            dates=np.asarray(dates, dtype="datetime64[D]"),
            tickers=np.asarray(tickers, dtype=str),
            g_buy=np.asarray(g_buy, dtype=np.float32),
            g_sell=np.asarray(g_sell, dtype=np.float32),
            meta=np.asarray(json.dumps(meta, sort_keys=True)),
        )
    return path


# An export and its labels on disk, the labels made from that export.
def _files(tmp_path, sessions, names=NAMES, seed=0, start="2019-01-02"):
    data = _export(sessions, names, seed, start)
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
    return data, s1, labels


# The dataset is the export's rows, keys and columns in order, with one
# side's label in bp as y (NaN kept), the side in its meta, the grade kept
# and the stage-3 relative return dropped.
def test_the_dataset_is_the_exports_rows_with_one_sides_label_in_bp():
    data = _export(30)
    g_buy, g_sell = _labels(data)
    for side, label in (("buy", g_buy), ("sell", g_sell)):
        timing = models.timing_data(data, data.dates, data.tickers, g_buy, g_sell, side)
        assert timing.kind == io.S1
        np.testing.assert_array_equal(timing.dates, data.dates)
        np.testing.assert_array_equal(timing.tickers, data.tickers)
        np.testing.assert_array_equal(timing.slot, data.slot)
        np.testing.assert_array_equal(timing.x, data.x)
        assert timing.feature_names == data.feature_names
        assert timing.y.dtype == np.float32
        np.testing.assert_array_equal(timing.y, label.astype(np.float32))
        assert np.isnan(timing.y).sum() == np.isnan(label).sum() > 0
        assert set(timing.extra) == {"grade"}
        np.testing.assert_array_equal(timing.extra["grade"], data.extra["grade"])
        record = timing.meta["stage4"]
        assert record["side"] == side
        assert record["target"] == f"g_{side}"
        assert record["units"] == "bp"
        assert record["labelled"] == int(np.isfinite(label).sum())
    # The stage-3 label never reaches y.
    assert not np.array_equal(timing.y, data.y)


# Labels that are not the export's rows, in order, are refused: too few, two
# names swapped on one date, a date moved; so are a side that does not
# exist, a T-I dataset and an infinite label. A labels file made from
# another export is refused by its recorded sha256.
def test_labels_that_are_not_the_exports_rows_are_refused():
    data = _export(20)
    g_buy, g_sell = _labels(data)
    with pytest.raises(ValueError, match="99 dates and 99 tickers"):
        models.timing_data(
            data, data.dates[:-1], data.tickers[:-1], g_buy[:-1], g_sell[:-1], "buy"
        )
    swapped = data.tickers.copy()
    swapped[[7, 8]] = swapped[[8, 7]]
    with pytest.raises(
        ValueError, match="2 label rows are not the export's rows; the first is row 7"
    ):
        models.timing_data(data, data.dates, swapped, g_buy, g_sell, "buy")
    moved = data.dates.copy()
    moved[42] = moved[42] + np.timedelta64(1, "D")
    with pytest.raises(ValueError, match="1 label rows"):
        models.timing_data(data, moved, data.tickers, g_buy, g_sell, "sell")
    with pytest.raises(ValueError, match="side"):
        models.timing_data(data, data.dates, data.tickers, g_buy, g_sell, "hold")
    ti = io.Stage3Data(
        io.TI, data.dates, data.tickers, data.slot, data.x, data.feature_names, data.y
    )
    with pytest.raises(ValueError, match="T-S1 rows"):
        models.timing_data(ti, data.dates, data.tickers, g_buy, g_sell, "buy")
    infinite = g_sell.copy()
    infinite[3] = np.inf
    with pytest.raises(ValueError, match="1 sell labels are infinite"):
        models.timing_data(data, data.dates, data.tickers, g_buy, infinite, "sell")
    models.timing_data(data, data.dates, data.tickers, g_buy, infinite, "buy")
    models.check_labels_source({"s1_sha256": "ab" * 32}, "ab" * 32)
    with pytest.raises(ValueError, match="made from the export"):
        models.check_labels_source({"s1_sha256": "ab" * 32}, "cd" * 32)
    with pytest.raises(ValueError, match="None"):
        models.check_labels_source({}, "cd" * 32)


# M1 reads the rows as a ``ti`` dataset: the same keys and label, slot 0,
# the daily columns only (every column when all are daily, without a copy).
def test_m1_reads_the_rows_as_a_ti_dataset_over_the_daily_columns():
    timing = _timing(_export(12))
    view = models.tree_data(timing)
    assert view.kind == io.TI
    assert view.feature_names == DAILY
    np.testing.assert_array_equal(view.x, timing.x[:, :3])
    np.testing.assert_array_equal(view.y, timing.y)
    np.testing.assert_array_equal(view.dates, timing.dates)
    np.testing.assert_array_equal(view.tickers, timing.tickers)
    assert (view.slot == 0).all()
    io.validate(view)
    daily_only = models.timing_data(
        io.Stage3Data(
            io.S1,
            timing.dates,
            timing.tickers,
            timing.slot,
            timing.x[:, :3],
            DAILY,
            timing.y,
        ),
        timing.dates,
        timing.tickers,
        timing.y,
        timing.y,
        "buy",
    )
    assert models.tree_data(daily_only).x is daily_only.x
    no_daily = models.timing_data(
        io.Stage3Data(
            io.S1,
            timing.dates,
            timing.tickers,
            timing.slot,
            timing.x[:, 3:],
            ("i_other",),
            timing.y,
        ),
        timing.dates,
        timing.tickers,
        timing.y,
        timing.y,
        "buy",
    )
    with pytest.raises(ValueError, match="daily column"):
        models.tree_data(no_daily)


# Every runner refuses a dataset timing_data did not build, before it needs
# LightGBM or torch: the export itself would train on the stage-3 label.
def test_the_runners_refuse_a_dataset_that_is_not_a_timing_dataset():
    export = _export(12)
    with pytest.raises(ValueError, match="not a stage-4 timing dataset"):
        models.run_lgbm(export)
    with pytest.raises(ValueError, match="not a stage-4 timing dataset"):
        models.run_cnn(export, None)
    with pytest.raises(ValueError, match="not a stage-4 timing dataset"):
        models.run_seq(export, None)


# The walk-forward: the first test block at session 500, test blocks of 63
# sessions for M1 and 252 for M2 and M3, the window ending 11 sessions
# before its test block and the fit part 11 sessions before the last 252.
def test_the_walk_forward_has_gap_11_and_the_plans_cadence():
    lgbm = models.folds_for(io.LGBM, 700)
    assert [(f.test_start, f.test_end) for f in lgbm] == [
        (500, 563),
        (563, 626),
        (626, 689),
        (689, 700),
    ]
    for family in (io.CNN_I20, io.SEQ):
        nets = models.folds_for(family, 900)
        assert [(f.test_start, f.test_end) for f in nets] == [(500, 752), (752, 900)]
    for fold in lgbm + nets:
        assert fold.window_end == fold.test_start - 11
        assert fold.val_start == fold.window_end - 252
        assert fold.fit_end == fold.val_start - 11
    assert (lgbm[0].fit_end, lgbm[0].val_start, lgbm[0].window_end) == (226, 237, 489)
    smoke = models.folds_for(io.SEQ, 70, min_train=40, validation=10)
    assert [
        (f.fit_end, f.val_start, f.window_end, f.test_start, f.test_end) for f in smoke
    ] == [(8, 19, 29, 40, 70)]
    cut = models.folds_for(io.LGBM, 90, min_train=40, validation=10, refit=20, gap=2)
    assert [(f.test_start, f.test_end, f.window_end, f.fit_end) for f in cut] == [
        (40, 60, 38, 26),
        (60, 80, 58, 46),
        (80, 90, 78, 66),
    ]
    assert models.folds_for(io.LGBM, 500) == []
    with pytest.raises(ValueError, match="family"):
        models.folds_for(io.CNN_I5, 700)


# `registered` is true exactly when every protocol value is the plan's: the
# thread count and the device are execution details, an explicit plan
# value is still the plan, and anything else - stage 3's gap or cadence, a
# cut grid, fewer seeds, a capped run, stage 3's T-I bagging, a fold cut -
# is not.
def test_registered_means_every_protocol_setting_is_the_plans():
    protocol = models.lgbm_protocol()
    assert (protocol["refit"], protocol["gap"], protocol["bagging_fraction"]) == (
        63,
        11,
        0.7,
    )
    assert protocol["grid"] == [dict(c) for c in io.LGBM_GRID]
    assert protocol["seeds"] == [0, 1, 2, 3, 4]
    assert (protocol["max_rounds"], protocol["patience"]) == (3000, 200)
    assert (protocol["min_train"], protocol["validation"]) == (500, 252)
    assert protocol["winsor_quantiles"] == [0.005, 0.995]
    assert protocol["metric"] == "pooled_spearman"
    assert models.lgbm_registered()
    assert models.lgbm_registered(trees.Settings(num_threads=3))
    assert models.lgbm_registered(trees.Settings(refit=63, gap=11))
    for changed in (
        trees.Settings(gap=26),
        trees.Settings(refit=126),
        trees.Settings(seeds=(0,)),
        trees.Settings(grid=io.LGBM_GRID[:2]),
        trees.Settings(max_rounds=100),
        trees.Settings(min_train=150),
    ):
        assert not models.lgbm_registered(changed)
    assert not models.lgbm_registered(bagging=0.3)
    assert not models.lgbm_registered(max_folds=1)
    seq = models.net_protocol(io.SEQ)
    assert seq["grid"] == [dict(c) for c in io.SEQ_GRID]
    assert (
        seq["refit"],
        seq["gap"],
        seq["max_epochs"],
        seq["patience"],
        seq["batch"],
    ) == (
        252,
        11,
        60,
        6,
        512,
    )
    cnn = models.net_protocol(io.CNN_I20)
    assert cnn["grid"] == [{"lr": 1e-5}]
    assert (
        cnn["refit"],
        cnn["gap"],
        cnn["max_epochs"],
        cnn["patience"],
        cnn["batch"],
    ) == (
        252,
        11,
        100,
        2,
        128,
    )
    for family in (io.SEQ, io.CNN_I20):
        assert models.net_registered(family)
        assert models.net_registered(family, nn3.Settings(device="cuda"))
        assert models.net_registered(family, nn3.Settings(refit=252, gap=11))
        for changed in (
            nn3.Settings(gap=26),
            nn3.Settings(refit=63),
            nn3.Settings(max_epochs=1),
            nn3.Settings(patience=3),
            nn3.Settings(batch=64),
            nn3.Settings(seeds=(0, 1)),
            nn3.Settings(max_folds=1),
            nn3.Settings(validation=10),
        ):
            assert not models.net_registered(family, changed)
    assert models.net_registered(io.SEQ, nn3.Settings(grid=io.SEQ_GRID))
    assert not models.net_registered(io.SEQ, nn3.Settings(grid=io.SEQ_GRID[:1]))
    assert not models.net_registered(io.CNN_I20, nn3.Settings(grid=({"lr": 1e-3},)))
    with pytest.raises(ValueError, match="network family"):
        models.net_protocol(io.LGBM)


# A stand-in for the lightgbm module that records what it is asked to train.
class _FakeLightGBM:
    """Records train calls; Dataset and early_stopping are plain markers."""

    __version__ = "fake"

    # Start with no calls recorded.
    def __init__(self):
        self.calls = []

    # Record one training call and return a marker booster.
    def train(self, params, *args, **kwargs):
        self.calls.append((params, args, kwargs))
        return "booster"

    # A marker Dataset.
    def Dataset(self, *args, **kwargs):  # noqa: N802 - lightgbm's name
        return "dataset"

    # A marker callback.
    def early_stopping(self, *args, **kwargs):
        return "callback"


# Bagged hands LightGBM stage 3's parameters with only the bagging fraction
# replaced by the plan's 0.7, leaves the caller's parameters untouched, and
# passes everything else through.
def test_bagged_lightgbm_trains_every_model_at_the_plans_fraction():
    fake = _FakeLightGBM()
    bagged = models.Bagged(fake, models.LGBM_BAGGING)
    params = trees.lgbm_params(io.TI, io.LGBM_GRID[3], seed=4, num_threads=2)
    assert params["bagging_fraction"] == 0.3  # stage 3's T-I fraction
    assert (
        bagged.train(params, "fit set", num_boost_round=7, valid_sets=["v"])
        == "booster"
    )
    sent, args, kwargs = fake.calls[0]
    assert sent["bagging_fraction"] == 0.7
    assert {k: v for k, v in sent.items() if k != "bagging_fraction"} == {
        k: v for k, v in params.items() if k != "bagging_fraction"
    }
    assert args == ("fit set",)
    assert kwargs == {"num_boost_round": 7, "valid_sets": ["v"]}
    assert params["bagging_fraction"] == 0.3
    assert bagged.Dataset(np.zeros((2, 2))) == "dataset"
    assert bagged.early_stopping(5) == "callback"
    assert bagged.__version__ == "fake"
    assert bagged.fraction == 0.7


# The networks' selection score is pooled Spearman over the units' rows. On
# two dates whose names are ranked perfectly within each date but whose
# levels are inverted, the mean daily IC (stage 3's T-S1 metric) is +1 and
# the pooled Spearman about -0.52; rows a unit does not map to are skipped.
def test_network_selection_is_pooled_spearman():
    dates = np.repeat(_days(2), 5)
    y = np.r_[np.arange(1.0, 6.0), np.arange(101.0, 106.0)]
    data = SimpleNamespace(y=y.astype(np.float32), dates=dates)
    forecast = np.r_[np.arange(11.0, 16.0), np.arange(1.0, 6.0)][:, None]
    rows = np.arange(10)
    units = nn3.Units(first=rows, rows=rows[:, None], targets=y[:, None], of_row=rows)
    task = SimpleNamespace(kind=io.S1, units=units)
    every = np.arange(10)
    pooled = models.pooled_score(task, data, every, forecast)
    assert pooled == pytest.approx(-42.5 / 82.5, rel=1e-12)
    assert pooled == pytest.approx(io.spearman(forecast[:, 0], y), rel=1e-12)
    assert nn3._score(task, data, every, forecast) == pytest.approx(1.0)
    gapped = nn3.Units(
        first=rows,
        rows=np.where(rows == 4, -1, rows)[:, None],
        targets=y[:, None],
        of_row=rows,
    )
    kept = np.flatnonzero(rows != 4)
    assert models.pooled_score(
        SimpleNamespace(kind=io.S1, units=gapped), data, every, forecast
    ) == pytest.approx(io.spearman(forecast[kept, 0], y[kept]), rel=1e-12)
    assert math.isnan(models.pooled_score(task, data, every[:2], forecast[:2]))


# The command refuses what cannot describe a run, before reading a file: a
# family's missing input, an input or option the family does not read, a
# count below its minimum, a bad seed list, an unknown side or family.
def test_the_command_refuses_runs_it_cannot_describe(tmp_path):
    common = [
        "--s1",
        str(tmp_path / "s1.npz"),
        "--labels",
        str(tmp_path / "l.npz"),
        "--out",
        str(tmp_path / "f.npz"),
    ]
    refused = [
        (["--family", "seq", "--side", "buy"], "needs --seq"),
        (["--family", "cnn_i20", "--side", "buy"], "needs --ohlcv"),
        (["--family", "lgbm", "--side", "buy", "--seq", "x.npz"], "--seq is for"),
        (
            ["--family", "seq", "--side", "buy", "--seq", "x.npz", "--ohlcv", "o.npz"],
            "--ohlcv is for",
        ),
        (
            ["--family", "lgbm", "--side", "buy", "--max-epochs", "1"],
            "--max-epochs is for",
        ),
        (["--family", "lgbm", "--side", "buy", "--batch", "8"], "--batch is for"),
        (
            ["--family", "seq", "--side", "buy", "--seq", "x.npz", "--max-rounds", "5"],
            "--max-rounds is for",
        ),
        (
            [
                "--family",
                "cnn_i20",
                "--side",
                "buy",
                "--ohlcv",
                "o.npz",
                "--grid-first",
                "1",
            ],
            "--grid-first is for",
        ),
        (
            ["--family", "lgbm", "--side", "buy", "--max-folds", "0"],
            "--max-folds must be",
        ),
        (["--family", "lgbm", "--side", "buy", "--threads", "0"], "--threads must be"),
        (["--family", "lgbm", "--side", "buy", "--gap", "-1"], "--gap must not"),
        (["--family", "lgbm", "--side", "buy", "--grid-first", "9"], "at most 8"),
        (
            ["--family", "seq", "--side", "sell", "--seq", "x.npz", "--seeds", "0,0"],
            "repeats a seed",
        ),
        (
            ["--family", "seq", "--side", "sell", "--seq", "x.npz", "--seeds", ","],
            "at least one seed",
        ),
        (["--family", "lgbm", "--side", "hold"], "invalid choice: 'hold'"),
        (
            ["--family", "cnn_i5", "--side", "buy", "--ohlcv", "o.npz"],
            "invalid choice: 'cnn_i5'",
        ),
    ]
    for argv, reason in refused:
        errors = textio.StringIO()
        with contextlib.redirect_stderr(errors), pytest.raises(SystemExit):
            cli.main([*argv, *common], out=textio.StringIO())
        assert reason in errors.getvalue(), (argv, errors.getvalue())
    assert cli.parse_seeds("0, 2,4") == (0, 2, 4)
    assert not (tmp_path / "f.npz").exists()


# The command's inputs: an export and the labels made from it load as one
# side's dataset with their hashes; labels made from another export, or
# holding other rows, are refused before anything trains or is written.
def test_the_command_refuses_labels_that_are_not_the_exports(tmp_path):
    data, s1, labels = _files(tmp_path, 15)
    timing, provenance = cli.load_inputs(s1, labels, "sell")
    np.testing.assert_array_equal(timing.y, _labels(data)[1].astype(np.float32))
    assert timing.meta["stage4"]["side"] == "sell"
    assert provenance["s1_sha256"] == _sha256(s1)
    assert provenance["labels_sha256"] == _sha256(labels)
    assert provenance["export_registered"] is False
    assert provenance["labels_meta"]["s1_sha256"] == _sha256(s1)
    g_buy, g_sell = _labels(data)
    other = _write_labels(
        tmp_path / "other.npz", data.dates, data.tickers, g_buy, g_sell, "0" * 64
    )
    rows = _write_labels(
        tmp_path / "rows.npz",
        data.dates[5:],
        data.tickers[5:],
        g_buy[5:],
        g_sell[5:],
        _sha256(s1),
    )
    out = tmp_path / "forecast.npz"
    for path, reason in (
        (other, "made from the export"),
        (rows, "70 dates and 70 tickers"),
    ):
        argv = [
            "--family",
            "lgbm",
            "--side",
            "buy",
            "--s1",
            str(s1),
            "--labels",
            str(path),
            "--out",
            str(out),
        ]
        with pytest.raises(SystemExit, match=f"refused: .*{reason}"):
            cli.main(argv, out=textio.StringIO())
    assert not out.exists()


# A labels file the labels command itself wrote (from its stand-in loader,
# as its own test runs it) loads with the export it was made from.
def test_a_file_the_labels_command_wrote_is_accepted(tmp_path):
    from backend.tests.test_stage4_labels import _cube, _dates, _zigzag

    sessions = 60
    dates = _dates(sessions)
    closes = _zigzag(sessions)
    panel = SimpleNamespace(
        dates=dates,
        tickers=["AAA"],
        close=closes[:, None],
        adj_close=closes[:, None],
        high=closes[:, None],
        low=closes[:, None],
    )
    export = io.Stage3Data(
        kind=io.S1,
        dates=dates[25:45],
        tickers=np.array(["AAA"] * 20),
        slot=np.zeros(20, dtype=np.int8),
        x=np.ones((20, 1), dtype=np.float32),
        feature_names=("d_one",),
        y=np.zeros(20, dtype=np.float32),
        extra={
            "r": np.zeros(20, dtype=np.float32),
            "grade": np.zeros(20, dtype=np.int8),
        },
    )
    s1 = io.save_data(tmp_path / "s1.npz", export)
    labels = tmp_path / "labels.npz"
    args = labels_cli.build_parser().parse_args(["--s1", str(s1), "--out", str(labels)])
    cube = _cube(dates, closes)

    # The labels command's inputs without a store: the panel and the cube.
    def loader(store, tickers, workers, log):
        return panel, {"AAA": cube}

    assert labels_cli.run(args, out=textio.StringIO(), loader=loader) == 0
    _, _, g_buy, g_sell, _ = labels_cli.load(labels)
    for side, label in (("buy", g_buy), ("sell", g_sell)):
        timing, provenance = cli.load_inputs(s1, labels, side)
        np.testing.assert_array_equal(timing.y, label.astype(np.float32))
        # Rows 25..44 of a 60-session cube: every row's five sessions exist.
        assert np.isfinite(timing.y).all()
        assert provenance["labels_meta"]["window"] == 5
        assert provenance["s1_sha256"] == _sha256(s1)
