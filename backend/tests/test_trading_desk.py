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
    # A regulated utility stays out by decision: the book is AI and software,
    # and restoring all nineteen utilities carrying the power-cooling theme
    # measured better (38.45% a year at Sharpe 1.247 against 34.12% at 1.178)
    # without being the same book. The merchant and nuclear generators that
    # sell into datacenters are in, and they are the distinction.
    assert "DUK" not in sides
    assert sides["CEG"] == AI_SIDE
    # Corning was absent only because no theme was ever assigned to it, while
    # COHR - same sub-industry, same datacenter optical business - was in.
    assert sides["GLW"] == AI_SIDE
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
    # Sized by the grade's own multiplier rather than a literal: the ladder was
    # flattened once and this assertion was the only thing that noticed.
    assert bt.rule_return == pytest.approx(grading.SIZE_MULTIPLIER["A"] * 0.10)
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


# The tightening flag comes from the ten-year yield's own trend and reads
# only the past; a missing series means no view rather than a guess.
def test_tightening_from_yields():
    yields = np.concatenate([np.full(60, 4.0), np.full(20, 4.5), np.full(20, 4.05)])
    flags = regime.tightening_from(yields)
    assert not flags[:60].any()  # no history yet to compare against
    assert flags[60]  # 4.5 against 4.0 sixty sessions back is a 12.5% rise
    assert not flags[-1]  # 4.05 against 4.5 is not a rise
    assert regime.tightening_from(None) is None


# While money is tightening the regime carries less of the book and says so,
# and the risk manager shifts the same names toward the steadier ones.
def test_tightening_cuts_exposure_and_steepens_the_book():
    rng = np.random.default_rng(3)
    t, n = 900, 6
    themes = {f"AI{i}": (AI_COMPUTE,) for i in range(3)}
    themes.update({f"SW{i}": (SOFTWARE,) for i in range(3)})
    panel = _panel(rng.normal(scale=0.01, size=(t, n)), themes)
    sides = {k: (AI_SIDE if k.startswith("AI") else SOFTWARE_SIDE) for k in themes}
    calm = regime.opine(panel, sides)
    tight = regime.opine(panel, sides, np.ones(t, dtype=bool))
    assert not calm.today().tightening
    assert tight.today().tightening
    assert tight.today().exposure <= regime.TIGHTENING_EXPOSURE
    assert "the ten-year yield is rising sharply" in tight.today().flags

    # The same graded names, sized calm and sized tight: the steady name
    # takes more of the book while money tightens, and the gross is the same.
    wild = np.concatenate(
        [rng.normal(scale=0.05, size=(t, 1)), rng.normal(scale=0.005, size=(t, 1))],
        axis=1,
    )
    two = _panel(wild, {"WILD": (AI_COMPUTE,), "STEADY": (AI_COMPUTE,)})
    # Every column carries a score so the engine's top fraction is not
    # rescaled away; the benchmark is excluded by its grade.
    scores = np.array([0.9, 0.8, 0.5])
    grades = np.array([3, 3, 0])
    config = risk.SizingConfig(top_fraction=1.0, short_fraction=0.0, name_cap=1.0)
    calm_book = risk.size(scores, grades, two, calm.today(), config)
    tight_book = risk.size(scores, grades, two, tight.today(), config)
    # The final weight, not the engine's. The tilt now happens after the
    # grade and exposure multipliers - the same order the backtest uses -
    # so `position.weight` is the engine's untilted number and says
    # nothing about what the book holds.
    calm_weights = {s.position.ticker: s.weight for s in calm_book}
    tight_weights = {s.position.ticker: s.weight for s in tight_book}
    # "Takes more of the book" is a share, not an absolute weight: the
    # same regime that tilts toward the steady name also cuts exposure, so
    # every position shrinks. The tilt moves how the remaining gross is
    # split, and that is what this asserts.
    calm_gross = sum(calm_weights.values())
    tight_gross = sum(tight_weights.values())
    assert (
        tight_weights["STEADY"] / tight_gross
        > calm_weights["STEADY"] / calm_gross
    )

    # And the tilt does not breach the name cap on its way there.
    #
    # It renormalises to the gross it started with, which moves weight onto
    # the calmest names, and `size_today` had already capped those - so
    # without a second pass a position could end up over the cap. A review
    # found 18.75% against a 15% cap on the paper book after the same
    # defect had been fixed in the simulator alone; both paths call one
    # `apply_name_cap` now, and this is the paper one.
    #
    # The book needs enough names for the cap to be satisfiable at all. Two
    # names cannot hold 15% each and stay fully invested, and the engine
    # chooses full investment there; eight names can.
    wide = np.concatenate(
        [rng.normal(scale=v, size=(t, 1)) for v in np.linspace(0.004, 0.06, 8)],
        axis=1,
    )
    wide_panel = _panel(wide, {f"N{i}": (AI_COMPUTE,) for i in range(8)})
    wide_scores = np.linspace(0.9, 0.2, 9)
    wide_grades = np.array([3] * 8 + [0])
    capped = risk.SizingConfig(
        top_fraction=1.0, short_fraction=0.0, name_cap=0.15, theme_cap=1.0
    )
    for state in (calm.today(), tight.today()):
        book = risk.size(wide_scores, wide_grades, wide_panel, state, capped)
        assert book, "the engine should hold something"
        for sized in book:
            assert abs(sized.position.weight) <= capped.name_cap + 1e-9, (
                f"{sized.position.ticker} sized at {sized.position.weight:.4f}, "
                f"over the {capped.name_cap} cap while "
                f"{'tightening' if state.tightening else 'calm'}"
            )
    # The tilt itself holds the gross: it redistributes, and the exposure
    # cut is what changes the total.
    assert tight_gross == pytest.approx(calm_gross * tight.today().exposure)
    assert any("steadier" in s.position.note for s in tight_book)


