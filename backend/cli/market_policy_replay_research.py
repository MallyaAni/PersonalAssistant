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

from backend.agents.trading.desk import desk, point_in_time
from backend.cli import market_pit_scorecard as scorecard
from backend.market import grade_led_leader_policy as leader
from backend.market import policy_book, universe
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
    "backend/market/policy_book.py",
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


# Trading costs charged on every change of weight, per side, in the realised P&L.
COST_BPS = 10.0


# The adjusted open: the open on the adjusted-close basis, so a fill at the open
# and a mark at the close are on one price scale across splits and dividends.
def adjusted_open(panel, column: int) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return (
            np.asarray(panel.open[:, column], dtype=float)
            * np.asarray(panel.adj_close[:, column], dtype=float)
            / np.asarray(panel.close[:, column], dtype=float)
        )


# What happened after each signal, measured from the price the rule could
# actually trade at: a target set at close t fills at the open of t+1, so the
# outcome runs from that adjusted open to the close h sessions after the
# decision, against the benchmark over the same span. An entry (a target from
# zero) is judged by its excess return; an exit (a target to zero) by the
# return it avoided. The overnight gap after the decision is not the rule's.
def signal_outcomes(panel, column: int, path: np.ndarray) -> dict:
    closes = np.asarray(panel.adj_close[:, column], dtype=float)
    fills = adjusted_open(panel, column)
    b = panel.index(panel.benchmark)
    bench = np.asarray(panel.adj_close[:, b], dtype=float)
    bench_fill = adjusted_open(panel, b)
    entries: list[dict] = []
    exits: list[dict] = []
    n = len(path)
    for t in range(1, n):
        before, after = float(path[t - 1]), float(path[t])
        kind = (
            "entry" if before == 0 < after else "exit" if after == 0 < before else None
        )
        if kind is None or t + 1 >= n:
            continue
        price, base = fills[t + 1], bench_fill[t + 1]
        if not (np.isfinite(price) and price > 0 and np.isfinite(base) and base > 0):
            continue
        row = {"date": str(panel.dates[t])[:10], "filled": str(panel.dates[t + 1])[:10]}
        for h in HORIZONS:
            if t + h < n and np.isfinite(closes[t + h]) and np.isfinite(bench[t + h]):
                own = closes[t + h] / price - 1.0
                row[f"return_{h}"] = float(own)
                row[f"excess_{h}"] = float(own - (bench[t + h] / base - 1.0))
        (entries if kind == "entry" else exits).append(row)

    return {
        "entries": entries,
        "exits": exits,
        "entry_summary": _pooled(entries),
        "exit_summary": _pooled(exits),
    }


