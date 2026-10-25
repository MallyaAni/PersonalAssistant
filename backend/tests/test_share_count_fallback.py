"""The valuation share count: the weighted-average diluted count as a fallback.

What has to hold: the versions store keeps the weighted-average counts under
their own name (durations), so the instant "shares" readers are untouched; the
valuation levels (`levels_pit.versions_levels`) read a current cover-page
count exactly as before, and the latest weighted count only when it is later
than every cover / balance-sheet count (a multi-class filer with none, one
whose cover count stopped years ago); a count below `MIN_SHARES` or more
than `MAX_IMPLIED_RATIO` away from net income over diluted EPS (on one split
basis) is skipped for the next ranked tag; the switch happens on the filing
date (the day after under strict publication) and cutting the filings at
any date never changes an earlier session; later splits still multiply the
count; the frozen `edgar.parse_company_facts` does not read the new tags.
"""

import hashlib
import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.market import edgar, levels_pit
from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa
from backend.market.panel import Panel
from backend.market.yahoo import CorporateAction, TickerHistory

COVER = "dei:EntityCommonStockSharesOutstanding"
BALANCE = "us-gaap:CommonStockSharesOutstanding"
DILUTED = "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"
NIL = "us-gaap:NetIncomeLoss"
EPS = "us-gaap:EarningsPerShareDiluted"
W = edgar.WEIGHTED_SHARES_NAME
M = 1e6
SYMBOL = "SYNTH"

Q = [
    ("2024-01-01", "2024-03-31", "2024-05-01"),
    ("2024-04-01", "2024-06-30", "2024-08-01"),
    ("2024-07-01", "2024-09-30", "2024-11-01"),
]


def v(name, tag, start, end, value, filed, accession=None):
    return fa.Version(
        name,
        tag,
        None if start is None else date.fromisoformat(start),
        date.fromisoformat(end),
        float(value),
        date.fromisoformat(filed),
        None,
        accession or f"acc-{filed}",
        "10-Q",
    )


def days(*values):
    return np.array(values, dtype="datetime64[D]")


# A multi-class filer: no undimensioned cover count, an old one from 2010,
# and per-quarter diluted weighted counts, net income and diluted EPS.
def multiclass(old_cover=True):
    out = [v("shares", COVER, None, "2010-03-19", 600 * M, "2010-03-26")] if old_cover else []
    for i, (s, e, f) in enumerate(Q):
        out.append(v(W, DILUTED, s, e, (250 + i) * M, f))
        out.append(v("net_income", NIL, s, e, (500 + 10 * i) * M, f))
        out.append(v("eps", EPS, s, e, (500 + 10 * i) / (250 + i), f))
    return out


def shares(versions, sessions, **kw):
    return levels_pit.versions_levels(versions, sessions, **kw)["shares"]


def test_the_store_keeps_weighted_counts_under_their_own_name():
    rows = [{"start": "2024-01-01", "end": "2024-03-31", "val": 7e8, "filed": "2024-05-01", "accn": "x", "form": "10-Q"}]
    instant = [{"end": "2024-04-20", "val": 7e8, "filed": "2024-05-01", "accn": "x", "form": "10-Q"}]
    payload = {"facts": {"us-gaap": {
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": rows + instant}},
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted": {"units": {"shares": rows}},
        "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": rows}},
    }}}
    found = {(x.name, x.tag, x.start is None) for x in fa.parse_versions(payload)}
    assert found == {
        (W, DILUTED, False),
        (W, "us-gaap:WeightedAverageNumberOfShareOutstandingBasicAndDiluted", False),
    }


# The instant readers (`fundamentals_asof.levels_for`) never see them.
def test_instant_share_readers_are_untouched():
    sessions = days("2024-06-01", "2024-12-01")
    with_weighted = fa.levels_for(multiclass(), sessions)
    without = fa.levels_for([x for x in multiclass() if x.name != W], sessions)
    for name in with_weighted:
        np.testing.assert_array_equal(with_weighted[name], without[name])
    assert list(with_weighted["shares"]) == [600 * M, 600 * M]


def test_the_frozen_parser_does_not_read_weighted_counts():
    rows = [{"start": s, "end": e, "val": 3e8, "filed": f, "accn": f, "form": "10-Q"} for s, e, f in Q]
    payload = {"facts": {"us-gaap": {"WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": rows}}}}}
    assert not [f for f in edgar.parse_company_facts(payload) if f.name == "shares"]


# A stale 2010 cover count gives way to the first later weighted count from
# its filing date (the day after under strict publication); with no cover
# count at all nothing is known before it.
@pytest.mark.parametrize("old_cover", [True, False])
def test_a_multiclass_filer_reads_its_weighted_count(old_cover):
    sessions = days("2024-04-30", "2024-05-01", "2024-05-02", "2024-08-01", "2024-12-01")
    first = 600 * M if old_cover else np.nan
    latest, _back, source = shares(multiclass(old_cover), sessions)
    np.testing.assert_array_equal(latest, [first, 250 * M, 250 * M, 251 * M, 252 * M])
    assert source[1] == np.datetime64("2024-05-01")
    strict = shares(multiclass(old_cover), sessions, strict_publication=True)[0]
    np.testing.assert_array_equal(strict, [first, first, 250 * M, 250 * M, 252 * M])


