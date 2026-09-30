"""Kronos K1 and K3 on a synthetic panel.

What has to hold (docs/research/kronos-plan-2026-09-30.md, Addenda 1-2):

- A forecast frame lands on the panel's (T, N) grid at its (date, ticker),
  NaN elsewhere; a duplicate cell is refused.
- The arms are measured on the cells every arm scores; a score equal to
  the realised residual earns an IC near one, its negative near minus one,
  and the desk's score is paired against each.
- The post-cutoff window decides: fewer than 60 periods there is RECORD by
  construction whatever the IC; a passing IC without the book gate is
  still RECORD and says why.
- K3 appends K1's two columns to the stage-1 scalars on the rows that have
  a forecast and reports the paired daily-IC difference per window.
- The k1 command runs on a stub desk, records the forecast files' sha256s
  and writes the payload; the k3 command on a stub walk.
"""

from __future__ import annotations

import hashlib
import io as textio
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.market import kronos_eval as ke
from backend.market.panel import Panel

NAMES = tuple(f"N{i:02d}" for i in range(24))
T = 700


# Weekday dates from 2023-01-02.
def _dates(n, start=date(2023, 1, 2)):
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return np.array(out, dtype="datetime64[D]")


# A panel of 24 names plus SPY with random walks.
def _panel(seed=0):
    rng = np.random.default_rng(seed)
    n = len(NAMES)
    close = 100.0 * np.exp(rng.normal(0.0002, 0.02, size=(T, n + 1)).cumsum(axis=0))
    return Panel(
        dates=_dates(T),
        tickers=NAMES + ("SPY",),
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: ("ai",) for t in NAMES},
        benchmark="SPY",
    )


# A forecast frame from a (T, N) grid of values, one row per finite cell.
def _frame(panel, grid, column="k1_logret_20", mdd=None):
    t, j = np.nonzero(np.isfinite(grid))
    out = pd.DataFrame(
        {
            "ticker": np.asarray(panel.tickers)[j],
            "date": panel.dates[t],
            column: grid[t, j],
        }
    )
    out["k1_mdd"] = (mdd if mdd is not None else -np.abs(grid))[t, j]
    return out


# A frame lands at its cells; duplicates are refused.
def test_score_grid_places_cells():
    panel = _panel()
    frame = pd.DataFrame(
        {
            "ticker": ["N00", "N05", "ZZZ"],
            "date": [panel.dates[3], panel.dates[10], panel.dates[4]],
            "v": [1.0, 2.0, 3.0],
        }
    )
    grid = ke.score_grid(panel, frame, "v")
    assert grid[3, 0] == 1.0 and grid[10, 5] == 2.0 and np.isfinite(grid).sum() == 2
    with pytest.raises(ValueError, match="duplicate"):
        ke.score_grid(panel, pd.concat([frame, frame]), "v")


# The residual itself scores IC near +1; its negative near -1; the desk is paired.
def test_evaluate_k1_reads_a_perfect_score():
    panel = _panel()
    residual = panel.forward_residual(20)
    cells = np.ones(residual.shape, dtype=bool)
    cells[:, -1] = False
    noise = np.random.default_rng(4).normal(0, 0.02, size=residual.shape)
    grids = {"K1 return": residual + noise, "K1 drawdown": -residual + noise}
    desk = np.random.default_rng(1).normal(size=residual.shape)
    windows = {
        "in_window": (date(2023, 1, 2), date(2024, 6, 30)),
        "post_window": (date(2024, 7, 1), None),
    }
    payload = ke.evaluate_k1(panel, cells, grids, desk, windows=windows)
    post = payload["results"]["post_window"]
    assert (
        post["arms"]["K1 return"]["ic"] > 0.8
        and post["arms"]["K1 drawdown"]["ic"] < -0.8
    )
    assert post["arms"]["K1 return"]["periods"] == post["arms"][ke.DESK]["periods"]
    assert post["paired_vs_desk"]["K1 return"]["delta"] > 0.7
    # The post window here has 700 - ~390 sessions / 20 < 60 periods: RECORD by construction.
    assert payload["criteria"]["record_by_construction"] is True
    assert (
        payload["criteria"]["arms"]["K1 return"]["ic_clears"] is True
        and payload["criteria"]["arms"]["K1 return"]["passes"] is False
    )
    assert (
        payload["verdict"]["label"] == ke.RECORD
        and "by construction" in payload["verdict"]["reason"]
    )
    assert any("K1 post_window K1 return" in line for line in payload["lines"])


# With enough periods a passing IC is still RECORD without the book gate.
def test_k1_verdict_without_book_gate_is_record():
    criteria = {
        "arms": {
            "K1 return": {"enough_periods": True, "ic_clears": True, "passes": True}
        },
        "record_by_construction": False,
    }
    verdict = ke.k1_verdict(criteria)
    assert verdict["label"] == ke.RECORD and "book gate" in verdict["reason"]
    criteria["arms"]["K1 return"]["passes"] = False
    assert "no K1 arm" in ke.k1_verdict(criteria)["reason"]


# The paired difference is over common finite periods.
def test_paired():
    a = {"d1": 0.1, "d2": 0.2, "d3": float("nan"), "d4": 0.0}
    b = {"d1": 0.2, "d2": 0.4, "d3": 0.1, "d5": 0.3}
    p = ke.paired(a, b)
    assert p["periods"] == 2 and p["delta"] == pytest.approx(0.15)


