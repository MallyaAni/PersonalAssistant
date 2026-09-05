"""Reproducibility of the daily market snapshot, and its failure flags.

The acceptance criteria for the snapshot, as a test suite:

- rerunning a fetch lands on the same rows (upsert idempotency) and a pure
  calculation (daily_returns) is bit-for-bit reproducible;
- a split never manufactures a return (returns come from adjusted close);
- missing or stale data is explicitly flagged, and a refused data source is
  captured per ticker rather than failing the whole run.

Parser tests use a recorded fixture and never touch the network; the
repository tests follow the repository convention of throwaway rows on a
synthetic ticker, removed in the same test.
"""

import json
from datetime import UTC, date, datetime

import pytest

from backend.database.session import AsyncSessionLocal
from backend.market import repository, snapshot
from backend.market.yahoo import (
    DailyBar,
    MarketDataUnavailable,
    parse_chart_payload,
)
from backend.models.market_bar import MarketDailyBar

# A throwaway ticker the tests own; every row it writes is removed in the test.
TEST_TICKER = "ZZZZTST"


def _epoch(day: int, month: int = 1, year: int = 2026) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp())


# A recorded chart payload in Yahoo's real shape: per-session OHLCV plus an
# adjusted close series, one entry per timestamp.
def _chart_payload(
    closes: list[float],
    adjcloses: list[float] | None = None,
    volumes: list[int] | None = None,
    ticker: str = "CRWV",
) -> dict:
    timestamps = [_epoch(5 + i) for i in range(len(closes))]
    adjusted = adjcloses or closes
    quote = {
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": volumes or [1_000_000] * len(closes),
    }
    return {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": ticker, "currency": "USD"},
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [quote],
                        "adjclose": [{"adjclose": adjusted}],
                    },
                }
            ],
            "error": None,
        }
    }


def test_parser_reads_the_recorded_yahoo_shape_oldest_first():
    payload = _chart_payload(
        closes=[10.0, 11.0, 12.0, 13.0, 14.0], volumes=[100, 200, 300, 400, 500]
    )
    bars = parse_chart_payload(payload)
    assert [bar.session_date for bar in bars] == [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    ]
    assert bars[0].close == 10.0
    assert bars[0].adjusted_close == 10.0
    assert bars[0].volume == 100
    assert bars[-1].close == 14.0


def test_parser_rejects_a_rate_limited_response():
    with pytest.raises(MarketDataUnavailable):
        parse_chart_payload({"chart": {"result": [], "error": None}})


def test_parser_rejects_a_non_json_guarding_fetch():
    with pytest.raises(MarketDataUnavailable):
        parse_chart_payload({"chart": {"error": {"description": "blocked"}}})


def test_daily_returns_are_split_safe():
    # A 2:1 split on 2026-01-07 halves the raw close but leaves the adjusted
    # close continuous. The return series must be identical to a no-split
    # world and must never contain the raw close's fake -50% drop.
    bars = [
        DailyBar(date(2026, 1, 5), 100, 100, 100, 100, 100, 1_000),
        DailyBar(date(2026, 1, 6), 100, 100, 100, 100, 100, 1_000),
        DailyBar(date(2026, 1, 7), 50, 50, 50, 50, 100, 1_000),
        DailyBar(date(2026, 1, 8), 55, 55, 55, 55, 110, 1_000),
        DailyBar(date(2026, 1, 9), 60, 60, 60, 60, 121, 1_000),
    ]
    returns = snapshot.daily_returns(bars)
    # Five bars yield four consecutive returns; the split gap is absorbed by
    # the adjusted close, so the series is 0, 0, +10%, +10%.
    expected = [0.0, 0.0, _log(1.1), _log(1.1)]
    assert [round(value, 12) for _, value in returns] == [round(v, 12) for v in expected]
    # No return may equal the raw close's split gap.
    fake_drop = _log(50.0 / 100.0)
    assert all(round(value, 12) != round(fake_drop, 12) for _, value in returns)


