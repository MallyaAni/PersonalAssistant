"""The drawdown forecast file: round trip, alignment without lookahead, the export, the stage-2 flag.

A hand-built stage-2 dataset (three names, enough sessions for one ridge
fit, random inputs) is walked forward on ``drawdown20`` by the ridge where
torch is absent (the CNN under importorskip) and its forecasts written to
one npz with ticker / date / forecast; the file round-trips, aligns onto a
panel with row (name, t) at the position of date t and a one-session shift
is a different matrix, and `market_deep_stage2 --export-forecasts` writes
the same file from the study's own run.
"""

from __future__ import annotations

import io
import json
from datetime import date

import numpy as np
import pytest

from backend.market import deep_intraday as stage1
from backend.market import deep_stage2 as s2
from backend.market import drawdown_forecast as df

SLOTS = 4


# A hand-built stage-2 dataset: `t` sessions x `n` names with random inputs
# and a drawdown target the inputs partly explain, sorted by session then
# name as `deep_stage2.dataset` sorts.
def _dataset(t: int = stage1.MIN_TRAIN + stage1.REFIT + 5, n: int = 3, seed: int = 0):
    rng = np.random.default_rng(seed)
    sessions = np.busday_offset(
        np.datetime64(date(2018, 1, 2), "D"), np.arange(t), roll="forward"
    ).astype("datetime64[D]")
    names = np.array([f"N{j:02d}" for j in range(n)])
    m = t * n
    x_seq = rng.normal(0, 1, size=(m, SLOTS, 3)).astype(np.float32)
    x_scalar = rng.normal(0, 1, size=(m, 2))
    drawdown = -np.abs(0.05 + 0.02 * x_scalar[:, 0] + rng.normal(0, 0.01, m))
    return s2.Dataset2(
        dates=np.repeat(sessions, n),
        tickers=np.tile(names, t),
        x_seq=x_seq,
        x_scalar=x_scalar,
        scalar_names=("gap", "band_z"),
        y_return=np.zeros(m),
        y_rank=np.full(m, 0.5),
        y_downgrade20=np.zeros(m),
        y_drawdown20=drawdown,
        y_vol20=np.zeros(m),
        trailing_vol20=np.zeros(m),
        fwd20=np.zeros(m),
        grade=np.full(m, s2.A_MIN_GRADE),
        sessions=sessions,
        session_index=np.repeat(np.arange(t), n),
        k=1,
        benchmarks=(),
        benchmark_fill=0,
    )


# The file round-trips: dates, tickers, forecast, the optional realized
# column and the metadata; a file without the fields or with ragged arrays
# is refused.
def test_save_and_load_round_trip(tmp_path):
    dates = np.array(["2024-01-02", "2024-01-02", "2024-01-03"], dtype="datetime64[D]")
    forecasts = df.Forecasts(
        dates=dates,
        tickers=np.array(["AAA", "BBB", "AAA"]),
        forecast=np.array([-0.1, np.nan, -0.2]),
        realized=np.array([-0.05, -0.08, np.nan]),
        meta={"model": "cnn", "fits": [{"n": 1}]},
    )
    path = df.save_forecasts(tmp_path / "out" / "dd.npz", forecasts)
    back = df.load_forecasts(path)
    np.testing.assert_array_equal(back.dates, dates)
    np.testing.assert_array_equal(back.tickers, forecasts.tickers)
    np.testing.assert_array_equal(back.forecast, forecasts.forecast)
    np.testing.assert_array_equal(back.realized, forecasts.realized)
    assert back.meta == {"model": "cnn", "fits": [{"n": 1}]}
    assert len(back) == 3
    with np.load(path) as data:
        assert set(data.files) == {"ticker", "date", "forecast", "realized", "meta"}
        assert data["date"].dtype == np.int64
    bare = df.save_forecasts(
        tmp_path / "bare.npz",
        df.Forecasts(dates, forecasts.tickers, forecasts.forecast),
    )
    assert df.load_forecasts(bare).realized is None
    np.savez(tmp_path / "wrong.npz", ticker=np.array(["A"]), date=np.array([0]))
    with pytest.raises(ValueError, match="lacks forecast arrays"):
        df.load_forecasts(tmp_path / "wrong.npz")
    np.savez(
        tmp_path / "ragged.npz",
        ticker=np.array(["A", "B"]),
        date=np.array([0, 1]),
        forecast=np.array([0.1]),
    )
    with pytest.raises(ValueError, match="differ in length"):
        df.load_forecasts(tmp_path / "ragged.npz")
    with pytest.raises(ValueError, match="one common length"):
        df.save_forecasts(
            tmp_path / "bad.npz", df.Forecasts(dates, forecasts.tickers, np.zeros(2))
        )


