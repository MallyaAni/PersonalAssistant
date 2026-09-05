"""An immutable, as-of partitioned store of daily market history.

The previous store was a Postgres table with an upsert, and that made
reproducibility impossible: adjusted closes are back-adjusted, so a
dividend rewrites a ticker's whole history on the next fetch and the upsert
silently replaced the old rows. This store keeps every fetch as it was:

    <root>/bars/asof=2026-09-04/CRWV.parquet
    <root>/actions/asof=2026-09-04/CRWV.parquet

A partition is written once and never modified. Reading "CRWV as of
2026-09-04" returns exactly what a run on that day saw, forever, and a
research result is reproducible by pinning its as-of date. A re-run on the
same day is a no-op for tickers already present, which is what lets a
refresh that was throttled halfway be resumed.

Parquet files on a local disk (spark1 has terabytes free) rather than the
assistant's production database: bulk, immutable, re-fetchable data has no
business in a store with nightly dumps and no point-in-time recovery.
"""

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from backend.market.yahoo import CorporateAction, DailyBar, TickerHistory

_BARS = "bars"
_ACTIONS = "actions"
_PARTITION_PREFIX = "asof="


@dataclass(frozen=True, slots=True)
class StoredTicker:
    """What the store holds for one ticker at one as-of date."""

    ticker: str
    asof: date
    bar_count: int
    first_session: date | None
    complete_through: date | None


# The directory name of an as-of partition.
def _partition(asof: date) -> str:
    return f"{_PARTITION_PREFIX}{asof.isoformat()}"


# The as-of date encoded in a partition directory name, or None if the name
# is not a partition.
def _partition_date(name: str) -> date | None:
    if not name.startswith(_PARTITION_PREFIX):
        return None
    try:
        return date.fromisoformat(name[len(_PARTITION_PREFIX) :])
    except ValueError:
        return None


