"""Offline acceptance for bounded, process-shared display-price persistence."""

import json
import multiprocessing
import os
import stat
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta, tzinfo
from itertools import repeat

import pytest

from backend.market import session_price_snapshot as store

NOW = datetime(2026, 9, 25, 15, tzinfo=UTC)


# Build dated synthetic public evidence without touching a data provider.
def _capture(symbols, captured=NOW, feed="iex", session="regular", price=100.0):
    observed = captured - timedelta(seconds=1)
    return {
        "session": session,
        "as_of": captured.isoformat(),
        "signal_scope": "regular-session",
        "quotes": {
            symbol: {
                "price": price,
                "bid": price - 0.5,
                "ask": price + 0.5,
                "at": observed.isoformat(),
                "valid_until": (observed + timedelta(seconds=60)).isoformat(),
                "feed": feed,
                "session": session,
                "indicative": feed == "overnight",
                "status": "fresh",
                "reason": (
                    "Indicative midpoint" if feed == "overnight" else "Quoted midpoint"
                ),
            }
            for symbol in symbols
        },
    }


# Wrap a synthetic capture with the same persisted metadata a collector writes.
def _wrapper(symbols=("AAA",), captured=NOW):
    return {
        "version": 1,
        "attempted_at": captured.isoformat(),
        "completed_at": captured.isoformat(),
        "symbols": list(symbols),
        "snapshot": _capture(symbols, captured),
    }


# Seed only this test's latest file so malformed persisted records exercise the reader.
def _persist(root, payload):
    folder = root / "desk" / "session-prices"
    folder.mkdir(parents=True, exist_ok=True)
    latest = folder / "latest.json"
    latest.write_text(json.dumps(payload))
    return latest


# Fail any forbidden fetch without importing or invoking provider transport.
def _forbidden(symbols):
    raise AssertionError(f"unexpected fetch for {symbols!r}")


# Keep a child process inside a synthetic fetch while another process checks its lock.
def _held_collection(root, started, release, outcome):
    # Hold only this synthetic provider boundary until the parent releases it.
    def fetch(symbols):
        started.set()
        if not release.wait(10):
            raise TimeoutError("test did not release collection")
        return _capture(symbols)

    outcome.put(store.collect(root, ["AAA"], fetch=fetch, clock=lambda: NOW))


# Run a potentially corrupt-file read in a separate process with a parent-owned timeout.
def _isolated_read(root, outcome):
    outcome.put(store.read(root, ["AAA"], now=NOW))


# Persist and reopen independent of browser activity while retaining only public fields.
def test_collection_persists_minimized_snapshot_for_read_only_consumers(
    tmp_path, monkeypatch
):
    captured = _capture(["AAA", "BBB"])
    captured["secret"] = "discard this envelope field"
    captured["quotes"]["AAA"]["secret"] = "discard this row field"
    calls = []

    # Record the exact bounded universe requested by collection.
    def fetch(symbols):
        calls.append(symbols)
        return captured

    outcome = store.collect(
        tmp_path, ["BBB", "AAA", "AAA"], fetch=fetch, clock=lambda: NOW
    )
    assert outcome == {
        "status": "collected",
        "attempted_at": NOW.isoformat(),
        "completed_at": NOW.isoformat(),
    }
    folder = tmp_path / "desk" / "session-prices"
    latest = folder / "latest.json"
    before = latest.read_bytes(), latest.stat().st_mtime_ns
    monkeypatch.setattr(store.session_prices, "fetch", _forbidden)
    read = store.read(tmp_path, ["AAA", "CCC"], now=NOW + timedelta(seconds=2))
    assert calls == [["AAA", "BBB"]]
    assert read["as_of"] == NOW.isoformat()
    assert set(read["quotes"]) == {"AAA", "CCC"}
    assert read["quotes"]["AAA"]["price"] == 100.0
    assert read["quotes"]["CCC"]["status"] == "unavailable"
    assert read["quotes"]["CCC"]["price"] is None
    assert "secret" not in latest.read_text()
    assert before == (latest.read_bytes(), latest.stat().st_mtime_ns)
    assert {path.name for path in folder.iterdir()} == {"latest.json", "collector.lock"}
    assert stat.S_IMODE(latest.stat().st_mode) == 0o600
    assert stat.S_IMODE((folder / "collector.lock").stat().st_mode) == 0o600


