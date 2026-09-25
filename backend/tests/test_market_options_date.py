"""New York collection dates with explicit dates and immutable storage preserved.

CLI parsing/main, refresh, chain parsing, book filtering, Parquet and the bounded
options reader are real. Only the clock, tiny universe, provider transport and
sleep are synthetic. Explicit --asof labels storage; it is not historical fetching.
"""

import io
import json
import socket
import sys
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.cli import market_options
from backend.market import live_technical, options
from backend.market.store import MarketStore
from backend.market.universe import UniverseMember

SYMBOL = "SYNTH"
UNIVERSE = (
    UniverseMember(
        SYMBOL, "member", ("software",), sub_industry="Application Software"
    ),
)
AFTER_UTC_MIDNIGHT = datetime(2026, 9, 26, 0, 5, tzinfo=UTC)
NY_DATE = date(2026, 9, 25)


# Detect forbidden connections even when a production fallback catches the error.
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    attempts = []

    # Record only the attempted connection, without any endpoint or credentials.
    def refuse(*args, **kwargs):
        attempts.append("network connection attempted")
        raise RuntimeError("Options date tests forbid network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
    assert attempts == []


# Supply two balanced OI levels at one expiry without using provider data.
def _rows(expiry, oi=5000, *, put=95, call=105):
    return [
        options.ChainRow(expiry, "put", put, oi, 1, 0.5, 0.0),
        options.ChainRow(expiry, "call", call, oi, 1, 0.5, 0.0),
    ]


# Encode public-shaped contracts for the real OCC symbol and chain parsers.
def _payload(rows):
    contracts = [
        {
            "option": (
                f"{SYMBOL}{row.expiry:%y%m%d}"
                f"{'P' if row.kind == 'put' else 'C'}{int(row.strike * 1000):08d}"
            ),
            "open_interest": row.open_interest,
            "volume": row.volume,
            "iv": row.implied_volatility,
            "gamma": row.gamma,
        }
        for row in rows
    ]
    return json.dumps({"data": {"current_price": 100.0, "options": contracts}}).encode()


# Run the actual CLI with bounded synthetic inputs instead of replacing its logic.
def _run_main(
    root,
    monkeypatch,
    now,
    *,
    asof=None,
    rows=None,
    refresh=True,
    walls=False,
    walls_book=False,
):
    calls, sleeps = [], []
    if rows is None:
        rows = _rows(
            now.astimezone(live_technical.NEW_YORK).date() + timedelta(days=30)
        )
    body = _payload(rows)

    # Freeze only datetime lookups while keeping their requested timezone intact.
    class Clock(datetime):
        # Return the declared instant in the caller's requested timezone.
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    # Serve exactly one synthetic symbol, recording any unexpected repeated fetch.
    def transport(url):
        assert url == options.CHAIN_URL.format(ticker=SYMBOL)
        calls.append(SYMBOL)
        assert len(calls) == 1
        return 200, {}, body

    # Keep pacing observable without making the test wait on wall-clock sleeps.
    def no_sleep(seconds):
        sleeps.append(seconds)

    argv = ["market_options", "--data-dir", str(root)]
    if refresh:
        argv.append("--refresh")
    if asof is not None:
        argv += ["--asof", asof.isoformat()]
    if walls:
        argv += ["--walls", SYMBOL.lower()]
    if walls_book:
        argv.append("--walls-book")
    output = io.StringIO()
    with monkeypatch.context() as scoped:
        scoped.setattr(market_options, "datetime", Clock)
        scoped.setattr(market_options, "build_universe", lambda: UNIVERSE)
        scoped.setattr(market_options.refresh, "__defaults__", (transport, no_sleep))
        scoped.setattr(sys, "argv", argv)
        with redirect_stdout(output):
            market_options.main()
    return {"calls": calls, "sleeps": sleeps, "stdout": output.getvalue()}


# Compare every temporary source byte, including unexpectedly created or deleted files.
def _files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


# Use the same New York calendar-date bound as the technical detail producer.
def _read_walls(store, now):
    today = now.astimezone(live_technical.NEW_YORK).date()
    return live_technical._walls_for(store, SYMBOL, 100.0, today)


# Every first collection is immediately readable across UTC, DST and year boundaries.
@pytest.mark.parametrize(
    ("instant", "ny_date"),
    [
        ("2026-09-25T23:59:59+00:00", "2026-09-25"),
        ("2026-09-26T00:00:00+00:00", "2026-09-25"),
        ("2026-09-26T03:59:59+00:00", "2026-09-25"),
        ("2026-09-26T04:00:00+00:00", "2026-09-26"),
        ("2026-11-01T03:59:59+00:00", "2026-10-31"),
        ("2026-11-01T04:00:00+00:00", "2026-11-01"),
        ("2026-11-02T04:59:59+00:00", "2026-11-01"),
        ("2026-11-02T05:00:00+00:00", "2026-11-02"),
        ("2026-03-08T04:59:59+00:00", "2026-03-07"),
        ("2026-03-08T05:00:00+00:00", "2026-03-08"),
        ("2026-03-09T03:59:59+00:00", "2026-03-08"),
        ("2026-03-09T04:00:00+00:00", "2026-03-09"),
        ("2026-10-01T00:05:00+00:00", "2026-09-30"),
        ("2026-10-01T04:00:00+00:00", "2026-10-01"),
        ("2027-01-01T00:05:00+00:00", "2026-12-31"),
        ("2027-01-01T05:00:00+00:00", "2027-01-01"),
    ],
)
def test_default_collection_uses_new_york_calendar_date(
    tmp_path, monkeypatch, instant, ny_date
):
    now = datetime.fromisoformat(instant)
    expected_date = date.fromisoformat(ny_date)
    assert now.astimezone(live_technical.NEW_YORK).date() == expected_date
    result = _run_main(tmp_path, monkeypatch, now)
    store = MarketStore(tmp_path)
    frame = store.read_frame(options.KIND, SYMBOL, expected_date)
    assert frame is not None, "The new collection is hidden from the NY-date reader"
    columns, metadata = frame
    assert metadata["source_time"] == instant
    assert columns["open_interest"] == [5000, 5000]
    assert set(_files(tmp_path)) == {f"options/asof={ny_date}/{SYMBOL}.parquet"}
    assert result["calls"] == [SYMBOL]
    assert result["sleeps"] == [market_options.PACE_SECONDS]
    assert f"options {ny_date}: 1 stored, 0 failed" in result["stdout"]
    before = _files(tmp_path)
    walls = _read_walls(store, now)
    assert walls["fetched_at"] == instant
    assert walls["put_wall_oi"] == walls["call_wall_oi"] == 5000
    assert _files(tmp_path) == before


# Crossing UTC midnight within one NY date must not refetch or rewrite its frame.
@pytest.mark.parametrize(
    ("before_midnight", "after_midnight"),
    [
        ("2026-09-25T23:55:00+00:00", "2026-09-26T00:05:00+00:00"),
        ("2026-11-01T23:55:00+00:00", "2026-11-02T00:05:00+00:00"),
    ],
)
def test_same_new_york_date_rerun_keeps_bytes_without_transport_or_sleep(
    tmp_path, monkeypatch, before_midnight, after_midnight
):
    old_at = datetime.fromisoformat(before_midnight)
    now = datetime.fromisoformat(after_midnight)
    expiry = now.astimezone(live_technical.NEW_YORK).date() + timedelta(days=30)
    _run_main(tmp_path, monkeypatch, old_at, rows=_rows(expiry, oi=1000))
    before = _files(tmp_path)
    result = _run_main(tmp_path, monkeypatch, now, rows=_rows(expiry, oi=5000))
    assert result["calls"] == []
    assert result["sleeps"] == []
    assert "kept" in result["stdout"]
    assert "0 stored, 0 failed" in result["stdout"]
    assert _files(tmp_path) == before
    walls = _read_walls(MarketStore(tmp_path), now)
    assert walls["fetched_at"] == before_midnight
    assert walls["put_wall_oi"] == walls["call_wall_oi"] == 1000


# Preserve explicit storage labels, including past and future calendar dates.
@pytest.mark.parametrize("asof", ["2026-09-24", "2026-09-25", "2026-09-27"])
def test_explicit_asof_remains_authoritative_with_actual_utc_collection_time(
    tmp_path, monkeypatch, asof
):
    selected = date.fromisoformat(asof)
    result = _run_main(tmp_path, monkeypatch, AFTER_UTC_MIDNIGHT, asof=selected)
    store = MarketStore(tmp_path)
    assert set(_files(tmp_path)) == {f"options/asof={asof}/{SYMBOL}.parquet"}
    _, metadata = store.read_frame(options.KIND, SYMBOL)
    assert metadata["source_time"] == AFTER_UTC_MIDNIGHT.isoformat()
    assert f"options {asof}: 1 stored, 0 failed" in result["stdout"]
    assert result["calls"] == [SYMBOL]
    assert (_read_walls(store, AFTER_UTC_MIDNIGHT) is not None) is (selected <= NY_DATE)


# Write a real legacy UTC-labelled chain without altering the current CLI default.
def _legacy_frame(store, partition, collected_at, rows):
    assert store.write_frame(
        options.KIND,
        partition,
        SYMBOL,
        options.frame(rows),
        {"source_time": collected_at.isoformat(), "price": "100.0000"},
    )


# Keep legacy future partitions immutable and preserve the bounded/unbounded readers.
def test_legacy_utc_partitions_are_not_migrated_or_read_early(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    old_at = datetime(2026, 9, 25, 23, 55, tzinfo=UTC)
    new_at = AFTER_UTC_MIDNIGHT
    expiry = NY_DATE + timedelta(days=30)
    _legacy_frame(store, NY_DATE, old_at, _rows(expiry, oi=1000))
    _legacy_frame(store, new_at.date(), new_at, _rows(expiry, oi=5000))
    before = _files(tmp_path)
    result = _run_main(tmp_path, monkeypatch, new_at, walls=True)
    assert result["calls"] == result["sleeps"] == []
    assert "5,000 OI" in result["stdout"]
    for now, expected_at, expected_oi in [
        (new_at, old_at, 1000),
        (datetime(2026, 9, 26, 3, 59, 59, tzinfo=UTC), old_at, 1000),
        (datetime(2026, 9, 26, 4, 0, tzinfo=UTC), new_at, 5000),
    ]:
        walls = _read_walls(store, now)
        assert walls["fetched_at"] == expected_at.isoformat()
        assert walls["put_wall_oi"] == walls["call_wall_oi"] == expected_oi
    assert _files(tmp_path) == before


# Default and explicit dates govern actual 180-day parser inclusion, not just labels.
@pytest.mark.parametrize("explicit_offset", [None, -1, 0, 1])
def test_chain_retention_horizon_uses_selected_calendar_date(
    tmp_path, monkeypatch, explicit_offset
):
    expiries = [NY_DATE + timedelta(days=offset) for offset in (-1, 0, 180, 181)]
    rows = [row for expiry in expiries for row in _rows(expiry)]
    selected = (
        NY_DATE
        if explicit_offset is None
        else NY_DATE + timedelta(days=explicit_offset)
    )
    asof = None if explicit_offset is None else selected
    _run_main(tmp_path, monkeypatch, AFTER_UTC_MIDNIGHT, asof=asof, rows=rows)
    store = MarketStore(tmp_path)
    columns, metadata = store.read_frame(options.KIND, SYMBOL)
    expected = {
        expiry.isoformat()
        for expiry in expiries
        if selected <= expiry <= selected + timedelta(days=180)
    }
    assert set(columns["expiry"]) == expected
    assert len(columns["expiry"]) == 2 * len(expected)
    assert metadata["source_time"] == AFTER_UTC_MIDNIGHT.isoformat()
    assert set(_files(tmp_path)) == {f"options/asof={selected}/{SYMBOL}.parquet"}


# Query-only walls keep latest-frame lookup and use the selected expiry date read-only.
@pytest.mark.parametrize("selection", ["walls", "walls_book"])
@pytest.mark.parametrize("explicit_offset", [None, 0, 1])
def test_query_only_walls_remain_unbounded_without_fetches_or_writes(
    tmp_path, monkeypatch, selection, explicit_offset
):
    store = MarketStore(tmp_path)
    _legacy_frame(
        store,
        NY_DATE,
        AFTER_UTC_MIDNIGHT - timedelta(minutes=10),
        _rows(NY_DATE + timedelta(days=30), oi=1000, put=90, call=110),
    )
    _legacy_frame(
        store,
        NY_DATE + timedelta(days=2),
        AFTER_UTC_MIDNIGHT,
        _rows(NY_DATE + timedelta(days=1), oi=5000),
    )
    before = _files(tmp_path)
    asof = (
        None if explicit_offset is None else NY_DATE + timedelta(days=explicit_offset)
    )
    result = _run_main(
        tmp_path,
        monkeypatch,
        AFTER_UTC_MIDNIGHT,
        asof=asof,
        refresh=False,
        walls=selection == "walls",
        walls_book=selection == "walls_book",
    )
    assert result["calls"] == result["sleeps"] == []
    assert "1,000 OI" not in result["stdout"]
    if explicit_offset == 1:
        assert "expiry None" in result["stdout"]
        assert result["stdout"].count("none in range") == 2
    else:
        assert f"expiry {NY_DATE + timedelta(days=1)}" in result["stdout"]
        assert "95 (5,000 OI)" in result["stdout"]
        assert "105 (5,000 OI)" in result["stdout"]
    assert _files(tmp_path) == before
