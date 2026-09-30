"""The structure the board shows and the desk does not act on (S0).

What has to hold, because the operator reads these numbers in his own
account: the 21-EMA is pandas' `ewm(span=21, adjust=False)` on the adjusted
close up to the prior session; the slope is the five-session change as a
fraction of the EMA; a first bar that reaches within 0.5% of a level from
below is a tag, and one that closes back under it is a rejection; the count
of sessions at the level walks back over the daily highs and stops at the
first session away from it; a session's opening bar survives in the
entry-timing latch once later candles have folded it into the session's
high; and the balancer's rows carry every field, with the price's age
measured from the bar's end to the run's `as_of`.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.agents.trading.desk import structure
from backend.market import entry_timing
from backend.market.yahoo import DailyBar

NY = ZoneInfo("America/New_York")
# Wednesday 2026-09-30: the session whose first bar is under test.
SESSION = date(2026, 9, 30)
ALPHA = 2.0 / 22.0


# A daily bar with every price the same unless told otherwise.
def bar(day: date, close: float, high: float | None = None, adj: float | None = None):
    """Return a DailyBar closing at `close` with high `high`."""
    return DailyBar(
        session_date=day,
        open=close,
        high=high if high is not None else close,
        low=close,
        close=close,
        adjusted_close=adj if adj is not None else close,
        volume=1_000,
    )


# `count` daily bars ending the session before `SESSION`, closing at
# `closes[i]` with highs `highs[i]` (the close when omitted), oldest first.
def history(closes: list[float], highs: list[float | None] | None = None) -> list:
    """Return synthetic bars for the sessions before SESSION, oldest first."""
    highs = highs or [None] * len(closes)
    days: list[date] = []
    day = SESSION
    while len(days) < len(closes):
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    days.reverse()
    return [bar(d, c, h) for d, c, h in zip(days, closes, highs, strict=True)]


# A live.json quote for the session's bar starting at `hour:minute`.
def quote(last: float, high: float, hour: int = 9, minute: int = 30, opened=100.0):
    """Return the balancer's quote dict for one name."""
    start = datetime(SESSION.year, SESSION.month, SESSION.day, hour, minute, tzinfo=NY)
    return {
        "symbol": "AAA",
        "last": last,
        "open": opened,
        "high": high,
        "low": min(opened, last),
        "bar": start.astimezone(UTC).isoformat(),
        "as_of": (start + timedelta(minutes=15)).astimezone(UTC).isoformat(),
    }


# The EMA is the adjust=False recursion: seeded by the first value, then
# a*v + (1-a)*prior with a = 2/(span+1).
def test_the_ema_is_the_adjust_false_recursion():
    values = [100.0, 102.0, 101.0, 105.0, 110.0]
    expected = [values[0]]
    for value in values[1:]:
        expected.append(ALPHA * value + (1 - ALPHA) * expected[-1])
    got = structure.ema(values, 21)
    assert got == pytest.approx(expected)
    assert structure.ema([], 21) == []
    with pytest.raises(ValueError, match="span"):
        structure.ema(values, 0)


# The same recursion pandas runs for `ewm(span=21, adjust=False)`.
def test_the_ema_matches_pandas_ewm_span_21_adjust_false():
    pd = pytest.importorskip("pandas")
    values = [float(100 + ((i * 7) % 11) - 5) for i in range(60)]
    expected = pd.Series(values).ewm(span=21, adjust=False).mean().tolist()
    assert structure.ema(values, 21) == pytest.approx(expected)


# The slope is today's EMA minus the EMA five sessions ago, as a fraction of
# today's; too short a series has no slope.
def test_the_slope_is_the_five_session_change_as_a_fraction():
    series = [100.0, 101.0, 102.0, 103.0, 104.0, 106.0]
    assert structure.ema_slope(series, 5) == pytest.approx((106.0 - 100.0) / 106.0)
    assert structure.ema_slope(series[:5], 5) is None
    assert structure.ema_slope([], 5) is None


# The levels are read up to the prior session: a bar dated the session
# itself (a same-day append) is left out, and fewer than 21 closes give no EMA.
def test_the_levels_stop_at_the_prior_session():
    bars = history([100.0] * 25) + [bar(SESSION, 500.0, 900.0)]
    prior = structure.prior_bars(bars, SESSION)
    assert all(b.session_date < SESSION for b in prior)
    ema_21, slope = structure.ema_levels(prior)
    assert ema_21 == pytest.approx(100.0)
    assert slope == pytest.approx(0.0)
    assert structure.high_20(prior) == pytest.approx(100.0)
    assert structure.ema_levels(prior[:20]) == (None, None)


# The EMA uses the adjusted close, not the raw one.
def test_the_ema_reads_the_adjusted_close():
    bars = [bar(d.session_date, 200.0, adj=100.0) for d in history([0.0] * 30)]
    ema_21, _ = structure.ema_levels(structure.prior_bars(bars, SESSION))
    assert ema_21 == pytest.approx(100.0)