# Missing storage is unavailable and a read must not create the collection directory.
def test_missing_store_has_no_invented_capture_or_writes(tmp_path):
    read = store.read(tmp_path, ["AAA"], now=NOW)
    assert read["as_of"] is None
    assert read["session"] == "unknown"
    assert read["signal_scope"] == "regular-session"
    assert read["quotes"]["AAA"]["price"] is None
    assert list(tmp_path.iterdir()) == []


# Preserve capture time and expire prices at the original 60-second boundary.
@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [(0, "fresh"), (58.999, "fresh"), (59, "stale"), (60, "stale"), (3600, "stale")],
)
def test_read_ages_original_observation_without_restamping(tmp_path, elapsed, expected):
    payload = _wrapper()
    latest = _persist(tmp_path, payload)
    original = latest.read_bytes()
    read = store.read(tmp_path, ["AAA"], now=NOW + timedelta(seconds=elapsed))
    row = read["quotes"]["AAA"]
    assert read["as_of"] == payload["snapshot"]["as_of"]
    assert row["at"] == payload["snapshot"]["quotes"]["AAA"]["at"]
    assert row["status"] == expected
    assert row["price"] == (100.0 if expected == "fresh" else None)
    assert row["feed"] == "iex"
    assert row["valid_until"] == payload["snapshot"]["quotes"]["AAA"]["valid_until"]
    assert latest.read_bytes() == original


# Retain source-session evidence, including unknown, without calendar recomputation.
@pytest.mark.parametrize("feed", ["sip", "iex", "boats", "overnight"])
@pytest.mark.parametrize(
    "session",
    ["regular", "pre-market", "post-market", "overnight", "closed", "unknown"],
)
def test_read_preserves_each_feed_and_recorded_session(tmp_path, feed, session):
    payload = _wrapper()
    payload["snapshot"] = _capture(["AAA"], feed=feed, session=session)
    _persist(tmp_path, payload)
    read = store.read(tmp_path, ["AAA"], now=NOW)
    row = read["quotes"]["AAA"]
    assert (read["session"], row["session"]) == (session, session)
    assert (row["feed"], row["indicative"], row["status"]) == (
        feed,
        feed == "overnight",
        "fresh",
    )


# A later wall clock may age a capture but must not rewrite its original timezone text.
def test_capture_text_and_distinct_row_session_are_preserved(tmp_path):
    payload = _wrapper()
    payload["snapshot"]["as_of"] = "2026-09-25T11:00:00-04:00"
    payload["snapshot"]["session"] = "regular"
    payload["snapshot"]["quotes"]["AAA"]["session"] = "unknown"
    _persist(tmp_path, payload)
    read = store.read(tmp_path, ["AAA"], now=NOW + timedelta(seconds=5))
    assert read["as_of"] == "2026-09-25T11:00:00-04:00"
    assert read["quotes"]["AAA"]["session"] == "unknown"


# Failures replace earlier success, respect shared cadence, and allow recovery.
@pytest.mark.parametrize(
    "failure", ["exception", "none", "bad-envelope", "unhashable-envelope"]
)
def test_failure_replaces_prior_success_and_later_recovery(tmp_path, failure):
    store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)
    later = NOW + timedelta(seconds=15)
    calls = []

    # Supply distinct failures without persisting arbitrary exception details.
    def fetch(symbols):
        calls.append(symbols)
        if failure == "exception":
            raise RuntimeError("synthetic private error that must not be stored")
        if failure == "none":
            return None
        raw = _capture(symbols, later)
        raw["session"] = [] if failure == "unhashable-envelope" else "invalid"
        return raw

    outcome = store.collect(tmp_path, ["AAA"], fetch=fetch, clock=lambda: later)
    assert outcome["status"] == "failed"
    read = store.read(tmp_path, ["AAA"], now=later)
    assert read["as_of"] is None
    assert read["quotes"]["AAA"]["price"] is None
    assert read["quotes"]["AAA"]["status"] == "unavailable"
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: later)[
            "status"
        ]
        == "not_due"
    )
    assert len(calls) == 1
    after = later + timedelta(seconds=15)
    outcome = store.collect(
        tmp_path,
        ["AAA"],
        fetch=lambda symbols: _capture(symbols, after, price=101),
        clock=lambda: after,
    )
    assert outcome["status"] == "collected"
    assert store.read(tmp_path, ["AAA"], now=after)["quotes"]["AAA"]["price"] == 101
    assert "private" not in (tmp_path / "desk/session-prices/latest.json").read_text()


