"""Kronos K2: the predicted-path fill rule on hand-made cubes and books.

What has to hold (docs/research/kronos-plan-2026-09-30.md, Addendum 2):

- The level is t+1's open times the predicted low over the predicted open,
  clipped to [0.97, 0.99]: a predicted 2% dip waits for a 2% dip and fills
  there when the bars reach it, else at the official close; a predicted
  0.5% dip is the control's 1% level; a predicted 5% dip is capped at 3%.
- A cell without a forecast fills as the control and counts as
  `no_forecast`; the sell mirror reads the predicted high in [1.01, 1.03].
- A session whose t+1 is not a complete cube session is unpriced; every
  price is on the adjusted basis via `cube_scale`.
- The windows are the post-cutoff model window from 2024-07-01 and the
  contaminated window before it; the criteria are adaptive entry's six
  with criterion 3 on the contaminated window and the deflated Sharpe at
  N = 2.
- The k2 command runs end to end on a stub loader and CSV forecasts,
  writes the payload with per-order rows and prints a verdict line per
  candidate.
"""

from __future__ import annotations

import io as textio
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.market import kronos_fill as kf
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market.sip_cube import FULL_SESSION_SLOTS
from backend.tests.test_stage4_decisions import _session_cube
from backend.tests.test_stage4_labels import _agree, _cube, _dates, _series, _zigzag
from backend.tests.test_stage4_orders import _history, _report

SLOTS = FULL_SESSION_SLOTS
T = 60
t0 = 40


# A zigzag series with a cube whose session t0+1 follows `path` (26 bar
# closes, open = the first); returns (series, cube).
def _scene(path, split=None):
    dates = _dates(T)
    closes = _zigzag(T)
    raw = closes if split is None else closes * split
    cube = _cube(dates, raw, paths={t0 + 1: path})
    panel = closes if split is not None else _agree(closes, cube, dates)
    return _series(dates, panel), cube


# A (T,) ratio array with one value at t0.
def _ratio(value):
    out = np.full(T, np.nan)
    out[t0] = value
    return out


# A predicted 2% dip: the rule waits past the control's 1% bar and fills
# at the first bar closing 2% under the open; g > 0 for a buy.
def test_predicted_deeper_dip_fills_deeper():
    path = [100.0] * SLOTS
    path[5] = 98.9  # the control's bar
    path[12] = 97.9  # the 2% bar
    path[-1] = 99.5
    series, cube = _scene(path)
    fills = kf.name_fills(series, cube, _ratio(0.98), np.full(T, np.nan))
    control = fills[(kf.CONTROL, kf.BUY)]
    own = fills[(kf.KRONOS_LOW, kf.BUY)]
    assert control.price[t0] == pytest.approx(98.9) and control.slot[t0] == 5
    assert (
        own.price[t0] == pytest.approx(97.9) and own.slot[t0] == 12 and own.active[t0]
    )
    assert own.level_ratio[t0] == pytest.approx(0.98)
    assert lab.gain(control.price[t0], own.price[t0], "buy") > 0


# A predicted 2% dip the bars never reach fills at the official close.
def test_predicted_dip_not_reached_fills_at_the_close():
    path = [100.0] * SLOTS
    path[5] = 98.9
    path[-1] = 99.5
    series, cube = _scene(path)
    own = kf.name_fills(series, cube, _ratio(0.98), np.full(T, np.nan))[
        (kf.KRONOS_LOW, kf.BUY)
    ]
    assert (
        own.price[t0] == pytest.approx(99.5)
        and not own.reached[t0]
        and own.slot[t0] == -1
    )