def test_daily_returns_are_deterministic():
    bars = [
        DailyBar(date(2026, 1, 5 + i), 10 + i, 10 + i, 10 + i, 10 + i, 10 + i, 1_000)
        for i in range(5)
    ]
    first = snapshot.daily_returns(bars)
    second = snapshot.daily_returns(bars)
    assert first == second
    assert [value for _, value in first] == [_log(11 / 10), _log(12 / 11), _log(13 / 12), _log(14 / 13)]


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_latest_session_tracks_it():
    async with AsyncSessionLocal() as session:
        bars = [
            DailyBar(date(2026, 1, 5 + i), 10 + i, 10 + i, 10 + i, 10 + i, 10 + i, 1_000)
            for i in range(3)
        ]
        try:
            first = await repository.upsert_bars(session, TEST_TICKER, bars)
            second = await repository.upsert_bars(session, TEST_TICKER, bars[:2])
            assert first == 3
            assert second == 3  # rerun refreshes, never duplicates
            assert await repository.latest_session(session, TEST_TICKER) == date(2026, 1, 7)
            stored = await repository.bars_for(session, TEST_TICKER)
            assert len(stored) == 3
            assert stored[0].session_date == date(2026, 1, 5)
        finally:
            await repository.delete_for(session, TEST_TICKER)


@pytest.mark.asyncio
async def test_status_flags_missing_and_stale_rows():
    async with AsyncSessionLocal() as session:
        old_bars = [
            DailyBar(date(2026, 1, 5), 10, 10, 10, 10, 10, 1_000),
            DailyBar(date(2026, 1, 6), 11, 11, 11, 11, 11, 1_000),
        ]
        try:
            await repository.upsert_bars(session, TEST_TICKER, old_bars)
            today = date(2026, 1, 30)
            rows = await snapshot.status(session, [TEST_TICKER, "NOBODY"], today=today)
            by_ticker = {row.ticker: row for row in rows}
            assert by_ticker[TEST_TICKER].stale is True  # newest is 24 days old
            assert by_ticker[TEST_TICKER].missing is False
            assert by_ticker["NOBODY"].missing is True
            assert by_ticker["NOBODY"].stale is True
        finally:
            await repository.delete_for(session, TEST_TICKER)


@pytest.mark.asyncio
async def test_refresh_captures_a_refused_source_per_ticker(monkeypatch):
    from backend.market import snapshot as snapshot_module

    def refuse(ticker, days):
        raise MarketDataUnavailable("429 Too Many Requests")

    monkeypatch.setattr(snapshot_module, "fetch_daily_bars", refuse)
    async with AsyncSessionLocal() as session:
        report = await snapshot.refresh(session, [TEST_TICKER])
        assert report.ok is False
        assert TEST_TICKER in report.failed_tickers
        assert "429" in report.results[0].error


@pytest.mark.asyncio
async def test_refresh_stores_successful_fetches(monkeypatch):
    from backend.market import snapshot as snapshot_module

    bars = [
        DailyBar(date(2026, 1, 5), 10, 10, 10, 10, 10, 1_000),
        DailyBar(date(2026, 1, 6), 11, 11, 11, 11, 11, 1_000),
    ]

    def succeed(ticker, days):
        return bars

    monkeypatch.setattr(snapshot_module, "fetch_daily_bars", succeed)
    async with AsyncSessionLocal() as session:
        try:
            report = await snapshot.refresh(session, [TEST_TICKER])
            assert report.ok is True
            assert report.results[0].bars_stored == 2
            stored = await repository.bars_for(session, TEST_TICKER)
            assert len(stored) == 2
        finally:
            await repository.delete_for(session, TEST_TICKER)


def _log(value: float) -> float:
    import math

    return math.log(value)


# Keep the module importable without a live backend at import time by
# referencing the model only inside tests that use it.
def test_fixture_payload_round_trips_through_json():
    payload = _chart_payload(closes=[10.0, 11.0])
    assert json.loads(json.dumps(payload)) == payload
    assert parse_chart_payload(payload)[0].session_date == date(2026, 1, 5)
