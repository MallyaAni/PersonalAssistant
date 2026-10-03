"""Compare conditional continuation timing with the current gate in one funded book.

This is a price-timing component diagnostic, not a reconstruction of broker
receipts or the current rotation executor. Both sides retain missing sessions.
"""

from datetime import date

import numpy as np

from backend.market import calendar, entry_timing
from backend.market.learned_execution_timing import replay_account

POLICY = "crossfitted-session-continuation/1"
CONTROL = "current-one-percent-next-open/1"
TERMINAL = 24


# Retain early closes as unsupported rather than padding an absent regular grid.
def supported_sessions(dates):
    years, sessions = calendar.reviewed_sessions()
    dates = np.asarray(dates, dtype="datetime64[D]")
    if np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("unique ordered calendar sessions required")
    supported = []
    for value in dates:
        day = date.fromisoformat(str(value))
        if day.year not in years or not np.is_busday(value, busdaycal=sessions):
            raise ValueError("source date outside reviewed exchange sessions")
        supported.append(calendar.session_close(day) == calendar.REGULAR_CLOSE)
    return np.asarray(supported, dtype=bool)


# Select pending intents from observed prices and conditional expected advantages.
def choose(predictions, delta, known, pending, final, counts):
    if final:
        return pending & known
    side = (delta < 0).astype(int)
    values = predictions[np.arange(len(delta)), side]
    available = pending & known & np.isfinite(values)
    waiting = available & np.where(delta > 0, values > 0, values < 0)
    counts["waiting_decisions"] += int(waiting.sum())
    counts["forecast_unavailable"] += int((pending & known & ~available).sum())
    return available & ~waiting


# Use the live rule's exact crossing arithmetic without searching future bars.
def gate(opened, observed, delta, known, pending, final, counts):
    if final:
        return pending & known
    available = np.isfinite(opened) & (opened > 0)
    acting = np.zeros(len(delta), dtype=bool)
    for stock in np.flatnonzero(pending & known & available):
        side = "buy" if delta[stock] > 0 else "sell"
        acting[stock] = entry_timing.crosses(observed[stock], opened[stock], side)
    counts["waiting_decisions"] += int((pending & known & available & ~acting).sum())
    counts["opening_unavailable"] += int((pending & known & ~available).sum())
    return acting


# Replay either policy with identical plans, funding, deadlines and outcome prices.
def account(
    panel,
    grades,
    eligible,
    dataset,
    predictions,
    session_open,
    first,
    cost_bps,
    offset,
    *,
    method="candidate",
    supported_days=None,
):
    shape = (len(panel.dates), 25, len(panel.tickers))
    if method not in ("candidate", "control"):
        raise ValueError("candidate or control required")
    if np.shape(predictions) != (*shape, 2):
        raise ValueError("aligned buy/sell continuation predictions required")
    if np.shape(session_open) != panel.adj_close.shape:
        raise ValueError("aligned causal session opening prices required")
    if supported_days is None:
        supported_days = supported_sessions(panel.dates)

    # Decide before the shared engine reads the selected next-open outcome.
    def select(
        day, clock, delta, known, pending, observed, nav, budget, cost, final, counts
    ):
        notional = np.maximum(delta, 0) * np.where(pending & known, observed, 0)
        if float(notional.sum()) * (1 + cost / 1e4) > budget:
            counts["cash_limited_decisions"] += int(
                (pending & known & (delta > 0)).sum()
            )
        if method == "control":
            return gate(
                session_open[day], observed, delta, known, pending, final, counts
            )
        return choose(predictions[day, clock], delta, known, pending, final, counts)

    # Read the honest subsequent open only after the first action is locked.
    def prices(day, clock, final):
        return dataset["next_open"][day, clock]

    result = replay_account(
        panel,
        grades,
        eligible,
        dataset,
        first,
        cost_bps,
        offset,
        select,
        prices,
        TERMINAL,
        supported_days=supported_days,
        record_intents=True,
        decision_counts={
            "waiting_decisions": 0,
            "forecast_unavailable": 0,
            "opening_unavailable": 0,
            "cash_limited_decisions": 0,
            "unsupported_plan_sessions": 0,
        },
    )
    result["policy"] = POLICY if method == "candidate" else CONTROL
    return result
