"""The trailing-stop watcher.

What has to hold: the high ratchets up and never down; the stop sits the
given fraction under it, or at the floor when that is higher; a cross
fires and stays fired; and a feed that answers with anything but a price
reads as no print rather than a number.
"""

from types import SimpleNamespace

from backend.cli import market_watch


# The high only rises, the stop follows it, and once hit it stays hit.
def test_the_stop_trails_the_high_and_stays_fired():
    watch = market_watch.Watch("IREN", stop=0.10, high=None, floor=None)
    watch.update(40.0)
    assert watch.high == 40.0
    assert watch.level() == 36.0
    watch.update(50.0)
    assert watch.level() == 45.0
    line = watch.update(46.0)  # a dip that does not reach the stop
    assert "STOP HIT" not in line
    assert watch.high == 50.0  # the high does not fall
    line = watch.update(45.0)
    assert "STOP HIT" in line and watch.fired
    assert "STOP HIT" in watch.update(49.0)  # fired stays fired


# A floor above the trailing level is the level; a given high is honoured.
def test_the_floor_and_a_given_high_are_honoured():
    watch = market_watch.Watch("IREN", stop=0.12, high=46.10, floor=42.0)
    assert watch.level() == 42.0  # the floor, since 46.10 * 0.88 is below it
    watch.update(44.0)
    assert watch.high == 46.10
    assert "STOP HIT" not in watch.update(42.5)
    assert "STOP HIT" in watch.update(42.0)


# The feed's answer is a price only when it is one.
def test_latest_price_reads_the_feed_or_reports_none():
    def ok(url, headers, timeout):
        return SimpleNamespace(status_code=200, json=lambda: {"trade": {"p": 44.67}})

    def refused(url, headers, timeout):
        return SimpleNamespace(status_code=403, json=lambda: {})

    def empty(url, headers, timeout):
        return SimpleNamespace(status_code=200, json=lambda: {"trade": {}})

    assert market_watch.latest_price("IREN", {}, get=ok) == 44.67
    assert market_watch.latest_price("IREN", {}, get=refused) is None
    assert market_watch.latest_price("IREN", {}, get=empty) is None
