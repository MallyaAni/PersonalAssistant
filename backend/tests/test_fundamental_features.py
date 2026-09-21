"""The point-in-time quarterly fundamental feature adapter.

The first test reproduces the frozen path's missingness defect on one
panel row: revenue is known, so `has_fundamentals` is set, but a ratio that
was never filed was zero-filled by `edgar.edgar_features` and the
fundamental analyst reads that fabricated zero as a valid input. The
remaining tests pin the adapter's corrections: a later filing or a new tag
cannot change any earlier feature (checked on the feature tensor); a
restatement changes only the features it affects and only from its
availability on, after-close and date-only alike; missing lagged quarters
and zero denominators are NaN while a genuine zero stays zero; every ratio
compares the same fiscal period; tag ties are deterministic and nothing is
filled from the future; and one end-to-end panel run proves shape, names,
coverage and hand-computed values including a derived cash-flow quarter.
"""

from datetime import UTC, date, datetime

import numpy as np

from backend.market import fundamental_features as ff
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


def sessions(*days):
    return np.array(days, dtype="datetime64[D]")


def panel(days, closes):
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


QUARTERS = [
    row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
    row("2025-04-01", "2025-06-30", 110, "2025-08-01", "q2"),
    row("2025-07-01", "2025-09-30", 120, "2025-11-01", "q3"),
    row("2025-10-01", "2025-12-31", 130, "2026-02-15", "q4"),
]

PRIOR = [
    row("2024-01-01", "2024-03-31", 90, "2024-05-01", "p1"),
    row("2024-04-01", "2024-06-30", 95, "2024-08-01", "p2"),
    row("2024-07-01", "2024-09-30", 100, "2024-11-01", "p3"),
    row("2024-10-01", "2024-12-31", 105, "2025-02-15", "p4"),
]

# Eight consecutive quarters (2024 + 2025) so year-over-year and sequential
# growth are both computable at a 2026 session.
EIGHT = PRIOR + QUARTERS


# The frozen path zero-fills a ratio that was never filed, and the analyst
# then reads that zero as valid because revenue is known; the adapter keeps
# the missing ratio NaN on the same underlying data.
def test_reproduces_legacy_zero_fill_of_a_missing_ratio():
    from backend.agents.trading.desk.fundamental import opine
    from backend.market import edgar
    from backend.market.edgar import CompanyRecord, QuarterFact

    days = ["2026-02-16", "2026-02-17"]
    p = panel(days, [[40.0, 1.0], [40.0, 1.0]])
    facts = (
        QuarterFact(
            "revenue", date(2025, 1, 1), date(2025, 3, 31), 100.0, date(2025, 5, 1)
        ),
        QuarterFact(
            "revenue", date(2025, 4, 1), date(2025, 6, 30), 110.0, date(2025, 8, 1)
        ),
        QuarterFact(
            "revenue", date(2025, 7, 1), date(2025, 9, 30), 120.0, date(2025, 11, 1)
        ),
        QuarterFact(
            "revenue", date(2025, 10, 1), date(2025, 12, 31), 130.0, date(2026, 2, 15)
        ),
        QuarterFact(
            "net_income", date(2025, 1, 1), date(2025, 3, 31), 10.0, date(2025, 5, 1)
        ),
        QuarterFact(
            "net_income", date(2025, 4, 1), date(2025, 6, 30), 12.0, date(2025, 8, 1)
        ),
        QuarterFact(
            "net_income", date(2025, 7, 1), date(2025, 9, 30), 14.0, date(2025, 11, 1)
        ),
        QuarterFact(
            "net_income", date(2025, 10, 1), date(2025, 12, 31), 16.0, date(2026, 2, 15)
        ),
        # gross profit is never filed: gross_margin is genuinely missing.
    )
    record = CompanyRecord("N0", 0, (), facts, datetime(2026, 2, 16, tzinfo=UTC))
    extra = edgar.edgar_features(p, {"N0": record})
    names = edgar.FEATURE_NAMES
    has = extra[0, 0, names.index("has_fundamentals")]
    gross = extra[0, 0, names.index("gross_margin")]
    # Revenue is known, so the analyst is told fundamentals exist...
    assert has == 1.0
    # ...but the missing gross margin was replaced by a zero, not left missing.
    assert gross == 0.0
    # The fundamental analyst reads that fabricated zero as a valid input.
    assert opine(extra).evidence["gross_margin"][0, 0] == 0.0

    # The same underlying data through the adapter keeps the missing ratio NaN.
    versions = fa.parse_versions(
        payload(
            Revenues=QUARTERS,
            NetIncomeLoss=[
                row("2025-01-01", "2025-03-31", 10, "2025-05-01", "q1"),
                row("2025-04-01", "2025-06-30", 12, "2025-08-01", "q2"),
                row("2025-07-01", "2025-09-30", 14, "2025-11-01", "q3"),
                row("2025-10-01", "2025-12-31", 16, "2026-02-15", "q4"),
            ],
        )
    )
    out = ff.features(p, {"N0": versions})
    assert np.isnan(out.feature("gross_margin")[0, 0])


