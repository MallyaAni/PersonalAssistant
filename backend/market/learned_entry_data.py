"""Pure preparation of causal observations and separately matured outcome labels.

No cache loading, fitting or source writes occur here. Future official prices
convert accounting/label units only; prediction features use raw prefix ratios.
"""

from __future__ import annotations

import numpy as np

from backend.market.fill_timing import session_scale

FEATURE_NAMES = (
    "return_5",
    "return_20",
    "return_60",
    "return_252",
    "volatility_20",
    "drawdown_252",
    "ema_21_distance",
    "ema_63_distance",
    "prior_grade",
    "spy_return_5",
    "spy_return_20",
    "spy_volatility_20",
    "breadth_20",
    "gap",
    "session_return",
    "last_bar_return",
    "prefix_range",
    "range_location",
    "vwap_distance",
    "prefix_volatility",
    "session_time",
)
LABEL_HORIZON = 10
DECISIONS = 25


# Compute prior-only daily features without filling missing price history.
def _daily_context(prices, grades, eligible, spy):
    days, stocks = prices.shape
    context = np.full((days, stocks, 13), np.nan, dtype=np.float32)
    available = np.zeros((days, stocks), dtype=bool)
    ema = np.full((stocks, 2), np.nan)
    alpha = np.array([2 / 22, 2 / 64])
    for day in range(1, days):
        last = prices[day - 1]
        positive = np.isfinite(last) & (last > 0)
        ema = np.where(
            positive[:, None],
            np.where(
                np.isfinite(ema),
                alpha * last[:, None] + (1 - alpha) * ema,
                last[:, None],
            ),
            np.nan,
        )
        if day < 253:
            continue
        history = prices[day - 253 : day]
        good = np.all(np.isfinite(history) & (history > 0), axis=0)
        with np.errstate(all="ignore"):
            for feature, horizon in enumerate((5, 20, 60, 252)):
                context[day, :, feature] = np.log(last / prices[day - 1 - horizon])
            returns = np.diff(np.log(prices[day - 21 : day]), axis=0)
            context[day, :, 4] = np.std(returns, axis=0)
            context[day, :, 5] = last / np.max(history[-252:], axis=0) - 1
            context[day, :, 6:8] = last[:, None] / ema - 1
            context[day, :, 8] = np.where(grades[day - 1] >= 0, grades[day - 1], np.nan)
            context[day, :, 9] = context[day, spy, 0]
            context[day, :, 10] = context[day, spy, 1]
            context[day, :, 11] = context[day, spy, 4]
        members = eligible[day - 1] & good
        if np.any(members):
            context[day, :, 12] = np.mean(context[day, members, 1] > 0)
        available[day] = good & good[spy] & np.isfinite(context[day, :, 12])
    return context, available


# Validate supplied raw cubes before deriving any observation or label.
def _validate_cube(cube):
    dates = np.asarray(cube.dates, dtype="datetime64[D]")
    if np.any(np.isnat(dates)) or np.any(np.diff(dates).astype(int) <= 0):
        raise ValueError("cube dates must be unique and strictly increasing")
    for field in ("open", "high", "low", "close", "volume"):
        if np.asarray(getattr(cube, field)).shape != (len(dates), 26):
            raise ValueError("cube must contain 26-slot regular sessions")
    for field in ("prior_close", "auction_open", "auction_volume"):
        if np.asarray(getattr(cube, field)).shape != (len(dates),):
            raise ValueError("cube session vectors must match its calendar")


