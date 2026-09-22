"""Read-only adapter over the cached market parquet and desk JSON partitions.

Research-only, per ``docs/research/intraday-comparison-protocol-2026-09-22.md``
and its input audit. This module supplies the observations a later reviewed
replay needs: ONE symbol's intraday bars from an explicitly chosen
``bars_15m/asof=...`` partition, ONE symbol's daily rows from an explicitly
chosen ``bars/asof=...`` partition, and the archived desk eligibility records
for that symbol from an explicitly supplied list of ``desk/asof=.../desk.json``
paths.

It never writes, never fetches, never calls a model, never recomputes a grade,
never infers a price basis and never assumes a scoring authorization: loading
observations is an input to a later review, not an outcome. Partitions are
always explicit paths - there is no implicit latest-partition lookup.

The cached Alpaca intraday bars were fetched with ``adjustment=all``
(``backend/market/alpaca.py``), yet the schema metadata omits the adjustment
flag. This adapter therefore accepts only an explicitly declared ``adjusted``
price basis and rejects any other declaration; the basis is carried in the
provenance together with the persistent limitation that it comes from the
inspected fetch code and the partition declaration, not from the files
themselves, and that a basis label cannot prove that every corporate-action
scale agrees between providers.

Row order, duplicates and missing values are preserved for causal validation:
a non-numeric price cell becomes NaN with a counted data-quality reason, and a
later malformed OHLCV row never rejects an earlier prefix. Timestamp and date
failures remain explicit exceptions because their causal location is
unknowable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq

from backend.market.intraday_comparison import DailyRow
from backend.market.intraday_entry import Bar
from backend.market.intraday_inputs import RecordedEligibility

# The one price basis this adapter accepts, matching how the cache was fetched.
PRICE_BASIS_ADJUSTED = "adjusted"

# The expected schema-metadata source labels of the two price caches.
INTRADAY_SOURCE = "alpaca-iex"
DAILY_SOURCE = "yahoo"

# Persistent limitation: the basis is a declaration, not an independent attestation.
BASIS_LIMITATION = (
    "price basis is taken from the inspected fetch code "
    "(backend/market/alpaca.py requests adjustment=all) and the explicit "
    "partition declaration; it is not independently attested inside the "
    "cached files, and a basis label cannot prove that every corporate-action "
    "scale agrees between providers"
)

# Loading supplies inputs to a later reviewed replay; it authorizes no scoring.
LOADING_NOT_SCORING = (
    "loading cached observations only supplies inputs to a later reviewed "
    "replay; it does not itself authorize or perform any scoring"
)

# An explicit as-of partition is a directory named asof=YYYY-MM-DD.
_PARTITION_RE = re.compile(r"^asof=(\d{4}-\d{2}-\d{2})$")


# Every source file's identity, hash, partition, units and data bounds.
@dataclass(frozen=True)
class CacheProvenance:
    """Which file, its hash, its partition, its units and its data bounds."""

    source_path: str
    sha256: str
    partition_label: str
    metadata_source: str | None
    price_basis: str | None
    row_count: int
    data_bounds: tuple[str | None, str | None]
    limitation: str


# Counted data-quality notes, so a NaN row is explained and never silent.
@dataclass(frozen=True)
class DataQuality:
    """Counts of preserved-but-degraded cells, keyed by reason."""

    reason_counts: dict[str, int]


# One symbol's raw intraday bars, order and duplicates preserved.
@dataclass(frozen=True)
class IntradayCache:
    """The symbol's ordered raw bars plus their provenance and quality notes."""

    symbol: str
    bars: tuple[Bar, ...]
    provenance: CacheProvenance
    quality: DataQuality


# One symbol's raw daily rows, order and duplicates preserved.
@dataclass(frozen=True)
class DailyCache:
    """The symbol's ordered raw daily rows plus provenance and quality notes."""

    symbol: str
    rows: tuple[DailyRow, ...]
    provenance: CacheProvenance
    quality: DataQuality


# An explicit desk record that could not supply a publication-time observation.
@dataclass(frozen=True)
class EligibilityIssue:
    """One desk record that was invalid or lacked publication/session."""

    source_path: str
    reason: str


# The archived eligibility observations and every source file's provenance.
@dataclass(frozen=True)
class EligibilityCache:
    """Chronological RecordedEligibility objects, issues, and file provenance."""

    symbol: str
    records: tuple[RecordedEligibility, ...]
    issues: tuple[EligibilityIssue, ...]
    provenance: tuple[CacheProvenance, ...]


