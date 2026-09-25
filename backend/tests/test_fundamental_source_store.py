"""Original-byte financial archive boundaries through real Parquet persistence."""

import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa
from backend.market.store import MarketStore

ASOF = date(2026, 9, 25)
CAPTURED = datetime(2026, 9, 25, 21, 15, tzinfo=UTC)


# Keep original JSON whitespace, units and issuer identity observable after persistence.
def _source(value=100, unit="USD"):
    payload = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        unit: [
                            {
                                "start": "2026-04-01",
                                "end": "2026-06-30",
                                "val": value,
                                "filed": "2026-07-31",
                                "form": "10-Q",
                                "accn": "example",
                            }
                        ]
                    },
                }
            }
        },
    }
    body = json.dumps(payload, indent=2).encode() + b"\n"
    return units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )


# Preserve original bytes and unit evidence independently of same-day legacy partitions.
def test_source_archive_roundtrip_and_same_day_legacy_isolation(tmp_path):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    store = MarketStore(tmp_path)
    source = _source(unit="EUR")
    store.write_frame(
        fa.KIND, ASOF, "TEST", fa.frame([f.version for f in source.facts])
    )
    legacy_path = store._path(fa.KIND, ASOF, "TEST")
    original = legacy_path.read_bytes()
    assert archive.save(store, "TEST", ASOF, source, captured_at=CAPTURED)
    found = archive.load(store, "TEST", ASOF)
    assert found.source == source
    assert found.source.body == source.body
    assert found.captured_at == CAPTURED
    assert found.asof == ASOF
    assert found.ticker == "TEST"
    assert found.source.facts[0].unit == "EUR"
    assert legacy_path.read_bytes() == original


# A repeated archive import cannot overwrite any already stored original response.
def test_same_day_rerun_preserves_original_archive_bytes(tmp_path):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    store = MarketStore(tmp_path)
    assert archive.save(store, "TEST", ASOF, _source(), captured_at=CAPTURED)
    path = store._path(archive.KIND, ASOF, "TEST")
    original = path.read_bytes()
    assert not archive.save(store, "TEST", ASOF, _source(999), captured_at=CAPTURED)
    assert path.read_bytes() == original
    assert archive.load(store, "TEST", ASOF).source.facts[0].version.value == 100


# Extraction cutoffs never borrow a newer archive or pretend legacy rows retain units.
def test_cutoff_and_legacy_only_store_never_fall_back(tmp_path):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    store = MarketStore(tmp_path)
    store.write_frame(fa.KIND, date(2026, 9, 24), "TEST", fa.frame([]))
    archive.save(store, "TEST", ASOF, _source(), captured_at=CAPTURED)
    assert archive.load(store, "TEST", date(2026, 9, 24)) is None
    assert archive.load(store, "ABSENT", ASOF) is None
    assert archive.load(store, "TEST").asof == ASOF


# Source and archive identities must remain bound when read back, not merely present.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "old"),
        ("source_sha256", "0" * 64),
        ("cik", "2"),
        ("ticker", "OTHER"),
        ("asof", "2026-09-24"),
        ("captured_at", "2026-09-25T21:15:00"),
    ],
)
def test_corrupt_archive_metadata_is_refused(tmp_path, field, value):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    good = MarketStore(tmp_path / "good")
    archive.save(good, "TEST", ASOF, _source(), captured_at=CAPTURED)
    columns, metadata = good.read_frame(archive.KIND, "TEST", ASOF)
    metadata[field] = value
    bad = MarketStore(tmp_path / "bad")
    bad.write_frame(archive.KIND, ASOF, "TEST", columns, metadata)
    before = bad._path(archive.KIND, ASOF, "TEST").read_bytes()
    with pytest.raises(ValueError, match="archive|hash|CIK|capture"):
        archive.load(bad, "TEST", ASOF)
    assert bad._path(archive.KIND, ASOF, "TEST").read_bytes() == before


# Missing, duplicated or text-converted bodies cannot impersonate original bytes.
@pytest.mark.parametrize("bodies", [[], [b"{}", b"{}"], ["{}"], [b"{}"]])
def test_corrupt_archive_bodies_are_refused(tmp_path, bodies):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    good = MarketStore(tmp_path / "good")
    archive.save(good, "TEST", ASOF, _source(), captured_at=CAPTURED)
    _, metadata = good.read_frame(archive.KIND, "TEST", ASOF)
    bad = MarketStore(tmp_path / "bad")
    bad.write_frame(archive.KIND, ASOF, "TEST", {"body": bodies}, metadata)
    with pytest.raises(ValueError, match="archive|hash"):
        archive.load(bad, "TEST", ASOF)


# A claimed capture date cannot create an archive before the source was acquired.
@pytest.mark.parametrize(
    "captured",
    [
        datetime(2026, 9, 25, 21, 15),
        datetime(2026, 9, 26, 21, 15, tzinfo=UTC),
        "2026-09-25T21:15:00Z",
    ],
)
def test_invalid_or_future_capture_is_rejected_before_writing(tmp_path, captured):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    store = MarketStore(tmp_path)
    with pytest.raises(ValueError, match="capture"):
        archive.save(store, "TEST", ASOF, _source(), captured_at=captured)
    assert not store.has_frame(archive.KIND, ASOF, "TEST")


# A mutated parsed source cannot be archived under the original response's hash.
def test_source_dataclass_tampering_is_refused_before_writing(tmp_path):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    source = _source()
    changed = replace(source, facts=(replace(source.facts[0], unit="EUR"),))
    with pytest.raises(ValueError, match="UnitSource observations differ"):
        archive.save(MarketStore(tmp_path), "TEST", ASOF, changed, captured_at=CAPTURED)


# Ticker shape is a filesystem boundary, never a reason to reinterpret issuer identity.
@pytest.mark.parametrize("ticker", ["../TEST", "a/b", "..", "", "test", "TEST\\child"])
def test_invalid_ticker_is_refused_before_any_store_access(tmp_path, ticker):
    archive = importlib.import_module("backend.market.fundamental_source_store")
    store = MarketStore(tmp_path)
    with pytest.raises(ValueError, match="ticker"):
        archive.save(store, ticker, ASOF, _source(), captured_at=CAPTURED)
    with pytest.raises(ValueError, match="ticker"):
        archive.load(store, ticker, ASOF)
