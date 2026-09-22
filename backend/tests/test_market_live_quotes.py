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


# Completed bars determine the displayed price and observed session range.
def test_bars_fold_into_last_high_and_low():
    bars = [
        _bar("2026-09-08T13:30", 44.0, 45.0, 43.5, 44.5),
        _bar("2026-09-08T13:45", 44.5, 46.0, 44.0, 45.8),
    ]
    q = live_quotes.quote_from_bars(
        "IREN", bars, datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
    )
    assert q is not None
    assert (q.last, q.high, q.low) == (45.8, 46.0, 43.5)
    assert q.open == 44.0  # the session's first bar's open
    assert q.bar.startswith("2026-09-08T13:45")
    assert live_quotes.quote_from_bars("IREN", [], datetime.now(UTC)) is None


# A forming or future candle must not influence the displayed price or range.
def test_unfinished_candles_are_excluded_until_the_interval_closes():
    bars = [
        _bar("2026-09-08T13:30", 44.0, 45.0, 43.5, 44.5),
        _bar("2026-09-08T13:45", 44.5, 46.0, 44.0, 45.8),
        _bar("2026-09-08T14:00", 45.8, 99.0, 1.0, 98.0),
    ]
    assert (
        live_quotes.quote_from_bars(
            "IREN", bars, datetime(2026, 9, 8, 13, 44, tzinfo=UTC)
        )
        is None
    )
    quote = live_quotes.quote_from_bars(
        "IREN", bars, datetime(2026, 9, 8, 13, 50, tzinfo=UTC)
    )
    assert quote is not None
    assert (quote.last, quote.high, quote.low) == (44.5, 45.0, 43.5)


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


# The session is the Eastern calendar day: at 01:00 UTC on the 11th it is
# still the evening of the 10th in New York, and the feed is asked for the
# 10th's bars, not for a day that has not opened.
def test_the_session_is_the_new_york_day_not_the_utc_one():
    from datetime import UTC, datetime

    live_quotes.forget()
    asked = []

    def fetch(symbol, start, end, headers=None):
        asked.append((start, end))
        return []

    live_quotes.quotes(
        ["AAA"],
        fetch=fetch,
        clock=lambda: datetime(2026, 9, 11, 1, 0, tzinfo=UTC),
    )
    assert asked == [(date(2026, 9, 10), date(2026, 9, 10))]


# A read just before the boundary answers from memory; the moment the next
# bar closes the cache turns over even though less than a candle of wall
# clock has passed, and the fresh quote then answers from memory again.
def test_cache_turns_over_at_the_bar_boundary_not_the_wall_clock():
    live_quotes.forget()
    calls: list[str] = []

    # Return two adjacent bars so advancing the clock exposes the second one.
    def fetch(symbol, start, end, headers=None):
        calls.append(symbol)
        return [
            _bar("2026-09-08T13:30", 44.0, 45.0, 43.5, 44.5),
            _bar("2026-09-08T13:45", 44.5, 46.0, 44.0, 45.8),
        ]

    wall = [datetime(2026, 9, 8, 13, 59, tzinfo=UTC)]  # 09:59 New York
    ticks = [0.0]
    kwargs = {
        "session": date(2026, 9, 8),
        "fetch": fetch,
        "now": lambda: ticks[0],
        "clock": lambda: wall[0],
    }
    first = live_quotes.quotes(["IREN"], **kwargs)
    assert first["IREN"].bar.startswith("2026-09-08T13:30")
    assert first["IREN"].last == 44.5
    assert calls.count("IREN") == 1
    # One minute later, still 09:59: the same candle, memory answers.
    wall[0] = datetime(2026, 9, 8, 13, 59, 59, tzinfo=UTC)
    ticks[0] = 59.0
    just_before = live_quotes.quotes(["IREN"], **kwargs)
    assert just_before["IREN"] is first["IREN"]
    assert calls.count("IREN") == 1
    # At 10:00 the 09:45 bar is complete; the cache turns over although only
    # sixty wall-clock seconds passed.
    wall[0] = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
    ticks[0] = 60.0
    at_boundary = live_quotes.quotes(["IREN"], **kwargs)
    assert calls.count("IREN") == 2
    assert at_boundary["IREN"].bar.startswith("2026-09-08T13:45")
    assert at_boundary["IREN"].last == 45.8
    # After the boundary the fresh quote is held for the rest of the candle.
    wall[0] = datetime(2026, 9, 8, 14, 1, tzinfo=UTC)
    ticks[0] = 61.0
    after = live_quotes.quotes(["IREN"], **kwargs)
    assert after["IREN"] is at_boundary["IREN"]
    assert calls.count("IREN") == 2
    live_quotes.forget()


