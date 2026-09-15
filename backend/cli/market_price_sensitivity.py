"""Price sensitivity of one name's grade and weight: a sensitivity analysis.

    python -m backend.cli.market_price_sensitivity --ticker ORCL ADBE
    python -m backend.cli.market_price_sensitivity --ticker ORCL --book-multipliers 1.5

Not a backtest. One fixed, dated information snapshot - the store's last
session, its filed fundamentals, every other analyst's stance and
conviction, the other names' scores, the realised volatilities and the
regime - and hypothetical prices. Assumptions, stated once:

- Only the named stock's close moves (or every close, in the book
  scenario). Fundamentals, filings, the other analysts, the volatilities
  the engine divides by, the regime exposure and the caps are held at
  the snapshot. The technical analyst would in reality respond to a
  three-session price level; here it does not, by design, so that the
  valuation path alone is traced.
- `immediate`: the price is at the scenario level on the last session
  only, so the value stance the rule carries is the one persistence left
  from the prior sessions. `persisted`: the price has sat at the level
  for the rule's three sessions, so a stance the rank implies is the
  stance the rule carries.
- The live rule's expectations-gap blend is not included; it halves the
  value rank's weight and adds a price-implied growth term.
- The proposed tilt is shown in its own column and never applied.

Per price the tool shows the valuation inputs, the value rank and the
stance it implies, the stance carried, the rank conviction, a bounded
magnitude input beside it (see `magnitude`), the votes and the grade,
value's share of the votes and of the score, whether the name would
clear the selection cut without value's contribution, the engine weight,
the multiplier, the final target and dollars, the binding constraint, and
the hard gates and bearish opinions separately.
"""

import argparse
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import grading, risk, value
from backend.agents.trading.desk.opinions import PERSISTENCE, STANCE_FRACTION
from backend.market.levels_pit import point_in_time_levels
from backend.market.store import MarketStore

DEFAULT_MULTIPLIERS = "0.50,0.70,0.85,1.00,1.15,1.30,1.50,2.00"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data/market")
    parser.add_argument("--ticker", nargs="+", default=["ORCL"])
    parser.add_argument("--multipliers", default=DEFAULT_MULTIPLIERS)
    parser.add_argument("--book-multipliers", default="")
    parser.add_argument("--equity", type=float, default=100_000.0)
    parser.add_argument("--tilt", type=float, default=0.5, help="shown, never applied")
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--report", type=Path, default=None)
    return parser


# The panel with closes scaled on the last `sessions` sessions, for one
# column or for every column.
def repriced(panel, multiplier: float, sessions: int, column: int | None):
    """Return the panel with the scenario's closes."""
    t = len(panel.dates)
    out = {}
    for field in ("open", "high", "low", "close", "adj_close"):
        arr = np.array(getattr(panel, field), dtype=float)
        if column is None:
            arr[t - sessions :, :] *= multiplier
        else:
            arr[t - sessions :, column] *= multiplier
        out[field] = arr
    return replace(panel, **out)


# The stance a rank implies on its own, before persistence.
def raw_stance(rank: float) -> int:
    """Return +1, 0 or -1 from a percentile rank."""
    if not np.isfinite(rank):
        return 0
    if rank >= 1.0 - STANCE_FRACTION:
        return 1
    if rank <= STANCE_FRACTION:
        return -1
    return 0


# A bounded input that keeps the size of the discount: the log distance of
# the name's price-to-sales from its side's median, scaled by the book's
# own typical distance that session and squashed to [-1, 1]. Halving the
# price adds log 2 to the distance for every name, however cheap it
# already ranks. It is a valuation magnitude, not an expected return;
# nothing here says how fast, or whether, a multiple reverts.
def magnitude(
    cheap_vs_side: np.ndarray, eligible: np.ndarray, scale: float | None = None
) -> np.ndarray:
    """Return (N,) tanh(cheap / scale), scale the eligible names' median |cheap|."""
    if scale is None:
        values = np.where(eligible, cheap_vs_side, np.nan)
        scale = float(np.nanmedian(np.abs(values)))
    scale = scale if np.isfinite(scale) and scale > 0 else 1.0
    with np.errstate(all="ignore"):
        return np.tanh(np.nan_to_num(cheap_vs_side, nan=0.0) / scale)


