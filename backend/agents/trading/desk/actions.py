"""The action board: what to do at the next open, in the order it matters.

A grade says what the desk thinks. An action says what a person does
about it at 9:30 tomorrow: buy, add, trim, sell or hold, how much, and
what would make the desk leave. This turns the record's targets and the
account's holdings into that list, with everything a decision needs on
one row and nothing that is not measured.

Sizes are weights of equity, so the same row scales to any account. The
entry is the next open - the execution study found every later schedule
pays. The exit is the desk's own: a name leaves at a rebalance when it
no longer earns its grade, so the row carries how far its votes sit
above the line and how many sessions remain on the rebalance clock.
Stop levels are given as risk controls, not signals, and the view shows
them only when asked. The book's history says a trailing stop trades the
mean for the tail (a 12% stop after a sharp rise cut the worst tenth
from -25% to -16% and the mean from +9% to +4%). It also says the cost is
not a predator at the level: across the universe since 2015, a day that
trades through the prior twenty-session low and closes back above it
(65,787 cases) is followed by the same flat ten sessions as one that
closes below it (73,169 cases), -0.03% against -0.02% beta-adjusted, and
wicks are 47% of such days; the same holds at a 12% trailing level. A
stop costs because it truncates a right-skewed path, not because it is
hunted. The person, knowing their size, chooses.
"""

from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk import grading, plainly

REBALANCE = 20
HIGH_WINDOW = 20
STOPS = (0.08, 0.12, 0.20)
# A change below this fraction of equity is not worth an order.
DELTA_FLOOR = 0.005
ORDER = {"sell": 0, "trim": 1, "buy": 2, "add": 3, "hold": 4}


@dataclass(frozen=True)
class Holding:
    """What the account holds in one name, as a weight of equity."""

    weight: float
    entry_price: float | None = None


# How far a name's votes sit above the line that keeps its grade: at or
# below zero it is one bearish stance from losing it.
def grade_margin(votes: float, grade: str, release_bullish: bool) -> float:
    """Return the votes above the threshold of `grade`."""
    if grade == grading.A_PLUS:
        return votes - 2.0
    if grade == grading.A:
        return votes - (1.0 if release_bullish else 2.0)
    if grade == grading.B:
        return votes - 0.5
    return votes - 0.5  # a C: how far below a B


# The action a target and a holding imply.
def action_for(target: float, held: float) -> str:
    """Return buy, add, trim, sell or hold."""
    if target <= 0 and held > 0:
        return "sell"
    if target > 0 and held <= 0:
        return "buy"
    if target - held > DELTA_FLOOR:
        return "add"
    if held - target > DELTA_FLOOR:
        return "trim"
    return "hold"


# The plain-English headline for a name, or nothing where the report
# cannot brief it (a bare report in a test has no evidence to write from).
def _headline(report, ticker: str) -> str:
    try:
        return plainly.headline(report.brief(ticker))
    except (AttributeError, KeyError, TypeError):
        return ""


# Build the board from the day's report, the targets and the holdings.
def build(
    report,
    targets: dict[str, float],
    holdings: dict[str, Holding],
    sessions_since_rebalance: int,
    reasons: dict[str, str] | None = None,
) -> list[dict]:
    """Return one row per name that is targeted or held, most urgent first."""
    panel = report.panel
    last = len(panel.dates) - 1
    in_book = [t for t in panel.tickers if t in report.sides]
    ordered = sorted(in_book, key=lambda t: -float(report.scores[last, panel.index(t)]))
    rank = {t: i + 1 for i, t in enumerate(ordered)}
    reasons = reasons or {}
    rows = []
    for ticker in sorted(set(targets) | set(holdings)):
        if ticker not in report.sides:
            continue
        column = panel.index(ticker)
        target = float(targets.get(ticker, 0.0))
        holding = holdings.get(ticker, Holding(0.0))
        action = action_for(target, holding.weight)
        grade = report.graded.letter(last, column)
        votes = float(report.graded.votes[last, column])
        sentiment = report.graded.stances.get("sentiment")
        bullish = (
            sentiment is not None and int(sentiment[last, column]) == grading.BULLISH
        )
        highs = panel.high[max(0, last - HIGH_WINDOW + 1) : last + 1, column]
        with np.errstate(all="ignore"):
            high = float(np.nanmax(highs)) if np.isfinite(highs).any() else float("nan")
        close = float(panel.close[last, column])
        rows.append(
            {
                "ticker": ticker,
                "action": action,
                "grade": grade,
                "rank": rank.get(ticker),
                "score": float(report.scores[last, column]),
                "target_weight": target,
                "current_weight": float(holding.weight),
                "delta_weight": target - float(holding.weight),
                "last_close": close,
                "entry_price": holding.entry_price,
                "entry": "market-on-open",
                "until_rebalance": max(REBALANCE - int(sessions_since_rebalance), 0),
                "grade_margin": grade_margin(votes, grade, bullish),
                "leaves_if": (
                    "the grade falls below A at a rebalance"
                    if target > 0
                    else "already outside the book"
                ),
                "high_20": high,
                "stops": (
                    {f"{int(s * 100)}": high * (1.0 - s) for s in STOPS}
                    if np.isfinite(high)
                    else {}
                ),
                "why": reasons.get(ticker) or _headline(report, ticker),
            }
        )
    rows.sort(key=lambda r: (ORDER[r["action"]], -abs(r["delta_weight"]), r["ticker"]))
    return rows
