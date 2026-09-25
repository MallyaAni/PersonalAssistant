"""Independent archive review using synthetic bytes and real temporary Parquet files."""

import hashlib
import json
import multiprocessing
import os
from datetime import UTC, date, datetime
from pathlib import Path
from queue import Empty

import pytest

from backend.market import fundamental_source_store as archive
from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa
from backend.market.store import MarketStore

DAY = date(2026, 9, 25)
CAPTURED = datetime(2026, 9, 25, 21, 15, tzinfo=UTC)
TICKER = "TEST-A"
TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"


# Build visibly noncanonical JSON whose unit labels and original bytes must survive.
def _source(value=100, labels=("USD",)):
    rows = {
        label: [
            {
                "start": "2025-04-01",
                "end": "2025-06-30",
                "val": value + index,
                "filed": "2025-07-31",
                "form": "10-Q",
                "accn": "synthetic-review",
            }
        ]
        for index, label in enumerate(labels)
    }
    payload = {
        "entityName": "Synthetic archive review only",
        "cik": "0000000001",
        "facts": {"us-gaap": {TAG: {"units": rows}}},
    }
    body = b"\n\t" + json.dumps(payload, indent=3).encode() + b"\r\n"
    return units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )


# Construct the documented envelope independently of the writer being tested.
def _metadata(source, day=DAY, captured=CAPTURED):
    return {
        "schema": "fundamental-source-archive/1",
        "source_schema": units.SCHEMA,
        "source_sha256": source.sha256,
        "cik": "1",
        "ticker": TICKER,
        "asof": day.isoformat(),
        "captured_at": captured.isoformat(),
    }


# Stop two actual processes at the contested write while retaining real POSIX locking.
def _writer_process(root, source, first, entered, releasing, attempted, results):
    import fcntl

    from backend.market import store as store_module

    real_flock = fcntl.flock
    real_write = store_module._write_atomically

    # Signal the second process's actual lock attempt before letting flock serialize it.
    def observed_flock(fd, operation):
        if not first and operation == fcntl.LOCK_EX:
            attempted.set()
        return real_flock(fd, operation)

    # Hold the first writer after its existence check and before publishing its bytes.
    def paused_write(pq, table, path):
        if first:
            entered.set()
            if not releasing.wait(10):
                raise TimeoutError("review did not release the first archive writer")
        return real_write(pq, table, path)

    fcntl.flock = observed_flock
    store_module._write_atomically = paused_write
    try:
        store = MarketStore(root)
        written = archive.save(store, TICKER, DAY, source, captured_at=CAPTURED)
        results.put(
            (first, written, store._path(archive.KIND, DAY, TICKER).read_bytes())
        )
    except BaseException as exc:
        results.put((first, "error", repr(exc)))
        raise


