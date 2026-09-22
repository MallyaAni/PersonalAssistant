"""The causal entry comparison adapter: fixed levels, parity, path and dedupe.

Synthetic acceptance, per `docs/research/intraday-comparison-protocol-2026-09-22.md`
and COMPARISON_ADAPTER_TASK.md. What has to hold: future daily rows and future
intraday bars cannot change an earlier decision; a partial bar is excluded; a
repeated prefix reads identically; naive and aware New York timestamps agree;
an invalid or gapped completed prefix cannot recommend either method; the fixed
levels stay fixed as the intraday session evolves; zero-variance, insufficient
or invalid daily context is unavailable; unknown or late eligibility blocks a
recommendation; the incumbent's band is exactly the existing bollinger_z on the
last 19 priors plus the observed close times the ratio, and its action is
exactly the existing entry_action; the candidate keeps the engine's causal
path; events do not repeat, do not resurrect and retain a pre-invalidation
event; the regular full-session scope is explicit and a close-time signal never
fabricates a next-session execution.
"""

from datetime import UTC, date, datetime, timedelta
from functools import partial

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.agents.trading.desk.entry import bollinger_z
from backend.market.decision_view import Action, entry_action
from backend.market.intraday_comparison import (
    CANDIDATE,
    ENTRY_READY,
    NOT_ELIGIBLE,
    PRIOR_OBSERVATIONS,
    SCOPE,
    UNAVAILABLE,
    WAIT,
    Comparison,
    DailyRow,
    Eligibility,
    EventLedger,
    compare,
    fixed_levels,
    incumbent_band_z,
    record_event,
)
from backend.market.intraday_entry import (
    Bar,
    session_close_for,
    session_open_for,
)

SESSION = date(2026, 1, 6)
# All original fixtures explicitly express intraday observations in raw units.
compare = partial(compare, price_basis="raw")
# The 20 prior sessions, the day before SESSION, in reverse order on purpose to
# prove the adapter sorts before choosing the most recent 20.
_PRIOR_DATES = [date(2025, 12, 31) - timedelta(days=i) for i in range(30)]


# The standard 20-prior daily history: adjusted closes 100..119 rising in time,
# raw doubles. The input is deliberately reversed so the adapter must sort
# before choosing the most recent 20 and the most recent 19 for the band.
def _history() -> list[DailyRow]:
    """Return 20 prior DailyRows, adjusted 100..119 rising chronologically."""
    dates = sorted(_PRIOR_DATES[:20])
    rows = [
        DailyRow(date=d, close=2.0 * (100.0 + i), adj_close=100.0 + i)
        for i, d in enumerate(dates)
    ]
    return list(reversed(rows))


# The daily history above plus future rows that must never reach validation.
def _future_poisoned_history() -> list[DailyRow]:
    """Return the standard history plus corrupt future rows after the session."""
    return _history() + [
        DailyRow(date=SESSION, close=float("nan"), adj_close=-5.0),
        DailyRow(date=date(2026, 1, 7), close=0.0, adj_close=float("nan")),
        DailyRow(date=SESSION, close=999.0, adj_close=999.0),
    ]


# One regular-session bar at `slot` (0 = 09:30, 1 = 09:45, ...) on SESSION.
def _bar(slot: int, o: float, h: float, lo: float, c: float) -> Bar:
    """Return a 15-minute Bar at the given slot and OHLC on SESSION."""
    start = session_open_for(SESSION) + timedelta(minutes=15 * slot)
    return Bar(start=start, open=o, high=h, low=lo, close=c, volume=100.0)


# The instant a bar's 15-minute window has fully elapsed.
def _completed(slot: int) -> datetime:
    """Return the New York instant the slot's window has elapsed."""
    return session_open_for(SESSION) + timedelta(minutes=15 * (slot + 1))


