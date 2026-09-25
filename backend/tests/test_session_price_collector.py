"""Background collection works without browser traffic and drains active writes."""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from functools import partial

import pytest

from backend.market import session_price_snapshot, session_prices
from backend.services.session_price_collector import SessionPriceCollector


# Wait for an observable state transition without sleeping through a whole poll period.
async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


# Create only the public graded-universe record the collector is allowed to read.
def graded_root(tmp_path):
    folder = tmp_path / "desk" / "asof=2026-09-24"
    folder.mkdir(parents=True)
    (folder / "desk.json").write_text(json.dumps({"grades": {"AAA": {}, "BBB": {}}}))
    return tmp_path


# Build genuine display validation output from synthetic, independently dated quotes.
def envelope(symbols, stamp):
    return {
        "session": session_prices.session_window(stamp)[0],
        "as_of": stamp.isoformat(),
        "signal_scope": "regular-session",
        "quotes": {
            symbol: session_prices.describe(
                {"bp": 100, "ap": 102, "bs": 10, "as": 10, "t": stamp.isoformat()},
                "sip",
                stamp,
            )
            for symbol in symbols
        },
    }


# Use no real credentials while exercising the actual start/stop methods.
@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setattr(session_prices.alpaca, "credentials", lambda: {})


# Prove real latest-state publication before any browser or HTTP client exists.
@pytest.mark.asyncio
async def test_background_collection_persists_without_a_browser_and_expires(tmp_path):
    root = graded_root(tmp_path)
    calls = []

    # Return one dated display batch and audit the exact public universe requested.
    def fetch(symbols):
        calls.append(tuple(symbols))
        return envelope(symbols, datetime.now(UTC))

    collector = SessionPriceCollector(
        root,
        interval_seconds=0.05,
        collect=partial(session_price_snapshot.collect, fetch=fetch),
    )
    collector.start()
    collector.start()
    try:
        await eventually(
            lambda: session_price_snapshot.read(root, ["AAA"])["as_of"] is not None
        )
        first = session_price_snapshot.read(root, ["AAA"])
        await eventually(lambda: len(calls) >= 2)
    finally:
        await collector.stop()
    assert calls
    assert all(symbols == ("AAA", "BBB") for symbols in calls)
    stored = session_price_snapshot.read(root, ["AAA"])
    assert stored["quotes"]["AAA"]["price"] == 101
    assert stored["signal_scope"] == "regular-session"
    assert "eligible" not in stored["quotes"]["AAA"]
    stamp = datetime.fromisoformat(stored["as_of"])
    expired = session_price_snapshot.read(
        root, ["AAA"], now=stamp + timedelta(seconds=61)
    )
    assert expired["as_of"] == stored["as_of"]
    assert expired["quotes"]["AAA"]["at"] == stored["quotes"]["AAA"]["at"]
    assert expired["quotes"]["AAA"]["price"] is None
    assert expired["quotes"]["AAA"]["status"] != "fresh"
    assert first["as_of"] <= stored["as_of"]
    stopped_count = len(calls)
    await asyncio.sleep(0.08)
    assert len(calls) == stopped_count


# Shutdown cannot return while the thread can still publish a later snapshot.
@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_task", [False, True])
async def test_shutdown_drains_an_inflight_pass(tmp_path, cancel_task):
    root = graded_root(tmp_path)
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    calls = []

    # Hold a bounded synthetic write so shutdown ordering can be observed directly.
    def collect(root, symbols, interval_seconds):
        calls.append(tuple(symbols))
        started.set()
        assert release.wait(3)
        (root / "completed.json").write_text(json.dumps({"symbols": symbols}))
        completed.set()

    collector = SessionPriceCollector(root, interval_seconds=0.02, collect=collect)
    collector.start()
    await eventually(started.is_set)
    if cancel_task:
        collector._task.cancel()
    stopping = asyncio.create_task(collector.stop())
    try:
        await asyncio.sleep(0.03)
        assert not stopping.done()
        assert not completed.is_set()
    finally:
        release.set()
        await asyncio.wait_for(stopping, timeout=3)
    assert completed.is_set()
    assert json.loads((root / "completed.json").read_text())["symbols"] == [
        "AAA",
        "BBB",
    ]
    await asyncio.sleep(0.05)
    assert len(calls) == 1


# Missing configuration and explicit disablement never cause collection or disk writes.
@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_disabled_or_unconfigured_start_is_inactive(
    tmp_path, monkeypatch, enabled
):
    calls = []

    # Treat absent credentials exactly as the production helper does, without secrets.
    def missing_credentials():
        raise RuntimeError("Credentials unavailable")

    monkeypatch.setattr(session_prices.alpaca, "credentials", missing_credentials)
    collector = SessionPriceCollector(
        tmp_path, enabled=enabled, collect=lambda *a, **k: calls.append(True)
    )
    collector.start()
    await collector.stop()
    assert calls == []
    assert list(tmp_path.iterdir()) == []


# A transient pass failure is isolated and cannot permanently stop future collection.
@pytest.mark.asyncio
async def test_failed_pass_recovers_and_logs_no_exception_contents(tmp_path, caplog):
    root = graded_root(tmp_path)
    calls = []

    # Fail one pass with sensitive-looking text that must never enter log output.
    def collect(root, symbols, interval_seconds):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("DO_NOT_LOG_PROVIDER_BODY")
        (root / "recovered.json").write_text(json.dumps({"symbols": symbols}))

    collector = SessionPriceCollector(root, interval_seconds=0.02, collect=collect)
    collector.start()
    try:
        await eventually(lambda: (root / "recovered.json").exists())
    finally:
        await collector.stop()
    assert len(calls) >= 2
    assert "DO_NOT_LOG_PROVIDER_BODY" not in caplog.text
    assert "will retry" in caplog.text


# Returned storage failures are visible once per transition, without response contents.
@pytest.mark.asyncio
async def test_returned_failures_are_sanitized_and_recovery_is_reported(
    tmp_path, caplog
):
    caplog.set_level("INFO")
    statuses = iter(
        [
            "unavailable",
            "unavailable",
            "not_due",
            "busy",
            "failed",
            "failed",
            "collected",
        ]
    )
    calls = []

    # Exercise both non-raising failures and idle ticks before a recovered publication.
    def collect(*args, **kwargs):
        status = next(statuses, "collected")
        calls.append(status)
        return {"status": status, "provider_body": "DO_NOT_LOG_PROVIDER_BODY"}

    collector = SessionPriceCollector(tmp_path, interval_seconds=0.005, collect=collect)
    collector.start()
    try:
        await eventually(lambda: "collected" in calls)
    finally:
        await collector.stop()
    messages = [record.message for record in caplog.records]
    assert messages == [
        "Display-price collection unavailable; will retry",
        "Display-price collection failed; will retry",
        "Display-price snapshot publication recovered",
    ]
    assert "DO_NOT_LOG_PROVIDER_BODY" not in caplog.text


# Unsupported file-locking hosts keep the backend usable without unsafe collection.
@pytest.mark.asyncio
async def test_unsupported_locking_skips_collection_and_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(session_price_snapshot, "supported", lambda: False)

    # Neither secrets nor provider work are needed when safe publication is unavailable.
    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported collector must stay inactive")

    monkeypatch.setattr(session_prices.alpaca, "credentials", forbidden)
    collector = SessionPriceCollector(tmp_path, collect=forbidden)
    collector.start()
    await collector.stop()
    assert list(tmp_path.iterdir()) == []
