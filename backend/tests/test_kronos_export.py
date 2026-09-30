"""The Kronos export's tables on a synthetic panel and cubes.

What has to hold (docs/research/kronos-plan-2026-09-30.md):

- The daily table carries the book names only (no benchmark), adjusted
  OHLC (the dividend factor on open/high/low), sessions with a close.
- The 15-minute table scales a cube's raw bars by `cube_scale` (the
  panel's adjusted close over the cube's official close), so a raw bar
  before a split lands on the adjusted basis; a cube session the panel
  lacks is left out.
- The cells are the graded, member (session, name) pairs from `since`
  on, with the next panel session's date (NaT on the last).
- The context coverage counts cells with 512 daily rows and 512 bars.
- The command writes the four tables and a summary with sha256s on a stub
  loader, in CSV where parquet is unavailable.
"""

from __future__ import annotations

import hashlib
import io as textio
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.market import kronos_export as ke
from backend.market.panel import Panel
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

NAMES = ("AAA", "BBB")
T = 40


# Weekday dates.
def _weekdays(n, start="2024-01-02"):
    return np.busday_offset(np.datetime64(start, "D"), np.arange(n), roll="forward")


# A two-name panel plus SPY with a dividend factor on AAA.
def _panel():
    dates = _weekdays(T)
    close = np.tile(np.array([100.0, 50.0, 400.0]), (T, 1)) + np.arange(T)[:, None]
    adj = close.copy()
    adj[:, 0] = close[:, 0] * 0.9  # AAA's dividend factor
    return Panel(
        dates=dates,
        tickers=NAMES + ("SPY",),
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        adj_close=adj,
        volume=np.full_like(close, 1e6),
        themes={t: ("ai",) for t in NAMES},
        benchmark="SPY",
    )


# A flat cube for one name on the given dates and official closes.
def _cube(ticker, dates, closes, split=1.0):
    n = len(dates)
    raw = np.asarray(closes, dtype=float) * split
    close = np.repeat(raw[:, None], FULL_SESSION_SLOTS, axis=1)
    return SessionCube(
        ticker=ticker,
        dates=np.asarray(dates),
        open=close.copy(),
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=np.ones((n, FULL_SESSION_SLOTS)),
        prior_close=np.r_[np.nan, raw[:-1]],
        excluded={},
        auction_open=raw.copy(),
        auction_volume=np.ones(n),
    )


# The inputs: grades everywhere but a gap, membership from session 5.
def _inputs():
    panel = _panel()
    grades = np.full((T, 3), 2, dtype=int)
    grades[10:12, 1] = -1
    grades[:, 2] = -1
    member = np.ones((T, 3), dtype=bool)
    member[:5, :] = False
    cubes = {
        "AAA": _cube("AAA", panel.dates[2:], panel.close[2:, 0], split=2.0),
        "BBB": _cube("BBB", panel.dates, panel.close[:, 1]),
    }
    return ke.Inputs(panel=panel, cubes=cubes, grades=grades, member=member)


# The daily table: book names, adjusted OHLC, the store's volume.
def test_daily_table_is_adjusted_and_book_only():
    daily = ke.daily_table(_inputs())
    assert list(daily.columns) == list(ke.DAILY_COLUMNS)
    assert set(daily["ticker"]) == set(NAMES)
    aaa = daily[daily["ticker"] == "AAA"].iloc[0]
    assert aaa["close"] == 90.0 and aaa["open"] == 99.0 * 0.9 and aaa["high"] == 102.0 * 0.9
    bbb = daily[daily["ticker"] == "BBB"].iloc[0]
    assert bbb["close"] == 50.0 and bbb["low"] == 48.0


