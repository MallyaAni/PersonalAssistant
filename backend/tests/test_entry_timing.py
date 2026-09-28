"""The measured entry level: the per-session latch and the five timing states.

What has to hold, because the operator acts on the board in his own account:
the level is `fill_timing.DIP` (not a copy of it); a buy triggers on a close
AT the level (<=) and a sell on a close AT its level (>=), and a hair either
side does not; a trigger survives the price moving back and is never un-set;
the latch is written atomically, idempotently and pruned to 30 sessions;
the clock gives pre-open / waiting / triggered / close / closed at the right
instants, with the close window at 15:30 ET on a regular day and 12:30 ET on
an early close; and the balancer latches every candle without ever failing
because of it.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.market import calendar, entry_timing, fill_timing

NY = ZoneInfo("America/New_York")
# Monday 2026-09-28: a regular session closing at 16:00.
SESSION = date(2026, 9, 28)
# Friday 2026-11-27: the day after Thanksgiving, a published 13:00 close.
EARLY = date(2026, 11, 27)


# An aware New York instant on `day`.
def ny(day: date, hour: int, minute: int = 0) -> datetime:
    """Return `day` at hour:minute in New York."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)


# A live.json quote for one name: the session's open and the latest
# completed bar (start `bar`) closing at `last`.
def quote(last: float, bar: datetime, opened: float = 100.0, symbol: str = "AAA"):
    """Return the quote dict the balancer writes for `symbol`."""
    return {
        "symbol": symbol,
        "last": last,
        "open": opened,
        "high": max(opened, last),
        "low": min(opened, last),
        "bar": bar.astimezone(UTC).isoformat(),
        "as_of": (bar + timedelta(minutes=15)).astimezone(UTC).isoformat(),
    }


# A balancer snapshot holding the given quotes, written when the bars closed.
def snapshot(*quotes, as_of: datetime | None = None) -> dict:
    """Return a live.json-shaped snapshot."""
    return {
        "as_of": (as_of or ny(SESSION, 10, 16)).astimezone(UTC).isoformat(),
        "quotes": {q["symbol"]: q for q in quotes},
    }


# The level is the research engine's constant, reused, not restated.
def test_the_level_is_the_measured_dip():
    assert entry_timing.LEVEL is fill_timing.DIP
    assert entry_timing.level_for(100.0, "buy") == 100.0 * (1.0 - fill_timing.DIP)
    assert entry_timing.level_for(100.0, "sell") == 100.0 * (1.0 + fill_timing.DIP)


# Exactly at the level triggers (<= for a buy, >= for a sell), as
# `fill_timing._dip_or_close` decides it; one cent short does not.
@pytest.mark.parametrize(
    ("side", "close", "expected"),
    [
        ("buy", 99.0, True),
        ("buy", 98.99, True),
        ("buy", 99.01, False),
        ("sell", 101.0, True),
        ("sell", 101.01, True),
        ("sell", 100.99, False),
    ],
)
def test_the_boundary_is_inclusive(side, close, expected):
    assert entry_timing.crosses(close, 100.0, side) is expected


# The same boundary holds through the research engine's own fill rule: a
# session whose one bar closes exactly at the level fills there.
def test_the_boundary_matches_the_research_fill_rule():
    import numpy as np

    closes = np.full(26, 100.5)
    closes[3] = 99.0
    row = {
        "open": np.full(26, 100.0),
        "high": np.full(26, 101.0),
        "low": np.full(26, 98.0),
        "close": closes,
        "volume": np.ones(26),
        "auction_open": 100.2,
    }
    assert fill_timing.fill_price(row, "dip_or_close", "buy") == 99.0
    assert entry_timing.crosses(99.0, 100.0, "buy")


