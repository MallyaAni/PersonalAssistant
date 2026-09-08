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


# The second valuation analyst: trailing four quarters, own history and
# finer peers. Each leg is a cheapness (higher is cheaper) known at the
# close; the score is the rank blend of the legs named in `legs`, and
# every leg is cited so a measurement can pick the set that earns its
# place (`backend/cli/market_valuation.py`).
LEGS_V2 = (
    "cheap_vs_side",
    "cheap_vs_peers",
    "cheap_vs_history",
    "cheap_earnings",
    "cheap_for_growth",
    "cheap_free_cash_flow",
    "cheap_ev_sales",
)


def opine_v2(
    panel: Panel,
    trailing: dict[str, np.ndarray],
    sides: dict[str, str],
    groups: np.ndarray | None = None,
    legs: tuple[str, ...] = LEGS_V2,
    size_neutral: bool = True,
) -> Opinion:
    """Return the second valuation analyst's Opinion from trailing levels."""
    from backend.market import baselines

    ratios = valuation.multiples(
        panel,
        trailing["revenue"],
        trailing["earnings"],
        trailing["equity"],
        trailing["shares"],
        trailing["revenue_growth"],
    )
    side_groups = valuation.groups_from(panel, sides)
    peer_groups = side_groups
    if groups is not None:
        groups = np.asarray(groups)
        peer_groups = (
            np.broadcast_to(groups[None, :], side_groups.shape)
            if groups.ndim == 1
            else groups
        )
    eligible = np.array([t in sides for t in panel.tickers])
    ps = ratios.get("price_sales")
    with np.errstate(all="ignore"):
        cheap_side = valuation.cheapness(
            ps,
            side_groups,
            cap=ratios.market_cap,
            eligible=eligible,
            size_neutral=size_neutral,
        )
        history = valuation.own_history_rank(ps)
        # Growth the price requires above the side, per year for five
        # years, for the multiple to come back to the side's: cited.
        implied = np.exp(valuation.relative_to_group(ps, side_groups) / 5.0) - 1.0
    with np.errstate(all="ignore"):
        cap = ratios.market_cap
        fcf = trailing.get("operating_cash_flow", np.nan) - trailing.get("capex", 0.0)
        p_fcf = np.log(cap / np.where(fcf > 0, fcf, np.nan))
        debt = np.nan_to_num(trailing.get("debt", np.nan), nan=0.0)
        cash = np.nan_to_num(trailing.get("cash", np.nan), nan=0.0)
        ev = cap + debt - cash
        ev_sales = np.log(
            np.where(ev > 0, ev, np.nan)
            / np.where(trailing["revenue"] > 0, trailing["revenue"], np.nan)
        )
    evidence = {
        "cheap_vs_side": cheap_side,
        "cheap_free_cash_flow": -valuation.relative_to_group(p_fcf, side_groups),
        "cheap_ev_sales": -valuation.relative_to_group(ev_sales, side_groups),
        "price_free_cash_flow": p_fcf,
        "ev_sales": ev_sales,
        "cheap_vs_peers": -valuation.relative_to_group(ps, peer_groups),
        "cheap_vs_history": -history,
        "cheap_earnings": -valuation.relative_to_group(
            ratios.get("price_earnings"), side_groups
        ),
        "cheap_for_growth": -valuation.relative_to_group(
            ratios.get("price_sales_growth"), side_groups
        ),
        "price_sales": ps,
        "price_earnings": ratios.get("price_earnings"),
        "price_book": ratios.get("price_book"),
        "price_sales_growth": ratios.get("price_sales_growth"),
        "implied_growth_vs_side": implied,
        "market_cap": ratios.market_cap,
    }
    scores = baselines.rank_blend(*[evidence[name] for name in legs])
    scores = np.where(eligible[None, :], scores, np.nan)
    return Opinion(NAME, scores, evidence)