# A current cover count (dated after the quarter's end) keeps exactly its
# reading; on the same date the instant tier beats the weighted tier.
def test_a_current_cover_count_keeps_its_reading():
    versions = multiclass(False)
    for s, e, f in Q:
        cover = (np.datetime64(e) + np.timedelta64(20, "D")).astype(str)
        versions.append(v("shares", COVER, None, cover, 240 * M, f))
    latest = shares(versions, days("2024-06-01", "2024-12-01"))[0]
    np.testing.assert_array_equal(latest, [240 * M, 240 * M])
    same_end = multiclass(False) + [v("shares", BALANCE, None, e, 245 * M, f) for s, e, f in Q]
    assert list(shares(same_end, days("2024-12-01"))[0]) == [245 * M]


# Placeholders and units slips are skipped for the next ranked tag: SPG's
# 8,000, a cover count of 1, a weighted count filed in thousands or in
# millions, and a count ten times the implied one; none plausible: unknown.
@pytest.mark.parametrize(
    "bad",
    [
        v("shares", BALANCE, None, "2024-10-30", 8000, "2024-11-01"),
        v("shares", COVER, None, "2024-10-30", 1, "2024-11-01"),
        v("shares", COVER, None, "2024-10-30", 2600 * M, "2024-11-01"),
        v("shares", COVER, None, "2024-10-30", 20 * M, "2024-11-01"),
    ],
)
def test_implausible_counts_fall_to_the_next_tag(bad):
    latest = shares(multiclass(False) + [bad], days("2024-12-01"))[0]
    assert list(latest) == [252 * M]


def test_a_weighted_count_in_the_wrong_unit_is_skipped():
    versions = [x for x in multiclass() if not (x.name == W and x.end == date(2024, 9, 30))]
    versions.append(v(W, DILUTED, "2024-07-01", "2024-09-30", 252.0, "2024-11-01"))  # in millions
    latest = shares(versions, days("2024-10-01", "2024-12-01"))[0]
    # Q2's count until Q3's slip is public, then the next ranked tag that passes.
    assert list(latest) == [251 * M, 600 * M]
    assert np.isnan(shares(versions[1:], days("2024-12-01"))[0][0])


# The implied count is put on the later filing's split basis: a 50:1 split
# between the EPS filing and the cover filing is not read as a units slip.
def test_the_check_puts_both_counts_on_one_split_basis():
    versions = multiclass(False)
    versions.append(v("shares", COVER, None, "2024-12-20", 252 * 50 * M, "2025-01-05"))
    split = [(date(2024, 12, 1), 50.0)]
    assert list(shares(versions, days("2025-01-06"), splits=split)[0]) == [252 * 50 * M]
    assert list(shares(versions, days("2025-01-06"))[0]) == [252 * M]


# Among the spans filed together for one period end, the shortest wins.
def test_the_quarter_beats_the_year_to_date_span():
    versions = multiclass(False) + [v(W, DILUTED, "2024-01-01", "2024-09-30", 245 * M, Q[2][2])]
    assert list(shares(versions, days("2024-12-01"))[0]) == [252 * M]


@pytest.mark.parametrize("cut", ["2010-03-26", "2024-04-30", "2024-05-01", "2024-08-01", "2024-10-31"])
@pytest.mark.parametrize("strict", [False, True])
def test_truncated_filings_reproduce_every_earlier_session(cut, strict):
    sessions = np.arange(np.datetime64("2024-01-01"), np.datetime64("2025-01-01"))
    versions = multiclass() + [v("shares", BALANCE, None, "2024-06-30", 8000, "2024-08-01")]
    split = [(date(2024, 7, 15), 2.0)]
    full = levels_pit.versions_levels(versions, sessions, strict_publication=strict, splits=split)
    limit = date.fromisoformat(cut)
    part = levels_pit.versions_levels(
        [x for x in versions if x.filed <= limit], sessions, strict_publication=strict, splits=split
    )
    upto = sessions <= np.datetime64(cut)
    for name in full:
        for a, b in zip(full[name], part[name], strict=True):
            np.testing.assert_array_equal(a[upto], b[upto])


class _Store:
    def __init__(self, versions, actions=()):
        self.versions, self.actions = versions, actions

    def read_frame(self, kind, ticker, asof=None):
        return (fa.frame(self.versions), {}) if ticker == SYMBOL and kind == fa.KIND else None

    def read(self, ticker, asof=None):
        stamp = datetime(2025, 1, 2, tzinfo=UTC)
        return TickerHistory(SYMBOL, (), self.actions, stamp.date(), stamp, "fixture")


# A weighted count carries every later split through the panel, as the
# cover count does (strict publication: from its filing date's basis).
def test_point_in_time_levels_split_adjust_the_weighted_count():
    sessions = days("2024-06-01", "2024-09-01", "2024-12-01")
    close = np.full((3, 2), 100.0)
    panel = Panel(sessions, (SYMBOL, "SPY"), close, close, close, close, close,
                  np.full_like(close, 1000.0), {}, "SPY")  # fmt: skip
    store = _Store(multiclass(False), (CorporateAction(date(2024, 10, 1), "split", 2.0),))
    for strict in (False, True):
        out = levels_pit.point_in_time_levels(store, panel, strict_publication=strict)
        np.testing.assert_array_equal(out["shares"][:, 0], [500 * M, 502 * M, 252 * M])


def test_unit_sources_project_weighted_counts_in_shares():
    rows = [{"start": "2025-01-01", "end": "2025-03-31", "val": 7e8, "filed": "2025-05-01", "accn": "1", "form": "10-Q"}]
    payload = {"cik": 1, "facts": {"us-gaap": {
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": rows, "USD": rows}}}}}
    body = json.dumps(payload).encode()
    source = units.parse(body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1)
    projection = units.project(source)
    assert {(f.version.name, f.unit) for f in projection.accepted_facts} == {(W, "shares")}
