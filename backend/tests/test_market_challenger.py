"""The challenger's record block and the scorecard's forward pricing.

What has to hold: the block carries the shadow book and every graded
name in the record's own shape; and a book walked from one record's
close to the next earns the weighted return of the names that have both
closes, cash earning nothing, when the fill is at the prior close and
costs are zero.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_scorecard
from backend.market import challenger


def test_record_block_has_the_book_and_every_grade():
    panel = SimpleNamespace(
        dates=np.arange(3).astype("datetime64[D]"),
        tickers=("AAA", "BBB", "SPY"),
        benchmark="SPY",
    )
    letters = {0: "A+", 1: "C"}
    graded = SimpleNamespace(letter=lambda t, column: letters[column])
    book = [
        SimpleNamespace(position=SimpleNamespace(ticker="AAA"), grade="A+", weight=0.11)
    ]
    shadow = SimpleNamespace(panel=panel, graded=graded, book=book)
    block = challenger.record_block(shadow)
    assert block["name"] == challenger.NAME
    assert block["book"] == [{"ticker": "AAA", "grade": "A+", "weight": 0.11}]
    assert block["grades"] == {"AAA": "A+", "BBB": "C"}


def test_the_shadow_blend_is_frozen_to_each_sessions_cross_section():
    # The challenger blends the value analyst's rank with the gap's rank per
    # session, so a shadow book frozen at t must not move with later days.
    from backend.market import baselines

    value = np.array([[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]])
    gap = np.array([[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]])
    blended = baselines.rank_blend(value, gap)
    # Make the later session's gap extreme: the earlier session's blend is
    # untouched, because each session ranks against its own cross-section.
    moved = gap.copy()
    moved[1] = [100.0, 100.0, 100.0]
    blended2 = baselines.rank_blend(value, moved)
    assert (blended[0] == blended2[0]).all()
    assert not (blended[1] == blended2[1]).all()


def test_forward_prices_a_book_between_two_closes(monkeypatch):
    records = [
        {
            "session": "2026-09-01",
            "book": [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.3}],
        },
        {
            "session": "2026-09-02",
            "book": [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.3}],
        },
    ]
    closes = {
        "AAA": {"2026-09-01": 100.0, "2026-09-02": 110.0},
        "BBB": {"2026-09-01": 50.0, "2026-09-02": 45.0},
    }
    # The fills happen at the next session's open; making the open equal the
    # prior close gives the close-to-close return, and zero cost keeps it exact.
    opens = {
        "AAA": {"2026-09-01": 100.0, "2026-09-02": 100.0},
        "BBB": {"2026-09-01": 50.0, "2026-09-02": 50.0},
    }
    monkeypatch.setattr(market_scorecard, "COST_BPS", 0.0)
    ret, invested = market_scorecard._forward_walk(records, closes, opens, "book")
    # 0.5 * 10% + 0.3 * -10% = +2%; the 20% in cash earns nothing.
    assert abs(ret[0] - 0.02) < 1e-12
    # The invested fraction is the book's share of the account at the close:
    # the 80c book grew to 0.55 + 0.27 over the 1.02 account.
    assert invested[0] == pytest.approx((0.55 + 0.27) / 1.02)