# Hard gates: what stops a name regardless of any analyst's opinion.
def hard_gates(report, levels, column: int) -> dict[str, bool]:
    """Return the eligibility gates for one name on the last session."""
    panel = report.panel
    t = len(panel.dates) - 1
    ticker = panel.tickers[column]
    lookback = risk.BOOK_CONFIG.volatility_lookback
    vol = risk.realised_volatility(panel, lookback)[t, column]
    close = panel.close[t, column]
    return {
        "in_book": ticker in report.sides,
        "price_known": bool(np.isfinite(close) and close > 0),
        "volatility_known": bool(np.isfinite(vol) and vol > 0),
        "valuation_data": bool(
            np.isfinite(levels["revenue"][t, column])
            and np.isfinite(levels["shares"][t, column])
        ),
        "regime_exposure_positive": float(report.regime.today().exposure) > 0,
    }


# The summed conviction of the analysts other than value, held fixed.
def _others(report, weights, fixed, t, column) -> float:
    total = 0.0
    for name in fixed:
        source = report.regime.rotation if name == "rotation" else report.opinions[name]
        total += weights[name] * float(np.nan_to_num(source.conviction()[t, column]))
    return total


# One row: the name at close x multiplier, held for `sessions` sessions.
def evaluate(report, levels, column, multiplier, sessions, equity, tilt, book=False):
    """Return the diagnostic row for one scenario."""
    panel = report.panel
    t = len(panel.dates) - 1
    ticker = panel.tickers[column]
    scenario = repriced(panel, multiplier, sessions, None if book else column)
    opinion = value.opine(scenario, levels, report.sides)
    rank = float(opinion.ranks()[t, column])
    carried = int(opinion.stances()[t, column])
    conviction = float(opinion.conviction()[t, column])
    evidence = opinion.evidence
    eligible = np.array([tk in report.sides for tk in panel.tickers])
    mags = magnitude(evidence["cheap_vs_side"][t], eligible)
    stances = {name: int(arr[t, column]) for name, arr in report.graded.stances.items()}
    fixed = {k: v for k, v in stances.items() if k != "value"}
    letter, votes = grading.grade_from_stances(
        {**stances, "value": carried}, grading.ANALYST_WEIGHTS
    )
    weights = grading.analyst_weights(grading.ANALYST_WEIGHTS, tuple(stances))
    others = _others(report, weights, fixed, t, column)
    score = others + weights["value"] * conviction
    scores_today = np.array(report.scores[t], dtype=float)
    scores_today[column] = score
    grades_today = np.array(report.graded.grades[t], dtype=int)
    grades_today[column] = grading.ORDINAL[letter]
    regime = report.regime.today()
    sized = risk.size(scores_today, grades_today, panel, regime)
    tilted = risk.size(
        scores_today,
        grades_today,
        panel,
        regime,
        tilt=tilt,
        conviction=np.array(opinion.conviction()[t], dtype=float),
    )
    mine = next((x for x in sized if x.position.ticker == ticker), None)
    mine_tilted = next((x for x in tilted if x.position.ticker == ticker), None)
    candidates = np.where(grades_today > 0, scores_today, np.nan)
    ranked = np.sort(candidates[np.isfinite(candidates)])[::-1]
    picked = len(sized)
    cut = float(ranked[picked - 1]) if picked and len(ranked) >= picked else np.nan
    engine, final, mult, binding = binding_of(
        mine, grades_today[column], letter, score, cut
    )
    price = float(scenario.close[t, column])
    return {
        "scenario": (
            "book"
            if book
            else ("persisted" if sessions >= PERSISTENCE else "immediate")
        ),
        "multiplier": multiplier,
        "price": price,
        "market_cap": float(evidence["market_cap"][t, column]),
        "price_sales": float(np.exp(evidence["price_sales"][t, column])),
        "price_earnings": float(np.exp(evidence["price_earnings"][t, column])),
        "cheap_vs_side": float(evidence["cheap_vs_side"][t, column]),
        "value_rank": rank,
        "stance_implied": raw_stance(rank),
        "stance_carried": carried,
        "value_conviction": conviction,
        "value_magnitude": float(mags[column]),
        "votes": float(votes),
        "value_vote_share": (weights["value"] * carried) / votes if votes else 0.0,
        "grade": letter,
        "score": score,
        "score_without_value": others,
        "value_score_share": (weights["value"] * conviction) / score if score else 0.0,
        "selection_cut": cut,
        "clears_cut_without_value": bool(np.isfinite(cut) and others >= cut),
        "engine_weight": engine,
        "grade_multiplier": mult,
        "exposure": float(regime.exposure),
        "target_weight": final,
        "target_weight_with_tilt": float(mine_tilted.final) if mine_tilted else 0.0,
        "dollars": final * equity,
        "shares": final * equity / price if price > 0 else 0.0,
        "binding": binding,
        "hard_gates": hard_gates(report, levels, column),
        "bearish_opinions": sorted(k for k, v in fixed.items() if v < 0),
        "fixed_stances": fixed,
    }


