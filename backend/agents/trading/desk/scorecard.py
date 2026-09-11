"""The scorecard: candidates judged on the objective, side by side.

The objective is compounded money after costs within a loss the person
accepts, against a pre-designated benchmark. A Sharpe ratio alone can
prefer a strategy that earns less money, and a higher return alone can
be bought with market risk, so every candidate is shown on the same
numbers: the compounded rate, the rate at the rule's volatility, the
volatility, worst drawdown, turnover, the largest position, and the
year-by-year total return beside SPY and QQQ. One table, read once.
"""

from datetime import date

import numpy as np

from backend.agents.trading.desk.simulate import SimResult
from backend.market.universe import MARKET_INDICES as INDICES


# Total return per calendar year from a daily series.
def yearly(dates: np.ndarray, daily: np.ndarray) -> dict[int, float]:
    """Return {year: total return} from aligned dates and daily returns."""
    years = np.array([int(str(d)[:4]) for d in dates])
    out = {}
    for y in sorted(set(years)):
        r = daily[(years == y) & np.isfinite(daily)]
        if len(r):
            out[y] = float(np.prod(1.0 + r) - 1.0)
    return out


# The CAGR a walk would have shown had its daily returns been scaled to
# another volatility. Scaling the mean (or the compounded rate) linearly is
# the classic mistake: the compounded rate carries a variance drag that grows
# with the square of the scale, so `cagr * k` overstates or understates the
# matched return. The correct number compounds the scaled daily returns.
def matched_at_volatility(daily: np.ndarray, target_vol: float) -> float:
    """Return the compounded CAGR of `daily` scaled to `target_vol`."""
    r = np.asarray(daily, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return float("nan")
    vol = float(r.std() * np.sqrt(252))
    if vol <= 0:
        return float("nan")
    scaled = 1.0 + (target_vol / vol) * r
    if np.any(scaled <= 0.0):
        return float("nan")
    years = len(r) / 252.0
    return float(np.prod(scaled) ** (1.0 / years) - 1.0) if years > 0 else float("nan")


# One row of the portfolio-vs-benchmark block.
def _portfolio_line(name: str, total: float, drawdown: float, exposure: float) -> str:
    return (
        f"{name:34} {total:+10.1%} {drawdown:9.1%} "
        f"{exposure:12.1%}"
    )


# The whole portfolio against the benchmarks: net compounded return (after
# the desk's costs), worst drawdown, and how much of the account was in
# positions on average. A benchmark is a fully invested buy-and-hold, so its
# exposure is 100% by construction and its return carries no cost.
def _portfolio_block(results, store, first) -> list[str]:
    """Return the comparison lines for the candidates and the benchmarks."""
    lines = [
        "",
        f"{'portfolio vs benchmark':34} {'compounded':>10} {'worst DD':>9} "
        f"{'avg exposure':>12}",
    ]
    for name in results:
        s = results[name].stats()
        invested = results[name].invested
        known = np.isfinite(invested)
        exposure = (
            float(np.nanmean(invested))
            if invested is not None and known.any()
            else float("nan")
        )
        lines.append(_portfolio_line(name, s["total"], s["drawdown"], exposure))
    if store is not None:
        for ticker in INDICES:
            daily = index_returns(store, ticker, first.dates)
            if daily is None or not np.isfinite(daily).any():
                # A benchmark with no bars at all is not a 0% benchmark: a
                # series nobody refreshes must not read as a flat cash line.
                continue
            known = np.isfinite(daily)
            curve = np.cumprod(1.0 + daily[known])
            total = float(curve[-1] - 1.0)
            drawdown = float((curve / np.maximum.accumulate(curve) - 1.0).min())
            lines.append(_portfolio_line(ticker, total, drawdown, 1.0))
    return lines


# An index's daily returns from the store, aligned to the dates given.
def index_returns(store, ticker: str, dates: np.ndarray) -> np.ndarray | None:
    """Return daily returns of `ticker` on `dates`, NaN where absent."""
    frame = store.read_frame("bars", ticker)
    if frame is None:
        return None
    cols = frame[0]
    key = next(
        k
        for k in cols
        if k not in ("open", "high", "low", "close", "volume", "adj_close")
    )
    stamps = np.array([str(d)[:10] for d in cols[key]])
    close = np.array(
        cols["adj_close"] if "adj_close" in cols else cols["close"], dtype=float
    )
    by = dict(zip(stamps, close, strict=True))
    prices = np.array([by.get(str(d)[:10], np.nan) for d in dates])
    out = np.full(len(dates), np.nan)
    with np.errstate(all="ignore"):
        out[1:] = prices[1:] / prices[:-1] - 1.0
    return out


# The table. `results` maps a name to its SimResult; the first is the
# rule the others are matched to.
def render(results: dict[str, SimResult], store=None, loss_limit: float = 0.25) -> str:
    """Return the scorecard as text."""
    names = list(results)
    rule = results[names[0]].stats()
    lines = [
        f"{'candidate':34} {'CAGR':>7} {'at rule vol':>11} {'vol':>6} {'Sharpe':>7} "
        f"{'worst DD':>9} {'turnover':>9} {'top pos':>8} {'within limit':>13}"
    ]
    for name in names:
        s = results[name].stats()
        matched = (
            matched_at_volatility(results[name].returns, rule["volatility"])
            if s["volatility"] > 0
            else float("nan")
        )
        within = "yes" if s["drawdown"] > -loss_limit else "NO"
        lines.append(
            f"{name:34} {s['cagr']:+7.1%} {matched:+11.1%} {s['volatility']:6.1%} "
            f"{s['sharpe']:7.2f} {s['drawdown']:9.1%} {s['turnover']:8.1f}x "
            f"{s['max_weight']:8.1%} {within:>13}"
        )
    lines.extend(
        _portfolio_block(results, store, results[names[0]])
    )
    first = results[names[0]]
    table = {name: yearly(results[name].dates, results[name].returns) for name in names}
    if store is not None:
        for ticker in INDICES:
            daily = index_returns(store, ticker, first.dates)
            if daily is not None:
                table[ticker] = yearly(first.dates, daily)
    years = sorted(set().union(*[set(v) for v in table.values()]))
    lines.append("")
    lines.append(f"{'total return by year':34} " + " ".join(f"{y:>7}" for y in years))
    for name, values in table.items():
        cells = " ".join(
            f"{values[y]:+7.1%}" if y in values else f"{'':>7}" for y in years
        )
        lines.append(f"{name:34} {cells}")
    beats = []
    for name in names[1:]:
        won = sum(
            1
            for y in years
            if y in table[name] and table[name][y] > table[names[0]].get(y, np.nan)
        )
        beats.append(f"{name} beats {names[0]} in {won} of {len(years)} years")
    for ticker in INDICES:
        if ticker in table:
            won = sum(
                1
                for y in years
                if y in table[ticker]
                and table[names[0]].get(y, np.nan) > table[ticker][y]
            )
            beats.append(f"{names[0]} beats {ticker} in {won} of {len(years)} years")
    if beats:
        lines.append("")
        lines.extend(beats)
    return "\n".join(lines)


def since_date(text: str) -> date:
    """Parse an ISO date for a --since argument."""
    return date.fromisoformat(text)
