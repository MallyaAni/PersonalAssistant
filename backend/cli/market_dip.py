"""A confirmed dip-buy: the conditions a trader uses, measured, then learned.

    python -m backend.cli.market_dip
    python -m backend.cli.market_dip --drop 0.08 --confirm 2 --years 2023 2024 2025 2026
    python -m backend.cli.market_dip --show IREN 2026-08-28

The question
------------
The desk ranks trend and quality on a twenty-session horizon and does
not buy dips. A trader does, and not blindly: a name that fell hard when
its peers did not, held its low for two sessions, and sits on a level it
has traded around before is a different proposition from a name that
fell with everything and is still falling. Those conditions are the
substance of the trade. This measures each of them, then lets a learner
combine them, and scores any single event on request - IREN at 35 in
late August 2026 being the one that prompted it.

The event
---------
A fall of `--drop` or more over one to three sessions, on any name in the
universe with daily bars (some five hundred, benchmarks excluded), then
`--confirm` sessions in which the close never breaks the low of the
fall. Entry is the close of the confirmation session, so nothing is
known at entry that was not. The label is the beta-adjusted forward
residual from entry over five, ten and twenty sessions, the desk's own
yardstick.

The conditions, all known at entry
----------------------------------
  own_fall        the name's return over the fall, in logs
  vs_peers        the fall less its peer basket's return over the same
                  sessions (peers: the same sector, else the universe)
  held_low        how far the entry close sits above the low of the fall
  tightening      the confirmation sessions' range against the twenty-day
                  average true range: a stabilising name trades tighter
  support_density the share of the last 250 closes within five percent
                  of the entry price - how much trading sits at this level
  above_low_250   distance above the 250-session low, in logs
  above_low_120   the same over 120
  drawdown_60     the fall from the 60-session high at entry
  volume_spike    the fall's volume against the twenty-day average
  market_week     the benchmark's five-session return at entry
  tone_rank       the desk's sentiment rank, where the name is in the book

The measurement
---------------
Each condition alone: the forward residual of events in its top and
bottom quintile, so a condition that matters shows a spread. Then a
gradient-boosted learner on all of them, fit walk-forward by year and
scored on the events of the year it never saw; its rank IC among events,
and the residual of the events it ranked in its top fifth against all
events, net of the cost of the round trip. The learner is trained on
the outcome directly - which is the "reinforcement" a person means when
they say the system should learn what worked - and it is measured the
only way that counts, on entries it did not see.

Results
-------
11,924 confirmed dips on 458 names, 2016 to 2026: a fall of 8% or more
within three sessions, the low held for two. Beta-adjusted forward
residual from the confirmation close:

  all events    next 5: mean -0.11%   next 10: -0.01%   next 20: -0.14%
                positive 50% / 51% / 49%

Each condition alone, top fifth less bottom fifth of the ten-session
residual: market week +1.24%, drawdown from the 60-session high +0.93%,
distance above the 120-session low +0.85%, size of the fall +0.40%, the
fall against peers +0.01%, stabilisation +0.46%, support density +0.02%,
tightening -0.65%, volume spike -0.42%, tone rank -0.59%. Nothing above
a percent and a quarter, and most flip sign across horizons.

The learner, walk-forward by year on the ten-session residual:

  test year   events   rank IC   all events   top fifth   net of cost
  2022         1770    +0.011      -1.56%      -1.21%       -1.41%
  2023          840    -0.044      +1.15%      -0.47%       -0.67%
  2024         1364    -0.017      -0.20%      +1.31%       +1.11%
  2025         2226    -0.035      +0.90%      +1.44%       +1.24%
  2026         1882    +0.014      +0.06%      +0.89%       +0.69%
  pooled       8082    -0.023      +0.00%      +0.48%       +0.28%

No skill out of sample. The conditions as a trader states them, made
into numbers and combined by a learner, do not sort the dips.

IREN, the event that prompted this: the fall of 28 August 2026 was
confirmed on 1 September and entered at 39.60 on the 2nd, thirteen
percent above the 34.81 low. Its conditions were what a trader would
want - the fall was its own (7.5 points worse than its peers), volume
1.3 times usual, tone rank 0.95, 43% off its 60-session high - and the
learner scored it at the 45th percentile of every event. The confirmed
entry missed most of the move: 35.45 to 39.60 happened before the low
was confirmed. The trade worked; the class of trade, entered when it
can be known to be one, does not on average. The chart network in
`market_charts` is the next attempt, with the shapes learned rather
than specified.
"""

