"""The book: size the best score, measure it, and say what to hold today.

    python -m backend.cli.market_book                 # fundamental blend
    python -m backend.cli.market_book --scores data/market/models/sweep_x.npz
    python -m backend.cli.market_book --target-vol 0.20 --name-cap 0.08 --theme-cap 0.35

Prints the simulated book (return, volatility, Sharpe, drawdown, turnover,
information ratio against the benchmark) for the chosen score, then the
positions the book would hold on the last session, the focus names first.
The default score is the fundamental rank blend from the EDGAR layer: the
only signal so far with positive net Sharpe through the harness.
"""

import argparse
from datetime import date
from pathlib import Path

import numpy as np

from backend.config.settings import settings
from backend.market import baselines, edgar, sizing
from backend.market.harness import evaluate_scores
from backend.market.model import load_edgar_features
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.technical import TECHNICAL_NAMES, technical_features
from backend.market.universe import (
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    build_universe,
    theme_map,
    tickers_with_role,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the book report."""
    parser = argparse.ArgumentParser(description="Size a score into a book.")
    parser.add_argument(
        "--scores", type=Path, default=None, help="An .npz of saved scores."
    )
    parser.add_argument(
        "--score",
        choices=("composite", "fundamental"),
        default="composite",
        help="composite = fundamentals + 52-week-low trend + 21-EMA fade",
    )
    parser.add_argument("--top-fraction", type=float, default=0.2)
    parser.add_argument("--short-fraction", type=float, default=0.0)
    parser.add_argument("--target-vol", type=float, default=0.15)
    parser.add_argument("--name-cap", type=float, default=0.10)
    parser.add_argument("--theme-cap", type=float, default=0.40)
    parser.add_argument("--rebalance-every", type=int, default=20)
    parser.add_argument("--speed", type=float, default=0.5)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    return parser


# The fundamental rank blend: revenue growth, sequential growth, gross
# margin and revenue acceleration, each ranked across names, averaged.
def fundamental_blend(extra: np.ndarray) -> np.ndarray:
    """Return the (T, N) fundamental blend score from EDGAR features."""
    names = edgar.FEATURE_NAMES
    has = extra[:, :, names.index("has_fundamentals")] > 0

    def column(feature: str) -> np.ndarray:
        return np.where(has, extra[:, :, names.index(feature)].astype(float), np.nan)

    return baselines.rank_blend(
        column("revenue_yoy"),
        column("revenue_qoq"),
        column("gross_margin"),
        column("revenue_acceleration"),
    )


# Slow momentum with fast reversion, from what has measured real: the
# fundamental blend, distance above the 52-week low (the long trend),
# and extension above the 21 EMA as a fade (the short reversal).
def composite_score(panel, extra: np.ndarray) -> np.ndarray:
    """Return the (T, N) composite: fundamentals, 52-week-low trend, 21-EMA fade."""
    feats = technical_features(panel)
    idx = {n: i for i, n in enumerate(TECHNICAL_NAMES)}
    low52 = feats[:, :, idx["low_52w_distance"]].astype(float)
    ext21 = feats[:, :, idx["ema21_distance"]].astype(float)
    return baselines.rank_blend(fundamental_blend(extra), low52, -ext21)


# Run the report.
def main() -> None:
    """Entry point: simulate the sized book and print today's positions."""
    args = build_parser().parse_args()
    universe = build_universe()
    learn = tickers_with_role(universe, FOCUS, MEMBER)
    themes = {t: tags for t, tags in theme_map(universe).items() if t in set(learn)}
    store = MarketStore(args.data_dir)
    panel = build_panel(
        store, learn, MARKET_BENCHMARK, themes, asof=args.asof, start=args.start
    )
    if args.scores:
        saved = np.load(args.scores, allow_pickle=True)
        if list(saved["tickers"]) != list(panel.tickers):
            raise SystemExit("saved scores were built on a different ticker set")
        scores = saved["scores"].astype(float)
        source = str(args.scores)
    else:
        extra = load_edgar_features(store, panel, args.asof)
        if extra is None:
            raise SystemExit("no EDGAR layer in the store; run market_edgar --refresh")
        if args.score == "composite":
            scores = composite_score(panel, extra)
            source = "composite: fundamentals + 52w-low trend + 21-EMA fade"
        else:
            scores = fundamental_blend(extra)
            source = "fundamental blend (EDGAR)"
    config = sizing.SizingConfig(
        top_fraction=args.top_fraction,
        short_fraction=args.short_fraction,
        target_volatility=args.target_vol,
        name_cap=args.name_cap,
        theme_cap=args.theme_cap,
        rebalance_every=args.rebalance_every,
        speed=args.speed,
        cost_bps=args.cost_bps,
    )
    harness = evaluate_scores(
        scores, panel, config.rebalance_every, cost_bps=args.cost_bps
    )
    book = sizing.simulate(scores, panel, config)
    print(f"score: {source}")
    print(
        f"harness: {harness.count} periods, rank IC {harness.mean_ic:.4f} "
        f"(t {harness.ic_tstat:.2f}), long-short net Sharpe {harness.net_sharpe:.2f}"
    )
    print(
        f"book: {book.rebalances} rebalances every {config.rebalance_every} sessions, "
        f"target vol {config.target_volatility:.0%}, name cap {config.name_cap:.0%}, "
        f"theme cap {config.theme_cap:.0%}, {config.cost_bps:.0f} bps"
    )
    print(
        f"  annual return {book.annual_return:7.2%}   "
        f"volatility {book.annual_volatility:6.2%}   "
        f"Sharpe {book.sharpe:5.2f}   max drawdown {book.max_drawdown:7.2%}"
    )
    print(
        f"  benchmark Sharpe {book.benchmark_sharpe:5.2f}   information ratio "
        f"{book.information_ratio:5.2f}   "
        f"mean turnover per rebalance {book.mean_turnover:5.1%}"
    )
    positions = sizing.size_today(scores[-1], panel, config)
    print(
        f"\npositions on {panel.dates[-1]} ({len(positions)} names, "
        f"gross {sum(abs(p.weight) for p in positions):.1%}):"
    )
    focus = set(tickers_with_role(universe, FOCUS))
    shown = [p for p in positions if p.ticker in focus] + [
        p for p in positions if p.ticker not in focus
    ][:15]
    for p in shown:
        tag = "*" if p.ticker in focus else " "
        print(
            f" {tag}{p.ticker:6} {p.weight:7.2%}  rank {p.score_rank:4.2f}  "
            f"vol {p.volatility:5.0%}  "
            f"{','.join(p.themes) or '-':28} {p.note}"
        )
    absent = [
        t
        for t in focus
        if t in panel.tickers and t not in {p.ticker for p in positions}
    ]
    if absent:
        ranks = baselines.percentile_rank(scores[-1:][:, :])[0]
        for t in absent:
            r = ranks[panel.index(t)]
            print(
                f" *{t:6}   0.00%  rank {r:4.2f}  not selected "
                f"(below the top {config.top_fraction:.0%})"
            )


if __name__ == "__main__":
    main()
