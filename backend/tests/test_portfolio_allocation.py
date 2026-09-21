"""The pure allocation decision, exercised on real module inputs.

This pins the fixed boundary behaviour of `desk.allocation.decide`: joint
weighted-return portfolio risk, the price-level (never last-return) trend, the
name and regime caps each applied once, a held position cut to a known event
cap when a desired stock lacks history, immunity to future rows, SPY entering
the target only when explicitly eligible, and the two second-review defects -
an empty `desired` targets all cash even with no diagnostics, and `vol_trend`
does not raise risk while its 200-session trend evidence is missing. Every
input here is a real price matrix and real weights; nothing is mocked.
"""

from datetime import date, timedelta

import numpy as np

from backend.agents.trading.desk.allocation import (
    BINDING_EVENT,
    BINDING_NONE,
    ENTRY_NAME_CAP,
    POLICY_VOL,
    POLICY_VOL_TREND,
    QQQ,
    SPY,
    decide,
)

BASE = date(2020, 1, 1)


# Consecutive session dates for a decision horizon.
def _dates(n: int) -> np.ndarray:
    """Return `n` consecutive datetime64[D] session dates from BASE."""
    return np.array([BASE + timedelta(days=i) for i in range(n)], dtype="datetime64[D]")


# Turn per-ticker simple-return series into a positive adjusted-close matrix.
def _prices(returns: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Return (T, N) positive prices and ticker order from return series."""
    tickers = list(returns)
    steps = len(next(iter(returns.values())))
    out = np.empty((steps + 1, len(tickers)))
    for col, name in enumerate(tickers):
        prices = np.empty(steps + 1)
        prices[0] = 100.0
        for row in range(steps):
            prices[row + 1] = prices[row] * (1.0 + returns[name][row])
        out[:, col] = prices
    return out, tickers


# Two stocks in exact opposition on top of SPY/QQQ at a fixed volatility.
def _hedge_matrix(n: int = 120) -> tuple[np.ndarray, list[str]]:
    """Return a matrix whose weighted joint return is identically zero."""
    pattern = np.where(np.arange(n - 1) % 2 == 0, 0.01, -0.01)
    return _prices({"AAA": pattern, "BBB": -pattern, SPY: pattern, QQQ: pattern})


# Verify diversification is measured from joint returns, including covariance.
def test_portfolio_risk_is_the_weighted_joint_return_not_a_sum_of_vols():
    # The two legs each carry real volatility but move in exact opposition, so
    # the weighted joint return is zero. The decision must report that joint
    # zero, not a weighted average of the two nonzero individual volatilities.
    prices, tickers = _hedge_matrix()
    t = len(prices) - 1
    d = decide(
        _dates(len(prices)),
        prices,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    assert d.available
    assert d.volatility is not None
    rets = prices[1:] / prices[:-1] - 1.0
    col_a, col_b = tickers.index("AAA"), tickers.index("BBB")
    joint = 0.1 * rets[:, col_a] + 0.1 * rets[:, col_b]
    expected = max(np.std(joint[-20:]), np.std(joint[-60:])) * np.sqrt(252)
    assert abs(d.volatility.portfolio_risk - expected) < 1e-12
    naive = (0.1 * np.std(rets[:, col_a]) + 0.1 * np.std(rets[:, col_b])) * np.sqrt(252)
    assert d.volatility.portfolio_risk != naive
    assert d.desired_weights == {"AAA": 0.1, "BBB": 0.1}


# Keep a down day in a rising market distinct from a bearish price trend.
def test_trend_ceiling_reads_price_levels_not_the_last_return():
    # Both benchmarks close above their 200-session price mean on a down day,
    # so the trend ceiling is full even though the last return is negative.
    n = 210
    t = n - 1
    p = 100.0 + 0.05 * np.arange(n)
    p[t] = p[t - 1] - 0.5
    prices = np.column_stack([p, p, p, p])
    tickers = ["AAA", "BBB", SPY, QQQ]
    assert prices[t, 2] / prices[t - 1, 2] - 1.0 < 0.0
    d = decide(
        _dates(n),
        prices,
        tickers,
        t,
        desired={"AAA": 0.05, "BBB": 0.05},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL_TREND,
    )
    assert d.available
    assert d.volatility is not None
    assert d.volatility.trend_ceiling == 1.0


# Bound individual stocks and aggregate equity without applying a cap twice.
def test_name_and_regime_caps_apply_once_each():
    prices, tickers = _hedge_matrix()
    t = len(prices) - 1
    dates = _dates(len(prices))
    # Names over the name cap are trimmed to it once; a full equity regime cap
    # adds no second scaling on top.
    full = decide(
        dates,
        prices,
        tickers,
        t,
        desired={"AAA": 0.5, "BBB": 0.5},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    assert full.desired_weights == {"AAA": ENTRY_NAME_CAP, "BBB": ENTRY_NAME_CAP}
    # A tight regime cap scales the already-name-capped names to it in one step
    # rather than applying the name cap a second time.
    tight = decide(
        dates,
        prices,
        tickers,
        t,
        desired={"AAA": 0.2, "BBB": 0.2},
        held={},
        regime_cap=0.2,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    assert tight.desired_weights == {"AAA": 0.1, "BBB": 0.1}
    assert sum(tight.desired_weights.values()) == 0.2


# Enforce known risk limits even when a proposed stock has no history.
def test_missing_stock_still_has_the_known_event_cap_enforced_on_held():
    # A desired stock with no history makes volatility unavailable, so the
    # decision starts from held and cuts it to the known event ceiling.
    prices = np.full((120, 4), np.nan)
    tickers = ["AAA", "BBB", SPY, QQQ]
    d = decide(
        _dates(120),
        prices,
        tickers,
        119,
        desired={"AAA": 0.3},
        held={"BBB": 0.4},
        regime_cap=1.0,
        event_cap=0.2,
        policy=POLICY_VOL,
    )
    assert not d.available
    assert d.desired_weights == {"BBB": 0.2}
    assert d.binding == BINDING_EVENT
    assert d.cash == 0.8
    assert any("AAA" in m for m in d.missing)


# Prove later observations cannot alter an earlier decision.
def test_future_rows_cannot_move_an_earlier_decision():
    prices, tickers = _hedge_matrix(n=150)
    t = 119
    base = decide(
        _dates(150),
        prices,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    future_changed = prices.copy()
    future_changed[t + 1 :] = 9999.0
    after_change = decide(
        _dates(150),
        future_changed,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    after_append = decide(
        _dates(300),
        np.vstack([prices, prices]),
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    for other in (after_change, after_append):
        assert other.desired_weights == base.desired_weights
        assert other.cash == base.cash
        assert other.available == base.available
        assert other.binding == base.binding
        assert other.reasons == base.reasons
        assert other.volatility == base.volatility


# Require explicit index eligibility before filling unused equity capacity.
def test_spy_fills_residual_capacity_only_when_explicitly_eligible():
    prices, tickers = _hedge_matrix()
    t = len(prices) - 1
    dates = _dates(len(prices))
    not_eligible = decide(
        dates,
        prices,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={},
        regime_cap=0.5,
        event_cap=1.0,
        policy=POLICY_VOL,
        index_eligible=False,
    )
    assert SPY not in not_eligible.desired_weights
    assert not_eligible.desired_weights == {"AAA": 0.1, "BBB": 0.1}
    eligible = decide(
        dates,
        prices,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={},
        regime_cap=0.5,
        event_cap=1.0,
        policy=POLICY_VOL,
        index_eligible=True,
    )
    assert eligible.desired_weights[SPY] == 0.3
    assert sum(eligible.desired_weights.values()) == 0.5


# Permit a cash target without inventing the evidence or fill needed to execute it.
def test_empty_desired_targets_all_cash_even_when_diagnostics_are_missing():
    # A deliberate zero-risk target is an exit, not a decision to hold: with no
    # SPY/QQQ risk evidence the decision still wants cash. Whether the position
    # can actually be sold without an execution price is execution's report.
    prices = np.full((120, 4), np.nan)
    tickers = ["AAA", "BBB", SPY, QQQ]
    d = decide(
        _dates(120),
        prices,
        tickers,
        119,
        desired={},
        held={"AAA": 0.15},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    assert not d.available
    assert d.desired_weights == {}
    assert d.cash == 1.0
    assert d.volatility is not None
    assert d.volatility.budget is None
    assert any(SPY in m for m in d.missing)
    assert any(QQQ in m for m in d.missing)


# Block new trend-policy risk on missing history while retaining known cuts.
def test_vol_trend_needs_the_full_trend_or_it_will_not_raise_risk():
    # 120 sessions give complete volatility but no 200-price trend. `vol_trend`
    # must not increase into AAA/BBB/SPY on missing trend evidence; `vol` alone
    # does not need the trend and still runs.
    prices, tickers = _hedge_matrix(n=120)
    t = len(prices) - 1
    dates = _dates(len(prices))
    trend_decision = decide(
        dates,
        prices,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={"AAA": 0.1},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL_TREND,
    )
    assert not trend_decision.available
    assert trend_decision.desired_weights == {"AAA": 0.1}
    assert trend_decision.binding == BINDING_NONE
    assert any("trend" in m for m in trend_decision.missing)
    vol_only = decide(
        dates,
        prices,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={"AAA": 0.1},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    assert vol_only.available
    # A known event ceiling still cuts held equity while the trend is missing.
    capped = decide(
        dates,
        prices,
        tickers,
        t,
        desired={"AAA": 0.1, "BBB": 0.1},
        held={"AAA": 0.1},
        regime_cap=1.0,
        event_cap=0.05,
        policy=POLICY_VOL_TREND,
    )
    assert not capped.available
    assert capped.desired_weights == {"AAA": 0.05}
    assert capped.binding == BINDING_EVENT
