"""Find earnings shocks, fear and election dates from stored data, then measure them.

    python -m backend.cli.market_event_watch --scan --asof 2026-10-30
    python -m backend.cli.market_event_watch --study \
        --cache ~/dsv41/pit2/cache.npz \
        --output docs/research/scorecards/event-shock/result.json

Implements `docs/research/event-shock-preregistration-2026-10-31.md`.

The scan is the part that answers "find it without being told": it walks every
book name's latest release, computes the EPS and revenue change, the tone
change, the reaction return and the volume ratio, and lists every name that
meets the pre-registered shock rule. It also reports the last five sessions'
large adverse price moves, any hyperscaler shock and the book's return since
it, the next FOMC decision and the next federal election. It reads stored
filings, tone records and bars; no model call and no prompt.

The study measures the rule on the honest PIT universe: own-name continuation
after a shock (A1) and hyperscaler contagion (A2), with the pre-registered
gate, placebo, cluster bootstrap and look-ahead controls. The midterm section
(A3) is descriptive. Research only: the scan writes under
`data/market/research/event-watch/`, and the study writes the path given.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk
from backend.market import calendar, event_watch, fundamentals_asof as fa, language
from backend.market.store import MarketStore

CHOOSING = (2016, 2023)
REPORTED = (2024, 2026)
HORIZONS = event_watch.HORIZONS
PLACEBO_DRAWS = 200
BOOTSTRAP_DRAWS = 2000
RNG_SEED = 20261031
MIN_EVENTS = 200
MIN_PEERS = 20
SHOCK_EXCLUSION = 10
PLACEBO_EXCLUSION = 20
PRICE_WINDOW = 5
PRICE_DROP = -0.05
PRICE_VOLUME = 2.0
RECENT_SESSIONS = 10


# A Python float, or None when the value is missing or not finite.
def number(value) -> float | None:
    """Return a JSON-safe float or None."""
    if value is None:
        return None
    value = float(value)
    return value if np.isfinite(value) else None


# The mean and a 95% month-cluster bootstrap interval.
def cluster_bootstrap(
    values: list[float], months: list[str], draws: int = BOOTSTRAP_DRAWS, seed: int = RNG_SEED
) -> dict:
    """Return the mean, interval and counts for values clustered by month."""
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"events": 0, "months": 0, "mean": None, "ci_low": None, "ci_high": None}
    groups: dict[str, list[float]] = defaultdict(list)
    for value, month in zip(values, months):
        groups[month].append(float(value))
    arrays = [np.asarray(groups[key], dtype=float) for key in sorted(groups)]
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    for index in range(draws):
        pick = rng.integers(0, len(arrays), len(arrays))
        means[index] = np.concatenate([arrays[column] for column in pick]).mean()
    return {
        "events": len(values),
        "months": len(arrays),
        "mean": float(values.mean()),
        "ci_low": float(np.percentile(means, 2.5)),
        "ci_high": float(np.percentile(means, 97.5)),
    }


# The summary of a set of event rows: mean, interval, yearly means and counts.
def describe(rows: list[dict]) -> dict:
    """Return the pooled and yearly statistics for event rows."""
    values = [row["value"] for row in rows]
    months = [row["month"] for row in rows]
    summary = cluster_bootstrap(values, months)
    yearly: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        yearly[row["year"]].append(row["value"])
    summary["yearly"] = {
        str(year): {"events": len(values), "mean": float(np.mean(values))}
        for year, values in sorted(yearly.items())
    }
    summary["negative_years"] = sum(
        1 for values in yearly.values() if float(np.mean(values)) < 0
    )
    return summary


# Forward excess rows for a set of events, one list per horizon.
def collect(
    events: list[dict], adj_close: np.ndarray, benchmark: int
) -> dict[int, list[dict]]:
    """Return the forward excess rows for every event and horizon."""
    rows: dict[int, list[dict]] = {horizon: [] for horizon in HORIZONS}
    for event in events:
        year = int(event["reaction_date"][:4])
        month = event["reaction_date"][:7]
        for horizon in HORIZONS:
            value = event_watch.forward_excess(
                adj_close, event["reaction_index"], event["column"], horizon, benchmark
            )
            if value is not None:
                rows[horizon].append(
                    {"value": value, "month": month, "year": year, "event": event}
                )
    return rows


# Candidate sessions for the own-name placebo: same name, same year, no real shock near.
def own_name_candidates(
    events: list[dict], days: np.ndarray, member: np.ndarray
) -> list[np.ndarray]:
    """Return the allowed placebo sessions for each event."""
    sessions = len(days)
    names = member.shape[1]
    near = np.zeros((sessions, names), dtype=bool)
    for event in events:
        start = max(0, event["reaction_index"] - PLACEBO_EXCLUSION)
        end = min(sessions, event["reaction_index"] + PLACEBO_EXCLUSION + 1)
        near[start:end, event["column"]] = True
    bounds: dict[int, tuple[int, int]] = {}
    for event in events:
        year = int(event["reaction_date"][:4])
        if year not in bounds:
            start = int(np.searchsorted(days, np.datetime64(f"{year}-01-01", "D")))
            end = int(np.searchsorted(days, np.datetime64(f"{year + 1}-01-01", "D")))
            bounds[year] = (start, end)
    out = []
    for event in events:
        start, end = bounds[int(event["reaction_date"][:4])]
        column = event["column"]
        allowed = member[start:end, column] & ~near[start:end, column]
        out.append(np.flatnonzero(allowed) + start)
    return out


# The 200 own-name placebo pooled means at both horizons.
def placebo_own_name(
    events: list[dict], adj_close: np.ndarray, member: np.ndarray, days: np.ndarray, benchmark: int
) -> dict[int, dict]:
    """Return the placebo mean distribution for the own-name arm."""
    candidates = own_name_candidates(events, days, member)
    rng = np.random.default_rng(RNG_SEED + 1)
    draws: dict[int, list[float]] = {horizon: [] for horizon in HORIZONS}
    for _ in range(PLACEBO_DRAWS):
        values: dict[int, list[float]] = {horizon: [] for horizon in HORIZONS}
        for event, allowed in zip(events, candidates):
            if not len(allowed):
                continue
            index = int(allowed[rng.integers(0, len(allowed))])
            for horizon in HORIZONS:
                value = event_watch.forward_excess(
                    adj_close, index, event["column"], horizon, benchmark
                )
                if value is not None:
                    values[horizon].append(value)
        for horizon in HORIZONS:
            draws[horizon].append(
                float(np.mean(values[horizon])) if values[horizon] else float("nan")
            )
    out = {}
    for horizon in HORIZONS:
        finite = np.asarray(draws[horizon], dtype=float)
        finite = finite[np.isfinite(finite)]
        out[horizon] = {
            "draws": len(finite),
            "median": number(np.median(finite)) if len(finite) else None,
            "p05": number(np.percentile(finite, 5)) if len(finite) else None,
            "p95": number(np.percentile(finite, 95)) if len(finite) else None,
        }
    return out


# The gate for the own-name arm, at both horizons.
def own_name_gate(
    rows: dict[int, list[dict]], placebo: dict[int, dict], minimum: int = MIN_EVENTS
) -> dict:
    """Return the A1 gate result, or the stop when the sample is underpowered."""
    stats = {horizon: describe(rows[horizon]) for horizon in HORIZONS}
    if stats[HORIZONS[0]]["events"] < minimum:
        return {
            "stats": stats,
            "stopped": f"fewer than {minimum} events with a full 20-session window",
            "G1": None,
            "G2": None,
            "G3": None,
            "pass": False,
        }
    g1 = all(
        stats[horizon]["mean"] is not None
        and stats[horizon]["mean"] < 0
        and stats[horizon]["ci_high"] is not None
        and stats[horizon]["ci_high"] < 0
        for horizon in HORIZONS
    )
    g2 = all(
        stats[horizon]["mean"] is not None
        and placebo[horizon]["p05"] is not None
        and stats[horizon]["mean"] < placebo[horizon]["p05"]
        for horizon in HORIZONS
    )
    g3 = all(
        sum(
            1
            for year in range(CHOOSING[0], CHOOSING[1] + 1)
            if stats[horizon]["yearly"].get(str(year), {}).get("mean") is not None
            and stats[horizon]["yearly"][str(year)]["mean"] < 0
        )
        >= 5
        for horizon in HORIZONS
    )
    return {"stats": stats, "stopped": None, "G1": g1, "G2": g2, "G3": g3, "pass": g1 and g2 and g3}


# The shock matrix used to exclude peers with their own event near a date.
def shock_matrix(events: list[dict], days: np.ndarray, names: int) -> np.ndarray:
    """Return a (sessions, names) matrix marking every shock reaction session."""
    out = np.zeros((len(days), names), dtype=bool)
    for event in events:
        out[event["reaction_index"], event["column"]] = True
    return out


# The hyperscaler events and their peer means at both horizons.
def contagion_rows(
    events: list[dict],
    adj_close: np.ndarray,
    member: np.ndarray,
    sectors: list[str],
    days: np.ndarray,
    benchmark: int,
    tickers: list[str],
) -> tuple[dict[int, list[dict]], dict]:
    """Return the peer-mean rows and the peer-count summary for A2."""
    hyperscalers = {tickers.index(name) for name in event_watch.HYPERSCALERS if name in tickers}
    shock = shock_matrix(events, days, member.shape[1])
    rows: dict[int, list[dict]] = {horizon: [] for horizon in HORIZONS}
    peers: list[int] = []
    by_name: dict[str, list[float]] = defaultdict(list)
    triggered: set[tuple[str, str]] = set()
    for event in events:
        if event["ticker"] not in event_watch.HYPERSCALERS:
            continue
        index = event["reaction_index"]
        window = shock[
            max(0, index - SHOCK_EXCLUSION):min(len(days), index + SHOCK_EXCLUSION + 1)
        ].any(axis=0)
        excluded = hyperscalers | set(np.flatnonzero(window).tolist())
        for horizon in HORIZONS:
            value, count = event_watch.peer_mean(
                adj_close, member, sectors, index, horizon, benchmark, excluded
            )
            if value is None or count < MIN_PEERS:
                continue
            rows[horizon].append(
                {
                    "value": value,
                    "peers": count,
                    "month": event["reaction_date"][:7],
                    "year": int(event["reaction_date"][:4]),
                    "event": event,
                }
            )
            peers.append(count)
            by_name[event["ticker"]].append(value)
            triggered.add((event["ticker"], event["reaction_date"]))
    summary = {
        "events": len(triggered),
        "observations": len(peers),
        "peers_min": int(min(peers)) if peers else None,
        "peers_median": float(np.median(peers)) if peers else None,
        "peers_max": int(max(peers)) if peers else None,
        "by_hyperscaler": {
            name: {"observations": len(values), "mean": float(np.mean(values))}
            for name, values in sorted(by_name.items())
        },
    }
    return rows, summary


# The 200 hyperscaler placebo pooled means at both horizons.
def placebo_contagion(
    events: list[dict],
    adj_close: np.ndarray,
    member: np.ndarray,
    sectors: list[str],
    days: np.ndarray,
    benchmark: int,
    tickers: list[str],
) -> dict[int, dict]:
    """Return the placebo mean distribution for the contagion arm."""
    hyperscalers = {tickers.index(name) for name in event_watch.HYPERSCALERS if name in tickers}
    shock = shock_matrix(events, days, member.shape[1])
    sessions = len(days)
    near = np.zeros_like(shock)
    for event in events:
        if event["ticker"] not in event_watch.HYPERSCALERS:
            continue
        start = max(0, event["reaction_index"] - PLACEBO_EXCLUSION)
        end = min(sessions, event["reaction_index"] + PLACEBO_EXCLUSION + 1)
        near[start:end, event["column"]] = True
    bounds: dict[int, tuple[int, int]] = {}
    for event in events:
        if event["ticker"] not in event_watch.HYPERSCALERS:
            continue
        year = int(event["reaction_date"][:4])
        if year not in bounds:
            start = int(np.searchsorted(days, np.datetime64(f"{year}-01-01", "D")))
            end = int(np.searchsorted(days, np.datetime64(f"{year + 1}-01-01", "D")))
            bounds[year] = (start, end)
    candidates = []
    for event in events:
        if event["ticker"] not in event_watch.HYPERSCALERS:
            continue
        start, end = bounds[int(event["reaction_date"][:4])]
        column = event["column"]
        allowed = member[start:end, column] & ~near[start:end, column]
        candidates.append((event, np.flatnonzero(allowed) + start))
    rng = np.random.default_rng(RNG_SEED + 2)
    draws: dict[int, list[float]] = {horizon: [] for horizon in HORIZONS}
    for _ in range(PLACEBO_DRAWS):
        values: dict[int, list[float]] = {horizon: [] for horizon in HORIZONS}
        for event, allowed in candidates:
            if not len(allowed):
                continue
            index = int(allowed[rng.integers(0, len(allowed))])
            window = shock[
                max(0, index - SHOCK_EXCLUSION):min(sessions, index + SHOCK_EXCLUSION + 1)
            ].any(axis=0)
            excluded = hyperscalers | set(np.flatnonzero(window).tolist())
            for horizon in HORIZONS:
                value, count = event_watch.peer_mean(
                    adj_close, member, sectors, index, horizon, benchmark, excluded
                )
                if value is not None and count >= MIN_PEERS:
                    values[horizon].append(value)
        for horizon in HORIZONS:
            draws[horizon].append(
                float(np.mean(values[horizon])) if values[horizon] else float("nan")
            )
    out = {}
    for horizon in HORIZONS:
        finite = np.asarray(draws[horizon], dtype=float)
        finite = finite[np.isfinite(finite)]
        out[horizon] = {
            "draws": len(finite),
            "median": number(np.median(finite)) if len(finite) else None,
            "p05": number(np.percentile(finite, 5)) if len(finite) else None,
            "p95": number(np.percentile(finite, 95)) if len(finite) else None,
        }
    return out


# The gate for the contagion arm, at both horizons.
def contagion_gate(
    rows: dict[int, list[dict]], placebo: dict[int, dict]
) -> dict:
    """Return the A2 gate result."""
    stats = {horizon: describe(rows[horizon]) for horizon in HORIZONS}
    g1 = all(
        stats[horizon]["mean"] is not None
        and stats[horizon]["mean"] < 0
        and stats[horizon]["ci_high"] is not None
        and stats[horizon]["ci_high"] < 0
        for horizon in HORIZONS
    )
    g2 = all(
        stats[horizon]["mean"] is not None
        and placebo[horizon]["p05"] is not None
        and stats[horizon]["mean"] < placebo[horizon]["p05"]
        for horizon in HORIZONS
    )
    return {"stats": stats, "G1": g1, "G2": g2, "pass": g1 and g2}


# The equal-weight return of PIT members over a session window.
def member_return(
    adj_close: np.ndarray, member: np.ndarray, start: int, end: int
) -> tuple[float | None, int]:
    """Return (mean member return, count) over [start, end]."""
    if start < 0 or end >= len(adj_close) or end <= start:
        return None, 0
    columns = np.flatnonzero(member[start])
    if not len(columns):
        return None, 0
    starts = adj_close[start, columns]
    ends = adj_close[end, columns]
    valid = np.isfinite(starts) & np.isfinite(ends) & (starts > 0)
    if not valid.any():
        return None, 0
    return float(np.mean(ends[valid] / starts[valid] - 1.0)), int(valid.sum())


# The market and PIT-universe path around each midterm election.
def midterm_rows(
    days: np.ndarray, member: np.ndarray, adj_close: np.ndarray, benchmark: int
) -> list[dict]:
    """Return the descriptive midterm windows in the cache."""
    out = []
    for year in sorted({int(str(day)[:4]) for day in days}):
        if not event_watch.is_midterm(year):
            continue
        election = event_watch.election_day(year)
        index = int(np.searchsorted(days, np.datetime64(election, "D"), side="left"))
        if index >= len(days):
            continue
        windows = {
            "before_20": (index - 20, index),
            "after_20": (index, index + 20),
            "after_60": (index, index + 60),
            "path_60": (index - 60, index + 60),
        }
        row = {"election": election.isoformat(), "session": str(days[index])}
        for label, (start, end) in windows.items():
            if start < 0 or end >= len(days):
                row[label] = {"complete": False}
                continue
            spy = adj_close[end, benchmark] / adj_close[start, benchmark] - 1.0
            mean, count = member_return(adj_close, member, start, end)
            row[label] = {
                "complete": True,
                "spy": float(spy),
                "members": count,
                "member_mean": mean,
            }
        out.append(row)
    return out


# Sessions from the as-of date to a target date on the reviewed calendar.
def sessions_until(asof: date, target: date | None) -> int | None:
    """Return the number of sessions after asof through target, or None."""
    if target is None:
        return None
    years, busday = calendar.reviewed_sessions()
    if target.year not in years or asof.year not in years:
        return None
    return int(
        np.busday_count(
            np.datetime64(asof + timedelta(days=1), "D"),
            np.datetime64(target + timedelta(days=1), "D"),
            busdaycal=busday,
        )
    )


# The next FOMC decision on or after a date.
def next_fomc(asof: date) -> date | None:
    """Return the first FOMC decision date on or after asof."""
    for decision in calendar.fomc_decisions():
        if decision >= asof:
            return decision
    return None


# The calendar section: the next Fed decision and the next federal election.
def calendar_section(asof: date) -> dict:
    """Return the upcoming event calendar with session counts."""
    fomc = next_fomc(asof)
    election, midterm = event_watch.next_election(asof)
    return {
        "next_fomc": None if fomc is None else fomc.isoformat(),
        "sessions_to_fomc": sessions_until(asof, fomc),
        "next_election": election.isoformat(),
        "next_election_midterm": midterm,
        "sessions_to_election": sessions_until(asof, election),
    }


# Large adverse price moves in the last few sessions, independent of earnings.
def price_shocks(
    panel, days: np.ndarray, window: int = PRICE_WINDOW
) -> list[dict]:
    """Return the recent one-session drops with heavy volume."""
    out = []
    last = len(days) - 1
    for column, ticker in enumerate(panel.tickers):
        for index in range(max(1, last - window + 1), last + 1):
            before = panel.adj_close[index - 1, column]
            after = panel.adj_close[index, column]
            if not (np.isfinite(before) and np.isfinite(after)) or before <= 0:
                continue
            move = float(after / before - 1.0)
            if move > PRICE_DROP:
                continue
            ratio = event_watch.volume_ratio(panel.volume[:, column], index)
            if ratio is None or ratio < PRICE_VOLUME:
                continue
            out.append(
                {
                    "ticker": ticker,
                    "date": str(days[index]),
                    "return": move,
                    "volume_ratio": ratio,
                }
            )
    return sorted(out, key=lambda row: (row["date"], row["return"]))


# The book's return since a hyperscaler shock, for the fear/contagion context.
def book_since(panel, days: np.ndarray, trigger: dict) -> dict:
    """Return the book's mean and worst returns from a shock close to the latest close."""
    index = event_watch.reaction_index(days, date.fromisoformat(trigger["reaction_date"]))
    last = len(days) - 1
    rows = []
    for column, ticker in enumerate(panel.tickers):
        start = panel.adj_close[index, column]
        end = panel.adj_close[last, column]
        if not (np.isfinite(start) and np.isfinite(end)) or start <= 0:
            continue
        rows.append({"ticker": ticker, "return_since": float(end / start - 1.0)})
    if not rows:
        return {"trigger": trigger, "members": 0, "mean": None, "worst": []}
    rows.sort(key=lambda row: row["return_since"])
    return {
        "trigger": trigger,
        "members": len(rows),
        "mean": float(np.mean([row["return_since"] for row in rows])),
        "worst": rows[:5],
    }


