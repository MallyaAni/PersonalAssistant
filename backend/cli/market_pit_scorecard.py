"""The first honest scorecard: the rule against a point-in-time book and funded indexes.

    python -m backend.cli.market_pit_scorecard
    python -m backend.cli.market_pit_scorecard --root data/market --offsets 20 --costs 10 25

Every published curve so far graded 2016-2026 on the book as it stands today,
and the equal-weight version of that book beats every rule the desk has - so
the rule's lead over QQQ has been mostly the choice of names, made with
hindsight. This command prices six things on identical sessions, at every
phase of the 20-session clock and at two costs, and reports them side by side
without choosing among them:

  rule / today's book        what every published curve showed
  rule / point-in-time       the same rule, restricted each session to the
                             names the book could have held then
                             (`point_in_time.restrict`, from the dated
                             membership file)
  equal weight / point-in-time   the survivorship hurdle: every eligible name,
                             equal weight, rebalanced on the same clock
  equal weight / today's book    the hindsight ceiling
  SPY, QQQ                   funded like the rules by `benchmarks.load_benchmark`

Two windows are always reported apart: 2016-2023 (the choosing window) and
2024-2026 (already examined by every earlier study; reported, never tuned
on). Across the offsets the median and the worst are shown, plus how many
offsets the rule beats the equal-weight point-in-time book and QQQ. The
paired daily difference at the median offset carries a Newey-West t and a
probabilistic Sharpe. No gate is applied here; this is the number the gate
reads.

Read-only with respect to the desk and the store; writes
`<root>/desk/pit_scorecard.json`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import event_risk, grading, paper, point_in_time, simulate
from backend.market import benchmarks, candidate_stats
from backend.market.universe import MARKET_INDICES

FILE = "pit_scorecard.json"
WINDOWS: dict[str, tuple[date | None, date | None]] = {
    "2016-2023": (date(2016, 1, 1), date(2024, 1, 1)),
    "2024-2026": (date(2024, 1, 1), None),
    "all": (None, None),
}
RULE_TODAY = "rule / today's book"
RULE_PIT = "rule / point-in-time"
EW_PIT = "equal weight / point-in-time"
EW_TODAY = "equal weight / today's book"

# Allocation arms the scorecard can put on the rule lines. Each is a factory
# taking the (T, N) membership mask and returning a `simulate.run` allocator.
# Parameters are frozen here, before any result is seen, and named in the
# output file, so an arm is one registered trial.
ARMS = {
    # P1.2: every A/A+ name at equal weight, capped at 10% of equity each.
    "ew_graded": lambda mask: point_in_time.graded_equal_weight_allocator(
        mask, min_grade=grading.ORDINAL[grading.A], cap=0.10, gross=1.0
    ),
}


@dataclass(frozen=True)
class Curve:
    """One strategy's daily returns on its executable sessions."""

    label: str
    dates: np.ndarray
    daily: np.ndarray  # NaN before the first fill