# The reclaim path: hold above the level, pull back to a setup, reclaim.
def _reclaim_bars(close2: float) -> list[Bar]:
    """Return a path that breaks the level then reclaims with bar 2 closing close2."""
    return [
        _bar(0, 260.0, 262.0, 258.0, 260.0),
        _bar(1, 260.0, 260.0, 238.0, 240.0),
        _bar(2, close2, close2 + 1.0, close2 - 1.0, close2),
    ]


# The rejection path: break the level then close through invalidation.
def _reject_bars() -> list[Bar]:
    """Return a path that breaks the level and then closes through invalidation."""
    return [
        _bar(0, 260.0, 262.0, 258.0, 260.0),
        _bar(1, 260.0, 260.0, 238.0, 240.0),
        _bar(2, 215.0, 216.0, 214.0, 215.0),
    ]


# A full 26-bar session: benign until a late setup and reclaim at the close.
def _close_time_path(close_last: float) -> list[Bar]:
    """Return a full session whose setup and reclaim land on the final bar."""
    bars = [_bar(s, 260.0, 262.0, 258.0, 260.0) for s in range(24)]
    bars.append(_bar(24, 260.0, 260.0, 238.0, 240.0))
    bars.append(_bar(25, close_last, close_last + 1.0, close_last - 1.0, close_last))
    return bars


# The standard eligibility: grade A, not rejecting, known at the session open.
def _eligibility(
    grade: str | None = "A",
    rejecting_band: bool | None = False,
    grade_at: datetime | None = None,
    rejecting_at: datetime | None = None,
) -> Eligibility:
    """Return an Eligibility known by the session open unless overridden."""
    return Eligibility(
        grade=grade,
        grade_available_at=grade_at or session_open_for(SESSION),
        rejecting_band=rejecting_band,
        rejecting_band_available_at=rejecting_at or session_open_for(SESSION),
    )


# The standard live read: the reclaim path observed after bar 2 completes.
def _standard_compare(as_of: datetime | None = None) -> Comparison:
    """Return compare() on the standard reclaim path at the standard time."""
    return compare(
        "AAA",
        SESSION,
        _reclaim_bars(245.0),
        _history(),
        _eligibility(),
        as_of=as_of or _completed(2),
    )


# Fixed levels are exactly the protocol's raw-price mapping of the last 20 priors.
def test_fixed_levels_match_the_protocol_mapping():
    context = fixed_levels(_history(), SESSION)
    adj = np.arange(20, dtype=float) + 100.0
    mean = float(adj.mean())
    std = float(np.std(adj, ddof=0))
    ratio = 119.0 / 238.0
    assert context.mean == pytest.approx(mean)
    assert context.std == pytest.approx(std)
    assert context.ratio == pytest.approx(ratio)
    assert context.observations == PRIOR_OBSERVATIONS
    assert context.levels.level == pytest.approx((mean + 2 * std) / ratio)
    assert context.levels.entry_level == pytest.approx(
        (mean + 2 * std * paper.ENTRY_BAND_Z) / ratio
    )
    assert context.levels.invalidation_level == pytest.approx(mean / ratio)
    # The band is ordered for the reclaim rule: invalidation < level < entry.
    assert (
        context.levels.invalidation_level
        < context.levels.level
        < context.levels.entry_level
    )


# Future daily rows are removed before validation, so corruption there is inert.
def test_future_daily_rows_never_change_the_fixed_levels():
    clean = fixed_levels(_history(), SESSION)
    poisoned = fixed_levels(_future_poisoned_history(), SESSION)
    assert clean == poisoned


# A duplicate date or a corrupt row inside the used window is unavailable.
def test_invalid_daily_context_is_unavailable():
    dup = _history() + [DailyRow(date=_PRIOR_DATES[0], close=1.0, adj_close=1.0)]
    with pytest.raises(ValueError, match="duplicate dates"):
        fixed_levels(dup, SESSION)
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(245.0), dup, _eligibility(), _completed(2)
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert cmp.incumbent.state == UNAVAILABLE
    assert cmp.candidate.state == UNAVAILABLE
    assert "duplicate dates" in cmp.incumbent.reason