# The live book scan: every name's latest release and the mechanical shock flags.
def scan(store: MarketStore, asof: date) -> dict:
    """Return the event-watch scan for the book on an as-of date."""
    panel, _ = desk.book_panel(store, asof)
    records = language.stored_records(store, panel.tickers, asof)
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    desk_path = store.root / "desk" / f"asof={asof.isoformat()}" / "desk.json"
    decisions = json.loads(desk_path.read_text(encoding="utf-8")) if desk_path.exists() else {}
    grades = decisions.get("grades", {})
    actions = {row["ticker"]: row for row in decisions.get("actions", [])}
    rows = []
    for column, ticker in enumerate(panel.tickers):
        grade = grades.get(ticker, "")
        if isinstance(grade, dict):
            grade = grade.get("grade", "")
        row = event_watch.scan_name(
            ticker,
            panel.themes.get(ticker, ""),
            records.get(ticker, ()),
            days,
            panel.adj_close[:, column],
            panel.volume[:, column],
            grade,
            actions.get(ticker),
        )
        if row is not None:
            if isinstance(grades.get(ticker), dict):
                row["grade_headline"] = grades[ticker].get("headline")
            rows.append(row)
    shocks = [row for row in rows if row["shock"]]
    price = price_shocks(panel, days)
    triggers = [
        row for row in shocks if row["ticker"] in event_watch.HYPERSCALERS
        and event_watch.reaction_index(days, date.fromisoformat(row["reaction_date"]))
        >= len(days) - PRICE_WINDOW
    ]
    return {
        "version": "event-watch/1",
        "asof": asof.isoformat(),
        "rule": {
            "qoq_drop": event_watch.QOQ_DROP,
            "yoy_drop": event_watch.YOY_DROP,
            "reaction_drop": event_watch.REACTION_DROP,
            "volume_ratio": event_watch.VOLUME_RATIO,
            "hyperscalers": list(event_watch.HYPERSCALERS),
            "price_window": PRICE_WINDOW,
        },
        "calendar": calendar_section(asof),
        "shocks": shocks,
        "price_shocks": price,
        "contagion": [book_since(panel, days, row) for row in triggers],
        "names": rows,
    }


