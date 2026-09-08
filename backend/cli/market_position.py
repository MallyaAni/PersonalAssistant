"""From a probability to a position: how much to buy, and when to leave.

    python -m backend.cli.market_position data/market/charts/scores-2026-09-04-20-20.npz
    python -m backend.cli.market_position SCORES --hold 20 --top 0.1 --cost 10

The question
------------
A model that says "this name is more likely to rise than that one" has
answered which. It has not answered how much, or for how long. Those are
two more decisions, and each is measurable against the same history:

  size    the position's weight at entry, as a function of the model's
          probability (the edge) and the name's volatility (the risk)
  exit    when the position leaves: after a fixed hold, at a trailing
          stop, or when the model re-scored on a later session no
          longer favours it - the edge-decay exit

The material
------------
An out-of-sample score matrix (sessions x names) saved by
`market_charts`, and the same panel it was scored on. Entries are the
top `--top` fraction of scored names on each session, held up to
`--hold` sessions, entered at that session's close and marked
close-to-close, with `--cost` basis points each way.

First the calibration: the model's probability in deciles across each
session, against the realised return and the beta-adjusted residual
over the hold. A monotone table is an edge that can be sized; a flat
one cannot be, whatever the model says.

Then the book, one rule at a time, everything else held equal:

  sizing    equal weight  |  proportional to the edge (p - 0.5)  |
            edge over volatility  |  edge over variance (Kelly-shaped)
  exits     hold to the horizon  |  trailing stop 8% and 12% off the
            peak  |  edge decay: leave when the re-scored probability
            falls below one half  |  edge decay with the 12% stop

Each book is scored by annual return, volatility, Sharpe, worst drawdown
and the mean return per trade, all net of cost, so a rule that trades
more pays for it.

What this cannot claim: the entries are the model's, so the exit and
sizing results are conditional on that model; and close-to-close entry
is a touch generous against the next open, the same bias for every rule.

Results
-------
On the daily chart network's probabilities (`market_charts`), 611,451
scored cells from 2022, the top tenth entered each session and held
twenty, ten basis points a side:

  sizing rule, hold 20            annual    vol  Sharpe   maxDD  per trade
  equal weight                    +14.4%  19.1%    0.75  -22.6%    +1.13%
  edge (p - 0.5)                  +14.4%  19.2%    0.75  -22.6%    +1.13%
  edge over volatility            +10.6%  16.7%    0.64  -19.8%    +1.13%
  edge over variance              +8.7%   14.8%    0.58  -18.9%    +1.13%

  exit rule, edge-over-volatility sizing
  hold to the horizon             +10.6%  16.7%    0.64  -19.8%    +1.13%
  trailing stop 8%                +6.3%   12.3%    0.51  -17.4%    +0.66%
  trailing stop 12%               +7.5%   14.3%    0.52  -20.4%    +0.79%
  edge decay, P(up) under a half  +9.2%   15.8%    0.58  -19.7%    +0.99%
  edge decay with the 12% stop    +6.6%   13.7%    0.48  -20.0%    +0.71%

A market-shaped long book: fourteen percent a year at a Sharpe of 0.75,
what holding these names does, which is what a signal with no
cross-sectional skill produces when its top tenth is bought. Sizing on
the edge changes nothing because the edge is noise; scaling by
volatility lowers the return with the risk. Every exit rule is worse
than holding, the stops most, and the model's own "edge decay" exit is
no better than a stop, because a probability that carried no
information at entry carries none at re-scoring. The desk's exit, the
signal at the rebalance, was measured against every one of these on
its own book and stands.
"""

import argparse

import numpy as np

from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    build_universe,
    theme_map,
    tickers_with_role,
)

