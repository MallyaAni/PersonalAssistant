"""Synthetic coverage of the read-only market cache adapter.

The tests create tiny temporary parquet and JSON files and prove real
readback, hashes, metadata rejection, the explicit adjusted basis,
timezone-aware timestamps, duplicate and future-poison retention, missing
newer grade/rejection, written-vs-session availability, invalid publication
reporting, and that loading never writes to any source. No credentials,
database, model or full historical cache is used.
"""

import hashlib
import json
from datetime import UTC, date, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.market.intraday_cache import (
    PRICE_BASIS_ADJUSTED,
    load_daily,
    load_intraday,
    load_recorded_eligibility,
)


# Write a tiny intraday parquet with the real cache's column names and source.
def _write_intraday(path, rows, source=b"alpaca-iex", asof=None):
    """Write a bars_15m-style parquet for one symbol and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {}
    if source is not None:
        metadata[b"source"] = source
    if asof is not None:
        metadata[b"asof"] = asof
    schema = pa.schema(
        [
            ("start", pa.string()),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.float64()),
            ("volume", pa.float64()),
        ],
        metadata=metadata,
    )
    table = pa.table(
        {
            "start": [r["start"] for r in rows],
            "open": [r["open"] for r in rows],
            "high": [r["high"] for r in rows],
            "low": [r["low"] for r in rows],
            "close": [r["close"] for r in rows],
            "volume": [r["volume"] for r in rows],
        },
        schema=schema,
    )
    pq.write_table(table, path)
    return path


# Write a tiny daily parquet with the real cache's column names and source.
def _write_daily(path, rows, source=b"yahoo", asof=b"2026-09-18"):
    """Write a daily-bars-style parquet for one symbol and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("session_date", pa.date32()),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.float64()),
            ("adjusted_close", pa.float64()),
            ("volume", pa.int64()),
        ],
        metadata={b"source": source, b"asof": asof},
    )
    table = pa.table(
        {
            "session_date": [r["session_date"] for r in rows],
            "open": [r["open"] for r in rows],
            "high": [r["high"] for r in rows],
            "low": [r["low"] for r in rows],
            "close": [r["close"] for r in rows],
            "adjusted_close": [r["adjusted_close"] for r in rows],
            "volume": [r["volume"] for r in rows],
        },
        schema=schema,
    )
    pq.write_table(table, path)
    return path


