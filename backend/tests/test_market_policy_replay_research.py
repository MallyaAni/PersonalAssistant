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


# The chart replays the book the live policy trades: a name is sizable from the
# first close with a full trailing window, whenever it joined the desk, and the
# indices and benchmark never are.
def test_book_eligibility_starts_at_the_full_window(history):  # noqa: F811
    import numpy as np

    report = _report()
    panel = report.panel
    mask = research.book_eligibility(panel, window=5)
    closes = np.asarray(panel.adj_close, dtype=float)
    for column, ticker in enumerate(panel.tickers):
        if ticker in (*research.universe.MARKET_INDICES, panel.benchmark):
            assert not mask[:, column].any()
            continue
        for t in range(len(panel.dates)):
            window = closes[max(0, t - 5) : t + 1, column]
            full = t >= 5 and bool(np.all(np.isfinite(window) & (window > 0)))
            assert mask[t, column] == full


def test_book_replay_is_not_restricted_to_membership(history):  # noqa: F811
    report = _report()
    manifest, stocks = research.replay(report, history, "leader_ewma_minB_floor50")
    assert manifest["universe"] == "book"
    assert "membership" not in manifest
    member, _ = research.replay(
        report, history, "leader_ewma_minB_floor50", basis="membership"
    )
    assert member["universe"] == "membership"


# The installed policy's targets are the live sizing on every close.
def test_installed_targets_are_the_live_leader_weights(history):  # noqa: F811
    import numpy as np

    from backend.market import grade_led_leader_policy as leader

    report = _report()
    mask = research.book_eligibility(report.panel)
    restricted = research.point_in_time.restrict(report, mask)
    weights = research.live_leader_targets(restricted, mask)
    closes = np.asarray(report.panel.adj_close, dtype=float)
    window = leader.WINDOW
    assert not weights[:window].any()
    for t in range(window, len(report.panel.dates)):
        sized = mask[t] & (np.asarray(restricted.graded.grades[t]) >= leader.ENTRY_GRADE)
        expected, _ = leader.leader_weights(closes[t - window : t + 1], sized)
        assert np.array_equal(weights[t], expected)


class _Panel:
    def __init__(self, days):
        import numpy as np

        self.dates = np.array(days, dtype="datetime64[D]")


# Cut half at the first reduced close, hold through the lead-in, restore the
# baseline on the eve for the decision close, then the ordinary plan.
def test_fomc_overlay_follows_the_live_cycle(monkeypatch):
    from datetime import date

    import numpy as np

    days = ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
    factor = np.array([1, 1, 1, 0.5, 0.5, 0.5, 0.5, 1, 1], dtype=float)
    monkeypatch.setattr(research.event_risk, "live_path", lambda panel: factor)
    monkeypatch.setattr(research, "fomc_decisions", lambda: [date(2026, 7, 29)])
    weights = np.array([[0.1], [0.1], [0.1], [0.2], [0.3], [0.3], [0.3], [0.4], [0.5]])
    out, steps = research.fomc_overlay(_Panel(days), weights)
    assert out[:, 0].tolist() == [0.1, 0.1, 0.1, 0.05, 0.05, 0.05, 0.1, 0.4, 0.5]
    assert steps == {
        3: "fomc_reduction",
        4: "fomc_reduction",
        5: "fomc_reduction",
        6: research.decision_close_step,
    }


# A cycle that starts on the eve cuts at the decision open and restores at the
# following open; the ordinary plan resumes the night after.
def test_fomc_overlay_cycle_starting_on_the_eve(monkeypatch):
    from datetime import date

    import numpy as np

    days = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
    factor = np.array([1, 0.5, 1, 1], dtype=float)
    monkeypatch.setattr(research.event_risk, "live_path", lambda panel: factor)
    monkeypatch.setattr(research, "fomc_decisions", lambda: [date(2026, 7, 29)])
    weights = np.array([[0.2], [0.3], [0.4], [0.5]])
    out, steps = research.fomc_overlay(_Panel(days), weights)
    assert out[:, 0].tolist() == [0.2, 0.1, 0.2, 0.5]
    assert steps == {1: "fomc_reduction", 2: "fomc_restoration"}


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


# A move is measured from the last written target, so the drawn target never
# drifts from the true one by more than DUST, and every entry and exit is written.
def test_written_targets_stay_within_dust(history):  # noqa: F811
    report = _report()
    manifest, stocks = research.replay(report, history, "leader_ewma_minB_floor50")
    for stock in stocks.values():
        last = 0.0
        for trade in stock["trades"]:
            assert abs(abs(trade["target"] - last) - trade["size"]) < 1e-12
            last = trade["target"]
        # The final close has no next open to trade at, but its row is written.
        assert abs(stock["rows"][-1]["weight"] - stock["latest_target"]) < research.DUST


# A band-blocked name is not bought, and a held one may not grow past its target.
def test_band_block_stops_buys_and_growth(history):  # noqa: F811
    import numpy as np

    report = _report()
    mask = research.book_eligibility(report.panel)
    restricted = research.point_in_time.restrict(report, mask)
    free = research.live_leader_targets(restricted, mask)
    blocked = np.zeros_like(mask)
    blocked[:, :] = True
    held = research.live_leader_targets(restricted, mask, blocked)
    assert not held.any()
    first = next(t for t in range(len(free)) if free[t].any())
    current = free[first]
    after = research.leader_target(restricted, mask, first + 1, blocked, current)
    assert (after <= current + 1e-15).all()
    assert ((after > 0) <= (current > 0)).all()


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