# The whole pre-registered study on the honest PIT universe.
def study(store: MarketStore, cache: Path) -> dict:
    """Return the A1, A2 and A3 results with the gate, placebo and controls."""
    z = np.load(cache, allow_pickle=True)
    days = np.asarray([str(day) for day in z["dates"]], dtype="datetime64[D]")
    tickers = [str(ticker) for ticker in z["tickers"]]
    member = np.asarray(z["member"], dtype=bool)
    adj_close = np.asarray(z["adj_close"], dtype=float)
    grades = np.asarray(z["grades"], dtype=float)
    sectors = [str(sector) for sector in z["sector"]]
    benchmark = tickers.index(str(z["benchmark"]))
    versions_by_ticker = []
    frames_missing = []
    for ticker in tickers:
        found = store.read_frame(fa.KIND, ticker, None)
        if found is None:
            frames_missing.append(ticker)
            versions_by_ticker.append([])
        else:
            versions_by_ticker.append(fa.versions_from_frame(found[0]))

    events = event_watch.study_events(
        days, tickers, member, adj_close, versions_by_ticker, "net_income"
    )
    choosing = [
        event for event in events if CHOOSING[0] <= int(event["reaction_date"][:4]) <= CHOOSING[1]
    ]
    reported = [
        event for event in events if REPORTED[0] <= int(event["reaction_date"][:4]) <= REPORTED[1]
    ]
    rows = collect(choosing, adj_close, benchmark)
    placebo = placebo_own_name(choosing, adj_close, member, days, benchmark)
    own = own_name_gate(rows, placebo)
    reported_rows = collect(reported, adj_close, benchmark)

    contagion_events = [event for event in choosing if event["ticker"] in event_watch.HYPERSCALERS]
    contagion, peers = contagion_rows(
        contagion_events, adj_close, member, sectors, days, benchmark, tickers
    )
    contagion_placebo = placebo_contagion(
        contagion_events, adj_close, member, sectors, days, benchmark, tickers
    )
    spread = contagion_gate(contagion, contagion_placebo)

    eps_events = event_watch.study_events(
        days, tickers, member, adj_close, versions_by_ticker, "eps"
    )
    eps_choosing = [
        event for event in eps_events if CHOOSING[0] <= int(event["reaction_date"][:4]) <= CHOOSING[1]
    ]
    revenue_events = event_watch.study_events(
        days, tickers, member, adj_close, versions_by_ticker, "revenue"
    )
    revenue_choosing = [
        event
        for event in revenue_events
        if CHOOSING[0] <= int(event["reaction_date"][:4]) <= CHOOSING[1]
    ]
    positive_events = event_watch.study_events(
        days, tickers, member, adj_close, versions_by_ticker, "net_income", "positive"
    )
    positive_choosing = [
        event
        for event in positive_events
        if CHOOSING[0] <= int(event["reaction_date"][:4]) <= CHOOSING[1]
    ]

    def diagnostic(event_set):
        diag_rows = collect(event_set, adj_close, benchmark)
        return {str(horizon): describe(diag_rows[horizon]) for horizon in HORIZONS}

    grade_rows = {horizon: [] for horizon in HORIZONS}
    for row in rows[20]:
        event = row["event"]
        if grades[event["reaction_index"], event["column"]] >= 2:
            grade_rows[20].append(row)
    for row in rows[60]:
        event = row["event"]
        if grades[event["reaction_index"], event["column"]] >= 2:
            grade_rows[60].append(row)

    sector_rows: dict[int, list[float]] = {horizon: [] for horizon in HORIZONS}
    for horizon in HORIZONS:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows[horizon]:
            grouped[sectors[row["event"]["column"]]].append(row["value"])
        means = [float(np.mean(values)) for values in grouped.values() if len(values) >= 10]
        sector_rows[horizon] = means

    controls = perturbation(adj_close, versions_by_ticker, events)
    midterms = midterm_rows(days, member, adj_close, benchmark)
    next_election_date, next_midterm = event_watch.next_election(
        date.fromisoformat(str(days[-1]))
    )
    full_window = {
        str(horizon): {
            "events": len(rows[horizon]),
            "share": len(rows[horizon]) / len(choosing) if choosing else None,
        }
        for horizon in HORIZONS
    }
    return {
        "version": "event-shock/1",
        "cache": str(cache),
        "sessions": len(days),
        "first_session": str(days[0]),
        "last_session": str(days[-1]),
        "frames_missing": frames_missing,
        "sample": {
            "events": len(events),
            "choosing": len(choosing),
            "reported": len(reported),
            "full_window": full_window,
            "by_year": {
                str(year): sum(1 for event in events if int(event["reaction_date"][:4]) == year)
                for year in sorted({int(event["reaction_date"][:4]) for event in events})
            },
        },
        "A1": own,
        "A1_reported": {
            str(horizon): describe(reported_rows[horizon]) for horizon in HORIZONS
        },
        "A2": {**spread, "peers": peers},
        "A3": {
            "midterms": midterms,
            "next_election": next_election_date.isoformat(),
            "next_election_midterm": next_midterm,
        },
        "diagnostics": {
            "eps": diagnostic(eps_choosing),
            "revenue": diagnostic(revenue_choosing),
            "positive": diagnostic(positive_choosing),
            "grade_a": {
                str(horizon): describe(grade_rows[horizon]) for horizon in HORIZONS
            },
            "sector_neutral": {
                str(horizon): {
                    "sectors": len(sector_rows[horizon]),
                    "mean": float(np.mean(sector_rows[horizon]))
                    if sector_rows[horizon]
                    else None,
                }
                for horizon in HORIZONS
            },
        },
        "controls": controls,
        "verdict": {
            "A1_pass": own["pass"],
            "A2_pass": spread["pass"],
            "A3_gated": False,
        },
    }


