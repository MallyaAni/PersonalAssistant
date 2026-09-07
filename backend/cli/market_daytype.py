"""Is it an AI day or a software day, green or red, and can the morning say?

    python -m backend.cli.market_daytype
    python -m backend.cli.market_daytype --at 11:30 --years 2023 2024 2025 2026

The question
------------
A person watching the tape reads the first hour and decides what kind
of day it is: the AI names leading or the software names, the market
closing green or red. If that read is right more often than chance, it
changes what to buy and when to sell today. It is a question about
patterns in the first candles, and it is measurable: take everything
known at `--at` on the New York clock and ask whether it predicts the
rest of the session, walk-forward, against the naive rule that the
morning simply continues.

The material
------------
The book's fifteen-minute bars, the AI names and the software names
averaged into two baskets by their side in the book, and the tape: the
five hundred universe names averaged, since no ETF has bars in the store.
At the cut-off each session: each basket's return since the open, its
overnight gap, its return yesterday and over the last five sessions, the
benchmark's the same, and the spread of the two baskets so far today.

Two targets from the cut-off to the close:

  colour   the tape's rest-of-day return is positive
  leader   the AI basket beats the software basket over the rest of day

Three readers, walk-forward by year on the sessions before the test
year: the naive continuation (the morning's sign), a logistic regression,
and gradient-boosted trees. Scored by hit rate and by the rest-of-day
return the reader would have captured, against a coin.

What this cannot claim: a hit rate a few points above a half is a
pattern a person cannot see, and it is also the size of effect that
disappears at cost; the return columns say whether it survives. And the
sample is one book's sessions since 2020.

Results
-------
1,512 sessions from 2020-08 to 2026-09, 67 AI names and 26 software
names, the five hundred universe names as the tape; walk-forward by
year, 2022 to 2026 pooled. Hit rate, and the rest-of-day return captured
by going with the call:

  from 10:30            colour (green/red)      leader (AI over software)
  coin (always long)     52.0%   +0.0 bps         51.3%   +1.9 bps
  morning continues      51.6%   +1.7 bps         52.5%   +3.5 bps
  logistic               49.5%   -1.5 bps         51.5%   +3.3 bps
  boosted trees          50.9%   +0.3 bps         52.4%   +3.5 bps

  from 11:30
  coin (always long)     53.7%   +0.4 bps         52.7%   +2.8 bps
  morning continues      52.8%   +2.2 bps         50.3%   +2.8 bps
  logistic               52.4%   +1.0 bps         50.2%   +0.7 bps
  boosted trees          50.9%   -1.2 bps         49.0%   -1.2 bps

  from 12:30
  coin (always long)     52.0%   +0.7 bps         52.0%   +2.0 bps
  morning continues      51.8%   +2.5 bps         48.0%   +0.1 bps
  logistic               49.8%   +1.4 bps         51.5%   +1.3 bps
  boosted trees          52.5%   +1.8 bps         51.9%   -0.3 bps

No reader beats the coin by more than a point or two of hit rate at any
cut-off, and the most any of them captures is three and a half basis
points of rest-of-day return - inside a single spread. The first hour,
the first two, the first three: none of them says what kind of day it is
in a way a book can use. Whatever a person feels they read in the
morning tape, these features do not carry it, and the learners do not
find it in them either. The day's colour and its leader are decided by
what the day has not yet shown.
"""

import argparse

import numpy as np

from backend.market import intraday
from backend.market.universe import (
    FOCUS,
    MEMBER,
    book_sides,
    build_universe,
    tickers_with_role,
)

BARS = intraday.BARS
FEATURES = (
    "ai_so_far",
    "sw_so_far",
    "mkt_so_far",
    "spread_so_far",
    "ai_gap",
    "sw_gap",
    "mkt_gap",
    "ai_yesterday",
    "sw_yesterday",
    "mkt_yesterday",
    "ai_week",
    "sw_week",
    "mkt_week",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Read the day from its first hour.")
    parser.add_argument("--at", default="10:30", help="the cut-off, New York time")
    parser.add_argument(
        "--years", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026]
    )
    parser.add_argument("--data-dir", default="data/market")
    return parser


# One name's sessions as bar log returns (days x BARS) with the overnight
# gap in the first bar, keyed by day.
def _series(root, ticker) -> dict:
    if not (root / f"{ticker}.parquet").exists():
        return {}  # a name the intraday fetch never covered
    got = intraday.episodes(root, ticker)
    if got is None:
        return {}
    days, close, _high, _low, _volume, open0, prev = got
    logc = np.log(close)
    bars = np.zeros_like(logc)
    bars[:, 1:] = np.diff(logc, axis=1)
    with np.errstate(all="ignore"):
        bars[:, 0] = logc[:, 0] - np.log(open0)
        gap = np.log(open0 / prev)
    return {d: (bars[i], gap[i]) for i, d in enumerate(days)}