# ---- the desk's fundamental data source ----

# A synthetic two-name book panel ending on the decision date, so the version
# availability stored in the store lines up with the sessions the desk sees.
def _desk_panel() -> Panel:
    t = 372  # 2025-02-10 .. 2026-02-16
    n = 2
    close = np.full((t, n + 1), 100.0)
    dates = np.array(
        [date(2025, 2, 10) + timedelta(days=i) for i in range(t)],
        dtype="datetime64[D]",
    )
    themes = {"N0": (AI_COMPUTE,), "N1": (AI_COMPUTE,)}
    return Panel(
        dates=dates,
        tickers=("N0", "N1", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes=themes,
        benchmark="SPY",
    )


# A store holding corrected version frames: N0 has revenue but never a gross
# profit, N1 files a gross profit too. All versions are public by the
# decision session.
def _write_corrected_versions(store, asof) -> None:
    from backend.market import fundamentals_asof as fa
    from backend.tests.test_fundamental_features import EIGHT, payload, row

    n0 = fa.parse_versions(payload(Revenues=EIGHT))
    n1 = fa.parse_versions(
        payload(
            Revenues=EIGHT,
            GrossProfit=[
                row(r["start"], r["end"], r["val"], r["filed"], r["accn"] + "g")
                for r in EIGHT
            ],
        )
    )
    store.write_frame(fa.KIND, asof, "N0", fa.frame(n0), {"source": "test"})
    store.write_frame(fa.KIND, asof, "N1", fa.frame(n1), {"source": "test"})


# The desk's torch-bound loaders do not exist in the gate container; a stub
# keeps the real `desk.run` path running while the corrected fundamental
# analyst, the version adapter and the store are all real. The tone loader
# returns the empty-book tone array (no view, never a crash); the legacy
# EDGAR loader refuses, so a corrected run that reached it would fail loudly.
@pytest.fixture
def torch_loaders(monkeypatch):
    import sys
    from types import SimpleNamespace

    from backend.market import language

    # Supply the real empty tone representation without importing torch.
    def load_tone_features(store, panel, asof=None):
        return language.tone_features(panel, {})

    # Fail if the corrected path unexpectedly reads the legacy feature block.
    def load_edgar_features(store, panel, asof=None):
        raise AssertionError("the legacy EDGAR loader must not run in corrected mode")

    stub = SimpleNamespace(
        load_edgar_features=load_edgar_features, load_tone_features=load_tone_features
    )
    monkeypatch.setitem(sys.modules, "backend.market.model", stub)
    return stub


# Run the real desk on the synthetic panel; the panel replaces the book's own
# (which needs a full store), everything else in `run` is the real path.
def _run_desk(store, monkeypatch, asof=date(2026, 2, 16), **kwargs):
    from backend.agents.trading.desk import desk as trading_desk

    panel = _desk_panel()
    sides = {"N0": AI_SIDE, "N1": SOFTWARE_SIDE}
    monkeypatch.setattr(
        trading_desk, "book_panel", lambda store, asof=None: (panel, sides)
    )
    return trading_desk.run(store, asof, inputs=(), **kwargs)


# The desk defaults to the corrected fundamental source: a missing ratio stays
# missing in the evidence and never reaches a score as a fabricated zero.
def test_desk_run_defaults_to_corrected_fundamentals(
    tmp_path, monkeypatch, torch_loaders
):
    from backend.agents.trading.desk import fundamental
    from backend.market.store import MarketStore

    asof = date(2026, 2, 16)
    store = MarketStore(tmp_path)
    _write_corrected_versions(store, asof)
    report = _run_desk(store, monkeypatch, asof)
    assert report.fundamentals_source == fundamental.CORRECTED_SOURCE
    opinion = report.opinions[fundamental.NAME]
    assert opinion.meta["source"] == fundamental.CORRECTED_SOURCE
    # N0's gross margin was never filed: missing in the evidence, and the
    # real growth legs still earn a finite score.
    assert np.isnan(opinion.evidence["gross_margin"][-1, 0])
    assert np.isfinite(opinion.scores[-1, 0])
    # N1 filed a gross profit: its margin is a real number.
    assert np.isfinite(opinion.evidence["gross_margin"][-1, 1])


# The explicit legacy option reads the frozen EDGAR block and is labelled as
# such, so a side-by-side comparison is honest about which data it used.
def test_desk_run_legacy_option_reads_the_frozen_block(
    tmp_path, monkeypatch, torch_loaders
):
    from datetime import UTC, datetime

    from backend.agents.trading.desk import fundamental
    from backend.market import edgar
    from backend.market.edgar import CompanyRecord, QuarterFact
    from backend.market.store import MarketStore
    from backend.tests.test_fundamental_features import EIGHT

    asof = date(2026, 2, 16)
    store = MarketStore(tmp_path)
    _write_corrected_versions(store, asof)
    facts = tuple(
        QuarterFact(
            "revenue",
            date.fromisoformat(r["start"]),
            date.fromisoformat(r["end"]),
            r["val"],
            date.fromisoformat(r["filed"]),
        )
        for r in EIGHT
    )
    record = CompanyRecord("N0", 0, (), facts, datetime(2026, 2, 16, tzinfo=UTC))
    legacy = edgar.edgar_features(_desk_panel(), {"N0": record})
    torch_loaders.load_edgar_features = lambda store, panel, asof=None: legacy
    report = _run_desk(store, monkeypatch, asof, fundamentals="legacy")
    assert report.fundamentals_source == fundamental.LEGACY_SOURCE
    opinion = report.opinions[fundamental.NAME]
    # The frozen block's zero-fill: the never-filed margin reads as a zero.
    assert opinion.evidence["gross_margin"][-1, 0] == 0.0


# A mode string that names neither source is refused before assembly, so a
# misspelt mode can never label corrected data as legacy.
def test_desk_run_refuses_unknown_fundamental_modes(
    tmp_path, monkeypatch, torch_loaders
):
    from backend.agents.trading.desk import desk as trading_desk
    from backend.market.store import MarketStore

    with pytest.raises(ValueError, match="unknown fundamental data source"):
        trading_desk.run(
            MarketStore(tmp_path), date(2026, 2, 17), inputs=(), fundamentals="bogus"
        )


# A stored frame whose version list is empty is not a filing: the desk refuses
# to assemble rather than count a present key as covered data.
def test_desk_run_refuses_empty_version_frames(
    tmp_path, monkeypatch, torch_loaders
):
    from backend.agents.trading.desk import fundamental
    from backend.market import fundamentals_asof as fa
    from backend.market.store import MarketStore

    asof = date(2026, 2, 16)
    store = MarketStore(tmp_path)
    store.write_frame(fa.KIND, asof, "N0", fa.frame([]), {"source": "test"})
    with pytest.raises(fundamental.FundamentalSourceError):
        _run_desk(store, monkeypatch, asof)


# A frame whose filings are all public only after the decision session is no
# input to that decision: the desk refuses rather than rank on an analyst
# that saw nothing.
def test_desk_run_refuses_versions_available_only_after_the_decision(
    tmp_path, monkeypatch, torch_loaders
):
    from backend.agents.trading.desk import fundamental
    from backend.market import fundamentals_asof as fa
    from backend.market.store import MarketStore
    from backend.tests.test_fundamental_features import payload, row

    asof = date(2026, 2, 16)
    store = MarketStore(tmp_path)
    late = fa.parse_versions(
        payload(Revenues=[row("2025-01-01", "2025-03-31", 100, "2026-03-01", "late")])
    )
    store.write_frame(fa.KIND, asof, "N0", fa.frame(late), {"source": "test"})
    with pytest.raises(fundamental.FundamentalSourceError):
        _run_desk(store, monkeypatch, asof)


# A malformed version frame fails as a named data error before assembly, not
# as a bare ValueError from deep in the read path.
def test_desk_run_raises_clearly_on_malformed_version_frames(
    tmp_path, monkeypatch, torch_loaders
):
    from backend.agents.trading.desk import fundamental
    from backend.market import fundamentals_asof as fa
    from backend.market.store import MarketStore

    asof = date(2026, 2, 16)
    store = MarketStore(tmp_path)
    store.write_frame(
        fa.KIND,
        asof,
        "N0",
        {
            "name": ["revenue"],
            "tag": ["us-gaap:Revenues"],
            "start": ["2025-01-01"],
            "end": ["2025-03-31"],
            "value": ["not-a-number"],
            "filed": ["2025-05-01"],
            "accepted": [""],
            "accession": ["a"],
            "form": ["10-Q"],
        },
        {"source": "test"},
    )
    with pytest.raises(fundamental.FundamentalSourceError):
        _run_desk(store, monkeypatch, asof)
