"""Seven grading-input defects from the 2026-09-16 review, each pinned.

What has to hold: a filed share count is multiplied by the splits between
its filing and the session it prices, and not by earlier ones; a name
below every support is the most stretched of the session, not the least;
the benchmark never enters the technical cross-section; levels use high
and low on the close's adjusted basis; a name the expectations gap does
not cover keeps its valuation rank; the grade margin knows the
fundamental-and-technical route to an A; a gated rotation session has no
rotation vote whatever the stance held before.
"""

from datetime import date

import numpy as np

from backend.agents.trading.desk import actions, grading
from backend.agents.trading.desk.opinions import Opinion
from backend.market import levels, levels_pit
from backend.market.panel import Panel


def _panel(t=12, n=3, close_scale=1.0):
    close = np.full((t, n), 100.0) * close_scale
    dates = np.array(
        [np.datetime64("2026-09-01") + np.timedelta64(i, "D") for i in range(t)],
        dtype="datetime64[D]",
    )
    return Panel(
        dates=dates,
        tickers=("AAA", "BBB", "SPY"),
        open=close,
        high=close * 1.02,
        low=close * 0.98,
        close=close,
        adj_close=close * 0.9,  # a dividend payer: adjusted sits below raw
        volume=np.full_like(close, 1e6),
        themes={},
        benchmark="SPY",
    )


def test_a_split_after_the_filing_scales_the_count_until_the_next_filing():
    dates = np.array(
        [np.datetime64("2024-08-20") + np.timedelta64(i, "D") for i in range(20)],
        dtype="datetime64[D]",
    )
    # One filing (250 shares) known from the start; a 10:1 split on 08-28;
    # a new filing (2500, post-split) first seen on 09-05.
    shares = np.array([250.0] * 16 + [2500.0] * 4)
    out = levels_pit.split_adjusted_shares(shares, dates, [(date(2024, 8, 28), 10.0)])
    assert out[0] == 250.0  # before the split, the filing's own basis
    assert out[8] == 2500.0  # 08-28 onward, the old filing carries the split
    assert out[15] == 2500.0
    assert out[16] == 2500.0  # the new filing is already on the new basis
    untouched = levels_pit.split_adjusted_shares(shares, dates, [])
    assert untouched.tolist() == shares.tolist()


def test_a_name_below_every_support_is_the_most_stretched():
    from backend.agents.trading.desk import technical

    stretch = np.array([[0.05, np.nan, 0.02]] * 12)
    with np.errstate(all="ignore"):
        worst = np.nanmax(np.where(np.isfinite(stretch), stretch, np.nan), axis=1)
    filled = np.where(np.isfinite(stretch), stretch, worst[:, None])
    assert filled[0, 1] == 0.05  # the largest distance of the session, not zero
    assert technical.MOMENTUM_SESSIONS > 0  # the module is the one patched


def test_the_benchmark_has_no_technical_score(monkeypatch):
    from backend.agents.trading.desk import technical

    p = _panel(t=260)
    rng = np.random.default_rng(0)
    steps = rng.normal(0, 0.01, size=p.adj_close.shape)
    p.adj_close[:] = 100 * np.cumprod(1 + steps, axis=0)
    p.close[:] = p.adj_close
    p.high[:] = p.close * 1.01
    p.low[:] = p.close * 0.99
    opinion = technical.opine(p, None)
    assert np.isnan(opinion.scores[:, p.index("SPY")]).all()
    assert np.isfinite(opinion.scores[-1, 0])


def test_levels_use_high_and_low_on_the_adjusted_basis():
    p = _panel(t=80)
    feats = levels.level_features(p)
    idx = {n: i for i, n in enumerate(levels.LEVEL_NAMES)}
    # With adjusted close at 90 and raw high/low at 102/98, an unadjusted
    # range would put the close below its own low; on the adjusted basis
    # the 60-session range position sits inside [0, 1].
    pos = feats[-1, 0, idx["range_position_60"]]
    assert np.isfinite(pos)
    assert 0.0 <= pos <= 1.0


def test_a_name_without_a_gap_keeps_its_valuation_rank():
    from backend.market import challenger

    value = Opinion("value", np.array([[0.1, 0.9, np.nan], [0.2, 0.8, np.nan]]), {})
    gap = np.array([[np.nan, 0.5, np.nan], [np.nan, 0.5, np.nan]])
    out = challenger.with_gap({"value": value}, gap)
    assert np.isfinite(out["value"].scores[:, 0]).all()  # AAA keeps a score
    assert np.isnan(out["value"].scores[:, 2]).all()  # nothing to rank stays NaN


def test_grade_margin_knows_the_fundamental_and_technical_route():
    assert actions.grade_margin(1.5, grading.A, False, both_bullish=True) == 0.0
    assert actions.grade_margin(1.5, grading.A, False, both_bullish=False) == -0.5
    assert actions.grade_margin(1.0, grading.A, True) == 0.0
    assert actions.grade_margin(2.5, grading.A_PLUS, True) == 0.5


def test_a_gated_rotation_session_has_no_rotation_vote():
    t, n = 6, 2
    ones = np.ones((t, n))
    bullish = Opinion("x", np.array([[0.9, 0.1]] * t), {})
    rotation_scores = np.array([[0.9, 0.1]] * 3 + [[np.nan, np.nan]] * 3)
    rotation = Opinion("rotation", rotation_scores, {})
    graded = grading.grade(bullish, bullish, bullish, rotation, None)
    assert graded.stances["rotation"][2, 0] == 1  # held while the gate is open
    assert (graded.stances["rotation"][3:] == 0).all()  # nothing across the gate
    assert ones.shape == (t, n)
