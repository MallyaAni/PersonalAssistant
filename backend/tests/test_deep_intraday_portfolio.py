"""The stage-1 top-quintile portfolio averages simple returns under turnover costs.

An equal-weight book earns the mean of its names' simple returns, so the
log returns the dataset stores are converted before averaging. Costs keep
the structure the study always had: each book - the top quintile and the
equal-weight hurdle - pays the one-way cost on its turnover against its own
previous session's holdings, so a book that rotates every day pays more
than one that holds still. Every portfolio summary, including the ones
stage 2 reuses, names this accounting.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.market import deep_intraday as di
from backend.market import deep_stage2 as stage2


# Build a small, complete forecast panel from observed session opens and closes.
def _dataset(opens: np.ndarray, closes: np.ndarray) -> di.Dataset:
    sessions, names = opens.shape
    dates = np.busday_offset("2020-01-06", np.arange(sessions))
    rows = sessions * names
    returns = np.log(closes / opens).reshape(-1)
    return di.Dataset(
        dates=np.repeat(dates, names),
        tickers=np.tile([f"N{j:02d}" for j in range(names)], sessions),
        x_seq=np.zeros((rows, di.SEQ_LEN, len(di.CHANNELS)), dtype=np.float32),
        x_scalar=np.zeros((rows, len(di.SCALARS))),
        y_return=returns,
        y_rank=np.zeros(rows),
        y_vol=np.zeros(rows),
        trailing_vol=np.zeros(rows),
        sessions=dates,
        session_index=np.repeat(np.arange(sessions), names),
    )


# +100% and -50% average to +25% as simple returns; their log returns
# average to zero, which is what the portfolio used to report.
def test_books_average_simple_returns_not_log_returns():
    opens = np.full((2, 10), 100.0)
    closes = opens.copy()
    closes[:, :2] = [200.0, 50.0]
    ds = _dataset(opens, closes)
    forecast = np.tile(np.arange(10, 0, -1, dtype=float), len(opens))
    result = di.top_quantile_portfolio(ds, forecast, 0.0)
    top = (ds.tickers == "N00") | (ds.tickers == "N01")
    assert ds.y_return[top].mean() == pytest.approx(0.0, abs=1e-15)
    np.testing.assert_allclose(result.portfolio_gross, [0.25, 0.25])
    np.testing.assert_allclose(result.hurdle_gross, [0.05, 0.05])
    np.testing.assert_allclose(result.portfolio, result.portfolio_gross)
    np.testing.assert_allclose(result.difference().values, [0.20, 0.20])


# Each book pays cost x its own turnover against its previous session: a
# top book rotating to a new name every day pays two-way turnover daily
# while the hurdle, holding every name, pays only to enter; a top book that
# keeps its pick pays the same as the hurdle.
@pytest.mark.parametrize("cost_bps", [10.0, 25.0])
def test_rotating_top_book_pays_more_turnover_cost_than_the_static_hurdle(cost_bps):
    opens = np.full((3, 5), 100.0)
    ds = _dataset(opens, opens)
    cost = cost_bps / di.BP
    rotating = np.concatenate([np.eye(5)[day] for day in range(3)])
    result = di.top_quantile_portfolio(ds, rotating, cost_bps)
    np.testing.assert_allclose(result.portfolio_gross, 0.0, atol=1e-15)
    np.testing.assert_allclose(result.turnover, [1.0, 2.0, 2.0])
    np.testing.assert_allclose(result.portfolio, -cost * np.array([1.0, 2.0, 2.0]))
    np.testing.assert_allclose(result.hurdle, -cost * np.array([1.0, 0.0, 0.0]))
    np.testing.assert_allclose(
        result.difference().values, -cost * np.array([0.0, 2.0, 2.0])
    )
    static = di.top_quantile_portfolio(ds, np.tile(np.arange(5.0), 3), cost_bps)
    np.testing.assert_allclose(static.turnover, [1.0, 0.0, 0.0])
    np.testing.assert_allclose(static.difference().values, 0.0, atol=1e-15)


# Both stages' payloads name the portfolio accounting and carry its numbers:
# on flat prices each book pays 25 bp once, on its first session of three.
def test_stage_summaries_identify_the_simple_return_accounting():
    opens = np.full((3, 5), 100.0)
    ds = _dataset(opens, opens)
    forecast = di.Forecast("ridge", "rank", np.tile(np.arange(5.0), 3))
    payload = di.study(ds, {("ridge", "rank"): forecast}, cost_bps=25.0)
    assert payload["version"] == di.STUDY_VERSION == 3
    ds2 = stage2.Dataset2(
        dates=ds.dates,
        tickers=ds.tickers,
        x_seq=ds.x_seq,
        x_scalar=ds.x_scalar,
        scalar_names=di.SCALARS,
        y_return=ds.y_return,
        y_rank=ds.y_rank,
        y_downgrade20=np.zeros(len(ds)),
        y_drawdown20=np.zeros(len(ds)),
        y_vol20=ds.y_vol,
        trailing_vol20=ds.trailing_vol,
        fwd20=np.zeros(len(ds)),
        grade=np.full(len(ds), stage2.A_MIN_GRADE),
        sessions=ds.sessions,
        session_index=ds.session_index,
        k=di.K_SESSIONS,
        benchmarks=(),
        benchmark_fill=0,
    )
    stage2_result = stage2.evaluate(ds2, forecast, None, cost_bps=25.0)
    for summary in (
        payload["results"][0]["portfolio"],
        stage2_result["portfolio"],
        stage2_result["portfolio_a"],
    ):
        assert summary["accounting"] == di.PORTFOLIO_ACCOUNTING
        assert summary["accounting"] == "simple-mean-turnover-cost/2"
        assert summary["return_basis"] == "simple"
        assert summary["portfolio_bp"] == pytest.approx(-25.0 / 3)
        assert summary["hurdle_bp"] == pytest.approx(-25.0 / 3)
        assert summary["mean_bp"] == pytest.approx(0.0, abs=1e-12)
