"""Cutting losses on the bounce: exit a broken trend on its dead-cat rally.

    python -m backend.cli.market_bounce                 # events and the book
    python -m backend.cli.market_bounce --since 2018-06-01

The claim
---------
Stops cost this book because they sell at the low of a right-skewed path
(`desk/exit.py`). The trader's alternative: when a name turns from an
uptrend into a downtrend, do not sell the break; wait for the bounce the
downtrend usually gives - the dead-cat rally back toward the average -
and sell into that. If downtrends really do bounce and then resume, the
bounce exit gets a better price than the break and avoids the further
fall the stop was meant to avoid.

Two questions, both on the book's own names since 2015 and then inside
the book's own rules:

1. Does a bounce after a break say anything? For every session on which
   a held-grade name (B or better, in the book) is in a broken trend and
   has just bounced, the next twenty sessions beta-adjusted against the
   ordinary held session. If the bounce is a selling point the number is
   below the baseline; if the name is just resuming its uptrend it is not.

2. Does exiting there help the book? `simulate.run` with the bounce as
   the exit rule, every variant, to cash and redeployed, against the rule
   with no exit overlay. The account is the only judge; a trigger that
   looks bad in the event study but sells a name the rebalance would have
   sold anyway three sessions later changes nothing.

The trend break, two definitions
--------------------------------
  cross    the 21-day EMA crosses below the 50-day EMA after being above
           it for at least ten sessions (the cross the desk already reads)
  break50  the close falls below the 50-day SMA after at least ten
           sessions above it

The bounce, from the break, four definitions
--------------------------------------------
  pct      the close is at least X% above the lowest close since the
           break, X in 3, 5, 8
  ema21    the close comes back up to the 21-day EMA
  ema10    the close comes back up to the 10-day EMA
  upday2   two consecutive up closes after the break

The flag clears when the trend is back (EMA21 above EMA50 for the
cross; five closes above the SMA50 for the break) or when a bounce
fires, and re-arms on the next break. A `deadline` variant sells after
ten flagged sessions if no bounce came - a trader who will not wait
forever. `break` itself, selling at the break, is the control the stop
studies already measured.

Results, 2026-09-10
-------------------
Book names, 83,670 held-grade sessions since 2015. After a break, the
bounce is not a selling point: a held-grade name that has broken trend
and just bounced earns +0.4% to +0.9% beta-adjusted over the next
twenty sessions against +0.72% for any held session, every spread
within a t of 1.2 either way. On these names the dead cat is usually
the recovery.

In the book from 2021-06, fifty-six variants against the rule's +35.4%
a year, Sharpe 1.85, worst -19.0%. Every variant to cash earns less
(+25.8% to +35.0%; the closest is selling the break itself) and shrinks
the drawdown only by holding less, at matched volatility no better than
the rule. Redeployed, the best of the fifty-six (below the 50-day,
bounce 8%) earns +38.5%, Sharpe 2.02, at t +1.5 against the rule with
turnover doubled to 11x, which is what the best of fifty-six looks like
when nothing is there. By year the pattern is the exit study's: the
bounce helps in 2022, the one falling year (-7.4% to cash and -3.1%
redeployed against the rule's -9.7%), and costs in the five rising
ones. The regime analyst already cuts exposure in that state. A
five-session grace moves every row a point toward the rule and changes
nothing (below the 50-day, bounce 8%, to cash: +34.2%, Sharpe 1.99, t
-0.5). Measured, not adopted.
"""

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk import grading, simulate
from backend.market import technical
from backend.market.store import MarketStore

HORIZON = 20
MIN_TREND = 10  # sessions the trend must have held before a break counts
RECLAIM = 5  # closes back above the SMA50 that clear a break50 flag
DEADLINE = 10  # flagged sessions before the deadline variant sells anyway
HELD_GRADE = grading.ORDINAL[grading.B]  # grades are ordinal: A+ 3 .. C 0


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--since", default="2021-06-01")
    parser.add_argument("--grace", type=int, default=0)
    parser.add_argument("--lag", type=int, default=HORIZON)
    return parser


