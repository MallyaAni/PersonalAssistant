"""The event calendar as features: where each session sits relative to the Fed.

Measured over 94 FOMC decisions since 2015: the index drifts up slightly
into the meeting, high-volatility and AI names lag defensives in the last
three sessions before it (small), jump on the decision day (high minus low
volatility +41 bp, t 2.4), and whipsaw for three sessions after. None of
the price, filing or language inputs carried the calendar, so a model
could not have learned any of it. This module gives it the calendar.

Per session: sessions until the next decision, sessions since the last,
and flags for the three-session pre-window, the decision day, and the
three-session post-window. They enter the market-state vector every
encoder's gate reads, and, broadcast per name, the "calendar" feature
layer where a tree or MLP can interact them with a name's volatility.

Decision dates are the last day of each scheduled meeting from
federalreserve.gov, committed in data/fomc_decisions.csv (dated in its
header), plus the March 2020 unscheduled actions. Add CPI releases and
options expiries here the same way when they earn their place.
"""

from datetime import date
from pathlib import Path

import numpy as np

from backend.market.panel import Panel

FOMC_PATH = Path(__file__).parent / "data" / "fomc_decisions.csv"
CALENDAR_NAMES: tuple[str, ...] = (
    "sessions_to_fomc",
    "sessions_since_fomc",
    "fomc_pre_window",
    "fomc_decision_day",
    "fomc_post_window",
)
CALENDAR_COUNT = len(CALENDAR_NAMES)
FAR = 30.0  # the count is capped here; beyond a month the Fed is not the story
WINDOW = 3


# The committed decision dates, sorted.
def fomc_decisions(path: Path = FOMC_PATH) -> list[date]:
    """Return the FOMC decision dates on file, oldest first."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line[:2] == "20":
            out.append(date.fromisoformat(line))
    return sorted(set(out))


# The (T, CALENDAR_COUNT) calendar features for a panel's sessions.
def calendar_by_session(
    panel: Panel, decisions: list[date] | None = None
) -> np.ndarray:
    """Return per-session FOMC features aligned to the panel's dates."""
    decisions = decisions if decisions is not None else fomc_decisions()
    dates = panel.dates.astype("datetime64[D]")
    marks = np.asarray(sorted(decisions), dtype="datetime64[D]")
    # The session on or after each decision (a Sunday action reacts Monday).
    positions = np.searchsorted(dates, marks, side="left")
    positions = positions[positions < len(dates)]
    out = np.zeros((len(dates), CALENDAR_COUNT), dtype=np.float32)
    for t in range(len(dates)):
        after = positions[positions >= t]
        before = positions[positions <= t]
        to_next = float(after[0] - t) if len(after) else FAR
        since = float(t - before[-1]) if len(before) else FAR
        to_next = min(to_next, FAR)
        since = min(since, FAR)
        out[t] = (
            to_next,
            since,
            1.0 if 1 <= to_next <= WINDOW else 0.0,
            1.0 if to_next == 0 else 0.0,
            1.0 if 1 <= since <= WINDOW else 0.0,
        )
    return out


# The calendar broadcast per name: (T, N, CALENDAR_COUNT).
def calendar_features(panel: Panel, decisions: list[date] | None = None) -> np.ndarray:
    """Return the per-session calendar repeated for every name."""
    per_session = calendar_by_session(panel, decisions)
    return np.repeat(per_session[:, None, :], len(panel.tickers), axis=1)