# The look-ahead controls: a future perturbation leaves detection unchanged.
def perturbation(
    adj_close: np.ndarray,
    versions_by_ticker: list,
    events: list[dict],
) -> dict:
    """Return the perturbation and borderline-threshold checks."""
    rng = np.random.default_rng(RNG_SEED + 3)
    sample = (
        [events[index] for index in rng.choice(len(events), size=100, replace=False)]
        if len(events) > 100
        else list(events)
    )
    unchanged = 0
    changed = 0
    for event in sample:
        index = event["reaction_index"]
        column = event["column"]
        factor = 1.0 + ((index % 11) - 5) / 100.0
        perturbed = adj_close[:, column].copy()
        perturbed[index + 1:] *= factor
        series = event_watch.quarter_series(versions_by_ticker[column], "net_income")
        change = event_watch.earnings_changes(series)[date.fromisoformat(event["period_end"])]
        reaction = float(perturbed[index] / perturbed[index - 1] - 1.0)
        same = change["available"].isoformat() == event["available"]
        same = same and abs(reaction - event["reaction_return"]) < 1e-12
        if change["qoq"] is None or event["qoq"] is None:
            same = same and change["qoq"] is None and event["qoq"] is None
        else:
            same = same and abs(change["qoq"] - event["qoq"]) < 1e-12
        unchanged += int(same)
        before_changed = adj_close[:, column].copy()
        before_changed[index - 1] *= 1.01
        new_reaction = float(before_changed[index] / before_changed[index - 1] - 1.0)
        changed += int(abs(new_reaction - event["reaction_return"]) > 1e-9)
    borderline = None
    if sample:
        event = sample[0]
        checks = []
        for target, expected in ((-0.049, False), (-0.051, True)):
            flag = event_watch.negative_shock(event["qoq"], event["yoy"]) and (
                target <= event_watch.REACTION_DROP
            )
            checks.append({"reaction": target, "flag": flag, "expected": expected})
        borderline = {
            "ticker": event["ticker"],
            "checks": checks,
            "ok": all(check["flag"] == check["expected"] for check in checks),
        }
    return {
        "sampled": len(sample),
        "detection_unchanged": unchanged,
        "reaction_changed": changed,
        "borderline": borderline,
    }


