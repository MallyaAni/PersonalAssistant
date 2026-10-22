"""How good are the grades, and which analyst earns them: a point-in-time read.

    python -m backend.cli.market_grade_quality_research --root data/market

For every session and every name the point-in-time panel knew, the grade
and each analyst's stance as the desk set them that evening, against the
name's return over the next 20 and 60 sessions relative to QQQ. Nothing
after the session is read when the grade is set; the forward return is
read afterwards, which is the point. Reports, by year and over all:
the mean forward excess by grade letter, the spread A+/A against B/C,
and for each analyst the mean excess of the names it was bullish on
against bearish, with the share of sessions it had a view. Research
only: no file the desk serves is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk, grading, point_in_time
from backend.market import universe
from backend.market.store import MarketStore

HORIZONS = (20, 60)


def forward_excess(panel, horizon: int) -> np.ndarray:
    """Return (T, N) excess over the benchmark `horizon` sessions ahead."""
    closes = np.asarray(panel.adj_close, dtype=float)
    bench = closes[:, panel.index(panel.benchmark)]
    out = np.full(closes.shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        own = closes[horizon:] / closes[:-horizon] - 1.0
        base = bench[horizon:] / bench[:-horizon] - 1.0
    out[:-horizon] = own - base[:, None]
    return out


def _stats(values: np.ndarray) -> dict:
    values = values[np.isfinite(values)]
    if not len(values):
        return {"n": 0}
    return {
        "n": int(len(values)),
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "hit": float((values > 0).mean()),
    }


def study(report, history_path) -> dict:
    restricted, mask = point_in_time.point_in_time(report, history_path)
    panel = restricted.panel
    grades = restricted.graded.grades
    years = np.array([str(d)[:4] for d in panel.dates])
    index_columns = [
        panel.index(name) for name in universe.MARKET_INDICES if name in panel.tickers
    ]
    eligible = np.asarray(mask, dtype=bool).copy()
    eligible[:, index_columns] = False
    out: dict = {"by_grade": {}, "by_analyst": {}, "by_year": {}}
    excess = {h: forward_excess(panel, h) for h in HORIZONS}
    for h in HORIZONS:
        for letter, ordinal in grading.ORDINAL.items():
            pick = eligible & (grades == ordinal)
            out["by_grade"][f"{letter}_{h}"] = _stats(excess[h][pick])
        top = eligible & (grades >= grading.ORDINAL[grading.A])
        rest = eligible & (grades < grading.ORDINAL[grading.A])
        out["by_grade"][f"spread_{h}"] = float(
            np.nanmean(excess[h][top]) - np.nanmean(excess[h][rest])
        )
        for name, stance in restricted.graded.stances.items():
            bull = eligible & (stance > 0)
            bear = eligible & (stance < 0)
            out["by_analyst"][f"{name}_{h}"] = {
                "bullish": _stats(excess[h][bull]),
                "bearish": _stats(excess[h][bear]),
                "spread": float(
                    np.nanmean(excess[h][bull]) - np.nanmean(excess[h][bear])
                )
                if bull.any() and bear.any()
                else None,
                "coverage": float(
                    (eligible & (stance != 0)).sum() / max(1, eligible.sum())
                ),
            }
        for year in sorted(set(years)):
            rows = years == year
            top_y = top & rows[:, None]
            rest_y = rest & rows[:, None]
            if top_y.any() and rest_y.any():
                out["by_year"].setdefault(year, {})[f"spread_{h}"] = float(
                    np.nanmean(excess[h][top_y]) - np.nanmean(excess[h][rest_y])
                )
                out["by_year"][year][f"top_{h}"] = _stats(excess[h][top_y])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--membership")
    args = parser.parse_args(argv)
    store = MarketStore(Path(args.root))
    report = desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))
    result = study(report, args.membership or universe.MEMBERSHIP_HISTORY_PATH)
    Path(args.output).write_text(
        json.dumps(result, indent=1, sort_keys=True, allow_nan=False)
    )
    for h in HORIZONS:
        print(f"-- {h} sessions ahead, excess over QQQ")
        for letter in grading.GRADES:
            s = result["by_grade"][f"{letter}_{h}"]
            if s["n"]:
                line = f"  {letter:2s} n={s['n']:7d} mean={s['mean']:+.3f}"
                print(f"{line} hit={s['hit']:.2f}")
        print(f"  A+/A minus B/C spread: {result['by_grade'][f'spread_{h}']:+.3f}")
        for name in sorted(restricted_names(result, h)):
            s = result["by_analyst"][f"{name}_{h}"]
            spread = s["spread"]
            print(
                f"  {name:12s} bull n={s['bullish']['n']:6d}"
                f" {s['bullish'].get('mean', 0):+.3f}"
                f" bear n={s['bearish']['n']:6d} {s['bearish'].get('mean', 0):+.3f}"
                f" spread={spread if spread is None else round(spread, 3)}"
                f" coverage={s['coverage']:.2f}"
            )
    return 0


def restricted_names(result: dict, h: int) -> list[str]:
    return [
        key[: -len(f"_{h}")] for key in result["by_analyst"] if key.endswith(f"_{h}")
    ]


if __name__ == "__main__":
    sys.exit(main())
