"""Day-type study: is a red day for the point-in-time book predictable at all?

    python -m backend.cli.market_day_type --root data/market

Runs the desk once, restricts it to the dated membership, builds the
day-type study (`backend.market.day_type`) and reports, for horizons of 1
and 5 sessions and for a logistic and a gradient-boosted model, the
out-of-sample Brier skill against climatology on 2016-2023 (the choosing
window) and on 2024-2026 (reported, never tuned on), plus the exposure
diagnostic beside the 1.5-CAGR insurance budget. Writes
`<root>/desk/day_type.json`.

The kill criterion is `day_type.SKILL_FLOOR` on 2016-2023: below it, the
verdict is INSUFFICIENT EVIDENCE and the idea stays a banner. Nothing here
trades or changes a target.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.market import calendar, day_type

FILE = "day_type.json"
WINDOWS = {"2016-2023": (date(2016, 1, 1), date(2024, 1, 1)), "2024-2026": (date(2024, 1, 1), None)}


# Build the study from a report and score every (horizon, model, window).
def build(report, mask: np.ndarray) -> dict:
    """Return the payload."""
    panel = report.panel
    scheduled = [d for d in calendar.fomc_decisions() if d not in (date(2020, 3, 3), date(2020, 3, 15))]
    ahead, since = calendar._fomc_distances(panel.dates, scheduled)
    study = day_type.build(report, mask, ahead, since)
    rows = []
    for horizon in day_type.HORIZONS:
        for model in ("logistic", "hgb"):
            full = day_type.walk_forward(study, horizon, model)
            for name, (start, end) in WINDOWS.items():
                window = point_in_time.window(panel.dates, start, end)
                scored = day_type.walk_forward(study, horizon, model, window=window)
                diagnostic = day_type.exposure_diagnostic(study, full, window=window)
                rows.append(
                    {
                        "horizon": horizon,
                        "model": model,
                        "window": name,
                        "sessions": scored.sessions,
                        "brier": scored.brier,
                        "brier_climatology": scored.brier_climatology,
                        "skill": scored.skill,
                        "base_rate": float(np.nanmean(study.labels[horizon][window])) if window.any() else float("nan"),
                        **diagnostic,
                    }
                )
    choosing = [r for r in rows if r["window"] == "2016-2023"]
    best = max(choosing, key=lambda r: (r["skill"] if r["skill"] == r["skill"] else -1.0), default=None)
    verdict = "INSUFFICIENT EVIDENCE"
    if best is not None and best["skill"] == best["skill"] and best["skill"] >= day_type.SKILL_FLOOR:
        verdict = "PASSED skill floor; not a trading verdict"
    return {
        "asof": str(panel.dates[-1]),
        "skill_floor": day_type.SKILL_FLOOR,
        "tail": day_type.TAIL,
        "features": list(day_type.FEATURE_NAMES),
        "rows": rows,
        "best_on_choosing_window": best,
        "verdict": verdict,
        "note": (
            "Brier skill = 1 - Brier / Brier of the trailing base rate, out of sample, "
            "walk-forward with a purge. The exposure diagnostic scales the basket to "
            "1 - p on sessions where p exceeds climatology; it is a diagnostic beside "
            "the insurance budget, not a strategy."
        ),
    }


# Print the rows as a table.
def render(payload: dict) -> str:
    """Return the study as text."""
    lines = [f"day-type study as of {payload['asof']}  (kill floor: skill {payload['skill_floor']:.2f} on 2016-2023)"]
    lines.append(f"  {'h':>2} {'model':<9}{'window':<11}{'n':>6}{'base':>7}{'Brier':>8}{'clim':>8}{'skill':>8}{'CAGR sc':>9}{'CAGR al':>9}{'DD sc':>8}{'DD al':>8}")
    for r in payload["rows"]:
        lines.append(
            f"  {r['horizon']:>2} {r['model']:<9}{r['window']:<11}{r['sessions']:>6}{r['base_rate']:>7.3f}"
            f"{r['brier']:>8.4f}{r['brier_climatology']:>8.4f}{r['skill']:>8.3f}"
            f"{r['cagr_scaled']*100:>8.1f}%{r['cagr_always']*100:>8.1f}%{r['drawdown_scaled']*100:>7.0f}%{r['drawdown_always']*100:>7.0f}%"
        )
    lines.append(f"verdict: {payload['verdict']}")
    return "\n".join(lines)


# Run the desk, build, score, write and print.
def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    args = parser.parse_args(argv)
    from backend.agents.trading.desk import desk
    from backend.market.store import MarketStore

    root = Path(args.root)
    store = MarketStore(root)
    report = desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))
    restricted, mask = point_in_time.point_in_time(report)
    payload = build(restricted, mask)
    target = root / "desk" / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")
    print(render(payload))
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
