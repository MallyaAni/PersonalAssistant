"""Support and resistance across timeframes: point-in-time levels for every bar.

The pre-registration is `docs/research/sr-levels-plan-2026-09-29.md`. This
module computes exactly the levels it fixes, the zone around each, and
what the study and the fill conventions read from them. It decides
nothing and prices nothing.

The levels, and the earliest moment each is known
-------------------------------------------------
Twenty-two levels in twelve families (`KINDS`, `FAMILY_OF`). The daily
structure is computed from the panel's rows up to and including the prior
session, so it is known at the prior close and in force all session:

  swing_low_{20,60,250}   the nearest confirmed swing low below the prior
                          close among those confirmed in the last 20 / 60 /
                          250 sessions (`levels.swing_points`, confirmed
                          `levels.SWING` sessions after it prints;
                          `levels._nearest`)
  swing_high_{20,60,250}  the nearest confirmed swing high above it; a swing
                          several horizons find is kept once, at the shortest
  sma_50, sma_200         simple means of the adjusted closes (`technical.sma`)
  wsma_21                 the simple mean of the last 21 completed weekly
                          closes: a week is Monday to Friday, its close is its
                          last adjusted close, and it is completed for a
                          session in a later week
  high_52w, low_52w       the 252 sessions' highest high and lowest low
                          (`levels._rolling`)
  prior_day_{high,low,close}
  prior_week_{high,low}   the most recent completed week's extremes

`node_1..3`, the volume nodes, are also known at the prior close. They are
built from the prior 20 complete cube sessions: 0.25%-wide log-price bins
anchored at 1, each bar's volume spread evenly over the bins its low-high
range covers. A node is a local peak of that profile (above the bin below,
at least the bin above), the three largest by volume, each priced at its
bin's geometric midpoint.

The intraday levels are known only once formed:

  or_high, or_low  the first two bars' extremes, in force from the 10:00
                   bar close (slot 2 on)
  vwap             the running session VWAP, proxied by bar closes weighted
                   by bar volume; the level in force during bar s is the
                   VWAP at bar s-1's close

The levels in force during bar s are therefore all known at bar s-1's
close. A level with no definition yet is NaN, never filled in.

Basis. Everything is on the panel's adjusted basis: the daily highs and
lows scaled by `adj_close / close` as `levels.py` does, and the cube's
raw bars multiplied by the per-session `scale` the caller passes
(`fill_timing.session_scale`, the split-safe ratio of the panel's adjusted
close to the cube's official close). `scale` is the one input from a
session's end. It is a corporate-action factor that moves every bar of the
session by one common factor, so comparisons inside a session are exact.

Zone and confluence
-------------------
The zone of a level L is [L - w, L + w]. The half-width w is
max(ATR_SHARE × ATR14, MIN_WIDTH × prior close) on the adjusted basis,
fixed for the session. ATR14 is `backtest._atr` through the prior close.
The confluence of a zone is the number of distinct level prices inside
it, L included. Identical prices count once: a prior-day low that is also
the prior week's low is one level, recorded under both families.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk import backtest
from backend.market import levels as daily_structure
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.technical import sma

# Horizons for the swing levels, in sessions since confirmation.
SWING_HORIZONS = (20, 60, 250)
# The daily simple moving averages, in sessions.
SMA_LENGTHS = (50, 200)
# The weekly simple moving average, in completed weeks.
WEEKLY_SMA_WEEKS = 21
# The 52-week range, in sessions.
YEAR_SESSIONS = 252
# The zone half-width: max(ATR_SHARE x ATR over ATR_SESSIONS, MIN_WIDTH x prior close).
ATR_SESSIONS = 14
ATR_SHARE = 0.25
MIN_WIDTH = 0.003
# The opening range is the first two bars (09:30-10:00); the first bar
# that can use it, and the first bar the study and the conventions read,
# is slot 2 (10:00-10:15, closing 10:15).
OPENING_RANGE_SLOTS = 2
FIRST_SLOT = OPENING_RANGE_SLOTS
# The volume profile: prior cube sessions, bin width in log price, nodes kept.
PROFILE_SESSIONS = 20
PROFILE_BIN = math.log(1.0025)
NODE_COUNT = 3

# The daily structure, in force all session from the prior close.
DAILY_KINDS: tuple[str, ...] = (
    "swing_low_20",
    "swing_low_60",
    "swing_low_250",
    "swing_high_20",
    "swing_high_60",
    "swing_high_250",
    "sma_50",
    "sma_200",
    "wsma_21",
    "high_52w",
    "low_52w",
    "prior_day_high",
    "prior_day_low",
    "prior_day_close",
    "prior_week_high",
    "prior_week_low",
)
# The volume nodes of the prior 20 cube sessions, also from the prior close.
NODE_KINDS: tuple[str, ...] = tuple(f"node_{i + 1}" for i in range(NODE_COUNT))
# The intraday levels, known only once formed.
INTRADAY_KINDS: tuple[str, ...] = ("or_high", "or_low", "vwap")
# Every level, in the order of the last axis of `SessionLevels.levels`.
KINDS: tuple[str, ...] = DAILY_KINDS + NODE_KINDS + INTRADAY_KINDS
# The family each level belongs to, for the by-type tables.
FAMILY_OF: dict[str, str] = {
    "swing_low_20": "swing_20",
    "swing_high_20": "swing_20",
    "swing_low_60": "swing_60",
    "swing_high_60": "swing_60",
    "swing_low_250": "swing_250",
    "swing_high_250": "swing_250",
    "sma_50": "sma_50",
    "sma_200": "sma_200",
    "wsma_21": "wsma_21",
    "high_52w": "range_52w",
    "low_52w": "range_52w",
    "prior_day_high": "prior_day",
    "prior_day_low": "prior_day",
    "prior_day_close": "prior_day",
    "prior_week_high": "prior_week",
    "prior_week_low": "prior_week",
    "node_1": "volume_node",
    "node_2": "volume_node",
    "node_3": "volume_node",
    "or_high": "opening_range",
    "or_low": "opening_range",
    "vwap": "vwap",
}
FAMILIES: tuple[str, ...] = (
    "swing_20",
    "swing_60",
    "swing_250",
    "sma_50",
    "sma_200",
    "wsma_21",
    "range_52w",
    "prior_day",
    "prior_week",
    "volume_node",
    "opening_range",
    "vwap",
)
# One bit per family, per level, in KINDS order: a touch's families are
# the OR of the bits of the levels inside its zone.
FAMILY_BITS = np.array(
    [1 << FAMILIES.index(FAMILY_OF[k]) for k in KINDS], dtype=np.int64
)
SUPPORT = "support"
RESISTANCE = "resistance"
SIDES = (SUPPORT, RESISTANCE)

assert len(KINDS) == 22
assert len(set(KINDS)) == 22
assert set(FAMILY_OF) == set(KINDS)
assert set(FAMILY_OF.values()) == set(FAMILIES)
assert FIRST_SLOT == 2


@dataclass(frozen=True)
class DailyLevels:
    """The daily structure and the zone half-width in force during each session."""

    dates: np.ndarray  # (T,) the panel's sessions
    tickers: tuple[str, ...]
    levels: np.ndarray  # (T, N, len(DAILY_KINDS)): row d from rows <= d - 1
    width: np.ndarray  # (T, N) zone half-width w for session d


@dataclass(frozen=True)
class SessionLevels:
    """One name's levels in force during every regular bar of its cube sessions."""

    dates: np.ndarray  # (N,) the cube's sessions
    open: np.ndarray  # (N, 26) adjusted bar opens
    high: np.ndarray  # (N, 26) adjusted
    low: np.ndarray  # (N, 26) adjusted
    close: np.ndarray  # (N, 26) adjusted
    width: np.ndarray  # (N,) zone half-width, adjusted dollars
    levels: np.ndarray  # (N, 26, len(KINDS)) the levels in force during each bar

    # Sessions held.
    def __len__(self) -> int:
        return int(len(self.dates))


