"""Is the desk's edge on the book an artefact of choosing the book?

    python -m backend.cli.market_survivorship
    python -m backend.cli.market_survivorship --horizons 20 60 --split 2024-01-01

The question
------------
The ninety-three names were chosen in 2026, knowing what had happened to
them. Every measurement of the desk on those names therefore carries the
choice: a signal that ranks names well among survivors and winners might
rank a fair draw of names no better than chance. A review raised this and
nothing had measured it.

The measurement
---------------
The universe's ordinary members outside the book - over four hundred
names, no ETF or benchmark among them - are the control, on their own
price panel from the same store. What can be measured on them is what
needs prices only: the technical analyst, and plain momentum as the
simplest price signal. The fundamental, sentiment and value analysts
read filings, release tone and point-in-time levels, and none of those
are stored for a name outside the book; measuring them off the book
means fetching four hundred names' filings and scoring their releases,
which is a project, not a run. They are reported on the book only, so
the gap is visible rather than silent.

For each signal on each cell set, the harness's rank IC against the
beta-adjusted forward residual, its t, and the net Sharpe of the
long-short at cost; the same split in time before and after `--split`,
since a book chosen in 2026 is most flattered in the years just before
it. And the survivorship in levels: the equal-weight book against the
equal-weight control over the common sessions, which is how much the
choice of names alone was worth, before any signal.

What this cannot claim, written before the result: a lower IC outside
the book is not only survivorship. The book was chosen for being the
names these analysts are built to read, AI infrastructure and software,
and the technical analyst's trend context is the AI trend. The honest
comparison is the order of magnitude, not equality.

Results
-------
Recorded below once the run is read.
"""

import argparse
from datetime import date

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import technical
from backend.market import baselines
from backend.market.harness import evaluate_scores
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    MARKET_BENCHMARK,
    MEMBER,
    build_universe,
    theme_map,
    tickers_with_role,
)

COST_BPS = 10.0
MIN_NAMES = 15
FILING_ANALYSTS = ("fundamental", "sentiment", "value")
SESSIONS_PER_YEAR = 252.0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Measure the desk off the book.")
    parser.add_argument("--horizons", type=int, nargs="+", default=[20, 60])
    parser.add_argument("--split", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--data-dir", default="data/market")
    return parser


# Rank IC, its t, and net Sharpe of `scores` on the given rows of a panel.
def _measure(scores, rows, panel, horizon) -> tuple[float, float, float]:
    masked = scores if rows is None else np.where(rows[:, None], scores, np.nan)
    r = evaluate_scores(masked, panel, horizon, cost_bps=COST_BPS, min_names=MIN_NAMES)
    return r.mean_ic, r.ic_tstat, r.net_sharpe


# The book's AI trend carried onto another panel's dates, NaN where the
# other panel has a session the book does not.
def _aligned(series: np.ndarray, from_dates, to_dates) -> np.ndarray:
    lookup = dict(zip(from_dates.tolist(), series.tolist(), strict=True))
    return np.array([lookup.get(d, np.nan) for d in to_dates.tolist()])


# The signals that need prices only, on any panel.
def _price_signals(panel, ai_trend) -> dict[str, np.ndarray]:
    return {
        "technical analyst": technical.opine(panel, ai_trend).ranks(),
        "momentum 252/21": baselines.momentum(panel, 252, 21),
    }


# Equal-weight annual return, volatility and Sharpe of a panel's names,
# benchmark excluded, over the given rows.
def _levels(panel, rows) -> tuple[float, float, float]:
    simple = np.expm1(panel.log_returns())
    simple[:, panel.index(panel.benchmark)] = np.nan
    with np.errstate(all="ignore"):
        daily = np.nanmean(simple[rows], axis=1)
    daily = daily[np.isfinite(daily)]
    annual = float(daily.mean() * SESSIONS_PER_YEAR)
    vol = float(daily.std() * np.sqrt(SESSIONS_PER_YEAR))
    return annual, vol, annual / vol if vol > 0 else float("nan")


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    report = trading_desk.run(store)
    book_panel = report.panel
    universe = build_universe()
    control_tickers = tuple(
        sorted(t for t in tickers_with_role(universe, MEMBER) if t not in report.sides)
    )
    themes = {t: g for t, g in theme_map(universe).items() if t in control_tickers}
    control_panel = build_panel(store, control_tickers, MARKET_BENCHMARK, themes)
    ai_trend = _aligned(report.regime.ai_trend, book_panel.dates, control_panel.dates)
    signals = {
        "the book": _price_signals(book_panel, report.regime.ai_trend),
        "control": _price_signals(control_panel, ai_trend),
    }
    panels = {"the book": book_panel, "control": control_panel}
    common = np.intersect1d(book_panel.dates, control_panel.dates)
    print(
        f"{len(report.sides)} book names over {len(book_panel.dates)} sessions; "
        f"{len(control_tickers)} control names over {len(control_panel.dates)}; "
        f"{len(common)} sessions in common"
    )
    print(
        f"\n{'equal weight, common sessions':34} {'annual':>8} {'vol':>7} {'Sharpe':>7}"
    )
    for label, panel in panels.items():
        rows = np.isin(panel.dates, common)
        annual, vol, sharpe = _levels(panel, rows)
        print(f"{label:34} {annual:+8.1%} {vol:7.1%} {sharpe:7.2f}")

    for horizon in args.horizons:
        print(f"\n=== horizon {horizon} ===")
        print(f"{'signal':22} {'cells':>26} {'rank IC':>9} {'t':>7} {'net Sharpe':>11}")
        for name in ("technical analyst", "momentum 252/21"):
            for label, panel in panels.items():
                scores = signals[label][name]
                before = panel.dates < np.datetime64(args.split)
                for when, rows in (
                    ("", None),
                    (f", before {args.split}", before),
                    (f", from {args.split}", ~before),
                ):
                    ic, t, sh = _measure(scores, rows, panel, horizon)
                    cells = label + when
                    print(f"{name:22} {cells:>26} {ic:+9.4f} {t:+7.2f} {sh:+11.2f}")
        for name in FILING_ANALYSTS:
            scores = report.opinions[name].ranks()
            ic, t, sh = _measure(scores, None, book_panel, horizon)
            print(f"{name:22} {'the book':>26} {ic:+9.4f} {t:+7.2f} {sh:+11.2f}")
            print(f"{name:22} {'control':>26}   not measurable: no filings stored")


if __name__ == "__main__":
    main()