# Malformed stored fields must invalidate data rather than crash an endpoint reader.
@pytest.mark.parametrize(
    "field",
    [
        "feed",
        "session",
        "status",
        "reason",
        "indicative",
        "at",
        "valid_until",
        "price",
        "bid",
        "ask",
    ],
)
@pytest.mark.parametrize("value", [[], {}])
def test_malformed_unhashable_row_fields_remain_unavailable(tmp_path, field, value):
    payload = _wrapper()
    row = payload["snapshot"]["quotes"]["AAA"]
    row[field] = value
    if field == "reason":
        row.update(status="unavailable", price=None, valid_until=None)
    _persist(tmp_path, payload)
    read = store.read(tmp_path, ["AAA"], now=NOW)
    assert read["quotes"]["AAA"]["price"] is None
    assert read["quotes"]["AAA"]["status"] == "unavailable"


# Invalid price geometry or timestamps must never reach the dashboard as a fresh price.
@pytest.mark.parametrize(
    "changes",
    [
        {"price": float("nan")},
        {"price": float("inf")},
        {"price": True},
        {"price": 0},
        {"price": 500},
        {"bid": 101, "ask": 99},
        {"bid": None},
        {"ask": -1},
        {"at": None},
        {"at": "2026-09-25T15:00:00"},
        {"at": (NOW + timedelta(seconds=1)).isoformat()},
        {"valid_until": (NOW + timedelta(seconds=60)).isoformat()},
        {"indicative": True},
        {"status": "stale"},
        {"status": "unavailable"},
        {"feed": "private source"},
    ],
)
def test_invalid_row_values_do_not_expose_prices(tmp_path, changes):
    payload = _wrapper()
    payload["snapshot"]["quotes"]["AAA"].update(changes)
    _persist(tmp_path, payload)
    row = store.read(tmp_path, ["AAA"], now=NOW)["quotes"]["AAA"]
    assert row["price"] is None
    assert row["status"] == "unavailable"


# Nonfresh results keep valid source evidence but no current price.
@pytest.mark.parametrize("status", ["stale", "unavailable"])
def test_nonfresh_provider_evidence_is_not_revived(tmp_path, status):
    payload = _wrapper()
    row = payload["snapshot"]["quotes"]["AAA"]
    row.update(status=status, price=None, reason="private provider text")
    if status == "unavailable":
        row["valid_until"] = None
    _persist(tmp_path, payload)
    observed = store.read(tmp_path, ["AAA"], now=NOW)["quotes"]["AAA"]
    assert observed["status"] == status
    assert observed["price"] is None
    assert observed["at"] == row["at"]
    assert observed["session"] == row["session"]
    assert "private" not in observed["reason"]


# Date valid unavailable feed checks without inventing a fresh price.
def test_completed_unavailable_feed_check_replaces_old_success(tmp_path):
    store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)
    later = NOW + timedelta(seconds=15)
    captured = _capture(["AAA"], later)
    captured["quotes"]["AAA"].update(
        status="unavailable",
        price=None,
        valid_until=None,
        at=None,
        reason="No fresh quote from available feeds",
    )
    outcome = store.collect(
        tmp_path, ["AAA"], fetch=lambda symbols: captured, clock=lambda: later
    )
    assert outcome["status"] == "collected"
    read = store.read(tmp_path, ["AAA"], now=later)
    assert read["as_of"] == later.isoformat()
    assert read["quotes"]["AAA"]["status"] == "unavailable"
    assert read["quotes"]["AAA"]["price"] is None


