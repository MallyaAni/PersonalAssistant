"""The as-of fundamentals comparison block: what it reports, and when not.

What has to hold: a grade, score or book weight that differs between the
frozen and as-of runs is named; an unchanged name is not; the turnover a
switch would cost is half the summed absolute weight change; and a store
with no stored versions yields no block rather than an empty comparison.
"""

from datetime import date, timedelta

import numpy as np

from backend.agents.trading.desk import grading, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.agents.trading.desk.risk import Position, Sized
from backend.market import fundamentals_shadow as fs
from backend.market.panel import Panel
from backend.market.store import MarketStore
from backend.market.universe import AI_COMPUTE


def _report(grades_row, weights: dict[str, float]) -> DeskReport:
    t, n = 3, 2
    close = np.full((t, n + 1), 100.0)
    dates = np.array(
        [date(2026, 9, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    panel = Panel(
        dates=dates,
        tickers=("SNDK", "IREN", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={"SNDK": (AI_COMPUTE,), "IREN": (AI_COMPUTE,)},
        benchmark="SPY",
    )
    grades = np.array([grades_row] * t, dtype=int)
    graded = grading.Graded(grades, grades.astype(float), {})
    state = regime.RegimeState(
        -0.06, 0.19, 0.0, -0.52, -3.6, 4.8, "software", -0.2, -0.2, 0.5, 1.0, ()
    )
    view = regime.RegimeView([state] * t, Opinion("rotation", np.full((t, 3), np.nan)))
    book = [
        Sized(Position(tk, w, 1.0, 1.0, (AI_COMPUTE,), "w"), "A", 1.0, 1.0)
        for tk, w in weights.items()
    ]
    return DeskReport(
        panel,
        {"SNDK": "ai", "IREN": "ai"},
        {},
        view,
        graded,
        grades.astype(float),
        book,
    )


def test_comparison_names_only_what_differs():
    a_plus, b, c = grading.ORDINAL["A+"], grading.ORDINAL["B"], grading.ORDINAL["C"]
    frozen = _report([a_plus, c, 0], {"SNDK": 0.10})
    asof = _report([b, c, 0], {"SNDK": 0.06, "IREN": 0.04})
    out = fs.comparison(frozen, asof, covered=2)
    assert out["grade_changes"] == [{"ticker": "SNDK", "frozen": "A+", "asof": "B"}]
    assert [r["ticker"] for r in out["score_moves"]] == ["SNDK"]
    assert out["book_changes"] == [
        {"ticker": "IREN", "frozen": 0.0, "asof": 0.04},
        {"ticker": "SNDK", "frozen": 0.10, "asof": 0.06},
    ]
    assert abs(out["summary"]["turnover_if_switched"] - 0.04) < 1e-12
    assert out["summary"]["grades_changed"] == 1
    assert out["names_with_versions"] == 2
    assert "SPY" not in [r["ticker"] for r in out["score_moves"]]


def test_identical_runs_report_no_change():
    a_plus, c = grading.ORDINAL["A+"], grading.ORDINAL["C"]
    frozen = _report([a_plus, c, 0], {"SNDK": 0.10})
    out = fs.comparison(frozen, _report([a_plus, c, 0], {"SNDK": 0.10}), covered=2)
    assert out["grade_changes"] == []
    assert out["book_changes"] == []
    assert out["summary"]["turnover_if_switched"] == 0.0


def test_no_stored_versions_yields_no_block(tmp_path, capsys):
    frozen = _report([grading.ORDINAL["A+"], 0, 0], {"SNDK": 0.10})
    assert fs.block(MarketStore(tmp_path), frozen) is None
    assert "no stored filing versions" in capsys.readouterr().out
