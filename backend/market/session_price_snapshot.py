"""One bounded, public display-price snapshot shared independently of browsers."""

import json
import math
import os
import stat
import tempfile
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.market import session_prices

try:
    import fcntl
except ImportError:
    fcntl = None

VERSION = 1
MAX_BYTES = 1_000_000
MAX_SYMBOLS = 256
MAX_AGE_SECONDS = 60
FEEDS = frozenset({"sip", "iex", "boats", "overnight"})
STATUSES = frozenset({"fresh", "stale", "unavailable"})
SESSIONS = frozenset(
    {"regular", "pre-market", "post-market", "overnight", "closed", "unknown"}
)
REASONS = frozenset(
    {
        "No fresh quote from available feeds",
        "Invalid or empty quote",
        "Missing or future quote timestamp",
        "Quote expired",
        "Indicative midpoint",
        "Quoted midpoint",
    }
)


# Require real process locking and no-follow reads; unsupported hosts stay inactive.
def supported():
    return (
        fcntl is not None
        and all(
            hasattr(fcntl, name) for name in ("flock", "LOCK_EX", "LOCK_NB", "LOCK_UN")
        )
        and all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_NONBLOCK"))
    )


# Supply a timezone-aware clock without consulting an exchange or broker.
def utc_now():
    return datetime.now(UTC)


# Accept bounded caller-supplied identifiers without expanding the desk universe.
def _symbols(values):
    if isinstance(values, (str, bytes)):
        raise ValueError("symbols require a bounded collection")
    result = set()
    for index, value in enumerate(values):
        if index >= MAX_SYMBOLS:
            raise ValueError("symbol collection exceeds the bound")
        if not isinstance(value, str) or not value or len(value) > 32:
            raise ValueError("invalid symbol")
        if not value.isascii() or any(char.isspace() for char in value):
            raise ValueError("invalid symbol")
        result.add(value)
    return tuple(sorted(result))


