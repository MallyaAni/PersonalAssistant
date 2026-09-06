"""What the market pays for a name, against what it pays for its peers.

The filings give revenue, earnings, equity and the share count, each dated
by when it was filed, so a multiple can be formed at any past session
without knowing anything later. Forward multiples would need analyst
consensus estimates, which are not free here; the trailing multiple and
the growth rate together are the honest substitute for "cheap for what it
grows".

The number that measured is not the multiple itself but the distance from
the peer group's median multiple: the market prices a whole side of the
book at some level, and a name sitting well under that level has tended to
catch up. Measured on the 90 book names, beta-adjusted, against the
distance from the side's (AI or software) median log price-to-sales:
rank IC 0.048 (t 3.6) over 20 sessions and 0.077 (t 3.3) over 60, positive
in nine of the twelve years on file.

Part of that is a small-company tilt: the cheap-against-peers rank
correlates +0.37 with the small-capitalisation rank, and small alone
measures 0.023 (t 1.5). `size_neutral` strips it by also ranking each name
against others of a similar size, which costs signal (0.036, t 2.3) and
removes a bet on size that a large-company market would punish.
"""

from dataclasses import dataclass

import numpy as np

from backend.market.panel import Panel

MULTIPLES = ("price_sales", "price_earnings", "price_book", "price_sales_growth")
SIZE_BUCKETS = 3
MIN_PEERS = 3


@dataclass(frozen=True)
class Multiples:
    """Point-in-time valuation multiples, as logs, per session and name."""

    price_sales: np.ndarray
    price_earnings: np.ndarray
    price_book: np.ndarray
    price_sales_growth: np.ndarray
    market_cap: np.ndarray

    # One named multiple.
    def get(self, name: str) -> np.ndarray:
        """Return the (T, N) log multiple called `name`."""
        return getattr(self, name)


# Log multiples from point-in-time levels. Each input is (T, N) and holds
# the value that was filed and public at that session: revenue and earnings
# annualised from the latest known quarter, the share count and equity as
# last reported. A multiple is NaN wherever its denominator is not positive,
# so a loss-making name simply has no earnings multiple rather than a
# meaningless one.
def multiples(
    panel: Panel,
    revenue: np.ndarray,
    earnings: np.ndarray,
    equity: np.ndarray,
    shares: np.ndarray,
    revenue_growth: np.ndarray,
) -> Multiples:
    """Return the Multiples for the panel."""
    with np.errstate(all="ignore"):
        cap = shares * panel.close
        cap = np.where(cap > 0, cap, np.nan)
        ps = np.log(cap / np.where(revenue > 0, revenue, np.nan))
        pe = np.log(cap / np.where(earnings > 0, earnings, np.nan))
        pb = np.log(cap / np.where(equity > 0, equity, np.nan))
        # Cheap for what it grows: the sales multiple less the growth rate,
        # clipped so a single wild quarter cannot dominate.
        psg = ps - np.log1p(np.clip(revenue_growth, -0.9, 5.0))
    return Multiples(ps, pe, pb, psg, cap)


# Each name's value minus the median of the same value among the names
# sharing its group on that session. A group with fewer than `MIN_PEERS`
# known values gives no opinion.
def relative_to_group(values: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Return (T, N) distances from each group's median."""
    out = np.full(values.shape, np.nan)
    for t in range(values.shape[0]):
        row, ids = values[t], groups[t]
        for label in np.unique(ids[ids >= 0]):
            members = (ids == label) & np.isfinite(row)
            if members.sum() >= MIN_PEERS:
                out[t, members] = row[members] - np.median(row[members])
    return out


# Group ids from a ticker-to-group mapping, constant through time.
def groups_from(panel: Panel, mapping: dict[str, str]) -> np.ndarray:
    """Return (T, N) integer group ids, -1 where a name has no group."""
    labels = sorted(set(mapping.values()))
    ids = np.full((len(panel.dates), len(panel.tickers)), -1, dtype=int)
    for column, ticker in enumerate(panel.tickers):
        group = mapping.get(ticker)
        if group is not None:
            ids[:, column] = labels.index(group)
    return ids


# Size buckets on each session: the eligible names split into thirds by
# market capitalisation, smallest first. Reads only that session.
def size_groups(cap: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    """Return (T, N) size-bucket ids, -1 where the size is unknown."""
    ids = np.full(cap.shape, -1, dtype=int)
    for t in range(cap.shape[0]):
        known = np.flatnonzero(np.isfinite(cap[t]) & eligible)
        if len(known) < SIZE_BUCKETS * MIN_PEERS:
            continue
        order = known[np.argsort(cap[t, known])]
        for i, column in enumerate(order):
            ids[t, column] = min(SIZE_BUCKETS - 1, i * SIZE_BUCKETS // len(order))
    return ids


# The valuation score: how cheap a name is against its peers. Positive is
# cheap. With `size_neutral`, the peer comparison is averaged with one made
# against names of a similar size, which removes most of the small-company
# tilt in the raw version.
def cheapness(
    multiple: np.ndarray,
    peer_groups: np.ndarray,
    cap: np.ndarray | None = None,
    eligible: np.ndarray | None = None,
    size_neutral: bool = False,
) -> np.ndarray:
    """Return (T, N) cheapness against peers; higher is cheaper."""
    from backend.market.baselines import rank_blend

    against_peers = -relative_to_group(multiple, peer_groups)
    if not size_neutral or cap is None or eligible is None:
        return against_peers
    against_size = -relative_to_group(multiple, size_groups(cap, eligible))
    blended = rank_blend(against_peers, against_size)
    # Too few names to form size thirds leaves the size view empty; the
    # peer view still stands, so the analyst keeps its opinion rather than
    # falling silent.
    return np.where(np.isfinite(blended), blended, against_peers)
