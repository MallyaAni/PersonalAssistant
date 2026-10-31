"""Mechanical event discovery: earnings shocks, fear and election dates.

The owner's requirement is that the desk finds these events from its own
ingested data, without being told the event in hindsight. This module is the
pure detection layer behind `backend/cli/market_event_watch.py`:

    earnings change   quarter over quarter and year over year, from filings
    shock event       a large earnings drop plus a large negative reaction
    election day      the first Tuesday after the first Monday in November
    midterm           an even year not divisible by four

Every threshold is fixed by `docs/research/event-shock-preregistration-2026-10-31.md`
and none is tuned to a named event. The module reads no model, no prompt and no
live book; it turns stored filings and prices into a table of facts. The CLI's
study measures whether the facts predict anything; the scan reports them.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from backend.market import fundamentals_asof as fa
from backend.market import language

# Pre-registered thresholds. The study and the live scan use the same ones.
QOQ_DROP = -0.20
YOY_DROP = -0.10
QOQ_RISE = 0.20
YOY_RISE = 0.10
REACTION_DROP = -0.05
REACTION_RISE = 0.05
VOLUME_RATIO = 2.0
HORIZONS = (20, 60)
HYPERSCALERS = ("MSFT", "AMZN", "GOOGL", "META", "ORCL")
AI_SECTORS = ("Information Technology", "Communication Services")
FOREIGN = frozenset({"ASML", "FDXF", "NBIS", "SIMO", "TSM"})
BENCHMARK = "SPY"


# The US federal election day: the first Tuesday after the first Monday in November.
def election_day(year: int) -> date:
    """Return the federal election day for a year."""
    first = date(year, 11, 1)
    first_monday = first + timedelta(days=(7 - first.weekday()) % 7)
    return first_monday + timedelta(days=1)


# A midterm is an even year that is not a presidential year.
def is_midterm(year: int) -> bool:
    """Return whether the year holds a midterm election."""
    return year % 2 == 0 and year % 4 != 0


# The first election on or after a date, with whether it is a midterm.
def next_election(asof: date) -> tuple[date, bool]:
    """Return (election day, is_midterm) for the first election on or after asof."""
    year = asof.year
    while True:
        day = election_day(year)
        if day >= asof:
            return day, is_midterm(year)
        year += 1


# Quarter spans only, earliest filing per period end, finite values.
def quarter_series(versions, source: str = "net_income") -> dict[date, tuple[float, date]]:
    """Return {period_end: (value, first_available)} for one earnings source."""
    by_end: dict[date, tuple[float, date]] = {}
    for version in versions:
        if version.name != source:
            continue
        if fa.span_kind(version.start, version.end) != "quarter":
            continue
        if not np.isfinite(version.value):
            continue
        previous = by_end.get(version.end)
        if previous is None or version.available < previous[1]:
            by_end[version.end] = (float(version.value), version.available)
    return by_end


# A sign-safe relative change: the absolute denominator keeps a larger loss negative.
def relative_change(value: float | None, comparison: float | None) -> float | None:
    """Return (value - comparison) / |comparison|, or None when undefined."""
    if value is None or comparison is None:
        return None
    if not (np.isfinite(value) and np.isfinite(comparison)) or comparison == 0:
        return None
    return (value - comparison) / abs(comparison)


# Quarter-over-quarter and year-over-year change for every quarter in a series.
def earnings_changes(series: dict[date, tuple[float, date]]) -> dict[date, dict]:
    """Return {period_end: {value, available, qoq, yoy}} for a quarter series."""
    ends = sorted(series)
    out: dict[date, dict] = {}
    for index, end in enumerate(ends):
        prior = None
        year_ago = None
        for earlier in reversed(ends[:index]):
            days = (end - earlier).days
            if prior is None and 60 <= days <= 120:
                prior = earlier
            if year_ago is None and 350 <= days <= 380:
                year_ago = earlier
            if prior is not None and year_ago is not None:
                break
        value, available = series[end]
        out[end] = {
            "value": value,
            "available": available,
            "qoq": relative_change(value, series[prior][0]) if prior is not None else None,
            "yoy": relative_change(value, series[year_ago][0]) if year_ago is not None else None,
        }
    return out


# The pre-registered negative earnings shock: either seasonal measure drops enough.
def negative_shock(qoq: float | None, yoy: float | None) -> bool:
    """Return whether a quarter meets the earnings-drop threshold."""
    return (qoq is not None and qoq <= QOQ_DROP) or (yoy is not None and yoy <= YOY_DROP)


# The symmetric positive shock, reported as a diagnostic and never gated.
def positive_shock(qoq: float | None, yoy: float | None) -> bool:
    """Return whether a quarter meets the earnings-rise threshold."""
    return (qoq is not None and qoq >= QOQ_RISE) or (yoy is not None and yoy >= YOY_RISE)


# The first session at or after the filing's availability date.
def reaction_index(days: np.ndarray, available: date) -> int:
    """Return the session index of the first reaction to a filing."""
    return int(np.searchsorted(days, np.datetime64(available, "D"), side="left"))


# The volume ratio against the prior median, the live scan's confidence field.
def volume_ratio(volume: np.ndarray, index: int, lookback: int = 20) -> float | None:
    """Return the session's volume divided by the prior lookback median."""
    if index <= 0 or index >= len(volume):
        return None
    base = volume[max(0, index - lookback):index]
    base = base[np.isfinite(base) & (base > 0)]
    value = volume[index]
    if not len(base) or not np.isfinite(value):
        return None
    median = float(np.median(base))
    return float(value) / median if median > 0 else None


