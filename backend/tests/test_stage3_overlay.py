"""The stage-3 T-S1 overlay: the /4 book without its worst-forecast decile.

What has to hold (docs/research/stage3-plan-2026-09-29.md, T-S1), under
the live executor:

- The drop count is ceil(0.1 n) from n = 5 candidates, none below.
- One session's targets: exactly the bottom decile of the names with a
  positive target and a forecast is dropped (ties: the lower column), the
  rest is the policy's equal weight over the reduced set under the 20% cap
  (bit for bit `point_in_time.graded_equal_weight_allocator` on the reduced
  mask), a name without a forecast is never dropped and is re-weighted,
  and with nothing dropped the policy's own targets come back untouched.
- The allocator reads row t alone.
- The forecast is placed at (ticker, t) on the panel; rows off the panel
  are counted; a duplicate is refused; a seed column reads that column.
- Under the live executor: the control is `profit_taking`'s ew-redeploy to
  the bit; an all-NaN forecast is the control exactly; a name dropped at
  every reset is never bought by a reset and is sold by one, and what the
  book still holds of it comes only from the executor's own mid-cycle
  breakout entry (measured); a name dropped only between resets is neither
  sold nor bought mid-cycle (no mid-cycle trims); the overlay passes the
  control's options and nothing else.
- The payload: windows start at the first forecast date, both lines per
  window and cost, paired rows with the excess moments, the drops, the
  reading; the command end to end with its refusals and seed runs.
"""

from __future__ import annotations

import io
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import grading, point_in_time, policy_v4, simulate
from backend.cli import market_pit_scorecard as sc
from backend.cli import market_stage3_overlay as cli
from backend.market import profit_taking as pt
from backend.market import stage3_io as s3
from backend.market import stage3_overlay as so
from backend.market import stage3_verdict as sv
from backend.market.midcycle_ew import REBALANCE, Ledger
from backend.tests.test_market_pit_scorecard import (  # noqa: F401 - fixture
    _report,
    history,
)

A_PLUS = grading.ORDINAL["A+"]
B = grading.ORDINAL["B"]