@dataclass(frozen=True)
class Signals:
    """Per session and name: the break, and every bounce read off it."""

    breaks: np.ndarray  # (T, N) True on the session the trend breaks
    flagged: np.ndarray  # (T, N) True while a break stands unresolved
    fires: dict[str, np.ndarray]  # variant name -> (T, N) exit sessions


# The state machine over one break definition: `broken[t, n]` is True on
# the session the trend is judged to have turned, `restored[t, n]` True
# where the trend is back. Walks forward so the running low since the
# break, the up-day count and the flagged count are what a trader knew.
def _walk(
    close: np.ndarray,
    broken: np.ndarray,
    restored: np.ndarray,
    ema10: np.ndarray,
    ema21: np.ndarray,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    rows, names = close.shape
    flagged = np.zeros((rows, names), dtype=bool)
    variants = ("pct3", "pct5", "pct8", "ema21", "ema10", "upday2", "break")
    fires = {v: np.zeros((rows, names), dtype=bool) for v in variants}
    fires.update(
        {v + "+deadline": np.zeros((rows, names), dtype=bool) for v in variants[:-1]}
    )
    armed = np.zeros(names, dtype=bool)
    low = np.full(names, np.nan)
    ups = np.zeros(names, dtype=int)
    age = np.zeros(names, dtype=int)
    for t in range(1, rows):
        c, prev = close[t], close[t - 1]
        known = np.isfinite(c) & np.isfinite(prev)
        # A flag clears when the trend is restored, and drops where price is unknown.
        armed &= known & ~restored[t]
        fresh = broken[t] & known & ~armed
        armed |= fresh
        low = np.where(fresh, c, np.where(armed, np.fmin(low, c), np.nan))
        ups = np.where(fresh, 0, np.where(c > prev, ups + 1, 0))
        age = np.where(fresh, 0, age + 1)
        flagged[t] = armed
        fires["break"][t] = fresh
        # Bounces are read only on flagged sessions after the break session.
        live = armed & ~fresh
        with np.errstate(invalid="ignore"):
            bounce = {
                "pct3": live & (c >= low * 1.03),
                "pct5": live & (c >= low * 1.05),
                "pct8": live & (c >= low * 1.08),
                "ema21": live & (c >= ema21[t]),
                "ema10": live & (c >= ema10[t]),
                "upday2": live & (ups >= 2),
            }
        overdue = live & (age >= DEADLINE)
        for v, hit in bounce.items():
            fires[v][t] = hit
            fires[v + "+deadline"][t] = hit | overdue
        # A fired bounce resolves the flag for every variant alike; the flag
        # is kept armed here so each variant is read off the same break, and
        # the exit itself is what the book does with it.
    return flagged, fires


# Read both break definitions off the panel.
def signals(panel) -> dict[str, Signals]:
    """Return {break definition: Signals} for the panel."""
    close = panel.adj_close
    ema10, ema21, ema50 = (technical.ema(close, n) for n in (10, 21, 50))
    sma50 = technical.sma(close, 50)
    with np.errstate(invalid="ignore"):
        above_cross = ema21 > ema50
        above_50 = close > sma50
    out = {}
    for name, above, restore_after in (
        ("cross", above_cross, 1),
        ("break50", above_50, RECLAIM),
    ):
        held = _run_length(above)
        broken = np.zeros_like(above)
        broken[1:] = (held[:-1] >= MIN_TREND) & ~above[1:] & np.isfinite(close[1:])
        restored = _run_length(above) >= restore_after
        flagged, fires = _walk(close, broken, restored, ema10, ema21)
        out[name] = Signals(broken, flagged, fires)
    return out


# Consecutive True count ending at each session, per column.
def _run_length(mask: np.ndarray) -> np.ndarray:
    out = np.zeros(mask.shape, dtype=int)
    for t in range(mask.shape[0]):
        out[t] = np.where(mask[t], (out[t - 1] if t else 0) + 1, 0)
    return out


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
    s = np.where(ok, label, 0.0).sum(axis=1)
    c = ok.sum(axis=1)
    return np.where(c > 0, s / np.maximum(c, 1), np.nan)


# Question 1: the next twenty sessions after each trigger, against the
# ordinary held session, session-mean spread with a Newey-West t.
def events(report, sigs: dict[str, Signals], lag: int) -> None:
    """Print the event study."""
    panel = report.panel
    label = panel.forward_residual(HORIZON)
    in_book = np.array([t in report.sides for t in panel.tickers])
    in_book[panel.index(panel.benchmark)] = False
    held = (report.graded.grades >= HELD_GRADE) & in_book[None, :]
    base = _session_means(label, held)
    ok_base = np.isfinite(base)
    print(
        f"held-grade sessions {int((held & np.isfinite(label)).sum()):,}: "
        f"next {HORIZON} beta-adjusted {100 * np.nanmean(label[held]):+.2f}%"
    )
    print(f"{'trigger':24} {'fires':>8} {'next 20':>9} {'vs held':>9} {'t':>6}")
    for bname, sig in sigs.items():
        rows = [("flagged (any session)", sig.flagged)] + [
            (v, m) for v, m in sig.fires.items() if "deadline" not in v
        ]
        for v, m in rows:
            mask = m & held
            n = int((mask & np.isfinite(label)).sum())
            mean = float(np.nanmean(label[mask])) if n else float("nan")
            own = _session_means(label, mask)
            ok = ok_base & np.isfinite(own)
            d = own[ok] - base[ok]
            t = _hac_t(d, lag) if ok.sum() >= 10 else float("nan")
            spread = float(d.mean()) if ok.sum() else float("nan")
            print(
                f"{bname + ' ' + v:24} {n:8,} {100 * mean:+8.2f}% "
                f"{100 * spread:+8.2f}% {t:+6.1f}"
            )


@dataclass(frozen=True)
class _Rule(exit_analyst.ExitEvidence):
    """An ExitEvidence whose signal is a precomputed matrix."""

    fires: np.ndarray | None = None

    def signalled(self) -> np.ndarray:
        """Return the precomputed (T, N) exit sessions."""
        return self.fires


def _rule(fires: np.ndarray) -> _Rule:
    blank = np.zeros(fires.shape)
    return _Rule(blank, blank, np.zeros(fires.shape, dtype=bool), fires)


def _row(name: str, stats: dict[str, float], base: dict[str, float], exits: int) -> str:
    matched = (
        stats["cagr"] * base["volatility"] / stats["volatility"]
        if stats["volatility"] > 0
        else float("nan")
    )
    return (
        f"{name:34} {100 * stats['cagr']:+6.1f}% {100 * matched:+7.1f}% "
        f"{100 * stats['volatility']:5.1f}% {stats['sharpe']:6.2f} "
        f"{100 * stats['drawdown']:+7.1f}% {stats['turnover']:5.1f}x {exits:5d}"
    )


# Question 2: the book with each bounce as its exit rule.
def book(report, sigs: dict[str, Signals], since: date, grace: int, lag: int) -> None:
    """Print the in-book comparison."""
    base_run = simulate.run(report, since=since, use_exits=False)
    base = base_run.stats()
    print(
        f"\n{'the book from ' + str(since):34} {'CAGR':>7} {'at vol':>8} {'vol':>6} "
        f"{'Sharpe':>6} {'worst':>8} {'turns':>6} {'exits':>5} {'t':>6}"
    )
    print(_row("no exit overlay (the rule)", base, base, 0))
    for bname, sig in sigs.items():
        for v, fires in sig.fires.items():
            for redeploy in (False, True):
                res = simulate.run(
                    report,
                    since=since,
                    exits=_rule(fires),
                    grace=grace,
                    redeploy=redeploy,
                )
                exits = sum(1 for tr in res.trades if tr.reason == "no exit condition")
                ok = np.isfinite(res.returns) & np.isfinite(base_run.returns)
                t = _hac_t(res.returns[ok] - base_run.returns[ok], lag)
                label = f"{bname} {v}{' redeployed' if redeploy else ' to cash'}"
                print(_row(label, res.stats(), base, exits) + f" {t:+6.1f}")


def main() -> None:
    """Run the study."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(Path(args.root)))
    sigs = signals(report.panel)
    events(report, sigs, args.lag)
    book(report, sigs, date.fromisoformat(args.since), args.grace, args.lag)


if __name__ == "__main__":
    main()
