"""The price-sensitive candidate against the rule, both on as-of fundamentals.

    python -m backend.cli.market_price_candidate --since 2018-06-01 --report OUT.json

One coherent candidate, evaluated inside the desk's own simulator with
the same costs, cadence, engine, caps and regime as the rule. Both the
baseline rule and the candidate read the corrected as-of fundamentals
(`fundamentals_asof`) for the valuation analyst; the rule on the frozen
fundamentals is printed once as the reference the production desk runs.

The candidate (`backend/market/attractiveness.py`): the ordering score
carries every analyst's signed conviction with the value leg the average
of the rank conviction and the relative valuation magnitude; candidacy
is the grade rule's admissions plus any name whose score reaches the
weakest admitted name's, nobody when the rule admits nobody; a name
admitted by the score alone is sized as a B; and the engine's weight is
tilted by the magnitude at one fixed tilt, gross restored, cap re-applied.

Ablations explain the candidate's behaviour; they are not a menu:
  magnitude-score    the score change only, candidacy and sizing as the rule
  +candidacy         the score change and the candidacy rule
  candidate          the whole design (score, candidacy, tilt)
  tilt-only          the tilt on the rule's own selection, the control
                     that separates price-sensitive selection from more
                     of what was already selected

Risk: the engine targets volatility on trailing returns, so every book is
matched ex ante by construction. The table also shows each series scaled
by the rule's trailing sixty-session volatility over its own, both lagged
one session, never by full-period realised volatility.
"""

import argparse
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import grading, risk, simulate, value
from backend.market import attractiveness as att
from backend.market import fundamentals_asof as fa
from backend.market.store import MarketStore

TILT = 0.5
MATCH_WINDOW = 60


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data/market")
    parser.add_argument("--since", default="2018-06-01")
    parser.add_argument("--report", type=Path, default=None)
    return parser


# The rule's report with the valuation analyst on as-of fundamentals.
def asof_report(store, plain):
    """Return (report, value opinion) with the value analyst on as-of levels."""
    panel = plain.panel
    versions = fa.load_versions(store, panel, None)
    levels = fa.levels(panel, versions)
    opinion = value.opine(panel, levels, plain.sides)
    opinions = {**plain.opinions, "value": opinion}
    return trading_desk.assemble(panel, plain.sides, opinions, plain.regime), opinion


# The window of the panel the engine sees at session t, as the simulator cuts it.
def _window(panel, t):
    return replace(
        panel,
        dates=panel.dates[: t + 1],
        open=panel.open[: t + 1],
        high=panel.high[: t + 1],
        low=panel.low[: t + 1],
        close=panel.close[: t + 1],
        adj_close=panel.adj_close[: t + 1],
        volume=panel.volume[: t + 1],
    )


# An allocator for the simulator from per-session scores, grades and tilt input.
def allocator_from(scores, grades, tilt, conviction):
    def allocate(report, panel, config, t):
        window = _window(panel, t)
        _positions, targets = risk.desk_targets(
            scores[t],
            grades[t],
            window,
            report.regime.states[t],
            config,
            None,
            tilt,
            conviction[t] if conviction is not None else None,
        )
        targets[window.index(window.benchmark)] = 0.0
        return targets

    return allocate


# Every variant's (scores, grades, tilt, conviction) from the as-of report.
def variants(report, opinion):
    """Return {name: (scores, grades, tilt, conviction)}."""
    panel = report.panel
    in_book = np.array([tk in report.sides for tk in panel.tickers])
    in_book[panel.index(panel.benchmark)] = False
    distance = opinion.evidence["cheap_vs_side"]
    magnitude = att.magnitude(
        distance, np.broadcast_to(in_book[None, :], distance.shape)
    )
    convictions = {
        name: (
            report.regime.rotation if name == "rotation" else report.opinions[name]
        ).conviction()
        for name in report.graded.stances
    }
    scores = att.candidate_scores(convictions, magnitude, grading.ANALYST_WEIGHTS)
    mask, _cut = att.admitted(scores, report.graded.grades)
    sized = att.sizing_grades(report.graded.grades, mask)
    return {
        "rule (as-of fundamentals)": (report.scores, report.graded.grades, 0.0, None),
        "magnitude-score": (scores, report.graded.grades, 0.0, None),
        "+candidacy": (scores, sized, 0.0, None),
        "candidate": (scores, sized, TILT, magnitude),
        "tilt-only": (report.scores, report.graded.grades, TILT, magnitude),
    }


