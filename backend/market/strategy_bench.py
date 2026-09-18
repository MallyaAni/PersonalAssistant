"""Candidate trading rules against each other and against the indices.

The desk has a scorecard that renders text for a terminal and has never been
on screen. This is the same comparison as data: every candidate rule and
every index on identical numbers, split by regime, so the reader can see
where a rule's return actually came from rather than one headline figure.

The regimes are fixed on the calendar and not on the results:

    pre-COVID bull   2015-01-02 .. 2020-02-19
    COVID crash      2020-02-19 .. 2020-03-23   SPY -33.4% in 24 sessions
    COVID recovery   2020-03-23 .. 2021-12-31
    2022 bear        2022-01-03 .. 2022-12-30
    AI boom          2023-01-03 ..

Each block carries the share of the sample it represents, because the COVID
crash is 0.8% of it and reads like half the evidence without that number
beside it.

Every figure inherits the survivorship the universe carries: the constituent
list is today's, delisted names are absent, and `market_survivorship`
measures nineteen points a year of the book's return as name choice. That
biases every candidate here in the same direction, so the comparisons
between them are far more trustworthy than any single absolute return.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

FILE = "strategy_bench.json"

# (label, first session, last session). Chosen on the calendar.
REGIMES: tuple[tuple[str, date, date], ...] = (
    ("Whole sample", date(2000, 1, 1), date(2100, 1, 1)),
    ("Pre-COVID bull", date(2015, 1, 2), date(2020, 2, 19)),
    ("COVID crash", date(2020, 2, 19), date(2020, 3, 23)),
    ("COVID recovery", date(2020, 3, 23), date(2021, 12, 31)),
    ("2022 bear", date(2022, 1, 3), date(2022, 12, 30)),
    ("AI boom", date(2023, 1, 3), date(2100, 1, 1)),
)


# The numbers every candidate is judged on, from one daily return series.
def stats(daily: np.ndarray) -> dict[str, float | None]:
    """Return total, annual, volatility, drawdown and Sharpe for a series."""
    r = np.where(np.isfinite(daily), daily, 0.0)
    if len(r) < 5:
        return {k: None for k in ("total", "annual", "volatility", "drawdown", "sharpe")}
    curve = np.cumprod(1 + r)
    years = len(r) / 252
    total = float(curve[-1] - 1)
    annual = float(curve[-1] ** (1 / years) - 1) if years > 0.15 else None
    vol = float(np.std(r) * np.sqrt(252))
    drawdown = float((curve / np.maximum.accumulate(curve) - 1).min())
    sharpe = (annual / vol) if (annual is not None and vol > 0) else None
    return {
        "total": total,
        "annual": annual,
        "volatility": vol,
        "drawdown": drawdown,
        "sharpe": sharpe,
    }


# One payload: every candidate over every regime, plus what each regime is.
def build(
    sessions: np.ndarray, series: dict[str, np.ndarray], note: str = ""
) -> dict[str, object]:
    """Return the comparison for `series`, each aligned to `sessions`."""
    days = np.array(
        [d.astype("datetime64[D]").astype(object) for d in sessions], dtype=object
    )
    total_sessions = len(days)
    blocks = []
    for label, lo, hi in REGIMES:
        mask = np.array([lo <= d <= hi for d in days])
        count = int(mask.sum())
        if count < 5:
            continue
        blocks.append(
            {
                "regime": label,
                "from": str(days[mask][0]),
                "to": str(days[mask][-1]),
                "sessions": count,
                "share": count / total_sessions if total_sessions else None,
                "rows": [
                    {"name": name, **stats(values[mask])}
                    for name, values in series.items()
                ],
            }
        )
    return {
        "version": "strategy-bench/1",
        "sessions": total_sessions,
        "from": str(days[0]) if total_sessions else None,
        "to": str(days[-1]) if total_sessions else None,
        "note": note,
        "caveat": (
            "Survivorship: the constituent list is today's, delisted names are "
            "absent, and market_survivorship measures nineteen points a year of "
            "the book's return as name choice. Every candidate here carries that "
            "same bias, so compare them against each other rather than reading "
            "any single return as achievable."
        ),
        "blocks": blocks,
    }


# Written beside the other records so the page reads a file, not a backtest.
def save(root: Path, payload: dict[str, object]) -> None:
    """Write the comparison under the market data root."""
    path = Path(root) / "desk" / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


# None when it has never been written, so the page can say so.
def load(root: Path) -> dict[str, object] | None:
    """Return the stored comparison, or None."""
    path = Path(root) / "desk" / FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