import argparse
from datetime import date

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

FEATURES = (
    "own_fall",
    "vs_peers",
    "held_low",
    "tightening",
    "support_density",
    "above_low_250",
    "above_low_120",
    "drawdown_60",
    "volume_spike",
    "market_week",
    "tone_rank",
)
HORIZONS = (5, 10, 20)
ROUND_TRIP_BPS = 20.0
TREE_ROUNDS = 300


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Measure the confirmed dip-buy.")
    parser.add_argument("--drop", type=float, default=0.08, help="fall, fraction")
    parser.add_argument("--window", type=int, default=3, help="sessions of the fall")
    parser.add_argument(
        "--confirm", type=int, default=2, help="sessions holding the low"
    )
    parser.add_argument(
        "--years", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026]
    )
    parser.add_argument("--show", nargs=2, metavar=("TICKER", "DATE"), default=None)
    parser.add_argument("--data-dir", default="data/market")
    return parser


# The universe's members on one panel, with each name's peer group.
def _universe_panel(store):
    universe = build_universe()
    members = tickers_with_role(universe, MEMBER, FOCUS)
    sector = {m.ticker: m.sector or "" for m in universe}
    themes = {t: g for t, g in theme_map(universe).items() if t in members}
    panel = build_panel(store, tuple(sorted(members)), MARKET_BENCHMARK, themes)
    return panel, sector


# Trailing sums of log returns over `k` sessions, NaN until the window fills.
def _trailing(logr: np.ndarray, k: int) -> np.ndarray:
    out = np.full(logr.shape, np.nan)
    clean = np.where(np.isfinite(logr), logr, 0.0)
    cum = np.cumsum(clean, axis=0)
    out[k:] = cum[k:] - cum[:-k]
    out[k - 1] = cum[k - 1]
    return out


# Rolling extreme over the previous `k` sessions, inclusive.
def _rolling(values: np.ndarray, k: int, largest: bool) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    fn = np.nanmax if largest else np.nanmin
    with np.errstate(all="ignore"):
        for t in range(k - 1, values.shape[0]):
            out[t] = fn(values[t - k + 1 : t + 1], axis=0)
    return out


# The peer basket's return per session: the sector's mean, else the
# universe's, benchmark excluded.
def _peer_returns(panel, sector: dict, logr: np.ndarray) -> np.ndarray:
    groups: dict[str, list[int]] = {}
    for i, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        groups.setdefault(sector.get(ticker, "") or "all", []).append(i)
    with np.errstate(all="ignore"):
        overall = np.nanmean(logr[:, [i for g in groups.values() for i in g]], axis=1)
    peers = np.tile(overall[:, None], (1, logr.shape[1]))
    for name, cols in groups.items():
        if name != "all" and len(cols) >= 5:
            with np.errstate(all="ignore"):
                # Each name against its sector without itself.
                total = np.nansum(logr[:, cols], axis=1, keepdims=True)
                count = np.isfinite(logr[:, cols]).sum(axis=1, keepdims=True)
                own = np.where(np.isfinite(logr[:, cols]), logr[:, cols], 0.0)
                peers[:, cols] = (total - own) / np.maximum(count - 1, 1)
    return peers


