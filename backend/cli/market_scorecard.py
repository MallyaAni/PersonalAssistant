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


# A book's return from one record's close to the next, at the record's
# weights held through the gap; cash earns nothing.
def _forward(book: list[dict], prices: dict[str, tuple[float, float]]) -> float:
    total = 0.0
    for row in book:
        pair = prices.get(row["ticker"])
        if pair is None or pair[0] <= 0:
            continue
        total += float(row["weight"]) * (pair[1] / pair[0] - 1.0)
    return total


# The records' books priced forward: one daily-return series per track.
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
        closes[ticker] = dict(
            zip(
                [str(d)[:10] for d in cols[key]],
                [
                    float(v)
                    for v in (
                        cols["adj_close"] if "adj_close" in cols else cols["close"]
                    )
                ],
                strict=True,
            )
        )
    tracks = {"the rule": [], "challenger": []}
    dates = []
    for earlier, later in zip(records, records[1:], strict=False):
        a, b = earlier["session"], later["session"]
        prices = {
            t: (closes[t][a], closes[t][b])
            for t in closes
            if a in closes[t] and b in closes[t]
        }
        dates.append(np.datetime64(b))
        tracks["the rule"].append(_forward(earlier.get("book", []), prices))
        block = earlier.get("challenger")
        tracks["challenger"].append(
            _forward(block["book"], prices) if block else float("nan")
        )
    out = {}
    for name, daily in tracks.items():
        arr = np.array(daily, dtype=float)
        if not np.isfinite(arr).any():
            continue
        equity = 100.0 * np.cumprod(1.0 + np.nan_to_num(arr))
        out[name] = SimResult(
            dates=np.array(dates),
            returns=arr,
            invested=np.ones(len(arr)),
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