# Invalid rows replace old prices without discarding other valid symbols.
@pytest.mark.parametrize("field", ["feed", "session", "status"])
def test_malformed_completed_rows_replace_old_prices(tmp_path, field):
    store.collect(tmp_path, ["AAA", "BBB"], fetch=_capture, clock=lambda: NOW)
    later = NOW + timedelta(seconds=15)
    captured = _capture(["AAA", "BBB"], later, price=101)
    captured["quotes"]["AAA"][field] = []
    outcome = store.collect(
        tmp_path, ["AAA", "BBB"], fetch=lambda symbols: captured, clock=lambda: later
    )
    assert outcome["status"] == "collected"
    read = store.read(tmp_path, ["AAA", "BBB"], now=later)
    assert read["quotes"]["AAA"]["status"] == "unavailable"
    assert read["quotes"]["AAA"]["price"] is None
    assert read["quotes"]["BBB"]["price"] == 101


# Corrupt wrapper metadata cannot suppress an otherwise due collection.
@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"version": True},
        {"attempted_at": "bad"},
        {"completed_at": "2026-09-25T15:00:00"},
        {"attempted_at": (NOW + timedelta(days=1)).isoformat()},
        {"completed_at": (NOW + timedelta(days=1)).isoformat()},
        {"symbols": None},
        {"symbols": {}},
        {"symbols": ["AAA", "AAA"]},
        {"snapshot": []},
    ],
)
def test_bad_metadata_does_not_serve_or_suppress_collection(tmp_path, changes):
    payload = _wrapper()
    payload.update(changes)
    _persist(tmp_path, payload)
    assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)["status"]
        == "collected"
    )


# Corrupt snapshots are unavailable even when their surrounding wrapper is valid.
@pytest.mark.parametrize(
    "changes",
    [
        {"session": []},
        {"session": {}},
        {"signal_scope": "extended-session"},
        {"as_of": None},
        {"as_of": (NOW + timedelta(seconds=1)).isoformat()},
        {"quotes": []},
    ],
)
def test_bad_snapshot_envelope_remains_unavailable(tmp_path, changes):
    payload = _wrapper()
    payload["snapshot"].update(changes)
    _persist(tmp_path, payload)
    read = store.read(tmp_path, ["AAA"], now=NOW)
    assert read["as_of"] is None
    assert read["quotes"]["AAA"]["price"] is None


# Missing or mismatched universes never leak another recorded symbol into a response.
def test_due_checks_use_shared_attempt_time_and_changed_universe(tmp_path):
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)["status"]
        == "collected"
    )
    assert (
        store.collect(
            tmp_path,
            ["AAA"],
            fetch=_forbidden,
            clock=lambda: NOW + timedelta(seconds=14.999),
        )["status"]
        == "not_due"
    )
    changed = NOW + timedelta(seconds=1)
    assert (
        store.collect(
            tmp_path,
            ["AAA", "BBB"],
            fetch=lambda symbols: _capture(symbols, changed),
            clock=lambda: changed,
        )["status"]
        == "collected"
    )
    read = store.read(tmp_path, ["CCC"], now=changed)
    assert set(read["quotes"]) == {"CCC"}
    assert read["quotes"]["CCC"]["price"] is None
    due = changed + timedelta(seconds=15)
    assert (
        store.collect(
            tmp_path,
            ["AAA", "BBB"],
            fetch=lambda symbols: _capture(symbols, due),
            clock=lambda: due,
        )["status"]
        == "collected"
    )


# A long-stale persisted attempt cannot defer collection after a restart.
def test_old_metadata_does_not_suppress_collection(tmp_path):
    _persist(tmp_path, _wrapper(captured=NOW - timedelta(days=1)))
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)["status"]
        == "collected"
    )


# Invalid or oversized JSON files are unavailable and replaced on the next due attempt.
@pytest.mark.parametrize(
    "content",
    [
        b"{",
        b"[]",
        b"null",
        b"\xff",
        b" ",
        b"x" * (store.MAX_BYTES + 1),
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_corrupt_file_is_read_safely_and_replaced(tmp_path, content):
    latest = _persist(tmp_path, _wrapper())
    latest.write_bytes(content)
    assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)["status"]
        == "collected"
    )


