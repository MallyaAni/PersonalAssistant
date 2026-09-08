"""Cash flow by quarter from year-to-date spans.

What has to hold: a six-month span less the first quarter gives the
second quarter and a nine-month span less the six-month gives the third,
each known when both parts were filed; a quarter already reported is
kept as reported; and a span that does not close a quarter is ignored.
"""

from datetime import date

from backend.market.edgar import QuarterFact, _with_year_to_date_quarters, _ytd_spans


def _row(start, end, val, filed):
    return {"start": start, "end": end, "val": val, "filed": filed}


def test_second_and_third_quarters_come_from_the_year_to_date_spans():
    rows = [
        _row("2025-01-01", "2025-03-31", 10.0, "2025-05-01"),  # Q1 as reported
        _row("2025-01-01", "2025-06-30", 25.0, "2025-08-01"),  # six months
        _row("2025-01-01", "2025-09-30", 45.0, "2025-11-01"),  # nine months
        _row("2025-01-01", "2025-12-31", 70.0, "2026-02-15"),  # the year
    ]
    ytd = _ytd_spans(rows, "operating_cash_flow")
    assert sorted(k[1].isoformat() for k in ytd) == ["2025-06-30", "2025-09-30"]
    quarters = {
        (date(2025, 1, 1), date(2025, 3, 31)): QuarterFact(
            "operating_cash_flow",
            date(2025, 1, 1),
            date(2025, 3, 31),
            10.0,
            date(2025, 5, 1),
        )
    }
    out = _with_year_to_date_quarters(quarters, ytd)
    q2 = out[(date(2025, 4, 1), date(2025, 6, 30))]
    q3 = out[(date(2025, 7, 1), date(2025, 9, 30))]
    assert q2.value == 15.0
    assert q2.derived
    assert q2.filed == date(2025, 8, 1)
    assert q3.value == 20.0
    assert q3.filed == date(2025, 11, 1)
    # The first quarter stays as reported.
    assert out[(date(2025, 1, 1), date(2025, 3, 31))].value == 10.0


def test_a_span_that_does_not_close_a_quarter_is_ignored():
    rows = [_row("2025-01-01", "2025-05-15", 5.0, "2025-06-01")]
    assert _ytd_spans(rows, "capex") == {}
