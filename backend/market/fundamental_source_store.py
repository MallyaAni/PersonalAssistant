"""Original-byte filing archives for the explicit qualified research desk mode.

No acquisition, legacy migration or currency conversion occurs here. The caller
supplies the issuer and capture evidence; integrity checks do not authenticate
historical publication or ticker/share-class identity. Existing unitless frames
are never used as a fallback or rewritten.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime

from backend.market import fundamental_unit_sources as units
from backend.market.fundamentals_asof import NEW_YORK

KIND = "edgar_facts_unit_archives"
SCHEMA = "fundamental-source-archive/1"
_FIELDS = {
    "schema",
    "source_schema",
    "source_sha256",
    "cik",
    "ticker",
    "asof",
    "captured_at",
}


@dataclass(frozen=True, slots=True)
class StoredSource:
    """An authenticated byte archive and its caller-declared acquisition evidence."""

    source: units.UnitSource
    ticker: str
    asof: date
    captured_at: datetime


# Validate filename shape without treating a symbol as proof of issuer equivalence.
def _ticker(value):
    if not (
        type(value) is str
        and 1 <= len(value) <= 32
        and value[0].isascii()
        and value[0].isalnum()
        and all(
            "A" <= char <= "Z" or "0" <= char <= "9" or char in ".-" for char in value
        )
    ):
        raise ValueError("ticker must be an uppercase symbol, not a path")


# Keep archive dates separate from filing dates and refuse backdated acquisitions.
def _dates(asof, captured_at):
    if type(asof) is not date or not (
        type(captured_at) is datetime
        and captured_at.tzinfo is not None
        and captured_at.utcoffset() is not None
    ):
        raise ValueError("archive date and timezone-aware capture timestamp required")
    try:
        if captured_at.astimezone(NEW_YORK).date() > asof:
            raise ValueError("archive cannot precede its declared capture date")
        return captured_at.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("capture timestamp is outside the supported calendar") from exc


# Serialize archive writers so concurrent imports cannot replace the first response.
@contextmanager
def _writer_lock(path):
    try:
        import fcntl
    except ImportError as exc:
        raise ValueError("safe archive writing requires POSIX file locking") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


# Save one validated original response without replacing same-date or legacy data.
def save(store, ticker, asof, source, *, captured_at):
    _ticker(ticker)
    captured = _dates(asof, captured_at)
    source = units._validated(source)
    metadata = {
        "schema": SCHEMA,
        "source_schema": units.SCHEMA,
        "source_sha256": source.sha256,
        "cik": str(source.cik),
        "ticker": ticker,
        "asof": asof.isoformat(),
        "captured_at": captured.isoformat(),
    }
    with _writer_lock(store._path(KIND, asof, ticker)):
        return store.write_frame(KIND, asof, ticker, {"body": [source.body]}, metadata)


# Re-extract exact original bytes and refuse malformed archives instead of falling back.
def load(store, ticker, asof=None):
    _ticker(ticker)
    if asof is not None and type(asof) is not date:
        raise ValueError("archive cutoff must be a date")
    resolved = store._latest_of_kind(KIND, ticker, asof)
    if resolved is None:
        return None
    # Pin the resolved partition so a concurrent newer import cannot change this read.
    found = store.read_frame(KIND, ticker, resolved)
    if found is None:
        raise ValueError("resolved source archive disappeared")
    columns, metadata = found
    if (
        set(columns) != {"body"}
        or len(columns["body"]) != 1
        or type(columns["body"][0]) is not bytes
        or set(metadata) != _FIELDS
        or metadata.get("schema") != SCHEMA
        or metadata.get("source_schema") != units.SCHEMA
        or metadata.get("ticker") != ticker
        or metadata.get("asof") != resolved.isoformat()
    ):
        raise ValueError("source archive envelope or identity is invalid")
    try:
        captured = _dates(resolved, datetime.fromisoformat(metadata["captured_at"]))
        cik = int(metadata["cik"])
        if str(cik) != metadata["cik"]:
            raise ValueError("source archive CIK is not canonical")
        source = units.parse(
            columns["body"][0],
            expected_sha256=metadata["source_sha256"],
            expected_cik=cik,
        )
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("source archive evidence is malformed") from exc
    return StoredSource(source, ticker, resolved, captured)
