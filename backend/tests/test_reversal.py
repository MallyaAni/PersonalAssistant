"""The post-decision reversal: basket, window arithmetic, the bar, the shadow.

What has to hold: the basket is the worst decile by the five-session
return with at least five names and never the benchmark; a meeting's
return runs from the next open to the close ten sessions after entry,
adjusted for splits and for beta times SPY, with costs both ways; the
verdict follows the registered bar; the shadow opens a cycle on a
decision close, fills the entry the next session and closes at the exit.
"""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from backend.market import reversal
from backend.market.panel import Panel


def _panel(
    t: int = 60,
    n: int = 12,
    seed: int = 0,
    drift: np.ndarray | None = None,
    start: str = "2026-06-01",
) -> Panel:
    rng = np.random.default_rng(seed)
    dates = np.array(
        [np.datetime64(start) + np.timedelta64(i, "D") for i in range(t)],
        dtype="datetime64[D]",
    )
    steps = rng.normal(0, 0.01, size=(t, n + 1))
    if drift is not None:
        steps = steps + drift
    close = 100 * np.cumprod(1 + steps, axis=0)
    return Panel(
        dates=dates,
        tickers=tuple(f"N{i}" for i in range(n)) + ("SPY",),
        open=close * 0.995,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close.copy(),
        volume=np.full_like(close, 1e6),
        themes={},
        benchmark="SPY",
    )


def test_basket_is_the_worst_decile_with_a_floor_and_never_the_benchmark():
    p = _panel(n=40)
    t = 30
    # Make N3 and N7 the worst into t, and SPY the worst of all.
    p.adj_close[t, 3] = p.adj_close[t - 5, 3] * 0.5
    p.adj_close[t, 7] = p.adj_close[t - 5, 7] * 0.6
    p.adj_close[t, 40] = p.adj_close[t - 5, 40] * 0.1
    cols = reversal.basket(p, t)
    assert len(cols) == 5  # ceil(40 * 0.1) = 4, floored to five
    assert cols[:2] == [3, 7]
    assert 40 not in cols
    assert reversal.basket(_panel(n=3), 30) == []


def test_meeting_window_prices_costs_and_beta():
    p = _panel(n=10)
    t = 30
    row = reversal.meeting(p, t)
    assert row["entry"] == str(p.dates[t + 1])
    assert row["exit"] == str(p.dates[t + 10])
    cols = [p.tickers.index(n) for n in row["names"]]
    opens = reversal.adjusted_open(p)
    expected = float(np.mean(p.adj_close[t + 10, cols] / opens[t + 1, cols] - 1))
    assert abs(row["basket_raw"] - expected) < 1e-12
    assert abs(row["after_costs"]["30"] - (row["adjusted"] - 0.006)) < 1e-12
    assert abs(row["after_costs"]["10"] - (row["adjusted"] - 0.002)) < 1e-12
    assert abs(row["book_contribution_30bp"] - 0.1 * row["after_costs"]["30"]) < 1e-12
    assert reversal.meeting(p, len(p.dates) - 3) is None  # exit beyond the panel


def test_a_split_does_not_create_a_return():
    p = _panel(n=10)
    t = 30
    # A 2-for-1 split at t+5 on every name: raw prices halve, adjusted do not.
    p.close[t + 5 :] /= 2
    p.open[t + 5 :] /= 2
    row_split = reversal.meeting(p, t)
    row_plain = reversal.meeting(_panel(n=10), t)
    assert abs(row_split["basket_raw"] - row_plain["basket_raw"]) < 1e-12


def test_verdict_follows_the_registered_bar():
    good = [{"after_costs": {"30": 0.03 + 0.01 * i}, "deep": True} for i in range(12)]
    bad = [{"after_costs": {"30": -0.04 - 0.01 * i}, "deep": False} for i in range(12)]
    v = reversal.verdict(good + bad[:3])
    assert v["primary_passed"]
    assert "unconditional" in v["standing"]
    v = reversal.verdict(good[:8] + bad)
    assert not v["primary_passed"]
    assert v["secondary_passed"]
    assert "depth condition" in v["standing"]
    v = reversal.verdict(bad)
    assert "insufficient evidence" in v["standing"]