# The explicit as-of label of a partition, validated to be consistent.
def _asof_label(partition_dir: Path) -> str:
    """Return the validated asof=YYYY-MM-DD label of an explicit partition."""
    match = _PARTITION_RE.match(partition_dir.name)
    if match is None:
        raise ValueError(
            "inconsistent explicit partition "
            f"{str(partition_dir)!r}: expected a directory named asof=YYYY-MM-DD"
        )
    date.fromisoformat(match.group(1))
    return match.group(0)


# The date component of a validated as-of label.
def _asof_date(label: str) -> str:
    """Return the YYYY-MM-DD date inside an asof=YYYY-MM-DD label."""
    match = _PARTITION_RE.match(label)
    if match is None:
        raise ValueError(f"not an asof partition label: {label!r}")
    return str(match.group(1))


# Hash and parse one byte snapshot so provenance identifies consumed observations.
def _read_cache(path: Path, expected: str, label: str) -> tuple[Any, str, str]:
    payload = path.read_bytes()
    table = pq.read_table(pa.BufferReader(payload))
    metadata = table.schema.metadata or {}
    raw_source = metadata.get(b"source")
    source = raw_source.decode("utf-8") if raw_source is not None else None
    if source is None:
        raise ValueError(
            f"cache {str(path)!r} declares no source metadata; cannot verify"
        )
    if source != expected:
        raise ValueError(
            f"cache {str(path)!r} declares source {source!r}, expected {expected!r}"
        )
    raw_asof = metadata.get(b"asof")
    declared = raw_asof.decode("utf-8") if raw_asof is not None else None
    if declared is not None and declared != _asof_date(label):
        raise ValueError(
            f"cache {str(path)!r} declares asof {declared!r}, inconsistent "
            f"with the explicit partition {label!r}"
        )
    return table, hashlib.sha256(payload).hexdigest(), source


# Accept only the declared adjusted basis this adapter is documented to serve.
def _checked_basis(price_basis: str | None) -> str:
    """Raise unless ``price_basis`` is the declared adjusted basis."""
    if price_basis != PRICE_BASIS_ADJUSTED:
        raise ValueError(
            f"this cache adapter accepts only the declared "
            f"{PRICE_BASIS_ADJUSTED!r} price basis (the cached Alpaca bars were "
            f"fetched with adjustment=all); got {price_basis!r}"
        )
    return PRICE_BASIS_ADJUSTED


# Coerce a start timestamp cell, raising because its causal place is unknown.
def _parse_start(value: object) -> datetime:
    """Return a timezone-aware start timestamp, or raise on a bad one."""
    if value is None:
        raise ValueError(
            "missing intraday timestamp; its causal location is unknowable"
        )
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except ValueError as exc:
        raise ValueError(
            f"invalid intraday timestamp {value!r}; its causal location is unknowable"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("intraday timestamp lacks a timezone; causal time is unknown")
    return parsed


# Coerce a daily session-date cell, raising because its causal place is unknown.
def _parse_session_date(value: object) -> date:
    """Return a daily session date, or raise on a missing or invalid one."""
    if value is None:
        raise ValueError(
            "missing daily session_date; its causal location is unknowable"
        )
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"invalid daily session_date {text!r}; its causal location is unknowable"
        ) from exc


# Coerce one numeric cell to a float, preserving the row as NaN when unreadable.
def _numeric(value: object, column: str, counts: dict[str, int]) -> float:
    """Return the cell as a float, or NaN with a counted reason when not."""
    if value is None:
        counts[f"non-numeric {column}"] += 1
        return float("nan")
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            counts[f"non-numeric {column}"] += 1
            return float("nan")
    try:
        return float(cast("Any", value))
    except (TypeError, ValueError):
        counts[f"non-numeric {column}"] += 1
        return float("nan")


# The ordered raw bars of one intraday table, preserving every row.
def _intraday_bars(table: Any) -> tuple[tuple[Bar, ...], DataQuality]:
    """Return (ordered Bar rows, quality notes) from a bars_15m table."""
    try:
        starts = table.column("start").to_pylist()
        opens = table.column("open").to_pylist()
        highs = table.column("high").to_pylist()
        lows = table.column("low").to_pylist()
        closes = table.column("close").to_pylist()
        volumes = table.column("volume").to_pylist()
    except (KeyError, AttributeError) as exc:
        raise ValueError("intraday cache lacks a required column") from exc
    counts: dict[str, int] = defaultdict(int)
    seen: set[datetime] = set()
    bars: list[Bar] = []
    for index in range(len(starts)):
        start = _parse_start(starts[index])
        if start in seen:
            counts["duplicate start"] += 1
        seen.add(start)
        bars.append(
            Bar(
                start=start,
                open=_numeric(opens[index], "open", counts),
                high=_numeric(highs[index], "high", counts),
                low=_numeric(lows[index], "low", counts),
                close=_numeric(closes[index], "close", counts),
                volume=_numeric(volumes[index], "volume", counts),
            )
        )
    return tuple(bars), DataQuality(dict(counts))