# A tiny stage-1 dataset: 3 sessions x 4 names.
def _dataset():
    from backend.market import deep_intraday as di

    sessions = _dates(3)
    dates = np.repeat(sessions, 4)
    tickers = np.tile(np.array(["A", "B", "C", "D"]), 3)
    m = len(dates)
    return di.Dataset(
        dates=dates,
        tickers=tickers,
        x_seq=np.zeros((m, di.SEQ_LEN, len(di.CHANNELS)), dtype=np.float32),
        x_scalar=np.arange(m * 3, dtype=np.float32).reshape(m, 3),
        y_return=np.linspace(-0.01, 0.01, m),
        y_rank=np.linspace(0, 1, m),
        y_vol=np.zeros(m),
        trailing_vol=np.zeros(m),
        sessions=sessions,
        session_index=np.repeat(np.arange(3), 4),
    )


# K3 aligns K1's columns by (date, ticker), drops rows without one, and
# reports the marginal IC per window through the walk given.
def test_evaluate_k3_appends_the_features():
    ds = _dataset()
    frame = pd.DataFrame(
        {
            "date": ds.dates[:8],
            "ticker": ds.tickers[:8],
            "k1_logret_20": np.arange(8) * 0.1,
            "k1_mdd": -np.arange(8) * 0.01,
        }
    )
    from backend.market import deep_intraday as di

    seen = []

    def walk(sub, model, target, log=None):
        seen.append((sub.x_scalar.shape, model, target))
        return di.Forecast(
            model, target, sub.y_return + (0.001 if sub.x_scalar.shape[1] == 5 else 0.0)
        )

    windows = {"all": (None, None)}
    payload = ke.evaluate_k3(ds, frame, windows=windows, walk=walk)
    assert payload["rows"] == 8 and payload["rows_without_forecast"] == 4
    assert seen[0] == ((8, 3), "ridge", "rank") and seen[1] == ((8, 5), "ridge", "rank")
    assert set(payload["windows"]) == {"all"} and payload["lines"][0].startswith(
        "K3 all"
    )


# The k1 command on a stub desk: the payload, the sha256s, the lines.
def test_k1_command(tmp_path):
    from backend.cli import market_kronos_eval as cli

    panel = _panel()
    residual = panel.forward_residual(20)
    grid = residual + np.random.default_rng(2).normal(0, 0.05, size=residual.shape)
    forecasts = tmp_path / "k1"
    forecasts.mkdir()
    frame = _frame(panel, grid)
    frame[frame["ticker"].isin(NAMES[:12])].to_csv(forecasts / "part1.csv", index=False)
    frame[frame["ticker"].isin(NAMES[12:])].to_csv(forecasts / "part2.csv", index=False)
    (forecasts / "_run.json").write_text(
        json.dumps({"arm": "k1", "sampling": {"T": 1.0}})
    )
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(f"{t},2016-01-04,2016-01-04,,,test,member\n" for t in NAMES)
    )

    class Graded:
        grades = np.ones((T, len(NAMES) + 1), dtype=int)

    class Report:
        pass

    report = Report()
    report.panel = panel
    report.graded = Graded()
    report.scores = np.random.default_rng(3).normal(size=residual.shape)
    out_path = tmp_path / "out" / "k1.json"
    args = cli.build_parser().parse_args(
        [
            "k1",
            "--root",
            str(tmp_path),
            "--membership",
            str(membership),
            "--forecasts",
            f"K1={forecasts}",
            "--out",
            str(out_path),
        ]
    )
    text = textio.StringIO()
    assert cli.run_k1(args, out=text, desk_run=lambda store: report) == 0
    payload = json.loads(out_path.read_text())
    assert payload["arm"] == "K1" and payload["cutoff"] == "2024-06-30"
    assert set(payload["run"]["forecasts"]["K1"]["files"]) == {"part1.csv", "part2.csv"}
    assert (
        payload["run"]["forecasts"]["K1"]["files"]["part1.csv"]
        == hashlib.sha256((forecasts / "part1.csv").read_bytes()).hexdigest()
    )
    assert payload["run"]["forecasts"]["K1"]["run"] == {
        "arm": "k1",
        "sampling": {"T": 1.0},
    }
    post = payload["results"]["post_window"]["arms"]
    assert post["K1 return"]["ic"] > 0.5 and "VERDICT: RECORD" in text.getvalue()
    # A missing directory is refused before the desk runs.
    args = cli.build_parser().parse_args(
        [
            "k1",
            "--root",
            str(tmp_path),
            "--forecasts",
            f"K1={tmp_path / 'nope'}",
            "--out",
            str(out_path),
        ]
    )
    assert (
        cli.run_k1(
            args,
            out=textio.StringIO(),
            desk_run=lambda store: (_ for _ in ()).throw(AssertionError("ran")),
        )
        == 1
    )


# The independent check script recomputes a K1 payload's numbers.
def test_check_script_passes_on_k1_payload(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    panel = _panel()
    residual = panel.forward_residual(20)
    cells = np.ones(residual.shape, dtype=bool)
    cells[:, -1] = False
    noise = np.random.default_rng(6).normal(0, 0.05, size=residual.shape)
    payload = ke.evaluate_k1(
        panel,
        cells,
        {"K1 return": residual + noise, "K1 drawdown": -np.abs(residual) + noise},
        noise,
    )
    from backend.market import stage3_io as io

    path = tmp_path / "k1.json"
    path.write_text(json.dumps(io.clean_json(payload), allow_nan=False))
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
    assert module.main([str(path)]) == 0
    assert "independent check: PASS" in capsys.readouterr().out