@dataclass(frozen=True)
class Touches:
    """One side's zone touches per (session, slot) and the zone each touched."""

    hit: np.ndarray  # (N, 26) bool
    level: np.ndarray  # (N, 26) the touched zone's level L*, NaN off a touch
    families: np.ndarray  # (N, 26) int64 bitmask of the families inside the zone
    confluence: np.ndarray  # (N, 26) distinct level prices in the zone, 0 off a touch


@dataclass(frozen=True)
class CloseZones:
    """Per (session, slot): the largest confluence of a zone holding the bar's close."""

    support: np.ndarray  # (N, 26) int: zones of levels below the prior bar's close
    resistance: np.ndarray  # (N, 26) int: zones of levels above it


# The value each row of `values` had one session earlier: row d gets row
# d - 1, row 0 gets NaN. This is the step from "known at the close of d - 1"
# to "in force during session d".
def _in_force_next(values: np.ndarray) -> np.ndarray:
    """Return `values` shifted down one row, NaN on the first."""
    out = np.full(values.shape, np.nan)
    out[1:] = values[:-1]
    return out


# A swing found by several horizons is one level: each later horizon's
# value is dropped (NaN) wherever it equals a shorter horizon's, so it is
# kept once, at its shortest horizon.
def _keep_shortest(by_horizon: list[np.ndarray]) -> list[np.ndarray]:
    """Return the per-horizon arrays with repeats of shorter horizons removed."""
    out = [by_horizon[0]]
    for i in range(1, len(by_horizon)):
        seen = np.zeros(by_horizon[i].shape, dtype=bool)
        for shorter in by_horizon[:i]:
            seen |= by_horizon[i] == shorter
        out.append(np.where(seen, np.nan, by_horizon[i]))
    return out


