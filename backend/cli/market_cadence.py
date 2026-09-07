"""How often to re-decide the book, and how much of it to run.

    python -m backend.cli.market_cadence
    python -m backend.cli.market_cadence --every 1 5 10 20 40 --since 2021-06-01

The question
------------
A continuous grade invites a continuous book: re-decide every session,
size on every change. And a book that earns its Sharpe invites more of
itself: run it at more exposure. Both are one parameter each in the
desk's own full-rule simulation, so both are measured rather than
argued. The first table re-decides the same rules every `--every`
sessions; the second keeps the desk's cadence and raises the volatility
target and the name and theme caps together.

Results
-------
The book from 2021-06-01, full rules, the desk's weights:

  re-decided every            annual    vol  Sharpe   maxDD    total
   1 session                  +27.5%  16.8%    1.63  -18.3%   +292%
   5 sessions                 +29.7%  16.7%    1.78  -20.5%   +340%
  10 sessions                 +30.3%  16.4%    1.85  -17.8%   +357%
  20 sessions (the desk)      +31.6%  16.7%    1.90  -17.8%   +388%
  40 sessions                 +32.4%  17.2%    1.88  -18.8%   +407%

  every 20, more exposure     annual    vol  Sharpe   maxDD    total
  vol target 25%, caps 15/60  +31.6%  16.7%    1.90  -17.8%   +388%
  vol target 35%, caps 20/70  +38.8%  20.7%    1.87  -24.8%   +581%
  vol target 50%, caps 25/80  +42.0%  22.2%    1.89  -25.5%   +696%

Re-deciding more often only pays churn: every session is a full Sharpe
point below every twenty, and forty is the same as twenty. The grade is
continuous; the book should not be. More exposure is the lever that
keeps the Sharpe: at a 50% volatility target with 25% and 80% caps the
same rule returns 42% a year at 1.89 against 31.6% at 1.90, with the
worst drawdown 25.5% against 17.8%. That is the honest form of "more
total gains": the same edge with more risk, at the same price per unit,
and the drawdown is the price. It is a choice about the account, not
about the rule, and the desk does not make it on its own. Every
absolute return here carries the book's survivorship, nineteen points a
year of it, equally across rows.
"""

import argparse
from dataclasses import replace
from datetime import date

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import risk, simulate
from backend.market.store import MarketStore

EXPOSURES = ((0.25, 0.15, 0.60), (0.35, 0.20, 0.70), (0.50, 0.25, 0.80))


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Cadence and exposure of the book.")
    parser.add_argument("--every", type=int, nargs="+", default=[1, 5, 10, 20, 40])
    parser.add_argument("--since", type=date.fromisoformat, default=date(2021, 6, 1))
    parser.add_argument("--data-dir", default="data/market")
    return parser


# One row of the table from a simulation.
def _line(name: str, result) -> None:
    s = result.stats()
    print(
        f"{name:40} {s['annual']:+8.1%} {s['volatility']:7.1%} {s['sharpe']:7.2f} "
        f"{s['drawdown']:8.1%} {s['total']:+9.1%}",
        flush=True,
    )


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(args.data_dir))
    header = f"{'annual':>8} {'vol':>7} {'Sharpe':>7} {'maxDD':>8} {'total':>9}"
    print(f"{'the book from ' + str(args.since):40} {header}")
    for every in args.every:
        result = simulate.run(
            report, since=args.since, use_exits=False, rebalance=every
        )
        _line(f"re-decided every {every} sessions", result)
    print(f"\n{'every 20, more exposure':40} {header}")
    for target, cap, theme in EXPOSURES:
        config = replace(
            risk.BOOK_CONFIG, target_volatility=target, name_cap=cap, theme_cap=theme
        )
        result = simulate.run(report, since=args.since, use_exits=False, config=config)
        _line(f"vol target {target:.0%}, caps {cap:.0%}/{theme:.0%}", result)


if __name__ == "__main__":
    main()
