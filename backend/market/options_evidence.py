"""Date stored option OI calculations without claiming current OI or dealer gamma.

This is a display-only projection. Raw snapshots remain unchanged; legacy
calculations without a recorded raw-price basis do not supply displayed levels.
"""

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from numbers import Real
from zoneinfo import ZoneInfo

from backend.market import options

CALCULATION_VERSION = "raw-option-oi-levels/1"
NEW_YORK = ZoneInfo("America/New_York")


# Accept only explicit timezone-aware observations and normalize them to UTC.
def _timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


# Preserve only canonical calendar dates, never a guessed date or datetime prefix.
def _date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


# Require a finite JSON-like number without treating Boolean flags as measurements.
def _number(value) -> bool:
    try:
        return (
            isinstance(value, Real)
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    except (ValueError, OverflowError):
        return False


# State the exact option-selection parameters used by this calculation version.
def method() -> dict:
    return {
        "min_days": 1,
        "max_days": options.WALL_DAYS,
        "strike_range_fraction": options.WALL_RANGE,
        "min_open_interest": options.MIN_WALL_OI,
    }


# Record the raw reference and expiry-selection date, not a calculation-time clock.
def calculation(price, today, reference_session, reference_bar_start) -> dict:
    bar = _timestamp(reference_bar_start)
    return {
        "version": CALCULATION_VERSION,
        "date": today.isoformat(),
        "reference_price": price,
        "reference_basis": "raw_panel_close",
        "reference_session": reference_session,
        "reference_bar_start": bar.isoformat() if bar else None,
        "method": method(),
    }


# Report collection age separately from the unrecorded effective time of open interest.
def _collection(walls: Mapping, now: datetime) -> dict:
    value = walls.get("fetched_at")
    collected = _timestamp(value)
    status = "missing" if value is None else "invalid"
    age = None
    if collected is not None:
        status = "future" if collected > now else "recorded"
        if status == "recorded":
            age = (now - collected).total_seconds()
    return {
        "checked_at": now.isoformat(),
        "collected_at": collected.isoformat() if collected else None,
        "collection_status": status,
        "collection_age_seconds": age,
        "oi_effective_at": None,
        "oi_freshness": "unknown",
    }


# Validate each stored OI level against its dated reference price and declared method.
def _levels(walls: Mapping, price, expiry, expected: dict) -> dict | None:
    result = {}
    for side in ("put", "call"):
        level = walls.get(f"{side}_wall")
        oi = walls.get(f"{side}_wall_oi")
        distance = walls.get(f"{side}_wall_distance")
        if not _number(oi) or oi < 0 or oi != int(oi):
            return None
        if level is None:
            if oi != 0 or distance is not None:
                return None
        else:
            if not _number(level) or level <= 0 or expiry is None:
                return None
            ratio = level / price
            actual_distance = ratio - 1.0
            lo, hi = (
                (price * (1.0 - expected["strike_range_fraction"]), price)
                if side == "put"
                else (price, price * (1.0 + expected["strike_range_fraction"]))
            )
            if (
                oi < expected["min_open_interest"]
                or not lo <= level <= hi
                or not _number(distance)
                or not math.isclose(
                    distance, actual_distance, rel_tol=1e-9, abs_tol=1e-12
                )
            ):
                return None
        result[f"{side}_level"] = level
        result[f"{side}_oi"] = int(oi)
        result[f"{side}_distance"] = distance
    return result


# Validate recorded reference provenance without equating selection date with OI age.
def _recorded(walls: Mapping, now: datetime) -> dict | None:
    calc = walls.get("calculation")
    if not isinstance(calc, Mapping) or calc.get("version") != CALCULATION_VERSION:
        return None
    calculated = _date(calc.get("date"))
    session = _date(calc.get("reference_session"))
    today = now.astimezone(NEW_YORK).date()
    price = calc.get("reference_price")
    declared = calc.get("method")
    expected = method()
    if (
        calculated is None
        or calculated > today
        or session is None
        or session > calculated
        or not _number(price)
        or price <= 0
        or calc.get("reference_basis") != "raw_panel_close"
        or not isinstance(declared, Mapping)
        or declared != expected
        or not all(_number(value) for value in declared.values())
    ):
        return None
    raw_bar = calc.get("reference_bar_start")
    bar = _timestamp(raw_bar)
    if raw_bar is not None and (
        bar is None or bar > now or bar.astimezone(NEW_YORK).date() > session
    ):
        return None
    expiry, through = (_date(walls.get(key)) for key in ("expiry", "through"))
    if any(
        walls.get(key) is not None and _date(walls.get(key)) is None
        for key in ("expiry", "through")
    ):
        return None
    if (expiry is None) != (through is None):
        return None
    if expiry is not None and not (
        expected["min_days"]
        <= (expiry - calculated).days
        <= (through - calculated).days
        <= expected["max_days"]
    ):
        return None
    result = {
        "status": "recorded",
        "calculation_version": CALCULATION_VERSION,
        "calculated_on": calculated.isoformat(),
        "calculation_date_status": "same_date" if calculated == today else "historical",
        "reference_price": price,
        "reference_basis": "raw_panel_close",
        "reference_session": session.isoformat(),
        "reference_bar_start": bar.isoformat() if bar else None,
        "expiry": expiry.isoformat() if expiry else None,
        "through": through.isoformat() if through else None,
        "method": expected,
    }
    levels = _levels(walls, price, expiry, expected)
    return {**result, **levels} if levels is not None else None


# Project one stored diagnostic into dated display evidence without mutating it.
def describe(walls, now: datetime) -> dict:
    if now.utcoffset() is None:
        raise ValueError("options evidence requires a timezone-aware assessment clock")
    now = now.astimezone(UTC)
    found = walls if isinstance(walls, Mapping) else {}
    common = _collection(found, now)
    if walls is None:
        return {**common, "status": "absent", "reason": "no_stored_diagnostic"}
    if not isinstance(walls, Mapping) or walls.get("status") is not None:
        return {**common, "status": "unavailable", "reason": "options_data_unavailable"}
    recorded = _recorded(walls, now)
    if recorded is None:
        return {
            **common,
            "status": "unverified",
            "reason": "calculation_provenance_unverified",
        }
    return {**common, **recorded}


# Assess each displayed symbol's optional diagnostic using the same read-time clock.
def for_snapshot(snapshot: dict, now: datetime) -> dict:
    details = snapshot.get("technical_detail")
    quotes = snapshot.get("quotes")
    details = details if isinstance(details, Mapping) else {}
    quotes = quotes if isinstance(quotes, Mapping) else {}
    symbols = dict.fromkeys((*quotes, *details))
    return {
        symbol: describe(
            (
                details[symbol].get("walls")
                if isinstance(details.get(symbol), Mapping)
                else None
            ),
            now,
        )
        for symbol in symbols
    }
