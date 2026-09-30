"""S1g, the structure notch on the technical analyst, behind its flag.

What has to hold (docs/research/structure-rules-plan-2026-09-30.md):

- With the flag off the analyst returns the incumbent Opinion, untouched.
- With the flag on, a name whose close is under a falling EMA21 with lower
  highs has its stance capped at neutral and its conviction at zero on
  those sessions; a bullish name elsewhere keeps its stance; the scores
  and the ranks are the incumbent's, so nothing else in the cross-section
  moves; the notch is cited in the evidence.
- The stance returns the session the condition clears.
- Under the null flag the notched path runs with a mask that never fires
  and reproduces the incumbent's stances, conviction and scores to the bit,
  and the grade is the incumbent's.
- The benchmark is never notched.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import grading, structure_panel, technical
from backend.agents.trading.desk.opinions import BULLISH, NEUTRAL, Opinion
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

T, N = 400, 8


# A panel of N names on daily returns, SPY flat as the benchmark; highs a
# hair over the close unless `highs` gives a name's own.
def _panel(returns: np.ndarray, highs: dict[int, np.ndarray] | None = None) -> Panel:
    t, n = returns.shape
    themes = {f"N{i}": (AI_COMPUTE,) for i in range(n)}
    full = np.concatenate([returns, np.zeros((t, 1))], axis=1)
    close = 100.0 * np.exp(np.cumsum(full, axis=0))
    high = close * 1.002
    for j, own in (highs or {}).items():
        high[:, j] = own
    dates = np.array(
        [date(2020, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    return Panel(
        dates=dates,
        tickers=tuple(themes) + ("SPY",),
        open=close,
        high=high,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes=themes,
        benchmark="SPY",
    )


# Returns where N0 rallies for 300 sessions and then slides for 100 (a
# falling EMA, lower highs, the close under it), the others mixed.
def _returns(seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.01, size=(T, N))
    returns[:300, 0] = 0.004
    returns[300:, 0] = -0.012
    returns[:, 1] = 0.003  # a steady climber
    return returns


# Run `fn` with the flags set, restoring them however it ends.
def _with_flags(monkeypatch, notch: bool, null: bool = False):
    monkeypatch.setattr(technical, "STRUCTURE_NOTCH", notch)
    monkeypatch.setattr(technical, "STRUCTURE_NOTCH_NULL", null)


# Off: the plain Opinion, no notch field, no evidence key.
def test_flag_off_is_the_incumbent(monkeypatch):
    _with_flags(monkeypatch, False)
    opinion = technical.opine(_panel(_returns()))
    assert type(opinion) is Opinion
    assert technical.NOTCH_EVIDENCE not in opinion.evidence


# On: the slide notches N0 (stance at most neutral, conviction at most 0)
# while the rally did not; the scores and the ranks are the incumbent's;
# the climber keeps its bullish stance; the notch is cited.
def test_notch_caps_the_stance_and_the_conviction_where_it_fires(monkeypatch):
    panel = _panel(_returns())
    _with_flags(monkeypatch, False)
    plain = technical.opine(panel)
    _with_flags(monkeypatch, True)
    notched = technical.opine(panel)
    assert isinstance(notched, technical.NotchedOpinion)
    mask = notched.notch
    assert mask.shape == (T, N + 1)
    assert mask.dtype == bool
    np.testing.assert_array_equal(mask, technical.notch_mask(panel))
    assert not mask[:, N].any()  # SPY never
    # N0 is notched somewhere in the slide and nowhere in the rally.
    assert mask[320:, 0].any()
    assert not mask[:300, 0].any()
    assert np.array_equal(
        mask[:, 0], structure_panel.notch_mask(panel.adj_close[:, 0], panel.high[:, 0])
    )
    np.testing.assert_allclose(notched.scores, plain.scores, equal_nan=True)
    np.testing.assert_allclose(notched.ranks(), plain.ranks(), equal_nan=True)
    s_plain, s_notch = plain.stances(), notched.stances()
    c_plain, c_notch = plain.conviction(), notched.conviction()
    assert (s_notch[mask] <= NEUTRAL).all()
    known = mask & np.isfinite(c_plain)
    assert known.any()
    assert (c_notch[known] <= 0.0).all()
    assert np.isnan(c_notch[mask & ~np.isfinite(c_plain)]).all()
    np.testing.assert_array_equal(s_notch[~mask], s_plain[~mask])
    np.testing.assert_allclose(c_notch[~mask], c_plain[~mask], equal_nan=True)
    # A bearish stance is not lifted by the notch: min, not set.
    bear = mask & (s_plain < 0)
    if bear.any():
        assert (s_notch[bear] == s_plain[bear]).all()
    # Somewhere the notch changed a stance the incumbent had bullish.
    changed = mask & (s_plain == BULLISH)
    assert changed.any()
    assert (s_notch[changed] == NEUTRAL).all()
    assert s_notch[-1, 1] == s_plain[-1, 1]
    assert not mask[:, 1].any()
    cited = notched.evidence[technical.NOTCH_EVIDENCE]
    np.testing.assert_array_equal(cited, mask.astype(float))
    at = int(np.flatnonzero(mask[:, 0])[0])
    assert notched.cite(at, 0)[technical.NOTCH_EVIDENCE] == 1.0


# The stance returns the session the condition clears: a name notched
# through a slide and then recovering is capped only while notched, and
# the held bullish stance is back the first clear session.
def test_the_stance_returns_when_the_condition_clears(monkeypatch):
    returns = _returns()
    returns[300:340, 0] = -0.012
    returns[340:, 0] = 0.02  # a sharp recovery: over the EMA, highs rising
    panel = _panel(returns)
    _with_flags(monkeypatch, True)
    notched = technical.opine(panel)
    mask = notched.notch[:, 0]
    fired = np.flatnonzero(mask)
    assert len(fired)
    assert fired.max() < 360
    assert fired.min() >= 300
    _with_flags(monkeypatch, False)
    plain = technical.opine(panel).stances()[:, 0]
    held = notched.stances()[:, 0]
    last = int(fired.max())
    assert held[last] <= NEUTRAL
    # The first session after the last notched one is the incumbent's again.
    np.testing.assert_array_equal(held[last + 1 :], plain[last + 1 :])
    assert (held[: fired.min()] == plain[: fired.min()]).all()


# The null test: the notched path with a mask that never fires reproduces
# the incumbent's stances, conviction and scores to the bit, and the
# graded panel is the incumbent's.
def test_null_flag_reproduces_the_incumbent_to_the_bit(monkeypatch):
    panel = _panel(_returns(seed=4))
    _with_flags(monkeypatch, False)
    plain = technical.opine(panel)
    _with_flags(monkeypatch, True, null=True)
    null = technical.opine(panel)
    assert isinstance(null, technical.NotchedOpinion)
    assert not null.notch.any()
    assert np.array_equal(null.stances(), plain.stances())
    assert np.array_equal(null.conviction(), plain.conviction(), equal_nan=True)
    assert np.array_equal(null.scores, plain.scores, equal_nan=True)
    other = Opinion("other", np.zeros((T, N + 1)))
    for opinion in (plain, null):
        graded = grading.grade_stances(
            other.stances(),
            opinion.stances(),
            other.stances(),
            None,
            None,
            {
                "fundamental": other.conviction(),
                "technical": opinion.conviction(),
                "sentiment": other.conviction(),
            },
        )
        if opinion is plain:
            reference = graded
        else:
            assert np.array_equal(graded.grades, reference.grades)
            assert np.array_equal(graded.votes, reference.votes)
    # And with a real mask a notched name loses the technical vote: where
    # the incumbent's stance was bullish the votes fall by one and the
    # grade never rises; everywhere else the grade is the incumbent's.
    # (What the lost vote costs in grades is the grading rule's business:
    # an A+ is a bullish release with votes >= 2, which the other analysts
    # can still supply.)
    _with_flags(monkeypatch, True)
    real = technical.opine(panel)
    assert real.notch.any(), "the fixture must notch something for the grade check"
    bull = Opinion("bull", np.tile(np.arange(N + 1, dtype=float), (T, 1)))
    with_notch = grading.grade_stances(bull.stances(), real.stances(), bull.stances())
    without = grading.grade_stances(bull.stances(), plain.stances(), bull.stances())
    lost = real.notch & (plain.stances() == BULLISH)
    assert lost.any()
    np.testing.assert_allclose(with_notch.votes[lost], without.votes[lost] - 1.0)
    assert (with_notch.grades[lost] <= without.grades[lost]).all()
    assert (with_notch.grades[lost] < without.grades[lost]).any()
    assert (with_notch.grades[~real.notch] == without.grades[~real.notch]).all()


# The mask is the board's definitions on the panel's adjusted basis: a
# dividend factor between close and adj_close scales the highs with the
# close, so the notch reads the same name.
def test_notch_mask_reads_the_adjusted_basis(monkeypatch):
    _with_flags(monkeypatch, True)
    panel = _panel(_returns(seed=2))
    factor = np.linspace(0.9, 1.0, T)[:, None]
    scaled = Panel(
        dates=panel.dates,
        tickers=panel.tickers,
        open=panel.open,
        high=panel.high,
        low=panel.low,
        close=panel.close,
        adj_close=panel.adj_close * factor,
        volume=panel.volume,
        themes=panel.themes,
        benchmark=panel.benchmark,
    )
    a = technical.notch_mask(panel)
    b = technical.notch_mask(scaled)
    expected = structure_panel.notch_mask(scaled.adj_close, scaled.high * factor)
    expected[:, N] = False
    np.testing.assert_array_equal(b, expected)
    assert a.any()
    with pytest.raises(AttributeError):
        technical.notch_mask(object())
