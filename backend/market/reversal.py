"""Post-decision reversal: the most beaten book names bought after an FOMC decision.

Registered in `docs/research/post-decision-reversal-2026-09-15.md` before
any number was seen. At the decision close the book is ranked by its
five-session return into the meeting; the worst decile is bought at the
next open, equal weight, and sold at the close ten sessions after entry.
Returns are adjusted prices, less beta times SPY over the same window,
after costs per side. The book's contribution is a tenth of the basket's
return (10% of equity).

Two uses of the same arithmetic: a backtest over every scheduled
decision since 2021, and a forward shadow that records each cycle as
real sessions arrive, trading nothing. Nothing here places an order or
changes a grade.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from backend.market.panel import Panel

VERSION = "post-decision-reversal/1"
SIGNAL_SESSIONS = 5
HOLD = 10
DECILE = 0.10
MIN_NAMES = 5
WEIGHT = 0.10
DEEP = -0.10
BETA_LOOKBACK = 120
COSTS_BP = (10.0, 30.0)
FIRST_MEETING = date(2021, 1, 27)
NAME = "reversal-shadow.json"
ANY_DAY_NAME = "reversal-anyday-shadow.json"
SHADOW_START = date(2026, 9, 16)


# The open adjusted by the same factor as the close, so entry and exit
# prices sit on one scale across splits.
def adjusted_open(panel: Panel) -> np.ndarray:
    """Return (T, N) adjusted opens."""
    with np.errstate(all="ignore"):
        factor = panel.adj_close / panel.close
        return np.where(np.isfinite(factor), panel.open * factor, np.nan)


# The five-session return into session t for every name.
def into_returns(panel: Panel, t: int) -> np.ndarray:
    """Return (N,) close_t / close_(t-5) - 1, NaN where unknown."""
    if t < SIGNAL_SESSIONS:
        return np.full(panel.adj_close.shape[1], np.nan)
    with np.errstate(all="ignore"):
        return panel.adj_close[t] / panel.adj_close[t - SIGNAL_SESSIONS] - 1


# The basket at a decision close: the worst decile of the book by the
# five-session return, at least MIN_NAMES names, never the benchmark.
def basket(panel: Panel, t: int, members: set[str] | None = None) -> list[int]:
    """Return the columns of the basket, worst first; empty when too few names."""
    into = into_returns(panel, t)
    columns = [
        j
        for j, ticker in enumerate(panel.tickers)
        if ticker != panel.benchmark
        and (members is None or ticker in members)
        and np.isfinite(into[j])
        and np.isfinite(panel.adj_close[t, j])
    ]
    if len(columns) < MIN_NAMES:
        return []
    columns.sort(key=lambda j: into[j])
    size = max(MIN_NAMES, int(math.ceil(len(columns) * DECILE)))
    return columns[:size]


# Beta of each name to the benchmark from the trailing window before t.
def betas(panel: Panel, t: int) -> np.ndarray:
    """Return (N,) betas, clipped to [0, 3], 1 where unknown."""
    b = panel.index(panel.benchmark)
    start = max(1, t - BETA_LOOKBACK)
    with np.errstate(all="ignore"):
        daily = panel.adj_close[start : t + 1] / panel.adj_close[start - 1 : t] - 1
    market = daily[:, b]
    out = np.ones(daily.shape[1])
    ok_m = np.isfinite(market)
    if ok_m.sum() < 40:
        return out
    m = market[ok_m] - market[ok_m].mean()
    var = float(m @ m)
    if var <= 0:
        return out
    for j in range(daily.shape[1]):
        x = daily[ok_m, j]
        ok = np.isfinite(x)
        if ok.sum() < 40:
            continue
        xc = x[ok] - x[ok].mean()
        out[j] = float(np.clip((xc @ m[ok]) / float(m[ok] @ m[ok]), 0.0, 3.0))
    return out


# One meeting's basket from the decision close: entry at the next open,
# exit at the close HOLD sessions after entry, costs both ways.
def meeting(panel: Panel, t: int, members: set[str] | None = None) -> dict | None:
    """Return the meeting's row, or None when the window is not on the panel."""
    entry, exit_ = t + 1, t + HOLD
    if exit_ >= len(panel.dates):
        return None
    columns = basket(panel, t, members)
    if not columns:
        return None
    opens = adjusted_open(panel)
    b = panel.index(panel.benchmark)
    with np.errstate(all="ignore"):
        raw = panel.adj_close[exit_, columns] / opens[entry, columns] - 1
        spy = float(panel.adj_close[exit_, b] / opens[entry, b] - 1)
    ok = np.isfinite(raw)
    if ok.sum() < MIN_NAMES:
        return None
    kept = [c for c, k in zip(columns, ok, strict=False) if k]
    raw = raw[ok]
    beta = float(np.mean(betas(panel, t)[kept]))
    into = into_returns(panel, t)[kept]
    basket_raw = float(raw.mean())
    adjusted = basket_raw - beta * spy
    return {
        "decision": str(panel.dates[t]),
        "entry": str(panel.dates[entry]),
        "exit": str(panel.dates[exit_]),
        "names": [panel.tickers[c] for c in kept],
        "into_mean": float(into.mean()),
        "deep": bool(into.mean() <= DEEP),
        "basket_raw": basket_raw,
        "spy": spy,
        "beta": beta,
        "adjusted": adjusted,
        "after_costs": {str(int(c)): adjusted - 2 * c / 1e4 for c in COSTS_BP},
        "book_contribution_30bp": WEIGHT * (adjusted - 2 * COSTS_BP[1] / 1e4),
        "share_positive": float((raw > 0).mean()),
    }