# A shallow prediction is floored at the control's level; a deep one is
# capped at 3%.
def test_ratio_is_clipped_to_the_plan():
    np.testing.assert_allclose(
        kf.level_ratio(np.array([0.995, 0.98, 0.9, np.nan]), "buy"),
        [0.99, 0.98, 0.97, np.nan],
    )
    np.testing.assert_allclose(
        kf.level_ratio(np.array([1.002, 1.02, 1.1]), "sell"), [1.01, 1.02, 1.03]
    )
    path = [100.0] * SLOTS
    path[5] = 98.9
    path[20] = 96.9
    path[-1] = 99.5
    series, cube = _scene(path)
    shallow = kf.name_fills(series, cube, _ratio(0.995), np.full(T, np.nan))[
        (kf.KRONOS_LOW, kf.BUY)
    ]
    assert shallow.price[t0] == pytest.approx(98.9) and shallow.level_ratio[
        t0
    ] == pytest.approx(0.99)
    deep = kf.name_fills(series, cube, _ratio(0.9), np.full(T, np.nan))[
        (kf.KRONOS_LOW, kf.BUY)
    ]
    assert deep.price[t0] == pytest.approx(96.9) and deep.level_ratio[
        t0
    ] == pytest.approx(0.97)


# No forecast: the control's fill, not active, no level ratio.
def test_no_forecast_is_the_control():
    path = [100.0] * SLOTS
    path[5] = 98.9
    path[-1] = 99.5
    series, cube = _scene(path)
    fills = kf.name_fills(series, cube, np.full(T, np.nan), np.full(T, np.nan))
    own = fills[(kf.KRONOS_LOW, kf.BUY)]
    assert (
        own.price[t0] == pytest.approx(98.9)
        and not own.active[t0]
        and np.isnan(own.level_ratio[t0])
    )


# The sell mirror: a predicted 2% pop waits past the control's 1% bar.
def test_sell_mirror_reads_the_predicted_high():
    path = [100.0] * SLOTS
    path[4] = 101.1
    path[15] = 102.1
    path[-1] = 100.5
    series, cube = _scene(path)
    fills = kf.name_fills(series, cube, np.full(T, np.nan), _ratio(1.02))
    control = fills[(kf.CONTROL, kf.SELL)]
    own = fills[(kf.KRONOS_HIGH, kf.SELL)]
    assert control.price[t0] == pytest.approx(101.1) and own.price[t0] == pytest.approx(
        102.1
    )
    assert lab.gain(control.price[t0], own.price[t0], "sell") > 0


# A split between the raw cube and the panel: the fill is scaled.
def test_prices_are_on_the_adjusted_basis():
    path = [200.0] * SLOTS
    path[8] = 195.8  # 2.1% under the open on the 2x raw basis
    path[-1] = 199.0
    series, cube = _scene(path, split=2.0)
    own = kf.name_fills(series, cube, _ratio(0.98), np.full(T, np.nan))[
        (kf.KRONOS_LOW, kf.BUY)
    ]
    scale = lab.cube_scale(series, cube)[t0 + 1]
    assert own.price[t0] == pytest.approx(195.8 * scale) and own.reached[t0]


# A session without a complete t+1 is unpriced.
def test_missing_next_session_is_unpriced():
    dates = _dates(T)
    closes = _zigzag(T)
    cube = _cube(dates, closes, drop=(t0 + 1,))
    series = _series(dates, _agree(closes, cube, dates))
    fills = kf.name_fills(series, cube, _ratio(0.98), np.full(T, np.nan))
    assert np.isnan(fills[(kf.KRONOS_LOW, kf.BUY)].price[t0]) and np.isnan(
        fills[(kf.CONTROL, kf.BUY)].price[t0]
    )


# The windows: post-cutoff model, contaminated before.
def test_windows():
    w = kf.windows()
    assert w[kf.MODEL] == (date(2024, 7, 1), None) and w[kf.CONTAMINATED] == (
        date(2018, 1, 2),
        date(2024, 7, 1),
    )
    assert kf.TRIALS == {"registered": 2, "cumulative": 466}