# A future restatement, a future quarter and a future competing tag, all
# available only after the last session, change no earlier feature, not even
# the tag-selection decision: checked on the whole feature tensor.
def test_appending_future_data_cannot_change_any_earlier_feature():
    base = fa.parse_versions(payload(Revenues=EIGHT))
    extended = fa.parse_versions(
        payload(
            Revenues=EIGHT
            + [
                row("2025-04-01", "2025-06-30", 999, "2026-06-01", "q2a", "10-Q/A"),
                row("2026-01-01", "2026-03-31", 160, "2026-06-01", "q1y"),
            ],
            RevenueFromContractWithCustomerExcludingAssessedTax=[
                row(r["start"], r["end"], r["val"] + 1, r["filed"], r["accn"] + "b")
                for r in EIGHT
            ]
            + [row("2026-01-01", "2026-03-31", 999, "2026-06-01", "q1yb")],
        )
    )
    days = ["2026-02-16", "2026-02-17", "2026-04-30"]
    p = panel(days, [[40.0, 1.0], [40.0, 1.0], [41.0, 1.0]])
    before = ff.features(p, {"N0": base})
    after = ff.features(p, {"N0": extended})
    # Every added version is available on 2026-06-02, after the last session.
    assert np.array_equal(before.values, after.values, equal_nan=True)
    assert np.array_equal(before.available, after.available)
    assert np.array_equal(before.staleness, after.staleness, equal_nan=True)


# When a competing tag acquires a fifth quarter, the switch happens only
# from that quarter's availability on; every earlier session is unchanged.
def test_tag_switch_rewrites_only_sessions_from_its_availability():
    other = [
        row(r["start"], r["end"], r["val"] + 1, r["filed"], r["accn"] + "b")
        for r in EIGHT
    ]
    grown = other + [row("2026-01-01", "2026-03-31", 141, "2026-05-01", "q5b")]
    same = fa.parse_versions(
        payload(
            Revenues=EIGHT, RevenueFromContractWithCustomerExcludingAssessedTax=other
        )
    )
    switched = fa.parse_versions(
        payload(
            Revenues=EIGHT, RevenueFromContractWithCustomerExcludingAssessedTax=grown
        )
    )
    days = ["2026-02-16", "2026-04-30", "2026-05-02"]
    p = panel(days, [[40.0, 1.0], [40.0, 1.0], [40.0, 1.0]])
    a = ff.features(p, {"N0": same})
    b = ff.features(p, {"N0": switched})
    # Tied counts before 05-02 keep the table's first tag in both snapshots.
    assert np.array_equal(a.values[0], b.values[0], equal_nan=True)
    assert np.array_equal(a.values[1], b.values[1], equal_nan=True)
    # On 05-02 the second tag has more quarters and is chosen: the yoy
    # comparison moves from Revenues' Q4 2025 (130) over its Q4 2024 (105)
    # to the second tag's Q1 2026 (141) over its Q1 2025 (101).
    assert np.isclose(b.feature("revenue_yoy")[2, 0], np.log(141 / 101))
    assert np.isclose(a.feature("revenue_yoy")[2, 0], np.log(130 / 105))


