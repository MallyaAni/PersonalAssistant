"""The challenger's record block and the scorecard's forward pricing.

What has to hold: the block carries the shadow book and every graded
name in the record's own shape; and a book priced from one record's
close to the next earns the weighted return of the names that have
both closes, cash earning nothing.
"""

from types import SimpleNamespace

import numpy as np

from backend.cli.market_scorecard import _forward
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


def test_forward_prices_a_book_between_two_closes():
    book = [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.3}]
    prices = {"AAA": (100.0, 110.0), "BBB": (50.0, 45.0)}
    # 0.5 * 10% + 0.3 * -10% = +2%; the 20% in cash earns nothing.
    assert abs(_forward(book, prices) - 0.02) < 1e-12
    # A name without both closes is skipped.
    assert abs(_forward(book, {"AAA": (100.0, 110.0)}) - 0.05) < 1e-12
