"""Authenticate the frozen market inputs without fitting or changing the desk.

Only the pinned trusted pickle is deserialized. Source paths in the pinned
manifest are identifiers, never filesystem instructions: validated partitions
are relocated under the caller's store. Hashes establish snapshot identity,
not historical membership, vendor correctness or point-in-time publication.
"""

import hashlib
import json
import pickle
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath

import numpy as np

from backend.market.panel import Panel

REPORT_SHA256 = "d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26"
MANIFEST_SHA256 = "3e7f398610919674c4f798c4b359811aeac7a2d73d1c91dbf2f0e8446d0db8f6"
QQQ_SHA256 = "e496f36ebe70fd5ddbe25115cc44883b3c690b2fa71438436468725f37d55cd3"
ASOF = "2026-09-18"
SOURCE_ROOT = PurePosixPath("/home/animallya96/anios/data/market")
FIELDS = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "adj_close": "adjusted_close",
    "volume": "volume",
}


# Read once so the bytes authenticated are exactly the bytes subsequently parsed.
def _read_pinned(path, expected, label):
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError(f"{label}: cannot read source file") from exc
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"{label}: SHA256 mismatch")
    return payload


# Reject duplicate JSON keys instead of allowing a later declaration to replace one.
def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Manifest contains duplicate key: {key}")
        result[key] = value
    return result


