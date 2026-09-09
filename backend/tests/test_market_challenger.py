"""The challenger's record block and the scorecard's forward pricing.

What has to hold: the block carries the shadow book and every graded
name in the record's own shape; and a book walked from one record's
close to the next earns the weighted return of the names that have both
closes, cash earning nothing, when the fill is at the prior close and
costs are zero.
"""

from types import SimpleNamespace

import numpy as np

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
    ret = market_scorecard._forward_walk(records, closes, opens, "book")
    # 0.5 * 10% + 0.3 * -10% = +2%; the 20% in cash earns nothing.
    assert abs(ret[0] - 0.02) < 1e-12