# What the rule's trades in this name earned, as a share of the book: each fill
# at its session's open (an FOMC restoration timed for the decision close at
# that close), the position held at its weight from the fill, the overnight
# move earned by the weight held into the open and the session's move by the
# weight after it, COST_BPS charged on every change of weight. Beside it, the
# benchmark held at the same weights on the same sessions: what the exposure
# alone would have earned, so the name's P&L is read as the rule's choice of
# this name and its timing, not as being invested. And the round trips, each
# from its entry fill to its exit fill.
def realised(panel, column: int, trades: list[dict]) -> dict:
    dates = [str(d)[:10] for d in panel.dates]
    index = {day: t for t, day in enumerate(dates)}
    closes = np.asarray(panel.adj_close[:, column], dtype=float)
    opens = adjusted_open(panel, column)
    b = panel.index(panel.benchmark)
    bench = np.asarray(panel.adj_close[:, b], dtype=float)
    bench_open = adjusted_open(panel, b)
    by_session: dict[int, list[dict]] = {}
    for trade in trades:
        by_session.setdefault(index[trade["date"]], []).append(trade)
    n = len(dates)
    earned = np.zeros(n)
    benched = np.zeros(n)
    costs = np.zeros(n)
    at_open = np.zeros(n)
    after_close = np.zeros(n)
    unpriced: list[str] = []
    weight = 0.0
    for t in range(n):
        held = weight
        fills = by_session.get(t, [])
        opening = [x for x in fills if x.get("timing") != "decision_close"]
        closing = [x for x in fills if x.get("timing") == "decision_close"]
        middle = opening[-1]["target"] if opening else held
        weight = closing[-1]["target"] if closing else middle
        costs[t] = COST_BPS / 1e4 * (abs(middle - held) + abs(weight - middle))
        at_open[t], after_close[t] = middle, weight
        if t == 0 or not (held or middle):
            continue
        priced = all(
            np.isfinite(x) and x > 0
            for x in (
                closes[t - 1],
                opens[t],
                closes[t],
                bench[t - 1],
                bench_open[t],
                bench[t],
            )
        )
        if not priced:
            unpriced.append(dates[t])
            continue
        earned[t] = held * (opens[t] / closes[t - 1] - 1) + middle * (
            closes[t] / opens[t] - 1
        )
        benched[t] = held * (bench_open[t] / bench[t - 1] - 1) + middle * (
            bench[t] / bench_open[t] - 1
        )
    trips: list[dict] = []
    start = None
    for t in range(n):
        before = after_close[t - 1] if t else 0.0
        if before == 0 and at_open[t] > 0:
            start = t
        if start is not None and before > 0 and at_open[t] == 0:
            span = slice(start, t + 1)
            trips.append(
                {
                    "entered": dates[start],
                    "exited": dates[t],
                    "sessions": t - start,
                    "price_return": float(opens[t] / opens[start] - 1),
                    "excess": float(
                        opens[t] / opens[start] - bench_open[t] / bench_open[start]
                    ),
                    "pnl": float((earned[span] - costs[span]).sum()),
                }
            )
            start = None
    net = float((earned - costs).sum())
    held_sessions = at_open > 0
    short = [trip for trip in trips if trip["sessions"] <= 2]
    return {
        "cost_bps": COST_BPS,
        "benchmark": panel.benchmark,
        "gross": float(earned.sum()),
        "costs": float(costs.sum()),
        "net": net,
        "benchmark_same_weights": float(benched.sum()),
        "excess": float(net - benched.sum()),
        "sessions_held": int(held_sessions.sum()),
        "mean_weight_held": float(at_open[held_sessions].mean())
        if held_sessions.any()
        else 0.0,
        "round_trips": len(trips),
        "winning_trips": sum(1 for trip in trips if trip["pnl"] > 0),
        "trips_beating_benchmark": sum(1 for trip in trips if trip["excess"] > 0),
        "short_trips": len(short),
        "short_trip_pnl": float(sum(trip["pnl"] for trip in short)),
        "open_since": dates[start] if start is not None else None,
        "unpriced_sessions": unpriced,
        "trips": trips,
    }


# The New York open of a session, as the instant a close's grade takes effect.
def _next_open(session: str) -> str:
    from zoneinfo import ZoneInfo

    opened = datetime.fromisoformat(f"{session}T09:30:00").replace(
        tzinfo=ZoneInfo("America/New_York")
    )
    return opened.isoformat()


# The installed policy run as the paper account runs it (`policy_book`): the
# same engine the backtest reports, so the chart, the backtest and the live
# rule are one calculation. Returns the simulated book and the desk's grades.
def installed_book(report) -> policy_book.Book:
    from backend.agents.trading.desk import exit as exit_analyst

    panel = report.panel
    return policy_book.simulate(
        panel.dates,
        panel.tickers,
        panel.benchmark,
        np.asarray(panel.open, dtype=float),
        np.asarray(panel.close, dtype=float),
        np.asarray(panel.adj_close, dtype=float),
        np.asarray(report.graded.grades),
        np.asarray(exit_analyst.evidence(panel).signalled(), dtype=bool),
        policy_book.Rule(),
        tilt=leader.report_pe_tilts(report),
    )


# The book's compounded record, over all of it and the 2015-2022 / 2023- windows
# the rule was chosen and checked on.
def book_summary(book) -> dict:
    split = next(i for i, d in enumerate(book.dates) if d >= "2023-01-01")
    start = int(np.argmax(np.isfinite(book.equity)))
    return {
        "capital": float(book.equity[start]),
        "all": policy_book.metrics(book, leader.WINDOW),
        "to_2022": policy_book.metrics(book, leader.WINDOW, split),
        "from_2023": policy_book.metrics(book, split - 1),
        "fills": len(book.trades),
        "costs": float(book.costs),
        "rule": {k: v for k, v in vars(policy_book.Rule()).items()},
    }