# Write a tiny desk.json record carrying session, written, grades and levels.
def _write_desk(
    path,
    session="2026-09-18",
    written="2026-09-18T23:47:41+00:00",
    grades=None,
    levels=None,
):
    """Write a desk.json record and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session": session,
        "written": written,
        "grades": grades if grades is not None else {"AAPL": {"grade": "A+"}},
        "levels": levels if levels is not None else {"AAPL": {"rejecting_band": False}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# The intraday rows used across tests, in file order.
def _intraday_rows():
    """Return a small ordered set of bars_15m rows."""
    return [
        {
            "start": "2026-09-18T13:30:00+00:00",
            "open": 90.0,
            "high": 91.0,
            "low": 89.5,
            "close": 90.7,
            "volume": 1000.0,
        },
        {
            "start": "2026-09-18T13:45:00+00:00",
            "open": 90.7,
            "high": 91.2,
            "low": 90.4,
            "close": 91.0,
            "volume": 800.0,
        },
        {
            "start": "2026-09-18T14:00:00+00:00",
            "open": 91.0,
            "high": 91.5,
            "low": 90.8,
            "close": 91.3,
            "volume": 900.0,
        },
    ]


# Loaded bars reproduce the file's rows, order, prices and volume exactly.
def test_intraday_readback_keeps_rows_order_and_values(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    cache = load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    assert [bar.close for bar in cache.bars] == [90.7, 91.0, 91.3]
    assert [bar.volume for bar in cache.bars] == [1000.0, 800.0, 900.0]
    assert cache.provenance.row_count == 3
    assert cache.provenance.partition_label == "asof=2026-09-20"
    assert cache.provenance.metadata_source == "alpaca-iex"
    assert cache.provenance.price_basis == PRICE_BASIS_ADJUSTED
    assert cache.provenance.data_bounds == (
        "2026-09-18T13:30:00+00:00",
        "2026-09-18T14:00:00+00:00",
    )


# The provenance carries the source file's SHA-256, not an invented one.
def test_intraday_provenance_hashes_the_source_file(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    path = _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    cache = load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert cache.provenance.sha256 == digest
    assert cache.provenance.source_path == str(path)


# A missing or unknown source metadata label is rejected, never guessed at.
def test_intraday_rejects_unknown_or_mismatched_source_metadata(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    path = partition / "AAPL.parquet"
    _write_intraday(path, _intraday_rows(), source=b"some-other-feed")
    with pytest.raises(ValueError, match="expected 'alpaca-iex'"):
        load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    path.unlink()
    _write_intraday(path, _intraday_rows(), source=None)
    with pytest.raises(ValueError, match="no source metadata"):
        load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)


# Only the declared adjusted basis is accepted; raw or absent is a clear error.
def test_intraday_requires_the_declared_adjusted_basis(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    with pytest.raises(ValueError, match="adjusted"):
        load_intraday("AAPL", partition, price_basis="raw")
    with pytest.raises(ValueError, match="adjusted"):
        load_intraday("AAPL", partition, price_basis=None)
    cache = load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    assert cache.provenance.price_basis == PRICE_BASIS_ADJUSTED


# The basis limitation is persistent, explicit, and never claims scoring.
def test_intraday_limitation_is_explicit_and_not_an_attestation(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    cache = load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    assert "adjustment=all" in cache.provenance.limitation
    assert "not independently attested" in cache.provenance.limitation
    assert "does not itself authorize" in cache.provenance.limitation


# Timestamps parse timezone-aware and keep the source timezone (UTC).
def test_intraday_timestamps_are_timezone_aware_utc(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    cache = load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    first = cache.bars[0].start
    assert first.tzinfo is not None
    assert first.astimezone(UTC) == datetime(2026, 9, 18, 13, 30, tzinfo=UTC)
    assert first.utcoffset() == UTC.utcoffset(None)


# An invalid timestamp is an explicit error, not a silently dropped row.
def test_intraday_invalid_timestamp_raises_explicitly(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    rows = _intraday_rows()
    rows[1]["start"] = "not-a-timestamp"
    _write_intraday(partition / "AAPL.parquet", rows)
    with pytest.raises(ValueError, match="timestamp"):
        load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)


# Duplicate bar starts are preserved and counted, never discarded.
def test_intraday_preserves_and_counts_duplicate_starts(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    rows = _intraday_rows()
    rows.append(dict(rows[0]))
    _write_intraday(partition / "AAPL.parquet", rows)
    cache = load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    assert len(cache.bars) == 4
    assert cache.quality.reason_counts["duplicate start"] == 1
    assert cache.provenance.row_count == 4


# A later non-numeric price becomes NaN, never rejecting the earlier prefix.
def test_intraday_future_poison_is_kept_and_does_not_reject_the_prefix(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    path = partition / "AAPL.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _intraday_rows()
    schema = pa.schema(
        [
            ("start", pa.string()),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.string()),
            ("volume", pa.float64()),
        ],
        metadata={b"source": b"alpaca-iex"},
    )
    table = pa.table(
        {
            "start": [r["start"] for r in rows],
            "open": [r["open"] for r in rows],
            "high": [r["high"] for r in rows],
            "low": [r["low"] for r in rows],
            "close": ["90.7", "91.0", "corrupt"],
            "volume": [r["volume"] for r in rows],
        },
        schema=schema,
    )
    pq.write_table(table, path)
    cache = load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    assert len(cache.bars) == 3
    assert cache.bars[0].close == 90.7
    assert cache.bars[1].close == 91.0
    assert cache.bars[2].close != cache.bars[2].close  # NaN
    assert cache.quality.reason_counts["non-numeric close"] == 1


# An explicit partition that is not asof=YYYY-MM-DD fails clearly.
def test_explicit_partition_must_be_an_asof_directory(tmp_path):
    partition = tmp_path / "bars_15m" / "latest"
    _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    with pytest.raises(ValueError, match="asof=YYYY-MM-DD"):
        load_intraday("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)


# Daily rows reproduce the file's dates, closes and adjusted closes.
def test_daily_readback_keeps_rows_and_values(tmp_path):
    partition = tmp_path / "bars" / "asof=2026-09-18"
    rows = [
        {
            "session_date": date(2026, 9, 17),
            "open": 1.0,
            "high": 1.2,
            "low": 0.9,
            "close": 1.1,
            "adjusted_close": 1.1,
            "volume": 10,
        },
        {
            "session_date": date(2026, 9, 18),
            "open": 1.1,
            "high": 1.3,
            "low": 1.0,
            "close": 1.2,
            "adjusted_close": 1.2,
            "volume": 12,
        },
    ]
    _write_daily(partition / "AAPL.parquet", rows)
    cache = load_daily("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    assert [row.date for row in cache.rows] == [date(2026, 9, 17), date(2026, 9, 18)]
    assert [row.close for row in cache.rows] == [1.1, 1.2]
    assert [row.adj_close for row in cache.rows] == [1.1, 1.2]
    assert cache.provenance.metadata_source == "yahoo"
    assert cache.provenance.data_bounds == ("2026-09-17", "2026-09-18")
    assert (
        cache.provenance.sha256
        == hashlib.sha256((partition / "AAPL.parquet").read_bytes()).hexdigest()
    )


# Daily metadata as-of that contradicts the explicit partition fails clearly.
def test_daily_rejects_partition_asof_metadata_mismatch(tmp_path):
    partition = tmp_path / "bars" / "asof=2026-09-18"
    rows = [
        {
            "session_date": date(2026, 9, 18),
            "open": 1.0,
            "high": 1.2,
            "low": 0.9,
            "close": 1.1,
            "adjusted_close": 1.1,
            "volume": 10,
        }
    ]
    _write_daily(partition / "AAPL.parquet", rows, asof=b"2026-09-17")
    with pytest.raises(ValueError, match="inconsistent"):
        load_daily("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)


# A later non-numeric daily close is kept as NaN, prefix rows intact.
def test_daily_future_poison_kept_without_rejecting_earlier_rows(tmp_path):
    partition = tmp_path / "bars" / "asof=2026-09-18"
    path = partition / "AAPL.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("session_date", pa.date32()),
            ("close", pa.string()),
            ("adjusted_close", pa.string()),
        ],
        metadata={b"source": b"yahoo", b"asof": b"2026-09-18"},
    )
    table = pa.table(
        {
            "session_date": [date(2026, 9, 17), date(2026, 9, 18)],
            "close": ["1.1", "poison"],
            "adjusted_close": ["1.1", "1.2"],
        },
        schema=schema,
    )
    pq.write_table(table, path)
    cache = load_daily("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)
    assert len(cache.rows) == 2
    assert cache.rows[0].close == 1.1
    assert cache.rows[1].close != cache.rows[1].close  # NaN
    assert cache.quality.reason_counts["non-numeric close"] == 1


# An invalid daily session date is an explicit error, never a dropped row.
def test_daily_invalid_session_date_raises_explicitly(tmp_path):
    partition = tmp_path / "bars" / "asof=2026-09-18"
    path = partition / "AAPL.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "session_date": pa.array(["2026-09-17", "garbage"], type=pa.string()),
            "close": pa.array([1.1, 1.2], type=pa.float64()),
            "adjusted_close": pa.array([1.1, 1.2], type=pa.float64()),
        },
        schema=pa.schema(
            [
                ("session_date", pa.string()),
                ("close", pa.float64()),
                ("adjusted_close", pa.float64()),
            ],
            metadata={b"source": b"yahoo", b"asof": b"2026-09-18"},
        ),
    )
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="session_date"):
        load_daily("AAPL", partition, price_basis=PRICE_BASIS_ADJUSTED)


# Eligibility keeps the actual written time, never the folder date.
def test_eligibility_uses_written_time_not_folder_date(tmp_path):
    record_dir = tmp_path / "desk" / "asof=2026-09-14"
    _write_desk(
        record_dir / "desk.json",
        session="2026-09-14",
        written="2026-09-15T14:18:21+00:00",
        grades={"AAPL": {"grade": "A+"}},
        levels={"AAPL": {"rejecting_band": False}},
    )
    cache = load_recorded_eligibility("AAPL", [record_dir / "desk.json"])
    assert len(cache.records) == 1
    record = cache.records[0]
    assert record.session == date(2026, 9, 14)
    assert record.written_at == datetime(2026, 9, 15, 14, 18, 21, tzinfo=UTC)
    assert record.grade == "A+"
    assert record.rejecting_band is False
    assert cache.provenance[0].partition_label == "asof=2026-09-14"


# A missing symbol or field yields an explicit None, not a resurrected grade.
def test_eligibility_missing_symbol_and_field_stay_unknown(tmp_path):
    desk = tmp_path / "desk" / "asof=2026-09-18" / "desk.json"
    _write_desk(
        desk,
        grades={"AAOI": {"grade": "C"}},
        levels={"AAOI": {"rejecting_band": True}},
    )
    cache = load_recorded_eligibility("AAPL", [desk])
    assert cache.records[0].grade is None
    assert cache.records[0].rejecting_band is None


# Missing rejecting_band is UNKNOWN (None), never coerced to a false.
def test_eligibility_missing_rejecting_band_is_unknown_not_false(tmp_path):
    desk = tmp_path / "desk" / "asof=2026-09-18" / "desk.json"
    _write_desk(desk, levels={"AAPL": {}})
    cache = load_recorded_eligibility("AAPL", [desk])
    assert cache.records[0].grade == "A+"
    assert cache.records[0].rejecting_band is None


# A newer record without the symbol cannot silently revive an older grade.
def test_eligibility_newer_missing_record_keeps_an_unknown_observation(tmp_path):
    older = tmp_path / "desk" / "asof=2026-09-16" / "desk.json"
    newer = tmp_path / "desk" / "asof=2026-09-17" / "desk.json"
    _write_desk(older, session="2026-09-16", written="2026-09-17T01:00:00+00:00")
    _write_desk(
        newer, session="2026-09-17", written="2026-09-18T01:00:00+00:00", grades={}
    )
    cache = load_recorded_eligibility("AAPL", [newer, older])
    assert [r.grade for r in cache.records] == ["A+", None]
    assert cache.records[0].session == date(2026, 9, 16)
    assert cache.records[1].session == date(2026, 9, 17)


# Records are ordered chronologically by their actual written time.
def test_eligibility_records_are_chronological_by_written_time(tmp_path):
    late = tmp_path / "desk" / "asof=2026-09-17" / "desk.json"
    early = tmp_path / "desk" / "asof=2026-09-15" / "desk.json"
    _write_desk(early, session="2026-09-15", written="2026-09-15T23:00:00+00:00")
    _write_desk(late, session="2026-09-17", written="2026-09-18T01:00:00+00:00")
    cache = load_recorded_eligibility("AAPL", [late, early])
    assert [r.session for r in cache.records] == [date(2026, 9, 15), date(2026, 9, 17)]


# Invalid or missing publication or session is an explicit issue, not a row.
def test_eligibility_invalid_publication_is_reported_not_used(tmp_path):
    desk = tmp_path / "desk" / "asof=2026-09-18" / "desk.json"
    _write_desk(desk, written="not-a-datetime")
    cache = load_recorded_eligibility("AAPL", [desk])
    assert cache.records == ()
    assert len(cache.issues) == 1
    assert cache.issues[0].source_path == str(desk)
    assert "publication" in cache.issues[0].reason
    assert cache.provenance[0].row_count == 0


# A desk record missing session/written entirely is reported, not guessed.
def test_eligibility_missing_publication_fields_is_an_explicit_error(tmp_path):
    desk = tmp_path / "desk" / "asof=2026-09-18" / "desk.json"
    desk.parent.mkdir(parents=True, exist_ok=True)
    desk.write_text(json.dumps({"grades": {}}), encoding="utf-8")
    cache = load_recorded_eligibility("AAPL", [desk])
    assert cache.records == ()
    assert len(cache.issues) == 1
    assert "session or written" in cache.issues[0].reason


# Every supplied desk file is hashed and carried in the provenance.
def test_eligibility_provenance_hashes_every_source_file(tmp_path):
    a = tmp_path / "desk" / "asof=2026-09-16" / "desk.json"
    b = tmp_path / "desk" / "asof=2026-09-17" / "desk.json"
    _write_desk(a, session="2026-09-16", written="2026-09-17T01:00:00+00:00")
    _write_desk(b, session="2026-09-17", written="2026-09-18T01:00:00+00:00")
    cache = load_recorded_eligibility("AAPL", [a, b])
    assert {p.sha256 for p in cache.provenance} == {
        hashlib.sha256(a.read_bytes()).hexdigest(),
        hashlib.sha256(b.read_bytes()).hexdigest(),
    }


# Loading every kind of cache never writes to any source file or directory.
def test_loading_never_writes_to_any_source(tmp_path):
    intraday = tmp_path / "bars_15m" / "asof=2026-09-20"
    daily = tmp_path / "bars" / "asof=2026-09-18"
    desk = tmp_path / "desk" / "asof=2026-09-18"
    _write_intraday(intraday / "AAPL.parquet", _intraday_rows())
    daily_rows = [
        {
            "session_date": date(2026, 9, 18),
            "open": 1.0,
            "high": 1.2,
            "low": 0.9,
            "close": 1.1,
            "adjusted_close": 1.1,
            "volume": 10,
        }
    ]
    _write_daily(daily / "AAPL.parquet", daily_rows)
    _write_desk(desk / "desk.json")
    paths = sorted(str(p) for p in tmp_path.rglob("*") if p.is_file())
    before = {
        str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    load_intraday("AAPL", intraday, price_basis=PRICE_BASIS_ADJUSTED)
    load_daily("AAPL", daily, price_basis=PRICE_BASIS_ADJUSTED)
    load_recorded_eligibility("AAPL", [desk / "desk.json"])
    after_files = sorted(str(p) for p in tmp_path.rglob("*") if p.is_file())
    after = {
        str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert after_files == paths
    assert after == before
