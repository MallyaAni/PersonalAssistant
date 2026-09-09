"""The scorecard: the rule and its challengers on the objective.

    python -m backend.cli.market_scorecard             # history, rule vs challenger
    python -m backend.cli.market_scorecard --records   # the records, priced forward

The objective is compounded money after costs within a loss the person
accepts, against SPY and QQQ. `--records` is the forward test the
review asked for: every nightly record carries the rule's book and,
since 2026-09-08, the challenger's; this prices both from each record's
close to the next record's close with the store's bars, so the two
tracks are judged on the same real days with the same assumptions, and
nothing about the history can flatter either.

The history, 2026-09-08, from 2018-06 with costs
-------------------------------------------------
| candidate        | CAGR   | at rule vol | vol   | Sharpe | worst DD | turns | top |
| the rule         | +25.2% | +25.2%      | 16.3% | 1.46   | -23.4%   | 5.8x  | 19% |
| expectations-gap | +30.3% | +27.5%      | 18.0% | 1.56   | -24.6%   | 5.6x  | 23% |

The challenger beats the rule in seven of nine years; the rule beats
SPY in seven of nine and QQQ in five of nine. Both are within the 25%
loss limit. The challenger's extra return survives matching the rule's
volatility (+2.3 points a year) and costs nothing in turnover; its
largest position runs higher. Development evidence until the records
say the same; the forward track started with the 2026-09-09 record.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import scorecard, simulate
from backend.agents.trading.desk.simulate import SimResult
from backend.market import challenger, deskrecord
from backend.market.store import MarketStore


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--since", default="2021-06-01")
    parser.add_argument("--loss-limit", type=float, default=0.25)
    parser.add_argument(
        "--records", action="store_true", help="price the nightly records forward"
    )
    return parser


# The desk's rebalance cadence and costs, from simulate.py.
REBALANCE = 20
COST_BPS = 10.0
MIN_TRADE = 0.005


# Walk the records as the strategy would actually have run: persistent
# holdings, decisions made at a record's close and filled at the next
# record's open, the desk's rebalance cadence, and its cost on the notional
# traded. The old forward track re-priced each night's book from cash and
# charged nothing, which is not the strategy: the desk holds what it decided
# until the next rebalance, and every fill costs. The walk does no dip-adds
# and applies no exit analyst - the records do not carry either - so it is
# the cadence and the costs made real, not the whole rule.
def _forward_walk(
    records: list[dict],
    closes: dict[str, dict[str, float]],
    opens: dict[str, dict[str, float]],
    book_key: str,
) -> tuple[list[float], list[float]]:
    """Return (close-to-close returns, fraction invested) on the records."""
    held: dict[str, float] = {}  # ticker -> value, in units of the $1 start
    cash = 1.0
    values: list[float] = [1.0]
    out: list[float] = []
    invested_out: list[float] = []
    for i, rec in enumerate(records[:-1]):
        a = rec["session"]
        b = records[i + 1]["session"]
        # A missing challenger block is no decision at all; an empty book is
        # a real one (hold nothing), and both are walks that carry forward.
        if book_key == "challenger":
            block = rec.get("challenger")
            known = isinstance(block, dict)
            rows = block.get("book", []) if known else []
        else:
            known = True
            rows = rec.get("book", [])
        target = {row["ticker"]: float(row["weight"]) for row in rows}
        # Mark the held book to the next session's open, while it is still
        # the old book: the decision was taken at `a`'s close.
        value_open = cash
        for ticker, dollars in held.items():
            ca, ob = closes.get(ticker, {}).get(a), opens.get(ticker, {}).get(b)
            if ca and ca > 0 and ob:
                held[ticker] = dollars * (ob / ca)
                value_open += held[ticker]
            else:
                value_open += dollars
        # A rebalance settles at `b`'s open, the desk's market-on-open fill.
        if known and (i == 0 or i % REBALANCE == 0):
            desired = {
                t: w * value_open
                for t, w in target.items()
                if t in opens and b in opens[t]
            }
            trades = {}
            for t in set(held) | set(desired):
                move = desired.get(t, 0.0) - held.get(t, 0.0)
                if abs(move) >= MIN_TRADE * value_open:
                    trades[t] = move
            notional = sum(abs(v) for v in trades.values())
            for t, move in trades.items():
                held[t] = held.get(t, 0.0) + move
            held = {t: v for t, v in held.items() if v > 1e-12}
            cash += -sum(trades.values()) - notional * (COST_BPS / 1e4)
        # Carry the book to `b`'s close.
        for ticker, dollars in held.items():
            ob, cb = opens.get(ticker, {}).get(b), closes.get(ticker, {}).get(b)
            if ob and ob > 0 and cb:
                held[ticker] = dollars * (cb / ob)
        values.append(cash + sum(held.values()))
        equity = values[-1]
        invested_out.append(
            sum(held.values()) / equity if equity > 0 else float("nan")
        )
        out.append(
            values[-1] / values[-2] - 1.0 if known else float("nan")
        )
    return out, invested_out


# The records' books walked forward: one daily-return series per track.
def from_records(root: Path, store) -> dict[str, SimResult]:
    """Return {track: SimResult} built from consecutive nightly records."""
    sessions = (
        sorted(deskrecord.sessions(root)) if hasattr(deskrecord, "sessions") else []
    )
    if not sessions:
        sessions = sorted(
            p.name.split("=", 1)[1] for p in (root / "desk").glob("asof=*")
        )
    records = []
    for session in sessions:
        path = root / "desk" / f"asof={session}" / "desk.json"
        if path.exists():
            records.append(json.loads(path.read_text(encoding="utf-8")))
    if len(records) < 2:
        return {}
    tickers = sorted(
        {r["ticker"] for rec in records for r in rec.get("book", [])}
        | {
            r["ticker"]
            for rec in records
            for r in (rec.get("challenger") or {}).get("book", [])
        }
    )
    closes: dict[str, dict[str, float]] = {}
    opens: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        frame = store.read_frame("bars", ticker)
        if frame is None:
            continue
        cols = frame[0]
        key = next(
            k
            for k in cols
            if k not in ("open", "high", "low", "close", "volume", "adj_close")
        )
        stamps = [str(d)[:10] for d in cols[key]]
        close_col = next(
            (c for c in ("adj_close", "adjusted_close") if c in cols),
            "close",
        )
        closes[ticker] = dict(zip(stamps, [float(v) for v in cols[close_col]], strict=True))
        opens[ticker] = dict(
            zip(
                stamps,
                [float(v) for v in cols["open"]],
                strict=True,
            )
        )
    tracks = {
        "the rule": _forward_walk(records, closes, opens, "book"),
        "challenger": _forward_walk(records, closes, opens, "challenger"),
    }
    out = {}
    for name, (daily, invested) in tracks.items():
        arr = np.array(daily, dtype=float)
        if not np.isfinite(arr).any():
            continue
        equity = 100.0 * np.cumprod(1.0 + np.nan_to_num(arr))
        out[name] = SimResult(
            dates=np.array(
                [np.datetime64(records[i + 1]["session"]) for i in range(len(daily))]
            ),
            returns=arr,
            invested=np.array(invested, dtype=float),
            equity=equity,
            traded=0.0,
            top_weight=np.full(len(arr), np.nan),
        )
    return out


def main() -> None:
    """Run the scorecard."""
    args = build_parser().parse_args()
    root = Path(args.root)
    store = MarketStore(root)
    if args.records:
        results = from_records(root, store)
        if not results:
            print("fewer than two records on file")
            return
        print("the nightly records priced forward, close to close:")
        print(scorecard.render(results, store, args.loss_limit))
        return
    report = trading_desk.run(store)
    gap = challenger.expectations_gap(store, report.panel)
    shadow = challenger.report_with_gap(report, gap)
    start = date.fromisoformat(args.since)
    results = {
        "the rule": simulate.run(report, since=start, use_exits=False),
        f"challenger: {challenger.NAME}": simulate.run(
            shadow, since=start, use_exits=False
        ),
    }
    print(f"the book from {args.since}, full rules, costs included:")
    print(scorecard.render(results, store, args.loss_limit))


if __name__ == "__main__":
    main()
