"""Quality names stretched below their averages: does the snapback pay?

    python -m backend.cli.market_snapback
    python -m backend.cli.market_snapback --stretch 0.2 --volume 1.5

The claim
---------
A trader's argument: a quality name that has overextended to the
downside, below its short-term averages and ideally on heavy volume, is
a buy for the mean-reversion snapback, and a technical analyst that
marks it down for sitting below its averages has the sign wrong on
exactly those names. The technical analyst's evidence was measured
among names that already qualify on fundamentals and release tone, and
strength beat dips there; this asks the narrower question the trader
asks, on the desk's own book.

The cells
---------
Every (session, name) on the book since 2018. Quality is the
fundamental analyst's rank in the top half of the book that day (and,
as a stricter cut, the top third). Stretched is the name's distance
below its 21-day EMA in the bottom `--stretch` fraction of the book that
day and negative (it is below the average, and further below than most).
Volume is the session's volume at `--volume` times its twenty-session
average or more. Everything is known at the close.

The measurement
---------------
The beta-adjusted forward residual over five, ten and twenty sessions
for quality names that are stretched against quality names that are
not, the same with the volume condition, and the same among names the
technical analyst is against (the cells the claim says are graded
wrong). Newey-West t on the per-session mean difference. Then the
grades: what the desk gave those cells, and what the same cells earned
when the technical analyst was for the name instead, which is the
comparison that says whether the analyst's sign is right on them.

Results, 2026-09-08
-------------------
Book of 93 names, 2018 to 2026, beta-adjusted forward residual.

Quality does not make a stretched name a buy. Quality names in the
bottom tenth of the book by distance below the 21-day EMA earned the
same as quality names that were not: +0.01% at five sessions (t 0.0),
-0.02% at twenty (t 0.0), on 7,718 cells. With volume at 1.5x the
twenty-day average, +0.50% at twenty sessions (t 0.8). The top third
of quality reads the same. The cells the claim says are graded wrong,
quality and stretched with the technical analyst against, earned
-0.73% over twenty sessions against quality names the analyst was for
(t -1.0): the analyst's sign is right on them, weakly. Those cells
were graded C 64% of the time, B 25%.

Two results from the literature, asked of this book. Medhat and
Schmeling's short-term momentum in high-turnover names does not
appear: last-month winners lag losers by 0.56% in the high-turnover
half (t -1.0), a weak reversal. But the stretch does interact with
turnover: stretched names in the high-turnover half earned +0.98% over
twenty sessions against unstretched ones (t 2.3), and in the
low-turnover half -0.74% (t -1.1). By year it is 2022 (+3.9%, t 2.8)
and 2023 (+2.4%) with nothing before 2021 and -0.8% in 2026, and at a
wider stretch (bottom fifth) it halves (t 1.5). Nagel's stress
dependence is there in the five-session bounce after a stretched,
heavy-volume session: +0.77% (t 2.5) on stressed sessions, +0.07% on
calm ones, though on calm sessions the same cells earned +1.1% by
twenty sessions (t 2.1).

The test that counts. With the technical analyst made neutral on the
10,241 stretched high-turnover cells and the book run under its own
rules from 2021-06: +31.2% a year, Sharpe 1.80, worst drawdown -20.1%,
against the rule's +31.8%, 1.85, -19.0%. The snapback is real in two
years and costs the book across five. The grading stands.
"""

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import grading, simulate
from backend.market import technical
from backend.market.store import MarketStore

HORIZONS = (5, 10, 20)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--stretch", type=float, default=0.1, help="bottom fraction")
    parser.add_argument(
        "--volume", type=float, default=1.5, help="times 20-day average"
    )
    parser.add_argument("--since", default="2018-01-01")
    parser.add_argument(
        "--book",
        action="store_true",
        help="the book with technical neutral on stretched high-turnover names",
    )
    parser.add_argument("--book-since", default="2021-06-01")
    return parser


