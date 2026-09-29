"""The volatility forecast file round-trips, aligns to a panel without lookahead, and exports from the walk-forward.

The dataset's row (name, t) targets session t + 1 - asserted here against
the cube's own bars, not the docstring - so the aligned matrix puts the row
at date t and a one-session shift of it is a different matrix. The export
runs `deep_intraday.walk_forward` on the volatility target (the ridge here,
where torch is absent; the CNN under importorskip) and writes exactly its
out-of-sample values with the baseline and the realized target beside
them; the CLI wraps it.
"""

import io
import json
import math
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from backend.cli import market_vol_forecast as cli
from backend.market import deep_intraday as di
from backend.market import vol_forecast as vf
from backend.market.session_anatomy import bar_returns
from backend.tests.test_deep_intraday import CAL, _book


# `n` weekday dates from `start`.
def _dates(n: int, start: date = date(2016, 1, 4)) -> np.ndarray:
    first = np.datetime64(start, "D")
    return np.busday_offset(first, np.arange(n), roll="forward", busdaycal=CAL)


# A hand-built dataset of `sessions` x `names` rows with random inputs, a
# volatility target that follows the trailing scalar plus noise (so the
# ridge has something to fit), sorted the way `deep_intraday.dataset` sorts.
def _dataset(sessions: int, names: int = 3, seed: int = 0) -> di.Dataset:
    rng = np.random.default_rng(seed)
    dates = _dates(sessions)
    m = sessions * names
    tickers = np.array([f"N{j:02d}" for j in range(names)] * sessions)
    session_index = np.repeat(np.arange(sessions), names)
    trailing = rng.normal(math.log(0.0004), 0.3, size=m)
    x_scalar = np.column_stack([rng.normal(0, 0.002, m), rng.normal(0, 0.05, m), trailing])
    x_seq = rng.normal(0, 0.004, size=(m, di.SEQ_LEN, len(di.CHANNELS))).astype(np.float32)
    y_vol = 0.8 * trailing + rng.normal(0, 0.3, size=m)
    y_return = rng.normal(0, 0.01, m)
    return di.Dataset(
        dates=dates[session_index],
        tickers=tickers,
        x_seq=x_seq,
        x_scalar=x_scalar,
        y_return=y_return,
        y_rank=di.rank_within(y_return, session_index),
        y_vol=y_vol,
        trailing_vol=trailing,
        sessions=dates,
        session_index=session_index,
    )


@dataclass(frozen=True)
class _Panel:
    """The two attributes `aligned_to_panel` reads."""

    dates: np.ndarray
    tickers: tuple[str, ...]


# The file round-trips every array, the metadata and the optional realized
# column; a file missing an array or with ragged lengths is refused.
def test_save_and_load_round_trip(tmp_path):
    dates = _dates(4)
    fc = vf.Forecasts(
        dates=np.array([dates[0], dates[1], dates[1], dates[3]]),
        tickers=np.array(["AAA", "AAA", "BBB", "BBB"]),
        forecast=np.array([np.nan, -7.5, -8.0, -7.0]),
        baseline=np.array([-7.6, -7.7, -8.1, -7.2]),
        realized=np.array([-7.4, -7.3, -8.2, -6.9]),
        meta={"model": "cnn", "fits": [{"n_train": 3}]},
    )
    path = vf.save_forecasts(tmp_path / "f" / "vol.npz", fc)
    back = vf.load_forecasts(path)
    assert len(back) == 4
    np.testing.assert_array_equal(back.dates, fc.dates)
    assert back.dates.dtype == np.dtype("datetime64[D]")
    np.testing.assert_array_equal(back.tickers, fc.tickers)
    np.testing.assert_array_equal(back.forecast, fc.forecast)
    np.testing.assert_array_equal(back.baseline, fc.baseline)
    np.testing.assert_array_equal(back.realized, fc.realized)
    assert back.meta == {"model": "cnn", "fits": [{"n_train": 3}]}
    assert back.row_selection == di.LEGACY_ROW_SELECTION
    # Without the realized column and metadata (a file written elsewhere).
    bare = tmp_path / "bare.npz"
    np.savez(
        bare,
        ticker=fc.tickers,
        date=fc.dates.astype("int64"),
        forecast=fc.forecast,
        baseline=fc.baseline,
    )
    loaded = vf.load_forecasts(bare)
    assert loaded.realized is None and loaded.meta is None
    assert loaded.row_selection == di.LEGACY_ROW_SELECTION
    np.savez(tmp_path / "short.npz", ticker=fc.tickers, date=fc.dates.astype("int64"))
    with pytest.raises(ValueError, match="lacks forecast arrays"):
        vf.load_forecasts(tmp_path / "short.npz")
    with pytest.raises(ValueError, match="one common length"):
        vf.save_forecasts(
            tmp_path / "ragged.npz",
            vf.Forecasts(fc.dates, fc.tickers, fc.forecast[:2], fc.baseline),
        )
    np.testing.assert_allclose(vf.sigma(np.log(0.0004)), 0.02)
    assert np.isnan(vf.sigma(np.nan))


