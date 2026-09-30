"""The universe cohort path: grouped ranks, the cohort, and the desk through it.

The registration's contract is the null test: the book through the cohort
path must reproduce the book run to the bit. These tests hold that at each
layer on synthetic data (the grouped rank with no groups, the value analyst
with the sides as peers, the whole desk with the book cohort), and check
that with groups the rank really is within the group.
"""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import cohort, value
from backend.agents.trading.desk.opinions import BEARISH, BULLISH, Opinion
from backend.market import baselines, challenger, universe
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE, AI_SIDE, SOFTWARE_SIDE
from backend.tests.test_trading_desk import (
    _write_corrected_versions,
    torch_loaders,  # noqa: F401 - fixture
)


# With no groups the grouped rank is the plain rank, bit for bit.
def test_grouped_rank_without_groups_is_percentile_rank():
    rng = np.random.default_rng(1)
    scores = rng.normal(size=(30, 9))
    scores[rng.random(scores.shape) < 0.2] = np.nan
    plain = baselines.percentile_rank(scores)
    grouped = baselines.grouped_percentile_rank(scores, None)
    assert np.array_equal(plain, grouped, equal_nan=True)


# With groups, each name's rank is taken among its own group only; a
# negative id is no group and gets no rank.
def test_grouped_rank_ranks_within_each_group():
    scores = np.array([[5.0, 1.0, 3.0, 9.0, 2.0, 7.0]])
    groups = np.array([0, 0, 0, 1, 1, -1])
    out = baselines.grouped_percentile_rank(scores, groups)
    assert out[0, :3].tolist() == [1.0, 0.0, 0.5]
    assert out[0, 3:5].tolist() == [1.0, 0.0]
    assert np.isnan(out[0, 5])
    with pytest.raises(ValueError, match="one id per column"):
        baselines.grouped_percentile_rank(scores, np.array([0, 1]))


# An Opinion with groups takes its stance within the group: the best of a
# weak sector is bullish, the worst of a strong one is bearish.
def test_opinion_groups_make_the_stance_relative_to_the_group():
    t = 4
    scores = np.tile(np.array([1.0, 2.0, 3.0, 10.0, 11.0, 12.0]), (t, 1))
    groups = np.array([0, 0, 0, 1, 1, 1])
    whole = Opinion("x", scores).stances()
    within = Opinion("x", scores, groups=groups).stances()
    # Across the whole panel the low sector's top name is only neutral and
    # the high sector's bottom name is never bearish.
    assert whole[-1].tolist() == [BEARISH, BEARISH, 0, 0, BULLISH, BULLISH]
    # Within the group each sector has its own top and bottom.
    assert within[-1].tolist() == [BEARISH, 0, BULLISH, BEARISH, 0, BULLISH]
    assert np.array_equal(
        Opinion("x", scores).ranks(), Opinion("x", scores, groups=None).ranks()
    )


# A synthetic panel over `names`, random walk prices.
def _panel(names, t=60, seed=0) -> Panel:
    rng = np.random.default_rng(seed)
    n = len(names)
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    close = 100.0 * np.exp(rng.normal(0.0, 0.02, size=(t, n + 1)).cumsum(axis=0))
    return Panel(
        dates=dates,
        tickers=tuple(names) + ("SPY",),
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={},
        benchmark="SPY",
    )


# The value analyst with `peers` equal to the sides is the value analyst
# with the sides, bit for bit; with a sector map, a name outside the sides
# gets a view and the peer medians move.
def test_value_peers_default_to_sides_and_replace_them_when_given():
    names = ("A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3")
    panel = _panel(names)
    rng = np.random.default_rng(2)
    shape = (len(panel.dates), len(panel.tickers))
    levels = {
        "revenue": rng.uniform(1e8, 1e9, size=shape),
        "earnings": rng.uniform(1e6, 1e8, size=shape),
        "equity": rng.uniform(1e8, 1e9, size=shape),
        "shares": rng.uniform(1e6, 1e7, size=shape),
        "revenue_growth": rng.uniform(-0.1, 0.5, size=shape),
    }
    sides = {
        "A1": AI_SIDE,
        "A2": AI_SIDE,
        "A3": AI_SIDE,
        "B1": SOFTWARE_SIDE,
        "B2": SOFTWARE_SIDE,
        "B3": SOFTWARE_SIDE,
    }
    plain = value.opine(panel, levels, sides)
    same = value.opine(panel, levels, sides, peers=dict(sides))
    assert np.array_equal(plain.scores, same.scores, equal_nan=True)
    assert np.isnan(plain.scores[-1, panel.index("C1")])
    sectors = {**sides, "C1": "Health Care", "C2": "Health Care", "C3": "Health Care"}
    sectored = value.opine(panel, levels, sides, peers=sectors)
    assert np.isfinite(sectored.scores[-1, panel.index("C1")])


