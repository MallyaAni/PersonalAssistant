"""Independent readback checks for temporal and file-provenance boundaries."""

import hashlib

import pyarrow.parquet as pq
import pytest

from backend.market.intraday_cache import load_intraday, load_recorded_eligibility
from backend.tests.test_intraday_cache import (
    _intraday_rows,
    _write_desk,
    _write_intraday,
)


# A timezone-less historical bar cannot silently become New York time.
def test_naive_cache_timestamp_is_rejected(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    rows = _intraday_rows()
    rows[0]["start"] = "2026-09-18T13:30:00"
    _write_intraday(partition / "AAPL.parquet", rows)
    with pytest.raises(ValueError, match="timezone"):
        load_intraday("AAPL", partition, price_basis="adjusted")


# Publication timestamps without an offset stay explicitly unavailable.
def test_naive_archived_publication_is_an_issue(tmp_path):
    path = _write_desk(
        tmp_path / "desk" / "asof=2026-09-18" / "desk.json",
        written="2026-09-18T16:30:00",
    )
    cache = load_recorded_eligibility("AAPL", [path])
    assert not cache.records
    assert len(cache.issues) == 1


# An asof-shaped string must still be an actual date.
def test_invalid_partition_date_is_rejected(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-99-20"
    _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    with pytest.raises(ValueError, match="month"):
        load_intraday("AAPL", partition, price_basis="adjusted")


# Source row order is preserved while provenance bounds describe the full range.
def test_unsorted_rows_have_true_bounds_without_reordering(tmp_path):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    rows = list(reversed(_intraday_rows()))
    _write_intraday(partition / "AAPL.parquet", rows)
    cache = load_intraday("AAPL", partition, price_basis="adjusted")
    assert cache.bars[0].start > cache.bars[-1].start
    assert cache.provenance.data_bounds == (
        "2026-09-18T13:30:00+00:00",
        "2026-09-18T14:00:00+00:00",
    )


# The recorded session must agree with the explicitly supplied archive partition.
def test_conflicting_record_partition_is_unavailable(tmp_path):
    path = _write_desk(
        tmp_path / "desk" / "asof=2026-09-18" / "desk.json", session="2026-09-17"
    )
    cache = load_recorded_eligibility("AAPL", [path])
    assert not cache.records
    assert len(cache.issues) == 1


# A concurrent source replacement cannot detach reported hashes from consumed bytes.
def test_parquet_hash_identifies_the_bytes_actually_read(tmp_path, monkeypatch):
    partition = tmp_path / "bars_15m" / "asof=2026-09-20"
    path = _write_intraday(partition / "AAPL.parquet", _intraday_rows())
    original_bytes = path.read_bytes()
    changed = _intraday_rows()
    changed[0]["open"] = 90.5
    replacement = _write_intraday(
        tmp_path / "replacement.parquet", changed
    ).read_bytes()
    original_read = pq.read_table

    # Replace the on-disk source immediately before the adapter's table read.
    def replace_then_read(source, *args, **kwargs):
        path.write_bytes(replacement)
        return original_read(source, *args, **kwargs)

    monkeypatch.setattr(pq, "read_table", replace_then_read)
    cache = load_intraday("AAPL", partition, price_basis="adjusted")
    assert cache.provenance.sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert cache.bars[0].open == 90.0
