"""A provider's newest daily response must preserve previously observed sessions."""

from dataclasses import replace
from datetime import date

from backend.market import snapshot
from backend.market.store import MarketStore
from backend.tests.test_market_store_snapshot import _history


# A transient dropped date is retried once, and only the complete response lands.
def test_refresh_retries_a_disappearing_session_before_writing(tmp_path):
    store = MarketStore(tmp_path)
    previous = _history("AAA", [100, 101, 102])
    store.write(date(2026, 1, 7), previous)
    current = _history("AAA", [100, 101, 102, 103])
    broken = replace(current, bars=current.bars[:1] + current.bars[2:])
    responses = iter((broken, current))
    calls = []

    # Return the observed failure followed by the provider's complete retry.
    def fetch(ticker, start, end):
        calls.append(ticker)
        return next(responses)

    report = snapshot.refresh(store, ["AAA"], date(2026, 1, 8), fetcher=fetch)
    assert report.ok
    assert calls == ["AAA", "AAA"]
    assert store.read("AAA", date(2026, 1, 8)).bars == current.bars
    assert store.read("AAA", date(2026, 1, 7)).bars == previous.bars


# Persistent omissions remain failed and cannot create a falsely complete partition.
def test_repeated_gap_keeps_old_snapshots_and_reports_failure(tmp_path):
    store = MarketStore(tmp_path)
    original = _history("AAA", [100, 101, 102])
    store.write(date(2026, 1, 7), original)
    broken = replace(original, bars=original.bars[:1] + original.bars[2:])
    # An already-bad later snapshot must not erase the earlier date evidence.
    store.write(date(2026, 1, 8), broken)
    calls = []

    # Repeat the same incomplete history without touching the stored partitions.
    def fetch(ticker, start, end):
        calls.append(ticker)
        return broken

    report = snapshot.refresh(store, ["AAA"], date(2026, 1, 9), fetcher=fetch)
    assert report.failed_tickers == ("AAA",)
    assert "2026-01-06" in report.results[0].error
    assert calls == ["AAA", "AAA"]
    assert not store.has(date(2026, 1, 9), "AAA")
    assert store.read("AAA", date(2026, 1, 7)).bars == original.bars


# A narrower requested range may intentionally omit older stored sessions.
def test_preservation_respects_request_range_and_ignores_later_vintages(tmp_path):
    store = MarketStore(tmp_path)
    original = _history("AAA", [100, 101, 102])
    store.write(date(2026, 1, 7), original)
    store.write(date(2026, 2, 1), _history("AAA", [100] * 10))
    observed = store.observed_sessions(
        "AAA", date(2026, 1, 6), date(2026, 1, 8), date(2026, 1, 7)
    )
    assert observed == frozenset((date(2026, 1, 6), date(2026, 1, 7)))
    trimmed = replace(original, bars=original.bars[1:])

    # Supply exactly the explicitly requested shorter history.
    def fetch(ticker, start, end):
        return trimmed

    report = snapshot.refresh(
        store, ["AAA"], date(2026, 1, 8), start=date(2026, 1, 6), fetcher=fetch
    )
    assert report.ok
    assert store.read("AAA", date(2026, 1, 8)).bars == trimmed.bars