# The ordered raw daily rows of one daily table, preserving every row.
def _daily_rows(table: Any) -> tuple[tuple[DailyRow, ...], DataQuality]:
    """Return (ordered DailyRow rows, quality notes) from a daily bars table."""
    try:
        dates = table.column("session_date").to_pylist()
        closes = table.column("close").to_pylist()
        adjusted = table.column("adjusted_close").to_pylist()
    except (KeyError, AttributeError) as exc:
        raise ValueError("daily cache lacks a required column") from exc
    counts: dict[str, int] = defaultdict(int)
    seen: set[date] = set()
    rows: list[DailyRow] = []
    for index in range(len(dates)):
        session_date = _parse_session_date(dates[index])
        if session_date in seen:
            counts["duplicate session_date"] += 1
        seen.add(session_date)
        rows.append(
            DailyRow(
                session_date,
                _numeric(closes[index], "close", counts),
                _numeric(adjusted[index], "adjusted_close", counts),
            )
        )
    return tuple(rows), DataQuality(dict(counts))


# Load one symbol's raw intraday bars from an explicit as-of partition.
def load_intraday(
    symbol: str, partition_dir: Path | str, *, price_basis: str | None
) -> IntradayCache:
    """Return the symbol's raw ordered bars and full provenance.

    ``partition_dir`` is an explicit ``bars_15m/asof=YYYY-MM-DD`` path; the
    partition is never inferred. ``price_basis`` must declare the adjusted
    basis this adapter serves. Row order, duplicates and non-numeric cells are
    preserved; a missing or invalid timestamp raises because its causal
    location is unknowable.
    """
    basis = _checked_basis(price_basis)
    if not symbol:
        raise ValueError("a symbol is required")
    partition = Path(partition_dir)
    label = _asof_label(partition)
    path = partition / f"{symbol}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"no intraday parquet for {symbol} under {partition}")
    table, digest, source = _read_cache(path, INTRADAY_SOURCE, label)
    bars, quality = _intraday_bars(table)
    first = min(b.start for b in bars).astimezone(UTC).isoformat() if bars else None
    last = max(b.start for b in bars).astimezone(UTC).isoformat() if bars else None
    provenance = CacheProvenance(
        source_path=str(path),
        sha256=digest,
        partition_label=label,
        metadata_source=source,
        price_basis=basis,
        row_count=len(bars),
        data_bounds=(first, last),
        limitation=f"{BASIS_LIMITATION}. {LOADING_NOT_SCORING}",
    )
    return IntradayCache(symbol, bars, provenance, quality)


# Load one symbol's raw daily rows from an explicit as-of partition.
def load_daily(
    symbol: str, partition_dir: Path | str, *, price_basis: str | None
) -> DailyCache:
    """Return the symbol's raw ordered daily rows and full provenance.

    ``partition_dir`` is an explicit ``bars/asof=YYYY-MM-DD`` path; the
    partition is never inferred. ``price_basis`` must declare the adjusted
    basis this adapter serves. Row order, duplicates and non-numeric cells are
    preserved; a missing or invalid session date raises because its causal
    location is unknowable.
    """
    basis = _checked_basis(price_basis)
    if not symbol:
        raise ValueError("a symbol is required")
    partition = Path(partition_dir)
    label = _asof_label(partition)
    path = partition / f"{symbol}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"no daily parquet for {symbol} under {partition}")
    table, digest, source = _read_cache(path, DAILY_SOURCE, label)
    rows, quality = _daily_rows(table)
    first = min(r.date for r in rows).isoformat() if rows else None
    last = max(r.date for r in rows).isoformat() if rows else None
    provenance = CacheProvenance(
        source_path=str(path),
        sha256=digest,
        partition_label=label,
        metadata_source=source,
        price_basis=basis,
        row_count=len(rows),
        data_bounds=(first, last),
        limitation=f"{BASIS_LIMITATION}. {LOADING_NOT_SCORING}",
    )
    return DailyCache(symbol, rows, provenance, quality)


