"""Price sensitivity of one name's grade and weight: a sensitivity analysis.

    python -m backend.cli.market_price_sensitivity --ticker ORCL
    python -m backend.cli.market_price_sensitivity --ticker ORCL --tilt 0.5 --with-gap

One fixed, dated information snapshot - the store's last session, its
filed fundamentals, every other analyst's stance and conviction, the
other names' scores, the realised volatilities and the regime - and a
range of hypothetical prices for one name on that session. Only that
name's close on that one session moves. For each price the tool
recomputes the valuation analyst on the whole book (its multiples are
cross-sectional ranks, so the name's rank moves against the others),
takes the value stance and conviction that result, re-grades the name
with the other analysts held fixed, rebuilds the summed conviction
score, and runs the desk's own sizing with the original panel's
volatilities, so the risk assumptions do not move with the price.

Columns: the valuation inputs (market cap, price-to-sales, -earnings,
-book, cheapness against the side), the value score's rank, the stance
the rank implies today and the stance the rule actually carries after
its three-session persistence, the value conviction, the votes, the
grade, the summed conviction and where it sits against the book's
selection cut, the engine weight, the grade multiplier, the exposure,
the final target weight and dollars, the binding constraint, and why
the row differs from the one before it.

`--tilt` shows the proposed correction (`risk.tilt_by_conviction`,
off in production): the engine's weight tilted by the value conviction
within the book, gross unchanged, cap re-applied. `--with-gap` blends
the expectations gap into the value analyst as the live rule does, with
the gap itself held at the snapshot (its price-implied growth term is
not recomputed here; that understates the live sensitivity slightly).
"""

import argparse
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import grading, risk, value
from backend.agents.trading.desk.opinions import STANCE_FRACTION
from backend.market.levels_pit import point_in_time_levels
from backend.market.store import MarketStore

DEFAULT_MULTIPLIERS = "0.50,0.60,0.70,0.80,0.90,0.95,1.00,1.05,1.10,1.20,1.30,1.50,2.00"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data/market")
    parser.add_argument("--ticker", nargs="+", default=["ORCL"])
    parser.add_argument("--multipliers", default=DEFAULT_MULTIPLIERS)
    parser.add_argument("--equity", type=float, default=100_000.0)
    parser.add_argument("--tilt", type=float, default=0.0)
    parser.add_argument("--with-gap", action="store_true")
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--report", type=Path, default=None)
    return parser


# The panel with one name's close on the last session scaled.
def _repriced(panel, column: int, multiplier: float):
    t = len(panel.dates) - 1
    out = {}
    for field in ("open", "high", "low", "close", "adj_close"):
        arr = np.array(getattr(panel, field), dtype=float)
        arr[t, column] = arr[t, column] * multiplier
        out[field] = arr
    return replace(panel, **out)


# The stance a rank implies on its own, before persistence.
def _raw_stance(rank: float) -> int:
    if not np.isfinite(rank):
        return 0
    if rank >= 1.0 - STANCE_FRACTION:
        return 1
    if rank <= STANCE_FRACTION:
        return -1
    return 0