# The five tone fields of a record as a plain mapping.
def tone_fields(record) -> dict[str, float]:
    """Return the release's five tone scores."""
    return {name: float(getattr(record, name)) for name in language.SCORE_NAMES}


# The sum of the five tone changes from the previous release.
def tone_change(latest, previous) -> float | None:
    """Return the summed tone change, or None without a previous release."""
    if previous is None:
        return None
    return float(
        sum(getattr(latest, name) - getattr(previous, name) for name in language.SCORE_NAMES)
    )


# The year-ago record for a release, matched by reported quarter end.
def year_ago_record(rows, latest):
    """Return the release whose quarter end is 350-380 days before latest's."""
    if latest.quarter_end is None:
        return None
    for row in rows:
        if row is latest or row.quarter_end is None:
            continue
        days = (latest.quarter_end - row.quarter_end).days
        if 350 <= days <= 380:
            return row
    return None


# One book name's latest filing as the scan reports it, with no hindsight.
def scan_name(
    ticker: str,
    theme: str,
    rows,
    days: np.ndarray,
    adj_close: np.ndarray,
    volume: np.ndarray,
    grade: str,
    action: dict | None,
) -> dict | None:
    """Return the scan row for a name's latest release, or None without one."""
    if not rows:
        return None
    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else None
    year_ago = year_ago_record(rows, latest)
    index = reaction_index(days, latest.reaction_date)
    if index <= 0 or index >= len(days):
        return None
    before = adj_close[index - 1]
    after = adj_close[index]
    reaction = None
    if np.isfinite(before) and np.isfinite(after) and before > 0:
        reaction = float(after / before - 1.0)
    eps_qoq = relative_change(latest.eps_usd, previous.eps_usd) if previous is not None else None
    eps_yoy = relative_change(latest.eps_usd, year_ago.eps_usd) if year_ago is not None else None
    revenue_qoq = (
        relative_change(latest.revenue_usd_m, previous.revenue_usd_m)
        if previous is not None
        else None
    )
    revenue_yoy = (
        relative_change(latest.revenue_usd_m, year_ago.revenue_usd_m)
        if year_ago is not None
        else None
    )
    earnings_shock = negative_shock(eps_qoq, eps_yoy)
    confirmed = reaction is not None and reaction <= REACTION_DROP
    ratio = volume_ratio(volume, index)
    reasons = []
    if eps_qoq is not None and eps_qoq <= QOQ_DROP:
        reasons.append(f"EPS {eps_qoq:+.1%} quarter over quarter")
    if eps_yoy is not None and eps_yoy <= YOY_DROP:
        reasons.append(f"EPS {eps_yoy:+.1%} year over year")
    if confirmed:
        reasons.append(f"reaction {reaction:+.1%}")
    return {
        "ticker": ticker,
        "theme": theme,
        "grade": grade,
        "action": None if action is None else action.get("action"),
        "target_weight": None if action is None else action.get("target_weight"),
        "current_weight": None if action is None else action.get("current_weight"),
        "quarter_end": latest.quarter_end.isoformat() if latest.quarter_end else None,
        "reaction_date": latest.reaction_date.isoformat(),
        "age_sessions": int(len(days) - 1 - index),
        "eps": latest.eps_usd,
        "eps_qoq": eps_qoq,
        "eps_yoy": eps_yoy,
        "revenue_usd_m": latest.revenue_usd_m,
        "revenue_qoq": revenue_qoq,
        "revenue_yoy": revenue_yoy,
        "tone": tone_fields(latest),
        "tone_change": tone_change(latest, previous),
        "reaction_return": reaction,
        "volume_ratio": ratio,
        "shock": bool(earnings_shock and confirmed),
        "shock_reasons": reasons,
    }


