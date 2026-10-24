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
import pytest

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


def _panel(days, closes):
    from backend.market.panel import Panel

    n = len(closes[0])
    close = np.array(closes, dtype=float)
    return Panel(
        dates=sessions(*days),
        tickers=tuple(f"N{i}" for i in range(n)),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full(close.shape, 1000.0),
        themes={},
        benchmark=f"N{n - 1}",
    )


# The whole path: versions -> as-of levels -> the ratio columns the model
# reads, against arithmetic done by hand, including a fourth quarter derived
# from the year and a second quarter derived from a six-month span.
def test_feature_path_matches_hand_calculation():
    from backend.market import opportunity_learning as ol

    rows = {
        "Revenues": [
            row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
            row("2025-01-01", "2025-06-30", 230, "2025-08-01", "h1"),  # Q2 = 130
            row("2025-07-01", "2025-09-30", 120, "2025-11-01", "q3"),
            row("2025-01-01", "2025-12-31", 500, "2026-02-15", "fy"),  # Q4 = 150
        ],
        "NetIncomeLoss": [
            row("2025-01-01", "2025-03-31", 10, "2025-05-01", "q1"),
            row("2025-04-01", "2025-06-30", 12, "2025-08-01", "q2"),
            row("2025-07-01", "2025-09-30", 14, "2025-11-01", "q3"),
            row("2025-10-01", "2025-12-31", 16, "2026-02-15", "q4"),
        ],
        "GrossProfit": [
            row("2025-01-01", "2025-03-31", 60, "2025-05-01", "q1"),
            row("2025-04-01", "2025-06-30", 60, "2025-08-01", "q2"),
            row("2025-07-01", "2025-09-30", 60, "2025-11-01", "q3"),
            row("2025-10-01", "2025-12-31", 60, "2026-02-15", "q4"),
        ],
        "NetCashProvidedByUsedInOperatingActivities": [
            row("2025-01-01", "2025-03-31", 20, "2025-05-01", "q1"),
            row("2025-01-01", "2025-06-30", 45, "2025-08-01", "h1"),  # Q2 = 25
            row("2025-01-01", "2025-09-30", 75, "2025-11-01", "m9"),  # Q3 = 30
            row("2025-01-01", "2025-12-31", 110, "2026-02-15", "fy"),  # Q4 = 35
        ],
        "StockholdersEquity": [
            {"end": "2025-12-31", "val": 400, "filed": "2026-02-15", "accn": "fy"}
        ],
        "CommonStockSharesOutstanding": [
            {"end": "2025-12-31", "val": 50, "filed": "2026-02-15", "accn": "fy"}
        ],
        "CashAndCashEquivalentsAtCarryingValue": [
            {"end": "2025-12-31", "val": 80, "filed": "2026-02-15", "accn": "fy"}
        ],
        "LongTermDebtNoncurrent": [
            {"end": "2025-12-31", "val": 120, "filed": "2026-02-15", "accn": "fy"}
        ],
    }
    versions = fa.parse_versions(payload(**rows))
    days = ["2026-02-13", "2026-02-16", "2026-02-17"]
    panel = _panel(days, [[40.0, 1.0], [40.0, 1.0], [50.0, 1.0]])
    data, values, names = fa.features(panel, {"N0": versions})
    col = {name: i for i, name in enumerate(names)}
    # Before the 02-15 filing's availability the year is not complete.
    assert np.isnan(values[0, 0, col["log_sales_yield"]])
    # On 02-16: revenue 100 + 130 + 120 + 150 = 500; cap = 40 * 50 = 2000.
    assert values[1, 0, col["log_sales_yield"]] == np.log(500 / 2000)
    assert values[1, 0, col["earnings_yield"]] == (10 + 12 + 14 + 16) / 2000
    assert values[1, 0, col["book_yield"]] == 400 / 2000
    assert values[1, 0, col["cash_flow_yield"]] == (20 + 25 + 30 + 35) / 2000
    assert values[1, 0, col["net_margin"]] == 52 / 500
    assert values[1, 0, col["gross_margin"]] == 240 / 500
    assert values[1, 0, col["cash_flow_margin"]] == 110 / 500
    assert values[1, 0, col["cash_to_cap"]] == 80 / 2000
    assert values[1, 0, col["debt_to_cap"]] == 120 / 2000
    # The next day at 50: the same levels over a larger capitalisation.
    assert values[2, 0, col["log_sales_yield"]] == np.log(500 / 2500)
    # Fewer than 252 sessions: no year-over-year growth yet.
    assert np.isnan(values[1, 0, col["revenue_growth"]])
    # The price block is the research dataset's own, unchanged.
    assert names[: len(fa.gp.FEATURE_NAMES)] == fa.gp.FEATURE_NAMES
    assert names[len(fa.gp.FEATURE_NAMES) :] == ol.FUNDAMENTAL_NAMES


