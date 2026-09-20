"""Does the entry put on a size that matches the signal, on the real book?

The unit tests fix `_entry_orders` against hand-made holdings and prices. They
cannot say whether the rule behaves on the desk's own panel, where the band
readings are whatever eleven years of real prices produced. That gap is how
the flat 3% survived: every test asserted the constant it was given.

The operator's standard, said twice: "size depends on confidence at that
price", not a fixed number. So this drives the production sizing over the real
store and asserts the properties that make it that rule rather than another:

  * a stronger reading at the same price earns a larger position, monotonically
  * the name cap remains the backstop at readings the history never produced
  * nothing fires below the trigger, and what does fire is worth trading
  * the board and the book agree on the size, because they share one function

It also asserts the trigger admits enough signal to be a rule at all. At 2.5
sigma it fired 61 times a year across ninety-four names and never once in the
live account's first ten sessions, which is the defect the threshold change
was made to fix; a regression back toward silence should fail here rather than
be noticed months later on a chart.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.agents.trading.desk import entry as entry_analyst
from backend.agents.trading.desk import grading, paper
from backend.market import decision_view

pytest.importorskip("torch", reason="the desk panel loads models that need torch")


# The desk's own panel, built once: this is the real store, not a fixture.
@pytest.fixture(scope="module")
def report():
    """Return the desk report over the real market store."""
    from pathlib import Path

    from backend.agents.trading.desk import desk as trading_desk
    from backend.market.store import MarketStore

    root = Path("data/market")
    if not (root / "desk").exists():
        pytest.skip("no market store on this machine")
    return trading_desk.run(MarketStore(root), inputs=())


# A bigger reading at the same price is a bigger position, with no flat spot
# and no reversal. The flat increment failed this at every point.
def test_a_stronger_reading_earns_a_larger_position():
    readings = [paper.ENTRY_BAND_Z + step for step in (0.0, 0.1, 0.25, 0.5, 1.0)]
    sizes = [paper.entry_size(r) for r in readings]
    assert all(b > a for a, b in zip(sizes, sizes[1:])), sizes
    assert sizes[0] >= paper.MIN_TRADE, "the smallest entry must be worth trading"


# Below the trigger there is no entry at all, whatever else is true.
def test_nothing_fires_below_the_trigger():
    assert paper.entry_size(paper.ENTRY_BAND_Z - 0.01) == 0.0
    assert paper.entry_size(0.0) == 0.0
    assert paper.entry_size(float("nan")) == 0.0
    assert paper.entry_size(float("-inf")) == 0.0


# The cap is the backstop, including well past anything the history produced.
# The exponent was chosen for this property and not for its mean, so it is
# asserted rather than left to the caller's clipping.
def test_the_name_cap_still_bounds_the_tail(report):
    band = entry_analyst.bollinger_z(report.panel.adj_close)
    seen = float(np.nanmax(band[np.isfinite(band)]))
    # At the largest reading eleven years of real prices produced, the size
    # must sit COMFORTABLY inside the cap - not at it. A curve that is already
    # clipping on data it has seen is one where every further breakout is the
    # same maximum position, which is the degenerate behaviour the exponent
    # was chosen to avoid.
    assert paper.entry_size(seen) < paper.ENTRY_NAME_CAP * 0.75, (
        f"the largest reading in the history is {seen:.2f} and the curve asks "
        f"{paper.entry_size(seen):.1%} there, against a {paper.ENTRY_NAME_CAP:.0%} cap"
    )
    # And at 3.0 - the reference the exponent was picked on, already 40%
    # beyond anything seen - it is still inside. Exponent 4 asks 55% here.
    assert paper.entry_size(3.0) <= paper.ENTRY_NAME_CAP, paper.entry_size(3.0)
    # The cap is a backstop, so the curve is allowed to reach it eventually.
    # What is asserted is that "eventually" is far outside the observed range.
    crosses = next(
        (z / 100 for z in range(100, 1000) if paper.entry_size(z / 100) > paper.ENTRY_NAME_CAP),
        None,
    )
    assert crosses is None or crosses > seen * 1.4, (
        f"the curve reaches the cap at {crosses}, only {crosses / seen:.2f}x the "
        f"largest reading ever observed ({seen:.2f})"
    )


# The book and the board must name the same size, or the page advertises a
# trade the nightly will not place. They drifted on the WORD for the action
# four times; the number is the same class of defect.
def test_the_board_and_the_book_size_an_entry_identically():
    row = {"rejecting_band": False, "target_weight": 0.05}
    for band in (paper.ENTRY_BAND_Z, 1.4, 1.8, 2.5):
        action, size, _why = decision_view.entry_action(row, band, "A+", 0.0)
        assert action == decision_view.Action.BUY
        assert size == pytest.approx(paper.entry_size(band))


# The trigger has to admit enough signal to be a rule. This is the defect that
# prompted the change: at 2.5 sigma the entry never fired in the live account.
def test_the_trigger_fires_often_enough_to_be_a_rule(report):
    panel = report.panel
    grades = report.graded.grades
    in_book = np.array([t in report.sides for t in panel.tickers])
    in_book[panel.index(panel.benchmark)] = False
    band = entry_analyst.bollinger_z(panel.adj_close)
    with np.errstate(invalid="ignore"):
        fires = (
            np.isfinite(band)
            & (band >= paper.ENTRY_BAND_Z)
            & (grades >= grading.ORDINAL[grading.A])
            & in_book[None, :]
        )
    sessions, names = panel.dates.size, int(in_book.sum())
    per_name_year = float(fires.sum()) / names / (sessions / 252.0)
    # At the retired 2.5-sigma trigger this was 0.65 a name a year and the
    # live account saw none of it. One a year is a floor, not a target.
    assert per_name_year >= 1.0, (
        f"the trigger fires {per_name_year:.2f} times a name a year across "
        f"{names} names; at that rate the account can go months without an "
        "entry, which is what it did"
    )
    # And it must still be selective: a rule that fires most sessions is the
    # rebalance with extra cost, not a breakout.
    assert float(fires.mean()) < 0.05, "the trigger is no longer selective"


# What the rule would actually put on today, end to end, at real prices.
def test_todays_entries_are_sized_and_tradeable(report):
    panel = report.panel
    grades = report.graded.grades
    last = panel.dates.size - 1
    band = entry_analyst.bollinger_z(panel.adj_close)[last]
    sized = []
    for column, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark or ticker not in report.sides:
            continue
        if grades[last, column] < grading.ORDINAL[grading.A]:
            continue
        size = paper.entry_size(float(band[column]))
        if size > 0:
            sized.append((ticker, float(band[column]), size))
    # Nothing firing is a legitimate answer on a given day; what must never
    # happen is a firing that is unsized, unbounded, or below the floor.
    for ticker, reading, size in sized:
        assert paper.MIN_TRADE <= size <= paper.ENTRY_NAME_CAP, (ticker, reading, size)
