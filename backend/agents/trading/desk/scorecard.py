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

INDICES = ("SPY", "QQQ")


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
            s["cagr"] * rule["volatility"] / s["volatility"]
            if s["volatility"] > 0
            else float("nan")
        )
        within = "yes" if s["drawdown"] > -loss_limit else "NO"
        lines.append(
            f"{name:34} {s['cagr']:+7.1%} {matched:+11.1%} {s['volatility']:6.1%} "
            f"{s['sharpe']:7.2f} {s['drawdown']:9.1%} {s['turnover']:8.1f}x "
            f"{s['max_weight']:8.1%} {within:>13}"
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