# Fewer than 20 prior sessions is unavailable, not a short-band fallback.
def test_insufficient_history_is_unavailable():
    short = _history()[:19]
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(245.0), short, _eligibility(), _completed(2)
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert "daily context unavailable" in cmp.candidate.reason


# A zero-variance adjusted window cannot fix a band and is unavailable.
def test_zero_variance_context_is_unavailable():
    flat = [DailyRow(date=d, close=100.0, adj_close=100.0) for d in _PRIOR_DATES[:20]]
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(245.0), flat, _eligibility(), _completed(2)
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert "standard deviation" in cmp.candidate.reason


# A non-positive raw close makes the adjustment ratio unusable: unavailable.
def test_non_positive_raw_close_is_unavailable():
    bad = list(_history())
    bad[-1] = DailyRow(date=bad[-1].date, close=0.0, adj_close=bad[-1].adj_close)
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(245.0), bad, _eligibility(), _completed(2)
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert "raw close" in cmp.candidate.reason


# A corrupt row inside the used 20 is unavailable, never silently dropped.
def test_corrupt_prior_row_is_unavailable():
    bad = list(_history())
    bad[10] = DailyRow(date=bad[10].date, close=float("nan"), adj_close=100.0)
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(245.0), bad, _eligibility(), _completed(2)
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert "daily context unavailable" in cmp.candidate.reason


# The incumbent band is exactly the existing bollinger_z on prior19 + close*r.
def test_incumbent_band_parity_with_existing_bollinger_z():
    observed = 245.0
    prior = sorted((r for r in _history() if r.date < SESSION), key=lambda r: r.date)
    ratio = prior[-1].adj_close / prior[-1].close
    series = np.array(
        [row.adj_close for row in prior[-19:]] + [observed * ratio], dtype=float
    )
    expected = float(bollinger_z(series.reshape(-1, 1))[-1, 0])
    assert incumbent_band_z(_history(), SESSION, observed) == pytest.approx(expected)
    assert incumbent_band_z(_history(), SESSION, None) is None


# The incumbent band is dynamic: it includes the observed close, not the prior
# day's frozen band, so the protocol's no-frozen-band rule holds.
def test_incumbent_band_is_not_a_frozen_prior_day_band():
    prior = sorted((r for r in _history() if r.date < SESSION), key=lambda r: r.date)
    frozen_series = np.array([r.adj_close for r in prior[-20:]], dtype=float).reshape(
        -1, 1
    )
    frozen_z = float(bollinger_z(frozen_series)[-1, 0])
    dynamic = incumbent_band_z(_history(), SESSION, 245.0)
    assert dynamic != pytest.approx(frozen_z)
    # The same observed close read the incumbent dynamically at a much higher
    # close moves, while the frozen band stays put.
    assert incumbent_band_z(_history(), SESSION, 260.0) > dynamic


# The incumbent action is exactly the existing entry_action at the band reading.
def test_incumbent_action_parity_with_existing_entry_action():
    row = {"rejecting_band": False}
    for observed in (240.0, 245.0, 248.7, 250.0, 260.0):
        band = incumbent_band_z(_history(), SESSION, observed)
        result = entry_action(row, band, "A", 0.0)
        expected = result is not None and result[0] == Action.BUY
        cmp = compare(
            "AAA",
            SESSION,
            _reclaim_bars(observed),
            _history(),
            _eligibility(),
            _completed(2),
        )
        assert cmp.incumbent.readiness is expected, observed
        if expected:
            assert cmp.incumbent.state == ENTRY_READY
        elif band is not None and band < paper.ENTRY_BAND_Z:
            assert cmp.incumbent.state == WAIT