# Every event's row: entry session, column, the conditions, the labels.
def _events(panel, sector, tone_rank, drop: float, window: int, confirm: int):
    close, high, low, volume = panel.adj_close, panel.high, panel.low, panel.volume
    logr = panel.log_returns()
    rows, names = close.shape
    fall = np.minimum.reduce([_trailing(logr, k) for k in range(1, window + 1)])
    peers = _peer_returns(panel, sector, logr)
    peer_fall = np.minimum.reduce([_trailing(peers, k) for k in range(1, window + 1)])
    low_of_fall = _rolling(low, window, largest=False)
    with np.errstate(all="ignore"):
        rng = high - low
        atr20 = np.full(rng.shape, np.nan)
        for t in range(19, rows):
            atr20[t] = np.nanmean(rng[t - 19 : t + 1], axis=0)
        vol20 = np.full(volume.shape, np.nan)
        for t in range(19, rows):
            vol20[t] = np.nanmean(volume[t - 19 : t + 1], axis=0)
        low250 = _rolling(close, 250, largest=False)
        low120 = _rolling(close, 120, largest=False)
        high60 = _rolling(close, 60, largest=True)
        bench = panel.index(panel.benchmark)
        market_week = _trailing(logr, 5)[:, bench]
    labels = {h: panel.forward_residual(h) for h in HORIZONS}
    out = []
    fell = fall <= np.log(1.0 - drop)
    for t in range(260, rows - confirm):
        for n in np.flatnonzero(fell[t]):
            if n == bench:
                continue
            e = t + confirm  # entry: the close of the confirmation session
            floor = low_of_fall[t, n]
            if not np.isfinite(floor) or np.any(close[t + 1 : e + 1, n] < floor):
                continue
            if e >= rows or not np.isfinite(close[e, n]) or close[e, n] <= 0:
                continue
            with np.errstate(all="ignore"):
                dense = np.mean(
                    np.abs(np.log(close[e - 250 : e, n] / close[e, n])) < 0.05
                )
                feats = [
                    fall[t, n],
                    fall[t, n] - peer_fall[t, n],
                    np.log(close[e, n] / floor),
                    np.nanmean(rng[t + 1 : e + 1, n]) / atr20[t, n],
                    dense,
                    np.log(close[e, n] / low250[e, n]),
                    np.log(close[e, n] / low120[e, n]),
                    np.log(close[e, n] / high60[t, n]),
                    np.nanmean(volume[t - window + 1 : t + 1, n])
                    / vol20[t - window, n],
                    market_week[e],
                    tone_rank[e, n] if tone_rank is not None else np.nan,
                ]
            out.append((e, n, feats, [labels[h][e, n] for h in HORIZONS]))
    return out


# The desk's sentiment rank on the universe panel's grid, NaN off the book.
def _tone_rank(store, panel):
    from backend.agents.trading.desk import desk as trading_desk

    report = trading_desk.run(store)
    ranks = report.opinions["sentiment"].ranks()
    out = np.full(panel.adj_close.shape, np.nan)
    col = {t: i for i, t in enumerate(panel.tickers)}
    row = {d: i for i, d in enumerate(panel.dates.tolist())}
    for j, ticker in enumerate(report.panel.tickers):
        if ticker not in col:
            continue
        for i, d in enumerate(report.panel.dates.tolist()):
            if d in row:
                out[row[d], col[ticker]] = ranks[i, j]
    return out


# Each condition alone: the label's mean in its top and bottom quintile.
def _one_at_a_time(x: np.ndarray, y: np.ndarray) -> None:
    cell = f"{'bottom 5th':>10} {'top 5th':>8} {'spread':>7} |"
    cells = "  ".join(cell for _ in HORIZONS)
    print(f"\n{'condition':16} {'n':>6}  " + cells)
    for i, name in enumerate(FEATURES):
        known = np.isfinite(x[:, i])
        if known.sum() < 200:
            continue
        v = x[known, i]
        lo, hi = np.quantile(v, 0.2), np.quantile(v, 0.8)
        line = f"{name:16} {int(known.sum()):6d}  "
        for h in range(len(HORIZONS)):
            yy = y[known, h]
            b, t = np.nanmean(yy[v <= lo]), np.nanmean(yy[v >= hi])
            line += f"  {b:+10.2%} {t:+8.2%} {t - b:+7.2%} |"
        print(line)


