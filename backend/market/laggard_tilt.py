"""One research-only partial laggard tilt; no live policy imports this module."""

from __future__ import annotations

import hashlib

import numpy as np

from backend.agents.trading.desk import policy_v4

PLAN = "docs/research/laggard-tilt-plan-2026-09-29.md"


# Move half the weakest target only into eligible stock headroom, preserving cash.
def targets(base, scores):
    base = np.asarray(base, dtype=float)
    scores = np.asarray(scores, dtype=float)
    if base.ndim != 1 or base.shape != scores.shape:
        raise ValueError("aligned target and forecast vectors required")
    if not np.isfinite(base).all() or (base < 0).any():
        raise ValueError("finite nonnegative baseline targets required")
    candidates = np.flatnonzero((base > 0) & np.isfinite(scores))
    if len(candidates) < 3:
        return base.copy()
    weakest = int(candidates[np.argmin(scores[candidates])])
    recipients = candidates[candidates != weakest]
    room = np.maximum(0.0, policy_v4.HOLD_CAP - base[recipients])
    capacity = float(room.sum())
    if capacity <= 0:
        return base.copy()
    amount = min(0.5 * base[weakest], capacity)
    out = base.copy()
    out[weakest] -= amount
    out[recipients] += amount * room / capacity
    return out


# Build a deterministic placebo ordering without examining prices or future returns.
def placebo_scores(day, tickers, available):
    values = np.full(len(tickers), np.nan)
    for i, ticker in enumerate(tickers):
        if available[i]:
            digest = hashlib.sha256(
                f"laggard-placebo-7|{day}|{ticker}".encode()
            ).digest()
            values[i] = int.from_bytes(digest[:8], "big") / 2**64
    return values


class Allocator:
    """The unchanged `/4` allocator with one bounded, recorded target adjustment."""

    # Bind forecasts and membership; each call reads only the current row.
    def __init__(self, mask, grid, placebo=False):
        if np.shape(mask) != np.shape(grid):
            raise ValueError("membership and forecast grids must align")
        self.base = policy_v4.allocator(mask)
        self.grid = np.asarray(grid, dtype=float)
        self.placebo = placebo
        self.calls = 0
        self.changed = 0
        self.shifted = 0.0
        self.max_cash_difference = 0.0

    # Return the adjusted allocation without manufacturing a fill or changing execution.
    def __call__(self, report, panel, config, t):
        base = self.base(report, panel, config, t)
        scores = self.grid[t]
        if self.placebo:
            scores = placebo_scores(panel.dates[t], panel.tickers, np.isfinite(scores))
        result = targets(base, scores)
        moved = float(np.maximum(base - result, 0).sum())
        self.calls += 1
        self.changed += int(moved > 0)
        self.shifted += moved
        self.max_cash_difference = max(
            self.max_cash_difference, abs(float(result.sum() - base.sum()))
        )
        return result


# Describe past-close market regimes without reading the return being categorised.
def regimes(spy):
    spy = np.asarray(spy, dtype=float)
    out = np.full(len(spy), "warmup", dtype="U24")
    for t in range(200, len(spy)):
        history = spy[t - 200 : t]
        recent = spy[t - 21 : t]
        if not np.isfinite(history).all() or (history <= 0).any():
            continue
        high = np.std(np.diff(np.log(recent)), ddof=1) * np.sqrt(252) > 0.2
        trend = "above_200d" if spy[t - 1] > history.mean() else "below_200d"
        out[t] = trend + ("_high_vol" if high else "_low_vol")
    return out