# Check the supplied daily panel and membership contracts without changing them.
def _validate_panel(panel, grades, eligible):
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    prices = np.asarray(panel.adj_close, dtype=float)
    names = tuple(panel.tickers)
    days, stocks = len(dates), len(names)
    if days == 0 or np.any(np.isnat(dates)) or np.any(np.diff(dates).astype(int) <= 0):
        raise ValueError("panel dates must be nonempty, unique and ordered")
    if prices.shape != (days, stocks) or "SPY" not in names:
        raise ValueError("panel requires aligned prices and SPY")
    grades = np.asarray(grades)
    eligible = np.asarray(eligible)
    if grades.shape != prices.shape or eligible.shape != prices.shape:
        raise ValueError("grades and membership must match daily prices")
    if eligible.dtype.kind != "b":
        raise ValueError("membership must be explicitly boolean")
    if np.any(~np.isfinite(grades)) or np.any(~np.isin(grades, (-1, 0, 1, 2, 3))):
        raise ValueError("grades must contain known codes or -1")
    if len(set(names)) != len(names):
        raise ValueError("panel ticker names must be unique")
    return dates, prices, names, grades, eligible


# Build every completed-prefix observation while retaining unavailable outcomes.
def prepare(panel, grades, eligible, cubes):
    dates, prices, names, grades, eligible = _validate_panel(panel, grades, eligible)
    days, stocks = prices.shape
    context, daily_valid = _daily_context(prices, grades, eligible, names.index("SPY"))
    shape = (days, DECISIONS, stocks)
    features = np.full((*shape, len(FEATURE_NAMES)), np.nan, dtype=np.float32)
    labels = np.full((*shape, 3), np.nan, dtype=np.float32)
    valid = np.zeros(shape, dtype=bool)
    next_open = np.full(shape, np.nan, dtype=np.float32)
    current_close = np.full(shape, np.nan, dtype=np.float32)
    excluded = {}
    missing_cubes = []
    for stock, name in enumerate(names):
        cube = cubes.get(name)
        if cube is None or len(cube) == 0:
            missing_cubes.append(name)
            continue
        _validate_cube(cube)
        excluded[name] = dict(cube.excluded)
        positions, matched, scales = session_scale(cube, dates, prices[:, stock])
        rows = np.flatnonzero(matched)
        panel_rows = positions[rows]
        raw = [
            np.asarray(getattr(cube, field), dtype=float)[rows]
            for field in ("open", "high", "low", "close", "volume")
        ]
        opening, high, low, closing, volume = raw
        prior = np.asarray(cube.prior_close, dtype=float)[rows]
        bar_ok = (
            np.isfinite(opening)
            & np.isfinite(high)
            & np.isfinite(low)
            & np.isfinite(closing)
            & np.isfinite(volume)
            & (opening > 0)
            & (low > 0)
            & (volume >= 0)
            & (low <= np.minimum(opening, closing))
            & (high >= np.maximum(opening, closing))
            & (high >= low)
        )
        prefix_ok = np.logical_and.accumulate(bar_ok, axis=1)[:, :DECISIONS]
        prefix_ok &= (np.isfinite(prior) & (prior > 0))[:, None]
        running_high = np.maximum.accumulate(high, axis=1)[:, :DECISIONS]
        running_low = np.minimum.accumulate(low, axis=1)[:, :DECISIONS]
        running_volume = np.cumsum(volume, axis=1)[:, :DECISIONS]
        with np.errstate(all="ignore"):
            vwap = np.cumsum(closing * volume, axis=1)[:, :DECISIONS] / running_volume
            moves = np.log(closing / np.column_stack((prior, closing[:, :-1])))
            count = np.arange(1, DECISIONS + 1)
            mean = np.cumsum(moves, axis=1)[:, :DECISIONS] / count
            variance = np.cumsum(moves**2, axis=1)[:, :DECISIONS] / count - mean**2
            width = running_high - running_low
            location = np.divide(
                closing[:, :DECISIONS] - running_low,
                width,
                out=np.full_like(width, 0.5),
                where=width > 0,
            )
            prefix = np.stack(
                (
                    np.broadcast_to(
                        np.log(opening[:, :1] / prior[:, None]), width.shape
                    ),
                    np.log(closing[:, :DECISIONS] / opening[:, :1]),
                    moves[:, :DECISIONS],
                    width / prior[:, None],
                    location,
                    closing[:, :DECISIONS] / vwap - 1,
                    np.sqrt(np.maximum(variance, 0)),
                    np.broadcast_to(count / 26, width.shape),
                ),
                axis=-1,
            )
        prefix_ok &= (running_volume > 0) & np.all(np.isfinite(prefix), axis=-1)
        features[panel_rows, :, stock, :13] = context[panel_rows, stock, None, :]
        features[panel_rows, :, stock, 13:] = prefix
        valid[panel_rows, :, stock] = prefix_ok & daily_valid[panel_rows, stock, None]
        good_scale = np.isfinite(scales[rows]) & (scales[rows] > 0)
        scale = np.where(good_scale, scales[rows], np.nan)[:, None]
        adjusted_entry = opening[:, 1:26] * scale
        # Only the open exists at execution time; the bar's later range/close
        # cannot retrospectively veto a fill from the preceding decision.
        adjusted_entry = np.where(
            np.isfinite(adjusted_entry) & (adjusted_entry > 0),
            adjusted_entry,
            np.nan,
        )
        next_open[panel_rows, :, stock] = adjusted_entry
        current_close[panel_rows, :, stock] = closing[:, :DECISIONS] * scale
        waiting = np.full_like(adjusted_entry, np.nan)
        waiting[:, :24] = adjusted_entry[:, 1:25]
        cube_rows_by_day = {int(day): index for index, day in enumerate(panel_rows)}
        for index, day in enumerate(panel_rows):
            next_row = cube_rows_by_day.get(int(day + 1))
            if next_row is not None:
                waiting[index, 24] = adjusted_entry[next_row, 0]
        mature = panel_rows + LABEL_HORIZON < days
        endpoint = np.full(len(rows), np.nan)
        endpoint[mature] = prices[panel_rows[mature] + LABEL_HORIZON, stock]
        with np.errstate(all="ignore"):
            gain = np.log(endpoint[:, None] / adjusted_entry)
            advantage = np.log(adjusted_entry / waiting)
        gain = np.where(np.isfinite(gain) & (endpoint[:, None] > 0), gain, np.nan)
        advantage = np.where(np.isfinite(advantage) & (waiting > 0), advantage, np.nan)
        labels[panel_rows, :, stock, 0] = gain
        labels[panel_rows, :, stock, 1] = gain**2
        labels[panel_rows, :, stock, 2] = advantage
    prior_grades = np.full((days, stocks), -1, dtype=grades.dtype)
    prior_eligible = np.zeros((days, stocks), dtype=bool)
    prior_grades[1:] = grades[:-1]
    prior_eligible[1:] = eligible[:-1]
    label_end_dates = np.full(days, np.datetime64("NaT", "D"))
    if days > LABEL_HORIZON:
        label_end_dates[:-LABEL_HORIZON] = dates[LABEL_HORIZON:]
    return {
        "X": features,
        "y": labels,
        "valid": valid,
        "dates": dates,
        "feature_names": FEATURE_NAMES,
        "tickers": names,
        "next_open": next_open,
        "current_close": current_close,
        "prior_grades": prior_grades,
        "prior_eligible": prior_eligible,
        "label_end_dates": label_end_dates,
        "diagnostics": {
            "missing_cubes": missing_cubes,
            "cube_exclusions": excluded,
            "valid_predictions": int(np.count_nonzero(valid)),
            "complete_labels": int(
                np.count_nonzero(valid & np.all(np.isfinite(labels), axis=-1))
            ),
            "price_features": (
                "raw same-session prefix/prior_close; prior adjusted daily context"
            ),
            "label_basis": (
                "session_scale adjusted next opens and adjusted daily endpoint"
            ),
            "early_close_support": False,
            "grade_membership_basis": (
                "prior-session supplied current-vintage reconstruction"
            ),
        },
    }