def _stats(values: list[float]) -> dict:
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 2:
        return {
            "n": n,
            "mean": float(x.mean()) if n else None,
            "t": None,
            "share_positive": None,
        }
    sd = float(x.std(ddof=1))
    return {
        "n": n,
        "mean": float(x.mean()),
        "t": float(x.mean() / (sd / math.sqrt(n))) if sd > 0 else None,
        "share_positive": float((x > 0).mean()),
    }


# The bar as registered: primary on all meetings, secondary on the deep subset.
def verdict(rows: list[dict]) -> dict:
    """Return the standing of the registered bar."""
    key = "30"
    all_ = _stats([r["after_costs"][key] for r in rows])
    deep = _stats([r["after_costs"][key] for r in rows if r["deep"]])
    rest = _stats([r["after_costs"][key] for r in rows if not r["deep"]])
    primary = bool(
        all_["t"] is not None
        and all_["mean"] > 0
        and all_["t"] > 2
        and all_["share_positive"] >= 0.6
    )
    secondary = bool(
        deep["n"] >= 8
        and deep["t"] is not None
        and deep["mean"] > 0
        and deep["t"] > 2
        and deep["share_positive"] >= 0.6
    )
    if primary:
        standing = "primary passed: shadow runs unconditional"
    elif secondary:
        standing = "secondary passed: shadow runs with the depth condition"
    else:
        standing = "insufficient evidence to advance this specification"
    return {
        "all_meetings": all_,
        "deep": deep,
        "not_deep": rest,
        "primary_passed": primary,
        "secondary_passed": secondary,
        "standing": standing,
        "bar": (
            "beta-adjusted basket return after 30 bp per side: mean > 0, t > 2, "
            "positive in at least 60% of meetings; secondary the same on the "
            "deep subset (into-meeting mean <= -10%) with at least eight meetings"
        ),
    }


# Every scheduled decision on the panel from FIRST_MEETING.
def backtest(
    panel: Panel, decisions: list[date], members: set[str] | None = None
) -> dict:
    """Return {meetings, verdict, specification}."""
    dates = panel.dates.astype("datetime64[D]")
    rows = []
    for day in decisions:
        if day < FIRST_MEETING:
            continue
        matched = np.flatnonzero(dates == np.datetime64(day))
        if not len(matched):
            continue
        row = meeting(panel, int(matched[0]), members)
        if row is not None:
            rows.append(row)
    return {
        "version": VERSION,
        "specification": {
            "signal_sessions": SIGNAL_SESSIONS,
            "hold_sessions": HOLD,
            "decile": DECILE,
            "min_names": MIN_NAMES,
            "weight": WEIGHT,
            "deep_threshold": DEEP,
            "beta_lookback": BETA_LOOKBACK,
            "costs_bp_per_side": list(COSTS_BP),
            "first_meeting": FIRST_MEETING.isoformat(),
            "universe": "book names with a price on the decision day; chosen in 2026",
        },
        "meetings": rows,
        "verdict": verdict(rows),
    }