# A restatement changes the features that read the restated quarter, and
# only from the restatement's availability on, for an after-close filing and
# for a date-only filing alike.
def test_restatement_changes_features_only_after_availability():
    base = fa.parse_versions(payload(Revenues=EIGHT))
    days = ["2026-02-16", "2026-02-20", "2026-03-01", "2026-03-02", "2026-03-10"]
    p = panel(days, [[40.0, 1.0]] * 5)
    # Q3 2025 (the sequential-growth lag q1) is restated. Accepted 21:30 UTC
    # = 16:30 New York: public on 03-02, not 03-01.
    after_close = fa.parse_versions(
        payload(
            Revenues=EIGHT
            + [
                row(
                    "2025-07-01",
                    "2025-09-30",
                    999,
                    "2026-03-01",
                    "q3a",
                    "10-Q/A",
                    accepted="2026-03-01T21:30:00Z",
                )
            ]
        )
    )
    # A date-only restatement has no acceptance time: available the day after.
    dated = fa.parse_versions(
        payload(
            Revenues=EIGHT
            + [row("2025-07-01", "2025-09-30", 999, "2026-03-01", "q3a", "10-Q/A")]
        )
    )
    before = ff.features(p, {"N0": base})
    qoq = "revenue_qoq"
    for snapshot in (after_close, dated):
        after = ff.features(p, {"N0": snapshot})
        # Identical on every session before the availability (03-02), and the
        # sequential growth on the last pre-filing session reads the old Q3.
        assert np.allclose(
            before.feature(qoq)[:3, 0], after.feature(qoq)[:3, 0], equal_nan=True
        )
        assert np.isclose(after.feature(qoq)[0, 0], np.log(130 / 120))
        # From its availability on, the restated Q3 (999) drives the feature.
        assert np.isclose(after.feature(qoq)[3, 0], np.log(130 / 999))
        assert np.isclose(after.feature(qoq)[4, 0], np.log(130 / 999))
        # The year-over-year feature reads Q4 2025 and Q4 2024, which the
        # restatement does not touch: it stays exactly as before.
        assert np.allclose(
            before.feature("revenue_yoy"), after.feature("revenue_yoy"), equal_nan=True
        )


# A lagged quarter that was never filed is NaN (sequential growth cannot be
# computed across a gap), while year-over-year growth compares the same
# fiscal quarter a year apart and does not need the missing period.
def test_missing_lagged_quarter_is_nan_but_yoy_survives():
    rows = [
        row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
        row("2025-04-01", "2025-06-30", 110, "2025-08-01", "q2"),
        row("2025-07-01", "2025-09-30", 120, "2025-11-01", "q3"),
        row(
            "2026-01-01", "2026-03-31", 140, "2026-05-01", "q1y"
        ),  # Q4 2025 never filed
    ]
    v = fa.parse_versions(payload(Revenues=rows))
    p = panel(["2026-05-02"], [[40.0, 1.0]])
    out = ff.features(p, {"N0": v})
    # Sequential growth needs the missing Q4 2025: NaN, not a fabricated value.
    assert np.isnan(out.feature("revenue_qoq")[0, 0])
    # Year-over-year compares Q1 2026 with Q1 2025 and does not need Q4.
    assert np.isclose(out.feature("revenue_yoy")[0, 0], np.log(140 / 100))


