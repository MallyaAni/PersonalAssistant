"""The paper book and the backtest must size the same book.

They did not. The paper path tilted and capped the engine's weights and
then applied the grade and exposure multipliers; the simulator applied the
multipliers first and tilted and capped the result. Capping and scaling do
not commute, so with identical inputs in a tightening regime the two
disagreed on every name - 0.1125 against 0.1500 on the largest. A backtest
that sizes differently from the book it is meant to describe is not
evidence about that book.

There is one calculation now, `risk.desk_targets`, and this holds both
callers to it across the cases where they used to diverge: sparse books,
mixed grades, a tightening regime, overlapping themes, and a cut exposure.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import risk, simulate
from backend.agents.trading.desk.grading import Graded
from backend.agents.trading.desk.regime import RegimeState
from backend.market.panel import Panel
from backend.market.sizing import SizingConfig

SESSIONS = 400


def _panel(count: int, themes: dict[str, tuple[str, ...]]) -> Panel:
    rng = np.random.default_rng(11)
    vols = np.linspace(0.004, 0.05, count)
    steps = np.column_stack([rng.normal(0, v, SESSIONS) for v in vols])
    steps = np.concatenate([steps, np.zeros((SESSIONS, 1))], axis=1)
    close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    dates = np.array(
        [date(2020, 1, 1) + timedelta(days=i) for i in range(SESSIONS)],
        dtype="datetime64[D]",
    )
    return Panel(
        dates=dates,
        tickers=tuple(themes) + ("SPY",),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes=themes,
        benchmark="SPY",
    )


def _state(exposure: float, tightening: bool) -> RegimeState:
    return RegimeState(
        ai_participation=0.5,
        software_participation=0.5,
        participation_percentile=0.5,
        ai_vs_software_correlation=0.0,
        correlation_z=0.0,
        novelty_z=0.0,
        rotation_leader="ai",
        rotation_spread=0.0,
        ai_drawdown=0.0,
        selection_confidence=1.0,
        exposure=exposure,
        flags=(),
        tightening=tightening,
    )


def _report(panel: Panel, grade_row: np.ndarray, scores: np.ndarray, state):
    grades = np.tile(grade_row, (SESSIONS, 1))
    return SimpleNamespace(
        panel=panel,
        graded=Graded(grades=grades, votes=grades.astype(float), stances={}),
        scores=np.tile(scores, (SESSIONS, 1)),
        regime=SimpleNamespace(states=[state] * SESSIONS),
        sides={t: "ai" for t in panel.tickers[:-1]},
        book=[],
    )


# Sparse and full books, one theme and two, every grade, calm and
# tightening, full exposure and cut. These are the cases the two paths
# used to answer differently.
CASES = [
    ("two names, all A+", 2, [3, 3], False, 1.0, 1),
    ("three names, mixed grades", 3, [3, 1, 2], False, 1.0, 1),
    ("eight names, mixed grades", 8, [3, 1, 3, 1, 2, 1, 3, 1], False, 1.0, 1),
    ("eight names, tightening", 8, [3, 1, 3, 1, 2, 1, 3, 1], True, 1.0, 1),
    (
        "eight names, tightening, exposure cut",
        8,
        [3, 1, 3, 1, 2, 1, 3, 1],
        True,
        0.75,
        1,
    ),
    ("eight names, two themes", 8, [3, 2, 3, 2, 3, 2, 3, 2], False, 1.0, 2),
    ("eight names, two themes, tightening", 8, [3, 2, 3, 2, 3, 2, 3, 2], True, 0.75, 2),
    ("a book with only C grades", 5, [0, 0, 0, 0, 0], False, 1.0, 1),
    ("a name in three themes", 9, [3, 3, 2, 3, 1, 3, 2, 3, 1], False, 1.0, 3),
    (
        "a name in three themes, tightening",
        9,
        [3, 3, 2, 3, 1, 3, 2, 3, 1],
        True,
        0.75,
        3,
    ),
]


# Themes for `count` names. With more than one theme the first name
# belongs to all of them, because a name in two themes is the case where
# capping one theme changes another and the enforcement has to hold both.
def _themes(count: int, theme_count: int) -> dict[str, tuple[str, ...]]:
    every = tuple(f"theme-{k}" for k in range(theme_count))
    out: dict[str, tuple[str, ...]] = {}
    for i in range(count):
        out[f"N{i}"] = (
            every if i == 0 and theme_count > 1 else (every[i % theme_count],)
        )
    return out


# What each theme adds up to under a set of weights.
def _theme_totals(themes, tickers, weights) -> dict[str, float]:
    totals: dict[str, float] = {}
    for column, ticker in enumerate(tickers):
        for theme in themes.get(ticker, ()):
            totals[theme] = totals.get(theme, 0.0) + float(abs(weights[column]))
    return totals


@pytest.mark.parametrize(
    ("label", "count", "grade_list", "tightening", "exposure", "theme_count"),
    CASES,
    ids=[c[0] for c in CASES],
)
def test_the_paper_book_and_the_simulator_size_the_same_book(
    label, count, grade_list, tightening, exposure, theme_count
):
    themes = _themes(count, theme_count)
    panel = _panel(count, themes)
    grade_row = np.array([*grade_list, 0])
    scores = np.linspace(0.9, 0.2, count + 1)
    state = _state(exposure, tightening)
    config = SizingConfig(
        top_fraction=1.0, short_fraction=0.0, name_cap=0.15, theme_cap=0.6
    )

    paper = risk.size(scores, grade_row, panel, state, config)
    paper_weights = np.zeros(len(panel.tickers))
    for sized in paper:
        paper_weights[panel.index(sized.position.ticker)] = sized.weight

    report = _report(panel, grade_row, scores, state)
    sim = simulate._targets(report, panel, config, SESSIONS - 1)

    assert np.allclose(paper_weights, sim, atol=1e-12), (
        f"{label}: the paper book and the simulator disagree\n"
        f"  paper     {np.round(paper_weights, 4)}\n"
        f"  simulator {np.round(sim, 4)}"
    )
    # And whatever they agree on obeys every limit, not just the name one.
    # A test that checks the largest position and stops will pass a book
    # that is 46% into a theme capped at 40%, which is what the first
    # version of this file did.
    assert sim.max() <= config.name_cap + 1e-9
    for theme, total in _theme_totals(themes, panel.tickers, sim).items():
        assert total <= config.theme_cap + 1e-9, (
            f"{label}: {theme} at {total:.4f} over the {config.theme_cap} cap"
        )


# The cap is a postcondition of sizing, not an attempt at one.
#
# The engine clipped names over the cap and handed the excess to the
# others, a few rounds at most. With few names there is nowhere for the
# excess to go, so the rounds ran out and the book came back breaching: a
# two-name book held 42.5% of one name against a 15% cap, at 57.5% gross.
# It was never a choice of full investment over the cap - it was the cap
# not being enforced. Where the two cannot both hold, the gross gives way.
@pytest.mark.parametrize("count", [2, 3, 4, 6, 8, 12])
def test_no_book_is_ever_over_the_name_cap(count: int):
    themes = {f"N{i}": ("ai-compute",) for i in range(count)}
    panel = _panel(count, themes)
    grade_row = np.array([3] * count + [0])
    scores = np.linspace(0.9, 0.2, count + 1)
    config = SizingConfig(
        top_fraction=1.0, short_fraction=0.0, name_cap=0.15, theme_cap=1.0
    )
    for tightening in (False, True):
        book = risk.size(scores, grade_row, panel, _state(1.0, tightening), config)
        weights = [abs(s.weight) for s in book]
        assert weights, "the engine should hold something"
        assert max(weights) <= config.name_cap + 1e-9, (
            f"{count} names, {'tightening' if tightening else 'calm'}: "
            f"largest {max(weights):.4f} over the {config.name_cap} cap"
        )
        # A book too small to spend its gross under the cap holds cash
        # rather than breaching, so the gross may be below the target.
        assert sum(weights) <= count * config.name_cap + 1e-9


# Theme caps are a postcondition too, and the case that broke them is a
# name belonging to more than one theme.
#
# `apply_name_cap` guaranteed one constraint at a time, which is not enough
# when they interact: handing a capped name's excess to its neighbours
# lifts every theme those neighbours are in. With one name in two themes
# the book came back inside every name cap and 0.4376 into a theme capped
# at 0.40 - and the two sizing paths agreed exactly on that breaching book,
# so agreement between them proves nothing on its own.
@pytest.mark.parametrize("count", [4, 8, 12])
@pytest.mark.parametrize("theme_count", [2, 3])
@pytest.mark.parametrize("tightening", [False, True])
def test_no_theme_is_ever_over_its_cap(count, theme_count, tightening):
    themes = _themes(count, theme_count)
    panel = _panel(count, themes)
    grade_row = np.array([3] * count + [0])
    scores = np.linspace(0.9, 0.2, count + 1)
    config = SizingConfig(
        top_fraction=1.0, short_fraction=0.0, name_cap=0.15, theme_cap=0.40
    )
    book = risk.size(scores, grade_row, panel, _state(1.0, tightening), config)
    weights = np.zeros(len(panel.tickers))
    for sized in book:
        weights[panel.index(sized.position.ticker)] = sized.weight

    # The overlapping name is in every theme, so this is the case where
    # capping one theme moves another.
    assert len(themes["N0"]) == theme_count
    assert weights.max() <= config.name_cap + 1e-9
    for theme, total in _theme_totals(themes, panel.tickers, weights).items():
        assert total <= config.theme_cap + 1e-9, (
            f"{count} names in {theme_count} themes, "
            f"{'tightening' if tightening else 'calm'}: {theme} at {total:.4f} "
            f"over the {config.theme_cap} cap"
        )