# The generalisation registered on 2026-09-15 after the FOMC form: on any
# session where the worst decile's five-session return is at or below the
# depth threshold, and no episode is still holding, the same basket, entry,
# hold and exit. Meetings are then one case of a broader condition.
def backtest_any_day(
    panel: Panel, members: set[str] | None = None, since: date = FIRST_MEETING
) -> dict:
    """Return {episodes, verdict, specification} for the any-day form."""
    dates = panel.dates.astype("datetime64[D]")
    rows = []
    busy_until = -1
    for t in range(SIGNAL_SESSIONS, len(dates) - HOLD):
        if dates[t].astype(object) < since or t <= busy_until:
            continue
        columns = basket(panel, t, members)
        if not columns:
            continue
        into = into_returns(panel, t)[columns]
        if not np.isfinite(into).all() or into.mean() > DEEP:
            continue
        row = meeting(panel, t, members)
        if row is None:
            continue
        rows.append(row)
        busy_until = t + HOLD
    return {
        "version": VERSION + "/any-day",
        "specification": {
            "trigger": (
                f"worst-decile five-session mean <= {DEEP:+.0%}, no episode holding"
            ),
            "hold_sessions": HOLD,
            "since": since.isoformat(),
        },
        "episodes": rows,
        "verdict": verdict(rows),
    }


# ---- the forward shadow: each cycle recorded as sessions arrive, nothing traded


def path(root: Path, name: str = NAME) -> Path:
    """Where a shadow ledger lives."""
    return Path(root) / "desk" / name


# The any-day trigger dates on the panel from `since`: the worst decile at or
# below the depth threshold, and no trigger within the hold before it. The
# window need not have completed, so the latest sessions can trigger.
def triggers_any_day(
    panel: Panel, members: set[str] | None = None, since: date = SHADOW_START
) -> list[date]:
    """Return the sessions on which an any-day episode opens."""
    dates = panel.dates.astype("datetime64[D]")
    out: list[date] = []
    busy_until = -1
    for t in range(SIGNAL_SESSIONS, len(dates)):
        day = dates[t].astype(object)
        if day < since or t <= busy_until:
            continue
        columns = basket(panel, t, members)
        if not columns:
            continue
        into = into_returns(panel, t)[columns]
        if np.isfinite(into).all() and into.mean() <= DEEP:
            out.append(day)
            busy_until = t + HOLD
    return out


def load(root: Path, name: str = NAME) -> dict:
    """Return the ledger, or an empty one."""
    target = path(root, name)
    if not target.exists():
        return {"version": VERSION, "cycles": [], "written": None}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": VERSION, "cycles": [], "written": None}