# A first bar whose high reaches within 0.5% of the 21-EMA from below and
# closes back under it is a rejected tag.
def test_a_tag_that_rejects():
    prior = history([100.0] * 29 + [98.0])
    levels = {"ema_21": 100.0, "high_20": 130.0}
    tag = structure.level_tag(levels, 98.0, {"high": 99.6, "close": 98.5}, prior)
    assert tag is not None
    assert tag["level"] == "ema_21"
    assert tag["price"] == pytest.approx(100.0)
    assert tag["first_bar_high"] == pytest.approx(99.6)
    assert tag["first_bar_close"] == pytest.approx(98.5)
    assert tag["rejected"] is True


# A first bar that goes through the level and closes above it is a tag that
# held, not a rejection.
def test_a_tag_that_holds():
    prior = history([100.0] * 29 + [98.0])
    levels = {"ema_21": 100.0, "high_20": 130.0}
    tag = structure.level_tag(levels, 98.0, {"high": 101.2, "close": 100.4}, prior)
    assert tag is not None
    assert tag["level"] == "ema_21"
    assert tag["rejected"] is False


# No tag when the bar stays more than 0.5% under the level, and none when
# the prior close was already over it (that is not "from below").
def test_no_tag_when_the_bar_stays_away_or_the_close_was_already_over():
    prior = history([100.0] * 29 + [98.0])
    levels = {"ema_21": 100.0, "high_20": 130.0}
    assert (
        structure.level_tag(levels, 98.0, {"high": 99.4, "close": 99.0}, prior) is None
    )
    assert (
        structure.level_tag(levels, 100.5, {"high": 101.0, "close": 100.6}, prior)
        is None
    )
    assert structure.level_tag(levels, 98.0, None, prior) is None
    assert (
        structure.level_tag(
            {"ema_21": None, "high_20": None},
            98.0,
            {"high": 99.6, "close": 98.5},
            prior,
        )
        is None
    )


# The 20-session high is tagged too, and when the bar reaches both levels
# the one nearer its high is named.
def test_the_twenty_session_high_is_a_level_and_the_nearer_one_is_named():
    prior = history([100.0] * 29 + [98.0])
    only_high = structure.level_tag(
        {"ema_21": 90.0, "high_20": 100.0}, 98.0, {"high": 99.8, "close": 99.0}, prior
    )
    assert only_high is not None
    assert only_high["level"] == "high_20"
    both = structure.level_tag(
        {"ema_21": 100.0, "high_20": 100.3},
        98.0,
        {"high": 100.25, "close": 99.0},
        prior,
    )
    assert both is not None
    assert both["level"] == "high_20"


# The count is today plus every earlier session in a row whose high was
# within 1% of the level while its close stayed under it; the first session
# away from the level ends it.
def test_consecutive_sessions_walk_back_over_the_highs():
    level = 100.0
    # ... far away, then three sessions at the level (today makes four).
    highs = [90.0] * 26 + [99.5, 100.4, 99.2]
    closes = [89.0] * 26 + [98.0, 99.0, 98.5]
    prior = history(closes, highs)
    assert structure.consecutive_sessions(level, prior) == 4
    # A close over the level breaks the run even with the high at it.
    prior = history([89.0] * 27 + [100.5, 98.5], [90.0] * 27 + [100.6, 99.2])
    assert structure.consecutive_sessions(level, prior) == 2
    # Today alone.
    assert structure.consecutive_sessions(level, history([89.0] * 5, [90.0] * 5)) == 1
    assert structure.consecutive_sessions(level, []) == 1
    tag = structure.level_tag(
        {"ema_21": level, "high_20": 200.0},
        98.5,
        {"high": 99.6, "close": 99.0},
        history(closes, highs),
    )
    assert tag is not None
    assert tag["consecutive_sessions"] == 4


# The opening bar comes from the latch once one exists; before then, only a
# quote whose bar is the 09:30 bar can say what the first bar was.
def test_the_first_bar_is_the_latch_or_the_opening_candle():
    latched = {"first_bar": {"high": 99.6, "close": 98.5, "bar": "x"}}
    assert (
        structure.first_bar_of(quote(97.0, 101.0, 11, 0), latched)
        == latched["first_bar"]
    )
    opening = structure.first_bar_of(quote(98.5, 99.6), None)
    assert opening is not None
    assert opening["high"] == pytest.approx(99.6)
    assert opening["close"] == pytest.approx(98.5)
    assert structure.first_bar_of(quote(98.5, 99.6, 9, 45), None) is None
    assert structure.first_bar_of(None, None) is None


