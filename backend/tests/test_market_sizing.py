"""Sizing: caps hold, volatility is targeted, turnover is controlled, costs bite."""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import sizing
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory


# A history from a return series.
def _history(ticker: str, returns: np.ndarray) -> TickerHistory:
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    first = date(2024, 1, 1)
    bars = tuple(
        DailyBar(first + timedelta(days=i), p, p * 1.01, p * 0.99, p, p, 1_000_000)
        for i, p in enumerate(prices)
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# Twenty names, two themes, one theme far more volatile than the other.
def _panel(t: int = 400, seed: int = 5):
    rng = np.random.default_rng(seed)
    n = 20
    vols = np.where(np.arange(n) % 2 == 0, 0.01, 0.03)
    drifts = np.linspace(-0.001, 0.002, n)
    returns = drifts[None, :] + rng.normal(0.0, 1.0, size=(t, n)) * vols[None, :]
    histories = {f"N{i:02d}": _history(f"N{i:02d}", returns[:, i]) for i in range(n)}
    histories["SPY"] = _history("SPY", returns.mean(axis=1))
    themes = {f"N{i:02d}": ("calm",) if i % 2 == 0 else ("wild",) for i in range(n)}
    return panel_from_histories(histories, "SPY", themes), drifts


# Caps hold, weights are non-negative for a long-only book, gross <= max.
def test_target_weights_respect_caps_and_gross():
    panel, drifts = _panel()
    config = sizing.SizingConfig(
        top_fraction=0.5, name_cap=0.15, theme_cap=0.6, target_volatility=1.0
    )
    scores = np.full(len(panel.tickers), np.nan)
    for i, ticker in enumerate(panel.tickers):
        if ticker != "SPY":
            scores[i] = drifts[int(ticker[1:])]
    vol = sizing.realised_volatility(panel, 60)[-1]
    weights = sizing.target_weights(scores, vol, panel.themes, panel.tickers, config)
    assert (weights >= 0).all()
    assert weights.max() <= config.name_cap + 1e-9
    for theme in ("calm", "wild"):
        members = [
            i for i, tk in enumerate(panel.tickers) if theme in panel.themes.get(tk, ())
        ]
        assert weights[members].sum() <= config.theme_cap + 1e-6
    assert weights.sum() <= config.max_gross + 1e-9
    # Calm names carry more weight per unit of selection than wild ones.
    calm = [
        i
        for i, tk in enumerate(panel.tickers)
        if tk != "SPY" and int(tk[1:]) % 2 == 0 and weights[i] > 0
    ]
    wild = [
        i
        for i, tk in enumerate(panel.tickers)
        if tk != "SPY" and int(tk[1:]) % 2 == 1 and weights[i] > 0
    ]
    assert weights[calm].mean() > weights[wild].mean()


# The volatility target scales the book down when it would be too risky.
def test_volatility_target_scales_the_book():
    panel, drifts = _panel()
    scores = np.full(len(panel.tickers), np.nan)
    for i, ticker in enumerate(panel.tickers):
        if ticker != "SPY":
            scores[i] = drifts[int(ticker[1:])]
    vol = sizing.realised_volatility(panel, 60)[-1]
    tight = sizing.SizingConfig(target_volatility=0.02, name_cap=1.0, theme_cap=1.0)
    loose = sizing.SizingConfig(target_volatility=5.0, name_cap=1.0, theme_cap=1.0)
    w_tight = sizing.target_weights(scores, vol, panel.themes, panel.tickers, tight)
    w_loose = sizing.target_weights(scores, vol, panel.themes, panel.tickers, loose)
    assert w_tight.sum() < 0.5 * w_loose.sum()
    assert abs(w_loose.sum() - 1.0) < 1e-9  # fully invested at most


# Turnover control: an exit is full, an entry moves at half speed, and
# tiny trades are skipped.
def test_rebalance_controls_turnover():
    held = np.array([0.5, 0.5, 0.0])
    target = np.array([0.0, 0.5, 0.5])
    config = sizing.SizingConfig(speed=0.5, min_trade=0.01)
    new, traded = sizing.rebalance(held, target, config)
    assert np.allclose(new, [0.0, 0.5, 0.25])
    assert abs(traded - 0.75) < 1e-12
    tiny = np.array([0.5, 0.5, 0.004])
    new2, traded2 = sizing.rebalance(
        held, tiny, sizing.SizingConfig(speed=1.0, min_trade=0.01)
    )
    assert np.allclose(new2, held)
    assert traded2 == 0.0


# A name the target drops is sold in full even when the sale is tiny, and
# the held book never exceeds the gross limit.
def test_exits_are_full_and_gross_is_bounded():
    held = np.array([0.004, 0.5, 0.496])
    target = np.array([0.0, 0.5, 0.5])
    new, traded = sizing.rebalance(
        held, target, sizing.SizingConfig(speed=0.5, min_trade=0.01)
    )
    assert new[0] == 0.0
    assert abs(traded - 0.004) < 1e-12
    panel, drifts = _panel(t=600)
    rng = np.random.default_rng(0)
    # A score that reshuffles every rebalance, the worst case for stale
    # positions.
    scores = rng.normal(size=(len(panel.dates), len(panel.tickers)))
    scores[:, panel.index("SPY")] = np.nan
    book = sizing.simulate(scores, panel, sizing.SizingConfig(rebalance_every=5))
    gross = np.abs(book.weights).sum(axis=1)
    assert gross.max() <= 1.0 + 1e-9


# A book on a score that knows the drift beats the same book on the
# reversed score, stays near its volatility target, and pays for turnover.
def test_simulation_rewards_a_known_drift_and_charges_cost():
    panel, drifts = _panel(t=600)
    scores = np.full((len(panel.dates), len(panel.tickers)), np.nan)
    for i, ticker in enumerate(panel.tickers):
        if ticker != "SPY":
            scores[:, i] = drifts[int(ticker[1:])]
    free = sizing.simulate(
        scores, panel, sizing.SizingConfig(cost_bps=0, rebalance_every=20)
    )
    paid = sizing.simulate(
        scores, panel, sizing.SizingConfig(cost_bps=50, rebalance_every=20)
    )
    reversed_book = sizing.simulate(
        -scores, panel, sizing.SizingConfig(cost_bps=0, rebalance_every=20)
    )
    assert free.rebalances >= 20
    assert free.annual_return > 0
    assert free.annual_return > reversed_book.annual_return + 0.05
    assert free.sharpe > reversed_book.sharpe
    assert free.annual_volatility < 0.15 * 1.5
    assert paid.annual_return < free.annual_return
    assert free.max_drawdown <= 0
    assert paid.mean_turnover > 0


# Today's positions come back sorted, capped, with the reason noted.
def test_size_today_reports_positions():
    panel, drifts = _panel()
    scores = np.full(len(panel.tickers), np.nan)
    for i, ticker in enumerate(panel.tickers):
        if ticker != "SPY":
            scores[i] = drifts[int(ticker[1:])]
    positions = sizing.size_today(scores, panel, sizing.SizingConfig(name_cap=0.08))
    assert positions
    assert positions[0].weight >= positions[-1].weight
    assert all(p.weight <= 0.08 + 1e-9 for p in positions)
    assert all(p.ticker != "SPY" for p in positions)
    assert any("cap" in p.note for p in positions)
