"""Live quotes for the action board.

What has to hold: a session's bars fold into the last close and the
session's high and low; a second ask inside the same candle answers from
memory without touching the feed; a name the feed has nothing for is
left out rather than invented; and a feed error costs that name only.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from backend.market import live_quotes


def _bar(start: str, o: float, h: float, lo: float, c: float):
    return SimpleNamespace(
        start=datetime.fromisoformat(start), open=o, high=h, low=lo, close=c, volume=1
    )


def test_bars_fold_into_last_high_and_low():
    bars = [
        _bar("2026-09-08T13:30", 44.0, 45.0, 43.5, 44.5),
        _bar("2026-09-08T13:45", 44.5, 46.0, 44.0, 45.8),
    ]
    q = live_quotes.quote_from_bars(
        "IREN", bars, datetime(2026, 9, 8, 13, 50, tzinfo=UTC)
    )
    assert q is not None
    assert (q.last, q.high, q.low) == (45.8, 46.0, 43.5)
    assert q.bar.startswith("2026-09-08T13:45")
    assert live_quotes.quote_from_bars("IREN", [], datetime.now(UTC)) is None


def test_memory_holds_for_a_candle_and_errors_cost_one_name():
    live_quotes.forget()
    calls: list[str] = []
    ticks = [0.0]

    def fetch(symbol, start, end, headers=None):
        calls.append(symbol)
        if symbol == "BAD":
            raise RuntimeError("feed down")
        if symbol == "NONE":
            return []
        return [_bar("2026-09-08T13:30", 1.0, 2.0, 0.5, 1.5)]

    kwargs = {
        "session": date(2026, 9, 8),
        "fetch": fetch,
        "now": lambda: ticks[0],
        "clock": lambda: datetime(2026, 9, 8, 14, 0, tzinfo=UTC),
    }
    first = live_quotes.quotes(["AAA", "BAD", "NONE"], **kwargs)
    assert set(first) == {"AAA"}
    assert calls == ["AAA", "BAD", "NONE"]
    ticks[0] = 600.0  # ten minutes on: the same candle
    again = live_quotes.quotes(["AAA"], **kwargs)
    assert again["AAA"] is first["AAA"]
    assert calls.count("AAA") == 1
    ticks[0] = 1000.0  # the candle has turned
    live_quotes.quotes(["AAA"], **kwargs)
    assert calls.count("AAA") == 2
    live_quotes.forget()
