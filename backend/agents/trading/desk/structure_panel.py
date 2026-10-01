"""The board's structure definitions on a whole panel: EMA21, H20, the level, the tag.

`structure.py` holds the definitions the board prints for one name on one
session, in plain Python so the balancer needs no numpy. The structure-rules
study (`docs/research/structure-rules-plan-2026-09-30.md`) and the technical
analyst's structure notch (S1g) read the same definitions on (T, N) arrays.
This module vectorises them without restating a constant or a recursion:
the EMA is `structure.ema` column by column, the bands are `structure.
TAG_BAND` and `structure.NEAR_BAND`, the window `structure.HIGH_WINDOW`, the
slope look-back `structure.SLOPE_SESSIONS`, and `test_structure_panel.py`
pins every vectorised reading to the scalar function on random data, so the
study and the display cannot disagree.

The plan's definitions, fixed there:

- EMA21(t): the 21-session EMA (span 21, adjust=False) of the adjusted
  close through t; defined once 21 finite closes have been seen (the
  board's `ema_levels` rule). Falling when EMA21(t) < EMA21(t-5).
- H20(t): the highest daily high over sessions t-19..t, all finite.
- L(t+1): for an order in t+1, the nearer of EMA21(t) and H20(t) that lies
  above the close of t; no level when neither does.
- Tag: the first completed bar of t+1 has high >= L x (1 - TAG_BAND) while
  close(t) < L. Rejected: a tag whose bar close < L.
- Lower highs: high(t) < high(t-1) < high(t-2), or the daily high within
  NEAR_BAND of L on three consecutive sessions (t-2..t) with the close
  under L.

Every input is on one basis (the study's is the panel's adjusted basis:
the adjusted close and the highs scaled by the dividend factor, as
`stage4_labels.name_series` builds them).
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import structure

EMA_SPAN = structure.EMA_SPAN
SLOPE_SESSIONS = structure.SLOPE_SESSIONS
HIGH_WINDOW = structure.HIGH_WINDOW
TAG_BAND = structure.TAG_BAND
NEAR_BAND = structure.NEAR_BAND
# Lower highs: this many consecutive sessions at the level, or of falling highs.
LOWER_HIGHS_SESSIONS = 3


# A (T,) or (T, N) float array with a leading axis of sessions.
def _columns(values: np.ndarray) -> np.ndarray:
    """Return `values` as a float (T, N) array (a (T,) input becomes (T, 1))."""
    x = np.asarray(values, dtype=float)
    return x[:, None] if x.ndim == 1 else x


# Undo `_columns` for the caller: a (T, 1) result of a (T,) input is (T,).
def _shaped(out: np.ndarray, like: np.ndarray) -> np.ndarray:
    """Return `out` in the shape of `like`."""
    return out[:, 0] if np.asarray(like).ndim == 1 else out


# The 21-session EMA of every column, `structure.ema`'s recursion over the
# column's finite positive closes in order (a NaN session is skipped, as the
# board's `ema_levels` skips a bar it cannot price), placed back on the
# session it was read at, and NaN until `EMA_SPAN` such closes have been
# seen. The recursion itself is the board's: the first close seeds it.
def ema21(close: np.ndarray, span: int = EMA_SPAN) -> np.ndarray:
    """Return the EMA of `close` per column, NaN before the span is full."""
    x = _columns(close)
    out = np.full(x.shape, np.nan)
    for j in range(x.shape[1]):
        column = x[:, j]
        rows = np.flatnonzero(np.isfinite(column) & (column > 0))
        if len(rows) < span:
            continue
        series = structure.ema([float(v) for v in column[rows]], span)
        out[rows[span - 1 :], j] = series[span - 1 :]
    return _shaped(out, close)


# Whether the EMA is falling at each session: `structure.ema_slope` over
# SLOPE_SESSIONS is negative, i.e. EMA(t) < EMA(t-5); False where either
# value is missing.
def ema_falling(ema: np.ndarray, sessions: int = SLOPE_SESSIONS) -> np.ndarray:
    """Return the (T[, N]) bool array of sessions where the EMA is falling."""
    x = _columns(ema)
    out = np.zeros(x.shape, dtype=bool)
    with np.errstate(invalid="ignore"):
        slope = (x[sessions:] - x[:-sessions]) / x[sessions:]
        out[sessions:] = np.isfinite(slope) & (slope < 0.0)
    return _shaped(out, ema)


# The highest daily high over the last HIGH_WINDOW sessions through t, NaN
# unless every high in the window is finite (the plan's definition; the
# board's `high_20` also answers for a younger name, and the two agree
# whenever the window is full).
def high20(high: np.ndarray, window: int = HIGH_WINDOW) -> np.ndarray:
    """Return the (T[, N]) rolling high, NaN until the window is full."""
    x = _columns(high)
    out = np.full(x.shape, np.nan)
    if window <= len(x):
        windows = np.lib.stride_tricks.sliding_window_view(x, window, axis=0)
        complete = np.isfinite(windows).all(axis=-1)
        with np.errstate(invalid="ignore"):
            out[window - 1 :] = np.where(complete, windows.max(axis=-1), np.nan)
    return _shaped(out, high)


# The level an order in t+1 reads: the nearer of EMA21(t) and H20(t) that
# lies above the close of t, NaN when neither does.
def buy_level(close: np.ndarray, ema: np.ndarray, high_20: np.ndarray) -> np.ndarray:
    """Return the (T[, N]) level L above each session's close."""
    c, e, h = (np.asarray(v, dtype=float) for v in (close, ema, high_20))
    with np.errstate(invalid="ignore"):
        e_above = np.where(np.isfinite(e) & (e > c), e, np.inf)
        h_above = np.where(np.isfinite(h) & (h > c), h, np.inf)
    nearer = np.minimum(e_above, h_above)
    return np.where(np.isfinite(nearer), nearer, np.nan)


