"""The structure study's pure parts.

What has to hold: the last two confirmed swing levels are carried
forward from their confirming sessions and nothing is known before two
exist; and the states read the way a trader reads them, with a
breakout counted once, on the session the close first crosses.
"""

import numpy as np

from backend.cli.market_structure import last_two, states


def test_last_two_carries_confirmed_levels_forward():
    stamped = np.full((6, 1), np.nan)
    stamped[1, 0] = 10.0
    stamped[3, 0] = 12.0
    stamped[5, 0] = 11.0
    newest, older = last_two(stamped)
    assert np.isnan(newest[0, 0])
    assert np.isnan(older[0, 0])
    assert newest[1, 0] == 10.0
    assert np.isnan(older[1, 0])
    assert (newest[3, 0], older[3, 0]) == (12.0, 10.0)
    assert (newest[4, 0], older[4, 0]) == (12.0, 10.0)
    assert (newest[5, 0], older[5, 0]) == (11.0, 12.0)


def test_states_read_like_a_trader():
    # One name over five sessions with fixed swing levels: highs 12 then 12
    # (flat top), lows 8 then 9 (rising), close walking up through 12.
    close = np.array([[11.5], [11.8], [12.1], [12.4], [12.3]])
    h1 = np.full((5, 1), 12.0)
    h2 = np.full((5, 1), 12.0)
    l1 = np.full((5, 1), 9.0)
    l2 = np.full((5, 1), 8.0)
    st = states(close, h1, h2, l1, l2)
    assert not st["up"].any()  # the highs are equal, not higher
    assert not st["down"].any()
    assert st["setup"][:, 0].tolist() == [
        False,
        True,
        False,
        False,
        False,
    ]  # within 3% of 12
    assert st["breakout"][:, 0].tolist() == [False, False, True, False, False]
    assert not st["breakdown"].any()
    # Higher high and higher low is up; lower and lower is down.
    up = states(close, np.full((5, 1), 13.0), h2, l1, l2)
    assert up["up"].all()
    down = states(close, np.full((5, 1), 11.0), h2, np.full((5, 1), 7.0), l2)
    assert down["down"].all()
    # Nothing is known before two of each exist.
    unknown = states(close, h1, np.full((5, 1), np.nan), l1, l2)
    assert not unknown["known"].any()