# Reject naive, malformed and unrepresentable timestamps before comparing them.
def _instant(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


# Require a usable wall clock rather than fabricating a collection time.
def _now(clock):
    value = clock()
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("snapshot clock requires a dated instant")
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValueError("snapshot clock requires a dated instant") from exc


# Check external enum fields without hashing malformed arrays or objects.
def _known(value, allowed):
    return isinstance(value, str) and value in allowed


# Keep missing display evidence explicit and free of arbitrary provider text.
def _unavailable(raw=None, reason="Snapshot unavailable"):
    raw = raw if isinstance(raw, dict) else {}
    feed = raw.get("feed") if _known(raw.get("feed"), FEEDS) else None
    stamp = _instant(raw.get("at"))
    return {
        "price": None,
        "at": raw.get("at") if stamp else None,
        "feed": feed,
        "session": (
            raw.get("session") if _known(raw.get("session"), SESSIONS) else "unknown"
        ),
        "indicative": feed == "overnight",
        "status": "unavailable",
        "reason": reason,
        "valid_until": None,
    }


# Build an honest empty envelope without claiming a new successful capture.
def _empty(symbols, session="unknown", as_of=None):
    return {
        "session": session,
        "as_of": as_of,
        "signal_scope": "regular-session",
        "quotes": {symbol: _unavailable() for symbol in symbols},
    }


# Validate positive finite midpoint geometry without carrying arbitrary provider fields.
def _prices(raw):
    try:
        values = [raw[key] for key in ("price", "bid", "ask")]
        if any(isinstance(value, bool) for value in values):
            return None
        price, bid, ask = [float(value) for value in values]
        if (
            not all(math.isfinite(value) and value > 0 for value in (price, bid, ask))
            or bid > ask
            or not math.isclose(price, bid / 2 + ask / 2, rel_tol=1e-12, abs_tol=1e-9)
        ):
            return None
        return {"price": price, "bid": bid, "ask": ask}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


# Match a stored deadline to the original observation's fixed freshness boundary.
def _deadline(raw, stamp):
    if stamp is None:
        return None
    try:
        deadline = stamp + timedelta(seconds=MAX_AGE_SECONDS)
    except OverflowError:
        return None
    return deadline if _instant(raw.get("valid_until")) == deadline else None


# Validate a stored row and expire its price without changing source evidence.
def _row(raw, captured, now, capture_stale):
    if not isinstance(raw, dict):
        return _unavailable()
    result = _unavailable(raw, "Invalid snapshot quote")
    if (
        not _known(raw.get("feed"), FEEDS)
        or not _known(raw.get("session"), SESSIONS)
        or type(raw.get("indicative")) is not bool
        or raw["indicative"] != (raw["feed"] == "overnight")
        or not _known(raw.get("status"), STATUSES)
        or (raw["status"] != "fresh" and raw.get("price") is not None)
    ):
        return result
    stamp = _instant(raw.get("at"))
    if stamp and (stamp > captured or stamp > now):
        return result
    if raw["status"] == "unavailable":
        reason = raw.get("reason")
        return {
            **result,
            "reason": (
                reason
                if _known(reason, REASONS)
                else "No fresh quote from available feeds"
            ),
        }
    deadline = _deadline(raw, stamp)
    if deadline is None:
        return result
    result["valid_until"] = raw["valid_until"]
    if raw["status"] == "stale":
        return {**result, "status": "stale", "reason": "Quote expired"}
    prices = _prices(raw)
    if prices is None:
        return result
    if capture_stale or now >= deadline:
        return {**result, "status": "stale", "reason": "Quote expired"}
    return {
        **result,
        **prices,
        "status": "fresh",
        "reason": "Indicative midpoint" if raw["indicative"] else "Quoted midpoint",
    }


# Keep only the public display contract, preserving its original capture timestamp.
def _snapshot(raw, symbols, completed, now):
    if not isinstance(raw, dict):
        return None
    captured = _instant(raw.get("as_of"))
    if (
        captured is None
        or captured > completed
        or captured > now
        or not _known(raw.get("session"), SESSIONS)
        or raw.get("signal_scope") != "regular-session"
        or not isinstance(raw.get("quotes"), dict)
    ):
        return None
    expired = (now - completed).total_seconds() >= MAX_AGE_SECONDS or (
        now - captured
    ).total_seconds() >= MAX_AGE_SECONDS
    return {
        "session": raw["session"],
        "as_of": raw["as_of"],
        "signal_scope": "regular-session",
        "quotes": {
            symbol: _row(raw["quotes"].get(symbol), captured, now, expired)
            for symbol in symbols
        },
    }


# Read a bounded regular file without following a substituted snapshot symlink.
def _load(folder):
    try:
        if folder.is_symlink():
            return None
        fd = os.open(
            folder / "latest.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
                return None
            payload = handle.read(MAX_BYTES + 1)
        return json.loads(payload) if len(payload) <= MAX_BYTES else None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


# Validate attempt metadata before it can suppress another collection or serve data.
def _metadata(raw, now):
    if (
        not isinstance(raw, dict)
        or type(raw.get("version")) is not int
        or raw["version"] != VERSION
    ):
        return None
    attempted, completed = (
        _instant(raw.get("attempted_at")),
        _instant(raw.get("completed_at")),
    )
    if attempted is None or completed is None or not attempted <= completed <= now:
        return None
    try:
        symbols = _symbols(raw.get("symbols", ()))
    except (ValueError, TypeError):
        return None
    if list(symbols) != raw.get("symbols") or not isinstance(raw.get("snapshot"), dict):
        return None
    return attempted, completed, symbols


# Atomically publish private-mode data and clean this attempt's temporary file.
def _publish(folder, payload):
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("snapshot exceeds the byte bound")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".latest-", suffix=".tmp", dir=folder, delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, folder / "latest.json")
        temporary = None
        directory = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# Collect under a shared file lock and replace old evidence after completed failures.
def collect(
    root, symbols, interval_seconds=15, fetch=session_prices.fetch, clock=utc_now
):
    symbols = _symbols(symbols)
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("collection interval must be positive and finite")
    now = _now(clock)
    status = {"status": "unavailable", "attempted_at": None, "completed_at": None}
    if not supported():
        return status
    folder = Path(root) / "desk" / "session-prices"
    fd = None
    locked = False
    try:
        if folder.is_symlink() or (folder / "latest.json").is_symlink():
            return status
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(
            folder / "collector.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return status
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            return {**status, "status": "busy"}
        now = _now(clock)
        previous = _load(folder)
        metadata = _metadata(previous, now)
        if (
            metadata
            and metadata[2] == symbols
            and (now - metadata[0]).total_seconds() < interval_seconds
        ):
            return {
                "status": "not_due",
                "attempted_at": previous["attempted_at"],
                "completed_at": previous["completed_at"],
            }
        attempted = now.isoformat()
        raw = None
        with suppress(Exception):
            raw = fetch(list(symbols)) if symbols else None
        completed = _now(clock)
        snapshot = _snapshot(raw, symbols, completed, completed)
        outcome = "collected" if snapshot is not None else "failed"
        _publish(
            folder,
            {
                "version": VERSION,
                "attempted_at": attempted,
                "completed_at": completed.isoformat(),
                "symbols": list(symbols),
                "snapshot": snapshot if snapshot is not None else _empty(symbols),
            },
        )
        return {
            "status": outcome,
            "attempted_at": attempted,
            "completed_at": completed.isoformat(),
        }
    except (OSError, ValueError, TypeError, OverflowError):
        return status
    finally:
        if fd is not None:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# Read persisted evidence, filter symbols and expire prices without writing.
def read(root, symbols, now=None):
    symbols = _symbols(symbols)
    if not supported():
        return _empty(symbols)
    now = _now(utc_now if now is None else lambda: now)
    payload = _load(Path(root) / "desk" / "session-prices")
    metadata = _metadata(payload, now)
    if metadata is None:
        return _empty(symbols)
    _, completed, captured_symbols = metadata
    supplied = _snapshot(payload["snapshot"], captured_symbols, completed, now)
    if supplied is None:
        return _empty(symbols)
    return {
        **supplied,
        "quotes": {
            symbol: supplied["quotes"].get(symbol, _unavailable()) for symbol in symbols
        },
    }
