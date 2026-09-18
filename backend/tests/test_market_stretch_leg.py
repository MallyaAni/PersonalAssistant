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