# One row of the analysis at one price.
def evaluate(
    report, levels, column: int, multiplier: float, equity: float, tilt: float, gap=None
) -> dict:
    """Return the diagnostic row for the name at close x `multiplier`."""
    panel = report.panel
    t = len(panel.dates) - 1
    ticker = panel.tickers[column]
    repriced = _repriced(panel, column, multiplier)
    opinion = value.opine(repriced, levels, report.sides)
    if gap is not None:
        from backend.market import challenger

        opinion = challenger.with_gap({**report.opinions, "value": opinion}, gap)[
            "value"
        ]
    rank = float(opinion.ranks()[t, column])
    raw = _raw_stance(rank)
    persisted = int(opinion.stances()[t, column])
    conviction = float(opinion.conviction()[t, column])
    evidence = opinion.evidence
    inputs = {
        "price": float(repriced.close[t, column]),
        "market_cap": float(evidence["market_cap"][t, column]),
        "price_sales": float(np.exp(evidence["price_sales"][t, column])),
        "price_earnings": float(np.exp(evidence["price_earnings"][t, column])),
        "price_book": float(np.exp(evidence["price_book"][t, column])),
        "cheap_vs_side": float(evidence["cheap_vs_side"][t, column]),
    }
    # The other analysts as the snapshot left them; only value moves.
    stances = {name: int(arr[t, column]) for name, arr in report.graded.stances.items()}
    fixed = {name: v for name, v in stances.items() if name != "value"}
    rows = {}
    for label, value_stance in (("persisted", persisted), ("if_immediate", raw)):
        s = dict(stances)
        s["value"] = value_stance
        letter, votes = grading.grade_from_stances(s, grading.ANALYST_WEIGHTS)
        rows[label] = {"grade": letter, "votes": float(votes)}
    # The summed conviction with the value leg replaced.
    weights = grading.analyst_weights(grading.ANALYST_WEIGHTS, tuple(stances))
    total = 0.0
    for name in stances:
        if name == "value":
            total += weights[name] * conviction
        elif name == "rotation":
            total += weights[name] * float(
                np.nan_to_num(report.regime.rotation.conviction()[t, column])
            )
        else:
            total += weights[name] * float(
                np.nan_to_num(report.opinions[name].conviction()[t, column])
            )
    scores_today = np.array(report.scores[t], dtype=float)
    scores_today[column] = total
    grades_today = np.array(report.graded.grades[t], dtype=int)
    grades_today[column] = grading.ORDINAL[rows["persisted"]["grade"]]
    convictions_today = np.array(opinion.conviction()[t], dtype=float)
    sized = risk.size(
        scores_today,
        grades_today,
        panel,
        report.regime.today(),
        tilt=tilt,
        conviction=convictions_today,
    )
    mine = next((s for s in sized if s.position.ticker == ticker), None)
    # Where the score sits against the book's selection cut.
    candidates = np.where(grades_today > 0, scores_today, np.nan)
    ranked = np.sort(candidates[np.isfinite(candidates)])[::-1]
    picked = len(sized)
    cut = (
        float(ranked[picked - 1]) if picked and len(ranked) >= picked else float("nan")
    )
    engine, final, note, multiplier_used, binding = _binding(
        mine, grades_today[column], rows["persisted"]["grade"], total, cut
    )
    return {
        "multiplier": multiplier,
        "fixed_stances": fixed,
        **inputs,
        "value_rank": rank,
        "value_stance_if_immediate": raw,
        "value_stance_persisted": persisted,
        "value_conviction": conviction,
        "votes": rows["persisted"]["votes"],
        "grade": rows["persisted"]["grade"],
        "grade_if_immediate": rows["if_immediate"]["grade"],
        "score": total,
        "selection_cut": cut,
        "engine_weight": engine,
        "grade_multiplier": multiplier_used,
        "exposure": float(report.regime.today().exposure),
        "target_weight": final,
        "dollars": final * equity,
        "shares": (final * equity / inputs["price"]) if inputs["price"] > 0 else 0.0,
        "binding": binding,
        "engine_note": note,
    }


# The sized name's numbers and the constraint that decided its weight.
def _binding(mine, ordinal: int, letter: str, score: float, cut: float):
    if mine is None:
        if ordinal == 0:
            binding = "grade C: not a candidate"
        else:
            binding = f"not selected: score {score:+.3f} below the cut {cut:+.3f}"
        return 0.0, 0.0, "", grading.SIZE_MULTIPLIER[letter], binding
    note = mine.position.note
    multiplier_used = float(mine.multiplier)
    if "cap" in note:
        binding = note
    elif multiplier_used < 1.0:
        binding = f"grade multiplier {multiplier_used:.2f}"
    else:
        binding = "inverse-volatility weight"
    if mine.exposure < 1.0:
        binding += f"; regime exposure {mine.exposure:.2f}"
    return (
        float(mine.position.weight),
        float(mine.final),
        note,
        multiplier_used,
        binding,
    )


