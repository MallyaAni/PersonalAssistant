"""Valuation levels choose each tag per session from the filings on file then."""

from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.market import edgar, levels_pit
from backend.market import fundamentals_asof as fa
from backend.market.panel import Panel
from backend.market.yahoo import CorporateAction, TickerHistory

SYMBOL = "SYNTH"
STAMP = datetime(2024, 1, 2, tzinfo=UTC)
OLD = "us-gaap:SalesRevenueNet"
NEW = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
SHARES = "dei:EntityCommonStockSharesOutstanding"


def version(name, tag, start, end, value, filed, accession="a"):
    return fa.Version(
        name,
        tag,
        None if start is None else date.fromisoformat(start),
        date.fromisoformat(end),
        float(value),
        date.fromisoformat(filed),
        None,
        f"{accession}-{filed}",
        "10-Q",
    )


def quarter(tag, start, end, value, filed, name="revenue"):
    return version(name, tag, start, end, value, filed)


# Quarters 2016-2017 under the old tag; the new tag from 2018, with the
# 2017 comparatives filed under it in 2018 (the ASC 606 switch).
def switch_versions():
    return [
        quarter(OLD, "2016-01-01", "2016-03-31", 100, "2016-05-01"),
        quarter(OLD, "2016-04-01", "2016-06-30", 110, "2016-08-01"),
        quarter(OLD, "2016-07-01", "2016-09-30", 120, "2016-11-01"),
        quarter(OLD, "2017-01-01", "2017-03-31", 130, "2017-05-01"),
        quarter(NEW, "2017-01-01", "2017-03-31", 125, "2018-05-01"),
        quarter(NEW, "2018-01-01", "2018-03-31", 150, "2018-05-01"),
        version("shares", SHARES, None, "2016-04-20", 10, "2016-05-01"),
        version("shares", SHARES, None, "2018-04-20", 12, "2018-05-01"),
    ]


def make_panel(days):
    dates = np.asarray(days, dtype="datetime64[D]")
    close = np.full((len(dates), 2), 100.0)
    return Panel(
        dates, (SYMBOL, "SPY"), close, close, close, close, close,
        np.full_like(close, 1000.0), {}, "SPY",
    )  # fmt: skip


class VersionStore:
    """Serve one name's versions frame (and optionally a facts frame) in memory."""

    def __init__(self, versions, actions=(), record=None):
        self.versions = versions
        self.actions = actions
        self.record = record

    def read_frame(self, kind, ticker, asof=None):
        if ticker != SYMBOL:
            return None
        if kind == fa.KIND:
            if self.versions is None:
                return None
            return fa.frame(self.versions), {}
        if self.record is None:
            return None
        events, facts = edgar.record_frames(self.record)
        frames = {"edgar_events": events, "edgar_facts": facts}
        return frames.get(kind), {"cik": "0", "source_time": STAMP.isoformat()}

    def read(self, ticker, asof=None):
        if ticker != SYMBOL:
            return None
        return TickerHistory(SYMBOL, (), self.actions, STAMP.date(), STAMP, "fixture")


DAYS = ["2016-06-01", "2017-06-01", "2018-04-30", "2018-05-01", "2018-06-01"]


# Before the new tag exists the old tag is read (the frames path had no
# revenue there); once the new tag holds the latest quarter it is read,
# and growth compares within it.
def test_tag_is_chosen_from_the_filings_on_file_at_each_session():
    panel = make_panel(DAYS)
    out = levels_pit.point_in_time_levels(VersionStore(switch_versions()), panel)
    np.testing.assert_array_equal(
        out["revenue"][:, 0], [400.0, 520.0, 520.0, 600.0, 600.0]
    )
    growth = out["revenue_growth"][:, 0]
    assert np.isnan(growth[0])
    np.testing.assert_allclose(growth[1:3], 130.0 / 100.0 - 1.0)
    assert growth[3] == pytest.approx(150.0 / 125.0 - 1.0)


# Cutting the versions at any date never changes a session up to that date.
@pytest.mark.parametrize(
    "cut", ["2016-07-01", "2017-05-01", "2018-04-30", "2018-05-01"]
)
@pytest.mark.parametrize("strict", [False, True])
def test_truncated_filings_reproduce_every_earlier_session(cut, strict):
    days = np.arange(np.datetime64("2016-04-01"), np.datetime64("2018-07-01"))
    panel = make_panel(days)
    full = levels_pit.point_in_time_levels(
        VersionStore(switch_versions()), panel, strict_publication=strict
    )
    limit = date.fromisoformat(cut)
    kept = [v for v in switch_versions() if v.filed <= limit]
    part = levels_pit.point_in_time_levels(
        VersionStore(kept), panel, strict_publication=strict
    )
    upto = days <= np.datetime64(cut)
    for name in full:
        np.testing.assert_array_equal(full[name][upto], part[name][upto])


