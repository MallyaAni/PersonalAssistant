"""The EDGAR layer: parsing, point-in-time facts, reaction windows, features.

No network: payloads are recorded shapes. The properties that matter: an
earliest-filed value wins over a restatement; a fourth quarter is derived
from the year; a release accepted after the close reacts the next session;
nothing filed after session t is visible at t; names with nothing on file
keep neutral fills and stay eligible.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

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
                "Assets": {
                    "units": {
                        "USD": [
                            {"end": "2024-03-31", "val": 1000, "filed": "2024-05-01"},
                            {"end": "2025-03-31", "val": 1200, "filed": "2025-05-01"},
                            {"end": "2024-03-31", "val": 999, "filed": "2025-05-01"},
                        ]
                    }
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2024-03-31", "val": 100, "filed": "2024-05-01"},
                            {"end": "2025-03-31", "val": 110, "filed": "2025-05-01"},
                        ]
                    }
                },
            },
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


# Instant facts keep the earliest filing per date and come back as
# start == end rows; growth features read them four quarters apart.
def test_instant_facts_and_growth_features():
    facts = edgar.parse_company_facts(_facts_payload())
    assets = {f.end: f for f in facts if f.name == "assets"}
    assert assets[date(2024, 3, 31)].value == 1000  # not the 999 restatement
    assert assets[date(2024, 3, 31)].start == date(2024, 3, 31)
    shares = {f.end: f for f in facts if f.name == "shares"}
    assert shares[date(2025, 3, 31)].value == 110


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
    # Growth in shares and assets, four quarters apart, from the instants.
    assert (
        abs(feats[t_after, a, names.index("share_issuance")] - np.log(110 / 100)) < 1e-5
    )
    assert (
        abs(feats[t_after, a, names.index("asset_growth")] - np.log(1200 / 1000)) < 1e-5
    )
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


# The same filings on a real scale, so a release's millions line up with
# the 10-Q's raw dollars in the ratio features.
def _facts_payload_scaled():
    def fact(start, end, val, filed, form="10-Q"):
        return {"start": start, "end": end, "val": val, "filed": filed, "form": form}

    m = 1e6
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            fact("2024-01-01", "2024-03-31", 100 * m, "2024-05-01"),
                            fact("2024-04-01", "2024-06-30", 110 * m, "2024-08-01"),
                            fact("2024-07-01", "2024-09-30", 120 * m, "2024-11-01"),
                            fact("2024-01-01", "2024-12-31", 470 * m, "2025-02-15", "10-K"),
                            fact("2025-01-01", "2025-03-31", 150 * m, "2025-05-01"),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [fact("2025-01-01", "2025-03-31", 30 * m, "2025-05-01")]
                    }
                },
            },
            "dei": {},
        }
    }


# A release's reported financials become dated facts, and once they are
# newer than the 10-Q's they carry the fundamental layer: revenue, net
# margin and gross margin read the release's own quarter from its reaction
# date on, while the 10-Q's figures stand until then.
def test_release_facts_advance_the_fundamental_layer():
    from dataclasses import replace
    from types import SimpleNamespace

    first = date(2025, 4, 1)
    panel = panel_from_histories(
        {"AAA": _history("AAA", first, 80), "SPY": _history("SPY", first, 80)},
        "SPY",
        {},
    )
    event = edgar.EarningsEvent(
        datetime(2025, 6, 9, 20, 10, tzinfo=UTC),
        date(2025, 6, 9),
        "r1",
        "2.02",
    )
    record = edgar.CompanyRecord(
        "AAA",
        1,
        (event,),
        tuple(edgar.parse_company_facts(_facts_payload_scaled())),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    release = SimpleNamespace(
        quarter_end=date(2025, 6, 30),
        reaction_date=date(2025, 6, 10),
        revenue_usd_m=200.0,
        eps_usd=2.0,
        net_income_usd_m=40.0,
        gross_margin_pct=55.0,
    )
    facts = edgar.release_facts({"AAA": [release]})["AAA"]
    assert {f.name for f in facts} == {"revenue", "eps", "net_income", "gross_profit"}
    rev = next(f for f in facts if f.name == "revenue")
    assert rev.value == 200.0 * 1e6  # millions to raw dollars, like the filings
    assert rev.end == date(2025, 6, 30)
    assert rev.filed == date(2025, 6, 10)
    gross = next(f for f in facts if f.name == "gross_profit")
    assert gross.value == 0.55 * 200.0 * 1e6  # the stated margin, same quarter

    merged = replace(record, facts=record.facts + tuple(facts))
    feats = edgar.edgar_features(panel, {"AAA": merged})
    names = edgar.FEATURE_NAMES
    a = panel.index("AAA")
    dates = list(panel.dates.astype("datetime64[D]").astype(object))
    t = dates.index(date(2025, 6, 10))
    t_before = dates.index(date(2025, 6, 9))
    # Before the release the features are the last 10-Q's (Q1 2025 revenue
    # 150, up from 100 a year before).
    assert abs(feats[t_before, a, names.index("revenue_yoy")] - np.log(150 / 100)) < 1e-5
    # From the release the features read its own numbers: 200 revenue, 150
    # last quarter, 110 a year ago, 40 net income, 55% gross margin.
    assert abs(feats[t, a, names.index("revenue_yoy")] - np.log(200 / 110)) < 1e-5
    assert abs(feats[t, a, names.index("revenue_qoq")] - np.log(200 / 150)) < 1e-5
    assert abs(feats[t, a, names.index("net_margin")] - 40.0 / 200.0) < 1e-5
    assert abs(feats[t, a, names.index("gross_margin")] - 0.55) < 1e-5
    assert feats[t, a, names.index("fundamentals_staleness")] == 0


# The shared loader folds release financials from the tone frames into the
# fundamental record, so the desk's nightly path reads an 8-K's numbers
# without any further wiring. The loader lives beside the torch models, so
# this skips in the gate container exactly as test_market_model does.
def test_load_edgar_features_merges_release_financials(tmp_path):
    pytest.importorskip("torch")
    from backend.market import language
    from backend.market.model import load_edgar_features

    store = MarketStore(tmp_path)
    asof = date(2025, 6, 11)
    facts = tuple(edgar.parse_company_facts(_facts_payload_scaled()))
    event = edgar.EarningsEvent(
        datetime(2025, 6, 9, 20, 10, tzinfo=UTC),
        date(2025, 6, 9),
        "r1",
        "2.02",
    )
    record = edgar.CompanyRecord("AAA", 1, (event,), facts, datetime(2026, 1, 1, tzinfo=UTC))
    events, fact_columns = edgar.record_frames(record)
    store.write_frame("edgar_events", asof, "AAA", events, {"cik": "1"})
    store.write_frame("edgar_facts", asof, "AAA", fact_columns, {"cik": "1"})
    tone = language.ToneRecord(
        accession="r1",
        reaction_date=date(2025, 6, 10),
        guidance=0.5,
        demand=0.2,
        pricing=0.0,
        capex=0.0,
        supply_constrained=0.0,
        summary="s",
        model="m",
        prompt_version="v",
        truncated=False,
        quarter_end=date(2025, 6, 30),
        revenue_usd_m=200.0,
        eps_usd=2.0,
        net_income_usd_m=40.0,
        gross_margin_pct=55.0,
    )
    store.write_frame(
        language.TONE_KIND, asof, "AAA", language.tone_frame([tone]), {"cik": "1"}
    )
    panel = panel_from_histories(
        {"AAA": _history("AAA", date(2025, 4, 1), 80), "SPY": _history("SPY", date(2025, 4, 1), 80)},
        "SPY",
        {},
    )
    feats = load_edgar_features(store, panel, asof)
    names = edgar.FEATURE_NAMES
    a = panel.index("AAA")
    dates = list(panel.dates.astype("datetime64[D]").astype(object))
    t = dates.index(date(2025, 6, 10))
    assert abs(feats[t, a, names.index("revenue_yoy")] - np.log(200 / 110)) < 1e-5
    assert abs(feats[t, a, names.index("net_margin")] - 40.0 / 200.0) < 1e-5
