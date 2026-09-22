"""Additional clock and partially published gate acceptance after worker review."""

from dataclasses import replace
from datetime import timedelta

import pytest

from backend.market.intraday_comparison import CANDIDATE, Eligibility
from backend.market.intraday_entry import session_open_for
from backend.market.intraday_replay import (
    EXECUTION_UNKNOWN,
    RECORDED_ELIGIBILITY,
    eligibility_at,
    execution_proxy,
    replay_session,
    replay_session_outcome,
)
from backend.tests.test_intraday_replay import (
    SESSION,
    _entry_bars,
    _history,
    _schedule,
    _timeline,
)


# Supply the reviewed synthetic path without changing any trading threshold.
def _kwargs():
    return dict(
        symbol="AAA",
        session=SESSION,
        bars=_entry_bars(SESSION, 250),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
    )


# A newly published rejection gate with unknown grade must block stale eligibility.
def test_new_rejection_with_missing_grade_publication_blocks_old_grade():
    at = session_open_for(SESSION) + timedelta(minutes=45)
    unknown_grade = Eligibility(None, None, True, at)
    selected = eligibility_at([*_timeline(), unknown_grade], at)
    assert selected == unknown_grade


# Arbitrary microseconds cannot qualify as a bar boundary for the proxy.
def test_subsecond_observation_does_not_execute():
    args = _kwargs()
    event = replay_session(**args).events[CANDIDATE]
    bar = args["bars"][3]
    stamp = bar.start + timedelta(microseconds=1)
    event = replace(event, observation_time=stamp.isoformat())
    assert (
        execution_proxy([replace(bar, start=stamp)], event).status == EXECUTION_UNKNOWN
    )


# Historical full-session replay refuses an as-of before the entry day closed.
def test_dataset_as_of_cannot_observe_future_entry_bars():
    with pytest.raises(ValueError, match="entry session"):
        replay_session_outcome(
            **_kwargs(),
            outcome_bars={},
            data_as_of=session_open_for(SESSION) + timedelta(minutes=15),
        )
