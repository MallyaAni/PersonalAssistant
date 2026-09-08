"""Improving technicals into earnings: does the slope mean more when a report is near?

    python -m backend.cli.market_earnings
    python -m backend.cli.market_earnings --near 15 --book
    python -m backend.cli.market_earnings --show ORCL

The claim
---------
A trader's argument: when earnings are two weeks out and the 21-day EMA
is turning up toward the 50, the turn has a reason - the market is
positioning for the report - so it should carry further than the same
turn on a quiet tape. ORCL in September 2026 was the case that prompted
it. The technical analyst scores the 21-above-50-and-rising trend and
cites the 21/50 convergence but does not score it, because on its own the
convergence measured nothing. This asks the narrower question: does it
measure something *conditional on earnings being near*?

The data
--------
Every 8-K with item 2.02 (results of operations) in the EDGAR layer gives
the reaction session of every results release since 2016 for the whole
universe (some five hundred names, benchmarks excluded). The reaction
session is the filing's own session when it was accepted before the
open, else the next. "Near" is one to `--near` sessions before that
reaction session. In practice the date is announced two to four weeks
ahead, so a window of ten to fifteen sessions is one a trader knows.
"Far" is more than thirty sessions from the nearest report on either
side. The look-ahead caveat is real but small: the *date* is known ahead,
and nothing about the result is used.

The conditions, from the technical feature set, all known at the close
------------------------------------------------------------------------
  slope_up      the (21 - 50) EMA spread rose over the last three sessions
  converging    the spread is below zero and rising: a cross up is coming
  ema21_up      the 21 EMA itself rose over five sessions
  trend_up      the 21 is above the 50 and the spread is still widening

The measurement
---------------
The label is the beta-adjusted forward residual over five, ten and
twenty sessions, and two event-shaped horizons: to the close before the
report (the drift a trader front-runs) and through the reaction session
(what they keep if they hold the print). For each condition, the residual
of names near earnings with the condition against those near without it,
and the same spread far from earnings. The interaction - the near spread
less the far spread - is the claim. The t statistics are Newey-West on
the per-session mean difference, lagged by the horizon, so overlapping
windows and names moving together are both counted once. The two
event-shaped labels are only comparable inside the near window, where
every horizon is at most `--near` sessions; far from a report they would
span a month or more, so those cells are left blank.

Results, 2026-09-07
-------------------
Universe: 526 names, 24,371 results releases, 2016 to 2026. Near a
report, names with a rising 21/50 spread did no better than names
without one: -0.23% over twenty sessions (t -1.1), -0.14% into the
close before the print (t -1.6). Far from a report the same spread is
-0.06%. The interaction, the whole claim, is -0.17% (t -0.9). Nothing.

The book (88 names, 3,483 releases) says the opposite of the claim.
Ten sessions before a report, a rising 21/50 spread was followed by
-1.38% over twenty sessions (t -2.7), -0.55% into the close before the
print (t -2.8) and -0.74% through it (t -2.0), against names in the
same window whose spread was falling. The sign held in nine of the
eleven years; 2026 is one of the two exceptions (+1.5%, t 1.1, on 107
sessions). The 21-above-50-and-widening trend near a report reads the
same: -1.18% (t -2.0). The convergence from below, the exact
"about to cross" shape, is -0.48% (t -0.8): nothing, on 5,825 cells.

Reading: on these names a technical turn into earnings is the run-up,
and the run-up is what gets sold. The report is the event that makes
the trader's slope mean something, and what it means is that the move
has been made. So the technical analyst keeps citing the convergence
and not scoring it, and near a report the improving slope is, if
anything, a reason to wait for the print rather than to front-run it.
"""

import argparse
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from backend.market import technical
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
FAR = 30
OPEN_ET = time(9, 30)
ET = ZoneInfo("America/New_York")
CONDITIONS = ("slope_up", "converging", "ema21_up", "trend_up")


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument(
        "--near", type=int, default=10, help="sessions before the report"
    )
    parser.add_argument(
        "--book", action="store_true", help="the desk's book names only"
    )
    parser.add_argument("--since", default="2016-01-01")
    parser.add_argument(
        "--show", metavar="TICKER", help="the name's next report and its slope today"
    )
    return parser


def _universe_panel(store, book_only: bool):
    universe = build_universe()
    members = tickers_with_role(universe, MEMBER, FOCUS)
    if book_only:
        members = [t for t in members if t in book_sides(universe)]
    themes = {t: g for t, g in theme_map(universe).items() if t in members}
    return build_panel(store, tuple(sorted(members)), MARKET_BENCHMARK, themes)


