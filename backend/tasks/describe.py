"""A task's schedule in words a person reads, from its stored columns."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


# "7:00 AM" from stored hour and minute.
def clock(hour: int, minute: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    shown = hour % 12 or 12
    return f"{shown}:{minute:02d} {suffix}"


# "every weekday at 7:00 AM" / "on Friday 2026-08-28 at 9:00 AM" and so on.
def schedule_phrase(task: dict[str, Any]) -> str:
    at = clock(int(task["hour"]), int(task["minute"]))
    cadence = str(task["cadence"])
    if cadence == "daily":
        return f"every day at {at}"
    if cadence == "weekdays":
        return f"every weekday at {at}"
    if cadence == "weekly":
        return f"every {_WEEKDAYS[int(task.get('weekday') or 0)]} at {at}"
    on_date = str(task.get("on_date") or "")
    return f"once on {on_date} at {at}" if on_date else f"once at {at}"


# The next firing as local wall-clock, or "" when the task has none.
def next_run_phrase(task: dict[str, Any]) -> str:
    moment = task.get("next_run_at")
    if not isinstance(moment, datetime):
        return ""
    try:
        local = moment.astimezone(ZoneInfo(str(task.get("timezone") or "UTC")))
    except Exception:
        local = moment
    return (
        f"{_WEEKDAYS[local.weekday()]} {local:%Y-%m-%d} at "
        f"{clock(local.hour, local.minute)} ({task.get('timezone') or 'UTC'})"
    )


# One line: what it does and when.
def describe_task(task: dict[str, Any]) -> str:
    # A one-off that has fired is disabled by the runner; described as
    # "(paused)" it read as still waiting - "the trivia reminder's still
    # sitting there at 6pm today", the morning after it fired (2026-09-03).
    if task.get("enabled", True):
        state = ""
    elif str(task.get("cadence") or "") == "once" and task.get("next_run_at") is None:
        state = " (done - it has fired)"
    else:
        state = " (paused)"
    return f'"{task["instruction"]}" - {schedule_phrase(task)}{state}'