# Invalid explicit declarations cannot silently acquire a valid producer meaning.
@pytest.mark.parametrize("selection", ["future-provenance", 1, []])
def test_invalid_forecast_row_selection_is_rejected(selection):
    values = np.zeros(1)
    forecasts = vf.Forecasts(
        _dates(1),
        np.array(["AAA"]),
        values,
        values,
        meta={"row_selection": selection},
    )
    with pytest.raises(ValueError, match="row_selection"):
        _ = forecasts.row_selection


# The dataset's row (name, t) targets the realized variance of the cube's
# session t + 1 and its baseline is the trailing 20 sessions through t -
# read from the bars, so the alignment rule below rests on the data, not
# on a comment.
def test_dataset_row_t_targets_session_t_plus_one():
    cubes, mask = _book("noise", names=2, n=40, seed=3)
    ds = di.dataset(cubes, mask, CAL)
    assert len(ds) > 0
    cube = cubes["N00"]
    realized = (bar_returns(cube) ** 2).sum(axis=1)
    days = cube.dates.astype("datetime64[D]")
    rows = np.flatnonzero(ds.tickers == "N00")
    for r in rows[:5]:
        i = int(np.searchsorted(days, ds.dates[r]))
        assert days[i] == ds.dates[r]
        assert ds.y_vol[r] == pytest.approx(math.log(realized[i + 1]))
        assert ds.trailing_vol[r] == pytest.approx(
            math.log(realized[i - di.TRAILING + 1 : i + 1].mean())
        )
        # Not the same session, and not two ahead.
        assert ds.y_vol[r] != pytest.approx(math.log(realized[i]))
        if i + 2 < len(realized):
            assert ds.y_vol[r] != pytest.approx(math.log(realized[i + 2]))