# Two reads inside one candle answer from memory however much wall clock has
# passed, as long as the bar has not turned.
def test_reads_within_one_candle_answer_from_memory():
    live_quotes.forget()
    calls: list[str] = []

    # Count requests while returning a stable completed bar.
    def fetch(symbol, start, end, headers=None):
        calls.append(symbol)
        return [_bar("2026-09-08T13:30", 1.0, 2.0, 0.5, 1.5)]

    wall = [datetime(2026, 9, 8, 13, 46, tzinfo=UTC)]  # 09:46 New York
    ticks = [0.0]
    kwargs = {
        "session": date(2026, 9, 8),
        "fetch": fetch,
        "now": lambda: ticks[0],
        "clock": lambda: wall[0],
    }
    first = live_quotes.quotes(["AAA"], **kwargs)
    assert calls.count("AAA") == 1
    # Ten minutes later in the same candle the wall clock moved but the bar
    # has not, so the answer still comes from memory.
    wall[0] = datetime(2026, 9, 8, 13, 56, tzinfo=UTC)
    ticks[0] = 600.0
    again = live_quotes.quotes(["AAA"], **kwargs)
    assert again["AAA"] is first["AAA"]
    assert calls.count("AAA") == 1
    live_quotes.forget()


# A delayed feed that has not produced the next bar must not reset the
# candle clock: the boundary turns the cache over once, and the unchanged
# bar is then held for the rest of the candle rather than polled again.
def test_a_delayed_feed_is_not_hot_polled():
    live_quotes.forget()
    calls: list[str] = []

    # Simulate a provider whose newest completed bar has not arrived yet.
    def fetch(symbol, start, end, headers=None):
        calls.append(symbol)
        return [_bar("2026-09-08T13:30", 1.0, 2.0, 0.5, 1.5)]

    wall = [datetime(2026, 9, 8, 13, 59, tzinfo=UTC)]  # 09:59 New York
    ticks = [0.0]
    kwargs = {
        "session": date(2026, 9, 8),
        "fetch": fetch,
        "now": lambda: ticks[0],
        "clock": lambda: wall[0],
    }
    first = live_quotes.quotes(["AAA"], **kwargs)
    assert first["AAA"].bar.startswith("2026-09-08T13:30")
    assert calls.count("AAA") == 1
    # The boundary turns the cache over even though the feed is late.
    wall[0] = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)  # 10:00 New York
    ticks[0] = 60.0
    at = live_quotes.quotes(["AAA"], **kwargs)
    assert calls.count("AAA") == 2
    assert at["AAA"].bar.startswith("2026-09-08T13:30")  # feed has not caught up
    # Still the same candle: the unchanged bar answers from memory, once.
    wall[0] = datetime(2026, 9, 8, 14, 10, tzinfo=UTC)
    ticks[0] = 90.0
    later = live_quotes.quotes(["AAA"], **kwargs)
    assert later["AAA"] is at["AAA"]
    assert calls.count("AAA") == 2
    live_quotes.forget()


# The memory belongs to its session: a bar cached one evening is not served
# the next morning, when the feed is asked for the new day instead.
def test_the_memory_does_not_cross_into_the_next_session():
    live_quotes.forget()
    calls: list[str] = []

    # Return the requested day's opening bar to expose cross-session reuse.
    def fetch(symbol, start, end, headers=None):
        calls.append(symbol)
        return [_bar(f"{start.isoformat()}T13:30", 1.0, 2.0, 0.5, 1.5)]

    wall = [datetime(2026, 9, 8, 19, 59, tzinfo=UTC)]  # 15:59 New York
    ticks = [0.0]
    kwargs = {
        "fetch": fetch,
        "now": lambda: ticks[0],
        "clock": lambda: wall[0],
    }
    first = live_quotes.quotes(["AAA"], **kwargs)
    assert first["AAA"].bar.startswith("2026-09-08T13:30")
    assert calls.count("AAA") == 1
    # The next morning the cached bar belongs to yesterday and is not served;
    # the feed is asked for the new day instead.
    wall[0] = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)  # 10:00 New York
    ticks[0] = 120.0
    next_day = live_quotes.quotes(["AAA"], **kwargs)
    assert calls.count("AAA") == 2
    assert next_day["AAA"].bar.startswith("2026-09-09T13:30")
    live_quotes.forget()


# A feed error at the boundary costs that name only: the board omits it
# rather than resurfacing the old candle it has stopped trusting.
def test_a_feed_error_after_the_boundary_omits_the_name():
    live_quotes.forget()
    calls: list[str] = []
    fail_next = [False]

    # Make the provider unavailable after the initial successful read.
    def fetch(symbol, start, end, headers=None):
        calls.append(symbol)
        if fail_next[0]:
            raise RuntimeError("feed down")
        return [_bar("2026-09-08T13:30", 1.0, 2.0, 0.5, 1.5)]

    wall = [datetime(2026, 9, 8, 13, 59, tzinfo=UTC)]  # 09:59 New York
    ticks = [0.0]
    kwargs = {
        "session": date(2026, 9, 8),
        "fetch": fetch,
        "now": lambda: ticks[0],
        "clock": lambda: wall[0],
    }
    first = live_quotes.quotes(["AAA"], **kwargs)
    assert "AAA" in first
    # The boundary turns the cache over and the feed is down, so the name is
    # left out rather than served from the old candle.
    wall[0] = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)
    ticks[0] = 60.0
    fail_next[0] = True
    at = live_quotes.quotes(["AAA"], **kwargs)
    assert "AAA" not in at
    live_quotes.forget()