class MarketStore:
    """Immutable as-of partitions of bars and corporate actions per ticker."""

    # `root` is created on first write. Nothing is read at construction.
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # The path of one ticker's bars or actions file in one partition.
    def _path(self, kind: str, asof: date, ticker: str) -> Path:
        return self.root / kind / _partition(asof) / f"{ticker}.parquet"

    # Whether a ticker already has bars in a partition.
    def has(self, asof: date, ticker: str) -> bool:
        """Return True when `ticker` is already stored as of `asof`."""
        return self._path(_BARS, asof, ticker).exists()

    # Write one fetch into a partition. Returns False, writing nothing, when
    # the partition already holds this ticker: partitions are immutable.
    def write(self, asof: date, history: TickerHistory) -> bool:
        """Store a ticker's history as of a date; no-op if already present."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        bars_path = self._path(_BARS, asof, history.ticker)
        if bars_path.exists():
            return False
        bars_path.parent.mkdir(parents=True, exist_ok=True)
        actions_path = self._path(_ACTIONS, asof, history.ticker)
        actions_path.parent.mkdir(parents=True, exist_ok=True)

        bars = history.bars
        bar_table = pa.table(
            {
                "session_date": pa.array([b.session_date for b in bars], pa.date32()),
                "open": pa.array([b.open for b in bars], pa.float64()),
                "high": pa.array([b.high for b in bars], pa.float64()),
                "low": pa.array([b.low for b in bars], pa.float64()),
                "close": pa.array([b.close for b in bars], pa.float64()),
                "adjusted_close": pa.array(
                    [b.adjusted_close for b in bars], pa.float64()
                ),
                "volume": pa.array([b.volume for b in bars], pa.int64()),
            }
        )
        metadata = {
            b"ticker": history.ticker.encode(),
            b"source": history.source.encode(),
            b"source_time": history.source_time.isoformat().encode(),
            b"complete_through": history.complete_through.isoformat().encode(),
            b"asof": asof.isoformat().encode(),
        }
        bar_table = bar_table.replace_schema_metadata(metadata)
        action_table = pa.table(
            {
                "action_date": pa.array(
                    [a.action_date for a in history.actions], pa.date32()
                ),
                "kind": pa.array([a.kind for a in history.actions], pa.string()),
                "value": pa.array([a.value for a in history.actions], pa.float64()),
            }
        )
        # Write to a temporary name and rename, so a crash mid-write never
        # leaves a half file that reads as a complete partition.
        _write_atomically(pq, bar_table, bars_path)
        _write_atomically(pq, action_table, actions_path)
        return True

    # Write a generic column frame (any kind, e.g. "edgar_events") into a
    # partition, immutably. Columns are lists of equal length; dates, floats,
    # ints, bools and strings are inferred by pyarrow. Returns False when the
    # partition already holds this ticker for this kind.
    def write_frame(
        self,
        kind: str,
        asof: date,
        ticker: str,
        columns: dict[str, list],
        metadata: dict[str, str] | None = None,
    ) -> bool:
        """Store one ticker's frame of `kind` as of a date; no-op if present."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = self._path(kind, asof, ticker)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table({k: pa.array(v) for k, v in columns.items()})
        if metadata:
            table = table.replace_schema_metadata(
                {k.encode(): v.encode() for k, v in metadata.items()}
            )
        _write_atomically(pq, table, path)
        return True

    # Whether a partition already holds a frame of `kind` for the ticker.
    def has_frame(self, kind: str, asof: date, ticker: str) -> bool:
        """Return True when the frame is already stored as of `asof`."""
        return self._path(kind, asof, ticker).exists()

    # Read a generic frame from the newest partition of `kind` on or before
    # `asof` holding the ticker, or None. Returns (columns, metadata).
    def read_frame(
        self, kind: str, ticker: str, asof: date | None = None
    ) -> tuple[dict[str, list], dict[str, str]] | None:
        """Return (columns, metadata) of the ticker's newest frame of `kind`."""
        import pyarrow.parquet as pq

        resolved = self._latest_of_kind(kind, ticker, asof)
        if resolved is None:
            return None
        table = pq.read_table(self._path(kind, resolved, ticker))
        meta = {
            k.decode(): v.decode() for k, v in (table.schema.metadata or {}).items()
        }
        return table.to_pydict(), meta

    # The newest partition of a kind holding the ticker on or before asof.
    def _latest_of_kind(self, kind: str, ticker: str, asof: date | None) -> date | None:
        base = self.root / kind
        if not base.exists():
            return None
        dates = sorted(
            d
            for d in (_partition_date(p.name) for p in base.iterdir() if p.is_dir())
            if d and (asof is None or d <= asof)
        )
        for candidate in reversed(dates):
            if self._path(kind, candidate, ticker).exists():
                return candidate
        return None

    # Every as-of date with at least one partition directory, oldest first.
    def asofs(self) -> list[date]:
        """Return the as-of dates present in the store, oldest first."""
        base = self.root / _BARS
        if not base.exists():
            return []
        dates = [
            d
            for d in (_partition_date(p.name) for p in base.iterdir() if p.is_dir())
            if d
        ]
        return sorted(dates)

    # The tickers stored in one partition, alphabetical.
    def tickers(self, asof: date) -> list[str]:
        """Return the tickers present as of a date."""
        base = self.root / _BARS / _partition(asof)
        if not base.exists():
            return []
        return sorted(p.stem for p in base.glob("*.parquet"))

    # The newest as-of date on or before `asof` that holds the ticker, or
    # None. With `asof` None, the newest of all.
    def latest_asof(self, ticker: str, asof: date | None = None) -> date | None:
        """Return the newest partition holding `ticker` on or before `asof`."""
        candidates = [d for d in self.asofs() if asof is None or d <= asof]
        for candidate in reversed(candidates):
            if self.has(candidate, ticker):
                return candidate
        return None

    # Read one ticker as it was on or before an as-of date. Returns None when
    # no partition up to that date holds it.
    def read(self, ticker: str, asof: date | None = None) -> TickerHistory | None:
        """Return the ticker's history from the newest partition <= `asof`."""
        import pyarrow.parquet as pq

        resolved = self.latest_asof(ticker, asof)
        if resolved is None:
            return None
        bar_table = pq.read_table(self._path(_BARS, resolved, ticker))
        meta = bar_table.schema.metadata or {}
        columns = bar_table.to_pydict()
        bars = tuple(
            DailyBar(
                session_date=columns["session_date"][i],
                open=columns["open"][i],
                high=columns["high"][i],
                low=columns["low"][i],
                close=columns["close"][i],
                adjusted_close=columns["adjusted_close"][i],
                volume=columns["volume"][i],
            )
            for i in range(bar_table.num_rows)
        )
        actions: tuple[CorporateAction, ...] = ()
        actions_path = self._path(_ACTIONS, resolved, ticker)
        if actions_path.exists():
            action_columns = pq.read_table(actions_path).to_pydict()
            actions = tuple(
                CorporateAction(
                    action_columns["action_date"][i],
                    action_columns["kind"][i],
                    action_columns["value"][i],
                )
                for i in range(len(action_columns["action_date"]))
            )
        return TickerHistory(
            ticker=ticker,
            bars=bars,
            actions=actions,
            complete_through=date.fromisoformat(meta[b"complete_through"].decode()),
            source_time=datetime.fromisoformat(meta[b"source_time"].decode()),
            source=meta.get(b"source", b"yahoo").decode(),
        )

    # A summary per ticker of what the newest partition <= `asof` holds,
    # without reading whole tables: parquet metadata carries the counts.
    def describe(
        self, tickers: Iterable[str], asof: date | None = None
    ) -> list[StoredTicker | None]:
        """Return one StoredTicker per requested ticker, None where absent."""
        import pyarrow.parquet as pq

        out: list[StoredTicker | None] = []
        for ticker in tickers:
            resolved = self.latest_asof(ticker, asof)
            if resolved is None:
                out.append(None)
                continue
            parquet = pq.ParquetFile(self._path(_BARS, resolved, ticker))
            meta = parquet.schema_arrow.metadata or {}
            count = parquet.metadata.num_rows
            first = None
            if count:
                first = (
                    parquet.read_row_group(0, columns=["session_date"])
                    .column(0)[0]
                    .as_py()
                )
            complete = meta.get(b"complete_through")
            out.append(
                StoredTicker(
                    ticker=ticker,
                    asof=resolved,
                    bar_count=count,
                    first_session=first,
                    complete_through=(
                        date.fromisoformat(complete.decode()) if complete else None
                    ),
                )
            )
        return out


# Write a table to a temporary sibling and rename it into place.
def _write_atomically(pq, table, path: Path) -> None:
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary)
    os.replace(temporary, path)


# A JSON-serialisable description of a store's partitions, for a status
# line or a handoff document.
def summarize(store: MarketStore) -> str:
    """Return a one-line JSON summary of partitions and ticker counts."""
    return json.dumps({d.isoformat(): len(store.tickers(d)) for d in store.asofs()})