# The restricted fixture report, its mask and the second-session start.
def _book(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    return report, restricted, mask, sc._since(report.panel, 1)


# One session of `n` names and the benchmark (last): every name graded A+
# and priced at 100, `members` in the book; returns (target, mask row,
# grades, prices, benchmark column).
def _session(n: int, members, grades=None):
    grades_row = np.full(n + 1, A_PLUS) if grades is None else np.asarray(grades)
    grades_row[-1] = 0
    prices = np.full(n + 1, 100.0)
    mask_row = np.zeros(n + 1, dtype=bool)
    mask_row[list(members)] = True
    target = policy_v4.targets(grades_row, prices, mask_row, n)
    return target, mask_row, grades_row, prices, n


# A forecast row of `n` names and the benchmark: NaN except the given columns.
def _scores(n: int, values: dict[int, float]) -> np.ndarray:
    out = np.full(n + 1, np.nan)
    for j, v in values.items():
        out[j] = v
    return out


# The drop count: none under five candidates, then ceil(n / 10) - the plan's
# ceil(0.1 n) - checked against integer arithmetic.
def test_drop_count_is_the_plans_decile():
    assert (s3.S1_DROP_SHARE, s3.S1_MIN_NAMES) == (0.1, 5)
    assert [so.drop_count(n) for n in range(5)] == [0] * 5
    for n in range(5, 400):
        assert so.drop_count(n) == (n + 9) // 10, n
    assert so.drop_count(10) == 1 and so.drop_count(11) == 2 and so.drop_count(30) == 3


# One session's targets. Twelve names at 1/12: the two lowest forecasts go
# and the ten left take 0.1 each. Five names at the 20% cap: one goes and
# the four left stay at the cap, a fifth of the book in cash. Seven names,
# five with forecasts: the lowest forecast goes and the six left - the two
# without a forecast included - take 1/6. Four candidates: nothing changes
# (the very same array). Ties drop the lower column; a name with a forecast
# but no target (graded B, or out of the book) is no candidate; a NaN is
# no forecast; the benchmark never has weight.
def test_reduce_targets_drops_the_bottom_decile_and_respreads():
    target, mask_row, grades, prices, bench = _session(12, range(12))
    scores = _scores(12, {j: float(j) for j in range(12)})
    out, dropped, n = so.reduce_targets(target, scores, mask_row, grades, prices, bench)
    assert n == 12 and dropped.tolist() == [0, 1]
    np.testing.assert_array_equal(out[:2], 0.0)
    np.testing.assert_allclose(out[2:12], 0.1)
    assert out[bench] == 0.0 and out.sum() == pytest.approx(1.0)
    target, mask_row, grades, prices, bench = _session(5, range(5))
    np.testing.assert_allclose(target[:5], 0.2)
    out, dropped, n = so.reduce_targets(
        target,
        _scores(5, {0: 3.0, 1: -1.0, 2: 2.0, 3: 5.0, 4: 4.0}),
        mask_row,
        grades,
        prices,
        bench,
    )
    assert dropped.tolist() == [1]
    np.testing.assert_allclose(out, [0.2, 0.0, 0.2, 0.2, 0.2, 0.0])
    assert out.sum() == pytest.approx(0.8)
    target, mask_row, grades, prices, bench = _session(7, range(7))
    np.testing.assert_allclose(target[:7], 1.0 / 7.0)
    out, dropped, n = so.reduce_targets(
        target,
        _scores(7, {0: 1.0, 1: 2.0, 2: 0.5, 3: 4.0, 4: 5.0}),
        mask_row,
        grades,
        prices,
        bench,
    )
    assert (n, dropped.tolist()) == (5, [2])
    np.testing.assert_allclose(out[[0, 1, 3, 4, 5, 6]], 1.0 / 6.0)
    assert out[2] == 0.0
    four = _scores(7, {0: 1.0, 1: 2.0, 2: 0.5, 3: 4.0})
    out, dropped, n = so.reduce_targets(target, four, mask_row, grades, prices, bench)
    assert out is target and dropped.size == 0 and n == 4
    ties = _scores(7, {0: 1.0, 1: 1.0, 2: 3.0, 3: 4.0, 4: 5.0})
    assert so.reduce_targets(target, ties, mask_row, grades, prices, bench)[
        1
    ].tolist() == [0]
    graded_b = np.full(8, A_PLUS)
    graded_b[6] = B
    target, mask_row, grades, prices, bench = _session(7, range(7), graded_b)
    assert target[6] == 0.0
    scores = _scores(7, {6: -9.0, 0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0, 5: np.nan})
    out, dropped, n = so.reduce_targets(target, scores, mask_row, grades, prices, bench)
    assert (n, dropped.tolist()) == (5, [0])
    np.testing.assert_allclose(out[[1, 2, 3, 4, 5]], 0.2)
    assert out[6] == 0.0 and out[0] == 0.0
    target, mask_row, grades, prices, bench = _session(8, range(6))
    out, dropped, n = so.reduce_targets(
        target,
        _scores(8, {j: float(-j) for j in range(8)}),
        mask_row,
        grades,
        prices,
        bench,
    )
    assert (n, dropped.tolist()) == (6, [5])
    assert out[6] == 0.0 and out[7] == 0.0


# The re-spread is the policy's own equal weight on the reduced book: bit
# for bit `graded_equal_weight_allocator` (the arm policy_v4 reproduces) on
# the mask with the dropped names taken out, on random books.
def test_reduced_targets_are_the_graded_equal_weight_arm_on_the_reduced_mask():
    rng = np.random.default_rng(0)
    for _ in range(200):
        n = int(rng.integers(3, 40))
        grades = rng.choice([A_PLUS, grading.ORDINAL["A"], B], size=(1, n + 1))
        grades[0, -1] = 0
        prices = np.where(rng.random((1, n + 1)) < 0.05, np.nan, 100.0)
        mask = rng.random((1, n + 1)) < 0.8
        mask[0, -1] = False
        tickers = tuple(f"N{j}" for j in range(n)) + ("SPY",)
        panel = SimpleNamespace(
            adj_close=prices, tickers=tickers, benchmark="SPY", index=tickers.index
        )
        report = SimpleNamespace(graded=SimpleNamespace(grades=grades), panel=panel)
        scores = np.where(rng.random(n + 1) < 0.1, np.nan, rng.normal(size=n + 1))
        target = policy_v4.allocator(mask)(report, panel, None, 0)
        out, dropped, _ = so.reduce_targets(
            target, scores, mask[0], grades[0], prices[0], n
        )
        reduced = mask.copy()
        reduced[0, dropped] = False
        arm = point_in_time.graded_equal_weight_allocator(
            reduced, min_grade=grading.ORDINAL["A"], cap=policy_v4.HOLD_CAP, gross=1.0
        )(report, panel, None, 0)
        assert out.tobytes() == arm.tobytes()


# The allocator reads row t alone: rewriting every later forecast row and
# grade leaves its targets on t unchanged; it records the candidate count
# and the dropped columns per session asked about; a grid off the mask's
# shape is refused.
def test_overlay_allocator_reads_row_t_only():
    rng = np.random.default_rng(1)
    t_count, n = 30, 12
    tickers = tuple(f"N{j}" for j in range(n)) + ("SPY",)
    grades = np.full((t_count, n + 1), A_PLUS)
    grades[:, -1] = 0
    panel = SimpleNamespace(
        adj_close=np.full((t_count, n + 1), 100.0),
        tickers=tickers,
        benchmark="SPY",
        index=tickers.index,
    )
    report = SimpleNamespace(graded=SimpleNamespace(grades=grades), panel=panel)
    mask = np.ones((t_count, n + 1), dtype=bool)
    mask[:, -1] = False
    grid = rng.normal(size=(t_count, n + 1))
    overlay = so.Overlay(mask, grid)
    before = overlay.allocator(report, panel, None, 10)
    changed = grid.copy()
    changed[11:] = -changed[11:]
    grades2 = grades.copy()
    grades2[11:, :5] = B
    later = so.Overlay(mask, changed)
    report2 = SimpleNamespace(graded=SimpleNamespace(grades=grades2), panel=panel)
    assert later.allocator(report2, panel, None, 10).tobytes() == before.tobytes()
    assert overlay.calls[10][0] == 12 and len(overlay.calls[10][1]) == 2
    assert set(overlay.calls[10][1]) == set(np.argsort(grid[10, :n])[:2].tolist())
    with pytest.raises(ValueError, match="not the mask's"):
        so.Overlay(mask, grid[:, :3])


# The forecast placed on the panel: row (ticker, t) at cell [t, ticker],
# NaN elsewhere; a row whose date or ticker the panel lacks is counted and
# left out; the first date with a forecast; a seed column reads its own
# column; a duplicate row, a T-I forecast and a missing column are refused.
def test_align_places_rows_on_the_panel():
    panel = _report().panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    rows = [(dates[5], "AAA", 1.0), (dates[5], "BBB", 2.0), (dates[9], "EEE", -1.0)]
    rows += [(dates[9] + np.timedelta64(1000, "D"), "AAA", 5.0), (dates[7], "ZZZ", 3.0)]
    values = np.array([r[2] for r in rows], dtype=np.float32)
    forecast = s3.Stage3Forecast(
        kind=s3.S1,
        family=s3.LGBM,
        dates=np.array([r[0] for r in rows], dtype="datetime64[D]"),
        tickers=np.array([r[1] for r in rows]),
        slot=np.zeros(len(rows), dtype=np.int8),
        yhat=values,
        yhat_seeds=np.stack([values + s for s in range(5)], axis=1),
        yhat_configs=None,
        fold=np.zeros(len(rows), dtype=np.int32),
    )
    s1 = so.align(forecast, panel)
    assert (s1.rows, s1.placed, s1.off_panel) == (5, 3, 2)
    assert s1.first == dates[5].astype(object) and s1.seed_column is None
    grid = s1.grid
    assert np.isfinite(grid).sum() == 3
    assert grid[5, panel.index("AAA")] == 1.0 and grid[5, panel.index("BBB")] == 2.0
    assert grid[9, panel.index("EEE")] == -1.0
    seeded = so.align(forecast, panel, column=2)
    assert seeded.grid[5, panel.index("AAA")] == 3.0 and seeded.seed_column == 2
    with pytest.raises(ValueError, match="seed column"):
        so.align(forecast, panel, column=5)
    twice = s3.Stage3Forecast(
        **{
            **forecast.__dict__,
            "dates": np.concatenate([forecast.dates, forecast.dates[:1]]),
            "tickers": np.concatenate([forecast.tickers, forecast.tickers[:1]]),
            "slot": np.zeros(len(rows) + 1, dtype=np.int8),
            "yhat": np.concatenate([values, values[:1]]),
            "yhat_seeds": np.zeros((len(rows) + 1, 5), dtype=np.float32),
            "fold": np.zeros(len(rows) + 1, dtype=np.int32),
        }
    )
    with pytest.raises(ValueError, match="more than once"):
        so.align(twice, panel)
    with pytest.raises(ValueError, match="S1 forecast is needed"):
        so.align(s3.Stage3Forecast(**{**forecast.__dict__, "kind": s3.TI}), panel)
    empty = so.align(
        s3.Stage3Forecast(**{**forecast.__dict__, "yhat": values * np.nan}), panel
    )
    assert empty.first is None


# The control priced here is profit_taking's ew-redeploy to the bit, and an
# overlay whose forecast is all NaN drops nothing and is the control
# exactly: the same returns, the same turnover, the same diagnostics.
def test_all_nan_forecast_is_the_control_exactly(history):
    report, restricted, mask, since = _book(history)
    spans = so.windows(None)
    control = so.price(restricted, mask, so.CONTROL, since, 25.0, None, spans)
    reference = pt.price(restricted, mask, pt.variant(pt.CONTROL), since, 25.0)
    assert control.curve.daily.tobytes() == reference.curve.daily.tobytes()
    blank = np.full(mask.shape, np.nan)
    overlay = so.price(restricted, mask, so.LINE, since, 25.0, blank, spans)
    assert overlay.curve.daily.tobytes() == control.curve.daily.tobytes()
    assert all(dropped == () for _, dropped in overlay.calls.values())
    assert json.dumps(overlay.diagnostics, sort_keys=True, default=str) == json.dumps(
        control.diagnostics, sort_keys=True, default=str
    )
    with pytest.raises(ValueError, match="needs the forecast grid"):
        so.price(restricted, mask, so.LINE, since, 25.0, None, spans)
    with pytest.raises(ValueError, match="unknown line"):
        so.price(restricted, mask, "other", since, 25.0, blank, spans)


# The overlay passes simulate.run exactly the control's options - no
# weight_filter, no midcycle_trims - and only the allocator differs.
def test_overlay_runs_the_controls_options(history, monkeypatch):
    report, restricted, mask, since = _book(history)
    seen = []
    real = simulate.run

    # Record the keyword options of every run, then run it.
    def spy(report_, **kwargs):
        seen.append(kwargs)
        return real(report_, **kwargs)

    monkeypatch.setattr(simulate, "run", spy)
    grid = np.random.default_rng(2).normal(size=mask.shape)
    spans = so.windows(None)
    so.price(restricted, mask, so.CONTROL, since, 25.0, None, spans)
    so.price(restricted, mask, so.LINE, since, 25.0, grid, spans)
    expected = pt.control_options(restricted.panel)
    for kwargs in seen:
        options = {
            k: v
            for k, v in kwargs.items()
            if k not in ("since", "cost_bps", "allocator", "journal")
        }
        assert set(options) == set(expected)
        assert "weight_filter" not in kwargs and "midcycle_trims" not in kwargs
        assert options["midcycle_redeploy"] is True
    assert seen[0]["allocator"] is not seen[1]["allocator"]


# Run the fixture book under the control's options with an allocator and a
# fresh ledger; return the ledger.
def _ledger(restricted, since, allocator) -> Ledger:
    ledger = Ledger()
    options = pt.control_options(restricted.panel)
    ledger.exposure = options.get("event_exposure")
    simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=allocator,
        journal=ledger,
        **options,
    )
    return ledger