# Annualised return, worst drawdown and Sharpe of a daily series, or NaNs.
def window_stats(daily: np.ndarray) -> dict[str, float]:
    """Return {"cagr", "drawdown", "sharpe", "sessions"} for finite entries."""
    r = np.asarray(daily, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 2:
        return {"cagr": math.nan, "drawdown": math.nan, "sharpe": math.nan, "sessions": n}
    curve = np.cumprod(1.0 + r)
    cagr = float(curve[-1] ** (252.0 / n) - 1.0)
    peak = np.maximum.accumulate(curve)
    drawdown = float((curve / peak - 1.0).min())
    sd = float(r.std(ddof=1))
    sharpe = float(r.mean() / sd * math.sqrt(252.0)) if sd > 0 else math.nan
    return {"cagr": cagr, "drawdown": drawdown, "sharpe": sharpe, "sessions": n}


# The live execution policy the paper account runs, on the rule's own clock.
def _live_options(panel) -> dict:
    return dict(
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        event_exposure=event_risk.live_path(panel),
        event_lifecycle=True,
        **simulate.LIVE_POLICY,
    )


# Price the six lines from one offset at one cost.
def price_offset(
    report, restricted, mask: np.ndarray, store, since, cost_bps: float,
    arm=None,
) -> dict[str, Curve]:
    """Return {label: Curve} for every line on this offset.

    `arm`, when given, is an allocator factory `(mask) -> allocator` that
    replaces the rule on the two "rule" lines (today's book and point in
    time), so an allocation arm is scored on exactly the sessions, costs
    and controls the frozen rule is. The labels keep their keys; the
    payload's `arm` field says what they hold.
    """
    panel = report.panel
    live = _live_options(panel)
    out: dict[str, Curve] = {}
    everyone = np.ones_like(mask)
    everyone[:, panel.index(panel.benchmark)] = False
    if arm is None:
        rule_today = simulate.run(report, since=since, cost_bps=cost_bps, **live)
        rule_pit = simulate.run(restricted, since=since, cost_bps=cost_bps, **live)
    else:
        plain = dict(use_exits=False, rebalance=paper.REBALANCE_EVERY, cost_bps=cost_bps)
        rule_today = simulate.run(report, since=since, allocator=arm(everyone), **plain)
        rule_pit = simulate.run(restricted, since=since, allocator=arm(mask), **plain)
    out[RULE_TODAY] = Curve(RULE_TODAY, rule_today.dates, rule_today.returns)
    out[RULE_PIT] = Curve(RULE_PIT, rule_pit.dates, rule_pit.returns)
    for label, book_mask in ((EW_PIT, mask), (EW_TODAY, everyone)):
        sim = simulate.run(
            restricted if label == EW_PIT else report,
            since=since,
            cost_bps=cost_bps,
            use_exits=False,
            rebalance=paper.REBALANCE_EVERY,
            allocator=point_in_time.equal_weight_allocator(book_mask),
        )
        out[label] = Curve(label, sim.dates, sim.returns)
    for symbol in MARKET_INDICES:
        series = benchmarks.load_benchmark(
            store, symbol, rule_today.dates, cost_bps=cost_bps
        )
        daily = series.daily if series.available else np.full(len(rule_today.dates), np.nan)
        out[symbol] = Curve(symbol, rule_today.dates, daily)
    return out


# Align a curve's daily returns onto a reference calendar (NaN where absent).
def _on(dates: np.ndarray, curve: Curve) -> np.ndarray:
    ref = np.asarray(dates, dtype="datetime64[D]")
    own = np.asarray(curve.dates, dtype="datetime64[D]")
    out = np.full(len(ref), np.nan)
    pos = np.searchsorted(ref, own)
    ok = (pos < len(ref)) & (ref[np.minimum(pos, len(ref) - 1)] == own)
    out[pos[ok]] = np.asarray(curve.daily, dtype=float)[ok]
    return out


# Summarise every line over every window across the offsets at one cost.
def summarise(
    priced: list[dict[str, Curve]], cost_bps: float
) -> list[dict[str, object]]:
    """Return one row per (line, window) with medians, worsts and win counts."""
    rows: list[dict[str, object]] = []
    labels = list(priced[0])
    for name, (start, end) in WINDOWS.items():
        per_label: dict[str, list[dict[str, float]]] = {label: [] for label in labels}
        for offset in priced:
            base = offset[RULE_TODAY].dates
            keep = point_in_time.window(base, start, end)
            for label in labels:
                per_label[label].append(window_stats(_on(base, offset[label])[keep]))
        for label in labels:
            cagrs = np.array([s["cagr"] for s in per_label[label]])
            hurdle = np.array([s["cagr"] for s in per_label[EW_PIT]])
            index = np.array([s["cagr"] for s in per_label["QQQ"]])
            rows.append(
                {
                    "line": label,
                    "cost_bps": cost_bps,
                    "window": name,
                    "offsets": len(priced),
                    "median_cagr": _nanmedian(cagrs),
                    "worst_cagr": _nanmin(cagrs),
                    "best_cagr": _nanmax(cagrs),
                    "median_drawdown": _nanmedian(
                        np.array([s["drawdown"] for s in per_label[label]])
                    ),
                    "median_sharpe": _nanmedian(
                        np.array([s["sharpe"] for s in per_label[label]])
                    ),
                    "offsets_above_ew_pit": int(np.nansum(cagrs > hurdle)),
                    "offsets_above_qqq": int(np.nansum(cagrs > index)),
                    "sessions": int(np.nanmedian([s["sessions"] for s in per_label[label]])),
                }
            )
    return rows


# Median over finite entries, NaN when there are none.
def _nanmedian(x):
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# Minimum over finite entries, NaN when there are none.
def _nanmin(x):
    return float(np.nanmin(x)) if np.isfinite(x).any() else math.nan


# Maximum over finite entries, NaN when there are none.
def _nanmax(x):
    return float(np.nanmax(x)) if np.isfinite(x).any() else math.nan


# Paired evidence at the median offset: rule minus hurdle, rule minus QQQ.
def paired(priced: list[dict[str, Curve]], cost_bps: float) -> list[dict[str, object]]:
    """Return HAC t and PSR of the paired daily differences per window."""
    out: list[dict[str, object]] = []
    offset = priced[len(priced) // 2]
    base = offset[RULE_TODAY].dates
    for name, (start, end) in WINDOWS.items():
        keep = point_in_time.window(base, start, end)
        for line, against in ((RULE_PIT, EW_PIT), (RULE_PIT, "QQQ"), (RULE_TODAY, "QQQ"), (EW_PIT, "QQQ")):
            a = _on(base, offset[line])[keep]
            b = _on(base, offset[against])[keep]
            diff = a - b
            diff = diff[np.isfinite(diff)]
            mom = candidate_stats.moments(diff)
            out.append(
                {
                    "cost_bps": cost_bps,
                    "window": name,
                    "line": line,
                    "against": against,
                    "sessions": int(len(diff)),
                    "mean_daily_bp": float(diff.mean() * 1e4) if len(diff) else math.nan,
                    "hac_t": candidate_stats.hac_t(diff, 20) if len(diff) > 2 else math.nan,
                    "psr": candidate_stats.probabilistic_sharpe(
                        mom.sharpe, mom.length, mom.skew, mom.kurtosis
                    ),
                }
            )
    return out


# Run everything and assemble the payload; `report` is the desk's unrestricted report.
def build(
    report, store, offsets: int, costs: tuple[float, ...], history_path=None, arm=None
) -> dict:
    """Return the scorecard payload; `arm` as in `price_offset`."""
    panel = report.panel
    restricted, mask = (
        point_in_time.point_in_time(report, history_path)
        if history_path
        else point_in_time.point_in_time(report)
    )
    members = mask.sum(axis=1)
    payload: dict[str, object] = {
        "asof": str(panel.dates[-1]),
        "offsets": offsets,
        "costs_bps": list(costs),
        "windows": {k: [str(s) if s else None, str(e) if e else None] for k, (s, e) in WINDOWS.items()},
        "book": {
            "names_today": int(len(panel.tickers) - 1),
            "eligible_first_session": int(members[0]),
            "eligible_last_session": int(members[-1]),
            "eligible_median": float(np.median(members)),
        },
        "rows": [],
        "paired": [],
        "note": (
            "Lines priced on identical sessions from each of the first `offsets` "
            "sessions; medians and worsts are across offsets. The point-in-time "
            "book is the dated membership file; names with no bars in the store "
            "on a session are not held by any line."
        ),
    }
    for cost in costs:
        priced = [
            price_offset(report, restricted, mask, store, _since(panel, k), cost, arm)
            for k in range(offsets)
        ]
        payload["rows"].extend(summarise(priced, cost))
        payload["paired"].extend(paired(priced, cost))
    return payload


# The k-th panel session as a date, for `simulate.run(since=...)`.
def _since(panel, k: int):
    return panel.dates[k].astype("datetime64[D]").astype(object)


# Print the rows as a table people can read.
def render(payload: dict) -> str:
    """Return the scorecard as text."""
    lines = [f"point-in-time scorecard as of {payload['asof']}"]
    book = payload["book"]
    lines.append(
        f"book: {book['names_today']} names today; eligible per session "
        f"{book['eligible_first_session']} at the start, {book['eligible_last_session']} "
        f"at the end, median {book['eligible_median']:.0f}"
    )
    for cost in payload["costs_bps"]:
        for window in WINDOWS:
            lines.append(f"\n{cost:g} bp, {window}  (median / worst across {payload['offsets']} offsets)")
            lines.append(f"  {'line':<34}{'CAGR':>8}{'worst':>8}{'maxDD':>8}{'Sharpe':>8}{'>EW-PIT':>9}{'>QQQ':>7}")
            for row in payload["rows"]:
                if row["cost_bps"] != cost or row["window"] != window:
                    continue
                lines.append(
                    f"  {row['line']:<34}{_pct(row['median_cagr']):>8}{_pct(row['worst_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}{row['median_sharpe']:>8.2f}"
                    f"{row['offsets_above_ew_pit']:>9}{row['offsets_above_qqq']:>7}"
                )
            for pair in payload["paired"]:
                if pair["cost_bps"] != cost or pair["window"] != window:
                    continue
                lines.append(
                    f"  paired {pair['line']} minus {pair['against']}: "
                    f"{pair['mean_daily_bp']:+.1f} bp/day, HAC t {pair['hac_t']:.2f}, PSR {pair['psr']:.2f}"
                )
    return "\n".join(lines)


# A fraction as a percentage string, "n/a" for NaN.
def _pct(x: float) -> str:
    return "n/a" if x != x else f"{x * 100:.1f}%"


# Run the desk, score, write and print.
def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--offsets", type=int, default=20)
    parser.add_argument("--costs", type=float, nargs="+", default=[10.0, 25.0])
    parser.add_argument(
        "--signed-rotation",
        action="store_true",
        help="score the signed-rotation arm instead of the frozen rule; "
        "writes pit_scorecard_signed_rotation.json",
    )
    parser.add_argument(
        "--arm",
        choices=sorted(ARMS),
        help="score an allocation arm on the two rule lines instead of the "
        "frozen rule; writes pit_scorecard_<arm>.json",
    )
    args = parser.parse_args(argv)
    from backend.agents.trading.desk import desk
    from backend.market.store import MarketStore

    root = Path(args.root)
    store = MarketStore(root)
    report = desk.run(
        store, None, inputs=(desk.EXPECTATIONS_GAP,), signed_rotation=args.signed_rotation
    )
    arm = ARMS[args.arm] if args.arm else None
    payload = build(report, store, args.offsets, tuple(args.costs), arm=arm)
    tags = [t for t, on in (("signed_rotation", args.signed_rotation), (args.arm, args.arm)) if on]
    payload["arm"] = " + ".join(tags) if tags else "frozen rule"
    name = FILE if not tags else FILE.replace(".json", "_" + "_".join(tags) + ".json")
    target = root / "desk" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")
    print(render(payload))
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
