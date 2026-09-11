"""The scorecard: the rule and its challengers on the objective.

    python -m backend.cli.market_scorecard             # history, rule vs challenger
    python -m backend.cli.market_scorecard --records   # the records, priced forward

The objective is compounded money after costs within a loss the person
accepts, against SPY and QQQ. `--records` is the forward test the
review asked for: every nightly record carries the rule's book and,
since 2026-09-08, the challenger's; this prices both from each record's
close to the next record's close with the store's bars, so the two
tracks are judged on the same real days with the same assumptions, and
nothing about the history can flatter either. The walk sizes each book
with the shared planner at the record's close and fills at the next
open, exactly as the desk's own simulator does, so a gap changes the
fill price and never the size of the decision.

The history, 2026-09-08, from 2018-06 with costs
------------------------------------------------
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
from backend.agents.trading.desk import planner, scorecard, simulate
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
# the cadence and the costs made real, not the whole rule. The book is
# shares and cash, sized by the shared planner at the close and filled at
# the next open, exactly as the desk's own simulator runs, so the two
# tracks are judged on the same real days with the same sizing.
# Which strategy a record's live book is, and which its shadow is. Records
# written before the rule carried a name are the plain rule with the
# expectations-gap shadow, which is what they were.
def _live_name(rec: dict) -> str:
    return str(
        ((rec.get("provenance") or {}).get("rule") or {}).get("name")
        or challenger.PLAIN
    )


def _shadow_name(rec: dict) -> str | None:
    block = rec.get("challenger")
    if not isinstance(block, dict):
        return None
    return str(block.get("name") or challenger.NAME)


# The rows a record decided for `name`, or None when it made no decision
# for that strategy that night.
def _book_for(rec: dict, name: str) -> list[dict] | None:
    if _live_name(rec) == name:
        return rec.get("book", [])
    if _shadow_name(rec) == name:
        return (rec.get("challenger") or {}).get("book", [])
    return None


def _forward_walk(
    records: list[dict],
    closes: dict[str, dict[str, float]],
    opens: dict[str, dict[str, float]],
    book_key: str,
) -> tuple[list[float], list[float], float]:
    """Return (close-to-close returns, fraction invested, notional traded).

    `book_key` is a strategy name (see `_book_for`); the two legacy keys
    "book" and "challenger" still mean the record's live and shadow rows.
    """
    held: dict[str, float] = {}  # ticker -> shares
    cash = 1.0
    values: list[float] = [1.0]
    out: list[float] = []
    invested_out: list[float] = []
    traded = 0.0
    for i, rec in enumerate(records[:-1]):
        a = rec["session"]
        b = records[i + 1]["session"]
        # A missing challenger block is no decision at all; an empty book is
        # a real one (hold nothing), and both are walks that carry forward.
        if book_key == "challenger":
            block = rec.get("challenger")
            known = isinstance(block, dict)
            rows = block.get("book", []) if known else []
        elif book_key == "book":
            known = True
            rows = rec.get("book", [])
        else:
            decided = _book_for(rec, book_key)
            known = decided is not None
            rows = decided or []
        # A rebalance is decided at `a`'s close - the weights, equity and
        # prices the decision could see - and filled at `b`'s open; a record
        # with no decision holds what it has and earns or loses the market.
        if known and (i == 0 or i % REBALANCE == 0):
            equity_close = cash + sum(
                held[t] * ca
                for t, ca in ((t, closes.get(t, {}).get(a)) for t in held)
                if ca and ca > 0
            )
            prices = {t: ca for t, d in closes.items() if (ca := d.get(a)) and ca > 0}
            targets = {row["ticker"]: float(row["weight"]) for row in rows}
            for o in planner.plan(targets, held, equity_close, prices):
                ob = opens.get(o.symbol, {}).get(b)
                if not ob or ob <= 0:
                    continue
                notional = o.qty * ob
                traded += notional
                cost = notional * (COST_BPS / 1e4)
                if o.side == "buy":
                    cash -= notional + cost
                    held[o.symbol] = held.get(o.symbol, 0.0) + o.qty
                else:
                    cash += notional - cost
                    held[o.symbol] = held.get(o.symbol, 0.0) - o.qty
                    if held[o.symbol] <= 1e-12:
                        del held[o.symbol]
        # Carry the book to `b`'s close; the return is always the real one,
        # even across a record with no decision, because the book is held.
        equity = cash + sum(
            held[t] * cb
            for t, cb in ((t, closes.get(t, {}).get(b)) for t in held)
            if cb and cb > 0
        )
        values.append(equity)
        out.append(values[-1] / values[-2] - 1.0)
        invested_out.append((equity - cash) / equity if equity > 0 else float("nan"))
    return out, invested_out, traded


# Every strategy the records carry, the latest live one first.
def _track_names(records: list[dict]) -> list[str]:
    names = [_live_name(records[-1])]
    for rec in records:
        for name in (_live_name(rec), _shadow_name(rec)):
            if name and name not in names:
                names.append(name)
    return names


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
        close = np.asarray([float(v) for v in cols[close_col]])
        raw_open = np.asarray([float(v) for v in cols["open"]])
        raw_close = np.asarray([float(v) for v in cols["close"]])
        # The open on the same basis as the adjusted close, so a return from
        # one to the other never straddles a split or a dividend; this is the
        # simulator's adjusted_open, and it is why a flat price cannot book a
        # fake move across an ex-date.
        with np.errstate(all="ignore"):
            factor = np.where(raw_close > 0, close / raw_close, np.nan)
        closes[ticker] = dict(zip(stamps, close.tolist(), strict=True))
        opens[ticker] = dict(
            zip(
                stamps,
                (raw_open * factor).tolist(),
                strict=True,
            )
        )
    # One track per strategy, the live one first (it sets the volatility
    # the others are matched to), so the swap of 2026-09-10 - the gap
    # promoted, the plain rule made the shadow - leaves both series whole.
    tracks = {
        name: _forward_walk(records, closes, opens, name)
        for name in _track_names(records)
    }
    out = {}
    for name, (daily, invested, traded) in tracks.items():
        arr = np.array(daily, dtype=float)
        if not np.isfinite(arr).any():
            continue
        # Returns are the real held-book returns, always finite, so the
        # equity compounds the actual days rather than a NaN treated as flat.
        equity = 100.0 * np.cumprod(1.0 + arr)
        out[name] = SimResult(
            dates=np.array(
                [np.datetime64(records[i + 1]["session"]) for i in range(len(daily))]
            ),
            returns=arr,
            invested=np.array(invested, dtype=float),
            equity=equity,
            traded=traded,
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
    start = date.fromisoformat(args.since)
    results = {
        f"the rule: {challenger.strategy(report)}": simulate.run(
            report, since=start, use_exits=False
        )
    }
    shadow = getattr(report, "alternate", None)
    if shadow is not None:
        results[f"shadow: {challenger.strategy(shadow)}"] = simulate.run(
            shadow, since=start, use_exits=False
        )
    print(f"the book from {args.since}, full rules, costs included:")
    print(scorecard.render(results, store, args.loss_limit))


if __name__ == "__main__":
    main()