def test_shadow_opens_fills_and_closes_a_cycle(tmp_path):
    p = _panel(n=10, t=30, start="2026-09-10")
    decision = p.dates[12].astype(object)
    # The decision is on the panel but nothing after it yet.
    short = replace(
        p,
        dates=p.dates[:13],
        open=p.open[:13],
        high=p.high[:13],
        low=p.low[:13],
        close=p.close[:13],
        adj_close=p.adj_close[:13],
        volume=p.volume[:13],
    )
    ledger = reversal.observe(tmp_path, short, [decision])
    assert len(ledger["cycles"]) == 1
    cycle = ledger["cycles"][0]
    assert cycle["status"].startswith("awaiting entry")
    assert cycle["entry"] is None
    # The next session fills the entry at its open.
    ledger = reversal.observe(tmp_path, p, [decision])
    cycle = ledger["cycles"][0]
    assert cycle["entry"]["session"] == str(p.dates[13])
    assert cycle["status"] == "closed"  # the full panel reaches the exit
    assert cycle["exit"]["session"] == str(p.dates[22])
    assert ledger["summary"]["closed"] == 1
    # A second observation does not duplicate the cycle.
    again = reversal.observe(tmp_path, p, [decision])
    assert len(again["cycles"]) == 1
    assert reversal.load(tmp_path)["cycles"][0]["decision"] == decision.isoformat()


def test_decisions_before_the_shadow_start_are_not_opened(tmp_path):
    p = _panel(n=10, t=30)
    early = date(2026, 6, 10)
    assert early == p.dates[9].astype(object)
    ledger = reversal.observe(tmp_path, p, [early])
    assert ledger["cycles"] == []
    assert reversal.observe(tmp_path, p, [early + timedelta(days=0)])["cycles"] == []


# The any-day form: an episode opens on a session where the worst decile
# is at or below the depth threshold, and no new episode opens while one
# is still holding.
def test_any_day_episodes_open_on_deep_selloffs_and_do_not_overlap():
    p = _panel(n=20, t=80, start="2024-01-01")
    # Crash five names over sessions 20..25 and again over 40..45.
    for t0 in (20, 40):
        for j in range(5):
            p.adj_close[t0 + 5 :, j] *= 0.7
            p.close[t0 + 5 :, j] *= 0.7
    result = reversal.backtest_any_day(p)
    starts = [r["decision"] for r in result["episodes"]]
    assert str(p.dates[25]) in starts
    assert str(p.dates[45]) in starts
    # No episode starts inside the ten-session hold after 25.
    held = {str(p.dates[i]) for i in range(26, 36)}
    assert not held & set(starts)
    assert all(r["deep"] for r in result["episodes"])


# The forward any-day trigger fires on the same sessions the backtest opens
# episodes on, and can fire on the latest session, whose window is still open.
def test_any_day_triggers_match_the_backtest_and_reach_the_last_session():
    p = _panel(n=20, t=80, start="2024-01-01")
    for t0 in (20, 40, 74):
        for j in range(5):
            p.adj_close[t0 + 5 :, j] *= 0.7
            p.close[t0 + 5 :, j] *= 0.7
    triggers = reversal.triggers_any_day(p, since=date(2024, 1, 1))
    starts = {str(np.datetime64(d)) for d in triggers}
    assert str(p.dates[25]) in starts
    assert str(p.dates[45]) in starts
    assert str(p.dates[79]) in starts  # the last session, window not yet closed
    opened = {
        r["decision"]
        for r in reversal.backtest_any_day(p, since=date(2024, 1, 1))["episodes"]
    }
    assert opened <= starts
