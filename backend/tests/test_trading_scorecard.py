"""The scorecard's arithmetic.

What has to hold: yearly totals compound the daily series within each
calendar year; the table matches every candidate to the rule's
volatility and flags a drawdown outside the loss limit; and the
year-by-year lines count the years a candidate beat the rule.
"""

import numpy as np
import pytest

from backend.agents.trading.desk import scorecard
from backend.agents.trading.desk.simulate import SimResult


def _result(daily, start="2024-01-01"):
    dates = (np.datetime64(start) + np.arange(len(daily))).astype("datetime64[D]")
    equity = 100.0 * np.cumprod(1.0 + daily)
    return SimResult(
        dates=dates,
        returns=daily,
        invested=np.ones(len(daily)),
        equity=equity,
        traded=float(equity.mean()),
        top_weight=np.full(len(daily), 0.1),
    )


def test_yearly_compounds_within_each_year():
    dates = np.array(["2024-12-30", "2024-12-31", "2025-01-02"], dtype="datetime64[D]")
    daily = np.array([0.01, 0.01, -0.02])
    out = scorecard.yearly(dates, daily)
    assert out[2024] == pytest.approx(1.01 * 1.01 - 1.0)
    assert out[2025] == pytest.approx(-0.02)


def test_render_matches_to_the_rules_volatility_and_flags_the_limit():
    rng = np.random.default_rng(1)
    rule = _result(rng.normal(0.0008, 0.01, size=504))
    risky = _result(rng.normal(0.0016, 0.02, size=504))
    text = scorecard.render({"the rule": rule, "risky": risky}, loss_limit=0.05)
    lines = text.splitlines()
    assert lines[0].startswith("candidate")
    assert "the rule" in lines[1]
    assert "risky" in lines[2]
    # The rule at its own volatility is itself; risky is matched by scaling
    # its daily returns to the rule's volatility and compounding them.
    rule_stats, risky_stats = rule.stats(), risky.stats()
    matched = scorecard.matched_at_volatility(risky.returns, rule_stats["volatility"])
    assert f"{matched:+.1%}" in lines[2]
    assert lines[2].rstrip().endswith("NO") or lines[2].rstrip().endswith("yes")
    assert "beats the rule in" in text


def test_matched_volatility_compounds_the_scaled_returns():
    # A violent alternating series: its compounded rate carries a huge
    # variance drag, so scaling the volatility must compound the scaled
    # daily returns, not scale the compounded rate linearly.
    daily = np.array([0.02, -0.01] * 252)
    own = _result(daily).stats()
    half = scorecard.matched_at_volatility(daily, own["volatility"] / 2.0)
    # With the volatility halved, the scaled days are +1% / -0.5%, whose
    # pair product is 1.00495 for 126 pairs over the two years.
    assert half == pytest.approx(1.00495**126 - 1.0, rel=1e-6)
    # The linear scaling of the compounded rate would overstate it badly.
    linear = own["cagr"] * 0.5
    assert half != pytest.approx(linear, rel=1e-2)
