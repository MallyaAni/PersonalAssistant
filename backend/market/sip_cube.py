"""One ticker's complete SIP sessions as (sessions, slots) arrays.

The fifteen-minute studies want every complete regular session of a name
stacked into arrays shaped (N, 26): one row per session, one column per
slot from 09:30 to 15:45 New York. This module assembles that cube from
the raw-basis SIP store (`intraday_sip`, one partition per session) and
caches it on disk, because reading 2,700 partitions a name for 98 names
every time a study runs is minutes of parquet reads for numbers that do
not change once a session is stored.

What goes in. Only sessions the calendar schedules at the full 26 slots
and the store holds complete: a 13:00 early close (14 slots) is excluded
and counted, a partition the store marks incomplete is excluded and
counted, and a session with no daily bar before it in the daily store
(so no prior close, so no gap) is excluded and counted. The counts are
carried on the cube so a study can print what it left out.

Basis. The SIP bars are raw dollars as the tape printed them, so a row's
open, high, low, close are all on that session's own basis. The prior
close comes from the daily store, whose closes are split-adjusted as of
the fetch: multiplying a daily close by `split_factor(history, session)`
(the product of the split ratios dated *after* the session) puts it on
the session's raw basis, exactly as `intraday_sip.reconcile` does for the
session's own daily bar. A split dated on the session itself is not
"after" it, so a pre-split prior close is divided by that split, which is
what puts it beside a post-split open. (Scaling the prior close by its
*own* session's factor instead would leave it in pre-split dollars and
read a 2:1 split as a 50% overnight gap; the test with a synthetic split
pins the difference.)

Cache. `<store.root>/research/sip_cubes/<TICKER>.npz`, keyed by the
number of sessions the store holds, the newest session date and
`CUBE_VERSION`; any of the three changing rebuilds the cube. The key does
not read every partition's `fetched_at`, which would cost what the cache
saves. A change to the daily store's corporate actions alone does not
invalidate the cache; bump `CUBE_VERSION` or delete the file for that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from backend.market import intraday_sip
from backend.market.alpaca import bars_expected
from backend.market.store import MarketStore
from backend.market.yahoo import TickerHistory

# Bump when the cube's layout or assembly rule changes; stale caches rebuild.
CUBE_VERSION = 1
# Slots in a full regular session: 09:30 to 16:00 New York at fifteen minutes.
FULL_SESSION_SLOTS = 26
# Where cubes are cached, under the market store's root.
CACHE_DIR = Path("research") / "sip_cubes"
# Why a stored session is left out of the cube, in the order they are checked.
EXCLUSION_REASONS = ("early_close", "incomplete", "no_prior_close")


@dataclass(frozen=True)
class SessionCube:
    """One ticker's complete 26-slot sessions, stacked, on the raw basis."""

    ticker: str
    dates: np.ndarray  # (N,) datetime64[D], ascending
    open: np.ndarray  # (N, 26)
    high: np.ndarray  # (N, 26)
    low: np.ndarray  # (N, 26)
    close: np.ndarray  # (N, 26)
    volume: np.ndarray  # (N, 26)
    prior_close: np.ndarray  # (N,) previous session's close on this session's basis
    excluded: dict[str, int]  # reason -> sessions left out

    # Sessions in the cube.
    def __len__(self) -> int:
        return int(len(self.dates))


# The cache file for one ticker under the store's root.
def cache_path(store: MarketStore, ticker: str) -> Path:
    """Return the cube's cache path for ``ticker``."""
    return store.root / CACHE_DIR / f"{ticker}.npz"


# The key a cached cube must match to be reused: session count, newest
# session and the module version, as one array of strings.
def _cache_key(sessions: list[date]) -> np.ndarray:
    newest = sessions[-1].isoformat() if sessions else ""
    return np.array([str(len(sessions)), newest, str(CUBE_VERSION)])


# The daily store's close for every session date, on the store's
# (split-adjusted as of fetch) basis, ascending by date.
def _daily_closes(history: TickerHistory | None) -> tuple[np.ndarray, np.ndarray]:
    if history is None:
        return np.array([], dtype="datetime64[D]"), np.array([], dtype=float)
    rows = sorted(
        (b.session_date, float(b.close))
        for b in history.bars
        if b.close is not None and b.close > 0
    )
    if not rows:
        return np.array([], dtype="datetime64[D]"), np.array([], dtype=float)
    days = np.array([d for d, _ in rows], dtype="datetime64[D]")
    return days, np.array([c for _, c in rows], dtype=float)