# The first crossing is latched with its bar and survives the price moving
# back above the level on later candles; a sell trigger is latched on its
# own side independently, and neither is ever un-set.
def test_a_trigger_is_latched_and_never_unset(tmp_path):
    early = ny(SESSION, 10, 0)
    entry_timing.update(tmp_path, snapshot(quote(99.5, early)), ny(SESSION, 10, 16))
    latch = entry_timing.load(tmp_path, SESSION)
    row = latch["symbols"]["AAA"]
    assert row["open"] == 100.0
    assert row["buy_trigger"] is None
    assert row["sell_trigger"] is None
    hit = ny(SESSION, 10, 15)
    entry_timing.update(tmp_path, snapshot(quote(98.9, hit)), ny(SESSION, 10, 31))
    back_up = ny(SESSION, 10, 30)
    entry_timing.update(tmp_path, snapshot(quote(100.4, back_up)), ny(SESSION, 10, 46))
    pop = ny(SESSION, 11, 0)
    entry_timing.update(tmp_path, snapshot(quote(101.2, pop)), ny(SESSION, 11, 16))
    row = entry_timing.load(tmp_path, SESSION)["symbols"]["AAA"]
    assert row["buy_trigger"]["bar"] == hit.astimezone(UTC).isoformat()
    assert row["buy_trigger"]["price"] == 98.9
    assert row["sell_trigger"]["bar"] == pop.astimezone(UTC).isoformat()
    assert row["last"] == 101.2
    assert row["bar"] == pop.astimezone(UTC).isoformat()


# A later bar read first does not hide an earlier crossing, and an older
# snapshot never moves the latest bar backwards.
def test_the_first_crossing_wins_whatever_the_order_read(tmp_path):
    late, early = ny(SESSION, 11, 0), ny(SESSION, 10, 15)
    entry_timing.update(tmp_path, snapshot(quote(98.5, late)), ny(SESSION, 12, 0))
    entry_timing.update(tmp_path, snapshot(quote(98.9, early)), ny(SESSION, 12, 0))
    row = entry_timing.load(tmp_path, SESSION)["symbols"]["AAA"]
    assert row["buy_trigger"]["bar"] == early.astimezone(UTC).isoformat()
    assert row["bar"] == late.astimezone(UTC).isoformat()
    assert row["last"] == 98.5


# The open is the first one seen: a later quote with another open does not
# move the level the board has already shown.
def test_the_open_is_latched_once(tmp_path):
    entry_timing.update(
        tmp_path, snapshot(quote(100.0, ny(SESSION, 10))), ny(SESSION, 10, 16)
    )
    entry_timing.update(
        tmp_path,
        snapshot(quote(99.2, ny(SESSION, 10, 15), opened=100.1)),
        ny(SESSION, 10, 31),
    )
    row = entry_timing.load(tmp_path, SESSION)["symbols"]["AAA"]
    assert row["open"] == 100.0
    # 99.2 is above 99.0 (1% under the latched 100), so nothing triggered.
    assert row["buy_trigger"] is None


# The same snapshot twice writes the file once; the bytes do not change.
def test_the_latch_is_idempotent(tmp_path):
    snap = snapshot(quote(98.0, ny(SESSION, 10)))
    first = entry_timing.update(tmp_path, snap, ny(SESSION, 10, 16))
    path = entry_timing.latch_path(tmp_path, SESSION)
    before = path.read_bytes()
    second = entry_timing.update(tmp_path, snap, ny(SESSION, 10, 40))
    assert first == [path]
    assert second == []
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


# A bar that would not be complete at `now`, a quote without an open, and
# a malformed row are ignored rather than latched.
def test_incomplete_and_malformed_quotes_are_ignored(tmp_path):
    snap = snapshot(
        quote(98.0, ny(SESSION, 10), symbol="EARLY"),
        {**quote(98.0, ny(SESSION, 9, 45), symbol="NOOPEN"), "open": None},
        {**quote(98.0, ny(SESSION, 9, 45), symbol="NAN"), "last": float("nan")},
    )
    snap["quotes"]["JUNK"] = "not a quote"
    assert entry_timing.update(tmp_path, snap, ny(SESSION, 10, 10)) == []
    assert entry_timing.load(tmp_path, SESSION) is None


