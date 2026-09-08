"""Chart structure, written down and measured: swings, setups, breakouts.

    python -m backend.cli.market_structure
    python -m backend.cli.market_structure --book

The claim
---------
A trader reads structure off a chart: higher highs and higher lows are
an uptrend, lower highs and lower lows a downtrend, rising lows into a
flat ceiling are a breakout setting up, and the close through the last
swing high is the breakout, on more than one timeframe. The chart
network was given the raw bars and found nothing on these names; the
objection is that it did not know what to look for. So here the
patterns are written down explicitly, from the confirmed swing points
the levels module already finds, and measured directly. If the explicit
features carry forward return, a network could refine them; if they do
not, a network on the same bars has nothing to refine.

The features, all from bars up to the session
---------------------------------------------
Swing points are confirmed pivots: a low that is the lowest of its `k`
neighbours either side, known only when the right-hand neighbours have
printed, stamped on the confirming session. Two timeframes: k = 5
(swings of about two weeks) and k = 20 (swings of about two months).
From the last two confirmed swing highs and lows on each:

  up         higher high and higher low
  down       lower high and lower low
  setup      higher low, the two highs within 2% of each other, and the
             close within 3% below that ceiling: rising lows into a flat
             top, the breakout setting up
  breakout   the close above the last swing high, having been at or
             below it the session before; with volume at 1.5x the
             twenty-session average as the confirmed version
  breakdown  the close below the last swing low, the same way
  agree      up on both timeframes; disagree, one up and one down

The measurement
---------------
The beta-adjusted forward residual over five, ten and twenty sessions
of each state against the rest of the universe that day, Newey-West t
on the per-session mean difference. Five hundred names since 2016, and
the book's ninety-three with `--book`. `--overlay` runs the book under
its own rules with a mid-cycle add on the one pattern the cells
favoured.

Results, 2026-09-08
-------------------
531 names, 2016 to 2026, beta-adjusted forward residual, twenty
sessions unless said. Structure carries no forward return. Higher high
and higher low on the two-week swings: -0.02% (t -0.2) on 491,297
cells; on the two-month swings -0.16% (t -1.4). Lower and lower:
+0.08%. The breakout setting up (rising lows into a flat top, price
near it): -0.11% (t -1.0). Both timeframes agreeing up: -0.19%
(t -1.4). The one thing with a sign is the volume split on the breakout
itself: a close through the last two-week swing high on thin volume
fades, -0.20% at ten sessions (t -3.1, 40,496 cells), and on volume at
1.5x the twenty-session average it does not, +0.19% (t 1.6, 10,572
cells); against each other +0.42% (t 3.3). The fakeout is real; the
confirmed breakout is a coin with a slight edge, not a signal.

On the book (93 names) the same shape, larger: thin breakouts -0.44%
at ten sessions (t -2.8), volume breakouts +0.70% (t 2.4), +0.70% at
twenty (t 1.6); against each other +1.00% (t 2.9). By year the volume
breakout is negative 2017 to 2020 and positive 2023 to 2026. On the
two-month swings the volume breakout is -0.46% (t -1.3). The bounce in
a downtrend (two-month structure down, two-week up) reads +0.90% at
twenty sessions (t 2.0), the only multi-timeframe state with a sign.

The test that counts. A 3% add from cash on a two-week breakout on
volume in a name graded A or better, inside the book's rules from
2021-06, 174 adds: +33.0% a year, Sharpe 1.78, worst drawdown -20.3%,
against the rule's +31.8%, 1.85, -19.0%. Funded from the other names:
+32.3%, 1.80, -19.2%. The add earns by adding exposure to names the
desk already owns, not by timing; per unit of risk it loses, as the
dip add did. Written down, the patterns a trader reads are either
nothing or a volume filter on a fade, and a network given the same bars
found nothing, which agrees. The grading stands.
"""

import argparse
from pathlib import Path

import numpy as np

from backend.cli.market_snapback import _line, _spread
from backend.market import levels
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    book_sides,
    build_universe,
    theme_map,
    tickers_with_role,
)

HORIZONS = (5, 10, 20)
FLAT_TOP = 0.02
NEAR_TOP = 0.03


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument(
        "--book", action="store_true", help="the desk's book names only"
    )
    parser.add_argument("--since", default="2016-01-01")
    parser.add_argument("--volume", type=float, default=1.5)
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="the book with a 3% add on a two-week breakout on volume in an A name",
    )
    parser.add_argument("--book-since", default="2021-06-01")
    return parser


def _universe_panel(store, book_only: bool):
    universe = build_universe()
    members = tickers_with_role(universe, MEMBER, FOCUS)
    if book_only:
        members = [t for t in members if t in book_sides(universe)]
    themes = {t: g for t, g in theme_map(universe).items() if t in members}
    return build_panel(store, tuple(sorted(members)), MARKET_BENCHMARK, themes)


