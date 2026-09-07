"""Buy the dip in a name the desk already rates: does it improve the book?

    python -m backend.cli.market_dipadd
    python -m backend.cli.market_dipadd --add 0.02 0.03 0.05 --fall 0.08 --vs-book 0.05

The question
------------
Dips in general have no edge in this book, measured every way today.
Dips in a name the desk rates A or A+ that day are different: a fall of
8% or more within three sessions, five points worse than the book's own
move, bought at that close, earned +1.23% beta-adjusted over ten sessions
against +0.64% for an A name on an ordinary day (1,090 events). Waiting
two sessions for the low to hold gave it all back.

An event return is not a book return. The rule has to act between
rebalances, fill at the next open, pay the cost, sit inside the name
cap, and earn its keep in the desk's own full-rule simulation. That is
what this runs: the book as it stands, then the book with the dip rule
at each add size, from 2021-06-01, with everything else unchanged.

Results
-------
Recorded below once the run is read.
"""

import argparse
from datetime import date

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import simulate
from backend.market.store import MarketStore


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="The dip-add rule in the book.")
    parser.add_argument("--add", type=float, nargs="+", default=[0.02, 0.03, 0.05])
    parser.add_argument("--fall", type=float, default=0.08)
    parser.add_argument("--vs-book", type=float, default=0.05)
    parser.add_argument("--since", type=date.fromisoformat, default=date(2021, 6, 1))
    parser.add_argument("--data-dir", default="data/market")
    return parser


def _line(name: str, result) -> None:
    s = result.stats()
    print(
        f"{name:34} {s['annual']:+8.1%} {s['volatility']:7.1%} {s['sharpe']:7.2f} "
        f"{s['drawdown']:8.1%} {s['total']:+9.1%} {result.dip_adds:6d}"
    )


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(args.data_dir))
    print(
        f"\n{'the book from ' + str(args.since):34} {'annual':>8} {'vol':>7} "
        f"{'Sharpe':>7} {'maxDD':>8} {'total':>9} {'adds':>6}"
    )
    _line("the desk's rule", simulate.run(report, since=args.since, use_exits=False))
    for add in args.add:
        rule = simulate.DipRule(fall=args.fall, vs_book=args.vs_book, add=add)
        result = simulate.run(report, since=args.since, use_exits=False, dip=rule)
        _line(f"with the dip add, {add:.0%} of equity", result)
    for add in args.add:
        rule = simulate.DipRule(
            fall=args.fall, vs_book=args.vs_book, add=add, funded=True
        )
        result = simulate.run(report, since=args.since, use_exits=False, dip=rule)
        _line(f"funded dip add, {add:.0%}, gross unchanged", result)
    loose = simulate.DipRule(
        fall=args.fall, vs_book=args.vs_book, add=0.03, min_grade="B"
    )
    loose_result = simulate.run(report, since=args.since, use_exits=False, dip=loose)
    _line("dip add at 3%, B names too", loose_result)


if __name__ == "__main__":
    main()
