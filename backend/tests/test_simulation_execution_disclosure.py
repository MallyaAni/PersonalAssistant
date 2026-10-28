"""The record publishes no daily-price simulation under the live rule's name.

The Paper account view's "Historical simulation" box used to draw a curve the
nightly priced with the older daily-price simulator (`desk/simulate.py`,
graded-equal-weight/5 with dip-or-close fills) under the live policy's name.
The box now reads the installed rule's own account simulation from the replay
(`market_policy_replay_research.read_book`), so the record carries only the
paper account's own equity history.
"""

from backend.agents.trading.desk import paper, simulate
from backend.cli import market_daily
from backend.tests.test_market_daily import _report


def test_the_record_carries_no_daily_price_simulation(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("the nightly priced the old daily-price simulation")

    monkeypatch.setattr(simulate, "run", forbidden)
    monkeypatch.setattr(paper, "load_state", lambda root: paper.PaperState())
    assert market_daily.curves(_report(), object(), tmp_path) == {"paper": None}
    assert not hasattr(market_daily, "curve_block")