# A restatement filed later never reaches an earlier session, and the value a
# session has seen for a period is not rewritten afterwards either.
def test_first_filed_value_is_kept():
    versions = [
        quarter(NEW, "2017-01-01", "2017-03-31", 100, "2017-05-01"),
        quarter(NEW, "2017-01-01", "2017-03-31", 90, "2017-08-01"),
    ]
    panel = make_panel(["2017-06-01", "2017-09-01"])
    known = levels_pit.versions_levels(versions, panel.dates)
    np.testing.assert_array_equal(known["revenue"][0], [100.0, 100.0])


# A filing on the session counts only without strict publication.
def test_strict_publication_excludes_same_day_filings():
    versions = [quarter(NEW, "2017-01-01", "2017-03-31", 100, "2017-05-01")]
    panel = make_panel(["2017-05-01", "2017-05-02"])
    loose = levels_pit.point_in_time_levels(VersionStore(versions), panel)
    strict = levels_pit.point_in_time_levels(
        VersionStore(versions), panel, strict_publication=True
    )
    np.testing.assert_array_equal(loose["revenue"][:, 0], [400.0, 400.0])
    np.testing.assert_array_equal(strict["revenue"][:, 0], [np.nan, 400.0])


# Share counts from versions carry every later split, as the closes do.
def test_versions_share_counts_stay_split_adjusted():
    panel = make_panel(DAYS)
    store = VersionStore(
        switch_versions(), actions=(CorporateAction(date(2017, 1, 3), "split", 2.0),)
    )
    out = levels_pit.point_in_time_levels(store, panel)
    np.testing.assert_array_equal(out["shares"][:, 0], [20.0, 20.0, 20.0, 12.0, 12.0])
    strict = levels_pit.point_in_time_levels(store, panel, strict_publication=True)
    np.testing.assert_array_equal(
        strict["shares"][:, 0], [20.0, 20.0, 20.0, 20.0, 12.0]
    )


# Like the frames path a level is carried however old; the optional age
# bound leaves a tag whose last quarter is long past unknown instead.
def test_flow_age_bound_is_optional():
    versions = [quarter(OLD, "2014-07-01", "2014-09-30", 100, "2014-11-01")]
    panel = make_panel(["2015-06-01", "2015-12-31"])
    carried = levels_pit.versions_levels(versions, panel.dates)
    np.testing.assert_array_equal(carried["revenue"][0], [100.0, 100.0])
    bounded = levels_pit.versions_levels(versions, panel.dates, max_flow_age_days=400)
    assert bounded["revenue"][0][0] == 100.0
    assert np.isnan(bounded["revenue"][0][1])


# A derived fourth quarter, once known, is not replaced by a quarter filed later.
def test_derived_fourth_quarter_is_first_visible_value():
    q = [
        quarter(NEW, "2016-01-01", "2016-03-31", 10, "2016-05-01"),
        quarter(NEW, "2016-04-01", "2016-06-30", 10, "2016-08-01"),
        quarter(NEW, "2016-07-01", "2016-09-30", 10, "2016-11-01"),
        quarter(NEW, "2016-01-01", "2016-12-31", 50, "2017-02-15"),
        quarter(NEW, "2016-10-01", "2016-12-31", 21, "2018-02-15"),
    ]
    panel = make_panel(["2017-03-01", "2018-03-01"])
    known = levels_pit.versions_levels(q, panel.dates)
    np.testing.assert_array_equal(known["revenue"][0], [20.0, 20.0])


# A name with no versions frame keeps the stored facts frame path.
def test_name_without_versions_falls_back_to_the_facts_frame():
    facts = (
        edgar.QuarterFact(
            "revenue", date(2017, 1, 1), date(2017, 3, 31), 100.0, date(2017, 5, 1)
        ),
    )
    record = edgar.CompanyRecord(SYMBOL, 0, (), facts, STAMP)
    panel = make_panel(["2017-04-28", "2017-05-02"])
    out = levels_pit.point_in_time_levels(VersionStore(None, record=record), panel)
    np.testing.assert_array_equal(out["revenue"][:, 0], [np.nan, 400.0])
    assert np.isnan(out["revenue"][:, 1]).all()
