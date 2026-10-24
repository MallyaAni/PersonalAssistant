"""What the installed policy's rule would have held in each name, session by session.

    python -m backend.cli.market_policy_replay_research --root data/market

The audited history on the desk's charts is the record of the policy it
names, locked when that policy was installed; a newer policy has no such
record until its own is reviewed. This writes the research view instead:
the point-in-time scorecard arm that reproduces the installed rule, run
once over the panel, and its target weight for every name on every
session, with the trades those targets imply at the next open. It is
in-sample research, not audited accounting and not advice that was ever
published, and the chart says so beside every marker it draws from it.

The chart replays the book the installed policy trades: every name on
today's desk, from the first session it has the full trailing window the
live sizing reads (WINDOW + 1 finite closes), whenever it was added to the
desk. Grades, sizes and the volatility brake read only data up to each
close. The scorecard's survivorship control (the dated membership history,
which admits an overlay name only from the day it was listed in
universe.py) answers a different question, whether the rule would have
picked these names, and is still available with `--membership`; applied
to the chart it graded C, and so never bought, every name added this
September for its whole past (CoreWeave, IREN, Apple, Meta ...).

The result lands under `research/policy-replay/<arm>/<asof>/` with a
manifest naming the arm, its parameters, the sources it ran from and the
sessions covered; the API serves the newest folder.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk, event_risk, point_in_time
from backend.market import grade_led_leader_policy as leader
from backend.cli import market_pit_scorecard as scorecard
from backend.market import universe
from backend.market.calendar import fomc_decisions
from backend.market.store import MarketStore

DIRECTORY = "research/policy-replay"
SCHEMA = "policy-replay-research/1"
# The arm that reproduces each installed policy's rule, and the policy it stands for.
INSTALLED_ARMS = {
    "grade-led-leader-weight/1": "leader_ewma_minB_floor50",
}
# A target move the size column would print as 0.0% is no trade.
DUST = 0.0005
SOURCES = (
    "backend/agents/trading/desk/point_in_time.py",
    "backend/cli/market_pit_scorecard.py",
    "backend/cli/market_policy_replay_research.py",
    "backend/market/grade_led_leader_policy.py",
    "backend/agents/trading/desk/event_risk.py",
)


def _sources() -> dict[str, str]:
    code = Path(__file__).resolve().parents[2]
    return {name: sha256((code / name).read_bytes()).hexdigest() for name in SOURCES}


def _write(path: Path, value) -> None:
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


HORIZONS = (5, 20, 60)
# The fundamentals mode the nightly grades with; the chart must grade the same way.
FUNDAMENTALS = desk.FUNDAMENTALS_CURRENT


# What happened after each signal, with nothing the rule could not have known:
# a target set at close t is compared with the name's close t+h against the
# benchmark's, for each horizon. An entry (a target from zero) is judged by
# its excess return; an exit (a target to zero) by the return it avoided.
def signal_outcomes(panel, column: int, path: np.ndarray) -> dict:
    closes = np.asarray(panel.adj_close[:, column], dtype=float)
    bench = np.asarray(panel.adj_close[:, panel.index(panel.benchmark)], dtype=float)
    entries: list[dict] = []
    exits: list[dict] = []
    n = len(path)
    for t in range(1, n):
        before, after = float(path[t - 1]), float(path[t])
        kind = (
            "entry"
            if before < DUST <= after
            else "exit"
            if after < DUST <= before
            else None
        )
        if kind is None or not np.isfinite(closes[t]) or closes[t] <= 0:
            continue
        row = {"date": str(panel.dates[t])[:10]}
        for h in HORIZONS:
            if t + h < n and np.isfinite(closes[t + h]) and np.isfinite(bench[t + h]):
                own = closes[t + h] / closes[t] - 1.0
                row[f"return_{h}"] = float(own)
                row[f"excess_{h}"] = float(own - (bench[t + h] / bench[t] - 1.0))
        (entries if kind == "entry" else exits).append(row)

    return {
        "entries": entries,
        "exits": exits,
        "entry_summary": _pooled(entries),
        "exit_summary": _pooled(exits),
    }


# The New York open of a session, as the instant a close's grade takes effect.
def _next_open(session: str) -> str:
    from zoneinfo import ZoneInfo

    opened = datetime.fromisoformat(f"{session}T09:30:00").replace(
        tzinfo=ZoneInfo("America/New_York")
    )
    return opened.isoformat()


# (T, N) True where the live policy could size the name at that close: a name
# on today's desk (not an index, not the benchmark) with the full trailing
# window of finite, positive closes the leader sizing reads.
def book_eligibility(panel, window: int = leader.WINDOW) -> np.ndarray:
    closes = np.asarray(panel.adj_close, dtype=float)
    with np.errstate(invalid="ignore"):
        priced = (np.isfinite(closes) & (closes > 0)).astype(np.int64)
    run = np.cumsum(priced, axis=0)
    span = window + 1
    lagged = np.vstack([np.zeros((span, closes.shape[1]), dtype=np.int64), run[:-span]])
    mask = (run - lagged[: len(run)]) == span
    for ticker in (*universe.MARKET_INDICES, panel.benchmark):
        if ticker in panel.tickers:
            mask[:, panel.index(ticker)] = False
    return mask


# The installed policy's own sizing, session by session: every name graded at
# least the entry grade with its full window is sized by the live
# `leader_weights` on that close's trailing window, exactly as `size_report`
# does for the nightly (live cap after the volatility scale, the 63-return
# EWMA), so the chart cannot drift from the scorecard arm's approximations.
def live_leader_targets(restricted, mask: np.ndarray) -> np.ndarray:
    panel = restricted.panel
    closes = np.asarray(panel.adj_close, dtype=float)
    grades = np.asarray(restricted.graded.grades)
    window = leader.WINDOW
    weights = np.zeros(closes.shape)
    for t in range(window, len(panel.dates)):
        sized = mask[t] & (grades[t] >= leader.ENTRY_GRADE)
        weights[t], _ = leader.leader_weights(closes[t - window : t + 1], sized)
    return weights


# The FOMC rule the nightly runs instead of the leader plan in the guidance
# regime (`nightly_plan.event_plan_required`, `event_execution.plan`): when
# the factor drops at a close the book's holdings are the cycle's baseline and
# half of each is sold at the next open; the book then stays frozen through
# the lead-in; on the eve, with the cut done, the baseline is bought back at
# the decision session's close; that night the ordinary plan takes over again.
# A cycle that starts on the eve itself cuts at the decision open and restores
# at the following open, as the live state machine does. Returns the adjusted
# targets and, per session index, the FOMC step that set them.
def fomc_overlay(panel, weights: np.ndarray) -> tuple[np.ndarray, dict[int, str]]:
    from datetime import date as _date

    factor = event_risk.live_path(panel)
    meetings = fomc_decisions()
    days = [_date.fromisoformat(str(d)[:10]) for d in panel.dates]
    out = np.array(weights, dtype=float, copy=True)
    steps: dict[int, str] = {}
    cycle = None
    for t, day in enumerate(days):
        if cycle is None:
            if t == 0 or factor[t] != event_risk.REDUCED:
                continue
            upcoming = next((m for m in meetings if m >= day), None)
            if upcoming is None:
                continue
            cycle = {"decision": upcoming, "baseline": out[t - 1].copy(), "cut": False}
        eve = t + 1 < len(days) and days[t + 1] == cycle["decision"]
        if day < cycle["decision"]:
            if eve and cycle["cut"]:
                out[t] = cycle["baseline"]
                steps[t] = decision_close_step
                cycle["restored"] = True
            else:
                out[t] = cycle["baseline"] * (1.0 - event_risk.REDUCED)
                steps[t] = "fomc_reduction"
                cycle["cut"] = True
            continue
        if not cycle.get("restored"):
            out[t] = cycle["baseline"]
            steps[t] = "fomc_restoration"
        cycle = None
    return out, steps


decision_close_step = "fomc_restoration_decision_close"


def replay(
    report, history_path, arm_name: str, *, basis: str = "book"
) -> tuple[dict, dict[str, dict]]:
    """Return (manifest, {ticker: rows}) for the arm over the book or the membership panel."""
    if basis == "membership":
        restricted, mask = point_in_time.point_in_time(report, history_path)
    elif basis == "book":
        mask = book_eligibility(report.panel)
        restricted = point_in_time.restrict(report, mask)
    else:
        raise ValueError(f"unknown basis {basis!r}")
    panel = restricted.panel
    dates = [str(d)[:10] for d in panel.dates]
    steps: dict[int, str] = {}
    if arm_name in INSTALLED_ARMS.values():
        # The installed policy: its own sizing and its FOMC rule, not the arm.
        weights, steps = fomc_overlay(panel, live_leader_targets(restricted, mask))
    else:
        allocator = scorecard.ARMS[arm_name](restricted, mask)
        weights = np.zeros((len(dates), len(panel.tickers)))
        for t in range(len(dates)):
            weights[t] = allocator(restricted, panel, None, t)
    stocks: dict[str, dict] = {}
    for column, ticker in enumerate(panel.tickers):
        if ticker in universe.MARKET_INDICES:
            continue
        path = weights[:, column]
        rows, trades, grades = [], [], []
        # The last target written: a move is measured from what the chart last
        # showed, so moves under DUST cannot add up to a drawn size that is off.
        shown = 0.0
        for t, day in enumerate(dates):
            weight = float(path[t])
            # The letter the desk gave the name at that close. On the book basis a
            # name too new for the sizing window still shows its real grade; it is
            # simply not sized until the window fills, as live.
            grade = (report if basis == "book" else restricted).graded.letter(t, column)
            # Every change of letter under the installed grading, as the rule saw
            # it at that close and acted on it at the next open: the chart's grade
            # arrows, so they come from the same engine as its trades.
            if t == 0 or grade != grades[-1]["grade"]:
                grades.append(
                    {
                        "date": day,
                        "grade": grade,
                        "said": False,
                        **({"at": _next_open(dates[t + 1])} if t + 1 < len(dates) else {}),
                    }
                )
            delta = weight - shown
            # An entry or an exit is always written, however small; a resize
            # once it reaches DUST from the last written target.
            opened_or_closed = (shown == 0.0) != (weight == 0.0)
            moved = abs(delta) >= DUST or (opened_or_closed and delta != 0.0)
            if moved or t == 0:
                rows.append({"date": day, "weight": weight, "grade": grade})
            # The target set at this close trades at the next session's open (an
            # FOMC restoration on the eve, at the decision session's close).
            if moved and t + 1 < len(dates):
                trade = {
                    "decided": day,
                    "date": dates[t + 1],
                    "action": "BUY" if delta > 0 else "SELL",
                    "size": abs(delta),
                    "target": weight,
                }
                if t in steps:
                    trade["reason"] = steps[t]
                    if steps[t] == decision_close_step:
                        trade["timing"] = "decision_close"
                trades.append(trade)
            if moved:
                shown = weight
        stocks[ticker] = {
            "ticker": ticker,
            "rows": rows,
            "trades": trades,
            "grades": grades,
            "latest_target": float(path[-1]),
            "sessions_held": int((path > 0).sum()),
            "outcomes": signal_outcomes(panel, column, path),
        }
    # The book-wide answer to "did the signals make money": every entry and
    # exit across the names, pooled, so one name's luck cannot carry it.
    pooled_entries = [r for v in stocks.values() for r in v["outcomes"]["entries"]]
    pooled_exits = [r for v in stocks.values() for r in v["outcomes"]["exits"]]
    audit = {
        "entry_summary": _pooled(pooled_entries),
        "exit_summary": _pooled(pooled_exits),
        "by_year": {
            year: _pooled([r for r in pooled_entries if r["date"][:4] == year])
            for year in sorted({r["date"][:4] for r in pooled_entries})
        },
    }
    manifest = {
        "schema": SCHEMA,
        "arm": arm_name,
        "audit": audit,
        "basis": "point_in_time_research_targets_not_audited_history",
        "universe": basis,
        "start": dates[0],
        "through": dates[-1],
        "sessions": len(dates),
        "stocks": sorted(stocks),
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": _sources(),
        **({"membership": str(history_path)} if basis == "membership" else {}),
        "note": (
            (
                "In-sample research: the installed rule run over today's desk "
                "names from the first session each had a full price window, "
                "reading only data up to each close, targets before costs and "
                "fills, trades at the next open. Not audited accounting, not "
                "advice that was ever published."
            )
            if basis == "book"
            else (
                "In-sample research: the installed rule run over the names as "
                "they were members at each date, targets before costs and "
                "fills, trades at the next open. Not audited accounting, not "
                "advice that was ever published."
            )
        ),
    }
    return manifest, stocks


def _pooled(rows: list[dict]) -> dict:
    out: dict = {"count": len(rows)}
    for h in HORIZONS:
        excess = np.array([r[f"excess_{h}"] for r in rows if f"excess_{h}" in r])
        own = np.array([r[f"return_{h}"] for r in rows if f"return_{h}" in r])
        if len(excess):
            out[f"hit_rate_{h}"] = float((excess > 0).mean())
            out[f"mean_excess_{h}"] = float(excess.mean())
            out[f"median_excess_{h}"] = float(np.median(excess))
            out[f"mean_return_{h}"] = float(own.mean())
            out[f"worst_return_{h}"] = float(own.min())
    return out


def write(root: Path, policy: str, manifest: dict, stocks: dict[str, dict]) -> Path:
    """Write the replay under the arm and session and point `latest.json` at it."""
    folder = root / DIRECTORY / manifest["arm"] / manifest["through"]
    manifest = {**manifest, "policy": policy}
    for ticker, value in stocks.items():
        _write(folder / f"{ticker}.json", value)
    _write(folder / "manifest.json", manifest)
    _write(
        root / DIRECTORY / manifest["arm"] / "latest.json",
        {"through": manifest["through"], "generated_at": manifest["generated_at"]},
    )
    return folder


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--policy", default="grade-led-leader-weight/1")
    parser.add_argument("--arm")
    parser.add_argument("--membership")
    args = parser.parse_args(argv)
    arm_name = args.arm or INSTALLED_ARMS[args.policy]
    root = Path(args.root)
    store = MarketStore(root)
    # The report the nightly decides from (`market_daily.desk_report`): the
    # current fundamentals mode, not the research default.
    report = desk.run(store, None, fundamentals=FUNDAMENTALS)
    history = args.membership or universe.MEMBERSHIP_HISTORY_PATH
    manifest, stocks = replay(
        report, history, arm_name, basis="membership" if args.membership else "book"
    )
    folder = write(root, args.policy, manifest, stocks)
    trades = sum(len(value["trades"]) for value in stocks.values())
    print(
        f"{folder}: {len(stocks)} names, {manifest['sessions']} sessions, "
        f"{trades} trades"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