# The reaction session of each results release: the filing's session when
# it was accepted before the open, else the next session.
def reaction_sessions(dates: list[date], events: dict[str, list]) -> list[int]:
    """Return sorted panel row indices of the results releases in `events`."""
    out = set()
    n = len(dates)
    for accepted, filed, items in zip(
        events.get("accepted", []),
        events.get("filed", []),
        events.get("items", []),
        strict=True,
    ):
        if "2.02" not in str(items or "").split(","):
            continue
        when = datetime.fromisoformat(str(accepted)).astimezone(ET)
        day = filed if isinstance(filed, date) else date.fromisoformat(str(filed))
        after_open = when.time() >= OPEN_ET
        i = int(
            np.searchsorted(
                np.array(dates), day, side="right" if after_open else "left"
            )
        )
        if i < n:
            out.add(i)
    return sorted(out)


# Sessions until the next report and since the last, per (session, name).
def report_distances(rows: int, reactions: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Return (until_next, since_last) in sessions, inf where none."""
    until = np.full(rows, np.inf)
    since = np.full(rows, np.inf)
    nxt = None
    for t in range(rows - 1, -1, -1):
        if t in reactions:
            nxt = t
        if nxt is not None:
            until[t] = nxt - t
    last = None
    for t in range(rows):
        if t in reactions:
            last = t
        if last is not None:
            since[t] = t - last
    return until, since


def _hac_t(diff: np.ndarray, lag: int) -> float:
    n = len(diff)
    if n < 10:
        return float("nan")
    d = diff - diff.mean()
    var = float(d @ d) / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2.0 * (1.0 - k / (lag + 1)) * float(d[:-k] @ d[k:]) / n
    return float(diff.mean() / np.sqrt(max(var, 1e-12) / n))


# The per-session mean of `label` over the cells where `mask` holds.
def _session_means(label: np.ndarray, mask: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        s = np.where(mask & np.isfinite(label), label, 0.0).sum(axis=1)
        c = (mask & np.isfinite(label)).sum(axis=1)
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)


# Mean of A less mean of B, session by session, and its Newey-West t.
def _spread(label, a, b, lag):
    ma, mb = _session_means(label, a), _session_means(label, b)
    ok = np.isfinite(ma) & np.isfinite(mb)
    if ok.sum() < 10:
        return float("nan"), float("nan"), 0
    d = ma[ok] - mb[ok]
    return float(d.mean()), _hac_t(d, lag), int(ok.sum())


# Residual from each session to the close of a per-cell target row.
def _residual_to(panel, target: np.ndarray, beta: np.ndarray) -> np.ndarray:
    adj = panel.adj_close
    bench = adj[:, panel.index(panel.benchmark)]
    out = np.full(adj.shape, np.nan)
    rows, cols = adj.shape
    for j in range(cols):
        for t in range(rows):
            r = target[t, j]
            if not np.isfinite(r):
                continue
            r = int(r)
            if r <= t or r >= rows:
                continue
            with np.errstate(all="ignore"):
                own = np.log(adj[r, j] / adj[t, j])
                mkt = np.log(bench[r] / bench[t])
            if np.isfinite(own) and np.isfinite(mkt) and np.isfinite(beta[t, j]):
                out[t, j] = own - beta[t, j] * mkt
    return out


def _conditions(feats: np.ndarray) -> dict[str, np.ndarray]:
    idx = {n: i for i, n in enumerate(technical.TECHNICAL_NAMES)}
    spread = feats[:, :, idx["spread_21_50"]]
    slope = feats[:, :, idx["spread_21_50_slope"]]
    e21 = feats[:, :, idx["ema21_slope"]]
    known = np.isfinite(spread) & np.isfinite(slope) & np.isfinite(e21)
    return {
        "_known": known,
        "slope_up": known & (slope > 0),
        "converging": known & (spread < 0) & (slope > 0),
        "ema21_up": known & (e21 > 0),
        "trend_up": known & (spread > 0) & (slope > 0),
    }


def _table(panel, labels, conds, near, far, years):
    names = list(labels)
    head = f"{'condition':11} {'where':5} {'n':>7}  " + "  ".join(
        f"{n:>17}" for n in names
    )
    print("\n" + head)
    for c in CONDITIONS:
        yes, no = conds[c], conds["_known"] & ~conds[c]
        for where, zone in (("near", near), ("far", far)):
            n = int((zone & yes).sum())
            line = f"{c:11} {where:5} {n:7d}  "
            for name in names:
                lag = labels[name][1]
                m, t, _ = _spread(labels[name][0], zone & yes, zone & no, lag)
                line += f"  {m:+8.2%} (t {t:5.1f})"
            print(line)
        line = f"{'':11} {'diff':5} {'':7}  "
        for name in names:
            lab, lag = labels[name]
            mn, _, _ = _spread(lab, near & yes, near & no, lag)
            mf, _, _ = _spread(lab, far & yes, far & no, lag)
            # The interaction's t: the near-spread series less the far-spread
            # series, session by session.
            a = _session_means(lab, near & yes) - _session_means(lab, near & no)
            b = _session_means(lab, far & yes) - _session_means(lab, far & no)
            ok = np.isfinite(a) & np.isfinite(b)
            t = _hac_t(a[ok] - b[ok], lag) if ok.sum() >= 10 else float("nan")
            line += f"  {mn - mf:+8.2%} (t {t:5.1f})"
        print(line)
    print(
        "\nslope_up near earnings, by year "
        "(twenty-session residual, with less without):"
    )
    yes, no = conds["slope_up"], conds["_known"] & ~conds["slope_up"]
    lab, lag = labels["20 sessions"]
    for y in sorted(set(years)):
        rows = years == y
        m, t, n = _spread(lab[rows], (near & yes)[rows], (near & no)[rows], lag)
        mf, _, _ = _spread(lab[rows], (far & yes)[rows], (far & no)[rows], lag)
        print(f"  {y}: near {m:+7.2%} (t {t:4.1f})   far {mf:+7.2%}   sessions {n}")


def _show(panel, ticker, until, since, feats, reactions):
    j = panel.index(ticker)
    t = len(panel.dates) - 1
    idx = {n: i for i, n in enumerate(technical.TECHNICAL_NAMES)}
    print(f"{ticker} at {panel.dates[t]}:")
    print(
        f"  21/50 spread {feats[t, j, idx['spread_21_50']]:+.4f}, "
        f"its 3-session slope {feats[t, j, idx['spread_21_50_slope']]:+.5f}"
    )
    print(f"  21 EMA 5-session slope {feats[t, j, idx['ema21_slope']]:+.4f}")
    last = [panel.dates[r] for r in reactions[j][-3:]]
    print(f"  last reports (reaction sessions): {last}")
    print(
        f"  sessions since the last report: {since[t, j]:.0f}; "
        "the next is not in the store until it is filed"
    )


def main() -> None:
    """Run the study."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.root))
    panel = _universe_panel(store, args.book)
    dates = [d.astype("datetime64[D]").astype(object) for d in panel.dates]
    rows, cols = panel.adj_close.shape
    feats = technical.technical_features(panel)
    until = np.full((rows, cols), np.inf)
    since = np.full((rows, cols), np.inf)
    reactions: dict[int, list[int]] = {}
    covered = 0
    for j, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        frame = store.read_frame("edgar_events", ticker)
        if frame is None:
            continue
        r = reaction_sessions(dates, frame[0])
        reactions[j] = r
        if r:
            covered += 1
        until[:, j], since[:, j] = report_distances(rows, r)
    if args.show:
        _show(panel, args.show.upper(), until, since, feats, reactions)
        return
    print(
        f"{covered} names with results releases on file, "
        f"{sum(len(v) for v in reactions.values())} releases"
    )
    beta = panel.rolling_beta(120)
    start = np.searchsorted(np.array(dates), date.fromisoformat(args.since))
    in_range = np.zeros((rows, cols), dtype=bool)
    in_range[start:] = True
    in_range[:, panel.index(panel.benchmark)] = False
    near = in_range & (until >= 1) & (until <= args.near)
    far = in_range & (until > FAR) & (since > FAR)
    target_pre = np.where(
        np.isfinite(until) & (until >= 1), np.arange(rows)[:, None] + until - 1, np.nan
    )
    target_thru = np.where(
        np.isfinite(until) & (until >= 1), np.arange(rows)[:, None] + until, np.nan
    )
    labels = {f"{h} sessions": (panel.forward_residual(h), h) for h in HORIZONS}
    labels["to the close before"] = (_residual_to(panel, target_pre, beta), args.near)
    labels["through the print"] = (
        _residual_to(panel, target_thru, beta),
        args.near + 1,
    )
    for name in ("to the close before", "through the print"):
        lab, lag = labels[name]
        labels[name] = (np.where(near, lab, np.nan), lag)
    conds = _conditions(feats)
    years = np.array([d.year for d in dates])
    print(
        f"near = 1..{args.near} sessions before a report; "
        f"far = more than {FAR} from any"
    )
    _table(panel, labels, conds, near, far, years)


if __name__ == "__main__":
    main()
