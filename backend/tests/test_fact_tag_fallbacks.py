"""Fallback revenue and net-income tags (edgar.FALLBACK_FACT_TAGS).

What has to hold: the versions store keeps the fallback tags (us-gaap only);
a fallback tag is chosen on a session only when its latest quarter is later
than that of every better-tier tag, so a filer still reporting under a
`FACT_TAGS` tag keeps exactly its reading even when the fallback has more
periods; between fallbacks the better tier wins on the same end; the switch
happens only from the session the fallback's filing is available, and
cutting the filings at any date never changes an earlier session; the
frozen `edgar.parse_company_facts` does not read the fallbacks.
"""

from datetime import date

import numpy as np
import pytest

from backend.market import edgar, levels_pit
from backend.market import fundamentals_asof as fa

NIL = "us-gaap:NetIncomeLoss"
COMMON = "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic"
PROFIT = "us-gaap:ProfitLoss"
REV = "us-gaap:Revenues"
BANK = "us-gaap:RevenuesNetOfInterestExpense"
SERVICES = "us-gaap:SalesRevenueServicesNet"

Q = [
    ("2023-01-01", "2023-03-31", "2023-05-01"),
    ("2023-04-01", "2023-06-30", "2023-08-01"),
    ("2023-07-01", "2023-09-30", "2023-11-01"),
    ("2023-10-01", "2023-12-31", "2024-02-15"),
    ("2024-01-01", "2024-03-31", "2024-05-01"),
    ("2024-04-01", "2024-06-30", "2024-08-01"),
    ("2024-07-01", "2024-09-30", "2024-11-05"),
    ("2024-10-01", "2024-12-31", "2025-02-14"),
]


def version(name, tag, start, end, value, filed):
    return fa.Version(
        name,
        tag,
        date.fromisoformat(start),
        date.fromisoformat(end),
        float(value),
        date.fromisoformat(filed),
        None,
        f"{tag}-{filed}",
        "10-Q",
    )


# AVGO / AEP shape: NetIncomeLoss through mid-2024, then only the fallback;
# ProfitLoss reported alongside throughout, with more periods.
def stopped_versions():
    out = []
    for i, (s, e, f) in enumerate(Q):
        if i < 6:
            out.append(version("net_income", NIL, s, e, 10 + i, f))
        out.append(version("net_income", PROFIT, s, e, 11 + i, f))
        if i >= 4:
            out.append(version("net_income", COMMON, s, e, 9 + i, f))
    # A quarter of 2022 under ProfitLoss only: ProfitLoss has more periods.
    out.append(version("net_income", PROFIT, "2022-10-01", "2022-12-31", 5, "2023-02-15"))
    return out


def sessions(*days):
    return np.array(days, dtype="datetime64[D]")


def chosen(versions, days, name="net_income"):
    trace = {}
    fa.levels_for(versions, sessions(*days), trace)
    return trace[name]


def test_the_versions_store_keeps_fallback_tags_us_gaap_only():
    rows = [{"start": "2024-01-01", "end": "2024-03-31", "val": 7, "filed": "2024-05-01", "accn": "x", "form": "10-Q"}]
    payload = {
        "facts": {
            "us-gaap": {"ProfitLoss": {"units": {"USD": rows}}, "RevenuesNetOfInterestExpense": {"units": {"USD": rows}}},
            "ifrs-full": {"ProfitLoss": {"units": {"USD": rows}}},
        }
    }
    tags = {(v.name, v.tag) for v in fa.parse_versions(payload)}
    assert tags == {("net_income", PROFIT), ("revenue", BANK)}


def test_tiers_follow_the_table():
    tiers = fa._tag_tiers("net_income")
    assert tiers[NIL] == 0 and tiers[COMMON] == 1 and tiers[PROFIT] == 2
    assert fa._tag_tiers("revenue")[BANK] == 1
    assert fa._tag_tiers("revenue")[SERVICES] == 2
    assert all(t == 0 for t in fa._tag_tiers("equity").values())
    assert fa._tag_order("net_income")[0] == NIL


# While NetIncomeLoss is current it is read, though ProfitLoss has more
# periods; once it stops, the parent's income available to common is read
# (not ProfitLoss), from the session its filing is available (the day after
# a filing date without an acceptance time, `Version.available`).
def test_a_fallback_wins_only_with_a_later_quarter():
    v = stopped_versions()
    days = ["2024-08-02", "2024-11-05", "2024-11-06", "2025-02-15"]
    assert chosen(v, days) == [NIL, NIL, COMMON, COMMON]


def test_profit_including_noncontrolling_interest_is_the_last_resort():
    v = [x for x in stopped_versions() if x.tag != COMMON]
    assert chosen(v, ["2024-08-02", "2024-11-06"]) == [NIL, PROFIT]


def test_revenue_tiers_on_the_same_end():
    v = []
    for i, (s, e, f) in enumerate(Q[:4]):
        v.append(version("revenue", BANK, s, e, 100 + i, f))
        v.append(version("revenue", SERVICES, s, e, 10 + i, f))
    v.append(version("revenue", SERVICES, "2022-10-01", "2022-12-31", 9, "2023-02-15"))
    assert chosen(v, ["2024-02-16"], "revenue") == [BANK]
    out = fa.levels_for(v, sessions("2024-02-16"))
    assert out["revenue"][0] == 100 + 101 + 102 + 103


# The valuation levels read the same tiers, from the filing date on.
def test_valuation_levels_switch_on_the_filing_date():
    days = sessions("2024-08-02", "2024-11-04", "2024-11-05")
    out = levels_pit.versions_levels(stopped_versions(), days)
    latest = out["net_income"][0]
    assert list(latest) == [15.0, 15.0, 15.0]  # NIL Q2 2024, then COMMON Q3 (9 + 6)
    out = levels_pit.versions_levels([x for x in stopped_versions() if x.tag != COMMON], days)
    assert list(out["net_income"][0]) == [15.0, 15.0, 17.0]
    assert out["net_income"][1][2] == 13.0  # four quarters back, same tag


@pytest.mark.parametrize("cut", ["2024-08-01", "2024-11-04", "2024-11-05", "2025-02-13"])
@pytest.mark.parametrize("strict", [False, True])
def test_truncated_filings_reproduce_every_earlier_session(cut, strict):
    days = np.arange(np.datetime64("2023-04-01"), np.datetime64("2025-03-01"))
    full = levels_pit.versions_levels(stopped_versions(), days, strict_publication=strict)
    limit = date.fromisoformat(cut)
    part = levels_pit.versions_levels(
        [v for v in stopped_versions() if v.filed <= limit], days, strict_publication=strict
    )
    upto = days <= np.datetime64(cut)
    for name in full:
        for a, b in zip(full[name], part[name], strict=True):
            np.testing.assert_array_equal(a[upto], b[upto])
    fl = fa.levels_for(stopped_versions(), days)
    pl = fa.levels_for([v for v in stopped_versions() if v.available <= limit], days)
    for name in fl:
        np.testing.assert_array_equal(fl[name][upto], pl[name][upto])


# The frozen whole-history parser keeps reading FACT_TAGS only.
def test_frozen_parser_does_not_read_fallbacks():
    rows = [{"start": s, "end": e, "val": 1, "filed": f, "accn": f, "form": "10-Q"} for s, e, f in Q]
    payload = {"facts": {"us-gaap": {"ProfitLoss": {"units": {"USD": rows}}}}}
    assert not [f for f in edgar.parse_company_facts(payload) if f.name == "net_income"]