# Repeated captures keep only the latest bounded file and one shared lock.
def test_repeated_collection_does_not_create_an_archive(tmp_path):
    for iteration in range(12):
        at = NOW + timedelta(seconds=15 * iteration)
        outcome = store.collect(
            tmp_path,
            ["AAA"],
            fetch=lambda symbols, at=at: _capture(symbols, at),
            clock=lambda at=at: at,
        )
        assert outcome["status"] == "collected"
    folder = tmp_path / "desk/session-prices"
    assert {path.name for path in folder.iterdir()} == {"latest.json", "collector.lock"}
    assert (folder / "latest.json").stat().st_size <= store.MAX_BYTES
    assert store.read(tmp_path, ["AAA"], now=at)["as_of"] == at.isoformat()


# Failed replacement cleans this attempt's temp file and preserves previous bytes.
def test_publication_failure_preserves_previous_file_and_cleans_temp(
    tmp_path, monkeypatch
):
    store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)
    folder = tmp_path / "desk/session-prices"
    original = (folder / "latest.json").read_bytes()

    # Simulate an ordinary storage failure at the atomic replacement boundary.
    def fail_replace(source, destination):
        assert source.read_bytes()
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(store.os, "replace", fail_replace)
    later = NOW + timedelta(seconds=15)
    outcome = store.collect(
        tmp_path,
        ["AAA"],
        fetch=lambda symbols: _capture(symbols, later),
        clock=lambda: later,
    )
    assert outcome["status"] == "unavailable"
    assert (folder / "latest.json").read_bytes() == original
    assert {path.name for path in folder.iterdir()} == {"latest.json", "collector.lock"}


# Readers see the old complete capture until the new complete capture is published.
def test_atomic_replace_does_not_expose_partial_new_content(tmp_path, monkeypatch):
    store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)
    later = NOW + timedelta(seconds=15)
    original_replace = os.replace
    seen = []

    # Inspect the actual old record immediately before the real atomic replacement.
    def observe_replace(source, destination):
        seen.append(store.read(tmp_path, ["AAA"], now=later)["quotes"]["AAA"]["price"])
        candidate = json.loads(source.read_bytes())
        assert candidate["snapshot"]["quotes"]["AAA"]["price"] == 101
        original_replace(source, destination)

    monkeypatch.setattr(store.os, "replace", observe_replace)
    outcome = store.collect(
        tmp_path,
        ["AAA"],
        fetch=lambda symbols: _capture(symbols, later, price=101),
        clock=lambda: later,
    )
    assert outcome["status"] == "collected"
    assert seen == [100]
    assert store.read(tmp_path, ["AAA"], now=later)["quotes"]["AAA"]["price"] == 101


# Competing processes cannot duplicate collection or bypass the persisted due check.
def test_cross_process_lock_prevents_duplicate_collection(tmp_path):
    context = multiprocessing.get_context("spawn")
    started, release = context.Event(), context.Event()
    outcome = context.Queue()
    worker = context.Process(
        target=_held_collection, args=(str(tmp_path), started, release, outcome)
    )
    worker.start()
    try:
        assert started.wait(10), "child did not enter the synthetic fetch"
        assert (
            store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: NOW)[
                "status"
            ]
            == "busy"
        )
        assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
        release.set()
        worker.join(10)
        assert worker.exitcode == 0
        assert outcome.get(timeout=2)["status"] == "collected"
        assert (
            store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: NOW)[
                "status"
            ]
            == "not_due"
        )
        assert store.read(tmp_path, ["AAA"], now=NOW)["quotes"]["AAA"]["price"] == 100
    finally:
        release.set()
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        outcome.close()


