"""Research-only FOMC exposure windows; no live planner imports this module.

A decision at today's close controls exposure from the next session. A
window protects the specified pre-meeting sessions and the decision session;
normal exposure resumes at the following open. The weakness variant waits
for a negative trailing five-session benchmark return, then stays reduced
through the event so a one-day rebound does not cause repeated trading.
"""

from datetime import date

import numpy as np

from backend.market.calendar import _fomc_distances
from backend.market.panel import Panel


# Build decisions from the published calendar and benchmark prices known at each close.
def exposure_path(
    panel: Panel,
    decisions: list[date],
    pre_sessions: int,
    reduced: float = 0.5,
    require_weakness: bool = False,
) -> np.ndarray:
    if pre_sessions not in (1, 3, 5, 10):
        raise ValueError("Use a predeclared 1, 3, 5 or 10 session window")
    if not 0 < reduced <= 1:
        raise ValueError("Exposure must be above zero and at most one")
    distance, _ = _fomc_distances(panel.dates, decisions)
    close = panel.adj_close[:, panel.index(panel.benchmark)]
    scale = np.ones(len(close))
    active = False
    for t in range(len(close)):
        # At distance window+1, the next open begins the first protected day.
        inside = np.isfinite(distance[t]) and 1 <= distance[t] <= pre_sessions + 1
        if not inside:
            active = False
            continue
        weak = (
            t >= 5
            and np.isfinite(close[t])
            and np.isfinite(close[t - 5])
            and 0 < close[t] < close[t - 5]
        )
        active = active or not require_weakness or weak
        if active:
            scale[t] = reduced
    return scale
