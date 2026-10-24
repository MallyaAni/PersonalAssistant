"""The account-faithful simulator behind the backtest, the charts and the live rule."""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import grade_led_leader_policy as leader
from backend.market import policy_book as pb

TICKERS = ("XXX", "YYY", "ZZZ", "SPY")


def _days(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _market(T=160, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(rng.normal(0.0005, 0.015, size=(T, len(TICKERS))).cumsum(axis=0))
    open_ = close * (1 + rng.normal(0, 0.003, size=close.shape))
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    band = np.zeros((T, len(TICKERS)), dtype=bool)
    return _days(T), open_, close, grades, band


def _run(grades, band=None, rule=None, T=160, seed=1, **kw):
    dates, open_, close, _, zero = _market(T, seed)
    return pb.simulate(
        dates, TICKERS, "SPY", open_, close, close.copy(), grades,
        zero if band is None else band, rule or pb.Rule(fomc=False), **kw
    )


# The defaults are the installed rule, so the backtest is the live policy.
def test_rule_defaults_are_the_installed_policy():
    rule = pb.Rule()
    policy = leader.GradeLedLeaderFundedPolicy
    assert rule.entry_grade == policy.entry_grade == 2
    assert rule.hold_grade == policy.minimum_held_grade == 1
    assert rule.min_trade == policy.min_trade
    assert (rule.floor, rule.target) == (leader.EXPOSURE_FLOOR, leader.TARGET)


# A name is sizable from its first full window, and never an index or the benchmark.
def test_sizable_starts_at_the_full_window():
    _, _, close, _, _ = _market()
    close[:10, 0] = np.nan
    mask = pb.sizable(close, TICKERS, "SPY")
    assert not mask[: 10 + leader.WINDOW, 0].any() and mask[10 + leader.WINDOW :, 0].all()
    assert mask[leader.WINDOW :, 1].all() and not mask[leader.WINDOW - 1, 1]
    assert not mask[:, 3].any()


# Bought when graded A, kept while B, sold at C; a name only ever B is never bought.
def test_entry_at_a_hold_at_b():
    T = 160
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    grades[80:91, 0] = 2
    grades[91:101, 0] = 1
    grades[:, 1] = 1
    book = _run(grades)
    x = [t for t in book.trades if t["ticker"] == "XXX"]
    assert x[0]["action"] == "BUY" and x[0]["decided"] == book.dates[80]
    assert x[0]["date"] == book.dates[81]
    assert (book.weights[81:102, 0] > 0).all() and (book.weights[102:, 0] == 0).all()
    assert x[-1]["action"] == "SELL" and x[-1]["decided"] == book.dates[101]
    assert not [t for t in book.trades if t["ticker"] == "YYY"]
    # Under the old B rule the B name is bought.
    old = _run(grades, rule=pb.Rule(fomc=False, entry_grade=1, hold_grade=1, min_trade=0))
    assert [t for t in old.trades if t["ticker"] == "YYY"]


# Whole shares, never more than the book, and every fill the session after its decision.
def test_fills_are_whole_shares_within_the_book():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    book = _run(grades, rule=pb.Rule(fomc=False, min_trade=0))
    assert book.trades
    for trade in book.trades:
        assert trade["shares"] == int(trade["shares"]) and trade["shares"] > 0
        assert book.dates.index(trade["date"]) == book.dates.index(trade["decided"]) + 1
    assert (book.weights.sum(axis=1) <= 1 + 1e-9).all()


# A resize under the minimum trade is not traded; an exit always is.
def test_min_trade_skips_small_resizes_not_exits():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    grades[120:, 2] = 0
    every = _run(grades, rule=pb.Rule(fomc=False, min_trade=0))
    banded = _run(grades, rule=pb.Rule(fomc=False, min_trade=0.01))
    assert len(banded.trades) < len(every.trades)
    exits = [t for t in banded.trades if t["ticker"] == "ZZZ" and t["action"] == "SELL"]
    assert exits and exits[-1]["target"] == 0
    for trade in banded.trades:
        if trade["target"] > 0 and trade["before"] > 0:
            assert trade["size"] >= 0.01 * 0.9


# Buys are funded from the cash on hand before the day's sells (the funded
# planner never spends same-day proceeds): on every session, what the buys
# cost with fees is within the cash the account opened the session with.
def test_buys_never_spend_same_day_sale_proceeds():
    T = 160
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    grades[64:100, :3] = 2
    grades[100:, 0] = 2
    grades[110:, 1:3] = 2
    book = _run(grades, rule=pb.Rule(fomc=False, min_trade=0))
    cost = pb.Rule().cost_bps / 1e4
    for t, day in enumerate(book.dates):
        buys = [x for x in book.trades if x["date"] == day and x["action"] == "BUY"]
        if not buys:
            continue
        spent = sum(x["shares"] * x["price"] for x in buys) * (1 + cost)
        assert spent <= book.cash_before[t] + 1e-6
    assert np.nanmin(book.cash) >= -1e-6


# The FOMC cycle: half of each holding sold at the next open after the first
# reduced close, nothing else traded through the lead-in, the baseline bought
# back at the decision session's close, the ordinary plan that night.
def test_fomc_cycle_matches_the_live_state_machine(monkeypatch):
    T = 160
    dates, open_, close, _, band = _market(T)
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    grades[:, :3] = 2
    factor = np.ones(T)
    factor[120:124] = 0.5
    decision = date.fromisoformat(dates[124])
    monkeypatch.setattr(pb.event_risk, "live_path", lambda panel: factor)
    monkeypatch.setattr(pb, "fomc_decisions", lambda: [decision])
    book = pb.simulate(dates, TICKERS, "SPY", open_, close, close.copy(), grades, band,
                       pb.Rule(min_trade=0))
    cuts = [t for t in book.trades if t.get("reason") == "fomc_reduction"]
    back = [t for t in book.trades if t.get("reason") == "fomc_restoration_decision_close"]
    assert cuts and {t["decided"] for t in cuts} == {dates[120]}
    assert {t["date"] for t in cuts} == {dates[121]}
    assert back and {t["date"] for t in back} == {dates[124]}
    assert all(t["timing"] == "decision_close" for t in back)
    between = [t for t in book.trades if dates[121] < t["date"] < dates[124]]
    assert between == []
    for cut in cuts:
        restored = next(t for t in back if t["ticker"] == cut["ticker"])
        assert restored["shares"] == cut["shares"]
    after = [t for t in book.trades if t["decided"] == dates[124] and not t.get("reason")]
    assert all(t["date"] == dates[125] for t in after)


# Tonight's plan after the last close is reported for the chart's current call.
def test_tonights_plan_is_reported():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    book = _run(grades)
    assert book.planned is not None and book.planned.shape == (len(TICKERS),)
    assert book.planned[3] == 0 and book.planned[:3].sum() == pytest.approx(
        book.planned.sum()
    )