# Alignment: row (name, t) lands at the panel position of date t; a name or
# a date the panel lacks is dropped; a shift by one session is a different
# matrix (no lookahead through the grid); a duplicate row is an error;
# unsorted panel dates are refused.
def test_align_puts_row_t_at_t_and_a_shift_differs():
    panel_dates = np.array(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], dtype="datetime64[D]"
    )
    tickers = ("AAA", "BBB", "SPY")
    forecasts = df.Forecasts(
        dates=np.array(
            ["2024-01-02", "2024-01-03", "2024-01-03", "2024-01-06", "2024-01-04"],
            dtype="datetime64[D]",
        ),
        tickers=np.array(["AAA", "AAA", "BBB", "AAA", "ZZZ"]),
        forecast=np.array([-0.1, -0.2, -0.3, -0.4, -0.5]),
    )
    grid = df.align(forecasts, panel_dates, tickers)
    assert grid.shape == (4, 3)
    assert grid[0, 0] == -0.1 and grid[1, 0] == -0.2 and grid[1, 1] == -0.3
    assert np.isnan(grid[:, 2]).all()  # the benchmark has no rows
    assert np.isnan(grid[2:, 0]).all()  # 2024-01-06 is off the panel
    assert np.isfinite(grid).sum() == 3
    shifted = df.align(
        df.Forecasts(
            forecasts.dates + np.timedelta64(1, "D"),
            forecasts.tickers,
            forecasts.forecast,
        ),
        panel_dates,
        tickers,
    )
    assert not np.array_equal(grid, shifted, equal_nan=True)
    assert shifted[1, 0] == -0.1  # the same value one session later
    with pytest.raises(ValueError, match="duplicate"):
        df.align(
            df.Forecasts(
                np.array(["2024-01-02", "2024-01-02"], dtype="datetime64[D]"),
                np.array(["AAA", "AAA"]),
                np.array([1.0, 2.0]),
            ),
            panel_dates,
            tickers,
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        df.align(forecasts, panel_dates[::-1], tickers)
    empty = df.align(
        df.Forecasts(np.array([], dtype="datetime64[D]"), np.array([]), np.array([])),
        panel_dates,
        tickers,
    )
    assert np.isnan(empty).all()


# The export walks the ridge forward on drawdown20 alone and writes exactly
# its values, NaN before the first fit, with the realized target beside
# them; the summary carries the run's shape and the IC per window; the file
# aligns onto a panel of the dataset's own sessions with every scored row
# in place.
def test_export_forecasts_with_the_ridge(tmp_path):
    ds = _dataset()
    dataset_file = s2.save_dataset(tmp_path / "stage2.npz", ds)
    out = tmp_path / "dd.npz"
    lines: list[str] = []
    meta = df.export_forecasts(
        dataset_file, out, device="cpu", model="ridge", log=lines.append
    )
    assert meta["model"] == "ridge" and meta["target"] == "drawdown20"
    assert meta["device"] == "cpu" and meta["rows"] == len(ds)
    assert meta["constants"]["purge"] == s2.PURGE == 20
    assert set(meta["ic"]) == set(stage1.WINDOWS)
    assert len(meta["fits"]) == 2  # MIN_TRAIN + REFIT + 5 sessions: two blocks
    assert any("wrote" in line for line in lines)
    # The file's sequence is float16, so the comparison is with the ridge on
    # the dataset as loaded, not as built.
    direct = s2.walk_forward(s2.load_dataset(dataset_file), "ridge", ("drawdown20",))[
        "drawdown20"
    ]
    back = df.load_forecasts(out)
    np.testing.assert_array_equal(back.forecast, direct.values)
    np.testing.assert_array_equal(back.realized, ds.y_drawdown20)
    np.testing.assert_array_equal(back.dates, ds.dates)
    np.testing.assert_array_equal(back.tickers, ds.tickers)
    before = ds.session_index < stage1.MIN_TRAIN
    assert np.isnan(back.forecast[before]).all()
    assert np.isfinite(back.forecast[~before]).all()
    assert meta["scored_rows"] == int((~before).sum())
    assert back.meta["scored_rows"] == meta["scored_rows"]
    grid = df.align(back, ds.sessions, tuple(np.unique(ds.tickers)) + ("SPY",))
    assert grid.shape == (len(ds.sessions), 4)
    assert np.isfinite(grid[:, :3]).sum() == meta["scored_rows"]
    assert np.isnan(grid[:, 3]).all()
    assert (
        grid[stage1.MIN_TRAIN, 0]
        == direct.values[
            (ds.session_index == stage1.MIN_TRAIN) & (ds.tickers == "N00")
        ][0]
    )


# `market_deep_stage2 --export-forecasts` writes the drawdown20 forecast of
# the study's own run (the ridge here) beside the payload and records the
# export; without a drawdown20 target it writes nothing and says so.
def test_stage2_cli_export_forecasts(tmp_path):
    from backend.cli import market_deep_stage2 as cli

    ds = _dataset()
    dataset_file = s2.save_dataset(tmp_path / "stage2.npz", ds)
    npz = tmp_path / "forecasts" / "dd.npz"
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--dataset",
            str(dataset_file),
            "--models",
            "ridge",
            "--targets",
            "drawdown20",
            "--device",
            "cpu",
            "--export-forecasts",
            str(npz),
            "--out",
            "dd.json",
        ]
    )
    assert cli.run(args, out) == 0
    assert npz.exists()
    text = out.getvalue()
    assert f"wrote ridge drawdown20 forecasts to {npz}" in text
    payload = json.loads((tmp_path / "desk" / "dd.json").read_text(encoding="utf-8"))
    export = payload["forecast_export"]
    assert export["written"] == str(npz) and export["model"] == "ridge"
    assert export["dataset"] == str(dataset_file)
    back = df.load_forecasts(npz)
    direct = s2.walk_forward(s2.load_dataset(dataset_file), "ridge", ("drawdown20",))[
        "drawdown20"
    ]
    np.testing.assert_array_equal(back.forecast, direct.values)
    assert back.meta["model"] == "ridge"
    # Without the target nothing is written.
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--dataset",
            str(dataset_file),
            "--models",
            "ridge",
            "--targets",
            "rank",
            "--device",
            "cpu",
            "--export-forecasts",
            str(tmp_path / "none.npz"),
            "--out",
            "rank.json",
        ]
    )
    assert cli.run(args, out) == 0
    assert not (tmp_path / "none.npz").exists()
    assert "nothing to export" in out.getvalue()
    payload = json.loads((tmp_path / "desk" / "rank.json").read_text(encoding="utf-8"))
    assert payload["forecast_export"]["written"] is None
    # The CNN is preferred when it ran; here only the ridge did.
    forecasts = {("ridge", "drawdown20"): direct}
    summary = cli.write_forecasts(
        ds, forecasts, tmp_path / "again.npz", "cpu", "ds", lambda _: None
    )
    assert summary["model"] == "ridge" and summary["written"] == str(
        tmp_path / "again.npz"
    )


# The CNN export (skipped where torch is absent): the file's forecasts are
# the CNN's walk-forward values, scored from the first fit on.
def test_export_forecasts_with_the_cnn(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(stage1, "_ANNOUNCED", set())
    monkeypatch.setattr(stage1, "CNN_CONFIG", {**stage1.CNN_CONFIG, "epochs": 1})
    ds = _dataset()
    dataset_file = s2.save_dataset(tmp_path / "stage2.npz", ds)
    out = tmp_path / "dd_cnn.npz"
    meta = df.export_forecasts(dataset_file, out, device="cpu", model="cnn")
    assert meta["model"] == "cnn" and meta["parameters"]
    back = df.load_forecasts(out)
    before = ds.session_index < stage1.MIN_TRAIN
    assert np.isnan(back.forecast[before]).all()
    assert np.isfinite(back.forecast[~before]).all()
