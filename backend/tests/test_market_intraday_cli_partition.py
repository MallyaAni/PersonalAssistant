"""The IEX fifteen-minute cache is partitioned by the New York date.

It used to be labelled by the UTC date, so a refresh run after 20:00
Eastern wrote a partition named for a session that had not happened yet.
"""

from datetime import UTC, date, datetime

from backend.cli.market_intraday import default_asof


# 23:30 UTC on the 5th is still the 5th in New York; 03:00 UTC on the
# 6th is the evening of the 5th in New York, and was labelled the 6th.
def test_default_partition_is_the_new_york_date():
    assert default_asof(datetime(2026, 1, 5, 23, 30, tzinfo=UTC)) == date(2026, 1, 5)
    assert default_asof(datetime(2026, 1, 6, 3, 0, tzinfo=UTC)) == date(2026, 1, 5)
    assert default_asof(datetime(2026, 7, 6, 3, 0, tzinfo=UTC)) == date(2026, 7, 5)
