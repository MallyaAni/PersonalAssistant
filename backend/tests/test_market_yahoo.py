"""The Yahoo fetcher: parsing, the in-progress session, actions, retries.

Every test here runs with no network: the parser is a pure function over a
payload in Yahoo's real shape, and the fetch takes its transport, sleep and
clock as parameters.
"""

import json
from datetime import UTC, date, datetime

import pytest

from backend.market.yahoo import (
    MarketDataUnavailableError,
    Pacer,
    chart_url,
    fetch_history,
    parse_chart_payload,
)

NY_OPEN_UTC_HOUR = 13  # 9:30 New York is 13:30 UTC in summer


# A Unix timestamp for the New York open on a date.
def _open_ts(day: date) -> int:
    return int(
        datetime(
            day.year, day.month, day.day, NY_OPEN_UTC_HOUR, 30, tzinfo=UTC
        ).timestamp()
    )


# A Unix timestamp for the New York close (16:00, 20:00 UTC in summer).
def _close_ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 20, 0, tzinfo=UTC).timestamp())


# A chart payload in Yahoo's real shape for consecutive sessions from
# `first`, with the market clock set to `market_time` and the regular
# session ending at `regular_end`.
def _payload(
    closes: list[float],
    first: date = date(2026, 8, 24),
    adjcloses: list[float] | None = None,
    market_time: int | None = None,
    regular_end: int | None = None,
    events: dict | None = None,
) -> dict:
    days = [date.fromordinal(first.toordinal() + i) for i in range(len(closes))]
    timestamps = [_open_ts(d) for d in days]
    last = days[-1]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "ZZZZA",
                        "exchangeTimezoneName": "America/New_York",
                        "regularMarketTime": (
                            market_time if market_time is not None else _close_ts(last)
                        ),
                        "currentTradingPeriod": {
                            "regular": {
                                "start": _open_ts(last),
                                "end": (
                                    regular_end
                                    if regular_end is not None
                                    else _close_ts(last)
                                ),
                            }
                        },
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": closes,
                                "high": [c * 1.02 for c in closes],
                                "low": [c * 0.98 for c in closes],
                                "close": closes,
                                "volume": [1_000_000] * len(closes),
                            }
                        ],
                        "adjclose": [{"adjclose": adjcloses or closes}],
                    },
                    "events": events or {},
                }
            ],
            "error": None,
        }
    }


# The parser keeps completed sessions in order with their exchange-local dates.
def test_parser_reads_completed_sessions_oldest_first():
    history = parse_chart_payload(
        _payload([10.0, 11.0, 12.0]), "ZZZZA", now=datetime(2026, 8, 27, tzinfo=UTC)
    )
    assert [b.session_date for b in history.bars] == [
        date(2026, 8, 24),
        date(2026, 8, 25),
        date(2026, 8, 26),
    ]
    assert history.bars[0].close == 10.0
    assert history.bars[-1].adjusted_close == 12.0
    assert history.complete_through == date(2026, 8, 26)
    assert history.bars[0].volume == 1_000_000


# A bar for a session that has not ended is the live day, not a close.
def test_parser_drops_the_in_progress_session():
    last = date(2026, 8, 26)
    two_pm = int(datetime(2026, 8, 26, 18, 0, tzinfo=UTC).timestamp())
    payload = _payload(
        [10.0, 11.0, 12.0], market_time=two_pm, regular_end=_close_ts(last)
    )
    history = parse_chart_payload(payload, "ZZZZA")
    assert [b.session_date for b in history.bars] == [
        date(2026, 8, 24),
        date(2026, 8, 25),
    ]
    assert history.complete_through == date(2026, 8, 25)


# Once the regular session has ended, the same last bar is a real close.
def test_parser_keeps_the_last_bar_after_the_close():
    history = parse_chart_payload(_payload([10.0, 11.0, 12.0]), "ZZZZA")
    assert history.complete_through == date(2026, 8, 26)


