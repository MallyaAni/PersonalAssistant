"""Capture comparable price-entry opinions, never personal orders or funded actions."""

import math
from datetime import time, timedelta

import numpy as np

from backend.agents.trading.desk import entry, paper
from backend.market import calendar, decision_view, desk_freshness

VERSION = "recorded-entry-opinions/1"


# Preserve missing numerical evidence as JSON null rather than a false zero.
def _number(value):
    return float(value) if math.isfinite(float(value)) else None


# Capture two price rules on the same observation and common non-account gates.
def capture(panel, record, observation):
    observed = desk_freshness.timestamp(observation.get("as_of"))
    deadline = desk_freshness.timestamp(observation.get("valid_until"))
    bar = desk_freshness.timestamp(observation.get("bar"))
    if observed is None or deadline is None or bar is None:
        raise ValueError("Dated entry evidence required")
    day = observed.astimezone(desk_freshness.NEW_YORK).date()
    if str(panel.dates[-1]) != day.isoformat() or observed >= deadline:
        raise ValueError("Current unexpired entry inputs required")
    local_bar = bar.astimezone(desk_freshness.NEW_YORK)
    years, sessions = calendar._published_sessions()
    regular = (
        day.year in years
        and np.is_busday(np.datetime64(day), busdaycal=sessions)
        and local_bar.date() == day
        and local_bar.time() >= time(9, 30)
        and (local_bar + timedelta(minutes=15)).time() <= calendar.session_close(day)
        and local_bar.minute % 15 == 0
        and local_bar.second == local_bar.microsecond == 0
    )
    if not regular or not 15 * 60 <= (observed - bar).total_seconds() < 30 * 60:
        raise ValueError("A completed price bar is required")
    distance = calendar._future_session_offset(
        np.datetime64(record["session"]), np.datetime64(day)
    )
    triggers = entry.entries(panel)
    rows = {}
    for name, grade in sorted(observation["grades"].items()):
        column = panel.index(name)
        band = _number(triggers.bollinger_z[-1, column])
        stretch = _number(triggers.stretch_21[-1, column])
        window = panel.adj_close[-20:, column]
        valid = len(window) == 20 and np.all(np.isfinite(window) & (window > 0))
        available = bool(valid and band is not None and stretch is not None)
        letter = grade["grade_live"]
        rejecting = bool(
            (record.get("levels", {}).get(name) or {}).get("rejecting_band")
        )
        blockers = []
        if not available:
            blockers.append("price_features_unavailable")
        if distance not in (0, 1):
            blockers.append("stale_decision")
        if letter not in paper.ENTRY_MIN_GRADE:
            blockers.append("grade_below_entry_floor")
        if observation.get("event_paused"):
            blockers.append("event_pause")
        if rejecting:
            blockers.append("rejecting_upper_band")
        opinion = decision_view.entry_action(
            {"rejecting_band": rejecting}, band, letter, current=0.0
        )
        rows[name] = {
            "grade": letter,
            "price_setup": triggers.kind(len(panel.dates) - 1, column) or "wait",
            "band_z": band,
            "stretch_21": stretch,
            "adjusted_band_closes": [_number(value) for value in window],
            "common_eligible": not blockers,
            "blockers": blockers,
            "dip_setup": bool(triggers.dip[-1, column]) if available else None,
            "incumbent_price_setup": band >= paper.ENTRY_BAND_Z if available else None,
            "dip_entry_opinion": bool(triggers.dip[-1, column])
            if not blockers
            else False,
            "incumbent_entry_opinion": bool(
                opinion and opinion[0] == decision_view.Action.BUY
            )
            if not blockers
            else False,
        }
    return {
        "version": VERSION,
        "mode": "unfunded_price_rule_comparison",
        "observed_at": observed.isoformat(),
        "bar": bar.isoformat(),
        "valid_until": deadline.isoformat(),
        "decision_session": record["session"],
        "incumbent_policy": paper.POLICY_VERSION,
        "incumbent_band_threshold": paper.ENTRY_BAND_Z,
        "band_window_dates": [str(value) for value in panel.dates[-20:]],
        "price_basis": "capture-vintage adjusted daily closes plus observed bar",
        "account_assumption": (
            "flat position; no cash, account caps, execution quote or fill claim"
        ),
        "rows": rows,
    }
