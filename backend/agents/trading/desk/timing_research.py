"""Causal multi-timeframe timing experiments, never a live order policy.

Daily trend uses the prior completed session. Hourly candles are anchored at
09:30 ET and usable only after completion. A 15-minute signal fills at the
following bar's open. These rules use price structure, not fixed profit targets.
"""

from collections import defaultdict
from datetime import time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from backend.market import technical
from backend.market.alpaca import IntradayBar

NY = ZoneInfo("America/New_York")


# Reuse the desk's causal EMA implementation for a single price series.
def _ema(values, span):
    return technical.ema(np.asarray(values, dtype=float)[:, None], span)[:, 0]


# Build complete exchange-anchored hourly candles without reading a partial hour.
def hourly(bars):
    groups = defaultdict(list)
    for bar in bars:
        local = bar.start.astimezone(NY)
        slot = (local.hour * 60 + local.minute - 570) // 60
        groups[(local.date(), slot)].append(bar)
    result = []
    for (_, slot), group in sorted(groups.items()):
        expected = 2 if slot == 6 else 4
        if len(group) != expected:
            continue
        if any(
            b.start - a.start != timedelta(minutes=15)
            for a, b in zip(group, group[1:], strict=False)
        ):
            continue
        result.append(
            IntradayBar(
                group[0].start,
                group[0].open,
                max(b.high for b in group),
                min(b.low for b in group),
                group[-1].close,
                sum(b.volume for b in group),
            )
        )
    return result


# Construct timestamped technical readings with an explicit completed-candle boundary.
def readings(bars, history):
    bars = sorted(
        (b for b in bars if time(9, 30) <= b.start.astimezone(NY).time() < time(16)),
        key=lambda b: b.start,
    )
    if not bars or history is None:
        return bars, []
    hours = hourly(bars)
    hour_ends = [
        b.start + timedelta(minutes=30 if b.start.astimezone(NY).hour == 15 else 60)
        for b in hours
    ]
    hour9, hour21 = (
        _ema([b.close for b in hours], 9),
        _ema([b.close for b in hours], 21),
    )
    daily = history.bars
    day_dates = [b.session_date for b in daily]
    day21 = _ema([b.adjusted_close for b in daily], 21)
    day50 = _ema([b.adjusted_close for b in daily], 50)
    closes = np.asarray([b.close for b in bars])
    ema9, ema21 = _ema(closes, 9), _ema(closes, 21)
    out = []
    for i, bar in enumerate(bars):
        end = bar.start + timedelta(minutes=15)
        hi = int(np.searchsorted(hour_ends, end, side="right")) - 1
        di = int(np.searchsorted(day_dates, bar.start.astimezone(NY).date())) - 1
        middle = float(np.mean(closes[i - 19 : i + 1])) if i >= 19 else np.nan
        spread = float(2 * np.std(closes[i - 19 : i + 1])) if i >= 19 else np.nan
        prior = bars[max(0, i - 1)]
        dc = float(daily[di].adjusted_close or np.nan) if di >= 0 else np.nan
        factor = dc / daily[di].close if di >= 0 and daily[di].close else np.nan
        out.append(
            {
                "at": end,
                "close": bar.close,
                "ema9": float(ema9[i]),
                "ema21": float(ema21[i]),
                "upper_band": middle + spread,
                "lower_band": middle - spread,
                "daily_close": dc,
                "daily_ema21": float(day21[di]) if di >= 0 else np.nan,
                "daily_ema50": float(day50[di]) if di >= 0 else np.nan,
                "prior_day_high": daily[di].high * factor
                if di >= 0 and daily[di].high
                else np.nan,
                "hourly_close": hours[hi].close if hi >= 0 else np.nan,
                "hourly_ema9": float(hour9[hi]) if hi >= 0 else np.nan,
                "hourly_ema21": float(hour21[hi]) if hi >= 0 else np.nan,
                "hourly_at": hour_ends[hi] if hi >= 0 else None,
                "bullish": bar.close > bar.open and bar.close > prior.close,
                "bearish": bar.close < bar.open and bar.close < prior.close,
                "low": bar.low,
                "high": bar.high,
                "prior_high": prior.high,
                "prior_low": prior.low,
            }
        )
    return bars, out


# Require agreement from completed daily and hourly trends before a chart entry.
def entry_signal(row, kind):
    aligned = (
        row["daily_close"] > row["daily_ema21"] > row["daily_ema50"]
        and row["hourly_close"] > row["hourly_ema21"]
    )
    if kind == "trend_pullback":
        return (
            aligned
            and row["bullish"]
            and row["low"] <= row["ema21"] < row["close"]
            and row["close"] > row["ema9"]
        )
    return (
        aligned
        and row["bullish"]
        and row["low"] <= row["prior_day_high"] < row["close"]
        and row["prior_high"] > row["prior_day_high"]
    )


# Exit on confirmed structure failure, with an optional half trim on band rejection.
def exit_fraction(row, kind, trimmed):
    failed = row["close"] < row["ema21"] and row["hourly_close"] < row["hourly_ema21"]
    if kind != "hold" and failed:
        return 1.0, "15-minute and completed hourly EMA21 failure"
    rejection = (
        row["bearish"]
        and row["high"] >= row["upper_band"]
        and row["close"] < row["ema9"]
    )
    if kind == "band_trim_then_structure" and not trimmed and rejection:
        return 0.5, "upper-band rejection with a close below EMA9"
    return 0.0, "hold"


# Walk actual entry and exit timestamps, keeping an unfilled candidate in cash.
def evaluate(bars, rows, published, entry_kind, exit_kind, cost_bps=10):
    eligible = [i for i, b in enumerate(bars) if b.start >= published]
    if not eligible:
        return {"status": "no post-publication bars", "return": None}
    if entry_kind == "first_open":
        opened = eligible[0]
    else:
        fired = next(
            (
                i
                for i in eligible
                if i + 1 < len(bars) and entry_signal(rows[i], entry_kind)
            ),
            None,
        )
        opened = fired + 1 if fired is not None else None
    if opened is None:
        return {"status": "no confirmed entry; cash", "return": 0.0}
    paid = bars[opened].open
    remaining, proceeds = 1.0, 0.0
    fills = []
    for i in range(opened, len(bars) - 1):
        fraction, reason = exit_fraction(rows[i], exit_kind, bool(fills))
        sold = remaining * fraction
        if sold <= 0:
            continue
        price = bars[i + 1].open
        proceeds += sold * price
        remaining -= sold
        fills.append(
            {
                "signal_at": rows[i]["at"],
                "filled_at": bars[i + 1].start,
                "fraction": sold,
                "price": price,
                "reason": reason,
            }
        )
        if remaining <= 0:
            break
    proceeds += remaining * bars[-1].close
    cost = cost_bps / 1e4
    return {
        "status": "entered",
        "entry_at": bars[opened].start,
        "entry_price": paid,
        "entry_signal_at": rows[opened - 1]["at"]
        if entry_kind != "first_open"
        else published,
        "return": proceeds * (1 - cost) / (paid * (1 + cost)) - 1,
        "exits": fills,
        "marked_fraction": remaining,
        "marked_at": rows[-1]["at"],
    }


# Compare predefined entry/exit combinations on one immutable grade's available prices.
def compare(bars, history, published):
    bars, rows = readings(bars, history)
    if not rows:
        return {}
    return {
        f"{entry}/{exit}": evaluate(bars, rows, published, entry, exit)
        for entry in ("first_open", "trend_pullback", "breakout_retest")
        for exit in ("hold", "structure", "band_trim_then_structure")
    }
