"""Where the money is going, by theme, from filings and from prices.

    python -m backend.cli.market_rotation
    python -m backend.cli.market_rotation --horizon 60

The question behind the whole system is which basket money is rotating
into — software, AI compute, memory, networking, power. This report
answers it two ways and puts them side by side. From filings: each theme's
median revenue growth, acceleration, capital-spending growth and gross
margin, as known today, and how those have moved over the last two
quarters. From prices: each theme basket's return over the last 20 and 60
sessions relative to the market. Then it measures whether theme-level
fundamentals predict theme-level returns at all, through the same harness,
by giving every member its theme's median fundamental blend as a score.
"""

import argparse
from datetime import date
from pathlib import Path

import numpy as np

from backend.cli.market_book import fundamental_blend
from backend.config.settings import settings
from backend.market import baselines, edgar
from backend.market.harness import evaluate_scores
from backend.market.model import load_edgar_features
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    THEMES,
    build_universe,
    theme_map,
    tickers_with_role,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the rotation report."""
    parser = argparse.ArgumentParser(
        description="Theme rotation from filings and prices."
    )
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    return parser


# The median of a feature across a theme's members with fundamentals, per
# session; NaN where fewer than three members have data.
def theme_median(values: np.ndarray, has: np.ndarray, members: list[int]) -> np.ndarray:
    """Return the (T,) median over `members` of `values`, NaN when thin."""
    block = np.where(has[:, members], values[:, members], np.nan)
    counts = np.isfinite(block).sum(axis=1)
    with np.errstate(all="ignore"):
        medians = np.nanmedian(np.where(counts[:, None] >= 3, block, np.nan), axis=1)
    return np.where(counts >= 3, medians, np.nan)


# Every member of a theme gets the theme's median blend as its score: a
# pure rotation signal built from filings rather than from prices.
def theme_fundamental_scores(panel, blend: np.ndarray) -> np.ndarray:
    """Return (T, N) scores: each name carries its primary theme's median blend."""
    out = np.full_like(blend, np.nan)
    by_theme: dict[str, list[int]] = {}
    for column, ticker in enumerate(panel.tickers):
        theme = panel.primary_theme(ticker)
        if theme:
            by_theme.setdefault(theme, []).append(column)
    has = np.isfinite(blend)
    for theme, members in by_theme.items():
        median = theme_median(blend, has, members)
        out[:, members] = median[:, None]
    return out


# Run the report.
def main() -> None:
    """Entry point: print the theme table and the rotation control."""
    args = build_parser().parse_args()
    universe = build_universe()
    learn = tickers_with_role(universe, FOCUS, MEMBER)
    themes = {t: tags for t, tags in theme_map(universe).items() if t in set(learn)}
    store = MarketStore(args.data_dir)
    panel = build_panel(store, learn, MARKET_BENCHMARK, themes, asof=args.asof)
    extra = load_edgar_features(store, panel, args.asof)
    if extra is None:
        raise SystemExit("no EDGAR layer in the store; run market_edgar --refresh")
    names = edgar.FEATURE_NAMES
    has = extra[:, :, names.index("has_fundamentals")] > 0
    last = len(panel.dates) - 1
    back = max(0, last - 126)  # roughly two quarters of sessions
    returns = panel.log_returns()
    bench = panel.benchmark_returns()
    rel20 = baselines.trailing_sum(returns, 20) - baselines.trailing_sum(
        bench[:, None], 20
    )
    rel60 = baselines.trailing_sum(returns, 60) - baselines.trailing_sum(
        bench[:, None], 60
    )

    print(f"as of {panel.dates[last]}; medians over members with fundamentals on file")
    print(
        f"{'theme':16} {'n':>3} {'rev yoy':>8} {'2q ago':>7} {'accel':>7} "
        f"{'capex yoy':>10} {'gross m':>8} {'rel 20d':>8} {'rel 60d':>8}"
    )
    for theme in THEMES:
        members = [
            c for c, t in enumerate(panel.tickers) if theme in panel.themes.get(t, ())
        ]
        if len(members) < 3:
            continue

        def med(feature: str, t: int = last) -> float:
            return float(
                theme_median(
                    extra[:, :, names.index(feature)].astype(float), has, members
                )[t]
            )

        r20 = float(np.nanmedian(rel20[last, members]))
        r60 = float(np.nanmedian(rel60[last, members]))
        print(
            f"{theme:16} {len(members):3d} {med('revenue_yoy'):8.3f} "
            f"{med('revenue_yoy', back):7.3f} {med('revenue_acceleration'):7.3f} "
            f"{med('capex_yoy'):10.3f} {med('gross_margin'):8.3f} {r20:8.3f} {r60:8.3f}"
        )

    blend = fundamental_blend(extra)
    rotation = theme_fundamental_scores(panel, blend)
    price_rotation = baselines.theme_momentum(panel, 20)
    print(
        f"\nrotation controls through the harness, horizon {args.horizon}, {args.cost_bps:.0f} bps:"
    )
    print(
        f"{'control':34} {'periods':>7} {'IC':>8} {'t':>7} {'hit':>6} "
        f"{'net Sharpe':>11}"
    )
    for label, scores in (
        ("theme median fundamental blend", rotation),
        ("theme price momentum 20", price_rotation),
        ("name-level fundamental blend", blend),
    ):
        r = evaluate_scores(
            scores, panel, args.horizon, cost_bps=args.cost_bps, min_names=15
        )
        print(
            f"{label:34} {r.count:7d} {r.mean_ic:8.4f} {r.ic_tstat:7.2f} "
            f"{r.ic_hit_rate:6.3f} {r.net_sharpe:11.2f}"
        )


if __name__ == "__main__":
    main()
