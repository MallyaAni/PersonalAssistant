"""A name's peer group from prices, point in time: shared by the S2 study and the desk.

`docs/research/sector-sells-plan-2026-10-01.md` fixed every definition and
constant here before any code or fill was read. The study
(`backend/market/sector_sells.py` on `research/sector-sells`) and the live
executor (`backend/agents/trading/desk/peer_sells.py`) both import them from
this one module, so the rule the desk would trade is the rule the study
priced, to the bit.

**The peer group** is computed from prices, never from a sector label: at
session t, each name's daily log returns over the 60 sessions t-59..t
(closes t-60..t) are regressed on the benchmark's (SPY) with an intercept,
and the residuals correlated. The name's peers P_i(t) are the k = 5 eligible
names with the highest residual correlation (ties by panel column); a peer
must have a complete window, a non-zero residual variance and be a
point-in-time member at t. sigma_g(t) is the standard deviation (ddof 1)
over t-19..t of the peers' equal-weight daily log return. Nothing after t
enters t's group.

**The peer group's morning** R_g is the equal-weight mean, over the peers
priced, of ln(first 15-minute bar close of t+1 / close of t); undefined with
fewer than 3 of the 5 priced.

**The triggers**: the deferral (G1, G3) fires when R_g > sigma_g; the
market-on-close rule (G2) when R_g > ln(1 + DIP), DIP the board's own 1%.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from backend.market.fill_timing import DIP

# The plan's fixed parameters (registered 2026-10-01; never searched).
K_PEERS = 5
CORR_SESSIONS = 60
PEER_SIGMA_SESSIONS = 20
MIN_PRICED_PEERS = 3
# G2's threshold: the peer group up more than the name's own 1% pop level.
CLOSE_THRESHOLD = math.log1p(DIP)

assert DIP == 0.01


@dataclass(frozen=True)
class PeerGroups:
    """Every name's peer group on every session, computed from data on or before it."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    members: np.ndarray  # (T, N, K) int64 panel columns, -1 where no group
    corr: np.ndarray  # (T, N, K) residual correlation of each peer, NaN where none
    sigma: np.ndarray  # (T, N) sigma_g: the peer group's 20-session daily std
    has: np.ndarray  # (T, N) bool: a peer group exists at t


# Daily log returns of a (T, N) matrix of adjusted closes: row s is
# ln(C[s] / C[s-1]); the first row and any gap are NaN.
def log_returns(adj_close: np.ndarray) -> np.ndarray:
    """Return the (T, N) daily log returns."""
    closes = np.asarray(adj_close, dtype=float)
    out = np.full(closes.shape, np.nan)
    with np.errstate(all="ignore"):
        out[1:] = np.log(closes[1:] / closes[:-1])
    return out


# The residuals of each column of `returns` (W, N) on `market` (W,) with
# an intercept (OLS): (r - mean r) - b (m - mean m), b the column's slope.
def residuals(returns: np.ndarray, market: np.ndarray) -> np.ndarray:
    """Return the (W, N) OLS residuals on the market with an intercept."""
    r = np.asarray(returns, dtype=float)
    m = np.asarray(market, dtype=float)
    mc = m - m.mean()
    rc = r - r.mean(axis=0)
    denom = float(mc @ mc)
    if not denom > 0:
        return rc
    beta = (mc @ rc) / denom
    return rc - mc[:, None] * beta[None, :]


