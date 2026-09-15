"""The desk on as-of fundamentals, recorded beside the desk on the frozen path.

Stage one of correcting the desk's fundamental data. The production value
analyst reads `levels_pit`: one facts snapshot per session, the tag
chosen for the whole history, restatements dropped. `fundamentals_asof`
keeps every filed version and gives each session the version that was
actually available, which on the research ladder moved the valuation
rule's backtest materially. Before the live analyst switches inputs the
difference has to be seen on real nights, so every record now carries the
plain rule run twice on the same session, frozen and as-of, and the
names whose grade, score or book weight differ. Nothing here sizes a
position or places an order; the block is evidence for the switch.

Stage two, when the differences are reviewed: the value analyst reads
`fundamentals_asof.levels` and this block becomes the frozen path's
shadow instead.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import value

KEY = "fundamentals_asof"


# The plain rule on the same session with the value analyst reading the
# stored filing versions; None when the store holds no versions yet.
def asof_report(store, report, asof: date | None = None):
    """Return (as-of DeskReport, names with versions) or (None, 0)."""
    from backend.market import fundamentals_asof as fa

    base = getattr(report, "alternate", None) or report
    panel = base.panel
    versions = fa.load_versions(store, panel, asof)
    covered = [t for t in versions if t != panel.benchmark]
    if not covered:
        return None, 0
    levels = fa.levels(panel, versions)
    opinions = {**base.opinions, value.NAME: value.opine(panel, levels, base.sides)}
    return trading_desk.assemble(panel, base.sides, opinions, base.regime), len(covered)


# What changed between the two runs on the last session, as plain data.
def comparison(frozen, asof, covered: int) -> dict:
    """Return the record block: grade, score and book differences."""
    panel = frozen.panel
    last = len(panel.dates) - 1
    grade_changes = []
    score_moves = []
    for column, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        before = frozen.graded.letter(last, column)
        after = asof.graded.letter(last, column)
        if before != after:
            grade_changes.append({"ticker": ticker, "frozen": before, "asof": after})
        a, b = float(frozen.scores[last, column]), float(asof.scores[last, column])
        if np.isfinite(a) and np.isfinite(b) and abs(b - a) > 1e-9:
            score_moves.append({"ticker": ticker, "frozen": a, "asof": b})
    score_moves.sort(key=lambda r: -abs(r["asof"] - r["frozen"]))
    weights_before = {s.position.ticker: float(s.weight) for s in frozen.book}
    weights_after = {s.position.ticker: float(s.weight) for s in asof.book}
    book_changes = [
        {
            "ticker": t,
            "frozen": weights_before.get(t, 0.0),
            "asof": weights_after.get(t, 0.0),
        }
        for t in sorted(set(weights_before) | set(weights_after))
        if abs(weights_before.get(t, 0.0) - weights_after.get(t, 0.0)) > 1e-9
    ]
    return {
        "session": str(panel.dates[last]),
        "base": "plain-value",
        "names_with_versions": int(covered),
        "names": len(panel.tickers) - 1,
        "grade_changes": grade_changes,
        "score_moves": score_moves[:10],
        "book_changes": book_changes,
        "summary": {
            "grades_changed": len(grade_changes),
            "book_names_changed": len(book_changes),
            "turnover_if_switched": float(
                sum(abs(r["asof"] - r["frozen"]) for r in book_changes) / 2
            ),
        },
    }


# The block for tonight's record, or None with the reason printed.
def block(store, report, asof: date | None = None) -> dict | None:
    """Return the comparison block for the record, or None."""
    shadow, covered = asof_report(store, report, asof)
    if shadow is None:
        print("\nas-of fundamentals: no stored filing versions; nothing compared")
        return None
    frozen = getattr(report, "alternate", None) or report
    out = comparison(frozen, shadow, covered)
    s = out["summary"]
    print(
        f"\nas-of fundamentals ({covered} of {out['names']} names with versions): "
        f"{s['grades_changed']} grades differ, {s['book_names_changed']} book "
        f"weights differ, {100 * s['turnover_if_switched']:.1f}% turnover if switched"
    )
    for row in out["grade_changes"]:
        print(f"  {row['ticker']:6} {row['frozen']:2} -> {row['asof']:2}")
    return out
