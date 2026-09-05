"""Measure the baselines on the stored snapshot.

    python -m backend.cli.market_baselines
    python -m backend.cli.market_baselines --horizon 20 --cost-bps 15 --asof 2026-09-04

Prints, per baseline, the walk-forward rank IC (mean, t-stat, hit rate) and
the equal-weight long-short book's net return, Sharpe and total cost over
every non-overlapping period, then where each focus name ranks today under
each baseline. These are the numbers a learned model must beat.
"""

import argparse
import math
from datetime import date
from pathlib import Path

from backend.config.settings import settings
from backend.market import baselines
from backend.market.harness import evaluate_scores
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    BENCHMARK,
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    build_universe,
    theme_map,
    tickers_with_role,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the baseline report."""
    parser = argparse.ArgumentParser(
        description="Measure the baselines on the stored snapshot."
    )
    parser.add_argument(
        "--horizon", type=int, default=10, help="Sessions per holding period."
    )
    parser.add_argument(
        "--cost-bps", type=float, default=10.0, help="Cost per unit of weight traded."
    )
    parser.add_argument(
        "--top-fraction", type=float, default=0.2, help="Fraction long and short."
    )
    parser.add_argument(
        "--asof", type=date.fromisoformat, default=None, help="Store partition to read."
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="First session in the panel.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(settings.MARKET_DATA_ROOT),
        help="Store root.",
    )
    return parser


# A number for a fixed-width table, or a dash when it is not defined.
def _fmt(value: float, width: int = 8, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-".rjust(width)
    return f"{value:{width}.{digits}f}"


# Run the report.
def main() -> None:
    """Entry point: build the panel, score every baseline, print the report."""
    args = build_parser().parse_args()
    universe = build_universe()
    learn = tickers_with_role(universe, FOCUS, MEMBER)
    themes = {t: tags for t, tags in theme_map(universe).items() if t in set(learn)}
    store = MarketStore(args.data_dir)
    panel = build_panel(
        store, learn, MARKET_BENCHMARK, themes, asof=args.asof, start=args.start
    )
    missing = sorted(set(learn) - set(panel.tickers))
    print(
        f"panel: {len(panel.dates)} sessions {panel.dates[0]}..{panel.dates[-1]}, "
        f"{len(panel.tickers)} tickers ({len(missing)} of the universe not in store)"
    )
    print(
        f"{'baseline':28} {'periods':>7} {'IC':>8} {'t':>8} {'hit':>8} "
        f"{'net/prd':>8} {'sharpe':>8} {'cost':>8}"
    )
    scores = baselines.all_baselines(panel)
    for name, matrix in scores.items():
        report = evaluate_scores(
            matrix,
            panel,
            args.horizon,
            cost_bps=args.cost_bps,
            top_fraction=args.top_fraction,
        )
        print(
            f"{name:28} {report.count:7d} {_fmt(report.mean_ic)} "
            f"{_fmt(report.ic_tstat, digits=2)} "
            f"{_fmt(report.ic_hit_rate)} {_fmt(report.mean_net_return, digits=4)} "
            f"{_fmt(report.net_sharpe, digits=2)} {_fmt(report.total_cost, digits=4)}"
        )
    focus = [t for t in tickers_with_role(universe, FOCUS) if t in panel.tickers]
    if focus:
        print(f"\nfocus names on {panel.dates[-1]} (percentile rank, 1 = strongest):")
        last = len(panel.dates) - 1
        for name, matrix in scores.items():
            ranks = baselines.percentile_rank(matrix[last : last + 1])[0]
            cells = "  ".join(
                f"{t}={_fmt(ranks[panel.index(t)], width=5, digits=2)}" for t in focus
            )
            print(f"  {name:28} {cells}")
    excluded = tickers_with_role(universe, BENCHMARK)
    if any(t in panel.tickers for t in excluded):
        print("note: benchmark ETFs are in the panel only as references, never ranked")


if __name__ == "__main__":
    main()