# Assemble the cube by reading every stored session of the ticker. The
# prior close is the daily store's close of the last daily bar before the
# session, moved onto the session's raw basis by the session's own split
# factor (see the module docstring).
def build(
    store: MarketStore, ticker: str, history: TickerHistory | None = None
) -> SessionCube:
    """Return the cube read from the store, without touching the cache."""
    if history is None:
        history = store.read(ticker)
    daily_days, daily_close = _daily_closes(history)
    excluded = dict.fromkeys(EXCLUSION_REASONS, 0)
    dates: list[np.datetime64] = []
    columns: dict[str, list[list[float]]] = {
        k: [] for k in ("open", "high", "low", "close", "volume")
    }
    prior: list[float] = []
    for session in intraday_sip.sessions_available(store, ticker):
        if bars_expected(session) != FULL_SESSION_SLOTS:
            excluded["early_close"] += 1
            continue
        stored = intraday_sip.read_session(store, ticker, session)
        if stored is None:
            excluded["incomplete"] += 1
            continue
        bars, metadata = stored
        if metadata.get("complete") != "true" or len(bars) != FULL_SESSION_SLOTS:
            excluded["incomplete"] += 1
            continue
        # The last daily bar strictly before the session.
        before = int(
            np.searchsorted(daily_days, np.datetime64(session, "D"), side="left")
        )
        if before == 0:
            excluded["no_prior_close"] += 1
            continue
        factor = (
            intraday_sip.split_factor(history, session) if history is not None else 1.0
        )
        prior.append(daily_close[before - 1] * factor)
        dates.append(np.datetime64(session, "D"))
        columns["open"].append([b.open for b in bars])
        columns["high"].append([b.high for b in bars])
        columns["low"].append([b.low for b in bars])
        columns["close"].append([b.close for b in bars])
        columns["volume"].append([b.volume for b in bars])
    shape = (len(dates), FULL_SESSION_SLOTS)
    arrays = {
        k: (np.asarray(v, dtype=float) if v else np.zeros(shape))
        for k, v in columns.items()
    }
    return SessionCube(
        ticker=ticker,
        dates=np.asarray(dates, dtype="datetime64[D]"),
        open=arrays["open"],
        high=arrays["high"],
        low=arrays["low"],
        close=arrays["close"],
        volume=arrays["volume"],
        prior_close=np.asarray(prior, dtype=float),
        excluded=excluded,
    )


# Write the cube and its key to the cache file, atomically.
def _write_cache(path: Path, key: np.ndarray, cube: SessionCube) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".npz.tmp")
    with tmp.open("wb") as handle:
        np.savez(
            handle,
            key=key,
            ticker=np.array(cube.ticker),
            dates=cube.dates.astype("datetime64[D]"),
            open=cube.open,
            high=cube.high,
            low=cube.low,
            close=cube.close,
            volume=cube.volume,
            prior_close=cube.prior_close,
            excluded_reasons=np.array(list(cube.excluded)),
            excluded_counts=np.array(list(cube.excluded.values()), dtype=np.int64),
        )
    tmp.replace(path)


# Read a cached cube when its key matches, else None. A file that cannot
# be read is treated as a miss, never raised: the cache is a convenience.
def _read_cache(path: Path, key: np.ndarray, ticker: str) -> SessionCube | None:
    if not path.exists():
        return None
    try:
        with np.load(path) as data:
            if list(data["key"].astype(str)) != list(key.astype(str)):
                return None
            reasons = [str(r) for r in data["excluded_reasons"]]
            counts = [int(c) for c in data["excluded_counts"]]
            return SessionCube(
                ticker=ticker,
                dates=data["dates"].astype("datetime64[D]"),
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
                volume=data["volume"],
                prior_close=data["prior_close"],
                excluded=dict(zip(reasons, counts, strict=True)),
            )
    except (OSError, ValueError, KeyError):
        return None


# The cube for a ticker: from the cache when its key matches the store,
# else assembled from the partitions and written back.
def load(
    store: MarketStore, ticker: str, history: TickerHistory | None = None
) -> SessionCube:
    """Return ``ticker``'s cube, rebuilding the cache when it is stale."""
    key = _cache_key(intraday_sip.sessions_available(store, ticker))
    path = cache_path(store, ticker)
    cached = _read_cache(path, key, ticker)
    if cached is not None:
        return cached
    cube = build(store, ticker, history)
    _write_cache(path, key, cube)
    return cube