def _hac_t(diff: np.ndarray, lag: int) -> float:
    n = len(diff)
    if n < 10:
        return float("nan")
    d = diff - diff.mean()
    var = float(d @ d) / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2.0 * (1.0 - k / (lag + 1)) * float(d[:-k] @ d[k:]) / n
    return float(diff.mean() / np.sqrt(max(var, 1e-12) / n))


def _session_means(label: np.ndarray, mask: np.ndarray) -> np.ndarray:
    ok = mask & np.isfinite(label)
    with np.errstate(all="ignore"):
        s = np.where(ok, label, 0.0).sum(axis=1)
        c = ok.sum(axis=1)
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)


# Mean of A less mean of B, session by session, its Newey-West t, and n.
def _spread(label, a, b, lag):
    ma, mb = _session_means(label, a), _session_means(label, b)
    ok = np.isfinite(ma) & np.isfinite(mb)
    if ok.sum() < 10:
        return float("nan"), float("nan"), 0
    d = ma[ok] - mb[ok]
    return float(d.mean()), _hac_t(d, lag), int((a & np.isfinite(label)).sum())


# Per-session bottom-fraction flag of a (T, N) reading across `universe`.
def _bottom(values: np.ndarray, universe: np.ndarray, fraction: float) -> np.ndarray:
    out = np.zeros(values.shape, dtype=bool)
    for t in range(values.shape[0]):
        row = np.where(universe[t] & np.isfinite(values[t]), values[t], np.nan)
        known = np.isfinite(row)
        if known.sum() < 10:
            continue
        cut = np.nanquantile(row, fraction)
        out[t] = known & (row <= cut)
    return out


def _line(name, labels, a, b):
    parts = []
    for h in HORIZONS:
        m, t, n = _spread(labels[h], a, b, h)
        parts.append(f"{m:+8.2%} (t {t:5.1f})")
    n = int(a.sum())
    print(f"{name:52} {n:7d}  " + "  ".join(parts))


# Two results from the literature, asked of this book.
#
# Medhat and Schmeling (RFS 2022, "Short-term Momentum"): sorted on last
# month's return and share turnover, low-turnover names reverse over the
# next month and high-turnover names continue. If it holds here, the
# stretched high-turnover name is the one not to buy for a snapback.
#
# Nagel (2012, "Evaporating Liquidity") and Da, Liu and Schaumburg
# (2014): the short-term reversal is payment for liquidity provision,
# larger when the market is stressed. If the five-session bounce after a
# stretched, heavy-volume session is that, it should be bigger when the
# book's own volatility is high.
def _papers(report, universe, stretched, heavy, labels, vol, avg) -> None:
    panel = report.panel
    adj = panel.adj_close
    rows = adj.shape[0]
    with np.errstate(all="ignore"):
        last_month = np.full_like(adj, np.nan)
        last_month[21:] = np.log(adj[21:] / adj[:-21])
        dollar = avg * panel.close
    cap = report.opinions["value"].evidence.get("market_cap")
    print("\nMedhat and Schmeling: last month's return by turnover, twenty sessions")
    if cap is None:
        print("  no market cap on the value analyst; turnover cannot be formed")
    else:
        with np.errstate(all="ignore"):
            turnover = dollar / np.asarray(cap, dtype=float)
        top_turn = _bottom(-turnover, universe, 0.5)
        low_turn = universe & ~top_turn & np.isfinite(turnover)
        winners = _bottom(-last_month, universe, 0.2)
        losers = _bottom(last_month, universe, 0.2)
        _line(
            "high turnover: last-month winners vs losers",
            labels,
            top_turn & winners,
            top_turn & losers,
        )
        _line(
            "low turnover: last-month winners vs losers",
            labels,
            low_turn & winners,
            low_turn & losers,
        )
        _line(
            "high turnover & stretched vs high turnover & not",
            labels,
            top_turn & stretched,
            top_turn & ~stretched,
        )
        _line(
            "low turnover & stretched vs low turnover & not",
            labels,
            low_turn & stretched,
            low_turn & ~stretched,
        )
        years = np.array([str(d)[:4] for d in panel.dates])
        print("  high turnover & stretched vs not, by year, twenty sessions:")
        for y in sorted(set(years[universe.any(axis=1)])):
            r = years == y
            m, t, n = _spread(
                labels[20][r], (top_turn & stretched)[r], (top_turn & ~stretched)[r], 20
            )
            print(f"    {y}: {m:+7.2%} (t {t:4.1f})  cells {n}")
    print("\nNagel: the stretched-and-heavy-volume bounce by the book's own stress")
    in_book = universe.any(axis=0)
    with np.errstate(all="ignore"):
        logr = np.diff(np.log(adj), axis=0, prepend=np.nan)
        basket = np.nanmean(np.where(in_book[None, :], logr, np.nan), axis=1)
        stress = np.full(rows, np.nan)
        for t in range(20, rows):
            stress[t] = np.nanstd(basket[t - 20 : t])
    calm = np.isfinite(stress) & (stress <= np.nanmedian(stress))
    tense = np.isfinite(stress) & (stress > np.nanmedian(stress))
    _line(
        "calm sessions: stretched & volume vs not",
        labels,
        stretched & heavy & calm[:, None],
        universe & ~stretched & calm[:, None],
    )
    _line(
        "stressed sessions: stretched & volume vs not",
        labels,
        stretched & heavy & tense[:, None],
        universe & ~stretched & tense[:, None],
    )