# The last two confirmed swing levels as of each session, per name:
# (newest, older), NaN until two exist. `stamped` is (T, N) with the level
# on its confirming session and NaN elsewhere.
def last_two(stamped: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (newest, older) (T, N) arrays of the last two confirmed levels."""
    rows, cols = stamped.shape
    newest = np.full((rows, cols), np.nan)
    older = np.full((rows, cols), np.nan)
    for j in range(cols):
        a = b = np.nan
        col = stamped[:, j]
        for t in range(rows):
            v = col[t]
            if np.isfinite(v):
                b, a = a, v
            newest[t, j] = a
            older[t, j] = b
    return newest, older


# The structure states from the last two highs and lows and the close.
def states(close, h1, h2, l1, l2) -> dict[str, np.ndarray]:
    """Return {state: (T, N) bool} for up, down, setup, breakout, breakdown."""
    known = np.isfinite(h1) & np.isfinite(h2) & np.isfinite(l1) & np.isfinite(l2)
    with np.errstate(all="ignore"):
        up = known & (h1 > h2) & (l1 > l2)
        down = known & (h1 < h2) & (l1 < l2)
        ceiling = np.maximum(h1, h2)
        flat = known & (np.abs(h1 - h2) / ceiling < FLAT_TOP)
        setup = (
            flat & (l1 > l2) & (close <= ceiling) & (close >= ceiling * (1 - NEAR_TOP))
        )
        above = known & (close > h1)
        below = known & (close < l1)
        prev_above = np.zeros_like(above)
        prev_above[1:] = above[:-1]
        prev_below = np.zeros_like(below)
        prev_below[1:] = below[:-1]
        breakout = above & ~prev_above
        breakdown = below & ~prev_below
    return {
        "known": known,
        "up": up,
        "down": down,
        "setup": setup,
        "breakout": breakout,
        "breakdown": breakdown,
    }


# The test that counts: the book under its own rules with a mid-cycle add
# on the one pattern the cells favoured, a two-week breakout on volume in
# a name graded A or better, against the rule. Funded from cash and from
# the other names.
def _overlay(root: Path, volume: float, since: str) -> None:
    from datetime import date

    from backend.agents.trading.desk import desk as trading_desk
    from backend.agents.trading.desk import simulate

    report = trading_desk.run(MarketStore(root))
    panel = report.panel
    rows = panel.adj_close.shape[0]
    low, high = levels.swing_points(panel.high, panel.low, 5)
    h1, h2 = last_two(high)
    l1, l2 = last_two(low)
    st = states(panel.close, h1, h2, l1, l2)
    vol = panel.volume.astype(float)
    avg = np.full_like(vol, np.nan)
    for t in range(20, rows):
        with np.errstate(all="ignore"):
            avg[t] = np.nanmean(vol[t - 20 : t], axis=0)
    with np.errstate(all="ignore"):
        heavy = vol >= volume * avg
    graded_a = report.graded.grades >= 2  # A+ is 3, A is 2
    in_book = np.array([t in report.sides for t in panel.tickers])
    signal = st["breakout"] & heavy & graded_a & in_book[None, :]
    start = date.fromisoformat(since)
    dates = np.array([str(d)[:10] for d in panel.dates])
    fires = int(signal[np.searchsorted(dates, since) :].sum())
    print(
        f"\nthe book from {since}, a 3% add on a two-week breakout on volume "
        f"in an A name ({fires} fires):"
    )
    print(
        f"{'':40} {'annual':>8} {'vol':>7} {'Sharpe':>7} {'maxDD':>8} "
        f"{'total':>9} {'adds':>5}"
    )
    for name, rule in (
        ("the rule", None),
        (
            "breakout add from cash",
            simulate.DipRule(signal=signal, add=0.03, funded=False),
        ),
        (
            "breakout add, funded",
            simulate.DipRule(signal=signal, add=0.03, funded=True),
        ),
    ):
        result = simulate.run(report, since=start, use_exits=False, dip=rule)
        stats = result.stats()
        print(
            f"{name:40} {stats['annual']:+8.1%} {stats['volatility']:7.1%} "
            f"{stats['sharpe']:7.2f} {stats['drawdown']:8.1%} {stats['total']:+9.1%} "
            f"{result.dip_adds:5d}"
        )


def main() -> None:
    """Run the study."""
    args = build_parser().parse_args()
    if args.overlay:
        _overlay(Path(args.root), args.volume, args.book_since)
        return
    panel = _universe_panel(MarketStore(Path(args.root)), args.book)
    rows, cols = panel.adj_close.shape
    dates = [str(d)[:10] for d in panel.dates]
    start = int(np.searchsorted(np.array(dates), args.since))
    universe = np.zeros((rows, cols), dtype=bool)
    universe[start:] = True
    universe[:, panel.index(panel.benchmark)] = False
    universe &= np.isfinite(panel.adj_close)
    close = panel.close
    vol = panel.volume.astype(float)
    avg = np.full_like(vol, np.nan)
    for t in range(20, rows):
        with np.errstate(all="ignore"):
            avg[t] = np.nanmean(vol[t - 20 : t], axis=0)
    with np.errstate(all="ignore"):
        heavy = vol >= args.volume * avg
    labels = {h: panel.forward_residual(h) for h in HORIZONS}
    by_k = {}
    for k in (5, 20):
        low, high = levels.swing_points(panel.high, panel.low, k)
        h1, h2 = last_two(high)
        l1, l2 = last_two(low)
        by_k[k] = {
            name: universe & flag
            for name, flag in states(close, h1, h2, l1, l2).items()
        }
    print(
        f"{cols - 1} names from {dates[start]}; "
        "swings confirmed at k = 5 and k = 20 bars"
    )
    head = f"{'state (A against the rest that day)':52} {'n(A)':>7}  " + "  ".join(
        f"{h:>3} sessions      " for h in HORIZONS
    )
    for k in (5, 20):
        st = by_k[k]
        rest = st["known"]
        print(f"\nk = {k}\n{head}")
        _line("up: higher high and higher low", labels, st["up"], rest & ~st["up"])
        _line("down: lower high and lower low", labels, st["down"], rest & ~st["down"])
        _line(
            "setup: rising lows into a flat top, near it",
            labels,
            st["setup"],
            rest & ~st["setup"],
        )
        _line(
            "breakout: close through the last swing high",
            labels,
            st["breakout"],
            rest & ~st["breakout"],
        )
        _line(
            "breakout on volume", labels, st["breakout"] & heavy, rest & ~st["breakout"]
        )
        _line(
            "breakout on thin volume",
            labels,
            st["breakout"] & ~heavy,
            rest & ~st["breakout"],
        )
        _line(
            "breakout on volume vs breakout on thin volume",
            labels,
            st["breakout"] & heavy,
            st["breakout"] & ~heavy,
        )
        _line(
            "breakout from a setup (setup the day before)",
            labels,
            st["breakout"] & _shift(st["setup"]),
            rest & ~st["breakout"],
        )
        _line(
            "breakdown: close through the last swing low",
            labels,
            st["breakdown"],
            rest & ~st["breakdown"],
        )
    a, b = by_k[5], by_k[20]
    both = a["known"] & b["known"]
    print(f"\nboth timeframes\n{head}")
    _line(
        "agree up: up on k=5 and k=20",
        labels,
        a["up"] & b["up"],
        both & ~(a["up"] & b["up"]),
    )
    _line("agree down", labels, a["down"] & b["down"], both & ~(a["down"] & b["down"]))
    _line(
        "k=20 up, k=5 down (pullback in a trend)",
        labels,
        b["up"] & a["down"],
        both & ~(b["up"] & a["down"]),
    )
    _line(
        "k=20 down, k=5 up (bounce in a downtrend)",
        labels,
        b["down"] & a["up"],
        both & ~(b["down"] & a["up"]),
    )
    _line(
        "k=5 breakout inside a k=20 uptrend",
        labels,
        a["breakout"] & b["up"],
        both & ~a["breakout"],
    )
    _line(
        "k=5 breakout on volume inside a k=20 uptrend",
        labels,
        a["breakout"] & b["up"] & heavy,
        both & ~a["breakout"],
    )
    years = np.array([d[:4] for d in dates])
    print(
        "\nby year, twenty sessions: agree up vs rest | k=5 breakout on volume vs rest"
    )
    for y in sorted(set(years[start:])):
        r = years == y
        m1, t1, n1 = _spread(
            labels[20][r], (a["up"] & b["up"])[r], (both & ~(a["up"] & b["up"]))[r], 20
        )
        m2, t2, n2 = _spread(
            labels[20][r],
            (a["breakout"] & heavy)[r],
            (a["known"] & ~a["breakout"])[r],
            20,
        )
        print(
            f"  {y}: {m1:+7.2%} (t {t1:4.1f}) n {n1:6d} | "
            f"{m2:+7.2%} (t {t2:4.1f}) n {n2:5d}"
        )


def _shift(flag: np.ndarray) -> np.ndarray:
    out = np.zeros_like(flag)
    out[1:] = flag[:-1]
    return out


if __name__ == "__main__":
    main()