SESSIONS_PER_YEAR = 252.0
VOL_WINDOW = 20


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Size and exit on a model's score.")
    parser.add_argument("scores", help="the .npz saved by market_charts")
    parser.add_argument("--hold", type=int, default=20)
    parser.add_argument(
        "--top", type=float, default=0.1, help="fraction entered each day"
    )
    parser.add_argument("--cost", type=float, default=10.0, help="bps each way")
    parser.add_argument("--data-dir", default="data/market")
    return parser


# The universe panel the scores were made on.
def _panel(store):
    universe = build_universe()
    names = tickers_with_role(universe, MEMBER, FOCUS)
    themes = {t: g for t, g in theme_map(universe).items() if t in names}
    return build_panel(store, tuple(sorted(names)), MARKET_BENCHMARK, themes)


# Trailing realised volatility per name, annualised.
def _volatility(simple: np.ndarray) -> np.ndarray:
    out = np.full(simple.shape, np.nan)
    for t in range(VOL_WINDOW, simple.shape[0]):
        out[t] = np.nanstd(simple[t - VOL_WINDOW + 1 : t + 1], axis=0)
    return out * np.sqrt(SESSIONS_PER_YEAR)


# Cross-sectional decile of each session's scores, NaN where unscored.
def _deciles(scores: np.ndarray) -> np.ndarray:
    out = np.full(scores.shape, np.nan)
    for t in range(scores.shape[0]):
        known = np.isfinite(scores[t])
        if known.sum() >= 20:
            ranks = scores[t, known].argsort().argsort()
            out[t, known] = np.floor(ranks / known.sum() * 10).clip(0, 9)
    return out


# The calibration table: realised outcomes by decile of the score.
def _calibration(scores, panel, hold: int) -> None:
    close = panel.adj_close
    with np.errstate(all="ignore"):
        forward = np.log(np.roll(close, -hold, axis=0) / close)
    forward[len(close) - hold :] = np.nan
    residual = panel.forward_residual(hold)
    deciles = _deciles(scores)
    print(
        f"\n{'decile of P(up)':16} {'cells':>8} {'mean return':>12} "
        f"{'residual':>10} {'positive':>9}"
    )
    for d in range(10):
        cells = (deciles == d) & np.isfinite(forward)
        f, r = forward[cells], residual[cells & np.isfinite(residual)]
        if len(f):
            print(
                f"{d + 1:16d} {len(f):8,d} {np.mean(f):+12.2%} "
                f"{np.mean(r):+10.2%} {np.mean(f > 0):9.0%}"
            )


# Entries: each session's top fraction by score, with the sizing rule's
# raw weight, normalised so a session's entries sum to 1 / hold of gross.
def _entries(
    scores, vol, top: float, hold: int, sizing: str
) -> list[tuple[int, int, float]]:
    out = []
    for t in range(scores.shape[0]):
        known = np.isfinite(scores[t]) & np.isfinite(vol[t]) & (vol[t] > 0)
        if known.sum() < 20:
            continue
        cols = np.flatnonzero(known)
        count = max(int(round(len(cols) * top)), 1)
        chosen = cols[np.argsort(-scores[t, cols])[:count]]
        p = scores[t, chosen]
        edge = np.clip(p - 0.5, 0.0, None) + 1e-6
        if sizing == "equal":
            raw = np.ones(count)
        elif sizing == "edge":
            raw = edge
        elif sizing == "edge over volatility":
            raw = edge / vol[t, chosen]
        else:  # edge over variance, Kelly-shaped
            raw = edge / vol[t, chosen] ** 2
        weights = raw / raw.sum() / hold
        out.extend((t, int(c), float(w)) for c, w in zip(chosen, weights, strict=True))
    return out


# When each entry leaves under a rule, given the path after it.
def _exit_session(close, scores, t, n, hold, rule, stop) -> int:
    last = min(t + hold, close.shape[0] - 1)
    peak = close[t, n]
    for k in range(t + 1, last + 1):
        price = close[k, n]
        if not np.isfinite(price):
            continue
        peak = max(peak, price)
        if stop and price <= peak * (1.0 - stop):
            return k
        if rule == "edge decay" and np.isfinite(scores[k, n]) and scores[k, n] < 0.5:
            return k
    return last