# Alignment: a row dated t lands at the panel position of t in the name's
# column, cells without a row are NaN, names and dates the panel lacks are
# dropped, a duplicate row is refused, and the aligned matrix shifted by
# one session is a different matrix (the decision at t reads the forecast
# made at t, never the one made at t + 1).
def test_align_puts_row_t_at_t_and_a_shift_differs():
    dates = _dates(6)
    fc = vf.Forecasts(
        dates=np.array([dates[1], dates[2], dates[3], dates[2], dates[4]]),
        tickers=np.array(["AAA", "AAA", "AAA", "BBB", "ZZZ"]),
        forecast=np.array([-7.0, -7.5, -8.0, -6.5, -1.0]),
        baseline=np.array([-7.1, -7.6, -8.1, -6.6, -1.1]),
        realized=np.array([-7.2, -7.7, -8.2, -6.7, -1.2]),
    )
    panel_dates = dates[:5]
    aligned = vf.align(fc, panel_dates, ("AAA", "BBB", "SPY"))
    assert aligned.forecast.shape == (5, 3)
    assert aligned.forecast[1, 0] == -7.0
    assert aligned.forecast[2, 0] == -7.5
    assert aligned.forecast[3, 0] == -8.0
    assert aligned.forecast[2, 1] == -6.5
    assert aligned.baseline[2, 1] == -6.6 and aligned.realized[2, 1] == -6.7
    assert np.isnan(aligned.forecast[0]).all() and np.isnan(aligned.forecast[:, 2]).all()
    assert np.isnan(aligned.forecast[4]).all()  # ZZZ is not on the panel
    assert aligned.coverage() == pytest.approx(4 / 15)
    # The shift test: reading the matrix one session late gives, for every
    # cell that has a forecast on both, a different value.
    shifted = np.roll(aligned.forecast, -1, axis=0)
    both = np.isfinite(aligned.forecast) & np.isfinite(shifted)
    assert both.any()
    assert (aligned.forecast[both] != shifted[both]).all()
    # A dataset row dated t is the forecast the allocator at decision t
    # reads: the aligned value at the panel index of t equals that row.
    for r in range(len(fc) - 1):
        t = int(np.searchsorted(panel_dates, fc.dates[r]))
        col = ("AAA", "BBB", "SPY").index(fc.tickers[r])
        assert aligned.forecast[t, col] == fc.forecast[r]
    duplicate = vf.Forecasts(
        dates=np.array([dates[1], dates[1]]),
        tickers=np.array(["AAA", "AAA"]),
        forecast=np.array([1.0, 2.0]),
        baseline=np.array([1.0, 2.0]),
    )
    with pytest.raises(ValueError, match="duplicate"):
        vf.align(duplicate, panel_dates, ("AAA",))
    with pytest.raises(ValueError, match="strictly increasing"):
        vf.align(fc, panel_dates[::-1], ("AAA",))
    empty = vf.align(vf.Forecasts(np.zeros(0, "datetime64[D]"), np.zeros(0, str), np.zeros(0), np.zeros(0)), panel_dates, ("AAA",))
    assert np.isnan(empty.forecast).all() and empty.realized is None


# The export walks the ridge forward on the volatility target and writes
# exactly `Forecast.values` (NaN before the first fit), the dataset's
# trailing baseline and its realized target, with the fits and the R² in
# the metadata; `aligned_to_panel` then reads the file onto a panel.
# Row-selection provenance and pending-label coverage survive the same real export.
def test_export_forecasts_with_the_ridge(tmp_path):
    ds = replace(
        _dataset(di.MIN_TRAIN + di.REFIT + 7, names=3, seed=1),
        row_selection=di.ROW_SELECTION,
    )
    ds.y_vol[-1] = np.nan
    dataset_file = di.save_dataset(tmp_path / "stage1.npz", ds, None)
    out = tmp_path / "vol" / "forecasts.npz"
    lines: list[str] = []
    meta = vf.export_forecasts(dataset_file, out, device="cpu", model="ridge", log=lines.append)
    assert out.exists()
    assert meta["model"] == "ridge" and meta["target"] == "vol" and meta["device"] == "cpu"
    assert meta["rows"] == len(ds)
    assert len(meta["fits"]) == 2
    assert meta["scored_rows"] == int((ds.session_index >= di.MIN_TRAIN).sum())
    assert meta["version"] == 2
    assert meta["row_selection"] == di.ROW_SELECTION
    assert meta["finite_forecast_rows"] == meta["scored_rows"]
    assert meta["observed_label_rows"] == len(ds) - 1
    assert meta["forecast_with_observed_label_rows"] == meta["scored_rows"] - 1
    assert meta["forecast_without_observed_label_rows"] == 1
    assert set(meta["vol_r2"]) == set(di.WINDOWS)
    assert any("wrote" in line for line in lines)
    fc = vf.load_forecasts(out)
    assert len(fc) == len(ds)
    assert fc.row_selection == di.ROW_SELECTION
    np.testing.assert_array_equal(fc.dates, ds.dates)
    np.testing.assert_array_equal(fc.tickers, ds.tickers)
    np.testing.assert_array_equal(fc.baseline, ds.trailing_vol)
    np.testing.assert_array_equal(fc.realized, ds.y_vol)
    before = ds.session_index < di.MIN_TRAIN
    assert np.isnan(fc.forecast[before]).all() and np.isfinite(fc.forecast[~before]).all()
    direct = di.walk_forward(ds, "ridge", "vol")
    np.testing.assert_array_equal(fc.forecast, direct.values)
    assert fc.meta["fits"][0]["test_start"] == direct.fits[0]["test_start"]
    panel = _Panel(ds.sessions, ("N00", "N02", "SPY"))
    aligned = vf.aligned_to_panel(out, panel)
    assert aligned.forecast.shape == (len(ds.sessions), 3)
    first = di.MIN_TRAIN
    row = np.flatnonzero((ds.session_index == first) & (ds.tickers == "N02"))[0]
    assert aligned.forecast[first, 1] == fc.forecast[row]
    assert np.isnan(aligned.forecast[:, 2]).all()
    assert np.isnan(aligned.forecast[first - 1]).all()


