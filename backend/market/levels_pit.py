"""Point-in-time levels from the filings: revenue, earnings, equity, shares.

`edgar.edgar_features` turns the filings into ratios and growth rates. The
valuation analyst needs the levels themselves, dated the same way: the
value that had been filed and was public at each session, never a later
restatement. This reads the stored frames and returns those levels, so
nothing else has to know how the filing store is shaped.
"""

from datetime import date, datetime

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
    """Return the trailing levels per name, known at each session."""
    shape = (len(panel.dates), len(panel.tickers))
    names = (
        "revenue",
        "earnings",
        "gross_profit",
        "operating_cash_flow",
        "capex",
        "shares",
        "equity",
        "debt",
        "cash",
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
        for name in ("operating_cash_flow", "capex"):
            out[name][:, column] = ttm_series(record.facts, name, panel.dates)
        for name in ("shares", "equity", "debt", "cash"):
            out[name][:, column] = edgar._known_series(record.facts, name, panel.dates)[
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
# The splits on file for a name: (date, ratio) pairs from the store's
# corporate-action history, empty when there is none.
def _splits(store: MarketStore, ticker: str, asof=None) -> list[tuple[date, float]]:
    try:
        history = store.read(ticker, asof)
    except Exception:  # noqa: BLE001 - no history is no splits
        return []
    if history is None:
        return []
    return [
        (a.action_date, float(a.value))
        for a in getattr(history, "actions", []) or []
        if a.kind == "split" and float(a.value) > 0
    ]


# A filed share count is on the basis of its filing; the close it is
# multiplied by is on today's split basis. Every split between the session
# a count first appeared (its filing) and the session it is used on
# multiplies it, so NVDA's 10:1 in 2024 does not read as a tenfold
# re-rating until the next 10-Q and a tenfold cheapness before it. When supplied,
# source basis dates take precedence over inferred first-visible rows.
def split_adjusted_shares(
    shares: np.ndarray,
    dates: np.ndarray,
    splits: list[tuple[date, float]],
    *,
    basis_dates: np.ndarray | None = None,
) -> np.ndarray:
    """Return the share series with later splits applied to earlier filings."""
    out = np.asarray(shares, dtype=float).copy()
    if not splits or len(out) == 0:
        return out
    days = np.asarray(dates).astype("datetime64[D]")
    basis = (
        None if basis_dates is None else np.asarray(basis_dates, dtype="datetime64[D]")
    )
    if basis is not None and basis.shape != days.shape:
        raise ValueError(
            "one source filing basis date is required per share observation"
        )
    first_seen = np.zeros(len(out), dtype=int)
    for t in range(1, len(out)):
        same = np.isfinite(out[t]) and np.isfinite(out[t - 1]) and out[t] == out[t - 1]
        first_seen[t] = first_seen[t - 1] if same else t
    split_days = [(np.datetime64(d), r) for d, r in splits]
    for t in range(len(out)):
        if not np.isfinite(out[t]):
            continue
        seen = days[first_seen[t]] if basis is None else basis[t]
        if np.isnat(seen):
            out[t] = np.nan
            continue
        factor = 1.0
        for day, ratio in split_days:
            if seen < day <= days[t]:
                factor *= ratio
        out[t] = out[t] * factor
    return out


# Read valuation inputs with optional strict publication and source share-basis bounds.
def point_in_time_levels(
    store: MarketStore, panel: Panel, asof=None, *, strict_publication: bool = False
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
        known = {
            name: edgar._known_quarters(
                record.facts,
                name,
                panel.dates,
                strict_before_session=strict_publication,
            )
            for name in ("revenue", "net_income", "equity", "shares")
        }
        series = {name: values[0] for name, values in known.items()}
        with np.errstate(all="ignore"):
            out["revenue"][:, column] = series["revenue"][0] * QUARTERS
            out["earnings"][:, column] = series["net_income"][0] * QUARTERS
            out["equity"][:, column] = series["equity"][0]
            out["shares"][:, column] = split_adjusted_shares(
                series["shares"][0],
                panel.dates,
                _splits(store, ticker, asof),
                basis_dates=known["shares"][2] if strict_publication else None,
            )
            out["revenue_growth"][:, column] = (
                series["revenue"][0] / series["revenue"][4] - 1.0
            )
    return out
