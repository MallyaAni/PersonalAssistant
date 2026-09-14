"""Compare calendar restoration with a causal multi-timeframe recovery gate."""
import json
from datetime import date
from pathlib import Path
import numpy as np
from backend.agents.trading.desk import desk, event_risk, simulate
from backend.cli.market_fomc import ResearchStore
from backend.market import levels
from backend.market.calendar import fomc_decisions


# Extend an event reduction only until both existing benchmark trend readings recover.
def gated_path(base, daily, weekly):
    result = base.copy()
    active = False
    for t in range(len(base)):
        if base[t] < 1:
            active = True
        elif active and np.isfinite(daily[t]) and np.isfinite(weekly[t]) and daily[t] >= 0 and weekly[t] >= 0:
            active = False
        if active:
            result[t] = .5
    return result


# Compare funded policies on one pinned data cut, including two cost assumptions.
def main():
    cutoff = date(2026, 9, 11)
    report = desk.run(ResearchStore(Path.home()/"anios/data/market", cutoff), asof=cutoff)
    panel = report.panel
    features = levels.level_features(panel)
    j = panel.index(panel.benchmark)
    daily = features[:, j, levels.LEVEL_NAMES.index("daily_trend")]
    weekly = features[:, j, levels.LEVEL_NAMES.index("weekly_trend")]
    base = event_risk.exposure_path(panel, fomc_decisions(), 3, require_weakness=True)
    gated = gated_path(base, daily, weekly)
    for since in (date(2021, 1, 1), date(2026, 6, 18)):
        for cost in (10, 25):
            for name, path in (("calendar", base), ("daily_weekly_nonnegative", gated)):
                result = simulate.run(report, since=since, cost_bps=cost, use_exits=False,
                                      event_exposure=path, event_lifecycle=True, **simulate.LIVE_POLICY)
                print(json.dumps({"candidate": name, "since": str(since), "through": str(cutoff),
                                  "cost_bps": cost, "stats": result.stats(),
                                  "completed_meetings": [str(d) for d in fomc_decisions() if since <= d <= cutoff]}), flush=True)


if __name__ == "__main__":
    main()