# The basket's bars and gap per day: the mean over the names present.
def _basket(series: list[dict]) -> dict:
    days = sorted(set().union(*[set(s) for s in series]))
    out = {}
    for d in days:
        rows = [s[d] for s in series if d in s]
        if len(rows) >= max(3, len(series) // 3):
            out[d] = (
                np.mean([r[0] for r in rows], axis=0),
                float(np.nanmean([r[1] for r in rows])),
            )
    return out


# The feature row and the two targets for one session at the cut-off.
def _row(day, index, ai, sw, mkt, cut: int):
    prev_days = [d for d in index if d < day][-5:]
    if len(prev_days) < 5 or day not in ai or day not in sw or day not in mkt:
        return None

    def so_far(b):
        return float(b[day][0][:cut].sum())

    def rest(b):
        return float(b[day][0][cut:].sum())

    def yesterday(b):
        return float(b[prev_days[-1]][0].sum() + b[prev_days[-1]][1])

    def week(b):
        return float(sum(b[d][0].sum() + b[d][1] for d in prev_days))

    x = [
        so_far(ai),
        so_far(sw),
        so_far(mkt),
        so_far(ai) - so_far(sw),
        ai[day][1],
        sw[day][1],
        mkt[day][1],
        yesterday(ai),
        yesterday(sw),
        yesterday(mkt),
        week(ai),
        week(sw),
        week(mkt),
    ]
    if not np.all(np.isfinite(x)):
        return None
    return x, rest(mkt), rest(ai) - rest(sw)


# Score a reader: hit rate and the rest-of-day return it captures when it
# goes with its call (long the benchmark or long the leader basket).
def _score(name, call, rest):
    hit = float(np.mean((call > 0) == (rest > 0)))
    captured = float(np.mean(np.where(call > 0, rest, -rest)))
    return f"{name:28} {hit:8.1%} {captured * 1e4:+9.1f} bps"


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    hour, minute = (int(v) for v in args.at.split(":"))
    cut = ((hour * 60 + minute) - intraday.OPEN_LOCAL) // 15
    root = intraday.partition()
    universe = build_universe()
    sides = book_sides(universe)
    ai = _basket([_series(root, t) for t, s in sides.items() if s == "ai"])
    sw = _basket([_series(root, t) for t, s in sides.items() if s == "software"])
    # The tape: every name with fifteen-minute bars, averaged. No ETF has
    # bars in the store, and five hundred names are a fair market.
    everyone = tickers_with_role(universe, MEMBER, FOCUS)
    mkt = _basket([_series(root, t) for t in everyone])
    index = sorted(set(ai) & set(sw) & set(mkt))
    rows = [(d, _row(d, index, ai, sw, mkt, cut)) for d in index]
    rows = [(d, r) for d, r in rows if r is not None]
    x = np.array([r[0] for _, r in rows])
    colour = np.array([r[1] for _, r in rows])
    leader = np.array([r[2] for _, r in rows])
    years = np.array([int(str(d)[:4]) for d, _ in rows])
    print(
        f"{len(rows)} sessions, cut-off {args.at} New York ({cut} bars in), "
        f"{sum(1 for s in sides.values() if s == 'ai')} AI names, "
        f"{sum(1 for s in sides.values() if s == 'software')} software names"
    )
    green, ai_leads = np.mean(colour > 0), np.mean(leader > 0)
    print(f"  base rates: green {green:.1%}, AI leads {ai_leads:.1%}")
    for label, target, naive in (
        ("colour: green or red", colour, x[:, 2]),
        ("leader: AI over software", leader, x[:, 3]),
    ):
        print(f"\n=== {label}, rest of day from {args.at}")
        print(f"{'reader':28} {'hit rate':>8} {'captured':>13}")
        pooled: dict[str, list] = {
            "morning continues": [],
            "logistic": [],
            "boosted trees": [],
        }
        rests = []
        for year in args.years:
            train, test = years < year, years == year
            if train.sum() < 200 or test.sum() < 20:
                continue
            pooled["morning continues"].append(naive[test])
            pooled["logistic"].append(_logistic(x[train], target[train], x[test]))
            pooled["boosted trees"].append(_trees(x[train], target[train], x[test]))
            rests.append(target[test])
        rest = np.concatenate(rests)
        print(_score("coin (always long)", np.ones(len(rest)), rest))
        for name, calls in pooled.items():
            print(_score(name, np.concatenate(calls), rest))


# Logistic regression on standardised features, returning a signed call.
def _logistic(x_fit, y_fit, x_test) -> np.ndarray:
    mean, std = x_fit.mean(axis=0), x_fit.std(axis=0) + 1e-9
    zf, zt = (x_fit - mean) / std, (x_test - mean) / std
    zf = np.column_stack([np.ones(len(zf)), zf])
    zt = np.column_stack([np.ones(len(zt)), zt])
    w = np.zeros(zf.shape[1])
    y = (y_fit > 0).astype(float)
    for _ in range(200):
        p = 1 / (1 + np.exp(-zf @ w))
        grad = zf.T @ (p - y) / len(y) + 1e-2 * w
        hess = (zf * (p * (1 - p))[:, None]).T @ zf / len(y) + 1e-2 * np.eye(len(w))
        w -= np.linalg.solve(hess, grad)
    return zt @ w


# Boosted trees on the sign, returning a signed call.
def _trees(x_fit, y_fit, x_test) -> np.ndarray:
    import lightgbm as lgb

    params = {
        "objective": "binary",
        "learning_rate": 0.03,
        "num_leaves": 7,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 10.0,
        "verbosity": -1,
    }
    booster = lgb.train(params, lgb.Dataset(x_fit, label=(y_fit > 0).astype(int)), 200)
    return booster.predict(x_test) - 0.5


if __name__ == "__main__":
    main()
