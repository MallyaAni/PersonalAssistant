"""The event calendar as features: where each session sits in the year's rhythm.

Measured over 94 FOMC decisions since 2015: the index drifts up slightly
into the meeting, high-volatility and AI names lag defensives in the last
three sessions before it (small), jump on the decision day (high minus low
volatility +41 bp, t 2.4), and whipsaw for three sessions after. None of
the price, filing or language inputs carried the calendar, so a model
could not have learned any of it. This module gives it the calendar, and
the rest of the documented date effects beside it:

    sessions_to_fomc, sessions_since_fomc   capped at 30
    fomc_pre_window, fomc_decision_day, fomc_post_window   three-session windows
    turn_of_month        the month's last session and its first three
    opex_week            the week of the third Friday (equity options expiry)
    opex_day             the third Friday itself, or the session before it
                         when that Friday is a holiday
    quad_witching        opex_day in March, June, September, December
    russell_reconstitution   the fourth Friday of June
    december, january    tax-loss selling and its unwind
    month_end_sessions   sessions until the month's last session, capped at 10

They enter the market-state vector every encoder's gate reads and, broadcast
per name, the "calendar" feature layer where a tree or MLP can interact
them with a name's volatility.

Decision dates are the last day of each scheduled meeting from
federalreserve.gov, committed in data/fomc_decisions.csv (dated in its
header), plus the March 2020 unscheduled actions.
"""

from datetime import date, timedelta
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
    "turn_of_month",
    "opex_week",
    "opex_day",
    "quad_witching",
    "russell_reconstitution",
    "december",
    "january",
    "month_end_sessions",
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


# The n-th Friday of a month (1-based).
def nth_friday(year: int, month: int, n: int) -> date:
    """Return the n-th Friday of the month."""
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


# Per-session FOMC distances: (sessions to next, sessions since last).
def _fomc_distances(
    dates: np.ndarray, decisions: list[date]
) -> tuple[np.ndarray, np.ndarray]:
    marks = np.asarray(sorted(decisions), dtype="datetime64[D]")
    # The session on or after each decision (a Sunday action reacts Monday).
    positions = np.searchsorted(dates, marks, side="left")
    positions = positions[positions < len(dates)]
    to_next = np.full(len(dates), FAR)
    since = np.full(len(dates), FAR)
    for t in range(len(dates)):
        after = positions[positions >= t]
        before = positions[positions <= t]
        if len(after):
            to_next[t] = min(float(after[0] - t), FAR)
        if len(before):
            since[t] = min(float(t - before[-1]), FAR)
    return to_next, since


# Whether each session is the options-expiry session of its month: the
# third Friday, or the last session before it when that Friday is closed.
def _opex_sessions(days: list[date]) -> np.ndarray:
    out = np.zeros(len(days), dtype=bool)
    by_month: dict[tuple[int, int], list[int]] = {}
    for i, d in enumerate(days):
        by_month.setdefault((d.year, d.month), []).append(i)
    for (year, month), rows in by_month.items():
        friday = nth_friday(year, month, 3)
        candidates = [
            i for i in rows if days[i] <= friday and (friday - days[i]).days <= 4
        ]
        if candidates:
            out[max(candidates)] = True
    return out


# The (T, CALENDAR_COUNT) calendar features for a panel's sessions.
def calendar_by_session(
    panel: Panel, decisions: list[date] | None = None
) -> np.ndarray:
    """Return per-session calendar features aligned to the panel's dates."""
    decisions = decisions if decisions is not None else fomc_decisions()
    dates = panel.dates.astype("datetime64[D]")
    days = [d for d in dates.astype(object)]
    to_next, since = _fomc_distances(dates, decisions)
    opex = _opex_sessions(days)
    out = np.zeros((len(days), CALENDAR_COUNT), dtype=np.float32)
    for t, d in enumerate(days):
        # Sessions until the month's last session, and since its first.
        to_end = 0
        while t + to_end + 1 < len(days) and days[t + to_end + 1].month == d.month:
            to_end += 1
            if to_end >= 10:
                break
        since_start = 0
        while t - since_start - 1 >= 0 and days[t - since_start - 1].month == d.month:
            since_start += 1
            if since_start >= 10:
                break
        turn = 1.0 if to_end == 0 or since_start <= 2 else 0.0
        third_friday = nth_friday(d.year, d.month, 3)
        opex_week = (
            1.0
            if 0 <= (third_friday - d).days <= 4
            and d.weekday() <= third_friday.weekday()
            else 0.0
        )
        russell = 1.0 if d.month == 6 and d == nth_friday(d.year, 6, 4) else 0.0
        out[t] = (
            to_next[t],
            since[t],
            1.0 if 1 <= to_next[t] <= WINDOW else 0.0,
            1.0 if to_next[t] == 0 else 0.0,
            1.0 if 1 <= since[t] <= WINDOW else 0.0,
            turn,
            opex_week,
            1.0 if opex[t] else 0.0,
            1.0 if opex[t] and d.month in (3, 6, 9, 12) else 0.0,
            russell,
            1.0 if d.month == 12 else 0.0,
            1.0 if d.month == 1 else 0.0,
            float(min(to_end, 10)),
        )
    return out


# The calendar broadcast per name: (T, N, CALENDAR_COUNT).
def calendar_features(panel: Panel, decisions: list[date] | None = None) -> np.ndarray:
    """Return the per-session calendar repeated for every name."""
    per_session = calendar_by_session(panel, decisions)
    return np.repeat(per_session[:, None, :], len(panel.tickers), axis=1)