# The test that counts: the book itself, full rules, with the technical
# analyst made neutral on the cells the study found (stretched names in
# the high-turnover half), against the rule. The cell means above are
# per-name averages; the book trades a tenth of the universe every
# twenty sessions with costs, and every overlay measured so far lost
# there whatever its cell means said.
def _book(report, universe, stretched, avg, since: str) -> None:
    panel = report.panel
    cap = report.opinions["value"].evidence.get("market_cap")
    if cap is None:
        print("\nno market cap; the book test needs turnover")
        return
    with np.errstate(all="ignore"):
        turnover = (avg * panel.close) / np.asarray(cap, dtype=float)
    top_turn = _bottom(-turnover, universe, 0.5)
    cells = top_turn & stretched
    technical = report.opinions["technical"]
    scores = technical.scores.copy()
    in_book = universe.any(axis=0)
    # Neutral: the book's median technical score that day, so the stance
    # thresholds read the name as neither for nor against.
    with np.errstate(all="ignore"):
        median = np.nanmedian(np.where(in_book[None, :], scores, np.nan), axis=1)
    scores = np.where(cells, median[:, None], scores)
    opinions = dict(report.opinions)
    opinions["technical"] = replace(technical, scores=scores)
    graded = grading.grade(
        opinions["fundamental"],
        opinions["technical"],
        opinions["sentiment"],
        report.regime.rotation,
        opinions["value"],
        grading.ANALYST_WEIGHTS,
    )
    adjusted = replace(
        report,
        opinions=opinions,
        graded=graded,
        scores=graded.as_scores(trading_desk.blended(opinions)),
    )
    start = date.fromisoformat(since)
    print(
        f"\nthe book from {since}, technical neutral on {int(cells.sum()):,} stretched "
        f"high-turnover cells: {'annual':>8} {'vol':>7} {'Sharpe':>7} "
        f"{'maxDD':>8} {'total':>9}"
    )
    for name, rep_ in (
        ("the rule", report),
        ("technical neutral on snapback cells", adjusted),
    ):
        stats = simulate.run(rep_, since=start, use_exits=False).stats()
        print(
            f"{name:38} {stats['annual']:+8.1%} {stats['volatility']:7.1%} "
            f"{stats['sharpe']:7.2f} {stats['drawdown']:8.1%} {stats['total']:+9.1%}"
        )


