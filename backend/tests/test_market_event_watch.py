"""Event discovery: deterministic election dates and the mechanical shock rule."""

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import event_watch, fundamentals_asof as fa


# Consecutive weekdays starting on a Monday, long enough for a filing and a window.
def _days(count: int, first: date = date(2024, 1, 1)) -> np.ndarray:
    out = []
    day = first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return np.asarray(out, dtype="datetime64[D]")


# One filed quarterly value.
def _version(end: date, value: float, filed: date) -> fa.Version:
    return fa.Version(
        name="net_income",
        tag="us-gaap:NetIncomeLoss",
        start=end - timedelta(days=90),
        end=end,
        value=value,
        filed=filed,
        accepted=None,
        accession=f"acc-{end.isoformat()}",
        form="10-Q",
    )


# Election day is the first Tuesday after the first Monday in November.
def test_election_day_is_deterministic():
    assert event_watch.election_day(2018) == date(2018, 11, 6)
    assert event_watch.election_day(2022) == date(2022, 11, 8)
    assert event_watch.election_day(2026) == date(2026, 11, 3)
    assert event_watch.election_day(2028) == date(2028, 11, 7)
    assert event_watch.is_midterm(2018)
    assert event_watch.is_midterm(2022)
    assert event_watch.is_midterm(2026)
    assert not event_watch.is_midterm(2020)
    assert not event_watch.is_midterm(2024)
    assert event_watch.next_election(date(2026, 10, 30)) == (date(2026, 11, 3), True)
    assert event_watch.next_election(date(2026, 11, 4)) == (date(2027, 11, 2), False)


# A larger loss is a negative change, and a zero comparison is missing, not infinite.
def test_relative_change_is_sign_safe():
    assert event_watch.relative_change(50.0, 100.0) == pytest.approx(-0.5)
    assert event_watch.relative_change(-200.0, -100.0) == pytest.approx(-1.0)
    assert event_watch.relative_change(-50.0, -100.0) == pytest.approx(0.5)
    assert event_watch.relative_change(100.0, 0.0) is None
    assert event_watch.relative_change(None, 100.0) is None
    assert event_watch.relative_change(100.0, None) is None


# The pre-registered threshold is an OR over the two seasonal measures.
def test_negative_and_positive_shock_thresholds():
    assert event_watch.negative_shock(-0.20, None)
    assert event_watch.negative_shock(None, -0.10)
    assert not event_watch.negative_shock(-0.19, -0.09)
    assert event_watch.positive_shock(0.20, None)
    assert event_watch.positive_shock(None, 0.10)
    assert not event_watch.positive_shock(0.19, 0.09)


# The earliest filing per period end wins, and only quarter spans are kept.
def test_quarter_series_deduplicates_and_keeps_quarters():
    versions = [
        _version(date(2024, 3, 31), 100.0, date(2024, 4, 20)),
        _version(date(2024, 3, 31), 90.0, date(2024, 4, 10)),
        fa.Version(
            name="net_income",
            tag="us-gaap:NetIncomeLoss",
            start=date(2023, 1, 1),
            end=date(2023, 12, 31),
            value=400.0,
            filed=date(2024, 2, 1),
            accepted=None,
            accession="annual",
            form="10-K",
        ),
    ]
    series = event_watch.quarter_series(versions)
    assert series == {date(2024, 3, 31): (90.0, date(2024, 4, 11))}


# Quarter-over-quarter and year-over-year use the pre-registered distance bands.
def test_earnings_changes_use_prior_and_year_ago_quarters():
    ends = [date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31)]
    series = {
        end: (value, end + timedelta(days=30))
        for end, value in zip(ends, (100.0, 100.0, 100.0, 50.0))
    }
    changes = event_watch.earnings_changes(series)
    assert changes[date(2023, 12, 31)]["qoq"] == pytest.approx(-0.5)
    assert changes[date(2023, 12, 31)]["yoy"] is None
    assert changes[date(2023, 9, 30)]["qoq"] == pytest.approx(0.0)


# A filing with a large drop and a large reaction becomes one event at its session.
def test_study_events_finds_the_shock_at_the_reaction_session():
    days = _days(40)
    tickers = ["AAA", "SPY"]
    member = np.ones((len(days), 2), dtype=bool)
    adj_close = np.full((len(days), 2), 100.0)
    reaction = int(np.searchsorted(days, np.datetime64("2024-01-16", "D")))
    adj_close[reaction, 0] = 90.0
    versions = [
        _version(date(2023, 3, 31), 100.0, date(2023, 4, 20)),
        _version(date(2023, 6, 30), 100.0, date(2023, 7, 20)),
        _version(date(2023, 9, 30), 100.0, date(2023, 10, 20)),
        _version(date(2023, 12, 31), 50.0, date(2024, 1, 15)),
    ]
    events = event_watch.study_events(
        days, tickers, member, adj_close, [versions, []], "net_income"
    )
    assert len(events) == 1
    assert events[0]["ticker"] == "AAA"
    assert events[0]["reaction_index"] == reaction
    assert events[0]["reaction_return"] == pytest.approx(-0.10)
    assert events[0]["qoq"] == pytest.approx(-0.5)


# Forward excess is the name's return minus the benchmark's over the same window.
def test_forward_excess_subtracts_the_benchmark():
    adj_close = np.asarray(
        [[100.0, 100.0], [110.0, 105.0], [120.0, 110.0]], dtype=float
    )
    assert event_watch.forward_excess(adj_close, 0, 0, 2, 1) == pytest.approx(
        (120.0 / 100.0 - 1.0) - (110.0 / 100.0 - 1.0)
    )
    assert event_watch.forward_excess(adj_close, 2, 0, 2, 1) is None


# The scan row flags a latest release that drops and reacts, with its volume ratio.
def test_scan_name_flags_a_drop_and_reaction():
    days = _days(40)
    adj_close = np.full(len(days), 100.0)
    volume = np.full(len(days), 1_000_000.0)
    reaction = int(np.searchsorted(days, np.datetime64("2024-01-16", "D")))
    adj_close[reaction] = 90.0
    volume[reaction] = 5_000_000.0
    latest = SimpleNamespace(
        reaction_date=date(2024, 1, 16),
        quarter_end=date(2023, 12, 31),
        eps_usd=50.0,
        revenue_usd_m=1_000.0,
        guidance=0.0,
        demand=0.0,
        pricing=0.0,
        capex=0.0,
        supply_constrained=0.0,
    )
    previous = SimpleNamespace(
        reaction_date=date(2023, 10, 17),
        quarter_end=date(2023, 9, 30),
        eps_usd=100.0,
        revenue_usd_m=900.0,
        guidance=1.0,
        demand=1.0,
        pricing=1.0,
        capex=1.0,
        supply_constrained=1.0,
    )
    row = event_watch.scan_name(
        "AAA", "ai", [previous, latest], days, adj_close, volume, "C", None
    )
    assert row["shock"]
    assert row["eps_qoq"] == pytest.approx(-0.5)
    assert row["reaction_return"] == pytest.approx(-0.10)
    assert row["volume_ratio"] == pytest.approx(5.0)
    assert row["tone_change"] == pytest.approx(-5.0)