# A losing concurrent writer must neither replace the winner nor publish a mixed frame.
@pytest.mark.skipif(os.name != "posix", reason="requires real POSIX process locks")
def test_two_process_writers_preserve_first_original_bytes(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, releasing, attempted = (context.Event() for _ in range(3))
    results = context.Queue()
    first_source = _source(101, ("USD", "EUR"))
    processes = [
        context.Process(
            target=_writer_process,
            args=(
                str(tmp_path),
                source,
                first,
                entered,
                releasing,
                attempted,
                results,
            ),
        )
        for first, source in ((True, first_source), (False, _source(909)))
    ]
    try:
        processes[0].start()
        assert entered.wait(10), "first writer never reached atomic publication"
        processes[1].start()
        assert attempted.wait(10), "second writer never attempted the real lock"
        with pytest.raises(Empty):
            results.get(timeout=0.2)
        releasing.set()
        outcomes = [results.get(timeout=10), results.get(timeout=10)]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        by_writer = {first: (written, body) for first, written, body in outcomes}
        assert by_writer[True][0] is True
        assert by_writer[False][0] is False
        assert by_writer[True][1] == by_writer[False][1]
        store = MarketStore(tmp_path)
        path = store._path(archive.KIND, DAY, TICKER)
        assert path.read_bytes() == by_writer[True][1]
        assert archive.load(store, TICKER, DAY).source == first_source
        assert not archive.save(
            store,
            TICKER,
            DAY,
            _source(808, ("JPY",)),
            captured_at=datetime(2026, 9, 25, 23, 59, tzinfo=UTC),
        )
        assert path.read_bytes() == by_writer[True][1]
        assert (
            archive.load(MarketStore(tmp_path), TICKER).source.body == first_source.body
        )
    finally:
        releasing.set()
        for process in processes:
            if process.pid is not None:
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        results.close()
        results.join_thread()


# A malformed newest envelope cannot borrow an older archive or the unitless store.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_schema", "fundamental-unit-sources/unknown"),
        ("captured_at", None),
        ("captured_at", "2026-09-26T04:00:00+00:00"),
        ("captured_at", "2026-09-25"),
        ("cik", "0000000001"),
        ("cik", " 1"),
        ("cik", "+1"),
        ("cik", "0"),
        ("unexpected", "do not ignore extra metadata"),
    ],
)
def test_malformed_newest_archive_never_falls_back(tmp_path, field, value):
    store = MarketStore(tmp_path)
    source = _source()
    earlier = date(2026, 9, 24)
    assert archive.save(
        store,
        TICKER,
        earlier,
        source,
        captured_at=datetime(2026, 9, 24, 20, tzinfo=UTC),
    )
    assert store.write_frame(fa.KIND, DAY, TICKER, fa.frame([]))
    metadata = _metadata(source)
    if value is None:
        metadata.pop(field)
    else:
        metadata[field] = value
    assert store.write_frame(
        archive.KIND, DAY, TICKER, {"body": [source.body]}, metadata
    )
    preserved = {path: path.read_bytes() for path in tmp_path.rglob("*.parquet")}
    assert archive.load(store, TICKER, earlier).source == source
    with pytest.raises(ValueError, match="archive|CIK"):
        archive.load(store, TICKER, DAY)
    with pytest.raises(ValueError, match="archive|CIK"):
        archive.load(store, TICKER)
    assert {path: path.read_bytes() for path in preserved} == preserved


# Capture cutoffs use the New York calendar rather than the UTC timestamp's date.
@pytest.mark.parametrize(
    ("day", "captured", "accepted"),
    [
        (DAY, "2026-09-26T03:59:59+00:00", True),
        (DAY, "2026-09-26T04:00:00+00:00", False),
        (date(2026, 1, 15), "2026-01-16T04:59:59+00:00", True),
        (date(2026, 1, 15), "2026-01-16T05:00:00+00:00", False),
        (date(2026, 11, 1), "2026-11-01T01:30:00-04:00", True),
        (date(2026, 11, 1), "2026-11-01T01:30:00-05:00", True),
    ],
)
def test_new_york_capture_date_and_partition_cutoff(tmp_path, day, captured, accepted):
    store = MarketStore(tmp_path / "untouched-until-save")
    timestamp = datetime.fromisoformat(captured)
    source = _source()
    if not accepted:
        with pytest.raises(
            ValueError, match="archive cannot precede its declared capture date"
        ):
            archive.save(store, TICKER, day, source, captured_at=timestamp)
        assert not store.root.exists()
        return
    assert archive.save(store, TICKER, day, source, captured_at=timestamp)
    found = archive.load(MarketStore(store.root), TICKER, day)
    assert found.source.body == source.body
    assert found.asof == day
    assert found.captured_at == timestamp.astimezone(UTC)
    assert archive.load(store, TICKER, date.fromordinal(day.toordinal() - 1)) is None