def main() -> None:
    """Run the study."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(Path(args.root)))
    panel = report.panel
    rows, cols = panel.adj_close.shape
    dates = [str(d)[:10] for d in panel.dates]
    start = int(np.searchsorted(np.array(dates), args.since))
    in_book = np.array([t in report.sides for t in panel.tickers])
    universe = np.zeros((rows, cols), dtype=bool)
    universe[start:] = in_book[None, :]
    universe &= np.isfinite(panel.adj_close)

    feats = technical.technical_features(panel)
    idx = {n: i for i, n in enumerate(technical.TECHNICAL_NAMES)}
    ema21 = feats[:, :, idx["ema21_distance"]]
    stretched = _bottom(ema21, universe, args.stretch) & (ema21 < 0)
    vol = panel.volume.astype(float)
    avg = np.full_like(vol, np.nan)
    for t in range(20, rows):
        with np.errstate(all="ignore"):
            avg[t] = np.nanmean(vol[t - 20 : t], axis=0)
    with np.errstate(all="ignore"):
        heavy = universe & (vol >= args.volume * avg)

    fund = report.opinions["fundamental"].ranks()
    quality = universe & np.isfinite(fund) & (fund >= 0.5)
    strict = universe & np.isfinite(fund) & (fund >= 2.0 / 3.0)
    tech = report.graded.stances["technical"]
    tech_against = universe & (tech < 0)
    tech_for = universe & (tech > 0)
    grade = report.graded.grades  # 3 A+, 2 A, 1 B, 0 C

    labels = {h: panel.forward_residual(h) for h in HORIZONS}
    head = f"{'cells (A against B), forward residual':52} {'n(A)':>7}  " + "  ".join(
        f"{h:>3} sessions      " for h in HORIZONS
    )
    print(
        f"book of {int(in_book.sum())} names from {dates[start]}; stretched = bottom "
        f"{args.stretch:.0%} of the book by distance below the 21-day EMA; "
        f"volume = {args.volume:g}x the 20-day average"
    )
    print("\n" + head)
    _line(
        "quality & stretched vs quality & not",
        labels,
        quality & stretched,
        quality & ~stretched,
    )
    _line(
        "quality & stretched & volume vs quality & not",
        labels,
        quality & stretched & heavy,
        quality & ~stretched,
    )
    _line(
        "top-third quality & stretched vs same not",
        labels,
        strict & stretched,
        strict & ~stretched,
    )
    _line(
        "top-third & stretched & volume vs same not",
        labels,
        strict & stretched & heavy,
        strict & ~stretched,
    )
    _line("anyone stretched vs not", labels, stretched, universe & ~stretched)
    _line(
        "anyone stretched & volume vs not",
        labels,
        stretched & heavy,
        universe & ~stretched,
    )
    print("\nthe cells the claim says are graded wrong:")
    _line(
        "quality & stretched & technical against vs tech for",
        labels,
        quality & stretched & tech_against,
        quality & tech_for,
    )
    _line(
        "quality & stretched & tech against vs quality & tech against & not stretched",
        labels,
        quality & stretched & tech_against,
        quality & tech_against & ~stretched,
    )
    _line(
        "quality & technical against (all) vs quality & technical for",
        labels,
        quality & tech_against,
        quality & tech_for,
    )
    cells = quality & stretched
    if cells.any():
        g = grade[cells]
        print(
            f"\ngrades given to quality & stretched cells: "
            f"A+ {np.mean(g == 3):.0%}, A {np.mean(g == 2):.0%}, "
            f"B {np.mean(g == 1):.0%}, C {np.mean(g == 0):.0%}; "
            f"technical against in {np.mean(tech[cells] < 0):.0%} of them"
        )
    _papers(report, universe, stretched, heavy, labels, vol, avg)
    if args.book:
        _book(report, universe, stretched, avg, args.book_since)
    print("\nby year, quality & stretched vs quality & not, twenty sessions:")
    years = np.array([d[:4] for d in dates])
    for y in sorted(set(years[start:])):
        r = years == y
        m, t, n = _spread(
            labels[20][r], (quality & stretched)[r], (quality & ~stretched)[r], 20
        )
        print(f"  {y}: {m:+7.2%} (t {t:4.1f})  cells {n}")


if __name__ == "__main__":
    main()