# The committed version-1 forecast file the vol-sizing and ML entry-level
# studies read still loads, reads as legacy-unrecorded and is not refused.
def test_committed_version_one_forecasts_still_load():
    path = (
        Path(__file__).resolve().parents[2]
        / "docs/research/scorecards/vol_forecasts.npz"
    )
    fc = vf.load_forecasts(path)
    assert fc.meta["version"] == 1
    assert "row_selection" not in fc.meta
    assert fc.row_selection == di.LEGACY_ROW_SELECTION
    assert len(fc) == fc.meta["rows"] > 0
    assert np.isfinite(fc.forecast).sum() == fc.meta["scored_rows"]


# The CLI writes the file and prints the R² lines; `--json` prints the
# summary; a missing dataset is exit 1.
def test_cli(tmp_path):
    ds = _dataset(di.MIN_TRAIN + 3, names=2, seed=2)
    dataset_file = di.save_dataset(tmp_path / "stage1.npz", ds, None)
    out_file = tmp_path / "forecasts.npz"
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        ["--dataset", str(dataset_file), "--out", str(out_file), "--device", "cpu", "--model", "ridge"]
    )
    assert cli.run(args, out) == 0
    text = out.getvalue()
    assert out_file.exists() and "R2 against trailing volatility" in text and "wrote" in text
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        ["--dataset", str(dataset_file), "--out", str(out_file), "--device", "cpu", "--model", "ridge", "--json"]
    )
    assert cli.run(args, out) == 0
    printed = json.loads(out.getvalue())
    assert printed["model"] == "ridge" and printed["rows"] == len(ds)
    assert printed["row_selection"] == di.LEGACY_ROW_SELECTION
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        ["--dataset", str(tmp_path / "missing.npz"), "--out", str(out_file)]
    )
    assert cli.run(args, out) == 1 and "not found" in out.getvalue()
    assert cli.build_parser().parse_args(["--dataset", "a", "--out", "b"]).device == "auto"


# The CNN export runs where torch is (one epoch, CPU) and writes finite
# forecasts after the first fit.
def test_export_forecasts_with_the_cnn(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(di, "_ANNOUNCED", set())
    monkeypatch.setitem(di.CNN_CONFIG, "epochs", 1)
    ds = _dataset(di.MIN_TRAIN + 3, names=2, seed=4)
    dataset_file = di.save_dataset(tmp_path / "stage1.npz", ds, None)
    out = tmp_path / "forecasts.npz"
    meta = vf.export_forecasts(dataset_file, out, device="cpu", model="cnn")
    assert meta["model"] == "cnn" and meta["parameters"] == 13058
    fc = vf.load_forecasts(out)
    after = ds.session_index >= di.MIN_TRAIN
    assert np.isfinite(fc.forecast[after]).all() and np.isnan(fc.forecast[~after]).all()