# Require an ordered, unique list of safe symbols before constructing any paths.
def _symbols(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("Manifest tickers must be an ordered nonempty sequence")
    if any(
        not isinstance(value, str)
        or len(value) > 16
        or re.fullmatch(r"[A-Z0-9]+(?:[.-][A-Z0-9]+)*", value) is None
        for value in values
    ):
        raise ValueError("Manifest contains an invalid ticker")
    if len(set(values)) != len(values) or "SPY" not in values or "QQQ" in values:
        raise ValueError("Manifest tickers must be unique, include SPY and omit QQQ")
    return tuple(values)


# Translate only the exact declared bars/actions identifiers to safe relative paths.
def _manifest_sources(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    symbols = _symbols(manifest.get("tickers"))
    if manifest.get("report_sha256") != REPORT_SHA256:
        raise ValueError("Manifest identifies a different report")
    source_hashes = manifest.get("source_hashes")
    expected = {
        str(SOURCE_ROOT / kind / f"asof={ASOF}" / f"{symbol}.parquet"): (
            PurePosixPath(kind) / f"asof={ASOF}" / f"{symbol}.parquet"
        )
        for symbol in symbols
        for kind in ("bars", "actions")
    }
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(expected):
        raise ValueError("Manifest source paths do not match the exact Sep18 universe")
    sources = {}
    for identifier, relative in expected.items():
        digest = source_hashes[identifier]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(f"{relative}: invalid SHA256 declaration")
        sources[str(relative)] = digest
    sources[f"bars/asof={ASOF}/QQQ.parquet"] = QQQ_SHA256
    return symbols, sources


# Keep relocated reads inside the selected store even when it contains symlinks.
def _source_payloads(store_root, sources):
    try:
        root = Path(store_root).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Source store does not exist") from exc
    if not root.is_dir():
        raise ValueError("Source store must be a directory")
    payloads = {}
    for relative, digest in sources.items():
        parts = PurePosixPath(relative).parts
        if (
            len(parts) != 3
            or parts[0] not in ("bars", "actions")
            or parts[1] != f"asof={ASOF}"
            or re.fullmatch(r"[A-Z0-9]+(?:[.-][A-Z0-9]+)*\.parquet", parts[2]) is None
            or str(PurePosixPath(relative)) != relative
        ):
            raise ValueError("Invalid relative source partition")
        try:
            path = root.joinpath(*parts).resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"{relative}: source partition is missing") from exc
        if not path.is_relative_to(root):
            raise ValueError(f"{relative}: source partition escapes the selected store")
        payloads[relative] = _read_pinned(path, digest, relative)
    return payloads


# Decode the authenticated bytes directly, without reopening a mutable pathname.
def _parquet(payload, label):
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        table = pq.ParquetFile(pa.BufferReader(payload)).read()
        if len(set(table.column_names)) != len(table.column_names):
            raise ValueError("duplicate columns")
        metadata = {
            key.decode(): value.decode()
            for key, value in (table.schema.metadata or {}).items()
        }
        return table.to_pydict(), metadata
    except (pa.ArrowException, UnicodeError, ValueError) as exc:
        raise ValueError(f"{label}: invalid parquet records") from exc


# Preserve daily dates exactly and reject timestamps or implicit date conversions.
def _record_dates(values, label, *, empty=False):
    if not isinstance(values, list) or (not values and not empty):
        raise ValueError(f"{label}: daily records are required")
    if any(type(value) is not date for value in values):
        raise ValueError(f"{label}: dates must be daily dates without truncation")
    return np.asarray(values, dtype="datetime64[D]")


# Require real finite values before any float conversion can discard information.
def _numbers(values, count, label, *, volume=False):
    array = np.asarray(values)
    if array.shape != (count,) or array.dtype.kind not in "iuf":
        raise ValueError(f"{label}: real numeric records are required")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.asarray(array, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f"{label}: missing or nonfinite source value")
    if volume:
        if np.any(result < 0) or np.any(result != np.floor(result)):
            raise ValueError(f"{label}: volume must be nonnegative whole units")
    elif np.any(result <= 0):
        raise ValueError(f"{label}: source prices must be positive")
    return result


# Refuse missing, duplicate or extra sessions instead of trimming the comparison grid.
def _calendar_match(dates, expected, label):
    dates = np.asarray(dates)
    if (
        dates.ndim != 1
        or dates.dtype != np.dtype("datetime64[D]")
        or not len(dates)
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError(f"{label}: sessions must be sorted unique daily dates")
    if not np.array_equal(dates, expected):
        raise ValueError(f"{label}: incomplete or extra XNYS sessions")


# Obtain the actual exchange calendar or fail closed when its dependency is absent.
@lru_cache(maxsize=128)
def _exchange_sessions(first, last):
    try:
        import exchange_calendars
    except ImportError as exc:
        raise ValueError(
            "exchange_calendars is required for exact XNYS validation"
        ) from exc
    calendar = exchange_calendars.get_calendar("XNYS", start=first, end=last)
    return (
        calendar.sessions.values.astype("datetime64[D]"),
        exchange_calendars.__version__,
        calendar.session_close(last).to_pydatetime(),
    )


# Validate stored bars while preserving vendor envelope anomalies as explicit evidence.
def _bar_records(symbol, columns, metadata, expected_dates, final_close):
    if set(columns) != {"session_date", *FIELDS.values()}:
        raise ValueError(f"{symbol}: unexpected bar columns")
    dates = _record_dates(columns["session_date"], symbol)
    _calendar_match(dates, expected_dates, symbol)
    if metadata.get("ticker") != symbol or metadata.get("asof") != ASOF:
        raise ValueError(f"{symbol}: source identity or asof mismatch")
    if metadata.get("complete_through") != ASOF or str(dates[-1]) != ASOF:
        raise ValueError(f"{symbol}: source is not complete through the frozen vintage")
    try:
        stamp = datetime.fromisoformat(metadata["source_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{symbol}: invalid source timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None or not metadata.get("source"):
        raise ValueError(f"{symbol}: source and aware ingestion timestamp are required")
    if stamp < final_close:
        raise ValueError(
            f"{symbol}: source was ingested before the final session closed"
        )
    arrays = {
        field: _numbers(
            columns[source], len(dates), f"{symbol} {source}", volume=field == "volume"
        )
        for field, source in FIELDS.items()
    }
    envelope = (arrays["low"] > np.minimum(arrays["open"], arrays["close"])) | (
        arrays["high"] < np.maximum(arrays["open"], arrays["close"])
    )
    anomalies = [
        {
            "symbol": symbol,
            "session": str(dates[row]),
            **{
                field: float(arrays[field][row])
                for field in ("open", "high", "low", "close")
            },
        }
        for row in np.flatnonzero(envelope)
    ]
    return {
        "dates": dates,
        **arrays,
        "metadata": dict(metadata),
        "ohlc_anomalies": anomalies,
    }


# Validate dated action records without asserting that the vendor supplied every action.
def _action_records(symbol, columns):
    if set(columns) != {"action_date", "kind", "value"}:
        raise ValueError(f"{symbol}: unexpected action columns")
    dates = _record_dates(columns["action_date"], f"{symbol} actions", empty=True)
    kinds = columns["kind"]
    if len(kinds) != len(dates) or any(
        kind not in ("split", "dividend") for kind in kinds
    ):
        raise ValueError(f"{symbol}: invalid action kinds")
    values = _numbers(columns["value"], len(dates), f"{symbol} actions")
    keys = [(str(day), kind) for day, kind in zip(dates, kinds, strict=True)]
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise ValueError(f"{symbol}: duplicate or unordered action records")
    if np.any(dates > np.datetime64(ASOF)):
        raise ValueError(f"{symbol}: action beyond the frozen vintage")
    return {"records": len(values), "completeness_verified": False}


# Align exact source observations and retain absent pre-listing rows as missing values.
def _aligned(bars, dates, field):
    positions = np.searchsorted(bars["dates"], dates)
    covered = positions < len(bars["dates"])
    covered[covered] &= bars["dates"][positions[covered]] == dates[covered]
    result = np.full(len(dates), np.nan)
    result[covered] = bars[field][positions[covered]]
    return result


# Reconcile every original field and append QQQ only to independently owned matrices.
def _assemble(panel, bars):
    symbols = _symbols(panel.tickers)
    if panel.benchmark != "SPY" or set(bars) != {*symbols, "QQQ"}:
        raise ValueError("Source symbols or report benchmark do not match")
    dates = np.asarray(panel.dates)
    if dates.ndim != 1 or dates.dtype != np.dtype("datetime64[D]"):
        raise ValueError("Report requires exact daily dates")
    matrices = {}
    comparisons = 0
    for field in FIELDS:
        original = np.asarray(getattr(panel, field))
        if (
            original.shape != (len(dates), len(symbols))
            or original.dtype.kind not in "iuf"
        ):
            raise ValueError(f"Report {field}: invalid price matrix")
        for column, symbol in enumerate(symbols):
            expected = _aligned(bars[symbol], dates, field)
            if not np.array_equal(original[:, column], expected, equal_nan=True):
                raise ValueError(f"{symbol}: report/source {field} mismatch")
            comparisons += 1
        extra = _aligned(bars["QQQ"], dates, field)
        if not np.isfinite(extra).all():
            raise ValueError(f"QQQ: incomplete report-grid {field}")
        matrices[field] = np.column_stack((original, extra))
    return Panel(
        dates.copy(),
        (*symbols, "QQQ"),
        **matrices,
        themes={symbol: tuple(panel.themes.get(symbol, ())) for symbol in symbols}
        | {"QQQ": ()},
        benchmark="SPY",
    ), comparisons


# Load the frozen report and fully authenticated, reconciled Sep18 partitions.
def load(report_path, store_root, manifest_path):
    report_payload = _read_pinned(report_path, REPORT_SHA256, "Trusted report")
    manifest_payload = _read_pinned(manifest_path, MANIFEST_SHA256, "Source manifest")
    manifest = json.loads(manifest_payload, object_pairs_hook=_unique_object)
    symbols, sources = _manifest_sources(manifest)
    if len(symbols) != 95:
        raise ValueError("Frozen report must contain 95 original symbols")
    payloads = _source_payloads(store_root, sources)
    report = pickle.loads(report_payload)  # noqa: S301 - exact trusted bytes authenticated above
    original = report.panel
    if tuple(original.tickers) != symbols:
        raise ValueError("Original report symbols differ from the pinned manifest")
    expected, calendar_version, final_close = _exchange_sessions("2015-01-02", ASOF)
    _calendar_match(original.dates, expected, "Original report")
    if len(original.dates) != 2945:
        raise ValueError("Frozen report must contain 2945 sessions")
    bars, actions = {}, {}
    for symbol in (*symbols, "QQQ"):
        relative = f"bars/asof={ASOF}/{symbol}.parquet"
        columns, metadata = _parquet(payloads[relative], relative)
        dates = _record_dates(columns.get("session_date"), symbol)
        sessions, _, _ = _exchange_sessions(str(dates[0]), ASOF)
        bars[symbol] = _bar_records(symbol, columns, metadata, sessions, final_close)
        if symbol != "QQQ":
            relative = f"actions/asof={ASOF}/{symbol}.parquet"
            columns, _ = _parquet(payloads[relative], relative)
            actions[symbol] = _action_records(symbol, columns)
    separate, comparisons = _assemble(original, bars)
    anomalies = [
        item for records in bars.values() for item in records["ohlc_anomalies"]
    ]
    provenance = {
        "schema": "nested-market-sources/1",
        "asof": ASOF,
        "report_sha256": REPORT_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "source_hashes": sources,
        "source_bytes": {name: len(value) for name, value in payloads.items()},
        "verified_source_files": len(payloads),
        "verified_price_field_comparisons": comparisons,
        "original_symbols": list(symbols),
        "execution_symbols": list(separate.tickers),
        "source_metadata": {
            symbol: records["metadata"] for symbol, records in bars.items()
        },
        "final_session_close": final_close.isoformat(),
        "source_ingestion_after_final_close_verified": True,
        "action_records": actions,
        "exchange_calendar": "XNYS",
        "exchange_calendar_version": calendar_version,
        "sessions": len(original.dates),
        "first_session": str(original.dates[0]),
        "last_session": str(original.dates[-1]),
        "ohlc_envelope_anomalies": anomalies,
        "ohlc_envelope_anomaly_count": len(anomalies),
        "vendor_ohlc_consistency_verified": not anomalies,
        "source_values_repaired": False,
        "source_hashes_verified": True,
        "report_price_fields_verified": True,
        "exchange_calendar_verified": True,
        "historical_availability_verified": False,
        "historical_membership_verified": False,
        "precomputed_report_causality_verified": False,
        "adoption_eligible": False,
        "limitations": [
            "Ingestion timestamps and hashes do not prove historical publication "
            "or membership.",
            "The report's precomputed scores, grades and regimes are not "
            "causally revalidated.",
            "Corporate-action completeness and QQQ action history are not verified.",
            "Vendor OHLC envelope anomalies are retained without repair and "
            "can affect outcomes.",
        ],
    }
    return report, separate, provenance
