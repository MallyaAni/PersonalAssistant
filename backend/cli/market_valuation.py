"""The second valuation analyst, measured: trailing quarters, own history, peers.

    python -m backend.cli.market_valuation
    python -m backend.cli.market_valuation --book

The claim
---------
The valuation analyst scores one multiple, price to sales, with the
latest quarter times four as the sales figure and the side of the book
as the peer group. A review named that a screening signal rather than
an answer to "is this business attractive at this price". This builds
the better inputs and measures whether they earn anything.

The inputs, all point in time
-----------------------------
  revenue, earnings   the trailing four filed quarters, consecutive by
                      construction (`levels_pit.ttm_series`)
  revenue growth      year over year of the trailing sum
  peers               the sub-industry when it has three names in the
                      panel, else the side of the book
  own history         where today's multiple sits in the name's own
                      three years of readings

The legs, each a cheapness known at the close
---------------------------------------------
  cheap_vs_side       trailing P/S against the side, size-neutral (the
                      current analyst, on trailing sales)
  cheap_vs_peers      trailing P/S against the sub-industry peers
  cheap_vs_history    the multiple against the name's own three years
  cheap_earnings      trailing P/E against the side, absent for losses
  cheap_for_growth    growth-adjusted P/S against the side

The measurement
---------------
Each leg's rank IC against the beta-adjusted twenty- and sixty-session
residual on the book, with the t statistic over non-overlapping
periods, and by year; then the blends. Then `--book`: the desk regraded
with the second analyst in place of the first and run under its own
rules from 2021-06 against the rule, which is the test that counts.
`--walk-forward` picks, each year, the leg that led on the years before
it, which is the choice a person could have made.

Results, 2026-09-08
-------------------
Book of 93 names, 2015 to 2026, trailing revenue known on 60% of cells
(the store's history starts in 2015 and four quarters must be filed).
Rank IC against the beta-adjusted residual:

| leg                              | 20 sessions      | 60 sessions      |
| current analyst (P/S, quarter x4)| +0.038 (t 2.6)   | +0.054 (t 2.1)   |
| trailing P/S vs the side         | +0.031 (t 2.1)   | +0.051 (t 2.0)   |
| trailing P/S vs sub-industry     | +0.027 (t 1.9)   | +0.048 (t 2.0)   |
| the multiple vs its own history  | -0.000 (t 0.0)   | -0.010 (t -0.3)  |
| trailing P/E vs the side         | +0.029 (t 2.0)   | +0.037 (t 1.6)   |
| growth-adjusted trailing P/S     | +0.049 (t 3.7)   | +0.087 (t 4.2)   |
| all five blended                 | +0.030 (t 1.9)   | +0.063 (t 2.2)   |

Own history is worth nothing: where a name sits against its own three
years does not say where it goes. Finer peers are no better than the
side. The trailing sum smooths away information the latest quarter
carries (0.031 against 0.038). The growth-adjusted trailing multiple is
the best leg by a distance in sample, positive in ten of eleven years.

Chosen with hindsight, that is development evidence. Walk-forward, the
leg that led on the prior years (growth-adjusted in nine years of ten)
earned +0.037 a year against the current analyst's +0.034: a wash. The
book from 2021-06 with the growth-adjusted trailing multiple in place
of the current analyst: +33.6% a year, Sharpe 1.83, worst drawdown
-20.8%, against the rule's +31.8%, 1.85, -19.0%; and the rule scaled
to the same volatility earns +33.9%. The extra return is extra risk.
The current analyst stands. What would change this is data the store
does not hold: cash flow by quarter (the filings carry it year to date),
debt and cash for enterprise value, and forward expectations, which
`market_expectations` builds from what is known.
"""

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import grading, simulate, value
from backend.market import valuation
from backend.market.harness import evaluate_scores
from backend.market.levels_pit import trailing_levels
from backend.market.store import MarketStore
from backend.market.universe import build_universe

HORIZONS = (20, 60)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument(
        "--book", action="store_true", help="run the book with the second analyst"
    )
    parser.add_argument("--book-since", default="2021-06-01")
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="each year, use the leg that led on the years before it",
    )
    parser.add_argument(
        "--legs",
        nargs="*",
        default=list(value.LEGS_V2),
        help="the legs blended into the second analyst's score",
    )
    return parser


# Mean IC, its t over the harness's non-overlapping periods, and the count.
def _ic(scores: np.ndarray, panel, horizon: int) -> tuple[float, float, int]:
    report = evaluate_scores(scores, panel, horizon, exclude=(panel.benchmark,))
    ics = report.defined_ics
    if len(ics) < 3:
        return float("nan"), float("nan"), len(ics)
    return (
        float(ics.mean()),
        float(ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))),
        len(ics),
    )


def _line(name: str, scores: np.ndarray, panel) -> None:
    parts = []
    for h in HORIZONS:
        m, t, n = _ic(scores, panel, h)
        parts.append(f"{m:+7.3f} (t {t:5.1f}, {n:3d} periods)")
    print(f"{name:34} " + "  ".join(parts))


def _by_year(name: str, scores: np.ndarray, panel) -> None:
    years = np.array([str(d)[:4] for d in panel.dates])
    print(f"  {name}, twenty sessions by year:")
    line = []
    for y in sorted(set(years)):
        rows = years == y
        if rows.sum() < 60:
            continue
        sub = replace(
            panel,
            dates=panel.dates[rows],
            open=panel.open[rows],
            high=panel.high[rows],
            low=panel.low[rows],
            close=panel.close[rows],
            adj_close=panel.adj_close[rows],
            volume=panel.volume[rows],
        )
        m, _t, n = _ic(scores[rows], sub, 20)
        line.append(f"{y} {m:+.3f}")
    print("    " + "  ".join(line))