# The k2 command end to end on a stub loader and CSV forecasts.
def test_command_end_to_end(tmp_path):
    from backend.cli import market_kronos_eval as cli

    report = _report()
    panel = report.panel
    rng = np.random.default_rng(11)
    cubes = {
        t: _session_cube(t, panel.dates, panel.close[:, j], rng)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    history = _history(tmp_path)
    forecasts = tmp_path / "k2"
    forecasts.mkdir()
    for t in cubes:
        pd.DataFrame(
            {
                "ticker": t,
                "date": panel.dates,
                "k2_low_rel_open": rng.uniform(0.96, 1.0, len(panel.dates)),
                "k2_high_rel_open": rng.uniform(1.0, 1.04, len(panel.dates)),
            }
        ).to_csv(forecasts / f"{t}.csv", index=False)

    def loader(store, workers, log):
        return report, cubes, {}

    out_path = tmp_path / "out" / "k2.json"
    args = cli.build_parser().parse_args(
        [
            "k2",
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--forecasts",
            str(forecasts),
            "--offsets",
            "20",
            "--max-offsets",
            "2",
            "--out",
            str(out_path),
        ]
    )
    text = textio.StringIO()
    assert cli.run_k2(args, out=text, loader=loader) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["study"] == kf.STUDY and payload["offsets"]["smoke"] is True
    assert payload["windows"][kf.MODEL] == ["2024-07-01", None] and payload["windows"][
        kf.CONTAMINATED
    ] == ["2018-01-02", "2024-07-01"]
    assert set(payload["results"]) == set(kf.CANDIDATES) == set(payload["deflated"])
    assert set(payload["rows"]["candidates"]) == set(kf.CANDIDATES)
    assert len(payload["run"]["inputs"]["forecasts"]["files"]) == len(cubes)
    for info in payload["verdict"]["candidates"].values():
        assert set(info["criteria"]) == {
            "1_floor",
            "2_next_bar",
            "3_not_negative_contaminated",
            "4_deflated_sharpe",
            "5_drift_adjusted",
            "6_offsets_positive",
        }
        assert info["label"] in (sd.REPLACES, sd.RECORD, sd.IMMATERIAL)
    printed = text.getvalue()
    assert (
        "K2_buy (kronos_low, buy)" in printed
        and "K2_sell (kronos_high, sell)" in printed
        and "SMOKE RUN" in printed
    )
    # The synthetic panel is 2023: the model window is empty and cannot pass.
    assert payload["verdict"]["replaces"] == []
    # The rows recompute: g of a priced buy is 1e4 ln(control / fill).
    rows = payload["rows"]
    k = rows["candidates"]["K2_buy"]
    for i, r in enumerate(k["rows"][:20]):
        if not k["unpriced"][i]:
            assert k["g_bp"][i] == pytest.approx(
                1e4 * np.log(rows["control"][r] / k["fill"][i]), abs=1e-6
            )


# The independent check script recomputes the smoke payload's numbers.
def test_check_script_passes_on_the_payload(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    from backend.cli import market_kronos_eval as cli

    report = _report()
    panel = report.panel
    rng = np.random.default_rng(5)
    cubes = {
        t: _session_cube(t, panel.dates, panel.close[:, j], rng)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    history = _history(tmp_path)
    forecasts = tmp_path / "k2"
    forecasts.mkdir()
    for t in cubes:
        pd.DataFrame(
            {
                "ticker": t,
                "date": panel.dates,
                "k2_low_rel_open": rng.uniform(0.96, 1.0, len(panel.dates)),
                "k2_high_rel_open": rng.uniform(1.0, 1.04, len(panel.dates)),
            }
        ).to_csv(forecasts / f"{t}.csv", index=False)
    out_path = tmp_path / "k2.json"
    args = cli.build_parser().parse_args(
        [
            "k2",
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--forecasts",
            str(forecasts),
            "--offsets",
            "20",
            "--max-offsets",
            "2",
            "--out",
            str(out_path),
        ]
    )
    assert (
        cli.run_k2(
            args,
            out=textio.StringIO(),
            loader=lambda store, workers, log: (report, cubes, {}),
        )
        == 0
    )
    # The synthetic panel is 2023: pretend the contaminated window is the model one by checking both.
    script = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "research"
        / "scorecards"
        / "kronos"
        / "kronos_check.py"
    )
    spec = importlib.util.spec_from_file_location("kronos_check", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main([str(out_path)]) == 0
    assert "independent check: PASS" in capsys.readouterr().out