# Each session has its own file, named by the New York date of the bar, and
# only the newest thirty are kept.
def test_sessions_are_separate_files_and_pruned_to_thirty(tmp_path):
    day = date(2026, 6, 1)
    sessions: list[date] = []
    while len(sessions) < 33:
        if calendar.exchange_status(ny(day, 12))["is_session"]:
            entry_timing.update(
                tmp_path, snapshot(quote(99.0, ny(day, 10))), ny(day, 10, 16)
            )
            sessions.append(day)
        day += timedelta(days=1)
    folder = tmp_path / "desk" / entry_timing.LATCH_DIR
    files = sorted(p.name for p in folder.glob("*.json"))
    assert files == [f"{d.isoformat()}.json" for d in sessions[-30:]]
    assert entry_timing.KEEP_SESSIONS == 30
    newest = entry_timing.load(tmp_path, sessions[-1])
    assert newest["symbols"]["AAA"]["buy_trigger"]["price"] == 99.0
    assert entry_timing.load(tmp_path, sessions[0]) is None


# The latch refuses a session other than the one asked for.
def test_row_for_answers_only_for_its_session(tmp_path):
    entry_timing.update(
        tmp_path, snapshot(quote(98.0, ny(SESSION, 10))), ny(SESSION, 10, 16)
    )
    latch = entry_timing.load(tmp_path, SESSION)
    assert entry_timing.row_for(latch, "AAA", SESSION)["open"] == 100.0
    assert entry_timing.row_for(latch, "AAA", date(2026, 9, 29)) is None
    assert entry_timing.row_for(latch, "BBB", SESSION) is None
    assert entry_timing.load(tmp_path, date(2026, 9, 29)) is None


# The five states on a regular session, at the instants that separate them.
@pytest.mark.parametrize(
    ("hour", "minute", "with_quote", "expected"),
    [
        (8, 0, False, entry_timing.PRE_OPEN),  # before 9:30
        (9, 40, False, entry_timing.PRE_OPEN),  # the opening bar is not complete
        (10, 16, True, entry_timing.WAITING),
        (15, 29, True, entry_timing.WAITING),  # one minute before the window
        (15, 30, True, entry_timing.CLOSE),  # the window opens at close - 30'
        (15, 59, True, entry_timing.CLOSE),
        (16, 0, True, entry_timing.CLOSED),  # the session's decisions are over
        (20, 0, True, entry_timing.CLOSED),
    ],
)
def test_the_clock_on_a_regular_session(hour, minute, with_quote, expected):
    now = ny(SESSION, hour, minute)
    q = quote(99.6, ny(SESSION, 10)) if with_quote else None
    timed = entry_timing.timing(None, q, "buy", now, SESSION)
    assert timed["state"] == expected, timed
    assert timed["close_cutoff"] == ny(SESSION, 15, 30).isoformat()
    assert timed["moc_deadline"] == ny(SESSION, 15, 50).isoformat()
    if expected == entry_timing.WAITING:
        assert timed["open"] == 100.0
        assert timed["level"] == pytest.approx(99.0)
        assert "$99.00 (1% under today's open $100.00)" in timed["reason"]


# On an early close the window opens at 12:30 and the session ends at 13:00.
def test_the_close_window_follows_an_early_close():
    assert calendar.session_close(EARLY).hour == 13
    q = quote(100.3, ny(EARLY, 10))
    at = entry_timing.timing
    assert at(None, q, "buy", ny(EARLY, 12, 29), EARLY)["state"] == "waiting"
    close = at(None, q, "buy", ny(EARLY, 12, 30), EARLY)
    assert close["state"] == entry_timing.CLOSE
    assert close["close_cutoff"] == ny(EARLY, 12, 30).isoformat()
    assert "before 12:50 PM ET" in close["reason"]
    assert at(None, q, "buy", ny(EARLY, 13, 0), EARLY)["state"] == entry_timing.CLOSED


# A weekend, a holiday and a year the calendar has not reviewed are not
# sessions: pre-open, never waiting on a stale open.
@pytest.mark.parametrize(
    "day", [date(2026, 9, 27), date(2026, 11, 26), date(2031, 3, 4)]
)
def test_a_non_session_day_is_pre_open(day):
    stale = quote(98.0, ny(date(2026, 9, 25), 15, 45))
    timed = entry_timing.timing(None, stale, "buy", ny(day, 11), day)
    assert timed["state"] == entry_timing.PRE_OPEN
    assert timed["trading_day"] is False
    assert timed["level"] is None


