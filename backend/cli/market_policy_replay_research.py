"""What the installed policy's rule would have held in each name, session by session.

    python -m backend.cli.market_policy_replay_research --root data/market

The audited history on the desk's charts is the record of the policy it
names, locked when that policy was installed; a newer policy has no such
record until its own is reviewed. This writes the research view instead:
the point-in-time scorecard arm that reproduces the installed rule, run
once over the restricted panel, and its target weight for every name on
every session, with the trades those targets imply at the next open. It
is in-sample research on today's names as they were known at the time,
not audited accounting and not advice that was ever published, and the
chart says so beside every marker it draws from it.

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
from backend.market import universe
from backend.market.store import MarketStore

DIRECTORY = "research/policy-replay"
SCHEMA = "policy-replay-research/1"
# The arm that reproduces each installed policy's rule, and the policy it stands for.
INSTALLED_ARMS = {
    "grade-led-leader-weight/1": "ew_graded_leader_forecast_ewma",
}
# A target move the size column would print as 0.0% is no trade.
DUST = 0.0005
SOURCES = (
    "backend/agents/trading/desk/point_in_time.py",
    "backend/cli/market_pit_scorecard.py",
    "backend/cli/market_policy_replay_research.py",
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


def replay(report, history_path, arm_name: str) -> tuple[dict, dict[str, dict]]:
    """Return (manifest, {ticker: rows}) for the arm over the restricted panel."""
    restricted, mask = point_in_time.point_in_time(report, history_path)
    allocator = scorecard.ARMS[arm_name](restricted, mask)
    panel = restricted.panel
    dates = [str(d)[:10] for d in panel.dates]
    weights = np.zeros((len(dates), len(panel.tickers)))
    for t in range(len(dates)):
        weights[t] = allocator(restricted, panel, None, t)
    stocks: dict[str, dict] = {}
    for column, ticker in enumerate(panel.tickers):
        if ticker in universe.MARKET_INDICES:
            continue
        path = weights[:, column]
        rows, trades = [], []
        previous = 0.0
        for t, day in enumerate(dates):
            weight = float(path[t])
            grade = restricted.graded.letter(t, column)
            if abs(weight - previous) >= DUST or t == 0:
                rows.append({"date": day, "weight": weight, "grade": grade})
            delta = weight - previous
            # The target set at this close trades at the next session's open.
            if abs(delta) >= DUST and t + 1 < len(dates):
                trades.append(
                    {
                        "decided": day,
                        "date": dates[t + 1],
                        "action": "BUY" if delta > 0 else "SELL",
                        "size": abs(delta),
                        "target": weight,
                    }
                )
            previous = weight
        stocks[ticker] = {
            "ticker": ticker,
            "rows": rows,
            "trades": trades,
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
        "start": dates[0],
        "through": dates[-1],
        "sessions": len(dates),
        "stocks": sorted(stocks),
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": _sources(),
        "membership": str(history_path),
        "note": (
            "In-sample research: the installed rule run over today's names as "
            "they were known at each date, targets before costs and fills, "
            "trades at the next open. Not audited accounting, not advice that "
            "was ever published."
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
    report = desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))
    history = args.membership or universe.MEMBERSHIP_HISTORY_PATH
    manifest, stocks = replay(report, history, arm_name)
    folder = write(root, args.policy, manifest, stocks)
    trades = sum(len(value["trades"]) for value in stocks.values())
    print(
        f"{folder}: {len(stocks)} names, {manifest['sessions']} sessions, "
        f"{trades} trades"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