# The operating system releases a terminated collector's file lock for a later process.
def test_terminated_collector_does_not_leave_a_permanent_lock(tmp_path):
    context = multiprocessing.get_context("spawn")
    started, release = context.Event(), context.Event()
    outcome = context.Queue()
    worker = context.Process(
        target=_held_collection, args=(str(tmp_path), started, release, outcome)
    )
    worker.start()
    try:
        assert started.wait(10)
        worker.terminate()
        worker.join(5)
        assert not worker.is_alive()
        assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
        assert (
            store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)[
                "status"
            ]
            == "collected"
        )
        assert store.read(tmp_path, ["AAA"], now=NOW)["quotes"]["AAA"]["price"] == 100
    finally:
        # A killed Event waiter may hold its internal lock; never signal it afterward.
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        outcome.close()


# A corrupt latest-file FIFO is rejected promptly instead of hanging an HTTP reader.
def test_fifo_snapshot_cannot_block_reading(tmp_path):
    folder = tmp_path / "desk/session-prices"
    folder.mkdir(parents=True)
    os.mkfifo(folder / "latest.json")
    context = multiprocessing.get_context("spawn")
    outcome = context.Queue()
    worker = context.Process(target=_isolated_read, args=(str(tmp_path), outcome))
    worker.start()
    try:
        worker.join(5)
        assert worker.exitcode == 0, "snapshot read blocked on a non-regular file"
        assert outcome.get(timeout=2)["as_of"] is None
        assert (
            store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)[
                "status"
            ]
            == "collected"
        )
        assert stat.S_ISREG((folder / "latest.json").stat().st_mode)
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        outcome.close()


# Read and collection refuse a substituted final directory without touching its target.
def test_symlink_directory_is_never_used(tmp_path):
    external = tmp_path / "outside"
    external.mkdir()
    (tmp_path / "desk").mkdir()
    (tmp_path / "desk/session-prices").symlink_to(external, target_is_directory=True)
    assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: NOW)["status"]
        == "unavailable"
    )
    assert list(external.iterdir()) == []


# A symlink at either file boundary must never read or modify an external target.
@pytest.mark.parametrize("name", ["latest.json", "collector.lock"])
def test_symlink_file_is_refused(tmp_path, name):
    folder = tmp_path / "desk/session-prices"
    folder.mkdir(parents=True)
    external = tmp_path / "outside.json"
    external.write_text(json.dumps(_wrapper()))
    original = external.read_bytes()
    (folder / name).symlink_to(external)
    assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: NOW)["status"]
        == "unavailable"
    )
    assert external.read_bytes() == original


# Fail unusable storage before provider access without claiming a successful attempt.
def test_unusable_storage_returns_unavailable(tmp_path):
    (tmp_path / "desk").write_text("not a directory")
    assert store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: NOW) == {
        "status": "unavailable",
        "attempted_at": None,
        "completed_at": None,
    }
    assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None


# Reject caller inputs that would exceed the collection's explicit universe bound.
@pytest.mark.parametrize(
    "symbols",
    [
        "AAA",
        [""],
        [None],
        ["A A"],
        ["é"],
        ["A" * 33],
        [str(value) for value in range(store.MAX_SYMBOLS + 1)],
    ],
)
def test_invalid_symbol_universes_are_rejected(tmp_path, symbols):
    with pytest.raises(ValueError, match="symbol"):
        store.collect(tmp_path, symbols, fetch=_forbidden, clock=lambda: NOW)
    with pytest.raises(ValueError, match="symbol"):
        store.read(tmp_path, symbols, now=NOW)
    assert list(tmp_path.iterdir()) == []


# Duplicate-heavy iterables still consume a bounded amount of validation work.
def test_duplicate_input_iteration_is_bounded(tmp_path):
    with pytest.raises(ValueError, match="symbol collection exceeds"):
        store.collect(
            tmp_path,
            repeat("AAA", store.MAX_SYMBOLS + 1),
            fetch=_forbidden,
            clock=lambda: NOW,
        )


# Invalid collection intervals cannot create files or call a provider.
@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_intervals_are_rejected(tmp_path, interval):
    with pytest.raises(ValueError, match="interval must be positive and finite"):
        store.collect(
            tmp_path,
            ["AAA"],
            interval_seconds=interval,
            fetch=_forbidden,
            clock=lambda: NOW,
        )
    assert list(tmp_path.iterdir()) == []