# The candidate matches the reviewed engine exactly, path for path.
def test_candidate_matches_the_engine_on_the_same_prefix():
    bars = _reclaim_bars(245.0)
    cmp = compare("AAA", SESSION, bars, _history(), _eligibility(), _completed(2))
    from backend.market.intraday_entry import evaluate

    levels = fixed_levels(_history(), SESSION).levels
    signal = evaluate("AAA", SESSION, bars, levels, _completed(2))
    assert cmp.candidate.state == signal.state
    assert cmp.candidate.reason == signal.reason
    assert cmp.candidate.trigger_time == signal.trigger_time
    assert cmp.candidate.trigger_bar_start == signal.trigger_bar_start
    assert cmp.candidate.trigger_price == signal.trigger_price
    assert cmp.candidate.identity == "raw:" + signal.identity


# Both methods receive the same observed completed prefix.
def test_both_methods_receive_the_same_observed_prefix():
    cmp = _standard_compare()
    assert cmp.observed_close == pytest.approx(245.0)
    assert (
        cmp.incumbent.observed_close
        == cmp.candidate.observed_close
        == cmp.observed_close
    )
    assert cmp.incumbent.band_z == cmp.candidate.band_z == cmp.band_z


# The candidate is path-sensitive: reclaim is ready, rejection is not, on the
# same daily OHLC.
def test_candidate_is_path_sensitive():
    reclaim = _standard_compare()
    reject = compare(
        "AAA", SESSION, _reject_bars(), _history(), _eligibility(), _completed(2)
    )
    assert reclaim.candidate.readiness is True
    assert reclaim.candidate.state == ENTRY_READY
    assert reject.candidate.readiness is False
    assert reject.candidate.state == "invalidated"


# The candidate's fixed entry level can fire where the incumbent's dynamic
# band has not yet reached its threshold.
def test_candidate_ready_where_incumbent_is_not():
    cmp = _standard_compare()  # observed close 245: >= fixed entry, band_z ~0.99
    assert cmp.candidate.readiness is True
    assert cmp.incumbent.readiness is False
    assert cmp.incumbent.state == WAIT
    assert cmp.candidate.trigger_price == pytest.approx(245.0)


# At a stronger close both methods are ready.
def test_both_methods_ready_at_a_stronger_close():
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(250.0), _history(), _eligibility(), _completed(2)
    )
    assert cmp.candidate.readiness is True
    assert cmp.incumbent.readiness is True
    assert cmp.incumbent.state == ENTRY_READY


# Future intraday bars (not yet completed) cannot change an earlier decision,
# even when the later bar would be corrupt or would invalidate.
def test_future_intraday_bars_cannot_change_an_earlier_decision():
    prefix = _reclaim_bars(245.0)
    early = compare("AAA", SESSION, prefix, _history(), _eligibility(), _completed(2))
    # A corrupt bar and an invalidating bar, both not yet completed at 10:00.
    poisoned = prefix + [
        _bar(5, 0.0, -1.0, -5.0, -3.0),
        _bar(6, 1000.0, 1000.0, 96.0, 96.0),
    ]
    late = compare("AAA", SESSION, poisoned, _history(), _eligibility(), _completed(2))
    assert early == late


# A partial (not yet elapsed) bar is excluded and cannot trigger either method.
def test_partial_bar_is_excluded():
    full = _reclaim_bars(245.0)
    # A fourth bar whose window has not elapsed by the observation time.
    with_bar = full + [_bar(3, 1000.0, 1001.0, 999.0, 1000.0)]
    a = compare("AAA", SESSION, full, _history(), _eligibility(), _completed(2))
    b = compare("AAA", SESSION, with_bar, _history(), _eligibility(), _completed(2))
    assert a == b


# Repeated reads of the same prefix give identical observations.
def test_repeated_prefix_is_identical():
    a = _standard_compare()
    b = _standard_compare()
    assert a == b
    assert a.candidate.identity == b.candidate.identity
    assert a.incumbent.identity == b.incumbent.identity


