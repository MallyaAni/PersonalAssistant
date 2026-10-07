"""Load published prior-session context without recomputing research grades.

The recorded current book is a prospective universe, not a reconstructed
historical membership series. Yahoo's split-adjusted close is deliberately
not represented as an attested raw anchor for a later session.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from backend.market import calendar

GRADE_CODES = {"C": 0, "B": 1, "A": 2, "A+": 3}
DAILY_BASIS = "yahoo_split_and_dividend_adjusted_close"
PRIOR_CLOSE_BASIS = "yahoo_split_adjusted_as_of_prior_session_fetch"


# Keep the frozen causal matrices and distinct source-basis identities together.
@dataclass(frozen=True)
class ShadowContext:
    panel: SimpleNamespace
    grades: np.ndarray
    eligible: np.ndarray
    published_at: dict[str, datetime]
    split_adjusted_prior_closes: dict[str, float]
    raw_prior_closes: dict[str, float]
    provenance: dict


# Reject unknown publication instants instead of assuming a timezone or filesystem time.
def _instant(value, label):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} requires a publication timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"{label} requires a timezone-aware timestamp")
    return stamp


# Pin original bytes before parsing so a reader never mixes changing source files.
def _read(path, sources):
    path = Path(path)
    content = path.read_bytes()
    sources[str(path.absolute())] = {
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }
    return content


# Check every consumed file again after the entire context has been assembled.
def _check_unchanged(sources):
    for path, receipt in sources.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != receipt["sha256"]:
            raise ValueError("Concurrent source changes prevent a stable context")


# Read an explicit Yahoo vintage and retain its full published adjusted price history.
def _daily(path, ticker, prior, captured, sources):
    table = pq.read_table(pa.BufferReader(_read(path, sources)))
    metadata = {
        key.decode(): value.decode()
        for key, value in (table.schema.metadata or {}).items()
    }
    if (
        metadata.get("ticker") != ticker
        or metadata.get("source") != "yahoo"
        or metadata.get("asof") != prior.isoformat()
        or metadata.get("complete_through") != prior.isoformat()
    ):
        raise ValueError("Explicit fresh prior-session Yahoo metadata required")
    published = _instant(metadata.get("source_time"), "Daily history")
    closing = datetime.combine(prior, calendar.session_close(prior), calendar.NEW_YORK)
    if not closing <= published <= captured:
        raise ValueError(
            "Daily publication was unavailable or before session completion"
        )
    columns = table.to_pydict()
    required = {"session_date", "adjusted_close", "close"}
    if not required <= columns.keys():
        raise ValueError("Daily history lacks explicit adjusted/split-adjusted bases")
    days = np.asarray(columns["session_date"], dtype="datetime64[D]")
    adjusted = np.asarray(columns["adjusted_close"], dtype=float)
    close = np.asarray(columns["close"], dtype=float)
    if (
        days.ndim != 1
        or not len(days)
        or np.isnat(days).any()
        or np.any(days[1:] <= days[:-1])
        or days[-1] != np.datetime64(prior, "D")
        or not np.isfinite(adjusted[-1])
        or adjusted[-1] <= 0
        or not np.isfinite(close[-1])
        or close[-1] <= 0
        or np.isinf(adjusted).any()
        or np.any(np.isfinite(adjusted) & (adjusted <= 0))
    ):
        raise ValueError(
            "Daily rows must be ordered, unique and completed through prior"
        )
    sources[str(Path(path).absolute())].update(metadata=metadata)
    return days, adjusted, float(close[-1]), published


# Retain omitted reviewed exchange sessions as NaNs without inventing older coverage.
def _session_dates(observed, first, prior):
    years, sessions = calendar.reviewed_sessions()
    observed_years = observed.astype("datetime64[Y]").astype(int) + 1970
    covered = np.isin(observed_years, list(years))
    if np.any(covered & ~np.is_busday(observed, busdaycal=sessions)):
        raise ValueError("Daily source contains a non-session in reviewed coverage")
    end = np.datetime64(prior, "D") + np.timedelta64(1, "D")
    grid = np.arange(first, end, dtype="datetime64[D]")
    grid_years = grid.astype("datetime64[Y]").astype(int) + 1970
    grid = grid[
        np.isin(grid_years, list(years)) & np.is_busday(grid, busdaycal=sessions)
    ]
    unknown = observed[~covered & (observed >= first)]
    return np.unique(np.concatenate((grid, unknown)))


# Freeze the actual prior record and all its price histories for an upcoming session.
def load_context(record_path, daily_partition, session, captured_at):  # noqa: C901
    captured = _instant(captured_at, "Capture")
    session = date.fromisoformat(str(session))
    years, sessions = calendar.reviewed_sessions()
    if session.year not in years or not np.is_busday(
        np.datetime64(session, "D"), busdaycal=sessions
    ):
        raise ValueError("Upcoming session must be a reviewed exchange session")
    if captured.astimezone(calendar.NEW_YORK).date() != session:
        raise ValueError("Capture must belong to the actual upcoming session")
    prior = np.busday_offset(
        np.datetime64(session, "D"), -1, busdaycal=sessions
    ).astype(object)
    if prior.year not in years:
        raise ValueError("Prior exchange-session coverage unavailable")
    sources = {}
    record = json.loads(_read(record_path, sources))
    if record.get("session") != prior.isoformat():
        raise ValueError("Record must describe the immediately preceding session")
    published = _instant(record.get("written"), "Research record")
    prior_close = datetime.combine(
        prior, calendar.session_close(prior), calendar.NEW_YORK
    )
    if not prior_close <= published <= captured:
        raise ValueError("Research publication was unavailable or before completion")
    revision = (record.get("provenance") or {}).get("code_revision")
    if not isinstance(revision, str) or revision.strip().lower() in (
        "",
        "unknown",
        "unavailable",
    ):
        raise ValueError("Actual research-record source revision required")
    partition = Path(daily_partition)
    if partition.name != f"asof={prior.isoformat()}":
        raise ValueError("Explicit prior-session daily partition required")
    recorded = record.get("grades")
    if not isinstance(recorded, dict) or not recorded:
        raise ValueError("Actual recorded grades and current-book membership required")
    for ticker, row in recorded.items():
        if (
            not isinstance(ticker, str)
            or not ticker
            or Path(ticker).name != ticker
            or ticker in (".", "..")
            or not isinstance(row, dict)
            or row.get("grade") not in GRADE_CODES
        ):
            raise ValueError("Research record contains an invalid ticker or grade")
    names = tuple(sorted(set(recorded) | {"SPY", "QQQ"}))
    histories, closes, stamps = {}, {}, []
    for ticker in names:
        days, prices, closes[ticker], stamp = _daily(
            partition / f"{ticker}.parquet", ticker, prior, captured, sources
        )
        histories[ticker] = (days, prices)
        stamps.append(stamp)
    dates = np.unique(np.concatenate([row[0] for row in histories.values()]))
    first = ((record.get("provenance") or {}).get("data") or {}).get("first_session")
    try:
        first = np.datetime64(date.fromisoformat(first), "D")
    except (ValueError, TypeError) as exc:
        raise ValueError("Recorded history origin required for EMA state") from exc
    if dates[0] > first or first not in histories["SPY"][0]:
        raise ValueError("Published history no longer covers the recorded EMA origin")
    unknown_years = sorted(
        set((dates.astype("datetime64[Y]").astype(int) + 1970).tolist()) - years
    )
    dates = np.append(_session_dates(dates, first, prior), np.datetime64(session, "D"))
    prices = np.full((len(dates), len(names)), np.nan)
    grades = np.full(prices.shape, -1, dtype=np.int8)
    eligible = np.zeros(prices.shape, dtype=bool)
    for stock, ticker in enumerate(names):
        days, values = histories[ticker]
        keep = days >= first
        prices[np.searchsorted(dates, days[keep]), stock] = values[keep]
        if ticker in recorded:
            grades[-2, stock] = GRADE_CODES[recorded[ticker]["grade"]]
            eligible[-2, stock] = ticker not in ("SPY", "QQQ")
    _check_unchanged(sources)
    for array in (dates, prices, grades, eligible):
        array.setflags(write=False)
    return ShadowContext(
        panel=SimpleNamespace(dates=dates, tickers=names, adj_close=prices),
        grades=grades,
        eligible=eligible,
        published_at={
            "history": max(stamps),
            "grades": published,
            "membership": published,
        },
        split_adjusted_prior_closes=closes,
        raw_prior_closes={},
        provenance={
            "schema": "sequential-shadow-context/1",
            "session": session.isoformat(),
            "prior_session": prior.isoformat(),
            "captured_at": captured.isoformat(),
            "record_source_revision": revision,
            "calendar_basis": "reviewed_exchange_sessions_with_missing_rows_retained",
            "unreviewed_history_years": unknown_years,
            "membership_basis": "recorded_current_book",
            "historical_membership_reconstruction": False,
            "historical_grades_reconstruction": False,
            "daily_price_basis": DAILY_BASIS,
            "prior_close_candidate_basis": PRIOR_CLOSE_BASIS,
            "raw_prior_close_status": "unavailable_without_current_basis_evidence",
            "history_origin": str(first),
            "sources": sources,
        },
    )
