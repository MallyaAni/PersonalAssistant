"""Versioned FOMC exposure policy and causal research windows.

A decision at today's close controls exposure from the next session. A
window protects the specified pre-meeting sessions and the decision session;
normal exposure resumes at the following open. The weakness variant waits
for a negative trailing five-session benchmark return, then stays reduced
through the event so a one-day rebound does not cause repeated trading.
"""

from datetime import date

import numpy as np

from backend.market.calendar import _fomc_distances, fomc_decisions
from backend.market.panel import Panel

VERSION = "fomc-3-session-weakness/2"
GUIDANCE_CHANGE = date(2026, 6, 18)
PRE_SESSIONS = 3
REDUCED = 0.5


# Apply the adopted policy only in the new guidance regime for current-rule research.
def live_path(panel: Panel) -> np.ndarray:
    path = exposure_path(panel, fomc_decisions(), PRE_SESSIONS, REDUCED, True)
    return np.where(panel.dates >= np.datetime64(GUIDANCE_CHANGE), path, 1.0)


# Measure distinct policy eras on one continuous account, without restarting its clock.
def evaluation_slices(result) -> list[dict]:
    if result.equity is None or len(result.dates) < 2:
        return []
    dates = result.dates
    boundary = int(np.searchsorted(dates, np.datetime64(GUIDANCE_CHANGE)))
    out = []
    for label, start, end in (
        (
            "Earlier guidance regime · historical stress test",
            0,
            min(boundary - 1, len(dates) - 1),
        ),
        (
            "After guidance change · limited sample",
            max(0, boundary - 1),
            len(dates) - 1,
        ),
    ):
        if end <= start:
            continue
        values = np.asarray(result.equity[start : end + 1], dtype=float)
        if not np.isfinite(values).all() or values[0] <= 0:
            continue
        meetings = [
            str(d)
            for d in fomc_decisions()
            if dates[start + 1].astype(object) <= d <= dates[end].astype(object)
        ]
        out.append(
            {
                "label": label,
                "since": str(dates[start + 1]),
                "base_session": str(dates[start]),
                "through": str(dates[end]),
                "total_return": float(values[-1] / values[0] - 1),
                "drawdown": float(np.max(1 - values / np.maximum.accumulate(values))),
                "sessions": end - start,
                "completed_meetings": meetings,
                "basis": "continuous simulation; costs included; not live returns",
            }
        )
    return out


# Describe tonight's policy decision without treating a requested cut as a fill.
def decision(panel: Panel) -> dict:
    meetings = fomc_decisions()
    last = panel.dates[-1].astype(object)
    upcoming = next((day for day in meetings if day >= last), None)
    distances, _ = _fomc_distances(panel.dates, meetings)
    distance = float(distances[-1])
    known = upcoming is not None and np.isfinite(distance)
    path = exposure_path(panel, meetings, PRE_SESSIONS, REDUCED, True)
    closes = panel.adj_close[:, panel.index(panel.benchmark)]
    change = (
        float(closes[-1] / closes[-6] - 1)
        if len(closes) >= 6 and np.isfinite(closes[-6:]).all() and closes[-6] > 0
        else None
    )
    return {
        "version": VERSION,
        "enabled": True,
        "session": str(last),
        "decision_date": str(upcoming) if upcoming else None,
        "sessions_to_decision": int(distance) if known else None,
        "calendar_known": bool(known),
        "factor": float(path[-1]) if known else None,
        "spy_five_session_return": change,
        "pre_sessions": PRE_SESSIONS,
        "reduced_exposure": REDUCED,
        "evaluation_since": str(GUIDANCE_CHANGE),
        "qualification": "Provisional policy; limited post-guidance evidence.",
    }


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