# The 15-minute table: raw bars x cube_scale, 26 rows a session.
def test_bars_table_scales_onto_the_adjusted_basis():
    inputs = _inputs()
    bars = ke.bars_table(inputs)
    assert list(bars.columns) == list(ke.BARS_COLUMNS)
    aaa = bars[bars["ticker"] == "AAA"]
    assert len(aaa) == (T - 2) * FULL_SESSION_SLOTS
    first = aaa.iloc[0]
    # AAA's cube is on a 2x raw basis; the panel's adjusted close is 0.9 x close.
    assert first["close"] == pytest.approx(102.0 * 0.9)
    assert first["high"] == pytest.approx((2 * 102.0 + 0.5) * (102.0 * 0.9) / (2 * 102.0))
    assert first["slot"] == 0 and aaa.iloc[25]["slot"] == 25
    assert np.asarray(aaa["date"], dtype="datetime64[D]")[0] == inputs.panel.dates[2]


# The cells: graded and member, from since on, with the next session.
def test_cells_table():
    inputs = _inputs()
    since = inputs.panel.dates[3].astype(object)
    cells = ke.cells_table(inputs, since)
    assert list(cells.columns) == list(ke.CELLS_COLUMNS)
    assert cells["date"].min().to_datetime64().astype("datetime64[D]") == inputs.panel.dates[5]
    assert "SPY" not in set(cells["ticker"])
    bbb = cells[cells["ticker"] == "BBB"]
    assert set(bbb["session"]) == set(range(5, T)) - {10, 11}
    last = cells[cells["session"] == T - 1].iloc[0]
    assert pd.isna(last["next_date"])
    row = cells[(cells["session"] == 5) & (cells["ticker"] == "AAA")].iloc[0]
    assert row["next_date"].to_datetime64().astype("datetime64[D]") == inputs.panel.dates[6] and row["grade"] == 2


# The context coverage counts full contexts: 512 daily rows (none here,
# the panel is 40 sessions) and 512 bars (20 sessions of 26).
def test_context_coverage_counts_full_contexts():
    inputs = _inputs()
    daily, bars, cells = ke.daily_table(inputs), ke.bars_table(inputs), ke.cells_table(inputs, date(2024, 1, 1))
    cov = ke.context_coverage(daily, bars, cells)
    aaa = cells[cells["ticker"] == "AAA"]
    bbb = cells[cells["ticker"] == "BBB"]
    assert cov["cells"] == len(cells) and cov["k1_full_context"] == 0
    # AAA's cube starts at session 2, so its 20th session is 21; BBB's is 19.
    assert cov["k2_full_context"] == int((aaa["session"] >= 21).sum()) + int((bbb["session"] >= 19).sum()) == 40


# The command end to end on a stub loader, CSV format.
def test_command_writes_tables_and_summary(tmp_path):
    from backend.cli import market_kronos_export as cli

    inputs = _inputs()
    membership = tmp_path / "membership.csv"
    membership.write_text("ticker,entered\n")

    def loader(store, tickers, membership_path, desk_run, workers, log):
        log(f"stub {len(tickers)} names")
        return inputs

    out_dir = tmp_path / "export"
    args = cli.build_parser().parse_args(
        ["--root", str(tmp_path), "--out-dir", str(out_dir), "--membership", str(membership), "--format", "csv", "--since", "2024-01-09", "--tickers", "aaa,bbb"]
    )
    text = textio.StringIO()
    assert cli.run(args, out=text, loader=loader, desk_run=lambda store: None) == 0
    summary = json.loads((out_dir / "kronos_export.json").read_text())
    assert set(summary["files"]) == set(cli.TABLES)
    for name, info in summary["files"].items():
        path = out_dir / f"{name}.csv"
        assert path.exists() and info["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    cells = pd.read_csv(out_dir / "cells.csv")
    assert summary["files"]["cells"]["rows"] == len(cells) and cells["date"].min() == "2024-01-09"
    assert summary["contexts"] == {"daily": 512, "intraday": 512} and summary["horizons"] == {"daily": 20, "intraday": 26}
    assert summary["coverage"]["cells"] == len(cells)
    assert "stub 0 names" in text.getvalue()  # --tickers names outside the book


# A bad --since is refused before anything loads.
def test_bad_since_is_refused(tmp_path):
    from backend.cli import market_kronos_export as cli

    args = cli.build_parser().parse_args(["--root", str(tmp_path), "--since", "nope"])
    text = textio.StringIO()
    assert cli.run(args, out=text, loader=lambda *a, **k: None, desk_run=lambda s: None) == 2