# Run the book: daily returns from every trade's weight and path, less cost.
def _book(entries, close, simple, scores, hold, rule, stop, cost_bps):
    rows = close.shape[0]
    daily = np.zeros(rows)
    per_trade = []
    for t, n, w in entries:
        if t + 1 >= rows:
            continue  # an entry on the last session has no path to mark
        e = _exit_session(close, scores, t, n, hold, rule, stop)
        path = simple[t + 1 : e + 1, n]
        path = np.where(np.isfinite(path), path, 0.0)
        daily[t + 1 : e + 1] += w * path
        daily[t + 1] -= w * cost_bps / 1e4
        daily[e] -= w * cost_bps / 1e4
        per_trade.append(float(np.prod(1 + path) - 1) - 2 * cost_bps / 1e4)
    return daily, np.array(per_trade)


# The usual numbers from a daily series.
def _stats(daily: np.ndarray, first: int) -> dict:
    d = daily[first:]
    annual = float(d.mean() * SESSIONS_PER_YEAR)
    vol = float(d.std() * np.sqrt(SESSIONS_PER_YEAR))
    equity = np.cumprod(1 + d)
    drawdown = float((equity / np.maximum.accumulate(equity) - 1).min())
    return {
        "annual": annual,
        "vol": vol,
        "sharpe": annual / vol if vol > 0 else 0.0,
        "drawdown": drawdown,
    }


def _line(name, s, trades) -> None:
    print(
        f"{name:40} {s['annual']:+8.1%} {s['vol']:7.1%} {s['sharpe']:7.2f} "
        f"{s['drawdown']:8.1%} {trades.mean():+9.2%} {len(trades):7,d}"
    )


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    saved = np.load(args.scores, allow_pickle=False)
    scores = saved["scores"].astype(float)
    panel = _panel(MarketStore(args.data_dir))
    assert tuple(saved["tickers"]) == tuple(panel.tickers), "the panel has changed"
    assert len(saved["dates"]) == len(panel.dates), "the sessions have changed"
    scores[:, panel.index(panel.benchmark)] = np.nan
    close = panel.adj_close
    simple = np.expm1(panel.log_returns())
    vol = _volatility(simple)
    scored = np.isfinite(scores).any(axis=1)
    first = int(np.argmax(scored))
    print(
        f"{int(np.isfinite(scores).sum()):,} scored cells from "
        f"{panel.dates[first]}; top {args.top:.0%} entered each session, "
        f"held up to {args.hold}, {args.cost:.0f} bps a side"
    )
    _calibration(scores, panel, args.hold)
    header = (
        f"\n{'rule':40} {'annual':>8} {'vol':>7} {'Sharpe':>7} {'maxDD':>8} "
        f"{'per trade':>9} {'trades':>7}"
    )
    print(header)
    for sizing in ("equal", "edge", "edge over volatility", "edge over variance"):
        entries = _entries(scores, vol, args.top, args.hold, sizing)
        daily, trades = _book(
            entries, close, simple, scores, args.hold, "hold", None, args.cost
        )
        _line(f"size: {sizing}, hold {args.hold}", _stats(daily, first), trades)
    print(header)
    entries = _entries(scores, vol, args.top, args.hold, "edge over volatility")
    for name, rule, stop in (
        ("hold to the horizon", "hold", None),
        ("trailing stop 8%", "hold", 0.08),
        ("trailing stop 12%", "hold", 0.12),
        ("edge decay: P(up) below one half", "edge decay", None),
        ("edge decay with the 12% stop", "edge decay", 0.12),
    ):
        daily, trades = _book(
            entries, close, simple, scores, args.hold, rule, stop, args.cost
        )
        _line(f"exit: {name}", _stats(daily, first), trades)


if __name__ == "__main__":
    main()
