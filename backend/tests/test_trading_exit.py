"""Bollinger readings and the exit analyst."""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import exit as exit_analyst
from backend.market import bands
from backend.market.panel import Panel


def _panel(close: np.ndarray, high=None, low=None, open_=None) -> Panel:
    t, n = close.shape
    dates = np.array(
        [date(2026, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    return Panel(
        dates=dates,
        tickers=tuple(f"N{i}" for i in range(n - 1)) + ("SPY",),
        open=close if open_ is None else open_,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={f"N{i}": () for i in range(n - 1)},
        benchmark="SPY",
    )


# Position is 0 at the lower band, 1 at the upper, and above 1 on a break.
def test_band_position():
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(scale=1.0, size=(120, 1)), axis=0)
    pos = bands.position(close)
    assert np.isnan(pos[:19, 0]).all()  # not enough history yet
    known = pos[20:, 0]
    known = known[np.isfinite(known)]
    assert known.min() < 0.3
    assert known.max() > 0.7
    # A flat series has no spread and therefore no position.
    assert np.isnan(bands.position(np.full((60, 1), 100.0))).all()


# Width is scale free: doubling every price leaves it unchanged.
def test_band_width_is_scale_free():
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(size=(80, 1)), axis=0)
    a = bands.width(close)
    b = bands.width(close * 2.0)
    finite = np.isfinite(a) & np.isfinite(b)
    assert finite.any()
    assert np.allclose(a[finite], b[finite])


# The width rank compares a name against its own past, reads nothing later,
# and calls a quiet stretch a squeeze and a violent one extended.
def test_width_rank_is_causal_and_relative():
    rng = np.random.default_rng(2)
    calm = rng.normal(scale=0.2, size=(300, 1))
    wild = rng.normal(scale=4.0, size=(60, 1))
    close = 100 + np.cumsum(np.vstack([calm, wild]), axis=0)
    ranks = bands.width_rank(close, history=250)
    assert np.isnan(ranks[:250, 0]).all()
    assert ranks[-1, 0] > 0.9  # the violent stretch is extended
    # Truncating the future must not change a past reading.
    cut = bands.width_rank(close[:320], history=250)
    assert cut[319, 0] == pytest.approx(ranks[319, 0])


# The exit fires on a bearish candle at the top of the band, and on a wide
# band with price high in it, and it names which one fired.
def test_exit_conditions():
    t = 60
    evidence = exit_analyst.ExitEvidence(
        band_position=np.full((t, 2), 0.5),
        band_width_rank=np.full((t, 2), 0.5),
        bearish_candle=np.zeros((t, 2), dtype=bool),
    )
    assert not evidence.signalled().any()

    reversal = exit_analyst.ExitEvidence(
        band_position=np.full((t, 2), 0.97),
        band_width_rank=np.full((t, 2), 0.2),
        bearish_candle=np.ones((t, 2), dtype=bool),
    )
    assert reversal.signalled().all()
    assert "bearish candle" in exit_analyst.reason(reversal, 30, 0)

    extended = exit_analyst.ExitEvidence(
        band_position=np.full((t, 2), 0.85),
        band_width_rank=np.full((t, 2), 0.95),
        bearish_candle=np.zeros((t, 2), dtype=bool),
    )
    assert extended.signalled().all()
    assert "band is wide" in exit_analyst.reason(extended, 30, 0)

    # High in a narrow band is not an exit: the move has not been made.
    quiet = exit_analyst.ExitEvidence(
        band_position=np.full((t, 2), 0.85),
        band_width_rank=np.full((t, 2), 0.30),
        bearish_candle=np.zeros((t, 2), dtype=bool),
    )
    assert not quiet.signalled().any()


# A fresh position is left alone through the grace period even when the
# condition is already true, so a name bought while extended is not sold
# straight back out.
def test_grace_period():
    t = 60
    evidence = exit_analyst.ExitEvidence(
        band_position=np.full((t, 2), 0.99),
        band_width_rank=np.full((t, 2), 0.99),
        bearish_candle=np.ones((t, 2), dtype=bool),
    )
    assert not exit_analyst.should_exit(evidence, 10, 0, entry_index=5)
    assert not exit_analyst.should_exit(evidence, 24, 0, entry_index=5)
    assert exit_analyst.should_exit(evidence, 25, 0, entry_index=5)
    assert exit_analyst.should_exit(evidence, 6, 0, entry_index=5, grace=0)


# The evidence reads off a real panel without needing anything else.
def test_evidence_from_a_panel():
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(size=(320, 3)), axis=0)
    high = close * 1.02
    low = close * 0.98
    panel = _panel(close, high=high, low=low, open_=close)
    evidence = exit_analyst.evidence(panel)
    assert evidence.band_position.shape == close.shape
    assert evidence.band_width_rank.shape == close.shape
    assert evidence.bearish_candle.dtype == bool
    assert np.isfinite(evidence.band_position[-1]).any()
