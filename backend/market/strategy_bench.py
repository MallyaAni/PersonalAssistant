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

from backend.market.benchmarks import BenchmarkSeries

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


# The metric keys every comparison row carries. An unavailable row keeps the
# same keys with null values, so the payload shape does not depend on whether
# a benchmark could be measured.
METRIC_KEYS = ("total", "annual", "volatility", "drawdown", "sharpe")


# The numbers every candidate is judged on, from one daily return series.
#
# Any missing return here is a genuinely missing evaluated session and is
# reported as None rather than silently measured as flat cash: a benchmark gap
# must have failed coverage in the loader before it reaches this function, and
# `build` removes the one deliberate initial NAV slot before calling this. So
# a leading NaN is not special-cased here - it is a missing evaluated return
# and rejects the whole measurement, which is what keeps a missing early
# session from becoming a shorter, favorable window.
def stats(daily: np.ndarray) -> dict[str, float | None]:
    """Return total, annual, volatility, drawdown and Sharpe for a series."""
    r = np.asarray(daily, dtype=float)
    if len(r) < 5:
        return {k: None for k in METRIC_KEYS}
    if not np.isfinite(r).all():
        return {k: None for k in METRIC_KEYS}
    curve = np.cumprod(1 + r)
    years = len(r) / 252
    total = float(curve[-1] - 1)
    annual = float(curve[-1] ** (1 / years) - 1) if years > 0.15 else None
    vol = float(np.std(r) * np.sqrt(252))
    drawdown = float((curve / np.maximum.accumulate(np.r_[1.0, curve])[1:] - 1).min())
    sharpe = float(np.mean(r) * 252 / vol) if vol > 0 else None
    return {
        "total": total,
        "annual": annual,
        "volatility": vol,
        "drawdown": drawdown,
        "sharpe": sharpe,
    }


# The evaluated returns of one series inside one regime block: the masked
# slice, minus the single intentional initial NAV slot when the block starts
# at the series' calendar position 0 and that value is non-finite. Anything
# else missing stays and is rejected by `stats`.
def _evaluated_block(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return the block's evaluated returns, dropping the initial NAV slot."""
    block = np.asarray(values, dtype=float)[mask]
    if mask[0] and len(block) and np.isnan(block[0]):
        block = block[1:]
    return block


# Whether two session calendars are the same, compared as ISO dates.
def _same_calendar(a, b) -> bool:
    """Return True when `a` and `b` name the same sessions in the same order."""
    if len(a) != len(b):
        return False
    return all(str(x)[:10] == str(y)[:10] for x, y in zip(a, b, strict=True))


# One series' aligned daily returns, or the reason it is unavailable. An array
# or an available benchmark that does not line up with the comparison's
# session calendar is reported as unavailable rather than silently aligned by
# array offset.
def _series_array(name: str, values, days) -> tuple[np.ndarray | None, str | None]:
    """Return (aligned daily returns, unavailable reason) for one series."""
    if isinstance(values, BenchmarkSeries):
        if not values.available:
            return None, values.reason
        if (
            values.sessions is None
            or len(values.sessions) != len(days)
            or not _same_calendar(values.sessions, days)
        ):
            return None, (
                f"{name} calendar does not match the comparison's executable calendar"
            )
        values = values.daily
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or len(arr) != len(days):
        return None, (
            f"{name} series has {arr.size} returns, not the {len(days)} "
            "sessions of the comparison's executable calendar"
        )
    return arr, None


# One payload: every candidate over every regime, plus what each regime is.
#
# `series` maps a name to either a daily return array aligned to `sessions`
# (a candidate, or an available benchmark) or a `benchmarks.BenchmarkSeries`
# that says it is unavailable. An unavailable benchmark is reported in every
# block and in a top-level `unavailable` list - populated outside the regime
# loop, so the metadata is present even when no regime holds five sessions -
# and is never silently dropped.
def build(
    sessions: np.ndarray,
    series: dict[str, np.ndarray | BenchmarkSeries],
    note: str = "",
) -> dict[str, object]:
    """Return the comparison for `series`, each aligned to `sessions`."""
    days = np.array(
        [d.astype("datetime64[D]").astype(object) for d in sessions], dtype=object
    )
    total_sessions = len(days)
    state = {name: _series_array(name, values, days) for name, values in series.items()}
    unavailable = [
        {"name": name, "reason": reason}
        for name, (_, reason) in state.items()
        if reason is not None
    ]
    blocks = []
    for label, lo, hi in REGIMES:
        mask = np.array([lo <= d <= hi for d in days])
        count = int(mask.sum())
        if count < 5:
            continue
        rows = []
        for name, (arr, reason) in state.items():
            if arr is None:
                row = {
                    "name": name,
                    "unavailable": reason,
                    "sessions": count,
                    **{k: None for k in METRIC_KEYS},
                }
            else:
                evaluated = _evaluated_block(arr, mask)
                row = {"name": name, **stats(evaluated)}
                if not np.isfinite(evaluated).all():
                    row["unavailable"] = "Missing or non-finite evaluated returns"
            rows.append(row)
        blocks.append(
            {
                "regime": label,
                "from": str(days[mask][0]),
                "to": str(days[mask][-1]),
                "sessions": count,
                "share": count / total_sessions if total_sessions else None,
                "rows": rows,
            }
        )
    return {
        "version": "strategy-bench/2",
        "sessions": total_sessions,
        "from": str(days[0]) if total_sessions else None,
        "to": str(days[-1]) if total_sessions else None,
        "note": note,
        "method": (
            "v2: each benchmark is loaded independently from the store, must "
            "carry adjusted prices and complete coverage of the executable "
            "calendar, and is priced like the strategy - the same starting "
            "capital, first fill at the first next-open, the same one-way "
            "cost, dividend-adjusted holding, terminal holdings marked at "
            "the last close with no hypothetical liquidation. The first "
            "return of every series is the intentional initial NAV and is "
            "removed at its calendar position before measurement; a missing "
            "evaluated session is reported unavailable, never measured as "
            "flat cash."
        ),
        "unavailable": unavailable,
        "caveat": (
            "Survivorship: the constituent list is today's, delisted names are "
            "absent. Bias need not cancel between policies. These retrospective "
            "comparisons do not establish achievable returns or an optimal strategy."
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
