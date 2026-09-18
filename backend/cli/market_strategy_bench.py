"""Write the candidate-rule comparison the Research view reads.

    python -m backend.cli.market_strategy_bench

Runs the desk once, then prices each candidate trading rule and each index
over the same sessions, and writes the regime-split comparison beside the
nightly records. Read-only with respect to the desk: nothing here changes a
grade, a target or a trade, and no candidate but the shipped one is traded
anywhere.

The candidates are the ones measured on 2026-09-18:

  * `every 20`  what ships: the calendar rebalance.
  * `every 120 + tails`  the loose maintenance schedule with entries taken
    on price instead, funded from the other holdings rather than from cash.
    A name the desk grades A or better, sitting more than 15% from its
    21-day average in either direction.
"""

import argparse
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk, simulate
from backend.market import strategy_bench, technical
from backend.market.store import MarketStore
from backend.market.universe import MARKET_INDICES

A_OR_BETTER = 2
TAIL = 0.15


# The command line: where to read and write.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the comparison writer."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    return parser


# Each index's daily return aligned to the panel's sessions, where the store
# has it. An index the store has never fetched is skipped rather than faked.
def _index_series(panel, close: np.ndarray) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for symbol in MARKET_INDICES:
        if symbol not in panel.tickers:
            continue
        prices = close[:, panel.index(symbol)]
        daily = np.full(len(prices), np.nan)
        daily[1:] = prices[1:] / prices[:-1] - 1.0
        out[symbol] = daily
    return out


def main(argv: list[str] | None = None) -> int:
    """Write the comparison and report where it went."""
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    store = MarketStore(root)
    report = desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))
    panel = report.panel
    close = panel.adj_close
    grades = report.graded.grades.astype(float)

    e21 = technical.ema(close, 21)
    with np.errstate(all="ignore"):
        stretch = (close - e21) / e21
    tails = (np.abs(stretch) >= TAIL) & (grades >= A_OR_BETTER)

    first = panel.dates[0].astype("datetime64[D]").astype(object)
    candidates = {
        "Desk, every 20 (ships)": dict(rebalance=20),
        "Desk, 120 + price entries": dict(
            rebalance=120, dip=simulate.DipRule(signal=tails, funded=True)
        ),
    }
    series: dict[str, np.ndarray] = {}
    for label, options in candidates.items():
        series[label] = simulate.run(
            report, since=first, use_exits=False, **options
        ).returns
    series.update(_index_series(panel, close))

    payload = strategy_bench.build(
        panel.dates,
        series,
        note=(
            "Candidates priced over identical sessions. Only 'ships' is traded; "
            "the other is a measured alternative, not a live policy."
        ),
    )
    strategy_bench.save(root, payload)
    print(f"wrote {root / 'desk' / strategy_bench.FILE}")
    for block in payload["blocks"]:
        print(f"  {block['regime']:<18}{block['sessions']:>6} sessions")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