# The previous session's quote (Friday's live.json on Monday morning) never
# stands in for today's open.
def test_a_previous_sessions_quote_is_not_todays_open():
    friday = quote(98.0, ny(date(2026, 9, 25), 15, 45))
    timed = entry_timing.timing(None, friday, "buy", ny(SESSION, 9, 50), SESSION)
    assert timed["state"] == entry_timing.PRE_OPEN
    assert timed["open"] is None


# A latched trigger stands after the price recovers, and outranks the close
# window: the rule fills at the first crossing.
def test_a_latched_trigger_stands_and_outranks_the_close(tmp_path):
    hit = ny(SESSION, 10, 15)
    entry_timing.update(tmp_path, snapshot(quote(98.9, hit)), ny(SESSION, 10, 31))
    row = entry_timing.row_for(entry_timing.load(tmp_path, SESSION), "AAA", SESSION)
    recovered = quote(100.4, ny(SESSION, 14, 0))
    for now in (ny(SESSION, 14, 16), ny(SESSION, 15, 40)):
        timed = entry_timing.timing(row, recovered, "buy", now, SESSION)
        assert timed["state"] == entry_timing.TRIGGERED
        assert timed["trigger_bar"] == hit.astimezone(UTC).isoformat()
        assert timed["trigger_price"] == 98.9
        assert "10:30 AM ET 15-minute close $98.90" in timed["reason"]
    # The sell side of the same name has no trigger.
    sell = entry_timing.timing(row, recovered, "sell", ny(SESSION, 14, 16), SESSION)
    assert sell["state"] == entry_timing.WAITING
    assert sell["level"] == pytest.approx(101.0)


# Without a latch, the current bar's own close at the level is a trigger:
# the first crossing is at or before it, so the rule has filled.
def test_the_current_bar_crossing_triggers_without_a_latch():
    q = quote(101.0, ny(SESSION, 11, 0))
    timed = entry_timing.timing(None, q, "sell", ny(SESSION, 11, 16), SESSION)
    assert timed["state"] == entry_timing.TRIGGERED
    assert timed["trigger_price"] == 101.0
    # A bar that is not complete at `now` does not count.
    early = entry_timing.timing(None, q, "sell", ny(SESSION, 11, 10), SESSION)
    assert early["state"] == entry_timing.PRE_OPEN


# The planned and acting sentences name the side, the size and the level.
def test_the_sentences_say_what_is_planned_and_why_now():
    at = ny(SESSION, 10, 20)
    q = quote(179.5, ny(SESSION, 10), opened=180.0)
    waiting = entry_timing.timing(None, q, "buy", at, SESSION)
    assert entry_timing.planned("Buy", 1 / 11, waiting) == (
        "Buy 9.1% planned: on a 15-minute close at or under $178.20 "
        "(1% under today's open $180.00), else at the close"
    )
    q = quote(97.2, ny(SESSION, 10), opened=97.13)
    sell = entry_timing.timing(None, q, "sell", at, SESSION)
    # 97.13 x 1.01 = 98.1013: "at or over" is only true of $98.11 in cents.
    assert "at or over $98.11 (1% over today's open $97.13)" in entry_timing.planned(
        "Trim", 0.049, sell
    )
    q = quote(179.5, ny(SESSION, 15), opened=180.0)
    closing = entry_timing.timing(None, q, "buy", ny(SESSION, 15, 31), SESSION)
    assert entry_timing.acting("Buy", closing) == (
        "Buy at the close: no 15-minute close reached $178.20 today; "
        "market-on-close before 3:50 PM ET"
    )
    q = quote(178.1, ny(SESSION, 10), opened=180.0)
    hit = entry_timing.timing(None, q, "buy", at, SESSION)
    assert entry_timing.acting("Buy", hit) == (
        "Buy now: the 10:15 AM ET 15-minute close $178.10 is at or under $178.20 "
        "(1% under today's open $180.00)"
    )
    closed = entry_timing.timing(None, None, "buy", ny(SESSION, 16, 30), SESSION)
    assert "session has closed" in entry_timing.planned("Buy", 0.05, closed)