# Daily returns scaled by the rule's trailing volatility over the series'
# own, both measured on sessions strictly before each day.
def lagged_matched(returns: np.ndarray, rule: np.ndarray, window: int = MATCH_WINDOW):
    """Return the series scaled to the rule's lagged trailing volatility."""
    out = np.array(returns, dtype=float)
    for t in range(len(out)):
        a = rule[max(0, t - window) : t]
        b = returns[max(0, t - window) : t]
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if len(a) >= 20 and len(b) >= 20 and b.std() > 0:
            out[t] = returns[t] * (a.std() / b.std())
    return out


def stats(returns: np.ndarray) -> dict:
    """Return the compounded return, volatility, Sharpe and worst drawdown."""
    r = returns[np.isfinite(returns)]
    if len(r) < 2:
        return {
            "cagr": np.nan,
            "volatility": np.nan,
            "sharpe": np.nan,
            "drawdown": np.nan,
        }
    curve = np.cumprod(1.0 + r)
    years = len(r) / 252.0
    return {
        "cagr": float(curve[-1] ** (1 / years) - 1),
        "volatility": float(r.std() * np.sqrt(252)),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
        "drawdown": float((curve / np.maximum.accumulate(curve) - 1).min()),
    }


def by_year(dates: np.ndarray, returns: np.ndarray) -> dict[str, float]:
    """Return {year: compounded return}."""
    out = {}
    years = np.array([str(d)[:4] for d in dates])
    for y in sorted(set(years)):
        r = returns[(years == y) & np.isfinite(returns)]
        out[y] = float(np.prod(1.0 + r) - 1.0) if len(r) else np.nan
    return out


def main() -> None:
    """Run the comparison."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.data_dir))
    since = date.fromisoformat(args.since)
    plain = trading_desk.run(store, None, inputs=())
    report, opinion = asof_report(store, plain)
    runs = {
        "rule (frozen fundamentals)": simulate.run(plain, since=since, use_exits=False)
    }
    for name, (scores, grades, tilt, conviction) in variants(report, opinion).items():
        runs[name] = simulate.run(
            report,
            since=since,
            use_exits=False,
            allocator=allocator_from(scores, grades, tilt, conviction),
        )
    rule = runs["rule (as-of fundamentals)"]
    rows = {}
    for name, res in runs.items():
        raw = stats(res.returns)
        matched = stats(lagged_matched(res.returns, rule.returns))
        s = res.stats()
        rows[name] = {
            **raw,
            "cagr_lag_matched": matched["cagr"],
            "volatility_lag_matched": matched["volatility"],
            "turnover": float(s["turnover"]),
            "max_weight": float(s["max_weight"]),
            "avg_invested": float(np.nanmean(res.invested)),
            "years": by_year(res.dates, res.returns),
        }
    print(
        f"{'book from ' + args.since:30} {'CAGR':>7} {'lag-matched':>11} {'vol':>6} "
        f"{'Sharpe':>6} {'worst':>7} {'turns':>6} {'top':>5} {'invested':>8}"
    )
    for name, r in rows.items():
        cells = (
            f"{100 * r['cagr']:+6.1f}%",
            f"{100 * r['cagr_lag_matched']:+10.1f}%",
            f"{100 * r['volatility']:5.1f}%",
            f"{r['sharpe']:6.2f}",
            f"{100 * r['drawdown']:+6.1f}%",
            f"{r['turnover']:5.1f}x",
            f"{100 * r['max_weight']:4.0f}%",
            f"{100 * r['avg_invested']:7.0f}%",
        )
        print(f"{name:30} " + " ".join(cells))
    years = sorted(rows["rule (as-of fundamentals)"]["years"])
    print(f"\n{'by year':30} " + " ".join(f"{y:>7}" for y in years))
    for name, r in rows.items():
        print(f"{name:30} " + " ".join(f"{100 * r['years'][y]:+6.1f}%" for y in years))
    if args.report:
        args.report.write_text(
            json.dumps({"since": args.since, "tilt": TILT, "rows": rows}, indent=1)
        )
        print("report written:", args.report)


if __name__ == "__main__":
    main()
