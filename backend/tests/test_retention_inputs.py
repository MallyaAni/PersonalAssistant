"""Whole-panel daily byte, calendar and price-basis authentication acceptance."""

import builtins
import copy
import hashlib
import json
from datetime import date

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.market import retention_inputs as inputs


# Hash exact synthetic source bytes independently of the loader's implementation.
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Build store-shaped parquet files and an authenticated three-symbol panel.
def fixture(tmp_path, *, sparse=False, dates=None):
    dates = np.array(
        dates or ["2026-09-28", "2026-09-29", "2026-09-30"], dtype="datetime64[D]"
    )
    symbols = ("ONE", "SPY", "QQQ")
    opening = np.arange(len(dates) * 3, dtype=float).reshape(len(dates), 3) + 100
    closing = opening + 0.5
    adjusted = closing * 0.97
    if sparse:
        opening[0, 0] = closing[0, 0] = adjusted[0, 0] = np.nan
    daily = tmp_path / "daily"
    daily.mkdir()
    hashes = {}
    cutoff = str(dates[-1])
    for stock, symbol in enumerate(symbols):
        kept = np.arange(1 if sparse and stock == 0 else 0, len(dates))
        table = pa.table(
            {
                "session_date": pa.array(
                    dates[kept].astype(object).tolist(), type=pa.date32()
                ),
                "open": pa.array(opening[kept, stock], type=pa.float64()),
                "high": pa.array(closing[kept, stock] + 2, type=pa.float64()),
                "low": pa.array(opening[kept, stock] - 2, type=pa.float64()),
                "close": pa.array(closing[kept, stock], type=pa.float64()),
                "adjusted_close": pa.array(adjusted[kept, stock], type=pa.float64()),
                "volume": pa.array([1000 + stock] * len(kept), type=pa.int64()),
            }
        ).replace_schema_metadata(
            {
                b"ticker": symbol.encode(),
                b"asof": cutoff.encode(),
                b"source": b"synthetic",
                b"source_time": b"2026-09-30T22:00:00+00:00",
                b"complete_through": cutoff.encode(),
            }
        )
        path = daily / f"{symbol}.parquet"
        pq.write_table(table, path)
        hashes[f"/original/market/bars/asof={cutoff}/{symbol}.parquet"] = digest(path)
    snapshot = tmp_path / "snapshot.npz"
    membership = np.zeros(opening.shape, bool)
    membership[:, 0] = True
    np.savez(
        snapshot,
        dates=dates,
        symbols=np.array(symbols),
        open=opening,
        close=closing,
        adj_close=adjusted,
        grades=np.full(opening.shape, 2, dtype=np.int64),
        eligible=membership,
    )
    provenance = tmp_path / "provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "price_basis": "close-ratio-adjusted",
                "eligibility_mode": "recomputed-current-vintage",
                "source_cutoff": cutoff,
                "snapshot_sha256": digest(snapshot),
                "source_hashes": hashes,
            }
        )
    )
    return snapshot, provenance, daily


# Rehash synthetic evidence to exercise semantic checks after authentication.
def replace_table(args, transform):
    _, provenance, daily = args
    path = daily / "ONE.parquet"
    table = pq.ParquetFile(path).read()
    pq.write_table(transform(table), path)
    evidence = json.loads(provenance.read_text())
    key = next(key for key in evidence["source_hashes"] if key.endswith("/ONE.parquet"))
    evidence["source_hashes"][key] = digest(path)
    provenance.write_text(json.dumps(evidence))


# Confirm every field, grade, membership, date and unchanged original source byte.
def test_complete_panel_exact_basis_arrays_and_readonly_receipt(tmp_path):
    args = fixture(tmp_path)
    paths = [args[0], args[1], *args[2].glob("*.parquet")]
    before = {path: digest(path) for path in paths}
    panel, grades, eligible, receipt = inputs.load(*args)
    with np.load(args[0], allow_pickle=False) as snapshot:
        for key in ("dates", "open", "close", "adj_close"):
            np.testing.assert_array_equal(getattr(panel, key), snapshot[key])
        np.testing.assert_array_equal(grades, snapshot["grades"])
        np.testing.assert_array_equal(eligible, snapshot["eligible"])
    np.testing.assert_array_equal(panel.high, panel.close + 2)
    np.testing.assert_array_equal(panel.low, panel.open - 2)
    np.testing.assert_array_equal(panel.volume, np.tile([1000, 1001, 1002], (3, 1)))
    assert panel.tickers == ("ONE", "SPY", "QQQ")
    assert panel.benchmark == "SPY"
    assert receipt["calendar"]["complete"] is True
    assert receipt["calendar"]["used_years"] == [2026]
    assert receipt["snapshot_sha256"] == before[args[0]]
    assert set(receipt["daily_sources"]) == set(panel.tickers)
    assert {path: digest(path) for path in paths} == before


# Keep prelisting absent history as declared NaNs while retaining all calendar rows.
def test_explicit_sparse_stock_history_does_not_drop_sessions(tmp_path):
    panel, _, _, receipt = inputs.load(*fixture(tmp_path, sparse=True))
    assert len(panel.dates) == 3
    assert np.isnan(panel.high[0, 0])
    assert np.isnan(panel.volume[0, 0])
    assert receipt["daily_sources"]["ONE"]["absent_snapshot_sessions"] == 1
    assert np.isfinite(panel.high[1:, 0]).all()