# The gap blend ranks within the value analyst's groups when it has them,
# and is unchanged without them.
def test_with_gap_follows_the_value_groups():
    scores = np.array([[1.0, 2.0, 3.0, 10.0, 11.0, 12.0]] * 3)
    gap = np.array([[3.0, 2.0, 1.0, 12.0, 11.0, 10.0]] * 3)
    plain = challenger.with_gap({"value": Opinion("value", scores)}, gap)["value"]
    expected = np.nanmean(
        np.stack([baselines.percentile_rank(scores), baselines.percentile_rank(gap)]),
        axis=0,
    )
    assert np.array_equal(plain.scores, expected, equal_nan=True)
    groups = np.array([0, 0, 0, 1, 1, 1])
    grouped = challenger.with_gap(
        {"value": Opinion("value", scores, groups=groups)}, gap
    )["value"]
    assert grouped.groups is groups
    # Within each group the two rankings reverse each other: every blend is 0.5.
    assert np.allclose(grouped.scores, 0.5)


# The sector map reads the constituent file's sector and puts an overlay-only
# name in Information Technology; the book cohort is the sides.
def test_sector_map_and_book_cohort():
    members = (
        universe.UniverseMember(
            "KO", universe.MEMBER, (), "Coke", "Consumer Staples", "Soft Drinks"
        ),
        universe.UniverseMember(
            "NVDA",
            universe.MEMBER,
            (AI_COMPUTE,),
            "NVIDIA",
            "Information Technology",
            "Semiconductors",
        ),
        universe.UniverseMember("CRWV", universe.FOCUS, (AI_COMPUTE,), "CoreWeave"),
        universe.UniverseMember("SPY", universe.BENCHMARK, (), "S&P 500"),
    )
    sectors = cohort.sector_map(members)
    assert sectors == {
        "KO": "Consumer Staples",
        "NVDA": "Information Technology",
        "CRWV": cohort.OVERLAY_SECTOR,
    }
    book = cohort.book_cohort()
    sides = universe.book_sides(universe.build_universe())
    assert book.names == tuple(sorted(sides))
    assert book.peers == sides
    assert not book.rank_within_peers
    assert book.groups_for(_panel(("NVDA",))) is None


# The arms: sector ranks within eleven-ish groups, flat within one, tone
# keeps only the names the store has tone for; group ids skip the benchmark.
def test_universe_cohorts(monkeypatch):
    members = (
        universe.UniverseMember(
            "KO", universe.MEMBER, (), "Coke", "Consumer Staples", "Soft Drinks"
        ),
        universe.UniverseMember(
            "PEP", universe.MEMBER, (), "Pepsi", "Consumer Staples", "Soft Drinks"
        ),
        universe.UniverseMember(
            "NVDA",
            universe.MEMBER,
            (AI_COMPUTE,),
            "NVIDIA",
            "Information Technology",
            "Semiconductors",
        ),
        universe.UniverseMember("CRWV", universe.FOCUS, (AI_COMPUTE,), "CoreWeave"),
        universe.UniverseMember("SPY", universe.BENCHMARK, (), "S&P 500"),
    )
    sector = cohort.universe_cohort(cohort.SECTOR, universe=members)
    assert sector.names == ("CRWV", "KO", "NVDA", "PEP")
    assert sector.rank_within_peers
    assert set(sector.peers.values()) == {"Consumer Staples", "Information Technology"}
    panel = _panel(sector.names)
    ids = sector.groups_for(panel)
    assert ids[panel.index("SPY")] == -1
    assert ids[panel.index("KO")] == ids[panel.index("PEP")] != ids[panel.index("NVDA")]
    assert ids[panel.index("CRWV")] == ids[panel.index("NVDA")]
    flat = cohort.universe_cohort(cohort.FLAT, universe=members)
    assert flat.names == sector.names
    assert not flat.rank_within_peers
    assert set(flat.peers.values()) == {cohort.FLAT_GROUP}
    monkeypatch.setattr(
        cohort, "has_tone", lambda store, t, asof=None: t in ("KO", "NVDA")
    )
    tone = cohort.universe_cohort(cohort.TONE, store=object(), universe=members)
    assert tone.names == ("KO", "NVDA")
    assert tone.rank_within_peers
    assert set(tone.peers) == {"KO", "NVDA"}
    with pytest.raises(ValueError, match="unknown universe arm"):
        cohort.universe_cohort("everything", universe=members)
    with pytest.raises(ValueError, match="needs the store"):
        cohort.universe_cohort(cohort.TONE, universe=members)