# A name's shares at every mark of a ledger, by session.
def _shares(ledger: Ledger, column: int) -> dict[int, float]:
    return {s: float(mark[1][column]) for s, mark in sorted(ledger.marks.items())}


# A name's mean weight at the marks of a ledger.
def _mean_weight(ledger: Ledger, closes: np.ndarray, column: int) -> float:
    return float(
        np.mean(
            [
                mark[1][column] * closes[s, column] / mark[2]
                for s, mark in ledger.marks.items()
                if mark[2] > 0
            ]
        )
    )


# The sessions whose mark shows a name's shares above (or below) the mark
# before, by the kind of decision that filled into them.
def _moves(ledger: Ledger, column: int, up: bool) -> list[tuple[int, str | None]]:
    shares = _shares(ledger, column)
    sessions = sorted(shares)
    return [
        (s, ledger.kinds.get(before))
        for before, s in zip(sessions[:-1], sessions[1:], strict=True)
        if (shares[s] > shares[before] if up else shares[s] < shares[before])
    ]


# Under the live executor. A name with the lowest forecast on every session
# is dropped at every reset: no reset buys it and a reset sells it, and the
# book holds far less of it than the control; what it still holds comes
# only from the executor's own mid-cycle breakout entry, which never reads
# the allocator (here the four names left sit at the 20% cap, so a fifth of
# the book is cash it can use), and `dropped_weight` measures it. A name
# with the lowest forecast only between resets is dropped from the
# redeploy's targets but never sold or bought mid-cycle: its holding
# changes only on the fill of a reset's decision.
def test_the_dropped_name_leaves_at_a_reset_and_is_never_trimmed_mid_cycle(history):
    report, restricted, mask, since = _book(history)
    panel = restricted.panel
    closes = np.asarray(panel.adj_close, dtype=float)
    aaa = panel.index("AAA")
    t_count, n = mask.shape
    base_grid = np.tile(np.arange(n, dtype=float) + 1.0, (t_count, 1))
    always = base_grid.copy()
    always[:, aaa] = -5.0
    control = _ledger(restricted, since, policy_v4.allocator(mask))
    overlay = so.Overlay(mask, always)
    ledger = _ledger(restricted, since, overlay.allocator)
    resets = sorted(s for s, kind in ledger.kinds.items() if kind == REBALANCE)
    assert len(resets) > 10
    assert resets == sorted(s for s, kind in control.kinds.items() if kind == REBALANCE)
    for t in resets:
        assert overlay.calls[t][1] == (aaa,)
    assert all(kind == "midcycle" for _, kind in _moves(ledger, aaa, up=True))
    assert all(kind == REBALANCE for _, kind in _moves(ledger, aaa, up=False))
    assert _mean_weight(ledger, closes, aaa) < 0.5 * _mean_weight(control, closes, aaa)
    priced = so.price(restricted, mask, so.LINE, since, 25.0, always, so.windows(None))
    assert min(priced.held_after_drop) == resets[0] + 1
    assert max(priced.held_after_drop) == max(ledger.marks)
    weights = {s: w for s, w in priced.held_after_drop.items()}
    for s, w in weights.items():
        mark = ledger.marks[s]
        assert w == pytest.approx(mark[1][aaa] * closes[s, aaa] / mark[2], abs=1e-15)
    stats = so.drop_stats(priced, panel.tickers)
    assert stats["resets"]["with_drops"] == stats["resets"]["sessions"] == len(resets)
    assert stats["dropped_at_resets"] == {"AAA": len(resets)}
    held = stats["held_after_reset_drop"]
    assert 0.0 < held["held_share"] < 0.2
    assert 0.0 < held["mean"] < held["max"] <= 0.2
    # Only between resets: the highest forecast at a reset, the lowest between.
    midcycle = base_grid.copy()
    midcycle[:, aaa] = 50.0
    for t in range(t_count):
        if t not in resets:
            midcycle[t, aaa] = -5.0
    overlay = so.Overlay(mask, midcycle)
    ledger = _ledger(restricted, since, overlay.allocator)
    moved = _moves(ledger, aaa, up=True) + _moves(ledger, aaa, up=False)
    assert moved
    assert all(kind == REBALANCE for _, kind in moved), moved
    assert all(overlay.calls[t][1] == (aaa,) for t in overlay.calls if t not in resets)
    assert all(aaa not in overlay.calls[t][1] for t in resets)