# Why a row differs from the one before it.
def _reason(prev: dict | None, row: dict) -> str:
    if prev is None:
        return "baseline"
    parts = []
    if row["value_stance_if_immediate"] != prev["value_stance_if_immediate"]:
        parts.append(
            "value rank crossed a stance line "
            f"({prev['value_rank']:.2f} -> {row['value_rank']:.2f})"
        )
    if row["value_stance_persisted"] != prev["value_stance_persisted"]:
        parts.append("persisted value stance changed")
    if row["grade"] != prev["grade"]:
        parts.append(f"grade {prev['grade']} -> {row['grade']}")
    selected_now, selected_before = row["target_weight"] > 0, prev["target_weight"] > 0
    if selected_now != selected_before:
        parts.append("entered the book" if selected_now else "left the book")
    if abs(row["target_weight"] - prev["target_weight"]) > 1e-9 and not parts:
        parts.append("weight moved with the engine only (volatility or cap)")
    if not parts and abs(row["score"] - prev["score"]) > 1e-9:
        parts.append("score moved, nothing crossed a line: weight unchanged")
    return "; ".join(parts) or "nothing changed"


def render(
    rows: list[dict], ticker: str, session: str, tilt: float, with_gap: bool
) -> str:
    """Return the table as text."""
    head = (
        f"SENSITIVITY ANALYSIS, not a backtest: {ticker} on the {session} snapshot; "
        "only its close on that session moves; fundamentals, other analysts, other "
        "names, volatilities and regime fixed"
    )
    if with_gap:
        head += "; value blended with the gap held at the snapshot"
    if tilt:
        head += f"; proposed tilt {tilt}"
    columns = (
        ("x", 5),
        ("price", 8),
        ("P/S", 6),
        ("P/E", 7),
        ("P/B", 6),
        ("cheap", 6),
        ("vrank", 6),
        ("now", 3),
        ("held", 4),
        ("vconv", 6),
        ("votes", 5),
        ("grade", 5),
        ("score", 7),
        ("cut", 7),
        ("engine", 7),
        ("mult", 5),
        ("target", 7),
        ("dollars", 9),
    )
    lines = [head, "", " ".join(f"{name:>{w}}" for name, w in columns) + " binding"]
    prev = None
    for r in rows:
        cells = (
            f"{r['multiplier']:5.2f}",
            f"{r['price']:8.2f}",
            f"{r['price_sales']:6.2f}",
            f"{r['price_earnings']:7.1f}",
            f"{r['price_book']:6.2f}",
            f"{r['cheap_vs_side']:+6.2f}",
            f"{r['value_rank']:6.2f}",
            f"{r['value_stance_if_immediate']:+3d}",
            f"{r['value_stance_persisted']:+4d}",
            f"{r['value_conviction']:+6.2f}",
            f"{r['votes']:5.1f}",
            f"{r['grade']:>5}",
            f"{r['score']:+7.3f}",
            f"{r['selection_cut']:+7.3f}",
            f"{r['engine_weight']:7.4f}",
            f"{r['grade_multiplier']:5.2f}",
            f"{r['target_weight']:7.4f}",
            f"{r['dollars']:9,.0f}",
        )
        lines.append(" ".join(cells) + " " + r["binding"])
        lines.append(f"{'':>5} reason: {_reason(prev, r)}")
        prev = r
    return "\n".join(lines)


def main() -> None:
    """Run the analysis."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.data_dir))
    report = trading_desk.run(store, args.asof, inputs=())
    panel = report.panel
    levels = point_in_time_levels(store, panel, args.asof)
    gap = None
    if args.with_gap:
        from backend.market import challenger

        gap = challenger.expectations_gap(store, panel)
    multipliers = [float(m) for m in args.multipliers.split(",")]
    session = str(panel.dates[-1])
    out = {
        "session": session,
        "tilt": args.tilt,
        "with_gap": args.with_gap,
        "names": {},
    }
    for ticker in args.ticker:
        column = panel.index(ticker)
        rows = [
            evaluate(report, levels, column, m, args.equity, args.tilt, gap)
            for m in multipliers
        ]
        fixed = rows[0]["fixed_stances"]
        print(render(rows, ticker, session, args.tilt, args.with_gap))
        print(f"      other analysts held at: {fixed}")
        print()
        out["names"][ticker] = rows
    if args.report:
        args.report.write_text(json.dumps(out, indent=1))
        print("report written:", args.report)


if __name__ == "__main__":
    main()
