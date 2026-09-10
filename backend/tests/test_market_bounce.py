"""The bounce-exit signals.

What has to hold: a trend break fires once, on the first close below the
average after a long run above it; no bounce fires before a break; the
percent bounce fires on the first close far enough above the post-break
low; the flag stays up while price is still below the average; and the
run-length helper counts consecutive sessions.
"""

from types import SimpleNamespace

import numpy as np

from backend.cli import market_bounce as mb


def _series():
    up = 100.0 + np.arange(100)  # 100 sessions rising a point a session
    drop = up[-1] * 0.97 ** np.arange(1, 11)  # ten sessions falling 3%
    rise = drop[-1] * 1.03 ** np.arange(1, 6)  # five sessions rising 3%
    return np.concatenate([up, drop, rise])


def test_run_length_counts_consecutive_true():
    mask = np.array([[True], [True], [False], [True]])
    assert mb._run_length(mask)[:, 0].tolist() == [1, 2, 0, 1]


def test_break_then_bounce():
    close = _series()[:, None]
    sigs = mb.signals(SimpleNamespace(adj_close=close))["break50"]
    breaks = np.flatnonzero(sigs.fires["break"][:, 0])
    assert len(breaks) == 1
    assert 100 <= breaks[0] < 110  # during the fall
    # Nothing bounces before the break, and the flag is up from it to the end.
    for fires in sigs.fires.values():
        assert not fires[: breaks[0], 0].any()
    assert sigs.flagged[breaks[0] :, 0].all()
    # The low is the last falling close (index 109); 1.03^3 clears 8%, 1.03^2 does not.
    first_pct8 = int(np.flatnonzero(sigs.fires["pct8"][:, 0])[0])
    assert first_pct8 == 112
    first_pct3 = int(np.flatnonzero(sigs.fires["pct3"][:, 0])[0])
    assert first_pct3 == 110  # one 3% up close clears 3%
    # The deadline variant sells ten sessions after the break even without a bounce.
    overdue = np.flatnonzero(sigs.fires["upday2+deadline"][:, 0])
    assert overdue[0] <= breaks[0] + 10 + 1


def test_cross_break_needs_a_standing_uptrend():
    close = np.linspace(100, 50, 120)[:, None]  # never above: no break
    sigs = mb.signals(SimpleNamespace(adj_close=close))["cross"]
    assert not sigs.fires["break"].any()
    assert not sigs.flagged.any()