# The payload on the fixture: the model window starts at the first forecast
# date and its paired statistics cover every session from it to 2024; both
# lines on every window and cost; the paired rows carry the excess moments;
# the drops and the reading are there; the costs and offsets are recorded.
def test_run_overlay_payload(history):
    report, restricted, mask, since = _book(history)
    panel = restricted.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    grid = np.random.default_rng(4).normal(size=mask.shape)
    grid[:100] = np.nan
    grid[:, panel.index("SPY")] = np.nan
    s1 = so.S1Grid(
        grid=grid, rows=0, placed=0, off_panel=0, first=dates[100].astype(object)
    )
    payload = so.run_overlay(
        restricted, mask, s1, offsets=2, costs=(10.0, 25.0), candidate="s1_lgbm"
    )
    assert payload["windows"]["model"] == [str(dates[100]), "2024-01-01"]
    assert payload["candidate"] == "s1_lgbm" and payload["seed_column"] is None
    assert payload["costs_bps"] == [10.0, 25.0] and payload["verdict_cost_bps"] == 25.0
    assert len(payload["rows"]) == 2 * 4 * 2
    assert len(payload["paired"]) == 4 * 2
    in_model = int(
        ((dates >= dates[100]) & (dates < np.datetime64("2024-01-01"))).sum()
    )
    model = next(
        p for p in payload["paired"] if p["window"] == "model" and p["cost_bps"] == 25.0
    )
    assert model["sessions"] == in_model
    assert set(model["excess"]) == {"sharpe", "skew", "kurtosis", "length"}
    assert model["excess"]["length"] == in_model
    for row in payload["rows"]:
        assert row["line"] in so.LINES
        assert "cash_share" in row and "idle_target_share" in row
        if row["line"] == so.CONTROL:
            assert row["offsets_above_control"] == 0
    drops = payload["drops"]
    assert drops["resets"]["sessions"] > 0 and drops["resets"]["with_drops"] > 0
    assert sum(drops["dropped_at_resets"].values()) >= drops["resets"]["with_drops"]
    reading = payload["reading"]
    assert set(reading["floor"]) == {"10", "16", "25"}
    assert reading["floor"]["16"]["priced"] is False and not reading["passes_floor"]
    assert reading["offsets"] == 2 and not reading["passes_offsets"]
    # The overlay leaves more idle when the cap binds (five names at 20%).
    overlay_rows = [
        r for r in payload["rows"] if r["line"] == so.LINE and r["window"] == "model"
    ]
    control_rows = [
        r for r in payload["rows"] if r["line"] == so.CONTROL and r["window"] == "model"
    ]
    assert overlay_rows[0]["idle_target_share"] > control_rows[0]["idle_target_share"]
    with pytest.raises(ValueError, match="offsets"):
        so.run_overlay(restricted, mask, s1, offsets=0)