def replay(
    report, history_path, arm_name: str, *, basis: str = "book"
) -> tuple[dict, dict[str, dict]]:
    """Return (manifest, {ticker: rows}) for the installed rule, or a scorecard arm."""
    panel = report.panel
    dates = [str(d)[:10] for d in panel.dates]
    summary = None
    if arm_name in INSTALLED_ARMS.values():
        if basis != "book":
            raise ValueError("The installed rule is replayed over the book")
        restricted = report
        book = installed_book(report)
        summary = book_summary(book)
        held = book.weights
        by_name: dict[str, list[dict]] = {}
        for trade in book.trades:
            by_name.setdefault(trade["ticker"], []).append(
                {k: v for k, v in trade.items() if k != "ticker"}
            )
        planned = book.planned if book.planned is not None else held[-1]
        # The weight the rule set at each close: what is held after the next fills.
        path = np.vstack([held[1:], planned[None, :]])
    else:
        if basis == "membership":
            restricted, mask = point_in_time.point_in_time(report, history_path)
        else:
            mask = policy_book.sizable(
                np.asarray(panel.adj_close, dtype=float), panel.tickers, panel.benchmark
            )
            restricted = point_in_time.restrict(report, mask)
        allocator = scorecard.ARMS[arm_name](restricted, mask)
        path = np.zeros((len(dates), len(panel.tickers)))
        for t in range(len(dates)):
            path[t] = allocator(restricted, panel, None, t)
        held = np.vstack([np.zeros((1, len(panel.tickers))), path[:-1]])
        by_name = {
            ticker: _arm_trades(path[:, column], dates)
            for column, ticker in enumerate(panel.tickers)
        }
    stocks: dict[str, dict] = {}
    for column, ticker in enumerate(panel.tickers):
        if ticker in universe.MARKET_INDICES:
            continue
        trades = by_name.get(ticker, [])
        rows, grades = [], []
        filled = {trade["date"] for trade in trades}
        for t, day in enumerate(dates):
            weight = float(held[t, column])
            # The letter the desk gave the name at that close; a name too new for
            # the sizing window still shows its real grade.
            grade = (report if basis == "book" else restricted).graded.letter(t, column)
            # Every change of letter, as the rule saw it at that close and acted on
            # it at the next open: the chart's grade arrows, from the same run.
            if t == 0 or grade != grades[-1]["grade"]:
                grades.append(
                    {
                        "date": day,
                        "grade": grade,
                        "said": False,
                        **(
                            {"at": _next_open(dates[t + 1])}
                            if t + 1 < len(dates)
                            else {}
                        ),
                    }
                )
            # The weight held at the close of each session the name traded.
            if t == 0 or day in filled:
                rows.append({"date": day, "weight": weight, "grade": grade})
        stocks[ticker] = {
            "ticker": ticker,
            "rows": rows,
            "trades": trades,
            "grades": grades,
            "latest_target": float(path[-1, column]),
            "sessions_held": int((held[:, column] > 0).sum()),
            "outcomes": signal_outcomes(panel, column, path[:, column]),
            "realised": realised(panel, column, trades),
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
        **({"book": summary} if summary else {}),
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
                "In-sample research: the installed rule run as the paper account "
                "runs it, over today's desk names from the first session each had "
                "a full price window, reading only data up to each close: fills at "
                "the next open from cash on hand, whole shares, 10 bp a side, the "
                "FOMC cycle. The same run is the backtest. Not audited accounting, "
                "not advice that was ever published."
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


# A scorecard arm's trades: each change of target at a close, filled at the next open.
def _arm_trades(path: np.ndarray, dates: list[str]) -> list[dict]:
    trades = []
    shown = 0.0
    for t in range(len(dates) - 1):
        weight = float(path[t])
        delta = weight - shown
        if abs(delta) >= DUST or ((shown == 0.0) != (weight == 0.0) and delta != 0.0):
            trades.append(
                {
                    "decided": dates[t],
                    "date": dates[t + 1],
                    "action": "BUY" if delta > 0 else "SELL",
                    "size": abs(delta),
                    "target": weight,
                }
            )
            shown = weight
    return trades


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