# The sized name's numbers and the constraint that decided its weight.
def binding_of(mine, ordinal: int, letter: str, score: float, cut: float):
    """Return (engine weight, final weight, multiplier, binding constraint)."""
    if mine is None:
        if ordinal == 0:
            binding = "grade C: not a candidate"
        else:
            binding = f"not selected: score {score:+.3f} below the cut {cut:+.3f}"
        return 0.0, 0.0, grading.SIZE_MULTIPLIER[letter], binding
    note = mine.position.note
    mult = float(mine.multiplier)
    if "cap" in note:
        binding = note
    elif mult < 1.0:
        binding = f"grade multiplier {mult:.2f}"
    else:
        binding = "inverse-volatility weight"
    if mine.exposure < 1.0:
        binding += f"; regime exposure {mine.exposure:.2f}"
    return float(mine.position.weight), float(mine.final), mult, binding


HEADS = (
    ("scen", 9),
    ("x", 5),
    ("price", 8),
    ("P/S", 6),
    ("cheap", 6),
    ("vrank", 6),
    ("impl", 4),
    ("held", 4),
    ("vconv", 6),
    ("vmag", 6),
    ("votes", 5),
    ("v%vote", 6),
    ("grade", 5),
    ("score", 7),
    ("noval", 7),
    ("cut", 7),
    ("v%scr", 6),
    ("clr-v", 5),
    ("engine", 7),
    ("mult", 5),
    ("target", 7),
    ("+tilt", 7),
    ("dollars", 8),
)


def _cells(r: dict) -> tuple[str, ...]:
    return (
        f"{r['scenario']:>9}",
        f"{r['multiplier']:5.2f}",
        f"{r['price']:8.2f}",
        f"{r['price_sales']:6.2f}",
        f"{r['cheap_vs_side']:+6.2f}",
        f"{r['value_rank']:6.2f}",
        f"{r['stance_implied']:+4d}",
        f"{r['stance_carried']:+4d}",
        f"{r['value_conviction']:+6.2f}",
        f"{r['value_magnitude']:+6.2f}",
        f"{r['votes']:5.1f}",
        f"{100 * r['value_vote_share']:5.0f}%",
        f"{r['grade']:>5}",
        f"{r['score']:+7.3f}",
        f"{r['score_without_value']:+7.3f}",
        f"{r['selection_cut']:+7.3f}",
        f"{100 * r['value_score_share']:5.0f}%",
        f"{'yes' if r['clears_cut_without_value'] else 'no':>5}",
        f"{r['engine_weight']:7.4f}",
        f"{r['grade_multiplier']:5.2f}",
        f"{r['target_weight']:7.4f}",
        f"{r['target_weight_with_tilt']:7.4f}",
        f"{r['dollars']:8,.0f}",
    )