# The command end to end on the fixture: the payload at its default file
# with the forecast's path and sha256, the reading in the text; a seed run
# to its own file; `--out` and `--json`; a verdict read off the runs; and
# refused before the desk runs: a missing file, a T-I file, a seed column
# the file lacks.
def test_cli_end_to_end(history, tmp_path):
    import hashlib

    calls = []

    # The desk hook: the fixture report, recorded.
    def fake_desk(store):
        calls.append(str(store.root))
        return _report()

    panel = _report().panel
    rows = [(d, t) for d in panel.dates[60:] for t in panel.tickers if t != "SPY"]
    rng = np.random.default_rng(3)
    values = rng.normal(size=len(rows)).astype(np.float32)
    forecast = s3.Stage3Forecast(
        kind=s3.S1,
        family=s3.LGBM,
        dates=np.array([r[0] for r in rows], dtype="datetime64[D]"),
        tickers=np.array([r[1] for r in rows]),
        slot=np.zeros(len(rows), dtype=np.int8),
        yhat=values,
        yhat_seeds=np.stack([values * (1 + s) for s in range(5)], axis=1),
        yhat_configs=None,
        fold=np.zeros(len(rows), dtype=np.int32),
        meta={"model": "synthetic"},
    )
    path = s3.save_forecast(tmp_path / "s1_lgbm.npz", forecast)
    common = [
        "--forecast",
        str(path),
        "--root",
        str(tmp_path),
        "--membership",
        str(history),
        "--offsets",
        "2",
        "--costs",
        "25",
    ]
    out = io.StringIO()
    assert cli.run(cli.build_parser().parse_args(common), out, desk_run=fake_desk) == 0
    target = tmp_path / "desk" / "stage3_overlay_lgbm.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == so.STUDY and payload["candidate"] == "s1_lgbm"
    assert (
        payload["forecast"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert payload["forecast"]["file"] == str(path)
    assert payload["forecast"]["first_forecast_date"] == str(panel.dates[60])
    assert payload["windows"]["model"][0] == str(panel.dates[60])
    assert payload["forecast"]["off_panel"] == 0
    assert payload["options"]["midcycle_redeploy"] is True
    text = out.getvalue()
    assert "stage-3 T-S1 overlay s1_lgbm" in text and "this run's reading" in text
    seeds = []
    for k in range(5):
        out = io.StringIO()
        args = cli.build_parser().parse_args([*common, "--seed-column", str(k)])
        assert cli.run(args, out, desk_run=fake_desk) == 0
        seeds.append(
            json.loads(
                (tmp_path / "desk" / f"stage3_overlay_lgbm_seed{k}.json").read_text()
            )
        )
    assert seeds[2]["seed_column"] == 2 and seeds[2]["forecast"]["seed_column"] == 2
    record = sv.s1_verdict(payload, seeds=seeds)
    assert record["label"] == sv.RECORD
    assert record["seeds"]["complete"]
    out = io.StringIO()
    elsewhere = tmp_path / "other" / "overlay.json"
    args = cli.build_parser().parse_args([*common, "--out", str(elsewhere), "--json"])
    assert cli.run(args, out, desk_run=fake_desk) == 0
    assert json.loads(out.getvalue())["candidate"] == "s1_lgbm"
    assert elsewhere.exists()
    before = len(calls)
    ti = s3.Stage3Forecast(**{**forecast.__dict__, "kind": s3.TI})
    ti_path = s3.save_forecast(tmp_path / "ti.npz", ti)
    for extra, code, message in (
        (["--forecast", str(tmp_path / "none.npz")], 1, "not found"),
        (["--forecast", str(ti_path)], 2, "the overlay reads S1"),
        (["--forecast", str(path), "--seed-column", "9"], 2, "seed column 9"),
    ):
        out = io.StringIO()
        base_args = ["--root", str(tmp_path), "--membership", str(history)]
        assert (
            cli.run(
                cli.build_parser().parse_args([*base_args, *extra]),
                out,
                desk_run=fake_desk,
            )
            == code
        )
        assert message in out.getvalue()
    assert len(calls) == before
    assert math.isfinite(payload["reading"]["floor"]["25"]["bp"])
