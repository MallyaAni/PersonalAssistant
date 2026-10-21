"""The board's market clock: phase, next action, next plan."""

from datetime import UTC, datetime

from backend.market import market_phase


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


# During the regular session the desk acts now and the next plan is tonight.
def test_regular_session_acts_now():
    now = _at("2026-09-24T10:00:00-04:00")
    phase = market_phase.describe(now)
    assert phase["phase"] == "regular"
    assert phase["acts_in"] == "regular_session"
    assert phase["next_action_at"] == now.isoformat()
    assert phase["next_open_at"] == "2026-09-25T09:30:00-04:00"
    assert phase["next_publication_at"] == "2026-09-24T19:30:00-04:00"


# After the close and before the brokers' 20:00 cutoff the phase is
# after-hours; the desk's next action is the next open.
def test_after_hours_points_at_the_next_open():
    phase = market_phase.describe(_at("2026-09-24T18:45:00-04:00"))
    assert phase["phase"] == "after_hours"
    assert phase["next_action_at"] == "2026-09-25T09:30:00-04:00"
    assert phase["next_publication_at"] == "2026-09-24T19:30:00-04:00"


# Past 20:00 the night is overnight, and tonight's plan is already behind us,
# so the next publication is tomorrow's.
def test_overnight_names_tomorrows_publication():
    phase = market_phase.describe(_at("2026-09-24T21:00:00-04:00"))
    assert phase["phase"] == "overnight"
    assert phase["next_action_at"] == "2026-09-25T09:30:00-04:00"
    assert phase["next_publication_at"] == "2026-09-25T19:30:00-04:00"


# Before the open the next action is today's open, not tomorrow's.
def test_pre_market_points_at_todays_open():
    phase = market_phase.describe(_at("2026-09-24T08:00:00-04:00"))
    assert phase["phase"] == "pre_market"
    assert phase["next_action_at"] == "2026-09-24T09:30:00-04:00"
    assert phase["next_open_at"] == "2026-09-24T09:30:00-04:00"


# Friday evening the next open is Monday, and a published holiday is skipped.
def test_weekend_and_holiday_skip_to_the_next_reviewed_session():
    friday = market_phase.describe(_at("2026-09-25T18:00:00-04:00"))
    assert friday["phase"] == "after_hours"
    assert friday["next_open_at"] == "2026-09-28T09:30:00-04:00"
    thanksgiving = market_phase.describe(datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
    assert thanksgiving["phase"] == "closed"
    assert thanksgiving["is_session"] is False
    assert thanksgiving["next_open_at"] == "2026-11-27T09:30:00-05:00"
    assert thanksgiving["next_action_at"] == "2026-11-27T09:30:00-05:00"


# Outside the reviewed years the clock fails closed rather than guessing.
def test_unreviewed_years_fail_closed():
    phase = market_phase.describe(_at("2099-03-02T10:00:00-05:00"))
    assert phase["phase"] == "unknown"
    assert phase["next_open_at"] is None
    assert phase["next_action_at"] is None


# Before the brokers' 04:00 pre-market open, a session day is still overnight,
# and the next action is that day's open.
def test_the_small_hours_of_a_session_day_are_overnight():
    phase = market_phase.describe(_at("2026-09-24T00:30:00-04:00"))
    assert phase["phase"] == "overnight"
    assert phase["is_session"] is True
    assert phase["next_action_at"] == "2026-09-24T09:30:00-04:00"
    assert phase["next_publication_at"] == "2026-09-24T19:30:00-04:00"