# One session's peer groups from the window's returns (W, N) and the
# market's (W,): the residual correlation of every pair of names with a
# complete window and a non-zero residual variance, then per such name the
# k highest among the `peer_ok` columns other than itself (ties by column),
# when there are at least k. Returns ((N, k) columns, (N, k) correlations,
# (N,) has a group); -1 / NaN / False elsewhere.
def session_peers(
    returns: np.ndarray,
    market: np.ndarray,
    peer_ok: np.ndarray,
    k: int = K_PEERS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (members, corr, has) for one session."""
    r = np.asarray(returns, dtype=float)
    n = r.shape[1]
    members = np.full((n, k), -1, dtype=np.int64)
    corr = np.full((n, k), np.nan)
    has = np.zeros(n, dtype=bool)
    m = np.asarray(market, dtype=float)
    if not np.isfinite(m).all():
        return members, corr, has
    valid = np.isfinite(r).all(axis=0)
    if not valid.any():
        return members, corr, has
    cols = np.flatnonzero(valid)
    e = residuals(r[:, cols], m)
    norm = np.sqrt((e * e).sum(axis=0))
    keep = norm > 0
    cols = cols[keep]
    if len(cols) < 2:
        return members, corr, has
    z = e[:, keep] / norm[keep]
    full = np.full((n, n), np.nan)
    full[np.ix_(cols, cols)] = np.clip(z.T @ z, -1.0, 1.0)
    candidate = np.zeros(n, dtype=bool)
    candidate[cols] = True
    candidate &= np.asarray(peer_ok, dtype=bool)
    score = np.where(candidate[None, :], full, -np.inf)
    np.fill_diagonal(score, -np.inf)
    order = np.argsort(-score, axis=1, kind="stable")[:, :k]
    picked = np.take_along_axis(score, order, axis=1)
    enough = np.isfinite(picked).all(axis=1)
    rows = np.zeros(n, dtype=bool)
    rows[cols] = True
    has = rows & enough
    members[has] = order[has]
    corr[has] = picked[has]
    return members, corr, has


# The peer groups and sigma_g of every name at one session t, from the full
# (T, N) returns, the same returns with the market column masked out, the
# market's (T,) returns and the (N,) membership row at t. The window is
# t-59..t and sigma_g's t-19..t: nothing after t is read. `peer_groups`
# calls this for every t and the desk calls it for the last one, so the two
# cannot compute different groups.
def groups_at(
    returns: np.ndarray,
    masked: np.ndarray,
    market_returns: np.ndarray,
    member_ok: np.ndarray,
    t: int,
    k: int = K_PEERS,
    window: int = CORR_SESSIONS,
    sigma_sessions: int = PEER_SIGMA_SESSIONS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N, k) members, (N, k) corr, (N,) sigma_g, (N,) has) at t."""
    n = returns.shape[1]
    lo = t - window + 1
    if lo < 1:
        return (
            np.full((n, k), -1, dtype=np.int64),
            np.full((n, k), np.nan),
            np.full(n, np.nan),
            np.zeros(n, dtype=bool),
        )
    m_t, c_t, h_t = session_peers(
        masked[lo : t + 1], market_returns[lo : t + 1], member_ok, k
    )
    sigma = np.full(n, np.nan)
    if h_t.any():
        recent = returns[t - sigma_sessions + 1 : t + 1]
        group = recent[:, np.where(m_t >= 0, m_t, 0)].mean(axis=2)
        with np.errstate(all="ignore"):
            s = group.std(axis=0, ddof=1)
        sigma = np.where(h_t, s, np.nan)
    return m_t, c_t, sigma, h_t


# The returns, the market-masked returns, the market's returns and the
# membership grid (benchmark never a peer) that `groups_at` reads, from
# the (T, N) adjusted closes, the market column and the (T, N) point-in-time
# membership (None: every name a member).
def prepare(
    adj_close: np.ndarray, market: int, membership: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (returns, masked returns, market returns, membership)."""
    closes = np.asarray(adj_close, dtype=float)
    length, n = closes.shape
    returns = log_returns(closes)
    mkt = returns[:, market].copy()
    names = np.ones(n, dtype=bool)
    names[market] = False
    ok = (
        np.ones((length, n), dtype=bool)
        if membership is None
        else np.asarray(membership, dtype=bool).copy()
    )
    if ok.shape != (length, n):
        raise ValueError("membership must be on the closes' (T, N) grid")
    ok &= names[None, :]
    masked = returns.copy()
    masked[:, market] = np.nan
    return returns, masked, mkt, ok


# Every name's peer group on every session t from the (T, N) adjusted
# closes, the market's column and the (T, N) point-in-time membership
# (None: every name a member): the residual correlations over t-59..t, the
# k best members at t, and sigma_g over t-19..t of the peers' equal-weight
# daily return. The market column is never a name or a peer.
def peer_groups(
    dates: np.ndarray,
    tickers: Sequence[str],
    adj_close: np.ndarray,
    market: int,
    membership: np.ndarray | None = None,
    k: int = K_PEERS,
    window: int = CORR_SESSIONS,
    sigma_sessions: int = PEER_SIGMA_SESSIONS,
) -> PeerGroups:
    """Return the PeerGroups."""
    returns, masked, mkt, ok = prepare(adj_close, market, membership)
    length, n = returns.shape
    members = np.full((length, n, k), -1, dtype=np.int64)
    corr = np.full((length, n, k), np.nan)
    sigma = np.full((length, n), np.nan)
    has = np.zeros((length, n), dtype=bool)
    for t in range(window, length):
        members[t], corr[t], sigma[t], has[t] = groups_at(
            returns, masked, mkt, ok[t], t, k, window, sigma_sessions
        )
    return PeerGroups(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        tickers=tuple(str(x) for x in tickers),
        members=members,
        corr=corr,
        sigma=sigma,
        has=has,
    )


# R_g for one name and one morning: the mean of the peers' first-bar log
# returns over those priced (finite), when at least `min_priced` are; with
# the count priced. None when too few are priced.
def group_morning(
    first_returns: Iterable[float | None], min_priced: int = MIN_PRICED_PEERS
) -> tuple[float | None, int]:
    """Return (R_g or None, peers priced)."""
    priced = [
        float(x) for x in first_returns if x is not None and math.isfinite(float(x))
    ]
    if len(priced) < min_priced:
        return None, len(priced)
    return sum(priced) / len(priced), len(priced)


# The deferral's trigger (G1, G3): the peer group's morning above its usual
# daily move. Works on scalars and arrays; NaN on either side never fires.
def defer_fires(morning, sigma):
    """Return R_g > sigma_g where both are finite."""
    r = np.asarray(morning, dtype=float)
    s = np.asarray(sigma, dtype=float)
    with np.errstate(invalid="ignore"):
        return np.isfinite(r) & np.isfinite(s) & (r > s)


# The market-on-close trigger (G2): the peer group's morning above
# ln(1.01). Works on scalars and arrays; NaN never fires.
def close_fires(morning):
    """Return R_g > ln(1 + DIP) where R_g is finite."""
    r = np.asarray(morning, dtype=float)
    with np.errstate(invalid="ignore"):
        return np.isfinite(r) & (r > CLOSE_THRESHOLD)