def render(rows: list[dict], ticker: str, session: str) -> str:
    """Return one name's scenario tables as text."""
    first = rows[0]
    gates = ", ".join(
        f"{k}={'yes' if v else 'NO'}" for k, v in first["hard_gates"].items()
    )
    lines = [
        f"SENSITIVITY ANALYSIS, not a backtest: {ticker} on the {session} snapshot",
        f"  hard gates: {gates}",
        f"  bearish opinions held fixed: {first['bearish_opinions'] or 'none'}; "
        f"other stances {first['fixed_stances']}",
        " ".join(f"{h:>{w}}" for h, w in HEADS) + " binding",
    ]
    for r in rows:
        lines.append(" ".join(_cells(r)) + " " + r["binding"])
    return "\n".join(lines)


def render_book(rows_by_name: dict[str, list[dict]], session: str) -> str:
    """Return the whole-book repricing table as text."""
    lines = [
        f"WHOLE-BOOK SCENARIO, not a backtest: every close x multiplier on the "
        f"{session} snapshot, fundamentals unchanged, volatilities held",
        " ".join(
            f"{h:>{w}}"
            for h, w in (
                ("name", 6),
                ("x", 5),
                ("price", 8),
                ("P/S", 6),
                ("vrank", 6),
                ("vconv", 6),
                ("vmag", 6),
                ("grade", 5),
                ("target", 7),
                ("+tilt", 7),
                ("dollars", 8),
                ("shares", 8),
            )
        ),
    ]
    for name, rows in rows_by_name.items():
        for r in rows:
            cells = (
                f"{name:>6}",
                f"{r['multiplier']:5.2f}",
                f"{r['price']:8.2f}",
                f"{r['price_sales']:6.2f}",
                f"{r['value_rank']:6.2f}",
                f"{r['value_conviction']:+6.2f}",
                f"{r['value_magnitude']:+6.2f}",
                f"{r['grade']:>5}",
                f"{r['target_weight']:7.4f}",
                f"{r['target_weight_with_tilt']:7.4f}",
                f"{r['dollars']:8,.0f}",
                f"{r['shares']:8.2f}",
            )
            lines.append(" ".join(cells))
    return "\n".join(lines)


def main() -> None:
    """Run the analysis."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.data_dir))
    report = trading_desk.run(store, args.asof, inputs=())
    panel = report.panel
    levels = point_in_time_levels(store, panel, args.asof)
    multipliers = [float(m) for m in args.multipliers.split(",")]
    session = str(panel.dates[-1])
    out = {"session": session, "tilt_shown": args.tilt, "names": {}, "book": {}}
    for ticker in args.ticker:
        column = panel.index(ticker)
        rows = []
        for sessions in (1, PERSISTENCE):
            rows += [
                evaluate(report, levels, column, m, sessions, args.equity, args.tilt)
                for m in multipliers
            ]
        print(render(rows, ticker, session))
        print()
        out["names"][ticker] = rows
    if args.book_multipliers:
        book_rows = {}
        for ticker in args.ticker:
            column = panel.index(ticker)
            book_rows[ticker] = [
                evaluate(
                    report,
                    levels,
                    column,
                    float(m),
                    PERSISTENCE,
                    args.equity,
                    args.tilt,
                    True,
                )
                for m in args.book_multipliers.split(",")
            ]
        print(render_book(book_rows, session))
        out["book"] = book_rows
    if args.report:
        args.report.write_text(json.dumps(out, indent=1))
        print("report written:", args.report)


if __name__ == "__main__":
    main()
