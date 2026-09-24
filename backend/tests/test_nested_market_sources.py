"""Pin trust, relocation, calendar and exact-price boundaries without real fits."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.market import nested_market_sources as source
from backend.market.panel import Panel

DATES = np.asarray(["2026-09-16", "2026-09-17", "2026-09-18"], dtype="datetime64[D]")
FINAL_CLOSE = datetime(2026, 9, 18, 20, tzinfo=UTC)


# Supply a small manifest with the same path and digest contract as production.
def _manifest():
    symbols = ["AAA", "SPY"]
    return {
        "tickers": symbols,
        "report_sha256": source.REPORT_SHA256,
        "source_hashes": {
            str(
                source.SOURCE_ROOT / kind / f"asof={source.ASOF}" / f"{symbol}.parquet"
            ): "a" * 64
            for symbol in symbols
            for kind in ("bars", "actions")
        },
    }


# Construct finalized raw records with explicit daily dates and source metadata.
def _bar_input(symbol="AAA", first=0):
    days = DATES[first:]
    prices = np.arange(10.0, 10.0 + len(days))
    columns = {
        "session_date": days.astype(object).tolist(),
        "open": prices.tolist(),
        "high": (prices + 1).tolist(),
        "low": (prices - 1).tolist(),
        "close": prices.tolist(),
        "adjusted_close": (prices / 2).tolist(),
        "volume": [100] * len(days),
    }
    metadata = {
        "ticker": symbol,
        "asof": source.ASOF,
        "complete_through": source.ASOF,
        "source": "yahoo",
        "source_time": "2026-09-18T23:33:00+00:00",
    }
    return columns, metadata


# Pass a synthetic finalized source through the real record validator.
def _bars(symbol="AAA", first=0):
    columns, metadata = _bar_input(symbol, first)
    return source._bar_records(symbol, columns, metadata, DATES[first:], FINAL_CLOSE)


# Build a ragged original report grid and a separate complete QQQ source.
def _assembly():
    bars = {"AAA": _bars(first=1), "SPY": _bars("SPY"), "QQQ": _bars("QQQ")}
    matrices = {
        field: np.column_stack((np.r_[np.nan, bars["AAA"][field]], bars["SPY"][field]))
        for field in source.FIELDS
    }
    panel = Panel(
        DATES.copy(),
        ("AAA", "SPY"),
        **matrices,
        themes={"AAA": ("test",)},
        benchmark="SPY",
    )
    return panel, bars


# Authenticate bytes once and return precisely the accepted payload.
def test_pinned_read_returns_authenticated_bytes_and_rejects_changes(tmp_path):
    path = tmp_path / "input.bin"
    payload = b"frozen source"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert source._read_pinned(path, digest, "fixture") == payload
    path.write_bytes(payload + b" changed")
    with pytest.raises(ValueError, match="fixture: SHA256 mismatch"):
        source._read_pinned(path, digest, "fixture")


# An untrusted public report must fail before any pickle deserialization occurs.
def test_public_load_rejects_untrusted_pickle_before_deserializing(
    tmp_path, monkeypatch
):
    path = tmp_path / "report.pickle"
    path.write_bytes(b"untrusted")

    # Make reaching the unsafe boundary a hard test failure.
    def forbidden(*args, **kwargs):
        pytest.fail("Untrusted pickle was deserialized")

    monkeypatch.setattr(source.pickle, "loads", forbidden)
    with pytest.raises(ValueError, match="Trusted report: SHA256 mismatch"):
        source.load(path, tmp_path, tmp_path / "missing-manifest.json")


# Missing artifacts must produce a bounded source error rather than be substituted.
def test_missing_pinned_file_fails_explicitly(tmp_path):
    with pytest.raises(ValueError, match="cannot read"):
        source._read_pinned(tmp_path / "absent", "a" * 64, "fixture")


# A repeated manifest key must not silently overwrite the earlier source declaration.
def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ValueError, match="duplicate key"):
        json.loads(
            '{"source_hashes": {}, "source_hashes": {}}',
            object_pairs_hook=source._unique_object,
        )


# Relocation preserves original sources and adds only the independently pinned QQQ bar.
def test_manifest_maps_only_expected_partitions():
    symbols, paths = source._manifest_sources(_manifest())
    assert symbols == ("AAA", "SPY")
    assert len(paths) == 5
    assert paths[f"bars/asof={source.ASOF}/QQQ.parquet"] == source.QQQ_SHA256
    assert all(not name.startswith("/") for name in paths)
    assert f"actions/asof={source.ASOF}/QQQ.parquet" not in paths


# Path shape changes cannot redirect a pinned-manifest source read.
@pytest.mark.parametrize(
    "replacement",
    [
        "/etc/passwd",
        "/other/market/bars/asof=2026-09-18/AAA.parquet",
        str(source.SOURCE_ROOT / "bars/asof=2026-09-23/AAA.parquet"),
        str(source.SOURCE_ROOT) + "/bars/asof=2026-09-18/../AAA.parquet",
        str(source.SOURCE_ROOT) + "/bars//asof=2026-09-18/AAA.parquet",
        str(source.SOURCE_ROOT / "bars/asof=2026-09-18/QQQ.parquet"),
    ],
)
def test_manifest_rejects_foreign_vintage_traversal_and_extra_symbols(replacement):
    manifest = _manifest()
    key = next(iter(manifest["source_hashes"]))
    manifest["source_hashes"][replacement] = manifest["source_hashes"].pop(key)
    with pytest.raises(ValueError, match="source paths"):
        source._manifest_sources(manifest)


# Partial manifests and malformed hashes cannot claim complete source verification.
@pytest.mark.parametrize("change", ["missing", "extra", "digest", "report"])
def test_manifest_rejects_incomplete_or_mismatched_contract(change):
    manifest = _manifest()
    key = next(iter(manifest["source_hashes"]))
    if change == "missing":
        manifest["source_hashes"].pop(key)
    elif change == "extra":
        manifest["source_hashes"][key + ".extra"] = "a" * 64
    elif change == "digest":
        manifest["source_hashes"][key] = "not a digest"
    else:
        manifest["report_sha256"] = "b" * 64
    with pytest.raises(
        ValueError, match="source paths|invalid SHA256|different report"
    ):
        source._manifest_sources(manifest)


# Reject unordered, duplicate, unsafe and misidentified symbol universes.
@pytest.mark.parametrize(
    "symbols",
    [
        set(("AAA", "SPY")),
        [],
        ["AAA"],
        ["AAA", "SPY", "QQQ"],
        ["SPY", "SPY"],
        ["../AAA", "SPY"],
        ["A/B", "SPY"],
        ["aaa", "SPY"],
        [True, "SPY"],
    ],
)
def test_manifest_rejects_invalid_symbols(symbols):
    manifest = _manifest()
    manifest["tickers"] = symbols
    with pytest.raises(ValueError, match="tickers|ticker"):
        source._manifest_sources(manifest)


# Read only validated relocated files and reject an actual changed source artifact.
def test_source_read_authenticates_relocated_bytes(tmp_path):
    relative = f"bars/asof={source.ASOF}/AAA.parquet"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"source")
    expected = {relative: hashlib.sha256(b"source").hexdigest()}
    assert source._source_payloads(tmp_path, expected) == {relative: b"source"}
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        source._source_payloads(tmp_path, expected)


# A symlink cannot move a source read outside the explicitly selected store.
def test_source_read_refuses_symlink_escape(tmp_path):
    root = tmp_path / "store"
    folder = root / "bars" / f"asof={source.ASOF}"
    folder.mkdir(parents=True)
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"source")
    (folder / "AAA.parquet").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        source._source_payloads(
            root, {f"bars/asof={source.ASOF}/AAA.parquet": "a" * 64}
        )


# The filesystem boundary independently refuses malformed relative partition names.
@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../AAA.parquet",
        "bars/asof=2026-09-23/AAA.parquet",
        "bars//asof=2026-09-18/AAA.parquet",
    ],
)
def test_source_read_rejects_unsafe_relative_paths(tmp_path, path):
    with pytest.raises(ValueError, match="Invalid relative"):
        source._source_payloads(tmp_path, {path: "a" * 64})


# Decode a real in-memory parquet artifact without allowing hive-path inference.
def test_parquet_decodes_values_and_metadata_from_supplied_bytes():
    columns, metadata = _bar_input()
    table = pa.table(columns).replace_schema_metadata(
        {k.encode(): v.encode() for k, v in metadata.items()}
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    actual_columns, actual_metadata = source._parquet(
        sink.getvalue().to_pybytes(), "fixture"
    )
    assert actual_columns == columns
    assert actual_metadata == metadata
    with pytest.raises(ValueError, match="invalid parquet"):
        source._parquet(b"not parquet", "fixture")


# Valid finalized records keep their exact numeric values and zero trading volume.
def test_bar_validation_accepts_explicit_complete_records():
    columns, metadata = _bar_input()
    columns["volume"][0] = 0
    result = source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)
    np.testing.assert_array_equal(result["adj_close"], [5, 5.5, 6])
    assert result["volume"][0] == 0
    assert result["ohlc_anomalies"] == []


# Vendor envelope defects remain visible and unchanged rather than being repaired.
def test_ohlc_anomalies_preserve_actual_values():
    columns, metadata = _bar_input()
    columns["open"][0] = 20.0
    columns["low"][1] = 11.1
    result = source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)
    assert result["open"][0] == 20.0
    assert result["low"][1] == 11.1
    assert [item["session"] for item in result["ohlc_anomalies"]] == [
        "2026-09-16",
        "2026-09-17",
    ]


# Later ingestion is not misrepresented as point-in-time historical publication.
def test_ingestion_after_vintage_is_allowed_but_intraday_ingestion_is_not():
    columns, metadata = _bar_input()
    metadata["source_time"] = "2026-09-20T10:00:00+00:00"
    assert (
        source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)["metadata"]
        == metadata
    )
    metadata["source_time"] = "2026-09-18T19:59:59+00:00"
    with pytest.raises(ValueError, match="before the final session closed"):
        source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)


# Every consumed price field rejects invalid observations before any outcome can run.
@pytest.mark.parametrize("field", ["open", "high", "low", "close", "adjusted_close"])
@pytest.mark.parametrize("bad", [None, np.nan, np.inf, 0, -1, 1 + 2j, True])
def test_bar_prices_reject_invalid_values(field, bad):
    columns, metadata = _bar_input()
    columns[field] = [bad] * len(DATES)
    with pytest.raises(ValueError, match=f"AAA {field}:"):
        source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)


# Non-whole, missing or non-real volumes cannot be silently cast into usable records.
@pytest.mark.parametrize("bad", [-1, 0.5, None, np.nan, np.inf, True, 1j])
def test_volume_rejects_invalid_values(bad):
    columns, metadata = _bar_input()
    columns["volume"] = [bad] * len(DATES)
    with pytest.raises(ValueError, match="AAA volume:"):
        source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)


# Metadata must identify the same asset, vintage, completeness and aware source clock.
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ticker", "BBB"),
        ("asof", "2026-09-23"),
        ("complete_through", "2026-09-17"),
        ("source_time", "2026-09-18T23:00:00"),
        ("source_time", "invalid"),
        ("source", ""),
    ],
)
def test_bar_metadata_rejects_mismatches(key, value):
    columns, metadata = _bar_input()
    metadata[key] = value
    with pytest.raises(ValueError, match="AAA: source|AAA: invalid source"):
        source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)


# Duplicate, missing or timestamp-truncated dates invalidate the source calendar.
@pytest.mark.parametrize(
    "change", ["duplicate", "reverse", "interior", "trailing", "timestamp"]
)
def test_bar_dates_refuse_calendar_changes(change):
    columns, metadata = _bar_input()
    if change == "duplicate":
        columns["session_date"][1] = columns["session_date"][0]
    elif change == "reverse":
        columns["session_date"].reverse()
    elif change == "timestamp":
        columns["session_date"][0] = datetime(2026, 9, 16, 12)
    else:
        row = 1 if change == "interior" else 2
        for values in columns.values():
            values.pop(row)
    with pytest.raises(ValueError, match="AAA: sessions|AAA: incomplete|AAA: dates"):
        source._bar_records("AAA", columns, metadata, DATES, FINAL_CLOSE)


# Grid checks cannot accept shuffled sessions, intraday timestamps or absent marks.
@pytest.mark.parametrize(
    "dates",
    [DATES[::-1], DATES[:2], np.r_[DATES, DATES[-1]], DATES.astype("datetime64[s]")],
)
def test_exact_calendar_refuses_mutated_grid(dates):
    with pytest.raises(ValueError, match="fixture: sessions|fixture: incomplete"):
        source._calendar_match(dates, DATES, "fixture")


# Corporate actions retain explicit records without inventing completeness evidence.
def test_actions_accept_empty_and_valid_records_without_claiming_completeness():
    empty = {"action_date": [], "kind": [], "value": []}
    assert source._action_records("AAA", empty) == {
        "records": 0,
        "completeness_verified": False,
    }
    valid = {
        "action_date": [date(2026, 9, 17)] * 2,
        "kind": ["dividend", "split"],
        "value": [0.5, 0.1],
    }
    assert source._action_records("AAA", valid)["records"] == 2


# Ambiguous, repeated or invalid action records cannot survive validation.
@pytest.mark.parametrize(
    "change",
    ["duplicate", "future", "kind", "zero", "negative", "nan", "timestamp", "columns"],
)
def test_actions_reject_invalid_records(change):
    columns = {"action_date": [date(2026, 9, 17)], "kind": ["split"], "value": [2.0]}
    if change == "duplicate":
        columns = {key: values * 2 for key, values in columns.items()}
    elif change == "future":
        columns["action_date"] = [date(2026, 9, 19)]
    elif change == "kind":
        columns["kind"] = ["unknown"]
    elif change == "timestamp":
        columns["action_date"] = [datetime(2026, 9, 17)]
    elif change == "columns":
        columns["extra"] = []
    else:
        columns["value"] = [{"zero": 0, "negative": -1, "nan": np.nan}[change]]
    with pytest.raises(ValueError, match="AAA"):
        source._action_records("AAA", columns)


# Appending QQQ must preserve ragged source identity and avoid mutating the incumbent.
def test_assembly_matches_every_field_and_owns_new_arrays():
    panel, bars = _assembly()
    original = {field: getattr(panel, field).copy() for field in source.FIELDS}
    separate, comparisons = source._assemble(panel, bars)
    assert comparisons == 12
    assert panel.tickers == ("AAA", "SPY")
    assert separate.tickers == ("AAA", "SPY", "QQQ")
    for field, values in original.items():
        actual = getattr(separate, field)
        np.testing.assert_array_equal(actual[:, :2], values)
        np.testing.assert_array_equal(actual[:, 2], bars["QQQ"][field])
        assert np.isnan(actual[0, 0])
        assert not np.shares_memory(actual, getattr(panel, field))
        actual[1, 0] = 999
        np.testing.assert_array_equal(getattr(panel, field), values)
    separate.dates[0] = np.datetime64("1900-01-01")
    np.testing.assert_array_equal(panel.dates, DATES)
    separate.themes["AAA"] = ()
    assert panel.themes["AAA"] == ("test",)


# A one-bit mismatch or invented pre-listing value must fail for all six source fields.
@pytest.mark.parametrize("field", tuple(source.FIELDS))
@pytest.mark.parametrize("change", ["finite", "missing", "invented"])
def test_assembly_rejects_any_report_field_mismatch(field, change):
    panel, bars = _assembly()
    values = getattr(panel, field)
    if change == "finite":
        values[1, 0] = np.nextafter(values[1, 0], np.inf)
    elif change == "missing":
        values[1, 0] = np.nan
    else:
        values[0, 0] = 10
    with pytest.raises(ValueError, match=f"report/source {field} mismatch"):
        source._assemble(panel, bars)


# A missing QQQ row must not shorten the incumbent grid or introduce a filled value.
def test_assembly_rejects_missing_qqq_price():
    panel, bars = _assembly()
    bars["QQQ"] = _bars("QQQ", first=1)
    with pytest.raises(ValueError, match="QQQ: incomplete"):
        source._assemble(panel, bars)


# The assembler rejects malformed or complex matrices rather than discarding their data.
@pytest.mark.parametrize("change", ["shape", "complex", "benchmark", "symbols"])
def test_assembly_rejects_invalid_panel_contract(change):
    panel, bars = _assembly()
    if change == "shape":
        panel = replace(panel, open=panel.open[:, :1])
    elif change == "complex":
        panel = replace(panel, open=panel.open.astype(complex))
    elif change == "benchmark":
        panel = replace(panel, benchmark="AAA")
    else:
        bars.pop("AAA")
    with pytest.raises(ValueError, match="Report open|Source symbols"):
        source._assemble(panel, bars)


# Missing exchange-calendar support must fail closed rather than use weekday heuristics.
def test_exchange_dependency_absence_is_an_explicit_error(monkeypatch):
    import sys

    source._exchange_sessions.cache_clear()
    monkeypatch.setitem(sys.modules, "exchange_calendars", None)
    with pytest.raises(ValueError, match="required for exact XNYS"):
        source._exchange_sessions("2026-09-16", source.ASOF)
    source._exchange_sessions.cache_clear()


# Check exceptional exchange closures and the frozen terminal closing instant.
def test_actual_xnys_grid_and_final_close_when_dependency_is_available():
    pytest.importorskip("exchange_calendars")
    dates, version, closing = source._exchange_sessions("2015-01-02", source.ASOF)
    assert len(dates) == 2945
    assert version
    assert dates[0] == np.datetime64("2015-01-02")
    assert dates[-1] == np.datetime64(source.ASOF)
    assert np.datetime64("2018-12-05") not in dates
    assert np.datetime64("2025-01-09") not in dates
    assert np.datetime64("2026-06-19") not in dates
    assert closing == FINAL_CLOSE