# The research training CLI reads the as-of selector when asked, from the
# stored versions, and fingerprints the versions it read.
def test_training_cli_consumes_the_selector_from_the_store(tmp_path):
    # The training CLI needs the research dependencies; the gate container
    # has none of them, and this test is about the selector, not the model.
    pytest.importorskip("joblib")
    pytest.importorskip("sklearn")
    pytest.importorskip("torch")
    from backend.cli import market_opportunity_learning as cli
    from backend.market.store import MarketStore

    versions = fa.parse_versions(payload(Revenues=QUARTERS))
    store = MarketStore(tmp_path)
    store.write_frame(fa.KIND, date(2026, 3, 1), "N0", fa.frame(versions), {})
    days = ["2026-02-16", "2026-02-17"]
    panel = _panel(days, [[40.0, 1.0], [41.0, 1.0]])
    data, raw, names, digest = cli.features_for(panel, store, date(2026, 3, 1), "asof")
    assert len(digest) == 64
    assert names == (*fa.gp.FEATURE_NAMES, *fa.ol.FUNDAMENTAL_NAMES)
    # Revenue is known (460) but shares are not: sales yield stays missing,
    # which is the explicit-missingness rule, not a crash.
    assert np.isnan(raw[0, 0, names.index("log_sales_yield")])
    frozen = cli.features_for(panel, store, date(2026, 3, 1), "frozen")
    assert frozen[3] is None


# ---- revenue tag switches (ASC 606): the current tag, not the longest one


def _switch_payload():
    old = [
        row(f"{y}-{m1}", f"{y}-{m2}", v, f"{y}-{f}", f"o{y}{m2}")
        for y, base in ((2016, 100), (2017, 110))
        for (m1, m2, f), v in zip(
            (("01-01", "03-31", "05-01"), ("04-01", "06-30", "08-01"),
             ("07-01", "09-30", "11-01")),
            (base, base + 1, base + 2),
        )
    ] + [
        row("2016-10-01", "2016-12-31", 103, "2017-02-15", "o16q4"),
        row("2017-10-01", "2017-12-31", 113, "2018-02-15", "o17q4"),
    ]
    # Each new-tag 10-Q carries its prior-year comparative under the new tag,
    # restated (the old tag said 110, 111, 112 for 2017).
    new = []
    for (m1, m2, f), cur, prior in zip(
        (("01-01", "03-31", "05-01"), ("04-01", "06-30", "08-01"),
         ("07-01", "09-30", "11-01")),
        (120, 121, 122),
        (109, 110, 111),
    ):
        accn = f"n18{m2}"
        new.append(row(f"2018-{m1}", f"2018-{m2}", cur, f"2018-{f}", accn))
        new.append(row(f"2017-{m1}", f"2017-{m2}", prior, f"2018-{f}", accn))
    new.append(row("2018-01-01", "2018-12-31", 486, "2019-02-15", "n18k", "10-K"))
    new.append(row("2017-01-01", "2017-12-31", 442, "2019-02-15", "n18k", "10-K"))
    return payload(
        Revenues=old, RevenueFromContractWithCustomerExcludingAssessedTax=new
    )


def test_a_tag_the_filer_stopped_using_does_not_outlive_its_successor():
    v = fa.parse_versions(_switch_payload())
    days = ["2018-04-30", "2018-05-02", "2018-11-02", "2019-02-16"]
    trace = {}
    r = fa.levels_for(v, sessions(*days), trace)["revenue"]
    new = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    # The old tag has more periods throughout; it is read only until the
    # new tag reports a later quarter.
    assert trace["revenue"] == ["us-gaap:Revenues", new, new, new]
    assert r[0] == 110 + 111 + 112 + 113
    # One new quarter and its comparative: no four consecutive quarters under
    # the new tag, so the trailing sum is missing, never mixed with the old tag.
    assert np.isnan(r[1])
    assert np.isnan(r[2])
    # The 10-K completes both years under the new tag (fourth quarters from
    # the annual figures).
    assert r[3] == 486.0


def test_tag_switch_never_changes_an_earlier_session():
    v = fa.parse_versions(_switch_payload())
    days = sessions(*[f"20{y}-{m}-15" for y in (16, 17, 18, 19) for m in ("02", "05", "08", "11")])
    full = fa.levels_for(v, days)
    for cut in (date(2018, 2, 16), date(2018, 5, 1), date(2018, 8, 2), date(2019, 2, 15)):
        part = fa.levels_for([x for x in v if x.available <= cut], days)
        keep = days <= np.datetime64(cut)
        for name, series in full.items():
            np.testing.assert_array_equal(series[keep], part[name][keep])


def test_an_inconsistently_dated_period_cannot_steer_the_tag():
    bogus = [row("2026-01-01", "2026-03-31", 999, "2026-02-16", "x")]  # ends after filing
    v = fa.parse_versions(
        payload(
            Revenues=QUARTERS,
            RevenueFromContractWithCustomerExcludingAssessedTax=bogus,
        )
    )
    trace = {}
    r = fa.levels_for(v, sessions("2026-02-17"), trace)["revenue"]
    assert trace["revenue"] == ["us-gaap:Revenues"]
    assert r[0] == 460.0


def test_an_instant_switch_reads_the_tag_still_reported():
    def inst(tag, rows):
        return {tag: {"units": {"USD": rows}}}

    old = [
        {"end": e, "val": 10, "filed": f, "accn": e}
        for e, f in (("2017-03-31", "2017-05-01"), ("2017-06-30", "2017-08-01"),
                     ("2017-09-30", "2017-11-01"), ("2017-12-31", "2018-02-15"))
    ]
    new = [{"end": "2018-03-31", "val": 20, "filed": "2018-05-01", "accn": "n"}]
    v = fa.parse_versions(
        {"facts": {"us-gaap": {**inst("LongTermDebtNoncurrent", old), **inst("LongTermDebt", new)}}}
    )
    debt = fa.levels_for(v, sessions("2018-04-30", "2018-05-02"))["debt"]
    assert debt.tolist() == [10.0, 20.0]