# Naive and aware New York timestamps decide identically.
def test_timezone_conversion_is_consistent():
    aware = _completed(2)
    naive = datetime(2026, 1, 6, 10, 15)
    a = _standard_compare(as_of=aware)
    b = _standard_compare(as_of=naive)
    assert a == b
    # A UTC-tagged instant at the same New York wall clock also agrees.
    utc = aware.astimezone(UTC)
    c = _standard_compare(as_of=utc)
    assert a == c


# A gapped or off-grid completed prefix cannot recommend either method.
def test_gapped_completed_prefix_cannot_recommend_either_method():
    bars = _reclaim_bars(245.0)
    gapped = [bars[0], bars[2]]  # missing the 09:45 bar
    cmp = compare("AAA", SESSION, gapped, _history(), _eligibility(), _completed(2))
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert cmp.incumbent.state == UNAVAILABLE
    assert cmp.candidate.state == UNAVAILABLE


# The fixed levels stay fixed as the intraday session evolves.
def test_fixed_levels_remain_fixed_as_intraday_evolves():
    early = _standard_compare(as_of=_completed(1))
    late = _standard_compare(as_of=_completed(2))
    assert early.levels == late.levels == fixed_levels(_history(), SESSION).levels


# Full-day completeness never filters a prefix: a partial prefix read inside a
# longer stream is identical to reading that prefix alone.
def test_full_day_completeness_never_filters_a_prefix():
    prefix = _reclaim_bars(245.0)
    # A full 26-bar session whose first three bars match the prefix exactly.
    full_session = list(prefix) + [
        _bar(s, 260.0, 262.0, 258.0, 260.0) for s in range(3, 26)
    ]
    # Prefix-only at 10:00 equals the same prefix inside the full-session stream
    # at the same time, because later bars are not yet completed.
    a = compare("AAA", SESSION, prefix, _history(), _eligibility(), _completed(2))
    b = compare("AAA", SESSION, full_session, _history(), _eligibility(), _completed(2))
    assert a == b


# Unknown or late eligibility blocks a recommendation for both methods.
@pytest.mark.parametrize(
    "eligibility",
    [
        Eligibility(None, session_open_for(SESSION), False, session_open_for(SESSION)),
        Eligibility("A", None, False, session_open_for(SESSION)),
        Eligibility("A", session_open_for(SESSION), None, session_open_for(SESSION)),
        Eligibility("A", session_open_for(SESSION), False, None),
    ],
)
def test_unknown_eligibility_blocks_both_methods(eligibility):
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(250.0), _history(), eligibility, _completed(2)
    )
    assert not cmp.candidate.readiness
    assert not cmp.incumbent.readiness
    assert cmp.candidate.state == NOT_ELIGIBLE
    assert cmp.incumbent.state == NOT_ELIGIBLE


# Eligibility learned after the observation time cannot retroactively enable it.
def test_eligibility_learned_after_as_of_blocks_both_methods():
    late = _eligibility(grade_at=_completed(3))
    cmp = compare("AAA", SESSION, _reclaim_bars(250.0), _history(), late, _completed(2))
    assert not cmp.candidate.readiness
    assert not cmp.incumbent.readiness
    assert cmp.candidate.state == NOT_ELIGIBLE
    # Once it is known, the same prefix becomes recommendable.
    known = _eligibility(grade_at=_completed(2))
    ok = compare("AAA", SESSION, _reclaim_bars(250.0), _history(), known, _completed(2))
    assert ok.candidate.readiness is True
    assert ok.incumbent.readiness is True


# A rejecting-band daily blocks both methods, as the common gate does.
def test_rejecting_band_blocks_both_methods():
    rejecting = _eligibility(rejecting_band=True)
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(250.0), _history(), rejecting, _completed(2)
    )
    assert not cmp.candidate.readiness
    assert not cmp.incumbent.readiness
    assert cmp.candidate.state == NOT_ELIGIBLE


# A grade below the entry requirement blocks both methods.
def test_low_grade_blocks_both_methods():
    low = _eligibility(grade="B")
    cmp = compare("AAA", SESSION, _reclaim_bars(250.0), _history(), low, _completed(2))
    assert not cmp.candidate.readiness
    assert not cmp.incumbent.readiness
    assert cmp.candidate.state == NOT_ELIGIBLE


