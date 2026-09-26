"""The rotation half-vote reaches both sides only when the stance is the sign.

With a 68/26 split of AI and software names, percentile ranks of a
two-valued score never put the larger side in the top or bottom fraction.
The signed opinion votes for the leading side and against the other one,
whatever the counts.
"""

import numpy as np

from backend.agents.trading.desk.opinions import BEARISH, BULLISH, NEUTRAL, Opinion, signed_ranks


# Two-valued scores at a 68/26 split: ranked, the large side is neutral both
# ways; signed, the leader is bullish and the laggard bearish both ways.
def test_signed_stance_votes_on_both_sides():
    t, ai, sw = 4, 68, 26
    side = np.array([1.0] * ai + [-1.0] * sw)
    ai_leads = np.tile(0.05 * side, (t, 1))
    sw_leads = -ai_leads
    ranked_ai = Opinion("rotation", ai_leads).stances(persistence=1)
    ranked_sw = Opinion("rotation", sw_leads).stances(persistence=1)
    assert (ranked_ai[:, :ai] == NEUTRAL).all() and (ranked_ai[:, ai:] == BEARISH).all()
    assert (ranked_sw[:, :ai] == NEUTRAL).all() and (ranked_sw[:, ai:] == BULLISH).all()
    signed_ai = Opinion("rotation", ai_leads, signed=True).stances(persistence=1)
    signed_sw = Opinion("rotation", sw_leads, signed=True).stances(persistence=1)
    assert (signed_ai[:, :ai] == BULLISH).all() and (signed_ai[:, ai:] == BEARISH).all()
    assert (signed_sw[:, :ai] == BEARISH).all() and (signed_sw[:, ai:] == BULLISH).all()
    conviction = Opinion("rotation", ai_leads, signed=True).conviction()
    assert (conviction[:, :ai] == 1.0).all() and (conviction[:, ai:] == -1.0).all()


# Ranks are the sign, zero is neutral, NaN stays NaN, and a gated session
# (all NaN) yields no stance.
def test_signed_ranks_shape():
    scores = np.array([[0.3, -0.3, 0.0, np.nan], [np.nan] * 4])
    ranks = signed_ranks(scores)
    np.testing.assert_array_equal(ranks[0], [1.0, 0.0, 0.5, np.nan])
    assert np.isnan(ranks[1]).all()
    stances = Opinion("rotation", scores, signed=True).stances(persistence=1)
    np.testing.assert_array_equal(stances[0], [BULLISH, BEARISH, NEUTRAL, NEUTRAL])


# The regime analyst keeps the frozen behaviour unless asked, and hands the
# flag through to its rotation opinion.
def test_regime_opine_passes_the_flag(monkeypatch):
    from backend.agents.trading.desk import regime

    captured = {}
    original = regime.Opinion

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(regime, "Opinion", spy)
    from backend.market.universe import AI_COMPUTE, AI_SIDE, SOFTWARE, SOFTWARE_SIDE
    from backend.tests.test_trading_desk import _panel

    rng = np.random.default_rng(1)
    themes = {f"AI{i}": (AI_COMPUTE,) for i in range(3)}
    themes.update({f"SW{i}": (SOFTWARE,) for i in range(3)})
    panel = _panel(rng.normal(scale=0.01, size=(300, 6)), themes)
    sides = {k: (AI_SIDE if k.startswith("AI") else SOFTWARE_SIDE) for k in themes}
    regime.opine(panel, sides)
    assert captured.get("signed") is False
    regime.opine(panel, sides, signed_rotation=True)
    assert captured.get("signed") is True


# desk.run hands the arm through to the regime analyst and defaults to off.
def test_desk_run_accepts_the_arm(monkeypatch):
    import inspect

    from backend.agents.trading.desk import desk

    assert inspect.signature(desk.run).parameters["signed_rotation"].default is False
    seen = {}
    real = desk.regime.opine

    def spy(panel, sides, tightening=None, signed_rotation=False):
        seen["signed_rotation"] = signed_rotation
        return real(panel, sides, tightening, signed_rotation=signed_rotation)

    monkeypatch.setattr(desk.regime, "opine", spy)
    source = inspect.getsource(desk.run)
    assert "signed_rotation=signed_rotation" in source


# The scorecard's flag routes the arm into desk.run and names the output.
def test_scorecard_flag_names_the_arm(monkeypatch, tmp_path):
    from backend.cli import market_pit_scorecard as sc

    calls = {}

    def fake_run(store, asof, inputs=(), signed_rotation=False):
        calls["signed_rotation"] = signed_rotation
        raise RuntimeError("stop here")

    monkeypatch.setattr("backend.agents.trading.desk.desk.run", fake_run)
    monkeypatch.setattr("backend.market.store.MarketStore", lambda root: None)
    import pytest

    with pytest.raises(RuntimeError):
        sc.main(["--root", str(tmp_path), "--signed-rotation"])
    assert calls["signed_rotation"] is True
    with pytest.raises(RuntimeError):
        sc.main(["--root", str(tmp_path)])
    assert calls["signed_rotation"] is False
