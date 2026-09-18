"""The stretch leg must stay continuous when price crosses a level.

This file exists because of a defect that reached production and stayed
there for months. `levels._nearest` takes the highest swing low *strictly
below* the close, so the session a price ticks under its own support, that
level is discarded and the measure snaps to the next level far beneath.
The distance-to-support leg therefore sawtoothed. On CRWV the leg's
percentile swung between 4 and 96 on price moves under one percent, and a
4.2% down day nearly tripled the name's technical rank.

The tests below are deterministic on purpose. An earlier attempt at this
guard used random paths and percentile thresholds, and on real prices every
candidate leg has some quiet session where it moves the width of the
cross-section, so a threshold either passed everything or failed
everything. The mechanism, on the other hand, is exact: two swing lows and
a close that steps across one of them reproduces the whole defect in four
rows, and no future change to volatility, book size or seed can make that
flaky.

Anything added to the stretch role in future belongs in
`CONTINUOUS_LEVELS` and its selector in `CONTINUOUS_SELECTORS`. A leg that
cannot survive a crossing does not go in front of a trader.
"""

import numpy as np
import pytest

from backend.market import levels

# Two swing lows, the second stamped later and nearer the price.
FAR_LEVEL, NEAR_LEVEL = 80.0, 90.0
# A close either side of the near level: a 2.2% step, nothing dramatic.
ABOVE, BELOW = 91.0, 89.0
# The published measures that survive a crossing. The original,
# "support_distance", is absent and must stay absent.
CONTINUOUS_LEVELS = ("support_gap", "band_position")
# The selector values in `technical.STRETCH_LEG` that reach them, plus the
# one that drops the leg entirely. "support" is the sawtooth and is barred.
CONTINUOUS_SELECTORS = ("signed", "band", "none")


# Four sessions: the two levels get stamped, then price steps across the
# nearer one. `_nearest` windows levels at or before each row, so the
# levels must be stamped first.
def _fixture() -> tuple[np.ndarray, np.ndarray]:
    stamped = np.array([[FAR_LEVEL], [NEAR_LEVEL], [np.nan], [np.nan]])
    close = np.array([[120.0], [120.0], [ABOVE], [BELOW]])
    return stamped, close


# The bug itself, pinned. If this ever stops failing to be continuous, the
# original has been fixed in place and the guard below can be retired.
def test_the_original_measure_discards_a_level_when_price_crosses_it():
    stamped, close = _fixture()
    nearest = levels._nearest(stamped, close, True, levels.LEVEL_LOOKBACK)
    assert nearest[2, 0] == NEAR_LEVEL
    # One 2.2% step down and the level the trader is watching is gone.
    assert nearest[3, 0] == FAR_LEVEL

    distance = (close[:, 0] - nearest[:, 0]) / close[:, 0]
    step = abs(distance[3] - distance[2])
    price_move = abs(BELOW - ABOVE) / ABOVE
    # The measure moved about nine percent on a two percent price move.
    assert step > 4.0 * price_move, (
        "the original measure no longer sawtooths; if it was fixed in place, "
        "delete this test and the selector along with it"
    )


# The replacement keeps the level it was measuring against, so the measure
# moves by roughly the price move and simply changes sign.
def test_the_signed_measure_survives_the_crossing():
    stamped, close = _fixture()
    signed = levels._nearest_signed(stamped, close, levels.LEVEL_LOOKBACK)
    price_move = abs(BELOW - ABOVE) / ABOVE

    assert signed[2, 0] == pytest.approx((ABOVE - NEAR_LEVEL) / ABOVE)
    # Below the level the distance is negative, not a jump to the far one.
    assert signed[3, 0] == pytest.approx((BELOW - NEAR_LEVEL) / BELOW)
    assert signed[3, 0] < 0.0

    step = abs(signed[3, 0] - signed[2, 0])
    assert step == pytest.approx(price_move, abs=0.005), (
        "the signed measure should move with price, not in jumps"
    )


