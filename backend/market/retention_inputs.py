"""Read-only authenticated daily OHLCV inputs for retention research.

The store's daily OHLC basis is preserved verbatim. No intraday data, price
conversion, interpolation, provider fallback, account or model is consulted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

import numpy as np

from backend.market import calendar as exchange
from backend.market import open_source_portfolio
from backend.market.learned_entry_models import _array_hash
from backend.market.panel import Panel

FIELDS = ("open", "high", "low", "close", "adjusted_close", "volume")


# Hash input bytes without asking a parser to interpret unauthenticated contents.
def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


# Require reviewed coverage and every exchange session between the supplied endpoints.
def _calendar(dates):
    paths = (exchange.HISTORICAL_SESSIONS_PATH, exchange.HOLIDAYS_PATH)
    before = {str(path): _hash(path) for path in paths}
    years, sessions = exchange.reviewed_sessions()
    used = set(dates.astype("datetime64[Y]").astype(int) + 1970)
    missing = sorted(used - years)
    if missing:
        raise ValueError(f"Unreviewed exchange calendar years: {missing}")
    span = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
    expected = span[np.is_busday(span, busdaycal=sessions)]
    if not np.array_equal(dates, expected):
        raise ValueError(
            "Snapshot must contain the complete reviewed exchange calendar"
        )
    if any(_hash(path) != digest for path, digest in before.items()):
        raise ValueError("Exchange calendar source changed while reading")
    return {
        "exchange": "XNYS",
        "used_years": sorted(int(year) for year in used),
        "reviewed_years": sorted(years),
        "sources_sha256": before,
        "dates_sha256": _array_hash(dates),
        "sessions": len(dates),
        "first": str(dates[0]),
        "last": str(dates[-1]),
        "complete": True,
    }


# Resolve exactly one declared original daily partition per required safe basename.
def _sources(provenance, symbols):
    cutoff = provenance.get("source_cutoff")
    try:
        if str(np.datetime64(cutoff, "D")) != cutoff:
            raise ValueError("Noncanonical source cutoff")
    except (TypeError, ValueError) as exc:
        raise ValueError("Canonical original daily source cutoff required") from exc
    sources = {}
    for symbol in symbols:
        if Path(symbol).name != symbol or "\\" in symbol or symbol in (".", ".."):
            raise ValueError("Safe original ticker basenames required")
        matches = [
            key
            for key in provenance["source_hashes"]
            if isinstance(key, str) and PurePosixPath(key).name == f"{symbol}.parquet"
        ]
        if len(matches) != 1:
            raise ValueError(f"Exactly one original daily source required: {symbol}")
        path = PurePosixPath(matches[0])
        if (
            not path.is_absolute()
            or ".." in path.parts
            or str(path) != matches[0]
            or path.parent.name != f"asof={cutoff}"
            or path.parent.parent.name != "bars"
        ):
            raise ValueError(f"Original daily partition path invalid: {symbol}")
        sources[symbol] = (matches[0], provenance["source_hashes"][matches[0]])
    return sources


# Load optional parquet support explicitly; absence never activates a substitute source.
def _parquet_dependencies():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required for authenticated daily parquet inputs"
        ) from exc
    return pa, pq


# Refuse invalid column types, price signs and nonintegral or negative volumes.
def _column(table, field, symbol, pa):
    kind = table.schema.field(field).type
    if not (pa.types.is_floating(kind) or pa.types.is_integer(kind)):
        raise ValueError(f"Numeric original daily {field} required: {symbol}")
    value = np.asarray(table[field].to_pylist(), dtype=float)
    invalid = np.isinf(value) | (
        np.isfinite(value) & (value < 0 if field == "volume" else value <= 0)
    )
    if invalid.any() or (
        field == "volume" and np.any(np.isfinite(value) & (value != np.floor(value)))
    ):
        raise ValueError(f"Invalid original daily {field}: {symbol}")
    return value


# Parse authenticated store bytes with exact ticker and partition metadata.
def _history(path, symbol, source, digest, cutoff):
    if not path.is_file():
        raise ValueError(f"Original daily parquet unavailable: {symbol}")
    if path.is_symlink() or path.resolve().parent != path.parent.resolve():
        raise ValueError(f"Daily source must be a direct original basename: {symbol}")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError(f"Original daily parquet SHA256 mismatch: {symbol}")
    pa, pq = _parquet_dependencies()
    table = pq.ParquetFile(pa.BufferReader(payload)).read()
    if (
        len(table.column_names) != len(set(table.column_names))
        or not {"session_date", *FIELDS}.issubset(table.column_names)
        or not pa.types.is_date32(table.schema.field("session_date").type)
    ):
        raise ValueError(f"Original daily store schema required: {symbol}")
    metadata = table.schema.metadata or {}
    if (
        metadata.get(b"ticker") != symbol.encode()
        or metadata.get(b"asof") != cutoff.encode()
    ):
        raise ValueError(f"Original daily ticker/partition metadata mismatch: {symbol}")
    dates = np.asarray(table["session_date"].to_pylist(), dtype="datetime64[D]")
    if not len(dates) or np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError(
            f"Original daily sessions must be unique and ordered: {symbol}"
        )
    values = {field: _column(table, field, symbol, pa) for field in FIELDS}
    complete = np.all(
        np.isfinite(
            np.column_stack([values[k] for k in ("open", "high", "low", "close")])
        ),
        axis=1,
    )
    if np.any(
        complete
        & (
            (values["low"] > np.minimum(values["open"], values["close"]))
            | (values["high"] < np.maximum(values["open"], values["close"]))
            | (values["low"] > values["high"])
        )
    ):
        raise ValueError(f"Inconsistent original daily OHLC range: {symbol}")
    if _hash(path) != digest:
        raise ValueError(f"Original daily bytes changed while reading: {symbol}")
    return (
        dates,
        values,
        {
            "source_path": source,
            "sha256": digest,
            "rows": len(dates),
            "metadata": {
                key.decode(): value.decode() for key, value in metadata.items()
            },
        },
    )


# Preserve missing history and refuse disagreements with frozen snapshot prices.
def _align(snapshot, stock, history_dates, values):
    dates = snapshot.dates
    rows = np.searchsorted(dates, history_dates)
    if np.any(rows >= len(dates)) or not np.array_equal(
        dates[np.minimum(rows, len(dates) - 1)], history_dates
    ):
        raise ValueError("Original daily source has dates outside snapshot calendar")
    aligned = {field: np.full(len(dates), np.nan) for field in FIELDS}
    for field in FIELDS:
        aligned[field][rows] = values[field]
    for field, target in (
        ("open", "open"),
        ("close", "close"),
        ("adjusted_close", "adj_close"),
    ):
        if not np.array_equal(
            aligned[field], getattr(snapshot, target)[:, stock], equal_nan=True
        ):
            raise ValueError(
                f"Original daily {field} differs from snapshot basis/calendar"
            )
    return aligned


# Return a full daily panel and authenticated lineage while preserving every input byte.
def load(snapshot, provenance_path, daily_dir):
    snapshot, provenance_path, daily_dir = (
        Path(snapshot),
        Path(provenance_path),
        Path(daily_dir),
    )
    before = {path: _hash(path) for path in (snapshot, provenance_path)}
    basic, grades, eligible, provenance = open_source_portfolio.load_snapshot(
        snapshot, provenance_path
    )
    calendar = _calendar(basic.dates)
    sources = _sources(provenance, basic.tickers)
    if str(basic.dates[-1]) != provenance["source_cutoff"]:
        raise ValueError("Snapshot endpoint must match original daily source cutoff")
    arrays = {field: np.full(basic.open.shape, np.nan) for field in FIELDS}
    receipts = {}
    for stock, symbol in enumerate(basic.tickers):
        source, digest = sources[symbol]
        path = daily_dir / f"{symbol}.parquet"
        dates, values, receipt = _history(
            path, symbol, source, digest, provenance["source_cutoff"]
        )
        aligned = _align(basic, stock, dates, values)
        for field in FIELDS:
            arrays[field][:, stock] = aligned[field]
        receipts[symbol] = {
            **receipt,
            "absent_snapshot_sessions": len(basic.dates) - len(dates),
        }
    if any(_hash(path) != digest for path, digest in before.items()):
        raise ValueError("Snapshot/provenance bytes changed while reading")
    if any(
        _hash(daily_dir / f"{symbol}.parquet") != digest
        for symbol, (_, digest) in sources.items()
    ):
        raise ValueError(
            "Original daily source bytes changed during full panel assembly"
        )
    panel = Panel(
        basic.dates,
        basic.tickers,
        arrays["open"],
        arrays["high"],
        arrays["low"],
        arrays["close"],
        arrays["adjusted_close"],
        arrays["volume"],
        {},
        "SPY",
    )
    receipt = {
        "schema": "retention-daily-inputs/1",
        "snapshot_sha256": before[snapshot],
        "provenance_sha256": before[provenance_path],
        "snapshot_provenance": provenance,
        "daily_sources": receipts,
        "calendar": calendar,
        "price_basis": "original_store_daily_ohlc_basis_preserved_without_conversion",
        "missingness": "source_nan_and_absent_history_preserved_no_fill",
        "themes": "unavailable_in_snapshot",
        "symbols": list(panel.tickers),
        "arrays_sha256": {
            field: _array_hash(getattr(panel, field))
            for field in (
                "dates",
                "open",
                "high",
                "low",
                "close",
                "adj_close",
                "volume",
            )
        },
        "grades_sha256": _array_hash(grades),
        "eligible_sha256": _array_hash(eligible),
        "source_sha256": {
            str(path.relative_to(Path(__file__).resolve().parents[2])): _hash(path)
            for path in (
                Path(__file__).resolve(),
                Path(open_source_portfolio.__file__).resolve(),
                Path(exchange.__file__).resolve(),
                Path(__file__).resolve().parent / "panel.py",
            )
        },
    }
    # Plain JSON lineage cannot hide nonfinite floats or parser-specific metadata.
    json.dumps(receipt, allow_nan=False)
    return panel, grades, eligible, receipt
