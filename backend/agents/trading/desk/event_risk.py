"""Versioned FOMC exposure policy and causal research windows.

The live policy holds through meetings. The pre-meeting cut was retired on
2026-10-28: across the 34 triggered meetings from 2015 to 2026 the book rose
from the cut to the decision close in 20 of them (mean +0.48%), and the
ten-year lead-in was better than an ordinary week, so cutting into the
pre-meeting selloff sold the rebound rather than avoiding it
(`docs/research/fomc-lead-in-2026-10-22.md`,
`docs/research/fomc-cut-retirement-2026-10-28.md`). The historical window stays
here for research and for the arithmetic of a cycle that was already open;
`live_path` no longer applies it.
"""

from datetime import date

import numpy as np

from backend.market.calendar import _fomc_distances, fomc_decisions
from backend.market.panel import Panel

VERSION = "fomc-hold-through-meeting/1"
ENABLED = False
RETIRED_ON = date(2026, 10, 28)
RETIREMENT_REASON = (
    "Pre-meeting cut retired: the book rose from the cut to the decision "
    "close in 20 of 34 triggered meetings (mean +0.48%), and the ten-year "
    "lead-in is positive on average."
)
RETIRED_VERSION = "fomc-3-session-weakness/2"
GUIDANCE_CHANGE = date(2026, 6, 18)
PRE_SESSIONS = 3
REDUCED = 0.5


# The live policy holds through meetings: no pre-meeting cut, so every session is full exposure.
def live_path(panel: Panel) -> np.ndarray:
    return np.ones(len(panel.dates))


# A missing calendar blocks planning only while the policy can still cut.
def calendar_blocks(event_policy: dict) -> bool:
    return bool(
        event_policy.get("enabled", True)
        and event_policy.get("calendar_known") is False
    )


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
                "drawdown": float(np.min(values / np.maximum.accumulate(values) - 1)),
                "sessions": end - start,
                "completed_meetings": meetings,
                "basis": "continuous simulation; costs included; not live returns",
            }
        )
    return out


# Describe tonight's retired policy: calendar and weakness readings stay visible, the cut never fires.
def decision(panel: Panel) -> dict:
    meetings = fomc_decisions()
    last = panel.dates[-1].astype(object)
    upcoming = next((day for day in meetings if day >= last), None)
    distances, _ = _fomc_distances(panel.dates, meetings)
    distance = float(distances[-1])
    known = upcoming is not None and np.isfinite(distance)
    closes = panel.adj_close[:, panel.index(panel.benchmark)]
    change = (
        float(closes[-1] / closes[-6] - 1)
        if len(closes) >= 6 and np.isfinite(closes[-6:]).all() and closes[-6] > 0
        else None
    )
    return {
        "version": VERSION,
        "enabled": ENABLED,
        "retired_on": str(RETIRED_ON),
        "retirement_reason": RETIREMENT_REASON,
        "session": str(last),
        "decision_date": str(upcoming) if upcoming else None,
        "sessions_to_decision": int(distance) if known else None,
        "calendar_known": bool(known),
        "factor": 1.0 if known else None,
        "spy_five_session_return": change,
        "pre_sessions": PRE_SESSIONS,
        "reduced_exposure": REDUCED,
        "evaluation_since": str(GUIDANCE_CHANGE),
        "qualification": (
            "Retired 2026-10-28; the pre-meeting cut is not run. The "
            "historical window remains for research."
        ),
    }


# Build the retired window from the published calendar and benchmark prices known at each close.
# Research and legacy cycle arithmetic only; `live_path` does not call it after the retirement.
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