# Yearly rank IC of one score, twenty sessions, as {year: ic}.
def _yearly(scores: np.ndarray, panel) -> dict[str, float]:
    years = np.array([str(d)[:4] for d in panel.dates])
    out = {}
    for y in sorted(set(years)):
        rows = years == y
        if rows.sum() < 60:
            continue
        sub = replace(
            panel,
            dates=panel.dates[rows],
            open=panel.open[rows],
            high=panel.high[rows],
            low=panel.low[rows],
            close=panel.close[rows],
            adj_close=panel.adj_close[rows],
            volume=panel.volume[rows],
        )
        m, _t, _n = _ic(scores[rows], sub, 20)
        if np.isfinite(m):
            out[y] = m
    return out


# The choice a person could have made: each year, the leg with the best
# mean IC over the years before it. The leg picked with hindsight over the
# whole sample is development evidence; this is the test.
def _walk_forward(candidates: dict[str, np.ndarray], panel) -> None:
    yearly = {name: _yearly(scores, panel) for name, scores in candidates.items()}
    years = sorted(set().union(*[set(v) for v in yearly.values()]))
    print("\nwalk-forward choice of leg, twenty-session IC by year:")
    chosen_total, current_total = [], []
    for y in years[2:]:
        history = {
            name: np.mean([ic for yy, ic in ics.items() if yy < y])
            for name, ics in yearly.items()
            if any(yy < y for yy in ics)
        }
        if not history:
            continue
        best = max(history, key=history.get)
        got = yearly[best].get(y, float("nan"))
        base = yearly["current analyst"].get(y, float("nan"))
        if np.isfinite(got) and np.isfinite(base):
            chosen_total.append(got)
            current_total.append(base)
        print(f"  {y}: chose {best:18} {got:+.3f}   current analyst {base:+.3f}")
    if chosen_total:
        print(
            f"  mean over {len(chosen_total)} years: "
            f"chosen {np.mean(chosen_total):+.3f}, "
            f"current {np.mean(current_total):+.3f}"
        )


def main() -> None:
    """Run the study."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.root))
    report = trading_desk.run(store)
    panel, sides = report.panel, report.sides
    universe = build_universe()
    sub_industry = {
        m.ticker: m.sector_detail if hasattr(m, "sector_detail") else m.sub_industry
        for m in universe
    }
    groups = valuation.fine_groups(panel, sides, sub_industry)
    trailing = trailing_levels(store, panel)
    known = np.isfinite(trailing["revenue"]).mean()
    print(
        f"book of {len(sides)} names, {str(panel.dates[0])[:10]} "
        f"to {str(panel.dates[-1])[:10]}; "
        f"trailing revenue known on {known:.0%} of cells; "
        f"{len(set(groups))} peer groups"
    )
    v2_all = value.opine_v2(panel, trailing, sides, groups, legs=tuple(value.LEGS_V2))
    v1 = report.opinions["value"]
    print(
        f"\n{'rank IC, beta-adjusted residual':34} "
        f"{'20 sessions':>28}  {'60 sessions':>28}"
    )
    _line("current analyst (P/S, quarter x4)", v1.scores, panel)
    for leg in value.LEGS_V2:
        _line(leg, v2_all.evidence[leg], panel)
    chosen = tuple(args.legs)
    v2 = value.opine_v2(panel, trailing, sides, groups, legs=chosen)
    _line("blend: " + " + ".join(chosen), v2.scores, panel)
    _by_year("current analyst", v1.scores, panel)
    _by_year("blend", v2.scores, panel)
    if args.walk_forward:
        candidates = {"current analyst": v1.scores}
        candidates.update({leg: v2_all.evidence[leg] for leg in value.LEGS_V2})
        _walk_forward(candidates, panel)
    if not args.book:
        return
    opinions = dict(report.opinions)
    opinions["value"] = v2
    graded = grading.grade(
        opinions["fundamental"],
        opinions["technical"],
        opinions["sentiment"],
        report.regime.rotation,
        opinions["value"],
        grading.ANALYST_WEIGHTS,
    )
    adjusted = replace(
        report,
        opinions=opinions,
        graded=graded,
        scores=graded.as_scores(trading_desk.blended(opinions)),
    )
    start = date.fromisoformat(args.book_since)
    print(
        f"\nthe book from {args.book_since}: {'annual':>8} {'vol':>7} "
        f"{'Sharpe':>7} {'maxDD':>8} {'total':>9}"
    )
    results = {}
    for name, rep_ in (
        ("the rule (current analyst)", report),
        ("the second analyst", adjusted),
    ):
        stats = simulate.run(rep_, since=start, use_exits=False).stats()
        results[name] = stats
        print(
            f"{name:34} {stats['annual']:+8.1%} {stats['volatility']:7.1%} "
            f"{stats['sharpe']:7.2f} {stats['drawdown']:8.1%} {stats['total']:+9.1%}"
        )
    # The objective is compounded money at a risk the person accepts, so
    # the rule is also shown scaled to the second analyst's volatility.
    rule, second = results["the rule (current analyst)"], results["the second analyst"]
    if rule["volatility"] > 0:
        scale = second["volatility"] / rule["volatility"]
        print(
            f"{'the rule at the same volatility':34} {rule['annual'] * scale:+8.1%} "
            f"{second['volatility']:7.1%} {rule['sharpe']:7.2f} {rule['drawdown'] * scale:8.1%}"
        )


if __name__ == "__main__":
    main()
