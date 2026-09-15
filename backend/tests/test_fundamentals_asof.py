"""The as-of fundamental selector.

What has to hold: a filing made later cannot change any feature on a
session before it was available; a restatement changes the level from its
availability on; a filing with a date but no time is available the next
day, one accepted before the close the same day, one accepted after the
close the next day; the tag is chosen from the periods available at the
session, so a later quarter under a competing tag cannot rewrite earlier
sessions; duplicate periods resolve to the reported quarter and the
latest available filing; and a frame round-trips.
"""

from datetime import date, datetime

import numpy as np

from backend.market import fundamentals_asof as fa


def row(start, end, val, filed, accn="a", form="10-Q", accepted=None):
    out = {
        "start": start,
        "end": end,
        "val": val,
        "filed": filed,
        "accn": accn,
        "form": form,
    }
    if accepted:
        out["accepted"] = accepted
    return out


def payload(**tags):
    return {
        "facts": {
            "us-gaap": {tag: {"units": {"USD": rows}} for tag, rows in tags.items()}
        }
    }


QUARTERS = [
    row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
    row("2025-04-01", "2025-06-30", 110, "2025-08-01", "q2"),
    row("2025-07-01", "2025-09-30", 120, "2025-11-01", "q3"),
    row("2025-10-01", "2025-12-31", 130, "2026-02-15", "q4"),
]


def sessions(*days):
    return np.array(days, dtype="datetime64[D]")


def revenue(versions, days):
    return fa.levels_for(versions, sessions(*days))["revenue"]


def test_a_later_filing_cannot_change_an_earlier_feature():
    base = fa.parse_versions(payload(Revenues=QUARTERS))
    restated = fa.parse_versions(
        payload(
            Revenues=QUARTERS
            + [row("2025-04-01", "2025-06-30", 999, "2026-03-01", "q2a", "10-K/A")]
        )
    )
    days = ["2026-02-16", "2026-02-20", "2026-03-01", "2026-03-02", "2026-03-10"]
    before, after = revenue(base, days), revenue(restated, days)
    # Every session before the restatement's availability (03-02) is identical.
    assert np.array_equal(before[:3], after[:3])
    assert before[0] == 460.0
    # From its availability on, the trailing sum carries the restated quarter.
    assert after[3] == 100 + 999 + 120 + 130
    assert after[4] == after[3]
    assert before[3] == 460.0


def test_availability_rule_next_day_without_a_time_same_day_before_the_close():
    dated = fa.parse_versions(payload(Revenues=QUARTERS))
    # Filed 2026-02-15 with no time: not usable that day, usable the next.
    assert np.isnan(revenue(dated, ["2026-02-15"])[0])
    assert revenue(dated, ["2026-02-16"])[0] == 460.0
    early = QUARTERS[:3] + [
        row(
            "2025-10-01",
            "2025-12-31",
            130,
            "2026-02-15",
            "q4",
            accepted="2026-02-15T14:00:00Z",
        )
    ]
    late = QUARTERS[:3] + [
        row(
            "2025-10-01",
            "2025-12-31",
            130,
            "2026-02-15",
            "q4",
            accepted="2026-02-15T21:30:00Z",
        )
    ]
    # 14:00 UTC is 09:00 New York: public that session. 21:30 UTC is 16:30: the next.
    assert (
        revenue(fa.parse_versions(payload(Revenues=early)), ["2026-02-15"])[0] == 460.0
    )
    assert np.isnan(
        revenue(fa.parse_versions(payload(Revenues=late)), ["2026-02-15"])[0]
    )
    assert (
        revenue(fa.parse_versions(payload(Revenues=late)), ["2026-02-16"])[0] == 460.0
    )


def test_tag_choice_uses_only_periods_available_at_the_session():
    other = [
        row(r["start"], r["end"], r["val"] + 1, r["filed"], r["accn"] + "b")
        for r in QUARTERS
    ]
    grown = other + [row("2026-01-01", "2026-03-31", 141, "2026-05-01", "q5b")]
    same = fa.parse_versions(
        payload(
            Revenues=QUARTERS, RevenueFromContractWithCustomerExcludingAssessedTax=other
        )
    )
    switched = fa.parse_versions(
        payload(
            Revenues=QUARTERS, RevenueFromContractWithCustomerExcludingAssessedTax=grown
        )
    )
    days = ["2026-02-16", "2026-04-30", "2026-05-02"]
    a, b = revenue(same, days), revenue(switched, days)
    # Tied counts before 05-02: the table's first tag wins in both snapshots,
    # and the later fifth quarter under the second tag changes nothing earlier.
    assert a[0] == 460.0
    assert b[0] == 460.0
    assert a[1] == 460.0
    assert b[1] == 460.0
    # From its availability the second tag has more periods and is chosen.
    assert b[2] == 111 + 121 + 131 + 141
    assert a[2] == 460.0


def test_duplicate_periods_resolve_to_the_reported_quarter_and_latest_filing():
    same_span_twice = QUARTERS + [
        row("2025-04-01", "2025-06-30", 115, "2025-08-20", "q2b")
    ]
    v = fa.parse_versions(payload(Revenues=same_span_twice))
    # Both filings are kept as versions.
    assert sum(1 for x in v if x.end == date(2025, 6, 30)) == 2
    days = ["2025-08-10", "2025-08-21", "2026-02-16"]
    r = revenue(v, days)
    assert np.isnan(r[0])  # fewer than four quarters known
    assert np.isnan(r[1])
    assert r[2] == 100 + 115 + 120 + 130  # the latest available filing of Q2
    # A year-to-date span ending on the same date as a reported quarter does
    # not displace it, and a fourth quarter is derived from the year.
    ytd = [row("2025-01-01", "2025-06-30", 205, "2025-08-01", "h1")]
    year = [row("2025-01-01", "2025-12-31", 470, "2026-02-15", "fy")]
    v2 = fa.parse_versions(payload(Revenues=QUARTERS[:3] + ytd + year))
    assert revenue(v2, ["2026-02-16"])[0] == 100 + 110 + 120 + (470 - 330)


def test_frame_round_trips_and_keeps_acceptance():
    v = fa.parse_versions(
        payload(
            Revenues=[
                row(
                    "2025-01-01",
                    "2025-03-31",
                    100,
                    "2025-05-01",
                    "q1",
                    accepted="2025-05-01T21:00:00Z",
                )
            ]
        )
    )
    back = fa.versions_from_frame(fa.frame(v))
    assert back == v
    assert back[0].accepted == datetime.fromisoformat("2025-05-01T21:00:00+00:00")
    assert back[0].available == date(2025, 5, 2)


def test_instants_take_the_latest_available_end_from_the_richest_tag():
    p = {
        "facts": {
            "us-gaap": {
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {
                                "end": "2025-03-31",
                                "val": 10,
                                "filed": "2025-05-01",
                                "accn": "a",
                            },
                            {
                                "end": "2025-06-30",
                                "val": 12,
                                "filed": "2025-08-01",
                                "accn": "b",
                            },
                            {
                                "end": "2025-06-30",
                                "val": 13,
                                "filed": "2025-09-01",
                                "accn": "c",
                            },
                        ]
                    }
                }
            }
        }
    }
    v = fa.parse_versions(p)
    eq = fa.levels_for(v, sessions("2025-05-02", "2025-08-02", "2025-09-02"))["equity"]
    assert eq.tolist() == [10.0, 12.0, 13.0]
