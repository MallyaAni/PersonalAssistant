"""The fundamental analyst: what the filings say.

Reads the point-in-time EDGAR layer. The score is the blend that measured
positive beta-adjusted (revenue growth, sequential growth, gross margin,
acceleration); the balance-sheet instants (share issuance, asset growth,
book-to-market) measured nothing on this universe and are cited, not scored.
"""

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.market import baselines, edgar

NAME = "fundamental"
SCORED = ("revenue_yoy", "revenue_qoq", "gross_margin", "revenue_acceleration")
CITED = SCORED + (
    "eps_change_yoy",
    "net_margin",
    "capex_to_revenue",
    "share_issuance",
    "asset_growth",
    "book_to_market",
    "sessions_since_earnings",
)


# Score every name from its filed fundamentals; no view where none are filed.
def opine(extra: np.ndarray) -> Opinion:
    """Return the fundamental analyst's Opinion from the EDGAR feature block."""
    names = edgar.FEATURE_NAMES
    has = extra[:, :, names.index("has_fundamentals")] > 0
    legs = [
        np.where(has, extra[:, :, names.index(n)].astype(float), np.nan) for n in SCORED
    ]
    scores = baselines.rank_blend(*legs)
    evidence = {
        n: np.where(has, extra[:, :, names.index(n)].astype(float), np.nan)
        for n in CITED
    }
    return Opinion(NAME, scores, evidence)