# A small synthetic store with corrected versions and bars is beyond a unit
# test; the desk's own loaders are stubbed as `test_trading_desk` stubs
# them, and `book_panel` is replaced by a panel over the cohort's names.
def _run(store, monkeypatch, panel, sides, **kwargs):
    from backend.agents.trading.desk import desk as trading_desk

    seen = {}

    def book_panel(store, asof=None, names=None):
        seen["names"] = names
        return panel, sides

    monkeypatch.setattr(trading_desk, "book_panel", book_panel)
    report = trading_desk.run(store, date(2026, 2, 16), inputs=(), **kwargs)
    return report, seen


# The null test at the desk: the book through the cohort path is the book
# run, grades, votes, scores and every opinion's score bit for bit.
@pytest.mark.usefixtures("torch_loaders")
def test_desk_book_cohort_reproduces_the_plain_run(tmp_path, monkeypatch):
    from backend.market.store import MarketStore
    from backend.tests.test_trading_desk import _desk_panel

    store = MarketStore(tmp_path)
    _write_corrected_versions(store, date(2026, 2, 16))
    panel = _desk_panel()
    sides = {"N0": AI_SIDE, "N1": SOFTWARE_SIDE}
    plain, seen_plain = _run(store, monkeypatch, panel, sides)
    assert seen_plain["names"] is None
    book = cohort.Cohort(
        cohort.BOOK, ("N0", "N1"), dict(sides), rank_within_peers=False
    )
    through, seen = _run(store, monkeypatch, panel, sides, cohort=book)
    assert seen["names"] == ("N0", "N1")
    assert np.array_equal(plain.graded.grades, through.graded.grades)
    assert np.array_equal(plain.graded.votes, through.graded.votes)
    assert np.array_equal(plain.scores, through.scores, equal_nan=True)
    for name, opinion in plain.opinions.items():
        assert np.array_equal(
            opinion.scores, through.opinions[name].scores, equal_nan=True
        )
        assert through.opinions[name].groups is None


# With a grouped cohort every analyst carries the group ids, the rotation
# analyst does not, and the value analyst's peers are the cohort's map.
@pytest.mark.usefixtures("torch_loaders")
def test_desk_grouped_cohort_sets_groups_on_the_analysts(tmp_path, monkeypatch):
    from backend.market.store import MarketStore
    from backend.tests.test_trading_desk import _desk_panel

    store = MarketStore(tmp_path)
    _write_corrected_versions(store, date(2026, 2, 16))
    panel = _desk_panel()
    sides = {"N0": AI_SIDE, "N1": SOFTWARE_SIDE}
    peers = {"N0": "Information Technology", "N1": "Health Care"}
    sector = cohort.Cohort(cohort.SECTOR, ("N0", "N1"), peers, rank_within_peers=True)
    calls = []
    original = value.opine

    def spy(panel, levels, sides, size_neutral=True, peers=None):
        calls.append(peers)
        return original(panel, levels, sides, size_neutral, peers)

    monkeypatch.setattr(value, "opine", spy)
    report, _ = _run(store, monkeypatch, panel, sides, cohort=sector)
    assert calls == [peers]
    ids = sector.groups_for(panel)
    for name, opinion in report.opinions.items():
        assert opinion.groups is not None, name
        assert np.array_equal(opinion.groups, ids), name
    assert report.regime.rotation.groups is None
    assert report.sides == sides


# `replace` keeps the groups, so a blended or re-scored opinion stays grouped.
def test_replace_keeps_groups():
    groups = np.array([0, 1])
    o = Opinion("x", np.zeros((2, 2)), groups=groups)
    assert replace(o, scores=np.ones((2, 2))).groups is groups