# The human-readable brief printed beside the JSON.
def brief(scan_result: dict) -> str:
    """Return the plain-word summary of a scan."""
    lines = [f"Event watch {scan_result['asof']}"]
    calendar_info = scan_result["calendar"]
    fomc_sessions = calendar_info["sessions_to_fomc"]
    election_sessions = calendar_info["sessions_to_election"]
    lines.append(
        "Calendar: next FOMC "
        f"{calendar_info['next_fomc']} "
        f"({fomc_sessions if fomc_sessions is not None else 'n/a'} sessions), "
        f"next election {calendar_info['next_election']} "
        f"({'midterm' if calendar_info['next_election_midterm'] else 'presidential'}, "
        f"{election_sessions if election_sessions is not None else 'n/a'} sessions)."
    )
    recent = [row for row in scan_result["shocks"] if row["age_sessions"] <= RECENT_SESSIONS]
    older = [row for row in scan_result["shocks"] if row["age_sessions"] > RECENT_SESSIONS]
    lines.append(
        f"Earnings shocks in the latest release: {len(recent)} within "
        f"{RECENT_SESSIONS} sessions, {len(older)} older."
    )
    for row in recent + older:
        eps = "n/a" if row["eps_qoq"] is None else f"{row['eps_qoq']:+.1%}"
        yoy = "n/a" if row["eps_yoy"] is None else f"{row['eps_yoy']:+.1%}"
        revenue = "n/a" if row["revenue_yoy"] is None else f"{row['revenue_yoy']:+.1%}"
        volume = "n/a" if row["volume_ratio"] is None else f"{row['volume_ratio']:.1f}x"
        age = row["age_sessions"]
        headline = row.get("grade_headline")
        grade = f"{row['grade']} ({headline})" if headline else row["grade"]
        lines.append(
            f"  {row['ticker']} {row['reaction_date']} "
            f"({age} session{'s' if age != 1 else ''} ago): "
            f"EPS {eps} QoQ / {yoy} YoY, revenue {revenue} YoY, "
            f"reaction {row['reaction_return']:+.1%}, volume {volume}, "
            f"grade {grade}, action {row['action']}."
        )
    if scan_result["price_shocks"]:
        lines.append(f"Large adverse price moves in the last {PRICE_WINDOW} sessions:")
        for row in scan_result["price_shocks"]:
            lines.append(
                f"  {row['ticker']} {row['date']}: {row['return']:+.1%} on "
                f"{row['volume_ratio']:.1f}x volume."
            )
    for item in scan_result["contagion"]:
        trigger = item["trigger"]
        mean = item["mean"]
        lines.append(
            f"Book since {trigger['ticker']} shock {trigger['reaction_date']}: "
            f"mean {mean:+.1%} across {item['members']} names."
            if mean is not None
            else f"Book since {trigger['ticker']} shock: no usable prices."
        )
    return "\n".join(lines)


# Parse arguments, run the scan or the study, and write the result.
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--asof", default=None)
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--study", action="store_true")
    parser.add_argument("--cache", default="/home/animallya96/dsv41/pit2/cache.npz")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    store = MarketStore(args.root)
    if args.study:
        result = study(store, Path(args.cache))
        output = Path(args.output or "docs/research/scorecards/event-shock/result.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=1, sort_keys=True, allow_nan=False))
        print(json.dumps(result["verdict"], sort_keys=True))
        return 0
    asof = date.fromisoformat(args.asof) if args.asof else date.today()
    result = scan(store, asof)
    output = Path(
        args.output
        or f"data/market/research/event-watch/asof={asof.isoformat()}/event_watch.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1, sort_keys=True, allow_nan=False))
    print(brief(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
