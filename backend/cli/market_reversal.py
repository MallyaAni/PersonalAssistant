"""The post-decision reversal experiment: backtest once, or advance the shadow.

    python -m backend.cli.market_reversal --backtest --report OUT.json
    python -m backend.cli.market_reversal --shadow

Registered in docs/research/post-decision-reversal-2026-09-15.md. Trades nothing.
"""

import argparse
import json
from pathlib import Path

from backend.market import reversal
from backend.market.calendar import fomc_decisions
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import book_sides, build_universe


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data/market")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--any-day", action="store_true", help="the any-day form")
    parser.add_argument("--shadow", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    return parser


# The book's panel from the store, SPY as the benchmark.
def book_panel(store: MarketStore):
    """Return (panel, members)."""
    members = set(book_sides(build_universe()))
    return build_panel(store, sorted(members), "SPY", {}), members


def main() -> None:
    """Run the experiment."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.data_dir))
    panel, members = book_panel(store)
    if args.backtest:
        if args.any_day:
            result = reversal.backtest_any_day(panel, members)
            rows = result["episodes"]
        else:
            result = reversal.backtest(panel, fomc_decisions(), members)
            rows = result["meetings"]
        print(
            f"{'decision':10} {'deep':4} {'into':>7} {'raw':>7} {'adj':>7} "
            f"{'net30':>7} {'pos':>5}  names"
        )
        for r in rows:
            print(
                f"{r['decision']:10} {'yes' if r['deep'] else 'no':4} "
                f"{100 * r['into_mean']:+6.1f}% {100 * r['basket_raw']:+6.1f}% "
                f"{100 * r['adjusted']:+6.1f}% {100 * r['after_costs']['30']:+6.1f}% "
                f"{100 * r['share_positive']:4.0f}%  {' '.join(r['names'][:6])}"
            )
        v = result["verdict"]
        for label in ("all_meetings", "deep", "not_deep"):
            s = v[label]
            mean = f"{100 * s['mean']:+.2f}%" if s["mean"] is not None else "—"
            t = f"{s['t']:+.2f}" if s["t"] is not None else "—"
            pos = (
                f"{100 * s['share_positive']:.0f}%"
                if s["share_positive"] is not None
                else "—"
            )
            print(f"{label:13} n={s['n']:2} mean {mean} t {t} positive {pos}")
        print("standing:", v["standing"])
        if args.report:
            args.report.write_text(json.dumps(result, indent=1), encoding="utf-8")
            print("report written:", args.report)
    if args.shadow:
        reversal.write_both(Path(store.root), panel, fomc_decisions(), members)


if __name__ == "__main__":
    main()
