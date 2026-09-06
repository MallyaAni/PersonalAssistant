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