# The learner, walk-forward by year on the ten-session label.
def _learned(x, y, years, test_years, entry_dates) -> None:
    import lightgbm as lgb

    target = 1  # the ten-session residual
    params = {
        "objective": "regression",
        "learning_rate": 0.03,
        "num_leaves": 15,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 10.0,
        "verbosity": -1,
    }
    print(
        f"\n{'test year':10} {'events':>7} {'rank IC':>8} {'all events':>11} "
        f"{'top fifth':>10} {'net of cost':>12}"
    )
    pooled_pred, pooled_y, pooled_day = [], [], []
    for year in test_years:
        train, test = years < year, years == year
        if train.sum() < 500 or test.sum() < 50:
            continue
        ok = np.isfinite(y[:, target])
        booster = lgb.train(
            params,
            lgb.Dataset(x[train & ok], label=y[train & ok, target]),
            num_boost_round=TREE_ROUNDS,
        )
        pred = booster.predict(x[test])
        yt = y[test, target]
        good = np.isfinite(yt)
        from scipy.stats import spearmanr

        ic = spearmanr(pred[good], yt[good]).statistic
        top = pred[good] >= np.quantile(pred[good], 0.8)
        top_mean = float(np.mean(yt[good][top]))
        print(
            f"{year:<10} {int(good.sum()):7d} {ic:+8.3f} {np.mean(yt[good]):+11.2%} "
            f"{top_mean:+10.2%} {top_mean - ROUND_TRIP_BPS / 1e4:+12.2%}"
        )
        pooled_pred.append(pred[good])
        pooled_y.append(yt[good])
        pooled_day.append(entry_dates[test][good])
    if pooled_pred:
        p, yy = np.concatenate(pooled_pred), np.concatenate(pooled_y)
        from scipy.stats import spearmanr

        top = p >= np.quantile(p, 0.8)
        top_mean = float(np.mean(yy[top]))
        print(
            f"{'pooled':10} {len(p):7d} {spearmanr(p, yy).statistic:+8.3f} "
            f"{np.mean(yy):+11.2%} {top_mean:+10.2%} "
            f"{top_mean - ROUND_TRIP_BPS / 1e4:+12.2%}"
        )
        gains = booster.feature_importance("gain")
        ranked = sorted(zip(FEATURES, gains, strict=True), key=lambda kv: -kv[1])[:6]
        print("  importance: " + ", ".join(f"{n} {g:.0f}" for n, g in ranked))
    return booster


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    panel, sector = _universe_panel(store)
    tone = _tone_rank(store, panel)
    events = _events(panel, sector, tone, args.drop, args.window, args.confirm)
    x = np.array([e[2] for e in events], dtype=float)
    y = np.array([e[3] for e in events], dtype=float)
    entry = np.array([panel.dates[e[0]] for e in events])
    years = entry.astype("datetime64[Y]").astype(int) + 1970
    print(
        f"{len(events):,} confirmed dips on {len(set(e[1] for e in events))} names, "
        f"{entry.min()} to {entry.max()}; a fall of {args.drop:.0%}+ within "
        f"{args.window} "
        f"sessions, the low held for {args.confirm}"
    )
    for h, label in zip(range(len(HORIZONS)), HORIZONS, strict=True):
        v = y[np.isfinite(y[:, h]), h]
        print(
            f"  all events, next {label:2d}: mean {v.mean():+.2%}, "
            f"median {np.median(v):+.2%}, positive {np.mean(v > 0):.0%}"
        )
    _one_at_a_time(x, y)
    booster = _learned(x, y, years, args.years, entry)
    if args.show:
        ticker, when = args.show[0].upper(), date.fromisoformat(args.show[1])
        col = panel.index(ticker)
        session = int(np.searchsorted(panel.dates, np.datetime64(when)))
        hits = [
            e for e in events if e[1] == col and 0 <= e[0] - session <= args.confirm + 1
        ]
        if not hits:
            print(f"\nno confirmed dip for {ticker} around {when}")
            return
        e = hits[-1]
        print(
            f"\n{ticker} entered {panel.dates[e[0]]} "
            f"at {panel.adj_close[e[0], col]:.2f}:"
        )
        for name, value in zip(FEATURES, e[2], strict=True):
            print(f"  {name:16} {value:+.3f}")
        score = booster.predict(np.array([e[2]], dtype=float))[0]
        all_scores = booster.predict(x)
        print(
            f"  learner's score {score:+.4f}, "
            f"percentile {np.mean(all_scores <= score):.0%} of every event"
        )
        print(
            "  what followed, if known: "
            + ", ".join(
                f"{h}: {v:+.2%}"
                for h, v in zip(HORIZONS, e[3], strict=True)
                if np.isfinite(v)
            )
        )


if __name__ == "__main__":
    main()
