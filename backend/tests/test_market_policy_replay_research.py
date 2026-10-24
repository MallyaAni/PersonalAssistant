"""The chart replay's grade changes come from the same run as its trades."""

from backend.cli import market_policy_replay_research as research
from backend.tests.test_market_pit_scorecard import _report, history  # noqa: F401


# Each stock's grades start on the first session, then list only changes of
# letter, each effective at the next session's New York open; and they agree
# with the letters on the rows the trades are read from.
def test_replay_records_every_grade_change_once(history):  # noqa: F811
    report = _report()
    manifest, stocks = research.replay(report, history, "leader_ewma_minB_floor50")
    assert manifest["arm"] == "leader_ewma_minB_floor50"
    assert stocks
    for stock in stocks.values():
        grades = stock["grades"]
        assert grades[0]["date"] == manifest["start"]
        letters = [g["grade"] for g in grades]
        assert all(a != b for a, b in zip(letters, letters[1:]))
        for g in grades:
            assert g["said"] is False
            if "at" in g:
                assert g["at"].endswith(("T09:30:00-04:00", "T09:30:00-05:00"))
                assert g["at"][:10] > g["date"]
        by_date = {g["date"]: g["grade"] for g in grades}
        current = None
        for row in sorted(stock["rows"], key=lambda r: r["date"]):
            for day in sorted(by_date):
                if day <= row["date"]:
                    current = by_date[day]
            assert row["grade"] == current


# The chart grades with the fundamentals the nightly decides from.
def test_replay_grades_like_the_nightly(monkeypatch):
    from backend.cli import market_daily

    seen = {}
    monkeypatch.setattr(
        market_daily.trading_desk, "run", lambda store, asof, **kw: seen.update(kw)
    )
    market_daily.desk_report(None, None)
    assert seen["fundamentals"] == research.FUNDAMENTALS
    assert seen.get("inputs", research.desk.LIVE_INPUTS) == research.desk.LIVE_INPUTS


# The chart's trades are the simulated account's fills: each on the session
# after its decision, and the chart's held weights move only on fill days.
def test_installed_replay_is_the_account_simulation(history):  # noqa: F811
    report = _report()
    manifest, stocks = research.replay(report, history, "leader_ewma_minB_floor50")
    book = research.installed_book(report)
    assert manifest["book"]["fills"] == len(book.trades)
    dates = manifest and [str(d)[:10] for d in report.panel.dates]
    fills = [t for v in stocks.values() for t in v["trades"]]
    assert len(fills) == len(book.trades)
    for stock in stocks.values():
        days = {t["date"] for t in stock["trades"]}
        for trade in stock["trades"]:
            assert dates.index(trade["date"]) == dates.index(trade["decided"]) + 1
        rows = stock["rows"]
        for row in rows[1:]:
            assert row["date"] in days


class _PricePanel:
    def __init__(self):
        import numpy as np

        self.dates = np.array(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"], dtype="datetime64[D]")
        self.tickers = ("X", "SPY")
        self.benchmark = "SPY"
        self.open = np.array([[10.0, 100.0], [11.0, 100.0], [12.0, 100.0], [12.0, 100.0]])
        self.close = np.array([[10.0, 100.0], [12.0, 100.0], [12.0, 100.0], [15.0, 100.0]])
        self.adj_close = self.close.copy()

    def index(self, ticker):
        return self.tickers.index(ticker)


# The P&L fills at the open after the decision: the overnight gap before the
# fill is not earned, the move after it is, and both fills pay the cost.
def test_realised_pnl_fills_at_the_next_open():
    import pytest

    trades = [
        {"decided": "2026-01-05", "date": "2026-01-06", "action": "BUY", "size": 0.1, "target": 0.1},
        {"decided": "2026-01-07", "date": "2026-01-08", "action": "SELL", "size": 0.1, "target": 0.0},
    ]
    out = research.realised(_PricePanel(), 0, trades)
    cost = 2 * 0.1 * research.COST_BPS / 1e4
    assert out["gross"] == pytest.approx(0.1 * (12 / 11 - 1))
    assert out["costs"] == pytest.approx(cost)
    assert out["net"] == pytest.approx(0.1 * (12 / 11 - 1) - cost)
    assert out["benchmark_same_weights"] == pytest.approx(0.0)
    assert out["round_trips"] == 1 and out["winning_trips"] == 1
    (trip,) = out["trips"]
    assert (trip["entered"], trip["exited"], trip["sessions"]) == ("2026-01-06", "2026-01-08", 2)
    assert trip["price_return"] == pytest.approx(12 / 11 - 1)
    assert out["open_since"] is None and out["unpriced_sessions"] == []


# An entry's outcome runs from its fill, the next open, not from the decision close.
def test_signal_outcomes_start_at_the_fill(monkeypatch):
    import numpy as np
    import pytest

    monkeypatch.setattr(research, "HORIZONS", (1, 2))
    out = research.signal_outcomes(_PricePanel(), 0, np.array([0.0, 0.1, 0.1, 0.0]))
    (entry,) = out["entries"]
    assert entry["date"] == "2026-01-06" and entry["filled"] == "2026-01-07"
    assert entry["return_1"] == pytest.approx(0.0)
    assert entry["return_2"] == pytest.approx(15 / 12 - 1)
    assert out["exits"] == []