# Whether the first bar of t+1 tagged the level from below, and whether the
# tag was rejected: `structure.tag_for` on arrays. `level` and `close_t`
# are the decision session's, `bar_high` and `bar_close` the first bar's,
# all on one basis. Returns (tagged, rejected).
def first_bar_tag(
    level: np.ndarray, close_t: np.ndarray, bar_high: np.ndarray, bar_close: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((...,) tagged, (...,) rejected) for the first bar against L."""
    lv, c, hi, cl = (
        np.asarray(v, dtype=float) for v in (level, close_t, bar_high, bar_close)
    )
    with np.errstate(invalid="ignore"):
        tagged = (
            np.isfinite(lv)
            & np.isfinite(c)
            & np.isfinite(hi)
            & np.isfinite(cl)
            & (c < lv)
            & (hi >= lv * (1.0 - TAG_BAND))
        )
        rejected = tagged & (cl < lv)
    return tagged, rejected


# Lower highs at each session: three falling daily highs (high(t) <
# high(t-1) < high(t-2)), or three consecutive sessions through t whose
# high sits within NEAR_BAND of the session's level L with the close under
# it (`structure.consecutive_sessions` at t's level, counting t itself).
# False where the highs or the level are missing.
def lower_highs(high: np.ndarray, close: np.ndarray, level: np.ndarray) -> np.ndarray:
    """Return the (T[, N]) bool array of sessions with lower highs."""
    h, c, lv = (_columns(v) for v in (high, close, level))
    n = LOWER_HIGHS_SESSIONS
    out = np.zeros(h.shape, dtype=bool)
    if len(h) < n:
        return _shaped(out, high)
    with np.errstate(invalid="ignore"):
        falling = np.ones(h[n - 1 :].shape, dtype=bool)
        for k in range(1, n):
            later = h[n - 1 - (k - 1) : len(h) - (k - 1)]
            earlier = h[n - 1 - k : len(h) - k]
            falling &= np.isfinite(later) & np.isfinite(earlier) & (later < earlier)
        at_level = np.isfinite(lv[n - 1 :])
        for k in range(n):
            hk = h[n - 1 - k : len(h) - k]
            ck = c[n - 1 - k : len(c) - k]
            at_level &= (
                np.isfinite(hk)
                & np.isfinite(ck)
                & (np.abs(hk / lv[n - 1 :] - 1.0) <= NEAR_BAND)
                & (ck < lv[n - 1 :])
            )
    out[n - 1 :] = falling | at_level
    return _shaped(out, high)


# S1g's condition on every (session, name): the close under a falling EMA21
# with lower highs, from the adjusted closes and highs. False wherever a
# reading is missing, so a young name is never notched.
def notch_mask(close: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Return the (T[, N]) bool mask of sessions the structure notch fires on."""
    c = np.asarray(close, dtype=float)
    ema = ema21(c)
    level = buy_level(c, ema, high20(high))
    with np.errstate(invalid="ignore"):
        under = np.isfinite(ema) & np.isfinite(c) & (c < ema)
    return under & ema_falling(ema) & lower_highs(high, c, level)