# A later archive date is allowed but cannot make an earlier cutoff borrow its bytes.
def test_delayed_archive_partition_does_not_backfill_capture_day(tmp_path):
    store = MarketStore(tmp_path)
    earlier = date(2026, 9, 24)
    source = _source()
    capture = datetime(2026, 9, 24, 20, tzinfo=UTC)
    assert archive.save(store, TICKER, DAY, source, captured_at=capture)
    assert archive.load(store, TICKER, earlier) is None
    found = archive.load(store, TICKER, DAY)
    assert (found.asof, found.captured_at, found.source) == (DAY, capture, source)


class _NoStoreAccess:
    """A sentinel that fails before any filesystem-backed store operation can run."""

    # Turn every attempted store lookup into direct evidence that validation ran late.
    def __getattr__(self, name):
        raise AssertionError(f"invalid symbol reached store attribute {name}")


# Reject hostile symbol shapes before touching any store method or creating a path.
@pytest.mark.parametrize(
    "ticker",
    [
        "/tmp/TEST",
        "../TEST",
        "TEST/../OTHER",
        "TEST\\OTHER",
        "TEST\x00OTHER",
        "TEST\n",
        "TEST ",
        ".TEST",
        "-TEST",
        "ＴEST",
        "TÉST",
        "A" * 33,
        b"TEST",
        Path("TEST"),
        None,
    ],
)
def test_malicious_symbol_shape_never_reaches_store(ticker):
    with pytest.raises(ValueError, match="ticker must be an uppercase symbol"):
        archive.save(_NoStoreAccess(), ticker, DAY, _source(), captured_at=CAPTURED)
    with pytest.raises(ValueError, match="ticker must be an uppercase symbol"):
        archive.load(_NoStoreAccess(), ticker, DAY)


# Unsupported monetary labels stay literal after storage and cannot be projected as USD.
def test_archive_preserves_unsupported_units_and_source_paths(tmp_path):
    labels = ("EUR", "USD", "usd", "CAD", "USD/shares", "USD/millions")
    source = _source(200, labels)
    store = MarketStore(tmp_path)
    assert archive.save(store, TICKER, DAY, source, captured_at=CAPTURED)
    found = archive.load(MarketStore(tmp_path), TICKER, DAY)
    assert found.source.body == source.body
    assert found.source.sha256 == hashlib.sha256(source.body).hexdigest()
    assert tuple(fact.unit for fact in found.source.facts) == labels
    assert found.source.facts == source.facts
    projection = units.project(found.source)
    assert len(projection.versions) == 1
    assert projection.versions[0].value == 201
    assert projection.accepted_facts[0].unit == "USD"
    rejected = {
        exclusion.unit: (exclusion.reason, exclusion.source_path)
        for exclusion in projection.exclusions
    }
    assert set(rejected) == set(labels) - {"USD"}
    for fact in found.source.facts:
        if fact.unit != "USD":
            assert rejected[fact.unit] == (
                "unsupported_unit_for_projection",
                fact.source_path,
            )


# An archive loaded before a concurrent newer import keeps its original resolved cutoff.
def test_loader_pins_resolved_partition_during_newer_import(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    source = _source(100)
    assert archive.save(store, TICKER, DAY, source, captured_at=CAPTURED)
    real_read = store.read_frame
    seen = []

    # Publish a valid next-day response after resolution and before the actual read.
    def publish_then_read(kind, ticker, asof=None):
        seen.append(asof)
        assert archive.save(
            store,
            ticker,
            date(2026, 9, 26),
            _source(900),
            captured_at=datetime(2026, 9, 26, 21, tzinfo=UTC),
        )
        return real_read(kind, ticker, asof)

    monkeypatch.setattr(store, "read_frame", publish_then_read)
    found = archive.load(store, TICKER)
    assert seen == [DAY]
    assert found.asof == DAY
    assert found.source == source
    assert (
        archive.load(MarketStore(tmp_path), TICKER).source.facts[0].version.value == 900
    )