# The recorded grade for a symbol, or None when the symbol or field is absent.
def _recorded_grade(grades: dict[str, object] | None, symbol: str) -> str | None:
    """Return the symbol's archived grade string, or None when unavailable."""
    if not grades:
        return None
    entry = grades.get(symbol)
    if not isinstance(entry, dict):
        return None
    grade = entry.get("grade")
    return grade if isinstance(grade, str) else None


# The recorded rejecting-band flag, a strict bool, or None when unknown.
def _recorded_rejecting_band(
    levels: dict[str, object] | None, symbol: str
) -> bool | None:
    """Return the symbol's archived rejecting_band, or None when unknown."""
    if not levels:
        return None
    entry = levels.get(symbol)
    if not isinstance(entry, dict):
        return None
    flag = entry.get("rejecting_band")
    return flag if isinstance(flag, bool) else None


# Parse one desk record into a symbol observation, raising on bad publication.
def _desk_record_for(record: object, symbol: str) -> RecordedEligibility:
    """Return the RecordedEligibility a valid desk record supplies for a symbol.

    Missing ``session`` or ``written``, or values that do not parse, raise:
    they are explicit unavailability/errors, never replaced by file mtime or
    the folder date. A missing symbol or missing grade/rejecting-band field
    still yields an observation with None values.
    """
    if not isinstance(record, dict):
        raise ValueError("desk record is not a JSON object")
    session_text = record.get("session")
    written_text = record.get("written")
    if not isinstance(session_text, str) or not isinstance(written_text, str):
        raise ValueError("desk record is missing session or written publication")
    try:
        session = date.fromisoformat(session_text)
        written = datetime.fromisoformat(written_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid desk record publication: {exc}") from exc
    if written.tzinfo is None or written.utcoffset() is None:
        raise ValueError("desk publication lacks an explicit timezone")
    grades = record.get("grades")
    levels = record.get("levels")
    return RecordedEligibility(
        session,
        written,
        _recorded_grade(grades if isinstance(grades, dict) else None, symbol),
        _recorded_rejecting_band(levels if isinstance(levels, dict) else None, symbol),
    )


# Order eligibility records by their actual written time, then their session.
def _chronological(
    records: list[RecordedEligibility],
) -> tuple[RecordedEligibility, ...]:
    """Return the records sorted by their validated aware publication times."""

    # Compare the absolute publication instants while preserving source timestamps.
    def key(record: RecordedEligibility) -> tuple[datetime, date]:
        return record.written_at, record.session

    return tuple(sorted(records, key=key))


# Load chronological archived eligibility for a symbol from explicit desk paths.
def load_recorded_eligibility(
    symbol: str, record_paths: list[Path | str]
) -> EligibilityCache:
    """Return the symbol's chronological archived eligibility and provenance.

    ``record_paths`` is an explicit list of ``desk/asof=.../desk.json`` files;
    none is inferred. Every valid record yields one symbol observation,
    including None grade/rejecting-band when the symbol or field is missing,
    so a later record cannot silently resurrect an earlier grade. A record
    whose publication or session is invalid or missing becomes an explicit
    EligibilityIssue rather than an observation, and file mtime and folder
    date are never used as publication. Callers must treat issues as unavailable
    evidence, not silently ignore them and revive an older grade.
    """
    if not symbol:
        raise ValueError("a symbol is required")
    records: list[RecordedEligibility] = []
    issues: list[EligibilityIssue] = []
    provenance: list[CacheProvenance] = []
    for record_path in record_paths:
        path = Path(record_path)
        if not path.is_file():
            raise FileNotFoundError(f"no desk record at {path}")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        label = _asof_label(path.parent)
        try:
            record = _desk_record_for(json.loads(payload), symbol)
            if record.session.isoformat() != _asof_date(label):
                raise ValueError("desk session conflicts with explicit partition")
        except (json.JSONDecodeError, ValueError) as exc:
            issues.append(EligibilityIssue(str(path), str(exc)))
            provenance.append(
                CacheProvenance(
                    source_path=str(path),
                    sha256=digest,
                    partition_label=label,
                    metadata_source=None,
                    price_basis=None,
                    row_count=0,
                    data_bounds=(None, None),
                    limitation=LOADING_NOT_SCORING,
                )
            )
            continue
        records.append(record)
        provenance.append(
            CacheProvenance(
                source_path=str(path),
                sha256=digest,
                partition_label=label,
                metadata_source=None,
                price_basis=None,
                row_count=1,
                data_bounds=(record.session.isoformat(), record.written_at.isoformat()),
                limitation=LOADING_NOT_SCORING,
            )
        )
    return EligibilityCache(
        symbol, _chronological(records), tuple(issues), tuple(provenance)
    )
