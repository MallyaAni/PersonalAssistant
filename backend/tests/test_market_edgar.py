"""The EDGAR layer: parsing, point-in-time facts, reaction windows, features.

No network: payloads are recorded shapes. The properties that matter: an
earliest-filed value wins over a restatement; a fourth quarter is derived
from the year; a release accepted after the close reacts the next session;
nothing filed after session t is visible at t; names with nothing on file
keep neutral fills and stay eligible.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import edgar
from backend.market.panel import panel_from_histories
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory


# A weekday-only history of flat prices with one jump on `jump_day`.
def _history(ticker: str, first: date, sessions: int, jump_day: date | None = None):
    bars = []
    day = first
    price = 100.0
    while len(bars) < sessions:
        if day.weekday() < 5:
            if jump_day is not None and day == jump_day:
                price *= 1.10
            bars.append(DailyBar(day, price, price, price, price, price, 1_000_000))
        day += timedelta(days=1)
    return TickerHistory(
        ticker, tuple(bars), (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


def _facts_payload():
    def fact(start, end, val, filed, form="10-Q"):
        return {"start": start, "end": end, "val": val, "filed": filed, "form": form}

    revenue = [
        fact("2024-01-01", "2024-03-31", 100, "2024-05-01"),
        fact("2024-04-01", "2024-06-30", 110, "2024-08-01"),
        fact("2024-07-01", "2024-09-30", 120, "2024-11-01"),
        fact("2024-01-01", "2024-12-31", 470, "2025-02-15", "10-K"),  # Q4 = 140
        fact("2024-01-01", "2024-03-31", 999, "2025-05-01"),  # restatement, later
        fact("2025-01-01", "2025-03-31", 150, "2025-05-01"),
    ]
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": revenue}},
                "NetIncomeLoss": {
                    "units": {
                        "USD": [fact("2025-01-01", "2025-03-31", 30, "2025-05-01")]
                    }
                },
            }
        }
    }


# The earliest filing wins, the fourth quarter is derived from the year.
def test_company_facts_are_point_in_time_with_derived_fourth_quarter():
    facts = edgar.parse_company_facts(_facts_payload())
    revenue = {f.end: f for f in facts if f.name == "revenue"}
    assert revenue[date(2024, 3, 31)].value == 100  # not the 999 restatement
    q4 = revenue[date(2024, 12, 31)]
    assert q4.derived is True
    assert q4.value == 470 - 100 - 110 - 120
    assert q4.filed == date(2025, 2, 15)
    assert q4.start == date(2024, 10, 1)


# 8-K item 2.02 filings become events; anything else is ignored; a release
# accepted after the New York close reacts the next day.
def test_submissions_events_and_reaction_dates():
    block = {
        "form": ["8-K", "8-K", "10-Q", "8-K"],
        "items": ["2.02,9.01", "5.02", "", "2.02"],
        "acceptanceDateTime": [
            "2025-05-01T20:10:00.000Z",  # 16:10 New York: after the close
            "2025-05-02T12:00:00.000Z",
            "2025-05-03T12:00:00.000Z",
            "2025-08-01T12:05:00.000Z",  # 08:05 New York: before the open
        ],
        "filingDate": ["2025-05-01", "2025-05-02", "2025-05-03", "2025-08-01"],
        "accessionNumber": ["a", "b", "c", "d"],
    }
    events = edgar.parse_submissions_block(block)
    assert [e.accession for e in events] == ["a", "d"]
    assert events[0].reaction_date == date(2025, 5, 2)
    assert events[1].reaction_date == date(2025, 8, 1)


# Features at session t use only what was filed by t; the reaction is the
# residual return over the reaction window, carried forward; a name with
# nothing on file keeps neutral fills and indicators of zero.
def test_features_are_point_in_time_and_filled():
    first = date(2025, 4, 1)
    jump = date(2025, 5, 2)  # the session after an after-close release
    histories = {
        "AAA": _history("AAA", first, 80, jump_day=jump),
        "BBB": _history("BBB", first, 80),
        "SPY": _history("SPY", first, 80),
    }
    panel = panel_from_histories(histories, "SPY", {})
    event = edgar.EarningsEvent(
        accepted=datetime(2025, 5, 1, 20, 10, tzinfo=UTC),
        filed=date(2025, 5, 1),
        accession="a",
        items="2.02",
    )
    facts = tuple(edgar.parse_company_facts(_facts_payload()))
    record = edgar.CompanyRecord(
        "AAA", 1, (event,), facts, datetime(2026, 1, 1, tzinfo=UTC)
    )
    feats = edgar.edgar_features(panel, {"AAA": record})
    names = edgar.FEATURE_NAMES
    a = panel.index("AAA")
    b = panel.index("BBB")
    dates = list(panel.dates.astype("datetime64[D]").astype(object))
    t_jump = dates.index(jump)
    # Before the reaction window closes nothing is known; after, the jump.
    assert feats[t_jump, a, names.index("earnings_reaction")] == 0.0
    assert (
        abs(feats[t_jump + 1, a, names.index("earnings_reaction")] - np.log(1.10))
        < 1e-5
    )
    assert feats[t_jump + 5, a, names.index("sessions_since_earnings")] == 5
    assert (
        feats[t_jump - 1, a, names.index("sessions_since_earnings")]
        == edgar.NO_EVENT_SESSIONS
    )
    # Before the 2025-05-01 filing the latest quarter is the derived Q4
    # (filed 2025-02-15): sequential growth is known, year-on-year is not
    # (no Q4 2023 on file) and reads as the neutral zero. After it, both.
    t_before = dates.index(date(2025, 4, 30))
    t_after = dates.index(date(2025, 5, 1))
    assert feats[t_before, a, names.index("has_fundamentals")] == 1.0
    assert feats[t_before, a, names.index("revenue_yoy")] == 0.0
    assert (
        abs(feats[t_before, a, names.index("revenue_qoq")] - np.log(140 / 120)) < 1e-5
    )
    assert feats[t_before, a, names.index("net_margin")] == 0.0  # no income yet
    assert feats[t_after, a, names.index("has_fundamentals")] == 1.0
    assert abs(feats[t_after, a, names.index("revenue_yoy")] - np.log(150 / 100)) < 1e-5
    assert abs(feats[t_after, a, names.index("revenue_qoq")] - np.log(150 / 140)) < 1e-5
    assert abs(feats[t_after, a, names.index("net_margin")] - 30 / 150) < 1e-5
    # Staleness counts sessions since the latest filing.
    assert feats[t_after, a, names.index("fundamentals_staleness")] == 0
    assert feats[t_after + 3, a, names.index("fundamentals_staleness")] == 3
    # A name with no record: neutral fills, indicators zero, nothing NaN.
    assert np.isfinite(feats).all()
    assert feats[:, b, names.index("has_events")].max() == 0.0
    assert (
        feats[:, b, names.index("sessions_since_earnings")].min()
        == edgar.NO_EVENT_SESSIONS
    )


# Frames round-trip through the store and rebuild the same record.
def test_record_round_trips_through_store_frames(tmp_path):
    store = MarketStore(tmp_path)
    facts = tuple(edgar.parse_company_facts(_facts_payload()))
    event = edgar.EarningsEvent(
        datetime(2025, 5, 1, 20, 10, tzinfo=UTC), date(2025, 5, 1), "a", "2.02"
    )
    record = edgar.CompanyRecord(
        "AAA", 7, (event,), facts, datetime(2026, 1, 1, tzinfo=UTC)
    )
    events, fact_columns = edgar.record_frames(record)
    assert store.write_frame(
        "edgar_events", date(2026, 1, 2), "AAA", events, {"cik": "7"}
    )
    assert store.write_frame(
        "edgar_facts", date(2026, 1, 2), "AAA", fact_columns, {"cik": "7"}
    )
    assert store.write_frame("edgar_events", date(2026, 1, 2), "AAA", events) is False
    e_cols, meta = store.read_frame("edgar_events", "AAA")
    f_cols, _ = store.read_frame("edgar_facts", "AAA")
    rebuilt = edgar.record_from_frames(
        "AAA", int(meta["cik"]), e_cols, f_cols, record.source_time
    )
    assert rebuilt.events == record.events
    assert rebuilt.facts == record.facts
    assert store.read_frame("edgar_events", "AAA", date(2026, 1, 1)) is None


# HTML becomes readable text.
def test_html_to_text():
    html = (
        "<html><style>x{}</style><body><p>Revenue was <b>$1.2B</b>,</p>"
        " up 10%.</body></html>"
    )
    assert edgar.html_to_text(html) == "Revenue was $1.2B , up 10%."