# Every pre-registered shock event for one earnings source on the PIT universe.
def study_events(
    days: np.ndarray,
    tickers: list[str],
    member: np.ndarray,
    adj_close: np.ndarray,
    versions_by_ticker: list,
    source: str = "net_income",
    direction: str = "negative",
) -> list[dict]:
    """Return the shock events with their reaction sessions and returns."""
    events: list[dict] = []
    for column, ticker in enumerate(tickers):
        if ticker in FOREIGN or ticker == BENCHMARK:
            continue
        series = quarter_series(versions_by_ticker[column], source)
        if not series:
            continue
        for end, change in earnings_changes(series).items():
            qualifies = (
                negative_shock(change["qoq"], change["yoy"])
                if direction == "negative"
                else positive_shock(change["qoq"], change["yoy"])
            )
            if not qualifies:
                continue
            index = reaction_index(days, change["available"])
            if index <= 0 or index >= len(days):
                continue
            if not member[index, column]:
                continue
            before = adj_close[index - 1, column]
            after = adj_close[index, column]
            if not (np.isfinite(before) and np.isfinite(after)) or before <= 0:
                continue
            reaction = float(after / before - 1.0)
            confirmed = (
                reaction <= REACTION_DROP
                if direction == "negative"
                else reaction >= REACTION_RISE
            )
            if not confirmed:
                continue
            events.append(
                {
                    "ticker": ticker,
                    "column": column,
                    "period_end": end.isoformat(),
                    "available": change["available"].isoformat(),
                    "reaction_index": index,
                    "reaction_date": str(days[index]),
                    "reaction_return": reaction,
                    "qoq": change["qoq"],
                    "yoy": change["yoy"],
                    "value": change["value"],
                }
            )
    return events


# The name's forward return minus the benchmark's over the same window.
def forward_excess(
    adj_close: np.ndarray,
    index: int,
    column: int,
    horizon: int,
    benchmark: int,
) -> float | None:
    """Return the h-session excess return from index's close, or None."""
    end = index + horizon
    if end >= len(adj_close):
        return None
    start_price = adj_close[index, column]
    end_price = adj_close[end, column]
    start_benchmark = adj_close[index, benchmark]
    end_benchmark = adj_close[end, benchmark]
    values = (start_price, end_price, start_benchmark, end_benchmark)
    if not all(np.isfinite(v) and v > 0 for v in values):
        return None
    return float((end_price / start_price - 1.0) - (end_benchmark / start_benchmark - 1.0))


# The equal-weight peer mean after a hyperscaler event at a session.
def peer_mean(
    adj_close: np.ndarray,
    member: np.ndarray,
    sectors: list[str],
    index: int,
    horizon: int,
    benchmark: int,
    excluded_columns: set[int],
) -> tuple[float | None, int]:
    """Return (mean peer excess, peer count) for one event session."""
    end = index + horizon
    if end >= len(adj_close):
        return None, 0
    columns = np.asarray(
        [
            column
            for column, sector in enumerate(sectors)
            if sector in AI_SECTORS
            and column not in excluded_columns
            and member[index, column]
        ],
        dtype=int,
    )
    if not len(columns):
        return None, 0
    starts = adj_close[index, columns]
    ends = adj_close[end, columns]
    benchmark_start = adj_close[index, benchmark]
    benchmark_end = adj_close[end, benchmark]
    if not (np.isfinite(benchmark_start) and np.isfinite(benchmark_end)) or benchmark_start <= 0:
        return None, 0
    valid = np.isfinite(starts) & np.isfinite(ends) & (starts > 0)
    if not valid.any():
        return None, 0
    excess = (ends[valid] / starts[valid] - 1.0) - (benchmark_end / benchmark_start - 1.0)
    return float(excess.mean()), int(valid.sum())