# Daily high/low remain on the exact close basis despite an adjusted-close factor.
def test_daily_split_adjusted_basis_is_not_scaled_as_intraday_cube(tmp_path):
    panel, _, _, _ = inputs.load(*fixture(tmp_path))
    assert panel.high[0, 0] == 102.5
    assert panel.low[0, 0] == 98
    assert panel.adj_close[0, 0] == pytest.approx(97.485)
    assert panel.high[0, 0] != pytest.approx(102.5 * 0.97)


# Detect modified bytes before the parquet parser can authenticate replacement content.
def test_changed_original_source_hash_rejected(tmp_path):
    args = fixture(tmp_path)
    path = args[2] / "ONE.parquet"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SHA256"):
        inputs.load(*args)


# Missing originals cannot silently activate a provider or retain a reduced universe.
def test_missing_required_original_rejected(tmp_path):
    args = fixture(tmp_path)
    (args[2] / "QQQ.parquet").unlink()
    with pytest.raises(ValueError, match="unavailable"):
        inputs.load(*args)


# Semantic schema and observed-price corruption must fail even with new declared hashes.
@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "foreign_date",
        "price",
        "ticker",
        "partition",
        "missing_column",
        "volume",
        "range",
        "string",
    ],
)
def test_rehashed_semantic_corruption_rejected(tmp_path, defect):
    args = fixture(tmp_path)

    # Change one independently authenticated table contract at a time.
    def corrupt(table):
        if defect == "duplicate":
            return pa.concat_tables([table.slice(0, 1), table])
        if defect == "foreign_date":
            return table.set_column(
                0,
                "session_date",
                pa.array(
                    [date(2026, 9, 27), date(2026, 9, 29), date(2026, 9, 30)],
                    type=pa.date32(),
                ),
            )
        if defect in ("ticker", "partition"):
            metadata = copy.deepcopy(table.schema.metadata)
            metadata[b"ticker" if defect == "ticker" else b"asof"] = b"WRONG"
            return table.replace_schema_metadata(metadata)
        if defect == "missing_column":
            return table.drop(["high"])
        field = {
            "price": "adjusted_close",
            "volume": "volume",
            "range": "high",
            "string": "low",
        }[defect]
        value = {"price": 999.0, "volume": -1.0, "range": 1.0, "string": "invalid"}[
            defect
        ]
        values = table[field].to_pylist()
        values[0] = value
        if defect == "string":
            values = [str(value) for value in values]
        return table.set_column(
            table.column_names.index(field), field, pa.array(values)
        )

    replace_table(args, corrupt)
    with pytest.raises(
        ValueError, match="required|ordered|metadata|outside|differs|Invalid|range"
    ):
        inputs.load(*args)


# Refuse absent rows that were present in the authoritative snapshot.
def test_missing_known_snapshot_row_rejected(tmp_path):
    args = fixture(tmp_path)
    replace_table(args, lambda table: table.slice(1))
    with pytest.raises(ValueError, match="calendar"):
        inputs.load(*args)


# Refuse ambiguous, noncanonical, or wrong-partition original source identities.
@pytest.mark.parametrize("defect", ["duplicate", "relative", "traversal", "partition"])
def test_source_path_provenance_refused(tmp_path, defect):
    args = fixture(tmp_path)
    evidence = json.loads(args[1].read_text())
    key = next(key for key in evidence["source_hashes"] if key.endswith("/ONE.parquet"))
    value = evidence["source_hashes"].pop(key)
    new = {
        "duplicate": key,
        "relative": key.lstrip("/"),
        "traversal": key.replace("/market/", "/market/../market/"),
        "partition": key.replace("2026-09-30", "2026-09-29"),
    }[defect]
    evidence["source_hashes"][new] = value
    if defect == "duplicate":
        evidence["source_hashes"][
            "/another/market/bars/asof=2026-09-30/ONE.parquet"
        ] = value
    args[1].write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="source|required|path"):
        inputs.load(*args)


# Reject unreviewed years, closures and omitted exchange sessions.
@pytest.mark.parametrize(
    "dates",
    [
        ["2014-01-02", "2014-01-03"],
        ["2026-07-02", "2026-07-03"],
        ["2026-09-28", "2026-09-30"],
    ],
)
def test_reviewed_complete_exchange_calendar_required(tmp_path, dates):
    args = fixture(tmp_path, dates=dates)
    with pytest.raises(ValueError, match="calendar"):
        inputs.load(*args)


# Accept the newly reviewed2015 year while keeping earlier unreviewed years blocked.
def test_reviewed_2015_context_calendar_is_explicit(tmp_path):
    args = fixture(tmp_path, dates=["2015-01-02", "2015-01-05"])
    panel, _, _, receipt = inputs.load(*args)
    assert str(panel.dates[0]) == "2015-01-02"
    assert receipt["calendar"]["used_years"] == [2015]
    assert 2015 in receipt["calendar"]["reviewed_years"]


# Follow no symlink to a different original source despite identical byte content.
def test_daily_basename_symlink_refused(tmp_path):
    args = fixture(tmp_path)
    path = args[2] / "ONE.parquet"
    actual = tmp_path / "other.parquet"
    path.rename(actual)
    path.symlink_to(actual)
    with pytest.raises(ValueError, match="basename"):
        inputs.load(*args)


# Dependency absence is explicit and cannot switch data providers or input formats.
def test_missing_parquet_dependency_has_no_fallback(monkeypatch):
    original = builtins.__import__

    # Intercept only the optional dependency to exercise its explicit refusal path.
    def unavailable(name, *args, **kwargs):
        if name == "pyarrow":
            raise ImportError("synthetic optional dependency absence")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(RuntimeError, match="pyarrow is required"):
        inputs._parquet_dependencies()
