"""Recover a known daily observation only when dated mechanical evidence agrees."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.market import calendar, snapshot
from backend.market.store import MarketStore
from backend.market.yahoo import CorporateAction, DailyBar, TickerHistory

ASOF = date(2026, 9, 24)
MISSING = date(2026, 9, 22)


# Construct complete exchange-session histories with one subsequently lost bar.
def histories():
    _, holidays = calendar._published_sessions()
    days = []
    day = date(2026, 8, 1)
    while day <= ASOF:
        if np.is_busday(np.datetime64(day), busdaycal=holidays):
            days.append(day)
        day += timedelta(days=1)
    bars = tuple(
        DailyBar(day, 100.0 + i, 102.0 + i, 99.0 + i, 101.0 + i, 101.0 + i, 1000)
        for i, day in enumerate(days)
    )
    old = TickerHistory(
        "AAA",
        tuple(b for b in bars if b.session_date <= MISSING),
        (),
        MISSING,
        datetime(2026, 9, 22, 23, tzinfo=UTC),
        "yahoo",
    )
    fresh = TickerHistory(
        "AAA",
        tuple(b for b in bars if b.session_date != MISSING),
        (),
        ASOF,
        datetime(2026, 9, 24, 23, tzinfo=UTC),
        "yahoo",
    )
    return old, fresh


# Drive the actual refresh boundary and keep immutable original hashes for assertions.
def run_refresh(tmp_path, old, fresh):
    store = MarketStore(tmp_path)
    store.write(MISSING, old)
    before = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*.parquet")
    }
    calls = []

    # Repeat the provider omission to reach the reviewed reconciliation branch.
    def fetch(ticker, start, end):
        calls.append(ticker)
        return fresh

    report = snapshot.refresh(store, ["AAA"], ASOF, fetcher=fetch)
    assert calls == ["AAA", "AAA"]
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in before.items()
    )
    return store, report


# Restore exactly the missing observation while retaining fresh adjusted revisions.
def test_identity_bar_recovery_preserves_fresh_rows_and_dated_receipt(tmp_path):
    old, fresh = histories()
    fresh = replace(
        fresh, bars=(replace(fresh.bars[0], adjusted_close=77.0),) + fresh.bars[1:]
    )
    store, report = run_refresh(tmp_path, old, fresh)
    assert report.ok
    stored = store.read("AAA", ASOF)
    assert stored.bars[0].adjusted_close == 77
    original = next(bar for bar in old.bars if bar.session_date == MISSING)
    assert next(bar for bar in stored.bars if bar.session_date == MISSING) == original
    assert {
        bar.session_date: bar for bar in stored.bars if bar.session_date != MISSING
    } == {bar.session_date: bar for bar in fresh.bars}
    receipts = list((tmp_path / "bar_reconciliations").rglob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["output_history_sha256"] == snapshot._history_hash(stored)
    assert receipt["fresh_parsed_history_sha256"] == snapshot._history_hash(fresh)
    assert receipt["retained_sources"][0]["sessions"] == [MISSING.isoformat()]
    assert receipt["restored_rows"][0]["close"] == original.close
    assert "prepared" in receipt["state"]


# Any evidence mismatch must preserve the failure rather than manufacture a bar.
@pytest.mark.parametrize(
    "case",
    [
        "split",
        "dividend",
        "action_mismatch",
        "missing_actions",
        "wrong_provider",
        "old_provider",
        "raw_overlap",
        "old_nonidentity",
        "new_nonidentity",
        "incomplete_end",
        "preclose",
        "undated",
        "missing_other_session",
        "duplicate",
    ],
)
def test_unsupported_reconciliations_leave_new_partition_absent(tmp_path, case):
    old, fresh = histories()
    old, fresh = _change_evidence(old, fresh, case)
    old, fresh = _change_coverage(old, fresh, case)
    store, report = run_refresh(tmp_path, old, fresh)
    assert not report.ok
    assert not store.has(ASOF, "AAA")
    assert not list(tmp_path.rglob("*.json"))


# Produce specific provider, action and price-basis contradictions.
def _change_evidence(old, fresh, case):
    if case in ("split", "dividend"):
        actions = (CorporateAction(date(2026, 9, 23), case, 2.0),)
        old, fresh = replace(old, actions=actions), replace(fresh, actions=actions)
    elif case == "action_mismatch":
        fresh = replace(
            fresh, actions=(CorporateAction(date(2026, 8, 3), "dividend", 1.0),)
        )
    elif case == "missing_actions":
        fresh = replace(fresh, actions=None)
    elif case == "wrong_provider":
        fresh = replace(fresh, source="iex")
    elif case == "old_provider":
        old = replace(old, source="iex")
    elif case == "raw_overlap":
        fresh = replace(
            fresh, bars=(replace(fresh.bars[0], volume=1001),) + fresh.bars[1:]
        )
    elif case == "old_nonidentity":
        old = replace(
            old, bars=old.bars[:-1] + (replace(old.bars[-1], adjusted_close=50.0),)
        )
    elif case == "new_nonidentity":
        fresh = replace(
            fresh,
            bars=fresh.bars[:-1] + (replace(fresh.bars[-1], adjusted_close=50.0),),
        )
    return old, fresh


# Produce incomplete or unavailable dated history without weakening the fixture window.
def _change_coverage(old, fresh, case):
    if case == "incomplete_end":
        fresh = replace(fresh, bars=fresh.bars[:-1], complete_through=date(2026, 9, 23))
    elif case == "preclose":
        fresh = replace(fresh, source_time=datetime(2026, 9, 24, 17, tzinfo=UTC))
    elif case == "undated":
        fresh = replace(fresh, source_time=fresh.source_time.replace(tzinfo=None))
    elif case == "missing_other_session":
        day = date(2026, 9, 21)
        old = replace(
            old, bars=tuple(bar for bar in old.bars if bar.session_date != day)
        )
        fresh = replace(
            fresh, bars=tuple(bar for bar in fresh.bars if bar.session_date != day)
        )
    elif case == "duplicate":
        fresh = replace(fresh, bars=fresh.bars[:1] + fresh.bars)
    return old, fresh


# A missing retained actions file cannot be interpreted as evidence of no events.
def test_missing_retained_action_file_refuses_recovery(tmp_path):
    old, fresh = histories()
    store = MarketStore(tmp_path)
    store.write(MISSING, old)
    store._path("actions", MISSING, "AAA").unlink()
    report = snapshot.refresh(store, ["AAA"], ASOF, fetcher=lambda *args: fresh)
    assert not report.ok
    assert not store.has(ASOF, "AAA")


# A provenance write failure prevents publication of a recovered data partition.
def test_receipt_failure_prevents_bar_publication(tmp_path, monkeypatch):
    old, fresh = histories()

    # Model an unwritable receipt location without changing market input data.
    def fail(*args):
        raise OSError("receipt unavailable")

    monkeypatch.setattr(snapshot, "_write_reconciliation_receipt", fail)
    store, report = run_refresh(tmp_path, old, fresh)
    assert not report.ok
    assert not store.has(ASOF, "AAA")


# New source captures get distinct prepared receipts instead of an orphan deadlock.
def test_content_addressed_receipts_accept_later_capture(tmp_path):
    old, fresh = histories()
    store = MarketStore(tmp_path)
    store.write(MISSING, old)
    snapshot._reconcile_missing_sessions(store, "AAA", ASOF, fresh, {MISSING})
    later = replace(fresh, source_time=fresh.source_time + timedelta(seconds=1))
    snapshot._reconcile_missing_sessions(store, "AAA", ASOF, later, {MISSING})
    assert len(list((tmp_path / "bar_reconciliations").rglob("*.json"))) == 2
    assert not store.has(ASOF, "AAA")


# Empty action lists cannot hide a changed adjustment immediately around the gap.
@pytest.mark.parametrize("changed_day", [date(2026, 9, 21), date(2026, 9, 23)])
def test_gap_neighborhood_requires_identity_prices(tmp_path, changed_day):
    old, fresh = histories()
    fresh = replace(
        fresh,
        bars=tuple(
            replace(bar, adjusted_close=bar.close * 0.99)
            if bar.session_date == changed_day
            else bar
            for bar in fresh.bars
        ),
    )
    store, report = run_refresh(tmp_path, old, fresh)
    assert not report.ok
    assert "gap-neighborhood" in report.results[0].error
    assert not store.has(ASOF, "AAA")


# Duplicate or reordered retained rows are unusable even if their values agree.
@pytest.mark.parametrize("duplicate", [True, False])
def test_retained_history_requires_unique_ordered_sessions(tmp_path, duplicate):
    old, fresh = histories()
    bars = old.bars + old.bars[-1:] if duplicate else tuple(reversed(old.bars))
    old = replace(old, bars=bars)
    store, report = run_refresh(tmp_path, old, fresh)
    assert not report.ok
    assert "duplicate or unordered" in report.results[0].error
    assert not store.has(ASOF, "AAA")
