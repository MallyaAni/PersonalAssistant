"""The as-of store and the snapshot layer over it.

The acceptance criteria: a partition is written once and read back exactly;
a second write of the same (as-of, ticker) is a no-op, never an overwrite;
reading as of an earlier date returns the earlier fetch even after a newer
one lands; a refresh captures a refused ticker per ticker, resumes past
what is stored, and status flags stale and missing names.
"""

from datetime import UTC, date, datetime, timedelta

from backend.market import snapshot
from backend.market.store import MarketStore
from backend.market.yahoo import (
    CorporateAction,
    DailyBar,
    MarketDataUnavailableError,
    TickerHistory,
)


# A history of consecutive sessions from `first` with the given closes.
def _history(
    ticker: str, closes: list[float], first: date = date(2026, 1, 5), actions=()
) -> TickerHistory:
    bars = tuple(
        DailyBar(first + timedelta(days=i), c, c * 1.01, c * 0.99, c, c, 1_000 + i)
        for i, c in enumerate(closes)
    )
    return TickerHistory(
        ticker=ticker,
        bars=bars,
        actions=tuple(actions),
        complete_through=bars[-1].session_date,
        source_time=datetime(2026, 1, 10, tzinfo=UTC),
    )


# Written bars and actions come back exactly, with their metadata.
def test_store_round_trips_bars_actions_and_metadata(tmp_path):
    store = MarketStore(tmp_path)
    history = _history(
        "ZZZZA",
        [10.0, 11.0, 12.0],
        actions=[CorporateAction(date(2026, 1, 6), "dividend", 0.5)],
    )
    assert store.write(date(2026, 1, 8), history) is True
    read = store.read("ZZZZA")
    assert read is not None
    assert read.bars == history.bars
    assert read.actions == history.actions
    assert read.complete_through == date(2026, 1, 7)
    assert read.source_time == history.source_time
    assert store.tickers(date(2026, 1, 8)) == ["ZZZZA"]


# A partition is immutable: the second write is refused and the first stays.
def test_store_never_overwrites_a_partition(tmp_path):
    store = MarketStore(tmp_path)
    asof = date(2026, 1, 8)
    assert store.write(asof, _history("ZZZZA", [10.0, 11.0])) is True
    assert store.write(asof, _history("ZZZZA", [99.0, 98.0, 97.0])) is False
    assert [b.close for b in store.read("ZZZZA", asof).bars] == [10.0, 11.0]


# Reading as of an earlier date returns the earlier fetch, even after a newer
# partition with different (back-adjusted) values has landed.
def test_store_reads_point_in_time(tmp_path):
    store = MarketStore(tmp_path)
    store.write(date(2026, 1, 8), _history("ZZZZA", [10.0, 11.0]))
    store.write(date(2026, 2, 8), _history("ZZZZA", [9.5, 10.45, 11.0]))
    assert [b.close for b in store.read("ZZZZA", date(2026, 1, 20)).bars] == [
        10.0,
        11.0,
    ]
    assert [b.close for b in store.read("ZZZZA", date(2026, 2, 8)).bars] == [
        9.5,
        10.45,
        11.0,
    ]
    assert [b.close for b in store.read("ZZZZA").bars] == [9.5, 10.45, 11.0]
    assert store.read("ZZZZA", date(2025, 12, 31)) is None
    assert store.asofs() == [date(2026, 1, 8), date(2026, 2, 8)]


# A refresh captures a refused ticker, stores the rest, and skips what the
# partition already holds on a rerun.
def test_refresh_captures_failures_and_resumes(tmp_path):
    store = MarketStore(tmp_path)
    fetched: list[str] = []

    def fetcher(ticker, start, end):
        fetched.append(ticker)
        if ticker == "ZZZZB":
            raise MarketDataUnavailableError("429 Too Many Requests")
        return _history(ticker, [10.0, 11.0])

    first = snapshot.refresh(
        store, ["ZZZZA", "ZZZZB"], asof=date(2026, 1, 8), fetcher=fetcher
    )
    assert first.ok is False
    assert first.failed_tickers == ("ZZZZB",)
    assert first.stored_count == 1
    assert "429" in first.results[1].error

    second = snapshot.refresh(
        store, ["ZZZZA", "ZZZZB"], asof=date(2026, 1, 8), fetcher=fetcher
    )
    assert second.results[0].skipped is True
    assert fetched == ["ZZZZA", "ZZZZB", "ZZZZB"]  # A was not fetched again


# Status flags a stale ticker and a missing one, judged against `today`.
def test_status_flags_stale_and_missing(tmp_path):
    store = MarketStore(tmp_path)
    store.write(date(2026, 1, 8), _history("ZZZZA", [10.0, 11.0]))
    rows = {
        r.ticker: r
        for r in snapshot.status(store, ["ZZZZA", "NOBODY"], today=date(2026, 1, 30))
    }
    assert rows["ZZZZA"].missing is False
    assert rows["ZZZZA"].stale is True  # complete through Jan 6, 24 days old
    assert rows["ZZZZA"].bar_count == 2
    assert rows["ZZZZA"].first_session == date(2026, 1, 5)
    assert rows["NOBODY"].missing is True
    assert rows["NOBODY"].stale is True
    fresh = snapshot.status(store, ["ZZZZA"], today=date(2026, 1, 9))[0]
    assert fresh.stale is False


# A split leaves the adjusted-close return series continuous.
def test_daily_returns_are_split_safe():
    bars = [
        DailyBar(date(2026, 1, 5), 100, 100, 100, 100, 100, 1_000),
        DailyBar(date(2026, 1, 6), 100, 100, 100, 100, 100, 1_000),
        DailyBar(date(2026, 1, 7), 50, 50, 50, 50, 100, 1_000),
        DailyBar(date(2026, 1, 8), 55, 55, 55, 55, 110, 1_000),
    ]
    returns = [round(v, 12) for _, v in snapshot.daily_returns(bars)]
    import math

    assert returns == [0.0, 0.0, round(math.log(1.1), 12)]