# The property stated plainly, over the whole crossing neighbourhood: a
# continuous leg's change is bounded by the price change that caused it.
# The original fails this; every candidate must pass it.
@pytest.mark.parametrize("nudge", [0.5, 0.2, 0.05, 0.01])
def test_the_signed_measure_is_bounded_by_the_price_move(nudge: float):
    stamped = np.array([[FAR_LEVEL], [NEAR_LEVEL], [np.nan], [np.nan]])
    close = np.array([[120.0], [120.0], [NEAR_LEVEL + nudge], [NEAR_LEVEL - nudge]])
    signed = levels._nearest_signed(stamped, close, levels.LEVEL_LOOKBACK)
    original = levels._nearest(stamped, close, True, levels.LEVEL_LOOKBACK)
    distance = (close[:, 0] - original[:, 0]) / close[:, 0]

    price_move = abs(close[3, 0] - close[2, 0]) / close[2, 0]
    signed_step = abs(signed[3, 0] - signed[2, 0])
    original_step = abs(distance[3] - distance[2])

    # A hair's-breadth crossing must be a hair's-breadth change.
    assert signed_step <= 2.0 * price_move + 1e-9
    # And the thing it replaces must be the thing that blows up, or this
    # comparison is measuring nothing. The smaller the nudge, the worse.
    assert original_step > 4.0 * signed_step


# Whatever plays the stretch role must be published for the analyst to
# find, and the original must not be reachable through that role.
def test_every_candidate_is_published_and_the_original_is_not_a_candidate():
    for leg in CONTINUOUS_LEVELS:
        assert leg in levels.LEVEL_NAMES, f"{leg} is not published in LEVEL_NAMES"
    assert "support_distance" not in CONTINUOUS_LEVELS
    assert "support" not in CONTINUOUS_SELECTORS


# The leg the desk actually ships must be one of the continuous ones. This
# is the line that fails if anyone ever points the selector back at the
# sawtooth.
def test_the_shipped_leg_is_continuous():
    from backend.agents.trading.desk import technical as nightly

    assert nightly.STRETCH_LEG in CONTINUOUS_SELECTORS, (
        f"the nightly analyst ships {nightly.STRETCH_LEG!r}, which sawtooths"
    )


# The 15-minute board read and the nightly grade must score through the
# same analyst, or a fix to one silently leaves the other sawtoothing and
# the board contradicts itself intraday. `live_technical` scores by calling
# the nightly analyst's own `opine`, and that is what makes one constant
# enough to fix both; this pins that arrangement so nobody forks it.
def test_the_live_read_scores_through_the_nightly_analyst():
    from backend.agents.trading.desk import technical as nightly
    from backend.market import live_technical

    assert live_technical.technical_analyst is nightly, (
        "the live read no longer delegates to the nightly analyst, so the "
        "stretch leg must now be fixed in both places"
    )
    assert nightly.opine is live_technical.technical_analyst.opine


# The band candidate is continuous by construction: it depends on no level
# dropping in or out, only on the close's own recent range.
def test_the_band_candidate_has_no_levels_to_drop():
    rising = np.linspace(90.0, 110.0, 60).reshape(-1, 1)
    position = levels.band_position(rising)
    good = np.isfinite(position[:, 0])
    steps = np.abs(np.diff(position[good, 0]))
    assert steps.max() < 0.35, "the band position jumped without a level to lose"


