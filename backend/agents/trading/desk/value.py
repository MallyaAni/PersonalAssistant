"""The valuation analyst: what the market pays for this, against its peers.

The market prices a whole side of the book at some multiple of sales. A
name sitting well below its side's median has tended to catch up. Measured
on the 90 book names, beta-adjusted: rank IC 0.048 (t 3.6) over 20
sessions and 0.077 (t 3.3) over 60, positive in nine of twelve years, and
its rank is *negatively* correlated with the other analysts (-0.16 with
the graded score), so it is information the desk did not have. Blended
with the existing grade the score reaches 0.057 (t 4.2) at 20 sessions.

Part of the raw signal is a small-company tilt (+0.37 rank correlation
with small size). The analyst is size-neutral by default: it also ranks
each name against others of a similar size, which costs signal (0.036,
t 2.3) and removes a bet on size that a large-company market would punish.

Earnings and book multiples measured less (0.028 and 0.016) and are cited
rather than scored, since two thirds of these names have no positive
earnings in a given quarter and the multiple is simply absent for them.
"""

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.market import valuation
from backend.market.panel import Panel

NAME = "value"
SCORED = "price_sales"
CITED = ("price_sales", "price_earnings", "price_book", "price_sales_growth")


# Score every name by how cheap it is against its side of the book; no view
# where the filings give no multiple.
def opine(
    panel: Panel,
    levels: dict[str, np.ndarray],
    sides: dict[str, str],
    size_neutral: bool = True,
) -> Opinion:
    """Return the valuation analyst's Opinion."""
    ratios = valuation.multiples(
        panel,
        levels["revenue"],
        levels["earnings"],
        levels["equity"],
        levels["shares"],
        levels["revenue_growth"],
    )
    peers = valuation.groups_from(panel, sides)
    eligible = np.array([t in sides for t in panel.tickers])
    scores = valuation.cheapness(
        ratios.get(SCORED),
        peers,
        cap=ratios.market_cap,
        eligible=eligible,
        size_neutral=size_neutral,
    )
    scores = np.where(eligible[None, :], scores, np.nan)
    evidence = {name: ratios.get(name) for name in CITED}
    evidence["cheap_vs_side"] = -valuation.relative_to_group(ratios.get(SCORED), peers)
    evidence["market_cap"] = ratios.market_cap
    return Opinion(NAME, scores, evidence)
