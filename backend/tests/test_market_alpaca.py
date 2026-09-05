"""The 15-minute layer: page parsing, session grouping, session features."""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import alpaca
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory


# Regular-session 15-minute bars for one New York day (26 bars, 09:30-15:45
# starts), following a close path, plus two pre-market bars to be ignored.
def _day(
    session: date, closes: list[float], volumes: list[float] | None = None
) -> list[dict]:
    rows = []
    volumes = volumes or [1000.0] * len(closes)
    base = datetime(
        session.year, session.month, session.day, 13, 30, tzinfo=UTC
    )  # 09:30 EDT
    rows.append(
        {
            "t": (base - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            "o": 1,
            "h": 1,
            "l": 1,
            "c": 1,
            "v": 5,
        }
    )
    for i, c in enumerate(closes):
        start = base + timedelta(minutes=15 * i)
        o = closes[i - 1] if i else c
        rows.append(
            {
                "t": start.isoformat().replace("+00:00", "Z"),
                "o": o,
                "h": max(o, c) * 1.001,
                "l": min(o, c) * 0.999,
                "c": c,
                "v": volumes[i],
            }
        )
    return rows


# A page parses into bars in order, with the token passed through.
def test_page_parses_bars_and_token():
    session = date(2025, 6, 3)
    payload = {
        "bars": {"SNDK": _day(session, [100.0, 101.0, 102.0])},
        "next_page_token": "abc",
    }
    bars, token = alpaca.parse_bars_page(payload, "SNDK")
    assert token == "abc"
    assert len(bars) == 4  # three regular plus the pre-market one
    assert bars[1].close == 100.0
    assert bars[1].start.tzinfo is not None


# Regular hours only, grouped by New York date.
def test_sessions_group_regular_hours_by_new_york_date():
    session = date(2025, 6, 3)
    payload = {"bars": {"SNDK": _day(session, [100.0] * 26)}}
    bars, _ = alpaca.parse_bars_page(payload, "SNDK")
    grouped = alpaca.sessions(bars)
    assert list(grouped) == [session]
    assert len(grouped[session]) == 26  # the 09:00 pre-market bar dropped


# A trending session and a reversing session read as such.
def test_session_features_read_trend_and_reversal():
    up = [100 + i for i in range(26)]
    feats = alpaca.session_features(
        alpaca.parse_bars_page({"bars": {"X": _day(date(2025, 6, 3), up)}}, "X")[0][1:]
    )
    names = alpaca.FEATURE_NAMES
    assert feats[names.index("intraday_trend")] > 0.9
    assert feats[names.index("bars_above_ema9")] > 0.9
    assert feats[names.index("intraday_reversal")] == 1.0
    assert feats[names.index("intraday_range_position")] > 0.95
    assert feats[names.index("ema9_crosses")] <= 1
    reversing = [100 + i for i in range(13)] + [112 - i for i in range(13)]
    feats2 = alpaca.session_features(
        alpaca.parse_bars_page({"bars": {"X": _day(date(2025, 6, 3), reversing)}}, "X")[
            0
        ][1:]
    )
    assert feats2[names.index("intraday_reversal")] == -1.0
    assert feats2[names.index("intraday_range_position")] < 0.2
    # Too few bars: NaN.
    assert np.isnan(alpaca.session_features([])).all()


# Features align to the daily panel by session and fill zeros elsewhere.
def test_intraday_features_align_to_the_panel():
    first = date(2025, 6, 2)
    bars_daily = []
    day = first
    while len(bars_daily) < 5:
        if day.weekday() < 5:
            bars_daily.append(DailyBar(day, 100, 101, 99, 100, 100, 1_000_000))
        day += timedelta(days=1)
    history = TickerHistory(
        "SNDK",
        tuple(bars_daily),
        (),
        bars_daily[-1].session_date,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    spy = TickerHistory(
        "SPY",
        tuple(bars_daily),
        (),
        bars_daily[-1].session_date,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    panel = panel_from_histories({"SNDK": history, "SPY": spy}, "SPY", {})
    session = date(2025, 6, 3)
    bars, _ = alpaca.parse_bars_page(
        {"bars": {"SNDK": _day(session, [100 + i for i in range(26)])}}, "SNDK"
    )
    feats = alpaca.intraday_features(panel, {"SNDK": bars})
    t = list(panel.dates.astype("datetime64[D]").astype(object)).index(session)
    c = panel.index("SNDK")
    assert feats[t, c, alpaca.FEATURE_NAMES.index("has_intraday")] == 1.0
    assert feats[t - 1, c, alpaca.FEATURE_NAMES.index("has_intraday")] == 0.0
    assert feats[:, panel.index("SPY"), :].max() == 0.0
    # The frame round-trips.
    rebuilt = alpaca.bars_from_frame(alpaca.bars_frame(bars))
    assert rebuilt == bars