# The latch keeps the opening bar's high and close once it has seen the
# 09:30 candle, and later candles do not overwrite it; a run that starts at
# 09:45 never learns it.
def test_the_latch_keeps_the_opening_bar(tmp_path: Path):
    first = quote(98.5, 99.6, 9, 30)
    second = quote(103.0, 104.0, 9, 45)
    at = datetime(SESSION.year, SESSION.month, SESSION.day, 10, 1, tzinfo=NY)
    entry_timing.update(
        tmp_path, {"as_of": at.isoformat(), "quotes": {"AAA": first}}, at
    )
    entry_timing.update(
        tmp_path, {"as_of": at.isoformat(), "quotes": {"AAA": second}}, at
    )
    row = entry_timing.row_for(entry_timing.load(tmp_path, SESSION), "AAA", SESSION)
    assert row is not None
    assert row["first_bar"]["high"] == pytest.approx(99.6)
    assert row["first_bar"]["close"] == pytest.approx(98.5)
    assert row["last"] == pytest.approx(103.0)
    late = tmp_path / "late"
    entry_timing.update(
        late,
        {"as_of": at.isoformat(), "quotes": {"BBB": {**second, "symbol": "BBB"}}},
        at,
    )
    assert "first_bar" not in entry_timing.row_for(
        entry_timing.load(late, SESSION), "BBB", SESSION
    )


# The price's instant is the bar's end, and its age is measured to `as_of`.
def test_the_price_age_is_from_the_bars_end():
    at = datetime(SESSION.year, SESSION.month, SESSION.day, 11, 42, tzinfo=NY)
    priced, age = structure.price_age(quote(98.5, 99.6, 11, 15), at.astimezone(UTC))
    assert priced == datetime(
        SESSION.year, SESSION.month, SESSION.day, 11, 30, tzinfo=NY
    ).astimezone(UTC).isoformat(timespec="seconds")
    assert age == pytest.approx(12 * 60)
    assert structure.price_age(None, at) == (None, None)
    assert structure.price_age({"bar": "not a time"}, at) == (None, None)
    with pytest.raises(ValueError, match="timezone-aware"):
        structure.price_age(quote(98.5, 99.6), datetime(2026, 9, 30, 12, 0))


# A store that answers with synthetic bars for one name and nothing for another.
class _Store:
    def __init__(self, bars: dict[str, list]):
        self.bars = bars

    def read(self, ticker: str, asof=None):
        if ticker not in self.bars:
            return None
        return type("H", (), {"bars": tuple(self.bars[ticker])})()


# Every row carries the payload fields: the levels from the store, the tag
# from the latch, the price age from the quote; a name the store lacks keeps
# null levels and the record's own 20-session high; the same fields come
# back by ticker for the live snapshot.
def test_the_rows_carry_the_payload_fields():
    at = datetime(
        SESSION.year, SESSION.month, SESSION.day, 11, 42, tzinfo=NY
    ).astimezone(UTC)
    highs = [90.0] * 27 + [99.5, 100.4]
    closes = [89.0] * 27 + [98.0, 98.5]
    store = _Store({"AAA": history(closes, highs)})
    rows = [
        {"ticker": "AAA", "high_20": 55.0},
        {"ticker": "BBB", "high_20": 55.0},
        {"ticker": "CCC", "high_20": None},
    ]
    quotes = {"AAA": quote(97.0, 101.0, 11, 15), "BBB": quote(50.0, 50.0, 11, 15)}
    latch = {
        "session": SESSION.isoformat(),
        "symbols": {"AAA": {"first_bar": {"high": 101.0, "close": 99.0, "bar": "x"}}},
    }
    by_name = structure.annotate(rows, store, quotes, latch, SESSION, at)
    aaa = rows[0]
    expected_ema = structure.ema(closes, 21)[-1]
    assert aaa["ema_21"] == pytest.approx(expected_ema)
    assert aaa["ema_21_slope_5"] == pytest.approx(
        (expected_ema - structure.ema(closes, 21)[-6]) / expected_ema
    )
    assert aaa["high_20"] == pytest.approx(100.4)
    # The first bar went through the 20-session high (100.4) and closed back
    # under it: a rejected tag on that level, the third session at it.
    assert aaa["level_tag"] == {
        "level": "high_20",
        "price": pytest.approx(100.4),
        "first_bar_high": pytest.approx(101.0),
        "first_bar_close": pytest.approx(99.0),
        "rejected": True,
        "consecutive_sessions": 3,
    }
    assert aaa["price_age_seconds"] == pytest.approx(12 * 60)
    assert aaa["price_as_of"].endswith("+00:00")
    bbb = rows[1]
    assert bbb["ema_21"] is None
    assert bbb["ema_21_slope_5"] is None
    assert bbb["high_20"] == pytest.approx(55.0)
    assert bbb["level_tag"] is None
    assert bbb["price_age_seconds"] == pytest.approx(12 * 60)
    ccc = rows[2]
    assert ccc["high_20"] is None
    assert ccc["price_as_of"] is None
    assert ccc["price_age_seconds"] is None
    assert set(by_name) == {"AAA", "BBB", "CCC"}
    assert by_name["AAA"]["level_tag"]["rejected"] is True
    for row in rows:
        for key in (
            "ema_21",
            "ema_21_slope_5",
            "high_20",
            "level_tag",
            "price_as_of",
            "price_age_seconds",
        ):
            assert key in row
    json.dumps(rows)  # the plan is written as JSON


