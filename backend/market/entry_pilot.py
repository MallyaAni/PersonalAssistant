"""Causal entry-versus-wait research and one funded ledger; no broker access."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.agents.trading.desk.entry import bollinger_z
from backend.market import intraday, technical

SLOTS = (3, 7)
SEQUENCE = 14
BASIC = 8
NAMES = (
    "return5",
    "return20",
    "vol20",
    "distance_ema21",
    "gap",
    "session_return",
    "last_bar_return",
    "market_return20",
    "return60",
    "return120",
    "distance_ema9",
    "distance_ema50",
    "distance_ema200",
    "band_position",
    "band_width",
    "distance_low20",
    "distance_high20",
    "theme_return20",
    "market_vol20",
    "range_position",
    "distance_vwap",
    "relative_volume",
    "realized_intraday_vol",
    "body",
    "upper_wick",
    "lower_wick",
    "time",
    "last_hour_return",
)


@dataclass
class Dataset:
    """Decision inputs kept separate from execution prices and future labels."""

    x: np.ndarray
    sequence: np.ndarray
    y: np.ndarray
    day: np.ndarray
    slot: np.ndarray
    name: np.ndarray
    entry_prices: np.ndarray
    exit_day: np.ndarray
    dates: np.ndarray
    closes: np.ndarray
    tickers: np.ndarray
    candidate: np.ndarray
    horizon: int = 5


# Build daily context using only data through the preceding session.
def daily_context(panel):
    close = panel.adj_close
    ret = panel.log_returns()
    lags = {}
    for lag in (5, 20, 60, 120):
        a = np.full_like(close, np.nan)
        a[lag:] = np.log(close[lag:] / close[:-lag])
        lags[lag] = a
    vol = np.full_like(close, np.nan)
    low, high = np.full_like(close, np.nan), np.full_like(close, np.nan)
    for t in range(20, len(close)):
        vol[t] = np.std(ret[t - 19 : t + 1], axis=0)
        low[t] = np.min(close[t - 19 : t + 1], axis=0)
        high[t] = np.max(close[t - 19 : t + 1], axis=0)
    averages = {n: technical.ema(close, n) for n in (9, 21, 50, 200)}
    mean = technical.sma(close, 20)
    band = bollinger_z(close)
    width = np.full_like(close, np.nan)
    for t in range(19, len(close)):
        width[t] = np.std(close[t - 19 : t + 1], axis=0) / mean[t]
    theme = panel.theme_return_matrix()
    theme20 = np.full_like(close, np.nan)
    for t in range(19, len(close)):
        theme20[t] = np.sum(theme[t - 19 : t + 1], axis=0)
    return lags, vol, low, high, averages, band, width, theme20


# Describe the observed prefix without inspecting any later intraday bar.
def prefix_features(bars, k, previous_close, historical_volume):
    prefix = bars[: k + 1]
    if not np.isfinite(prefix).all() or np.any(prefix[:, :4] <= 0):
        return None
    if np.any(prefix[:, 4] < 0):
        return None
    o, h, lo, c, v = prefix.T
    if np.any(h < np.maximum(o, c)) or np.any(lo > np.minimum(o, c)):
        return None
    if not np.isfinite(previous_close) or previous_close <= 0:
        return None
    r = np.diff(np.log(np.r_[previous_close, c]))
    expected = np.maximum(historical_volume[: k + 1], 1)
    relative = np.log1p(v / expected)
    typical = (h + lo + c) / 3
    vwap = np.sum(typical * v) / v.sum() if v.sum() > 0 else c[-1]
    span = max(h.max() - lo.min(), 1e-10)
    last_span = max(h[-1] - lo[-1], 1e-10)
    full = np.array(
        [
            (c[-1] - lo.min()) / span,
            np.log(c[-1] / vwap),
            np.log1p(v.sum() / max(expected.sum(), 1)),
            np.sqrt(np.mean(r[1:] ** 2)) if k else 0,
            (c[-1] - o[-1]) / last_span,
            (h[-1] - max(o[-1], c[-1])) / last_span,
            (min(o[-1], c[-1]) - lo[-1]) / last_span,
            k / 25,
            np.log(c[-1] / c[max(0, k - 4)]),
        ]
    )
    seq = np.zeros((SEQUENCE, 7), dtype=np.float32)
    seq[: k + 1] = np.column_stack(
        (
            r,
            np.log(h / lo),
            np.log(c / o),
            relative,
            np.log(c / o[0]),
            np.arange(k + 1) / 25,
            np.ones(k + 1),
        )
    )
    basic = [np.log(o[0] / previous_close), np.log(c[-1] / o[0]), r[-1]]
    return basic, full, seq


# Load bars on the shared daily calendar without filtering by future completeness.
def bar_grid(root, ticker, dates):
    grid = np.full((len(dates), intraday.BARS, 5), np.nan)
    day, slot, fields, _ = intraday.load(root, ticker)
    indexes = np.searchsorted(dates, day)
    valid = indexes < len(dates)
    valid &= dates[np.minimum(indexes, len(dates) - 1)] == day
    keys = indexes[valid] * intraday.BARS + slot[valid]
    _, counts = np.unique(keys, return_counts=True)
    if np.any(counts > 1):
        raise ValueError(f"Duplicate regular-session bar: {ticker}")
    grid[indexes[valid], slot[valid]] = np.column_stack(
        [fields[n][valid] for n in ("open", "high", "low", "close", "volume")]
    )
    return grid


# Construct action rewards separately from causal features and fixed candidate flags.
def build(panel, root: Path, horizon=5):  # noqa: C901 - explicit data-validity gates
    if horizon < 1:
        raise ValueError("Positive multi-session horizon required")
    lags, vol, low, high, averages, band, width, theme = daily_context(panel)
    bench = panel.index(panel.benchmark)
    x, seq, y, days, slots, names, prices, exits = ([] for _ in range(8))
    for j, ticker in enumerate(panel.tickers):
        if j == bench or not (root / f"{ticker}.parquet").exists():
            continue
        bars = bar_grid(root, ticker, panel.dates)
        for d in range(200, len(panel.dates) - horizon):
            p = d - 1
            if not np.isfinite(lags[20][p, j]) or lags[20][p, j] <= 0:
                continue
            historical = bars[max(0, d - 20) : d, :, 4]
            if np.sum(np.isfinite(historical), axis=0).min() < 5:
                continue
            med_volume = np.nanmedian(historical, axis=0)
            prior = panel.close[p, j]
            daily = [
                lags[5][p, j],
                lags[20][p, j],
                vol[p, j],
                np.log(panel.adj_close[p, j] / averages[21][p, j]),
            ]
            slow = [
                lags[60][p, j],
                lags[120][p, j],
                *[
                    np.log(panel.adj_close[p, j] / averages[n][p, j])
                    for n in (9, 50, 200)
                ],
                band[p, j],
                width[p, j],
                np.log(panel.adj_close[p, j] / low[p, j]),
                np.log(panel.adj_close[p, j] / high[p, j]),
                theme[p, j],
                vol[p, bench],
            ]
            for k in SLOTS:
                prefix = prefix_features(bars[d], k, prior, med_volume)
                if prefix is None:
                    continue
                basic, full, sequence = prefix
                features = np.r_[daily, basic, lags[20][p, bench], slow, full]
                if not np.isfinite(features).all():
                    continue
                # Adjustment factors belong only to accounting, never to features.
                factor = panel.adj_close[d, j] / panel.close[d, j]
                execution = bars[d, [k + 2, k + 6], 0] * factor
                exit_price = panel.adj_close[d + horizon, j]
                label = np.full(2, np.nan)
                if (
                    np.isfinite(execution).all()
                    and (execution > 0).all()
                    and np.isfinite(exit_price)
                    and exit_price > 0
                ):
                    rewards = 100 * np.log(exit_price / execution)
                    label = np.array([rewards[0], rewards[1] - rewards[0]])
                x.append(features)
                seq.append(sequence)
                y.append(label)
                days.append(d)
                slots.append(k)
                names.append(j)
                prices.append(execution)
                exits.append(d + horizon)
    if not x:
        raise ValueError("No usable causal entry observations")
    data = Dataset(
        np.asarray(x, dtype=np.float32),
        np.asarray(seq),
        np.asarray(y),
        np.asarray(days),
        np.asarray(slots),
        np.asarray(names),
        np.asarray(prices),
        np.asarray(exits),
        panel.dates,
        panel.adj_close,
        np.asarray(panel.tickers),
        np.zeros(len(x), dtype=bool),
        horizon,
    )
    for d in np.unique(data.day):
        for k in SLOTS:
            rows = np.flatnonzero((data.day == d) & (data.slot == k))
            chosen = rows[np.argsort(-data.x[rows, 1], kind="stable")[:5]]
            data.candidate[chosen] = True
    return data


# Purge observations whose outcome reaches or crosses the next chronological block.
def split(data, start, stop, labelled=True):
    mask = (data.dates[data.day] >= np.datetime64(start)) & (
        data.dates[data.exit_day] < np.datetime64(stop)
    )
    if labelled:
        mask &= np.isfinite(data.y).all(axis=1)
    return mask


# Convert two predicted rewards into enter, wait, or cash without seeing outcomes.
def actions(prediction, cost_bps=10, allow_skip=True):
    fee = cost_bps / 10000
    cost = 100 * np.log((1 + fee) / (1 - fee))
    immediate = prediction[:, 0] - cost
    waiting = immediate + prediction[:, 1]
    choice = (waiting > immediate).astype(int)
    if allow_skip:
        choice[np.maximum(immediate, waiting) <= 0] = 2
    return choice


# Simulate fixed cohorts through cash-funded delayed buys and daily marks.
def evaluate(data, mask, action, cost_bps=10):  # noqa: C901 - ordered ledger gates
    selected = np.flatnonzero(mask & data.candidate)
    if not len(selected):
        raise ValueError("No candidates in evaluation period")
    if len(action) != len(data.x) or np.any(~np.isin(action, [0, 1, 2])):
        raise ValueError("An enter/wait/skip action is required for each observation")
    fee = cost_bps / 10000
    if not 0 <= fee < 0.1:
        raise ValueError("Invalid execution cost")
    first, last = int(data.day[selected].min()), int(data.exit_day[selected].max())
    cash, holdings, nav, exposures, receipts = 1.0, [], [1.0], [], []
    traded = 0.0
    unfilled = 0
    # Each decision owns a fixed fraction; skipping never enlarges another slot.
    tranche = 1 / (len(SLOTS) * (data.horizon + 1))
    for d in range(first, last + 1):
        budget = nav[-1] * tranche / 5
        rows = selected[data.day[selected] == d]
        pending = sorted(rows, key=lambda r: (data.slot[r] + 2 + 4 * int(action[r]), r))
        for r in pending:
            a = int(action[r])
            if a == 2:
                receipts.append([int(r), a, 0.0])
                continue
            price = data.entry_prices[r, a]
            if not np.isfinite(price) or price <= 0:
                # This strategy requires a price observation at execution time.
                # No observation means no order, not a discarded opportunity.
                receipts.append([int(r), a, 0.0])
                unfilled += 1
                continue
            spend = min(budget, cash)
            units = spend / (price * (1 + fee))
            cash -= spend
            traded += units * price
            holdings.append((int(data.name[r]), int(data.exit_day[r]), units))
            receipts.append([int(r), a, float(spend)])
        kept, value = [], 0.0
        for j, end, units in holdings:
            price = data.closes[d, j]
            if not np.isfinite(price) or price <= 0:
                raise ValueError(f"Missing held-asset price on {data.dates[d]}")
            if d >= end:
                cash += units * price * (1 - fee)
                traded += units * price
            else:
                value += units * price
                kept.append((j, end, units))
        holdings = kept
        total = cash + value
        if total <= 0 or cash < -1e-12:
            raise ValueError("Unfunded or insolvent account")
        nav.append(total)
        exposures.append(value / total)
    curve = np.asarray(nav)
    daily = curve[1:] / curve[:-1] - 1
    vol = float(daily.std() * np.sqrt(252))
    counts = np.bincount(action[selected], minlength=3).tolist()
    return {
        "net_return": float(curve[-1] - 1),
        "sharpe_zero_cash_yield": float(daily.mean() * 252 / vol) if vol > 0 else 0,
        "max_drawdown": float(np.min(curve / np.maximum.accumulate(curve) - 1)),
        "average_exposure": float(np.mean(exposures)),
        "turnover_total": float(traded / np.mean(curve)),
        "unfilled_no_price": unfilled,
        "action_counts": dict(zip(("enter", "wait", "skip"), counts, strict=True)),
        "dates": data.dates[first : last + 1].astype(str).tolist(),
        "nav": nav,
        "daily": daily.tolist(),
        "decisions": receipts,
    }


# Estimate paired uncertainty by resampling whole blocks of market sessions.
def paired_interval(result, baseline, block=20, repetitions=1000):
    if result["dates"] != baseline["dates"]:
        raise ValueError("Paired paths must share dates")
    diff = np.asarray(result["daily"]) - np.asarray(baseline["daily"])
    rng = np.random.default_rng(713)
    draws = []
    for _ in range(repetitions):
        starts = rng.integers(0, len(diff), size=int(np.ceil(len(diff) / block)))
        idx = ((starts[:, None] + np.arange(block)) % len(diff)).ravel()[: len(diff)]
        draws.append(float(diff[idx].mean() * 10000))
    return {
        "paired_daily_bps": float(diff.mean() * 10000),
        "ci95_daily_bps": np.quantile(draws, [0.025, 0.975]).tolist(),
        "block_sessions": block,
    }
