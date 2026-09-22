"""Independent review of units, closed sessions and recorded availability."""

from dataclasses import replace
from datetime import timedelta

import pytest

from backend.market import intraday_comparison as c
from backend.market.intraday_entry import session_close_for
from backend.tests.test_intraday_comparison import (
    SESSION,
    _close_time_path,
    _completed,
    _eligibility,
    _history,
    _reclaim_bars,
)


# Historical evaluation must never become a fresh entry for either method.
@pytest.mark.parametrize("offset", [None, 0, 15])
def test_closed_session_neither_method_is_ready(offset):
    at = (
        None
        if offset is None
        else session_close_for(SESSION) + timedelta(minutes=offset)
    )
    result = c.compare(
        "AAA",
        SESSION,
        _close_time_path(260),
        _history(),
        _eligibility(),
        at,
        price_basis="raw",
    )
    assert result.incumbent.readiness is False
    assert result.candidate.readiness is False
    _, event, new = c.record_event(c.EventLedger(), result.incumbent)
    assert event is None
    assert new is False


# Availability uses the documented New York convention even for naive inputs.
def test_naive_availability_is_same_instant_as_aware():
    known = _eligibility()
    naive = replace(
        known,
        grade_available_at=known.grade_available_at.replace(tzinfo=None),
        rejecting_band_available_at=known.rejecting_band_available_at.replace(
            tzinfo=None
        ),
    )
    args = ("AAA", SESSION, _reclaim_bars(260), _history())
    assert c.compare(*args, naive, _completed(2), price_basis="raw") == c.compare(
        *args, known, _completed(2), price_basis="raw"
    )


# Comparable economic paths use explicitly declared price coordinates.
def test_raw_and_adjusted_paths_have_equal_signals_and_band():
    raw_bars = _reclaim_bars(260)
    adjusted = [
        replace(b, open=b.open / 2, high=b.high / 2, low=b.low / 2, close=b.close / 2)
        for b in raw_bars
    ]
    raw = c.compare(
        "AAA",
        SESSION,
        raw_bars,
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="raw",
    )
    adj = c.compare(
        "AAA",
        SESSION,
        adjusted,
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="adjusted",
    )
    assert raw.band_z == pytest.approx(adj.band_z)
    assert raw.levels.level / 2 == pytest.approx(adj.levels.level)
    for name in ("incumbent", "candidate"):
        r, a = getattr(raw, name), getattr(adj, name)
        assert (r.readiness, r.state) == (a.readiness, a.state)
        assert r.price_basis == "raw"
        assert a.price_basis == "adjusted"
        assert r.identity != a.identity
        ledger, event, new = c.record_event(c.EventLedger(), r)
        assert new
        assert event.price_basis == "raw"
        with pytest.raises(ValueError, match="basis"):
            c.record_event(ledger, a)


# Missing or contradictory basis declarations fail before any scoring can occur.
@pytest.mark.parametrize("basis", [None, "mixed", "unadjusted_guess"])
def test_unknown_price_basis_is_rejected(basis):
    with pytest.raises(ValueError, match="basis"):
        c.compare(
            "AAA",
            SESSION,
            _reclaim_bars(260),
            _history(),
            _eligibility(),
            _completed(2),
            price_basis=basis,
        )


# A caller cannot accidentally take a default scale when its data is unlabelled.
def test_omitted_basis_is_rejected():
    with pytest.raises(ValueError, match="basis"):
        c.compare(
            "AAA",
            SESSION,
            _reclaim_bars(260),
            _history(),
            _eligibility(),
            _completed(2),
        )


# A record's later publication cannot authorize an earlier observation or event.
def test_late_record_uses_observation_time_in_event():
    published = _completed(2) + timedelta(minutes=3)
    eligibility = replace(_eligibility(), grade_available_at=published)
    bars = _reclaim_bars(260)
    before = c.compare(
        "AAA", SESSION, bars, _history(), eligibility, _completed(2), price_basis="raw"
    )
    assert not before.incumbent.readiness
    assert not before.candidate.readiness
    bars.append(replace(bars[-1], start=bars[-1].start + timedelta(minutes=15)))
    after = c.compare(
        "AAA", SESSION, bars, _history(), eligibility, _completed(3), price_basis="raw"
    )
    _, event, new = c.record_event(c.EventLedger(), after.candidate)
    assert new
    assert event.observation_time == _completed(3).isoformat(timespec="seconds")
    assert event.trigger_time != event.observation_time