# A side other than buy or sell, or a naive clock, is a programming error.
def test_bad_arguments_are_refused(tmp_path):
    with pytest.raises(ValueError, match="side must be buy or sell"):
        entry_timing.timing(None, None, "short", ny(SESSION, 11), SESSION)
    with pytest.raises(ValueError, match="timezone-aware"):
        entry_timing.timing(None, None, "buy", datetime(2026, 9, 28, 11), SESSION)
    with pytest.raises(ValueError, match="timezone-aware"):
        entry_timing.update(tmp_path, {}, datetime(2026, 9, 28, 11))


# ---------------------------------------------------------------------------
# The balancer latches every candle it writes, and never fails because of it.
# ---------------------------------------------------------------------------


# Stub the balancer's network and side legs so `run` writes live.json from
# the given quotes at a fixed instant and does nothing else.
def _balancer(monkeypatch, tmp_path: Path, found: dict, now: datetime):
    """Prepare `market_balancer.run` against `tmp_path`; return the module."""
    import datetime as dt

    from backend.cli import market_balancer, market_event_recovery
    from backend.market import intraday_research

    class _Clock(dt.datetime):
        # The balancer's wall clock, fixed at `now`.
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(market_balancer, "datetime", _Clock)
    monkeypatch.setattr(market_balancer.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(market_balancer.live_quotes, "quotes", lambda *a, **k: found)
    for name in ("technical_now", "value_now", "technical_detail"):
        monkeypatch.setattr(market_balancer.live_technical, name, lambda *a, **k: {})
    monkeypatch.setattr(intraday_research, "publish", lambda *a, **k: {})
    monkeypatch.setattr(market_balancer, "_observe_paper", lambda *a, **k: None)
    monkeypatch.setattr(market_balancer, "_green_day_skip", lambda *a, **k: None)
    monkeypatch.setattr(market_event_recovery, "run", lambda *a, **k: None)
    record = {
        "session": "2026-09-25",
        "grades": {"AAA": {"grade": "A", "score": 1.0, "stances": {}}},
        "book": [{"ticker": "AAA", "weight": 0.1}],
        "levels": {"AAA": {"last_close": 100.0, "rejecting_band": False}},
    }
    path = tmp_path / "desk" / "asof=2026-09-25" / "desk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return market_balancer


# Right after live.json is written, today's latch holds the open and the
# first crossing of the candle the balancer just read.
def test_the_balancer_latches_the_candle_it_writes(tmp_path, monkeypatch):
    from backend.market.live_quotes import Quote

    bar = ny(SESSION, 10, 15).astimezone(UTC).isoformat()
    found = {
        "AAA": Quote("AAA", 98.9, 100.0, 100.2, 98.8, bar, "2026-09-28T14:31:00+00:00")
    }
    balancer = _balancer(monkeypatch, tmp_path, found, ny(SESSION, 10, 31))
    balancer.run(tmp_path, 100_000.0)
    live = json.loads((tmp_path / "desk" / "live.json").read_text(encoding="utf-8"))
    assert live["quotes"]["AAA"]["open"] == 100.0
    row = entry_timing.load(tmp_path, SESSION)["symbols"]["AAA"]
    assert row["open"] == 100.0
    assert row["buy_trigger"] == {
        "bar": bar,
        "price": 98.9,
        "seen_at": live["as_of"],
    }


# A latch failure is logged and the balancer finishes its run: the plan and
# the live snapshot are still written.
def test_a_latch_failure_never_stops_the_balancer(tmp_path, monkeypatch, capsys):
    from backend.market.live_quotes import Quote

    bar = ny(SESSION, 10, 15).astimezone(UTC).isoformat()
    found = {"AAA": Quote("AAA", 99.5, 100.0, 100.2, 99.4, bar, "x")}
    balancer = _balancer(monkeypatch, tmp_path, found, ny(SESSION, 10, 31))

    # Fail the way a full disk or a bad mount would.
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(entry_timing, "update", broken)
    path = balancer.run(tmp_path, 100_000.0)
    assert path.exists()
    assert (tmp_path / "desk" / "live.json").exists()
    out = capsys.readouterr().out
    assert "Entry timing latch unavailable (OSError: disk full)" in out
    assert entry_timing.load(tmp_path, SESSION) is None