# A genuinely zero growth and a genuinely zero margin are valid zeros; a zero
# denominator is NaN, never a number.
def test_zero_denominator_is_nan_but_genuine_zero_is_valid():
    zero_growth = fa.parse_versions(
        payload(
            Revenues=[
                row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
                row("2025-04-01", "2025-06-30", 110, "2025-08-01", "q2"),
                row("2025-07-01", "2025-09-30", 120, "2025-11-01", "q3"),
                row("2025-10-01", "2025-12-31", 130, "2026-02-15", "q4"),
                row("2026-01-01", "2026-03-31", 100, "2026-05-01", "q1y"),
            ]
        )
    )
    p = panel(["2026-05-02"], [[40.0, 1.0]])
    out = ff.features(p, {"N0": zero_growth})
    assert out.feature("revenue_yoy")[0, 0] == 0.0

    zero_margin = fa.parse_versions(
        payload(
            Revenues=[row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1")],
            GrossProfit=[row("2025-01-01", "2025-03-31", 0, "2025-05-01", "q1")],
        )
    )
    p = panel(["2025-05-02"], [[40.0, 1.0]])
    out = ff.features(p, {"N0": zero_margin})
    assert out.feature("gross_margin")[0, 0] == 0.0

    zero_denominator = fa.parse_versions(
        payload(
            Revenues=[row("2025-01-01", "2025-03-31", 0, "2025-05-01", "q1")],
            NetIncomeLoss=[row("2025-01-01", "2025-03-31", 10, "2025-05-01", "q1")],
        )
    )
    out = ff.features(p, {"N0": zero_denominator})
    assert np.isnan(out.feature("net_margin")[0, 0])


# A margin divides the numerator and denominator of the same fiscal period:
# when the numerator lags revenue, the ratio stays on the older quarter and
# an old numerator is never divided by a newer quarter of revenue.
def test_ratio_uses_the_same_fiscal_period_when_numerator_lags():
    v = fa.parse_versions(
        payload(
            Revenues=[
                row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
                row("2025-04-01", "2025-06-30", 110, "2025-08-01", "q2"),
            ],
            GrossProfit=[
                row("2025-01-01", "2025-03-31", 60, "2025-05-01", "q1"),
                # Q2 2025 gross profit is not public yet: the numerator lags.
                row("2025-04-01", "2025-06-30", 70, "2025-09-01", "q2"),
            ],
        )
    )
    # At 2025-08-02 revenue's latest quarter is Q2 2025 but gross profit's is
    # still Q1 2025: the margin compares Q1 on both sides, not 60 over 110.
    early = ff.features(panel(["2025-08-02"], [[40.0, 1.0]]), {"N0": v})
    assert np.isclose(early.feature("gross_margin")[0, 0], 60 / 100)
    # Once Q2 gross profit is public (available 09-02), the margin moves to
    # Q2 on both sides.
    later = ff.features(panel(["2025-09-02"], [[40.0, 1.0]]), {"N0": v})
    assert np.isclose(later.feature("gross_margin")[0, 0], 70 / 110)


# Tag ties resolve in the table's deterministic order, and a quarter whose
# filing is only public later is never used to fill an earlier session.
def test_tag_ties_are_deterministic_and_nothing_is_filled_from_the_future():
    other = [
        row(r["start"], r["end"], r["val"] + 1, r["filed"], r["accn"] + "b")
        for r in EIGHT
    ]
    tied = fa.parse_versions(
        payload(
            Revenues=EIGHT, RevenueFromContractWithCustomerExcludingAssessedTax=other
        )
    )
    p = panel(["2026-02-16"], [[40.0, 1.0]])
    out = ff.features(p, {"N0": tied})
    # Revenues (the first tag) wins the tie: yoy compares 130 with 105, not
    # the +1 second tag's 131 with 106.
    assert np.isclose(out.feature("revenue_yoy")[0, 0], np.log(130 / 105))
    # A future quarter under either tag is available 05-02, after the session:
    # this session must be byte-identical whether that future exists or not.
    future = fa.parse_versions(
        payload(
            Revenues=EIGHT + [row("2026-01-01", "2026-03-31", 141, "2026-05-01", "q5")],
            RevenueFromContractWithCustomerExcludingAssessedTax=other
            + [row("2026-01-01", "2026-03-31", 999, "2026-05-01", "q5b")],
        )
    )
    out_future = ff.features(p, {"N0": future})
    assert np.array_equal(out.values, out_future.values, equal_nan=True)


# The whole path on a small real panel: shape, names, coverage and hand
# computed values, including a cash-flow quarter derived from a six-month
# span and the fourth quarter derived from the year.
def test_end_to_end_panel_proves_shape_names_coverage_and_values():
    versions = fa.parse_versions(
        payload(
            Revenues=[
                row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
                row("2025-01-01", "2025-06-30", 230, "2025-08-01", "h1"),  # Q2 = 130
                row("2025-07-01", "2025-09-30", 120, "2025-11-01", "q3"),
                row("2025-01-01", "2025-12-31", 500, "2026-02-15", "fy"),  # Q4 = 150
            ],
            NetIncomeLoss=[
                row("2025-01-01", "2025-03-31", 10, "2025-05-01", "q1"),
                row("2025-04-01", "2025-06-30", 12, "2025-08-01", "q2"),
                row("2025-07-01", "2025-09-30", 14, "2025-11-01", "q3"),
                row("2025-10-01", "2025-12-31", 16, "2026-02-15", "q4"),
            ],
            GrossProfit=[
                row("2025-01-01", "2025-03-31", 60, "2025-05-01", "q1"),
                row("2025-04-01", "2025-06-30", 60, "2025-08-01", "q2"),
                row("2025-07-01", "2025-09-30", 60, "2025-11-01", "q3"),
                row("2025-10-01", "2025-12-31", 60, "2026-02-15", "q4"),
            ],
            NetCashProvidedByUsedInOperatingActivities=[
                row("2025-01-01", "2025-03-31", 20, "2025-05-01", "q1"),
                row("2025-01-01", "2025-06-30", 45, "2025-08-01", "h1"),  # Q2 = 25
                row("2025-01-01", "2025-09-30", 75, "2025-11-01", "m9"),  # Q3 = 30
                row("2025-01-01", "2025-12-31", 110, "2026-02-15", "fy"),  # Q4 = 35
            ],
        )
    )
    days = ["2026-02-13", "2026-02-16", "2026-02-17"]
    p = panel(days, [[40.0, 1.0], [40.0, 1.0], [50.0, 1.0]])
    out = ff.features(p, {"N0": versions})
    assert out.values.shape == (3, 2, len(ff.FEATURE_NAMES))
    assert out.period_ends.shape == (3, 2, len(ff.FEATURE_NAMES))
    assert out.names == ff.FEATURE_NAMES
    y = out.feature
    # Before the year filing's availability (02-16) the latest quarter is Q3.
    assert np.isclose(y("revenue_qoq")[0, 0], np.log(120 / 130))
    assert np.isclose(y("gross_margin")[0, 0], 60 / 120)
    assert np.isclose(y("net_margin")[0, 0], 14 / 120)
    assert np.isclose(y("ocf_to_revenue")[0, 0], 30 / 120)
    # On 02-16 the derived Q4 lands: the cash-flow quarter 35 comes from the
    # year (110) less the nine-month span (75), and every ratio aligns to it.
    assert np.isclose(y("revenue_qoq")[1, 0], np.log(150 / 120))
    assert np.isclose(y("gross_margin")[1, 0], 60 / 150)
    assert np.isclose(y("net_margin")[1, 0], 16 / 150)
    assert np.isclose(y("ocf_to_revenue")[1, 0], 35 / 150)
    # Only one year on file: year-over-year is not computable yet.
    assert np.isnan(y("revenue_yoy")[1, 0])
    # No capex was filed at all: the column stays missing, not zero.
    assert np.isnan(y("capex_to_revenue")[1, 0])
    # The next day carries the same features forward.
    assert np.allclose(out.values[2], out.values[1], equal_nan=True)
    # The availability mask and staleness are separate from the economic
    # columns: data is on file (mask true, staleness counted) even where a
    # feature needs history it does not have yet.
    assert out.available[1, 0]
    assert out.staleness[1, 0] == 0.0
    assert out.staleness[2, 0] == 1.0
    assert np.isnan(y("revenue_yoy")[1, 0])
    # The second ticker has no versions: missing, not a fabricated zero.
    assert not out.available[1, 1]
    assert np.isnan(out.staleness[1, 1])


# The lag lookup must pick the nearest eligible quarter end deterministically,
# independent of the dict's insertion order, breaking a distance tie by the
# earlier date.
def test_quarter_back_is_deterministic_under_reversed_insertion():
    target = date(2025, 12, 31)
    # Two ends both one day off the quarter before the target (2025-10-01):
    # 2025-09-30 and 2025-10-02 are each eligible and equidistant.
    forward = {date(2025, 9, 30): 1.0, date(2025, 10, 2): 2.0}
    backward = dict(reversed(list(forward.items())))
    # Reversed insertion picks the same end, and on the distance tie the
    # earlier date (2025-09-30, value 1.0) wins.
    assert ff._quarter_back(forward, target, 1) == 1.0
    assert ff._quarter_back(backward, target, 1) == 1.0
    # A nearer end beats a further one regardless of insertion order.
    mixed = {date(2025, 10, 15): 3.0, date(2025, 9, 30): 1.0}
    mixed_backward = dict(reversed(list(mixed.items())))
    assert ff._quarter_back(mixed, target, 1) == 1.0
    assert ff._quarter_back(mixed_backward, target, 1) == 1.0


# Each economic feature exposes its reference period end, so a consumer can
# see that a ratio still sits on an older quarter while revenue has moved
# on: a newly filed revenue quarter must not make the stale gross-margin
# period look fresh.
def test_period_ends_reveal_a_stale_ratio_while_revenue_moves_on():
    v = fa.parse_versions(
        payload(
            Revenues=[
                row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
                row("2025-04-01", "2025-06-30", 110, "2025-08-01", "q2"),
            ],
            GrossProfit=[
                row("2025-01-01", "2025-03-31", 60, "2025-05-01", "q1"),
                # Q2 2025 gross profit is not public yet: the numerator lags.
                row("2025-04-01", "2025-06-30", 70, "2025-09-01", "q2"),
            ],
        )
    )
    # At 2025-08-02 revenue's latest quarter is Q2 2025 but gross profit is
    # still on Q1 2025: the revenue features advance to Q2 while the margin
    # keeps Q1 as its reference period.
    early = ff.features(panel(["2025-08-02"], [[40.0, 1.0]]), {"N0": v})
    qoq = ff.FEATURE_NAMES.index("revenue_qoq")
    gm = ff.FEATURE_NAMES.index("gross_margin")
    assert early.period_ends[0, 0, qoq] == np.datetime64("2025-06-30")
    assert early.period_ends[0, 0, gm] == np.datetime64("2025-03-31")
    assert early.period_ends[0, 0, gm] != early.period_ends[0, 0, qoq]
    assert np.isclose(early.feature("gross_margin")[0, 0], 60 / 100)
    # Once Q2 gross profit is public (09-02) the margin advances to Q2 too.
    later = ff.features(panel(["2025-09-02"], [[40.0, 1.0]]), {"N0": v})
    assert later.period_ends[0, 0, gm] == np.datetime64("2025-06-30")


# A feature with no computable value has no reference period: its period end
# is NaT, for a ticker with too little history and for one with nothing on
# file at all.
def test_period_end_is_nat_when_the_feature_is_unknown():
    v = fa.parse_versions(payload(Revenues=QUARTERS))
    p = panel(["2025-05-02"], [[40.0, 1.0]])  # only Q1 2025 known
    out = ff.features(p, {"N0": v})
    yoy = ff.FEATURE_NAMES.index("revenue_yoy")
    # One quarter on file: year-over-year has no reference period, so NaT.
    assert np.isnan(out.feature("revenue_yoy")[0, 0])
    assert np.isnat(out.period_ends[0, 0, yoy])
    # The ticker with nothing on file is entirely NaT.
    assert np.isnat(out.period_ends[0, 1, yoy])


# Huge finite inputs must not overflow to inf: log growth is computed as
# log(a) - log(b) (the ratio a/b alone would overflow), and a margin whose
# quotient would overflow reads NaN, never inf.
def test_huge_finite_inputs_do_not_overflow_to_inf():
    v = fa.parse_versions(
        payload(
            Revenues=[
                row("2024-10-01", "2024-12-31", 1e-308, "2025-02-15", "p4"),
                row("2025-01-01", "2025-03-31", 100, "2025-05-01", "q1"),
                row("2025-04-01", "2025-06-30", 110, "2025-08-01", "q2"),
                row("2025-07-01", "2025-09-30", 120, "2025-11-01", "q3"),
                row("2025-10-01", "2025-12-31", 1e308, "2026-02-15", "q4"),
            ]
        )
    )
    out = ff.features(panel(["2026-02-16"], [[40.0, 1.0]]), {"N0": v})
    yoy = out.feature("revenue_yoy")[0, 0]
    assert np.isfinite(yoy)
    assert np.isclose(yoy, np.log(1e308) - np.log(1e-308))

    overflowing_margin = fa.parse_versions(
        payload(
            Revenues=[row("2025-01-01", "2025-03-31", 1e-308, "2025-05-01", "q1")],
            GrossProfit=[row("2025-01-01", "2025-03-31", 1e308, "2025-05-01", "q1")],
        )
    )
    out = ff.features(panel(["2025-05-02"], [[40.0, 1.0]]), {"N0": overflowing_margin})
    assert np.isnan(out.feature("gross_margin")[0, 0])


# The scalar guards directly: log growth stays finite for huge operands and
# a quotient that would overflow is NaN, while a genuine zero stays zero.
def test_log_ratio_and_ratio_guard_against_overflow():
    assert np.isfinite(ff._log_ratio(1e308, 1e-308))
    assert np.isclose(ff._log_ratio(1e308, 1e-308), np.log(1e308) - np.log(1e-308))
    assert np.isnan(ff._ratio(1e308, 1e-308))
    assert np.isnan(ff._ratio(1.0, 0.0))
    assert ff._ratio(0.0, 100.0) == 0.0
    assert ff._log_ratio(100.0, 100.0) == 0.0