# A name that has climbed for a year without printing a swing low has no
# level beneath it. `support_distance` floors on the moving averages so it
# is rarely absent, but `support_gap` reads swing lows alone and is absent
# for exactly that name. It must still be scored, at the stretched end of
# the scale, or it silently scores on one leg fewer than the rest of the
# book. This is the defect that failed the deploy gate on 2026-09-18.
def test_a_name_with_no_swing_low_is_still_scored_on_every_leg():
    from datetime import date, timedelta

    from backend.agents.trading.desk import technical as analyst
    from backend.market.panel import Panel

    t, n = 400, 4
    rng = np.random.default_rng(5)
    returns = np.zeros((t, n))
    returns[:, 0] = 0.004  # a straight climb: never prints a swing low
    returns[:, 1] = rng.normal(0.0, 0.015, t)
    returns[:, 2] = -0.001
    returns[:, 3] = -0.002
    close = 100.0 * np.exp(np.cumsum(returns, axis=0))
    close = np.column_stack([close, np.full(t, 100.0)])
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    tickers = tuple([f"N{i}" for i in range(n)] + ["SPY"])
    panel = Panel(
        dates=dates,
        tickers=tickers,
        open=close,
        high=close * 1.005,
        low=close * 0.995,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={x: () for x in tickers},
        benchmark="SPY",
    )
    loc = levels.level_features(panel)
    idx = {n_: i for i, n_ in enumerate(levels.LEVEL_NAMES)}
    # The premise: the climber really has no swing low to measure against.
    assert not np.isfinite(loc[-1, 0, idx["support_gap"]])

    falling = analyst.opine(panel, np.full(t, -0.1)).scores[-1, :n]
    rising = analyst.opine(panel, np.full(t, 0.1)).scores[-1, :n]
    assert np.isfinite(falling[0]), (
        "a name with no swing low dropped out of the falling blend"
    )
    # And the fade is actually applied to it rather than skipped: a name
    # with nothing beneath it must score worse in the falling playbook,
    # where stretch is penalised, than in the rising one, where it is not.
    # Its three trend legs are strong, so it may still rank well overall;
    # what matters is that the fourth leg reached it at all.
    assert falling[0] < rising[0]


# The second discontinuity, found only after the first fix shipped. A
# measure that picks the NEAREST level in absolute terms switches which
# level it is measuring the moment price passes the midpoint between two of
# them, and the sign flips with it. `_nearest_signed` does exactly that:
# with swing lows at 90 and 100, a 0.21% step across 95 moves the gap from
# -0.0515 to +0.0516, a jump of 49 times the price move. It fixed the
# crossing case and broke the midpoint case.
#
# This is why the shipped leg is `band`, which selects no level at all.
def test_the_signed_measure_jumps_at_the_midpoint_between_two_levels():
    stamped = np.array([[90.0], [100.0], [np.nan], [np.nan]])
    close = np.array([[120.0], [120.0], [95.1], [94.9]])
    gap = levels._nearest_signed(stamped, close, levels.LEVEL_LOOKBACK)
    move = abs(94.9 - 95.1) / 95.1
    jump = abs(gap[3, 0] - gap[2, 0])
    assert gap[2, 0] < 0 < gap[3, 0], "the measured level should switch here"
    assert jump > 20.0 * move, (
        "if this no longer jumps, _nearest_signed has been made continuous "
        "and may be reconsidered for the stretch role"
    )


# The band position has no level to select and no level to lose, so the
# same midpoint that breaks the signed measure does nothing to it.
def test_the_band_measure_has_no_midpoint_to_jump_at():
    # A path that drifts across the middle of its own range, twice.
    close = np.concatenate(
        [np.linspace(90.0, 100.0, 40), np.linspace(100.0, 90.0, 40)]
    ).reshape(-1, 1)
    position = levels.band_position(close)
    good = np.isfinite(position[:, 0])
    with np.errstate(all="ignore"):
        move = np.abs(np.diff(close[:, 0]) / close[:-1, 0])
    step = np.abs(np.diff(position[good, 0]))
    # No single session may move the position more than a quarter of the
    # band when price moved less than two percent.
    quiet = move[: len(step)] < 0.02
    assert step[quiet].max() < 0.25, (
        f"the band position jumped {step[quiet].max():.3f} on a quiet session"
    )
