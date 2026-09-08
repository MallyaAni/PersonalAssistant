"""Point-in-time levels from the filings: revenue, earnings, equity, shares.

`edgar.edgar_features` turns the filings into ratios and growth rates. The
valuation analyst needs the levels themselves, dated the same way: the
value that had been filed and was public at each session, never a later
restatement. This reads the stored frames and returns those levels, so
nothing else has to know how the filing store is shaped.
"""

from datetime import datetime

import numpy as np

from backend.market import edgar
from backend.market.panel import Panel
from backend.market.store import MarketStore

EVENTS = "edgar_events"
FACTS = "edgar_facts"
# A quarter annualised. Four trailing quarters would be better, but the
# stored fact series keeps lags 0, 1, 4 and 5, which is what the growth
# features need; the latest quarter times four is the level those lags
# support and it is consistent across every name.
QUARTERS = 4.0


# The trailing four quarters of one fundamental as known at each session:
# the sum of the four most recent distinct quarter-ends that had been
# filed by that session, provided they are consecutive quarters (each
# gap 75 to 105 days) so a missing quarter never leaves a three-quarter
# sum dressed as a year. Derived fourth quarters count like any other.
# NaN until four consecutive quarters are known.
def ttm_series(facts, name: str, dates: np.ndarray) -> np.ndarray:
    """Return (T,) trailing-four-quarter sums of `name`, point in time."""
    rows = sorted((f for f in facts if f.name == name), key=lambda f: (f.filed, f.end))
    size = len(dates)
    out = np.full(size, np.nan)
    if not rows:
        return out
    calendar = dates.astype("datetime64[D]")
    by_end: dict = {}
    pointer = 0
    current = np.nan
    for t in range(size):
        session = calendar[t].astype("datetime64[D]").astype(object)
        changed = False
        while pointer < len(rows) and rows[pointer].filed <= session:
            fact = rows[pointer]
            if fact.end not in by_end:
                by_end[fact.end] = fact.value
                changed = True
            pointer += 1
        if changed:
            current = _four_quarters(by_end)
        out[t] = current
    return out


# The sum of the last four consecutive quarter-ends in `by_end`, or NaN.
def _four_quarters(by_end: dict) -> float:
    ends = sorted(by_end)
    if len(ends) < 4:
        return np.nan
    last = ends[-4:]
    gaps = [(last[i + 1] - last[i]).days for i in range(3)]
    if any(g < 75 or g > 105 for g in gaps):
        return np.nan
    return float(sum(by_end[e] for e in last))


# The trailing-four-quarter levels the second valuation analyst needs:
# revenue, earnings and gross profit over the last four filed quarters,
# and the share count and equity as last reported, all known at each
# session. Revenue growth is the year-over-year growth of the trailing
# sum, so a single quarter cannot swing the growth adjustment.
def trailing_levels(
    store: MarketStore, panel: Panel, asof=None
) -> dict[str, np.ndarray]:
    """Return {"revenue", "earnings", "gross_profit", "shares", "equity", "revenue_growth"}."""
    shape = (len(panel.dates), len(panel.tickers))
    names = (
        "revenue",
        "earnings",
        "gross_profit",
        "shares",
        "equity",
        "revenue_growth",
    )
    out = {name: np.full(shape, np.nan) for name in names}
    for column, ticker in enumerate(panel.tickers):
        events = store.read_frame(EVENTS, ticker, asof)
        facts = store.read_frame(FACTS, ticker, asof)
        if events is None or facts is None:
            continue
        meta = facts[1]
        stamp = meta.get("source_time")
        record = edgar.record_from_frames(
            ticker,
            int(meta.get("cik", "0")),
            events[0],
            facts[0],
            datetime.fromisoformat(stamp) if stamp else datetime.now(),
        )
        out["revenue"][:, column] = ttm_series(record.facts, "revenue", panel.dates)
        out["earnings"][:, column] = ttm_series(record.facts, "net_income", panel.dates)
        out["gross_profit"][:, column] = ttm_series(
            record.facts, "gross_profit", panel.dates
        )
        for name, key in (("shares", "shares"), ("equity", "equity")):
            out[name][:, column] = edgar._known_series(record.facts, key, panel.dates)[
                0
            ][0]
        # Growth of the trailing sum against the trailing sum a year earlier,
        # taken from the same point-in-time series 252 sessions back.
        rev = out["revenue"][:, column]
        growth = np.full(len(rev), np.nan)
        with np.errstate(all="ignore"):
            growth[252:] = rev[252:] / rev[:-252] - 1.0
        out["revenue_growth"][:, column] = np.where(np.isfinite(growth), growth, np.nan)
    return out


# Every level the valuation analyst needs, as (T, N) arrays aligned to the
# panel and known at each session.
def point_in_time_levels(
    store: MarketStore, panel: Panel, asof=None
) -> dict[str, np.ndarray]:
    """Return {"revenue", "earnings", "equity", "shares", "revenue_growth"}."""
    shape = (len(panel.dates), len(panel.tickers))
    out = {
        name: np.full(shape, np.nan)
        for name in ("revenue", "earnings", "equity", "shares", "revenue_growth")
    }
    for column, ticker in enumerate(panel.tickers):
        events = store.read_frame(EVENTS, ticker, asof)
        facts = store.read_frame(FACTS, ticker, asof)
        if events is None or facts is None:
            continue
        meta = facts[1]
        stamp = meta.get("source_time")
        record = edgar.record_from_frames(
            ticker,
            int(meta.get("cik", "0")),
            events[0],
            facts[0],
            datetime.fromisoformat(stamp) if stamp else datetime.now(),
        )
        series = {
            name: edgar._known_series(record.facts, name, panel.dates)[0]
            for name in ("revenue", "net_income", "equity", "shares")
        }
        with np.errstate(all="ignore"):
            out["revenue"][:, column] = series["revenue"][0] * QUARTERS
            out["earnings"][:, column] = series["net_income"][0] * QUARTERS
            out["equity"][:, column] = series["equity"][0]
            out["shares"][:, column] = series["shares"][0]
            out["revenue_growth"][:, column] = (
                series["revenue"][0] / series["revenue"][4] - 1.0
            )
    return out