# Events: first eligible entry recorded once, repeats are not new events.
def test_events_record_only_the_first_eligible_entry():
    ledger: EventLedger = EventLedger()
    cmp = _standard_compare()
    ledger, event, new = record_event(ledger, cmp.candidate)
    assert new is True
    assert event is not None
    assert event.method == CANDIDATE
    # A repeated read of the same prefix is not a new event.
    ledger, again, new = record_event(ledger, cmp.candidate)
    assert new is False
    assert again is event
    # Both methods are separate keys.
    ledger, inc, inc_new = record_event(ledger, cmp.incumbent)
    assert inc is None
    assert inc_new is False  # incumbent not ready here


# Events: a later invalidation never erases the recorded event.
def test_events_retain_a_pre_invalidation_event():
    ledger: EventLedger = EventLedger()
    ready = _standard_compare()
    ledger, event, new = record_event(ledger, ready.candidate)
    assert new is True
    # The same session later invalidates, but the recorded event survives.
    invalid = compare(
        "AAA", SESSION, _reject_bars(), _history(), _eligibility(), _completed(3)
    )
    ledger, later, new = record_event(ledger, invalid.candidate)
    assert later is event
    assert new is False
    assert event.trigger_price == pytest.approx(245.0)


# Events: a new session is independently eligible.
def test_events_new_session_is_independently_eligible():
    ledger: EventLedger = EventLedger()
    first = _standard_compare()
    ledger, first_event, _ = record_event(ledger, first.candidate)
    next_session = date(2026, 1, 7)
    next_open = session_open_for(next_session)
    bars = [
        Bar(next_open + timedelta(minutes=15 * s), o, h, lo, c, 100.0)
        for s, (o, h, lo, c) in enumerate(
            [
                (260.0, 262.0, 258.0, 260.0),
                (260.0, 260.0, 238.0, 240.0),
                (245.0, 246.0, 244.0, 245.0),
            ]
        )
    ]
    second = compare(
        "AAA",
        next_session,
        bars,
        _history(),
        _eligibility(),
        next_open + timedelta(minutes=45),
    )
    ledger, second_event, new = record_event(ledger, second.candidate)
    assert new is True
    assert second_event is not first_event
    assert second_event.session == next_session


# Events: a not-ready observation records nothing.
def test_events_do_not_record_an_unready_observation():
    ledger: EventLedger = EventLedger()
    cmp = compare(
        "AAA", SESSION, _reclaim_bars(240.0), _history(), _eligibility(), _completed(2)
    )
    assert cmp.candidate.readiness is False
    ledger, event, new = record_event(ledger, cmp.candidate)
    assert new is False
    assert event is None


# The regular full-session scope is explicit and a close-time signal never
# fabricates a next-session execution.
def test_full_session_scope_and_close_time_never_reach_the_next_session():
    assert "09:30-16:00" in SCOPE
    assert "regular full sessions" in SCOPE
    # A reclaim confirmed on the final bar resolves at 16:00 of THIS session.
    path = _close_time_path(250.0)
    cmp = compare(
        "AAA", SESSION, path, _history(), _eligibility(), session_close_for(SESSION)
    )
    assert cmp.candidate.session == SESSION
    assert cmp.candidate.trigger_time is not None
    assert "16:00" in cmp.candidate.trigger_time
    # The session is already closed at the decision, so the engine reports the
    # entry as historical: recorded for replay, never an actionable next-session
    # execution.
    assert cmp.candidate.state == "historical"
    assert cmp.candidate.readiness is False
    # An intraday signal before the close is this session's, never the next's.
    mid = compare(
        "AAA", SESSION, _reclaim_bars(250.0), _history(), _eligibility(), _completed(2)
    )
    assert mid.candidate.session == SESSION
    assert mid.candidate.readiness is True
