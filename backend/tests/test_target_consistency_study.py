"""The small factorial runner exercises real simulation and strict benchmarks."""
# ruff: noqa: F811 - imported pytest fixture intentionally names test arguments

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import point_in_time
from backend.cli import market_target_consistency as study
from backend.market import stage3_overlay as so
from backend.market.session_anatomy import json_ready
from backend.tests.test_market_pit_scorecard import _report, history  # noqa: F401


def _inputs(history):
    report, mask = point_in_time.point_in_time(_report(), history)
    panel = report.panel
    n = len(panel.tickers)
    forecast = SimpleNamespace(
        kind="s1",
        dates=np.repeat(panel.dates, n),
        tickers=np.tile(panel.tickers, len(panel.dates)),
        yhat=np.tile(np.arange(n, dtype=float), len(panel.dates)),
    )

    # Stored benchmark bars, loaded and funded by the real strict loader.
    def read(symbol, asof=None):
        j = panel.index("SPY")
        bars = [
            SimpleNamespace(
                session_date=d.astype(object),
                adjusted_close=panel.adj_close[t, j],
                open=panel.open[t, j],
                close=panel.close[t, j],
            )
            for t, d in enumerate(panel.dates)
        ]
        return SimpleNamespace(bars=bars)

    return report, mask, forecast, SimpleNamespace(read=read)


def test_lagged_regimes_ignore_current_and_future_prices():
    prices = np.arange(1, 401, dtype=float)
    labels = study.lagged_trend(prices)
    assert (labels[:200] == "unknown").all()
    assert (labels[200:] == "up").all()
    prices[250:] = 0.5
    changed = study.lagged_trend(prices)
    np.testing.assert_array_equal(changed[:251], labels[:251])
    assert changed[251] == "down"


def test_factorial_run_matches_original_controls_and_recomputes_interaction(history):
    report, mask, forecast, store = _inputs(history)
    result = study.run(report, mask, forecast, store, offsets=1, costs=(25.0,))
    assert result["economic_check"]["status"] == "DO_NOT_PROMOTE"
    assert result["adoption_eligible"] is False
    saved = result["daily_at_middle_offset"][0]
    runs = {k: np.asarray(v) for k, v in saved["returns"].items()}
    assert set(runs) == set(study.ARMS) | {"SPY", "QQQ"}
    spans = so.windows(None)
    grid = so.align(forecast, report.panel).grid
    for line, name in ((so.CONTROL, "base"), (so.LINE, "ml")):
        old = so.price(
            report, mask, line, report.panel.dates[0].astype(object), 25.0, grid, spans
        )
        np.testing.assert_array_equal(runs[name], old.curve.daily)
    diff = ((runs["ml_gate"] - runs["base_gate"]) - (runs["ml"] - runs["base"]))[1:]
    row = next(
        p
        for p in result["paired"]
        if p["left"] == "interaction" and p["window"] == "all"
    )
    assert row["bp_per_session"] == pytest.approx(diff.mean() * 1e4)
    # SPY/QQQ incur a real initial entry fee, not a zero-cost normalized curve.
    panel = report.panel
    expected = panel.adj_close[1, -1] / (panel.open[1, -1] * 1.0025) - 1
    assert runs["SPY"][1] == pytest.approx(expected)
    assert json_ready(result)["daily_at_middle_offset"][0]["returns"]["SPY"][0] is None
    assert {r["regime"] for r in result["regimes"]} == {"up", "down", "unknown"}


def test_missing_benchmark_aborts_without_silent_flat_returns(history):
    report, mask, forecast, _ = _inputs(history)
    with pytest.raises(ValueError, match="no bars"):
        study.run(
            report,
            mask,
            forecast,
            SimpleNamespace(read=lambda *a: None),
            offsets=1,
            costs=(25.0,),
        )


def test_paired_missing_outcome_is_refused():
    with pytest.raises(ValueError, match="missing paired"):
        study.paired([0.1, np.nan])
