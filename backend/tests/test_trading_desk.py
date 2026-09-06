"""The trading desk: stances, grades, the regime's flags, sizes."""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import grading, regime, risk
from backend.agents.trading.desk.opinions import BEARISH, BULLISH, NEUTRAL, Opinion
from backend.market import edgar, language
from backend.market.panel import Panel
from backend.market.universe import (
    AI_COMPUTE,
    AI_SIDE,
    SOFTWARE,
    SOFTWARE_SIDE,
    UniverseMember,
    book_sides,
    build_universe,
)


# A panel of `n` names plus SPY over `t` sessions with the given returns.
def _panel(returns: np.ndarray, themes: dict[str, tuple[str, ...]]) -> Panel:
    t, n = returns.shape
    tickers = tuple(themes) + ("SPY",)
    full = np.concatenate([returns, np.zeros((t, 1))], axis=1)
    close = 100.0 * np.exp(np.cumsum(full, axis=0))
    dates = np.array(
        [date(2020, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    volume = np.full_like(close, 1e6)
    return Panel(
        dates=dates,
        tickers=tickers,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=volume,
        themes=themes,
        benchmark="SPY",
    )


# Stances come from the analyst's own ranks: top 30% bullish, bottom 30%
# bearish, unknown names neutral.
def test_stances_split_ranks_and_leave_unknown_neutral():
    scores = np.array([[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, np.nan]])
    stance = Opinion("x", scores).stances()[0]
    assert stance[0] == BEARISH
    assert stance[8] == BULLISH
    assert stance[4] == NEUTRAL
    assert stance[9] == NEUTRAL


# The grade rule: a bullish release plus agreement is A+; agreement without
# the release is A; one voice is B; nothing or a split is C.
def test_grade_rule():
    f = np.array([[1, 1, 1, 0, 0, 1, -1, -1]])
    t = np.array([[1, 0, 1, 1, 0, -1, -1, 1]])
    s = np.array([[1, 1, 0, 0, 1, 0, 1, 1]])
    graded = grading.grade_stances(f, t, s)
    letters = [graded.letter(0, c) for c in range(8)]
    # The last column: a bullish release and tape over bearish filings is
    # capped at B by the veto.
    assert letters == ["A+", "A+", "A", "B", "A", "C", "C", "B"]
    assert graded.as_scores()[0, 0] == 3.0


# The book universe: chips and software are in, a utility is out, and the
# side follows the themes.
def test_book_sides():
    universe = build_universe()
    sides = book_sides(universe)
    assert sides["SNDK"] == AI_SIDE
    assert sides["NVDA"] == AI_SIDE
    assert sides["CRWD"] == SOFTWARE_SIDE
    assert sides["MSFT"] == SOFTWARE_SIDE
    assert "DUK" not in sides
    assert "SPY" not in sides
    custom = (
        UniverseMember("AAA", "member", (AI_COMPUTE,), sub_industry="Semiconductors"),
        UniverseMember("BBB", "member", (SOFTWARE,), sub_industry="Systems Software"),
        UniverseMember("CCC", "member", (), sub_industry="Banks"),
    )
    assert book_sides(custom) == {"AAA": AI_SIDE, "BBB": SOFTWARE_SIDE}


# The novelty detector flags a window whose correlation structure flipped.
def test_novelty_flags_a_flipped_structure():
    rng = np.random.default_rng(0)
    t = 60 * 12
    common = rng.normal(size=t)
    a = common + 0.5 * rng.normal(size=t)
    b = common + 0.5 * rng.normal(size=t)
    c = rng.normal(size=t)
    # The last window inverts a against b.
    b[-60:] = -common[-60:] + 0.5 * rng.normal(size=60)
    baskets = np.stack([a, b, c], axis=1)
    z = regime.novelty(baskets)
    assert np.isnan(z[59])
    assert z[t - 61] < 1.5
    assert z[t - 1] > 2.5


# The regime analyst reads participation from volume: dead volume lowers
# selection confidence, a volume surge lowers exposure, and the rotation
# opinion is withheld while confidence is low.
def test_regime_participation_gates():
    rng = np.random.default_rng(1)
    t, n = 900, 6
    themes = {f"AI{i}": (AI_COMPUTE,) for i in range(3)}
    themes.update({f"SW{i}": (SOFTWARE,) for i in range(3)})
    panel = _panel(rng.normal(scale=0.01, size=(t, n)), themes)
    sides = {k: (AI_SIDE if k.startswith("AI") else SOFTWARE_SIDE) for k in themes}
    volume = panel.volume.copy()
    volume[-20:, :3] *= 0.2  # AI volume dies
    dead = regime.opine(replace(panel, volume=volume), sides)
    assert dead.today().selection_confidence == regime.LOW_CONFIDENCE
    assert "participation below its two-year median" in dead.today().flags
    assert np.isnan(dead.rotation.scores[-1]).all()
    volume = panel.volume.copy()
    volume[-20:, :3] *= 5.0  # AI volume surges
    hype = regime.opine(replace(panel, volume=volume), sides)
    assert hype.today().exposure == regime.HYPE_EXPOSURE
    assert hype.today().selection_confidence == 1.0
    assert np.isfinite(hype.rotation.scores[-1, :-1]).all()
    assert hype.today().rotation_leader in ("ai", "software")


# Sizes: a C name never takes a slot, and the grade and exposure scale the
# engine's weight.
def test_risk_sizes_by_grade_and_exposure():
    rng = np.random.default_rng(2)
    t, n = 200, 8
    themes = {f"N{i}": (AI_COMPUTE,) for i in range(n)}
    panel = _panel(rng.normal(scale=0.02, size=(t, n)), themes)
    scores = np.linspace(0, 1, n + 1)
    grades = np.array([3, 3, 2, 1, 0, 0, 0, 0, 0])
    state = regime.RegimeState(
        0, 0, 0.9, 0, 0, 0, "ai", 0.1, 0, 1.0, regime.HYPE_EXPOSURE, ()
    )
    config = risk.SizingConfig(top_fraction=0.5, short_fraction=0.0, name_cap=0.5)
    sized = risk.size(scores, grades, panel, state, config)
    tickers = {s.position.ticker for s in sized}
    assert tickers <= {"N0", "N1", "N2", "N3"}
    for s in sized:
        assert s.exposure == regime.HYPE_EXPOSURE
        assert s.weight == pytest.approx(
            s.position.weight * grading.SIZE_MULTIPLIER[s.grade] * regime.HYPE_EXPOSURE
        )
    assert risk.gross(sized) < sum(abs(s.position.weight) for s in sized)
    # With half the names graded C, the top half of the candidates is still
    # half of the whole universe: four names, not two.
    assert len(sized) == 4


# The technical analyst reads location: in a rising theme the name at the
# top of its range with both trends up ranks first; in a falling theme
# the most stretched name ranks lower than in a rising one.
def test_technical_analyst_switches_on_theme_trend():
    from backend.agents.trading.desk import technical as analyst

    t, n = 400, 4
    themes = {f"N{i}": (AI_COMPUTE,) for i in range(n)}
    returns = np.zeros((t, n))
    # N0 climbs steadily to a fresh high and sits well above its support.
    returns[:, 0] = 0.004
    returns[-10:, 0] = 0.03
    # N1 is flat; N2 and N3 drift down.
    returns[:, 2] = -0.001
    returns[:, 3] = -0.002
    panel = _panel(returns, themes)
    rising = analyst.opine(panel, np.full(t, 0.1)).scores[-1, :n]
    falling = analyst.opine(panel, np.full(t, -0.1)).scores[-1, :n]
    assert np.nanargmax(rising) == 0
    assert falling[0] < rising[0]
    assert np.allclose(analyst.opine(panel).scores[-1, :n], falling, equal_nan=True)


# The name backtest holds a name only while it is graded, pays a cost on
# each switch, and books buy-and-hold and the benchmark over the same span.
def test_name_backtest_holds_only_while_graded():
    from dataclasses import replace as dc_replace

    from backend.agents.trading.desk import desk as trading_desk
    from backend.agents.trading.desk.opinions import Opinion

    t, n = 30, 2
    themes = {"N0": (AI_COMPUTE,), "N1": (AI_COMPUTE,)}
    returns = np.zeros((t, n))
    returns[:, 0] = 0.01  # N0 gains 1% a session
    panel = _panel(returns, themes)
    grades = np.zeros((t, n + 1), dtype=int)
    grades[10:20, 0] = grading.ORDINAL["A"]  # graded A for ten sessions
    graded = grading.Graded(grades, grades.astype(float), {})
    state = regime.RegimeState(0, 0, 0.9, 0, 0, 0, "ai", 0.1, 0, 1.0, 1.0, ())
    view = regime.RegimeView(
        [state] * t, Opinion("rotation", np.full((t, n + 1), np.nan))
    )
    report = trading_desk.DeskReport(
        panel, {"N0": "ai", "N1": "ai"}, {}, view, graded, grades.astype(float), []
    )
    bt = trading_desk.name_backtest(report, "N0", "A", cost_bps=0.0)
    assert bt.sessions_in == 10
    assert bt.switches == 2
    assert bt.rule_return == pytest.approx(0.75 * 0.10)
    assert bt.hold_return == pytest.approx(0.01 * (t - 1))
    rows = trading_desk.history(report, "N0", 5)
    assert rows[10].grade == "A"
    assert rows[10].forward == pytest.approx(0.05)
    assert dc_replace(rows[0], grade="C").grade == "C"


# A stance that flickers does not change until it has held three sessions.
def test_stances_persist():
    from backend.agents.trading.desk.opinions import persist

    raw = np.array([[1], [0], [1], [0], [0], [0], [1], [1], [1]])
    held = persist(raw, 3)[:, 0].tolist()
    assert held == [1, 1, 1, 1, 1, 0, 0, 0, 1]


# A young filer with sequential growth and a margin, but no year-over-year
# figure yet, still gets a fundamental view.
def test_fundamental_view_from_partial_legs():
    from backend.agents.trading.desk import fundamental

    names = edgar.FEATURE_NAMES
    extra = np.zeros((1, 3, len(names)))
    extra[0, :, names.index("has_fundamentals")] = 1
    extra[0, :, names.index("revenue_qoq")] = [0.3, 0.1, -0.2]
    extra[0, :, names.index("gross_margin")] = [0.6, 0.4, 0.2]
    extra[0, :, names.index("revenue_yoy")] = np.nan
    extra[0, :, names.index("revenue_acceleration")] = np.nan
    scores = fundamental.opine(extra).scores[0]
    assert np.isfinite(scores).all()
    assert scores[0] > scores[1] > scores[2]


# The analysts have no view where their layer has no data.
def test_analysts_withhold_without_data():
    from backend.agents.trading.desk import fundamental, sentiment

    extra = np.zeros((3, 2, len(edgar.FEATURE_NAMES)))
    assert np.isnan(fundamental.opine(extra).scores).all()
    tone = np.zeros((3, 2, len(language.FEATURE_NAMES)))
    assert np.isnan(sentiment.opine(tone).scores).all()