# Dividends and splits come through as dated actions, oldest first.
def test_parser_reads_corporate_actions():
    events = {
        "dividends": {"1": {"amount": 0.25, "date": _open_ts(date(2026, 8, 25))}},
        "splits": {
            "2": {
                "date": _open_ts(date(2026, 8, 24)),
                "numerator": 10,
                "denominator": 1,
                "splitRatio": "10:1",
            }
        },
    }
    history = parse_chart_payload(_payload([10.0, 11.0, 12.0], events=events), "ZZZZA")
    assert [(a.action_date, a.kind, a.value) for a in history.actions] == [
        (date(2026, 8, 24), "split", 10.0),
        (date(2026, 8, 25), "dividend", 0.25),
    ]


# A payload with no bars, or an unrecognised shape, is unavailable data.
def test_parser_rejects_empty_or_malformed_payloads():
    with pytest.raises(MarketDataUnavailableError):
        parse_chart_payload({"chart": {"result": [], "error": None}}, "ZZZZA")
    with pytest.raises(MarketDataUnavailableError):
        parse_chart_payload({"chart": {"error": {"description": "blocked"}}}, "ZZZZA")


# A refusal is retried with the server's Retry-After, then captured.
def test_fetch_retries_on_429_and_honours_retry_after():
    calls: list[str] = []
    sleeps: list[float] = []
    responses = iter(
        [
            (429, {"retry-after": "3"}, b""),
            (429, {}, b""),
            (200, {}, json.dumps(_payload([10.0, 11.0])).encode()),
        ]
    )

    def transport(url):
        calls.append(url)
        return next(responses)

    history = fetch_history(
        "ZZZZA",
        date(2026, 8, 1),
        date(2026, 8, 31),
        transport=transport,
        sleep=sleeps.append,
        pacer=Pacer(min_interval=0, sleep=sleeps.append, clock=lambda: 0.0),
    )
    assert len(calls) == 3
    assert len(history.bars) == 2
    assert sleeps[0] == 3.0  # Retry-After honoured on the first refusal
    assert sleeps[1] == 4.0  # exponential from 2 s on the second


# After the attempt budget, the refusal is an error the caller can flag.
def test_fetch_gives_up_after_the_attempt_budget():
    def refuse(url):
        return 429, {}, b""

    with pytest.raises(MarketDataUnavailableError, match="refused after 2 attempts"):
        fetch_history(
            "ZZZZA",
            date(2026, 8, 1),
            date(2026, 8, 31),
            transport=refuse,
            sleep=lambda s: None,
            pacer=Pacer(min_interval=0, sleep=lambda s: None, clock=lambda: 0.0),
            max_attempts=2,
        )


# An unknown symbol is not retried.
def test_fetch_does_not_retry_an_unknown_symbol():
    calls = []

    def missing(url):
        calls.append(url)
        return 404, {}, b""

    with pytest.raises(MarketDataUnavailableError, match="404"):
        fetch_history(
            "ZZZZA",
            date(2026, 8, 1),
            date(2026, 8, 31),
            transport=missing,
            sleep=lambda s: None,
        )
    assert len(calls) == 1


# The pacer keeps requests at least the interval apart on the injected clock.
def test_pacer_spaces_requests():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    pacer = Pacer(min_interval=0.5, sleep=sleep, clock=lambda: now[0])
    pacer.wait()
    now[0] += 0.1
    pacer.wait()
    assert sleeps == [pytest.approx(0.4)]


# The URL carries the range as epoch bounds and asks for corporate actions.
def test_chart_url_uses_epoch_bounds_and_events():
    url = chart_url("CRWV", date(2026, 1, 1), date(2026, 1, 31))
    assert "period1=" in url
    assert "period2=" in url
    assert "range=" not in url
    assert "events=div%7Csplit" in url
    assert url.startswith("https://query1.finance.yahoo.com/v8/finance/chart/CRWV?")
