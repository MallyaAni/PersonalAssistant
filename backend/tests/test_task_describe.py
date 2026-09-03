"""A one-off reminder that has fired reads as done, not as paused."""
from backend.tasks.describe import describe_task


def test_a_fired_one_off_is_done_and_a_paused_daily_is_paused():
    fired = {"instruction": "Remind me about trivia at Courthouse Social today", "cadence": "once", "hour": 18, "minute": 0, "on_date": "2026-09-02", "enabled": False, "next_run_at": None}
    assert describe_task(fired).endswith("once on 2026-09-02 at 6:00 PM (done - it has fired)")
    paused = {"instruction": "chess tip", "cadence": "daily", "hour": 9, "minute": 0, "enabled": False, "next_run_at": None}
    assert describe_task(paused).endswith("every day at 9:00 AM (paused)")
    live = {"instruction": "chess tip", "cadence": "daily", "hour": 9, "minute": 0, "enabled": True}
    assert describe_task(live).endswith("every day at 9:00 AM")