# Advance the ledger with the panel's sessions: open a cycle on a decision
# close, fill its entry at the next open, close it at the exit close.
def observe(
    root: Path,
    panel: Panel,
    decisions: list[date],
    members: set[str] | None = None,
    now: datetime | None = None,
    name: str = NAME,
) -> dict:
    """Return the ledger after this session, having written it."""
    ledger = load(root, name)
    dates = [str(d) for d in panel.dates.astype("datetime64[D]")]
    by_decision = {c["decision"]: c for c in ledger["cycles"]}
    opens = adjusted_open(panel)
    b = panel.index(panel.benchmark)
    # Open cycles for decisions the panel has reached and the ledger lacks.
    for day in decisions:
        key = day.isoformat()
        if key in by_decision or key not in dates or day < SHADOW_START:
            continue
        t = dates.index(key)
        columns = basket(panel, t, members)
        if not columns:
            continue
        into = into_returns(panel, t)[columns]
        cycle = {
            "decision": key,
            "names": [panel.tickers[c] for c in columns],
            "into_mean": float(into.mean()),
            "deep": bool(into.mean() <= DEEP),
            "beta": float(np.mean(betas(panel, t)[columns])),
            "status": "awaiting entry at the next open",
            "entry": None,
            "exit": None,
        }
        ledger["cycles"].append(cycle)
        by_decision[key] = cycle
    # Fill entries and exits from sessions now on the panel.
    for cycle in ledger["cycles"]:
        t = dates.index(cycle["decision"]) if cycle["decision"] in dates else None
        if t is None:
            continue
        cols = [panel.index(n) for n in cycle["names"] if n in panel.tickers]
        entry, exit_ = t + 1, t + HOLD
        if cycle["entry"] is None and entry < len(dates):
            cycle["entry"] = {
                "session": dates[entry],
                "prices": {panel.tickers[c]: float(opens[entry, c]) for c in cols},
                "spy": float(opens[entry, b]),
            }
            cycle["status"] = "open"
        if cycle["entry"] is not None and cycle["exit"] is None:
            mark = min(exit_, len(dates) - 1)
            with np.errstate(all="ignore"):
                rets = [
                    panel.adj_close[mark, c]
                    / cycle["entry"]["prices"][panel.tickers[c]]
                    - 1
                    for c in cols
                    if cycle["entry"]["prices"].get(panel.tickers[c], 0) > 0
                ]
                spy = float(panel.adj_close[mark, b] / cycle["entry"]["spy"] - 1)
            rets = [r for r in rets if np.isfinite(r)]
            raw = float(np.mean(rets)) if rets else None
            marked = {
                "session": dates[mark],
                "basket_raw": raw,
                "spy": spy,
                "adjusted": (raw - cycle["beta"] * spy) if raw is not None else None,
            }
            if marked["adjusted"] is not None:
                marked["after_costs_30"] = marked["adjusted"] - 2 * COSTS_BP[1] / 1e4
                marked["book_contribution_30bp"] = WEIGHT * marked["after_costs_30"]
            if mark == exit_:
                cycle["exit"] = marked
                cycle["status"] = "closed"
            else:
                cycle["mark"] = marked
                cycle["status"] = f"open, {exit_ - mark} sessions to exit"
    ledger["written"] = (now or datetime.now(tz=UTC)).isoformat(timespec="seconds")
    closed = [c["exit"]["after_costs_30"] for c in ledger["cycles"] if c.get("exit")]
    ledger["summary"] = (
        {"closed": len(closed), **_stats(closed)} if closed else {"closed": 0}
    )
    target = path(root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    return ledger


# Write the shadow from the nightly; never raise into it.
def write(
    root: Path,
    panel: Panel,
    decisions: list[date],
    members: set[str] | None = None,
    name: str = NAME,
    label: str = "reversal shadow (meetings)",
) -> dict | None:
    """Advance and write a shadow ledger, or print why not."""
    try:
        ledger = observe(root, panel, decisions, members, name=name)
    except Exception as exc:  # noqa: BLE001 - evidence, never a reason to stop
        print(f"\n{label}: not written ({type(exc).__name__}: {exc})")
        return None
    open_cycles = [c for c in ledger["cycles"] if c["status"] != "closed"]
    print(
        f"\n{label}: {len(ledger['cycles'])} cycles, "
        f"{ledger['summary'].get('closed', 0)} closed, {len(open_cycles)} open"
    )
    for c in open_cycles:
        print(f"  {c['decision']} {c['status']}: {', '.join(c['names'])}")
    return ledger


# Both shadows from the nightly: the meeting form on the FOMC calendar and
# the any-day form on its own triggers.
def write_both(
    root: Path, panel: Panel, decisions: list[date], members: set[str] | None = None
) -> None:
    """Advance both ledgers; never raise into the nightly."""
    write(root, panel, decisions, members)
    write(
        root,
        panel,
        triggers_any_day(panel, members),
        members,
        name=ANY_DAY_NAME,
        label="reversal shadow (any day)",
    )