# The balancer writes the fields on its rows and, by name, on live.json,
# with the price age measured against the plan's own `as_of`.
def test_the_balancer_writes_the_structure(tmp_path: Path, monkeypatch):
    import datetime as dt

    from backend.cli import market_balancer

    class _FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 9, 30, 15, 42, tzinfo=dt.UTC)

    monkeypatch.setattr(market_balancer, "datetime", _FakeDT)
    record = {
        "session": "2026-09-29",
        "grades": {"AAA": {"grade": "A", "score": 1.0, "stances": {}, "ranks": {}}},
        "book": [{"ticker": "AAA", "weight": 0.25}],
        "actions": [
            {
                "ticker": "AAA",
                "action": "buy",
                "last_close": 98.5,
                "high_20": 55.0,
                "stops": {},
            }
        ],
        "paper": {"positions": [], "until_rebalance": 10},
    }
    # The record in the layout market_daily writes, as test_market_balancer does.
    record_path = tmp_path / "desk" / "asof=2026-09-29" / "desk.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record), encoding="utf-8")
    q = quote(97.0, 101.0, 11, 15)
    monkeypatch.setattr(market_balancer.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(
        market_balancer.live_quotes, "quotes", lambda *a, **k: {"AAA": q}
    )
    monkeypatch.setattr(market_balancer, "_quote_dict", lambda quote: dict(q))
    monkeypatch.setattr(
        market_balancer.live_technical, "technical_now", lambda *a, **k: {}
    )
    monkeypatch.setattr(market_balancer.live_technical, "value_now", lambda *a, **k: {})
    monkeypatch.setattr(
        market_balancer.live_technical, "technical_detail", lambda *a, **k: {}
    )
    monkeypatch.setattr(market_balancer, "_band_blocked", lambda *a, **k: set())
    monkeypatch.setattr(market_balancer, "_send_paper_orders", lambda *a, **k: None)
    monkeypatch.setattr(market_balancer, "_green_day_skip", lambda *a, **k: None)
    monkeypatch.setattr(market_balancer, "_observe_paper", lambda *a, **k: None)
    from backend.cli import market_event_recovery
    from backend.market import intraday_research

    monkeypatch.setattr(market_event_recovery, "run", lambda *a, **k: None)
    monkeypatch.setattr(intraday_research, "publish", lambda *a, **k: {})
    highs = [90.0] * 27 + [99.5, 100.4]
    closes = [89.0] * 27 + [98.0, 98.5]
    monkeypatch.setattr(
        market_balancer.MarketStore,
        "read",
        lambda self, ticker, asof=None: (
            type("H", (), {"bars": tuple(history(closes, highs))})()
            if ticker == "AAA"
            else None
        ),
    )
    entry_timing.update(
        tmp_path,
        {
            "as_of": "2026-09-30T13:46:00+00:00",
            "quotes": {"AAA": quote(99.0, 101.0, 9, 30)},
        },
        datetime(2026, 9, 30, 13, 46, tzinfo=UTC),
    )

    path = market_balancer.run(tmp_path, 100_000.0)
    plan = json.loads(path.read_text(encoding="utf-8"))
    row = next(r for r in plan["rows"] if r["ticker"] == "AAA")
    assert row["ema_21"] == pytest.approx(structure.ema(closes, 21)[-1])
    assert row["high_20"] == pytest.approx(100.4)
    assert row["level_tag"]["level"] == "high_20"
    assert row["level_tag"]["rejected"] is True
    assert row["level_tag"]["consecutive_sessions"] == 3
    # The 11:15 bar closed at 11:30 ET (15:30Z); the run is at 15:42Z.
    assert row["price_as_of"] == "2026-09-30T15:30:00+00:00"
    assert row["price_age_seconds"] == pytest.approx(12 * 60)
    live = json.loads((tmp_path / "desk" / "live.json").read_text(encoding="utf-8"))
    assert live["structure"]["AAA"]["level_tag"] == row["level_tag"]
    assert live["structure"]["AAA"]["ema_21"] == pytest.approx(row["ema_21"])


# The window is the one the record's `high_20` is built from.
def test_the_high_window_is_the_records():
    actions = pytest.importorskip("backend.agents.trading.desk.actions")
    assert structure.HIGH_WINDOW == actions.HIGH_WINDOW