# A timezone object without an offset is still a naive clock and must be rejected.
class _NoOffset(tzinfo):
    # Model an explicitly unusable timezone without consulting the host timezone.
    def utcoffset(self, value):
        return None


# Never infer UTC or local time when a caller supplies an undated instant.
@pytest.mark.parametrize(
    "now",
    [datetime(2026, 9, 25), datetime(2026, 9, 25, tzinfo=_NoOffset()), "2026-09-25"],
)
def test_naive_or_invalid_clock_is_rejected(tmp_path, now):
    with pytest.raises(ValueError, match="clock requires a dated instant"):
        store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: now)
    with pytest.raises(ValueError, match="clock requires a dated instant"):
        store.read(tmp_path, ["AAA"], now=now)


# Corrupt timestamps are invalid data, not a reason to retain earlier successful prices.
@pytest.mark.parametrize("field", ["as_of", "at"])
def test_overlong_timestamp_cannot_preserve_old_prices(tmp_path, field):
    store.collect(tmp_path, ["AAA"], fetch=_capture, clock=lambda: NOW)
    later = NOW + timedelta(seconds=15)
    captured = _capture(["AAA"], later)
    target = captured if field == "as_of" else captured["quotes"]["AAA"]
    instant = later if field == "as_of" else later - timedelta(seconds=1)
    target[field] = (
        instant.strftime("%Y-%m-%dT%H:%M:%S.") + "0" * store.MAX_BYTES + "+00:00"
    )
    outcome = store.collect(
        tmp_path, ["AAA"], fetch=lambda symbols: captured, clock=lambda: later
    )
    assert outcome["status"] == ("failed" if field == "as_of" else "collected")
    read = store.read(tmp_path, ["AAA"], now=later)
    assert read["quotes"]["AAA"]["price"] is None
    assert read["quotes"]["AAA"]["status"] == "unavailable"


# Storage metadata errors are unavailable data rather than uncaught endpoint exceptions.
def test_directory_metadata_error_is_unavailable(tmp_path, monkeypatch):
    # Refuse filesystem metadata access before any open or provider operation.
    def denied(path):
        raise PermissionError("synthetic metadata denial")

    monkeypatch.setattr(type(tmp_path), "is_symlink", denied)
    assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: NOW)["status"]
        == "unavailable"
    )


# Unsupported locking or no-follow primitives must never create an unlocked collector.
@pytest.mark.parametrize("missing", ["fcntl", "O_NOFOLLOW", "O_NONBLOCK"])
def test_unsupported_platform_fails_closed_without_io(tmp_path, monkeypatch, missing):
    if missing == "fcntl":
        monkeypatch.setattr(store, "fcntl", None)
    else:
        monkeypatch.delattr(store.os, missing)
    assert store.supported() is False
    assert (
        store.collect(tmp_path, ["AAA"], fetch=_forbidden, clock=lambda: NOW)["status"]
        == "unavailable"
    )
    assert store.read(tmp_path, ["AAA"], now=NOW)["as_of"] is None
    assert list(tmp_path.iterdir()) == []


# Import the actual application with no fcntl so disabled Windows hosts remain usable.
def test_application_import_survives_missing_fcntl(tmp_path):
    script = textwrap.dedent(
        """
        import builtins
        import sys
        from pathlib import Path
        original_import = builtins.__import__

        # Simulate a host that has no fcntl module before application import.
        def without_fcntl(name, *args, **kwargs):
            if name == "fcntl":
                raise ImportError("synthetic unsupported host")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = without_fcntl
        import backend.main
        from backend.market import session_price_snapshot as snapshot

        # Prove unsupported collection never enters provider code.
        def forbidden(symbols):
            raise AssertionError("unexpected provider operation")

        root = Path(sys.argv[1])
        assert not snapshot.supported()
        outcome = snapshot.collect(root, ["AAA"], fetch=forbidden)
        assert outcome["status"] == "unavailable"
        assert snapshot.read(root, ["AAA"])["as_of"] is None
        assert list(root.iterdir()) == []
        print("application import and unsupported snapshot boundary passed")
    """
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (
        "application import and unsupported snapshot boundary passed" in result.stdout
    )
