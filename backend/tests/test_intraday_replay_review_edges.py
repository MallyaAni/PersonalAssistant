"""Independent acceptance for replay timing, denominators and outcome coverage."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from backend.market.intraday_comparison import CANDIDATE, Eligibility
from backend.market.intraday_entry import NEW_YORK, session_open_for
from backend.market.intraday_replay import (
    ENDPOINT_IMMATURE,
    ENDPOINT_MISSING,
    EXECUTION_UNKNOWN,
    RECORDED_ELIGIBILITY,
    eligibility_at,
    endpoint_label,
    execution_proxy,
    replay_session,
    replay_session_outcome,
    session_after,
    summarize,
)
from backend.tests.test_intraday_replay import (
    SESSION,
    _bars_through,
    _entry_bars,
    _full_day,
    _history,
    _schedule,
    _timeline,
)


# Supply identical synthetic causal observations to both entry components.
def _kwargs(bars=None):
    return dict(
        symbol="AAA",
        session=SESSION,
        bars=_entry_bars(SESSION, 250) if bars is None else bars,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
    )


# The expected observation clock exists even when a feed bar is absent.
def test_missing_and_other_day_bars_do_not_change_session_clock():
    bars = _entry_bars(SESSION, 250)
    result = replay_session(
        **_kwargs(bars[:-1] + _full_day(SESSION + timedelta(days=1), 300))
    )
    expected = tuple(
        session_open_for(SESSION) + timedelta(minutes=15 * n) for n in range(1, 27)
    )
    assert tuple(o.time for o in result.observations) == expected
    assert not result.observations[-1].comparison.candidate.readiness
    assert len(replay_session(**_kwargs([])).observations) == 26


# Duplicate execution prints cannot be arbitrarily selected as the next open.
def test_duplicate_execution_bar_stays_unknown():
    bars = _entry_bars(SESSION, 250)
    event = replay_session(**_kwargs(bars)).events[CANDIDATE]
    duplicate = next(b for b in bars if b.start.isoformat() == event.observation_time)
    proxy = execution_proxy(
        bars + [replace(duplicate, open=duplicate.open + 0.5)], event
    )
    assert proxy.status == EXECUTION_UNKNOWN
    assert proxy.price is None


# A synthetic or malformed close-time event cannot fill in extended hours.
def test_execution_requires_regular_same_session_time():
    bars = _entry_bars(SESSION, 250)
    event = replay_session(**_kwargs()).events[CANDIDATE]
    at_close = session_open_for(SESSION) + timedelta(hours=6, minutes=30)
    event = replace(event, observation_time=at_close.isoformat())
    proxy = execution_proxy([replace(bars[-1], start=at_close)], event)
    assert proxy.status == EXECUTION_UNKNOWN


# Partially known newer eligibility must not resurrect an older ready grade.
def test_newer_unknown_common_gate_blocks_prior_eligibility():
    early = _timeline()[0]
    instant = session_open_for(SESSION) + timedelta(minutes=30)
    newer = Eligibility("B", instant, None, None)
    selected = eligibility_at([early, newer], instant)
    assert selected is not None
    assert selected.grade == "B"
    assert selected.rejecting_band is None


# Caller-supplied overrides must not silently relabel different outcomes as20/5.
def test_horizons_cannot_be_changed_through_public_replay():
    with pytest.raises(ValueError, match="horizon"):
        replay_session_outcome(**_kwargs(), outcome_bars={}, primary=1)


# A repeated opportunity cannot inflate the common denominator.
def test_summary_rejects_duplicate_symbol_session():
    outcome = replay_session_outcome(**_kwargs(), outcome_bars={})
    with pytest.raises(ValueError, match="duplicate"):
        summarize([outcome, outcome], mode=RECORDED_ELIGIBILITY, price_basis="raw")


# Waiting misses incumbent-only entries; retain their incumbent return context.
def test_missed_waiting_opportunities_have_incumbent_outcomes():
    outcome = replay_session_outcome(
        **_kwargs(_full_day(SESSION, 260)),
        outcome_bars=_bars_through(SESSION, _schedule()),
    )
    assert outcome.incumbent.event is not None
    assert outcome.candidate.event is None
    summary = summarize([outcome], mode=RECORDED_ELIGIBILITY, price_basis="raw")
    assert summary.missed_opportunity_count == 1
    assert summary.missed_opportunity_incumbent_primary.count == 1
    assert summary.missed_opportunity_incumbent_primary.mean == pytest.approx(0)


# Dataset availability, rather than future rows or a symbol's last row, sets maturity.
def test_explicit_data_as_of_blocks_future_labels_and_distinguishes_missing():
    schedule = _schedule()
    end = session_after(schedule, SESSION, 5)[0]
    before_close = datetime.combine(end, datetime.min.time(), NEW_YORK) + timedelta(
        hours=15
    )
    future = _bars_through(SESSION, schedule)
    immature = endpoint_label(
        schedule=schedule,
        outcome_bars=future,
        entry_session=SESSION,
        horizon=5,
        execution_price=250,
        data_as_of=before_close,
    )
    assert immature.status == ENDPOINT_IMMATURE
    assert immature.forward_return is None
    missing = endpoint_label(
        schedule=schedule,
        outcome_bars={SESSION: _full_day(SESSION, 250)},
        entry_session=SESSION,
        horizon=5,
        execution_price=250,
        data_as_of=before_close + timedelta(hours=2),
    )
    assert missing.status == ENDPOINT_MISSING
    assert missing.available_at == datetime.combine(
        end, datetime.min.time(), NEW_YORK
    ) + timedelta(hours=16)


# Paired execution-price improvement must be comparable across stock price scales.
def test_paired_price_improvement_has_relative_units():
    outcome = replay_session_outcome(**_kwargs(), outcome_bars={})
    assert outcome.incumbent.event is not None
    candidate = replace(
        outcome.candidate, execution=replace(outcome.candidate.execution, price=100)
    )
    incumbent = replace(
        outcome.incumbent, execution=replace(outcome.incumbent.execution, price=110)
    )
    summary = summarize(
        [replace(outcome, candidate=candidate, incumbent=incumbent)],
        mode=RECORDED_ELIGIBILITY,
        price_basis="raw",
    )
    assert summary.paired_entry_price_improvement == pytest.approx(10 / 110)