# The Monday-to-Friday week of each date, as an integer. The epoch is a
# Thursday, so three days are added to make weeks start on Monday (the
# convention `technical._weekly_ema` uses).
def week_of(dates: np.ndarray) -> np.ndarray:
    """Return (T,) week numbers, changing on each Monday."""
    days = np.asarray(dates, dtype="datetime64[D]").astype(np.int64)
    return (days + 3) // 7


# The completed-week levels in force during each session: the 21-week
# simple mean of weekly closes and the prior week's high and low, from the
# most recent week that ends before the session's own week begins. A
# week's close is its last finite close, its high and low the extremes of
# its sessions. Every row of those weeks is before the session, so nothing
# of the session's own week is read.
def _completed_weeks(
    dates: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (wsma_21, prior_week_high, prior_week_low), each (T, N)."""
    weeks = week_of(dates)
    rows, names = close.shape
    unique, starts = np.unique(weeks, return_index=True)
    ends = np.append(starts[1:], rows)
    weekly_close = np.full((len(unique), names), np.nan)
    weekly_high = np.full((len(unique), names), np.nan)
    weekly_low = np.full((len(unique), names), np.nan)
    columns = np.arange(names)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for k, (r0, r1) in enumerate(zip(starts, ends, strict=True)):
            block = close[r0:r1]
            last = np.where(np.isfinite(block), np.arange(r1 - r0)[:, None], -1).max(
                axis=0
            )
            weekly_close[k] = np.where(
                last >= 0, block[np.maximum(last, 0), columns], np.nan
            )
            weekly_high[k] = np.nanmax(high[r0:r1], axis=0)
            weekly_low[k] = np.nanmin(low[r0:r1], axis=0)
    weekly_sma = sma(weekly_close, WEEKLY_SMA_WEEKS)
    # The last week strictly before each session's week.
    completed = np.searchsorted(unique, weeks, side="left") - 1
    known = completed >= 0
    at = np.maximum(completed, 0)
    wsma = np.where(known[:, None], weekly_sma[at], np.nan)
    prior_high = np.where(known[:, None], weekly_high[at], np.nan)
    prior_low = np.where(known[:, None], weekly_low[at], np.nan)
    return wsma, prior_high, prior_low


# Every daily-structure level and the zone half-width, for every
# (session, name) of the panel, as in force during that session: row d is
# computed from rows up to d - 1 (and, for the weekly levels, from the
# calendar week of d, which is known). Highs and lows go onto the adjusted
# basis by `adj_close / close`, exactly as `levels.level_identity` does.
def daily_levels(panel) -> DailyLevels:
    """Return the DailyLevels of the panel."""
    with np.errstate(all="ignore"):
        factor = np.where(panel.close > 0, panel.adj_close / panel.close, np.nan)
    high, low, close = panel.high * factor, panel.low * factor, panel.adj_close
    at_close: dict[str, np.ndarray] = {}
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        swing_low, swing_high = daily_structure.swing_points(high, low)
        lows = [
            daily_structure._nearest(swing_low, close, True, h) for h in SWING_HORIZONS
        ]
        highs = [
            daily_structure._nearest(swing_high, close, False, h)
            for h in SWING_HORIZONS
        ]
        for h, lo, hi in zip(
            SWING_HORIZONS, _keep_shortest(lows), _keep_shortest(highs), strict=True
        ):
            at_close[f"swing_low_{h}"] = lo
            at_close[f"swing_high_{h}"] = hi
        for length in SMA_LENGTHS:
            at_close[f"sma_{length}"] = sma(close, length)
        at_close["high_52w"] = daily_structure._rolling(
            high, YEAR_SESSIONS, largest=True
        )
        at_close["low_52w"] = daily_structure._rolling(
            low, YEAR_SESSIONS, largest=False
        )
        at_close["prior_day_high"] = high
        at_close["prior_day_low"] = low
        at_close["prior_day_close"] = close
        atr = backtest._atr(panel, ATR_SESSIONS)
        width = np.fmax(ATR_SHARE * atr, MIN_WIDTH * close)
    wsma, week_high, week_low = _completed_weeks(panel.dates, high, low, close)
    in_force = {k: _in_force_next(v) for k, v in at_close.items()}
    in_force["wsma_21"] = wsma
    in_force["prior_week_high"] = week_high
    in_force["prior_week_low"] = week_low
    stacked = np.stack([in_force[k] for k in DAILY_KINDS], axis=2)
    return DailyLevels(
        dates=np.asarray(panel.dates, dtype="datetime64[D]"),
        tickers=tuple(panel.tickers),
        levels=stacked,
        width=_in_force_next(width),
    )


# The volume nodes in force during each cube session, from the prior
# PROFILE_SESSIONS cube sessions' bars on the adjusted basis. Each bar's
# volume is spread evenly over the 0.25% log-price bins its low-high range
# covers. A node is a bin above the bin below it and at least the bin above
# it. The NODE_COUNT largest are kept (ties to the lower price), each
# priced at its bin's geometric midpoint. A session with fewer than
# PROFILE_SESSIONS cube sessions before it has none. Nothing of the session
# itself is read.
def volume_nodes(cube: SessionCube, scale: np.ndarray) -> np.ndarray:
    """Return (N, NODE_COUNT) node prices on the adjusted basis, NaN where none."""
    sessions = len(cube)
    out = np.full((sessions, NODE_COUNT), np.nan)
    if sessions <= PROFILE_SESSIONS:
        return out
    scale = np.asarray(scale, dtype=float)
    with np.errstate(all="ignore"):
        low = cube.low * scale[:, None]
        high = cube.high * scale[:, None]
        volume = np.asarray(cube.volume, dtype=float)
        valid = (
            np.isfinite(low)
            & np.isfinite(high)
            & (low > 0)
            & (high >= low)
            & np.isfinite(volume)
            & (volume > 0)
        )
        low_bin = np.floor(np.log(np.where(valid, low, 1.0)) / PROFILE_BIN).astype(
            np.int64
        )
        high_bin = np.floor(np.log(np.where(valid, high, 1.0)) / PROFILE_BIN).astype(
            np.int64
        )
    span = np.where(valid, high_bin - low_bin + 1, 0)
    share = np.where(valid, volume / np.maximum(span, 1), 0.0)
    # Every bar's bins, session-major, with each session's first entry.
    flat_span = span.ravel()
    total = int(flat_span.sum())
    first = np.repeat(np.cumsum(flat_span) - flat_span, flat_span)
    bins = np.repeat(low_bin.ravel(), flat_span) + (np.arange(total) - first)
    weights = np.repeat(share.ravel(), flat_span)
    offsets = np.concatenate([[0], np.cumsum(span.sum(axis=1))])
    for n in range(PROFILE_SESSIONS, sessions):
        lo, hi = offsets[n - PROFILE_SESSIONS], offsets[n]
        if hi <= lo:
            continue
        window = bins[lo:hi]
        base = int(window.min())
        profile = np.bincount(window - base, weights=weights[lo:hi])
        below = np.concatenate([[0.0], profile[:-1]])
        above = np.concatenate([profile[1:], [0.0]])
        peaks = np.flatnonzero((profile > below) & (profile >= above) & (profile > 0))
        if not len(peaks):
            continue
        order = np.lexsort((peaks, -profile[peaks]))[:NODE_COUNT]
        chosen = peaks[order]
        out[n, : len(chosen)] = np.exp((base + chosen + 0.5) * PROFILE_BIN)
    return out


# The intraday levels in force during each bar, from the session's own
# adjusted bars: the opening range's high and low from slot 2 on (NaN
# before), and the VWAP at the close of the bar before (NaN on slot 0). The
# VWAP is a proxy, bar closes weighted by bar volume, NaN before any volume.
def intraday_levels(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray
) -> np.ndarray:
    """Return (N, 26, 3): or_high, or_low, vwap in force during each bar."""
    sessions = high.shape[0]
    out = np.full((sessions, FULL_SESSION_SLOTS, len(INTRADAY_KINDS)), np.nan)
    if sessions == 0:
        return out
    out[:, FIRST_SLOT:, 0] = np.max(high[:, :OPENING_RANGE_SLOTS], axis=1)[:, None]
    out[:, FIRST_SLOT:, 1] = np.min(low[:, :OPENING_RANGE_SLOTS], axis=1)[:, None]
    volume = np.asarray(volume, dtype=float)
    traded = np.cumsum(close * volume, axis=1)
    shares = np.cumsum(volume, axis=1)
    with np.errstate(all="ignore"):
        vwap_at_close = np.where(shares > 0, traded / shares, np.nan)
    out[:, 1:, 2] = vwap_at_close[:, :-1]
    return out


# One name's levels in force during every bar of every cube session. The
# caller passes the per-session basis scale and the daily structure and
# zone half-width already mapped onto the cube's sessions (`for_cube`); the
# volume nodes and the intraday levels are built here from the cube.
def session_levels(
    cube: SessionCube,
    scale: np.ndarray,
    daily: np.ndarray,
    width: np.ndarray,
) -> SessionLevels:
    """Return the SessionLevels of `cube` on the adjusted basis."""
    sessions = len(cube)
    scale = np.asarray(scale, dtype=float)
    daily = np.asarray(daily, dtype=float)
    if scale.shape != (sessions,) or np.shape(width) != (sessions,):
        raise ValueError("scale and width need one value per cube session")
    if daily.shape != (sessions, len(DAILY_KINDS)):
        raise ValueError(
            f"daily levels have shape {daily.shape}; "
            f"need ({sessions}, {len(DAILY_KINDS)})"
        )
    factor = scale[:, None]
    open_, high, low, close = (
        cube.open * factor,
        cube.high * factor,
        cube.low * factor,
        cube.close * factor,
    )
    nodes = volume_nodes(cube, scale)
    per_session = np.concatenate([daily, nodes], axis=1)
    stacked = np.concatenate(
        [
            np.repeat(per_session[:, None, :], FULL_SESSION_SLOTS, axis=1),
            intraday_levels(high, low, close, cube.volume),
        ],
        axis=2,
    )
    return SessionLevels(
        dates=np.asarray(cube.dates, dtype="datetime64[D]"),
        open=open_,
        high=high,
        low=low,
        close=close,
        width=np.asarray(width, dtype=float),
        levels=stacked,
    )


# The SessionLevels of panel column `j` for its cube: the daily structure
# and half-width of the panel row of each cube session (`pos`, where `ok`;
# NaN for a session the panel lacks) and the basis scale per cube session,
# as `fill_timing.session_scale` returns them.
def for_cube(
    cube: SessionCube,
    daily: DailyLevels,
    j: int,
    pos: np.ndarray,
    ok: np.ndarray,
    scale: np.ndarray,
) -> SessionLevels:
    """Return column `j`'s SessionLevels for its cube."""
    rows = np.minimum(np.asarray(pos), len(daily.dates) - 1)
    block = np.where(ok[:, None], daily.levels[rows, j], np.nan)
    width = np.where(ok, daily.width[rows, j], np.nan)
    return session_levels(cube, scale, block, width)


# For every level in force during every bar, the confluence of its zone:
# how many distinct level prices lie within the session's half-width of it,
# itself included. A price that repeats (two kinds on one number) counts
# once. Absent levels score 0. One slot at a time, so the (K, K) distances
# stay small.
def confluence(levels: SessionLevels) -> np.ndarray:
    """Return (N, 26, K) int confluence of each level's zone."""
    values = levels.levels
    sessions, slots, kinds = values.shape
    out = np.zeros((sessions, slots, kinds), dtype=np.int64)
    earlier = np.tril(np.ones((kinds, kinds), dtype=bool), k=-1)
    width = levels.width[:, None, None]
    for s in range(slots):
        v = values[:, s, :]
        finite = np.isfinite(v)
        repeat = ((v[:, :, None] == v[:, None, :]) & earlier[None]).any(axis=2)
        counted = finite & ~repeat
        with np.errstate(invalid="ignore"):
            near = np.abs(v[:, :, None] - v[:, None, :]) <= width
        out[:, s, :] = np.where(finite, (near & counted[:, None, :]).sum(axis=2), 0)
    return out


# The close of the bar before each bar, NaN on slot 0: the P of the
# pre-registration.
def prior_bar_close(levels: SessionLevels) -> np.ndarray:
    """Return (N, 26) the previous bar's close within the session."""
    out = np.full(levels.close.shape, np.nan)
    out[:, 1:] = levels.close[:, :-1]
    return out


# The slots the study and the conventions read: slot 2 (10:00-10:15) on.
def _eligible_slots() -> np.ndarray:
    """Return (26,) bool, True from FIRST_SLOT."""
    return np.arange(FULL_SESSION_SLOTS) >= FIRST_SLOT


# Support touches: a bar from slot 2 on whose low enters the zone of a
# level that sits below the prior bar's close with that bar closed above
# the zone (L + w < P and low <= L + w). The touched zone is the highest
# such level's, the first price meets on the way down. Resistance mirrors
# it: L - w > P and high >= L - w, the lowest such level. Each touch
# carries the families of every level inside its zone and the zone's
# confluence (`confluence`).
def touches(levels: SessionLevels, conf: np.ndarray, side: str) -> Touches:
    """Return one side's Touches on every bar of every session."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, not {side!r}")
    values = levels.levels
    width = levels.width[:, None, None]
    prior = prior_bar_close(levels)[:, :, None]
    slots = _eligible_slots()[None, :, None]
    with np.errstate(invalid="ignore"):
        if side == SUPPORT:
            reached = (values + width < prior) & (
                levels.low[:, :, None] <= values + width
            )
        else:
            reached = (values - width > prior) & (
                levels.high[:, :, None] >= values - width
            )
    reached &= np.isfinite(values) & slots
    hit = reached.any(axis=2)
    if side == SUPPORT:
        best = np.argmax(np.where(reached, values, -np.inf), axis=2)
    else:
        best = np.argmin(np.where(reached, values, np.inf), axis=2)
    chosen = np.take_along_axis(values, best[..., None], axis=2)[..., 0]
    level = np.where(hit, chosen, np.nan)
    with np.errstate(invalid="ignore"):
        inside = np.isfinite(values) & (np.abs(values - level[..., None]) <= width)
    families = np.bitwise_or.reduce(np.where(inside, FAMILY_BITS, 0), axis=2)
    zone_confluence = np.take_along_axis(conf, best[..., None], axis=2)[..., 0]
    return Touches(
        hit=hit,
        level=level,
        families=np.where(hit, families, 0),
        confluence=np.where(hit, zone_confluence, 0),
    )


# Bars that can serve as a control for one side: from slot 2 on, a
# support-side candidate traded below the prior bar's close (low < P) with
# no level in [low - 2w, P): nothing within two half-widths beneath its
# low, nothing it passed through. The resistance side mirrors it: high > P
# and no level in (P, high + 2w]. A session without a half-width has none.
def clear_moves(levels: SessionLevels, side: str, clearance: float = 2.0) -> np.ndarray:
    """Return (N, 26) bool: the bars with no level in the way on `side`."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, not {side!r}")
    values = levels.levels
    width = levels.width[:, None]
    prior = prior_bar_close(levels)
    finite = np.isfinite(values)
    with np.errstate(invalid="ignore"):
        if side == SUPPORT:
            moved = levels.low < prior
            floor = (levels.low - clearance * width)[:, :, None]
            blocked = finite & (values < prior[:, :, None]) & (values >= floor)
        else:
            moved = levels.high > prior
            ceiling = (levels.high + clearance * width)[:, :, None]
            blocked = finite & (values > prior[:, :, None]) & (values <= ceiling)
    known = np.isfinite(width) & np.isfinite(prior)
    return moved & known & ~blocked.any(axis=2) & _eligible_slots()[None, :]


# For the fill conventions: per bar, the largest confluence among zones
# that hold the bar's close, split by the level's side of the prior bar's
# close (below: support; above: resistance). Zero where no zone holds it,
# and on every slot before 2.
def close_zones(levels: SessionLevels, conf: np.ndarray) -> CloseZones:
    """Return the CloseZones of every bar."""
    values = levels.levels
    width = levels.width[:, None, None]
    close = levels.close[:, :, None]
    prior = prior_bar_close(levels)[:, :, None]
    with np.errstate(invalid="ignore"):
        holds = np.isfinite(values) & (np.abs(close - values) <= width)
        below = holds & (values < prior)
        above = holds & (values > prior)
    slots = _eligible_slots()[None, :]
    support = np.where(below, conf, 0).max(axis=2)
    resistance = np.where(above, conf, 0).max(axis=2)
    return CloseZones(
        support=np.where(slots, support, 0).astype(np.int64),
        resistance=np.where(slots, resistance, 0).astype(np.int64),
    )


# The names of the families set in a bitmask, in FAMILIES order.
def family_names(bits: int) -> list[str]:
    """Return the families whose bits are set in `bits`."""
    return [f for i, f in enumerate(FAMILIES) if int(bits) >> i & 1]
