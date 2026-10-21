"""Read-only published model percentages, independent of live paper-account access."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Response

from backend.api.v1 import market
from backend.core.auth import authorize_path_user
from backend.market import (
    deskrecord,
    market_phase,
    model_allocation_view,
    strategy_entries,
    strategy_entry_history,
    strategy_position_view,
    strategy_publication,
)
from backend.market import strategy_verdict as verdicts

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)

# How far inside the original window the expiry probe reads. The publication
# reader admits a snapshot only while `now < valid_until`; one microsecond
# before the close is still inside the window and after every other clock the
# snapshot carries.
PROBE = timedelta(microseconds=1)
# Bound at import: the HTTP tests replace this module's `datetime` with a
# fixed clock that has only `now`, and the probe must still parse a stamp.
_parse_instant = datetime.fromisoformat


# The verified snapshot an expired publication still is, or None when the
# bytes fail any check other than their clock. The reader itself is one of
# the sources the installed release approval binds, so expiry is told apart
# here by reading once more with the clock set just inside the window: a
# snapshot that verifies then, and only then, has merely expired.
def _expired_snapshot(root, now):
    folder = root / strategy_publication.DIRECTORY
    try:
        pointer = json.loads((folder / "latest.json").read_bytes())
        stored = json.loads((folder / f"{pointer['snapshot_id']}.json").read_bytes())
        until = _parse_instant(stored["valid_until"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if until.utcoffset() is None or now < until:
        return None
    try:
        return strategy_publication.read(root, until - PROBE)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


# The one-word verdict beside each served numerical row. The rows come from
# sealed engines whose modules the release approval binds, so the verdict is
# added here, on the way out, from the evidence the rows already carry.
def _with_verdicts(assessment, snapshot, *, reason_key, held_key=None):
    if not isinstance(assessment, dict):
        return assessment
    if not isinstance(assessment.get("rows"), dict):
        return assessment
    rows = {}
    for name, row in assessment["rows"].items():
        if not isinstance(row, dict):
            rows[name] = row
            continue
        target = row.get("model_position_weight")
        if target is None:
            target = snapshot.get("rows", {}).get(name, {}).get("target_weight")
        rows[name] = verdicts.annotate(
            row, reason_key=reason_key, target_weight=target,
            held_weight=row.get(held_key) if held_key else 0,
            quote_available=row.get("quote_at") is not None,
            distribution_available=row.get("state") != "unavailable"
            or "distribution" not in str(row.get("reason", "")).lower(),
            mandatory=row.get("reason") == "mandatory_grade_exit",
            resolved=bool(row.get("attempt_resolved")))
    return {**assessment, "rows": rows}


# Read original publication and persisted model objectives without recovering,
# recalculating or accessing accounts.
def allocation(root, now):
    root = Path(root)
    # Every answer carries the exchange clock, so the board can say which
    # phase the market is in and when the desk acts next instead of leaving
    # an evening or a weekend to be read as a failure.
    phase = market_phase.describe(now)
    if (root / strategy_publication.DIRECTORY).exists():
        try:
            snapshot = strategy_publication.read(root, now)
            positions = strategy_position_view.read(root, snapshot, now)
            entries = _with_verdicts(
                strategy_entries.read(root, snapshot, now), snapshot, reason_key="reason"
            )
            positions = _with_verdicts(
                positions, snapshot, reason_key="verdict_reason",
                held_key="reference_position_weight",
            )
            return {**snapshot, 'entry_assessment': entries,
                **({'reference_positions': positions} if positions is not None else {}),
                'recorded_history_version':strategy_entry_history.PAGE_SCHEMA,
                'market_phase': phase}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            expired = _expired_snapshot(root, now)
            if expired is not None:
                # A verified publication whose window has closed is a plan
                # waiting for tonight's, not an integrity failure.
                return {"version": strategy_publication.VERSION,
                        "status": "awaiting_nightly", "policy": expired["policy"],
                        "rows": {}, "expired_at": expired["valid_until"],
                        "next_publication_at": market_phase.next_publication_at(
                            now
                        ).isoformat(),
                        "last_session": expired["session"], "last_rows": expired["rows"],
                        "as_of": now.isoformat(), "valid_until": None,
                        "market_phase": phase}
            return {"version": strategy_publication.VERSION, "status": "unavailable",
                    "policy": "grade-led-learned-sizing/1", "rows": {},
                    "reason": "Independent strategy publication could not be verified",
                    "as_of": now.isoformat(), "valid_until": None,
                    "market_phase": phase}
    try:
        record, _ = deskrecord.latest_pair(root)
    except (OSError, ValueError, TypeError):
        return model_allocation_view.unavailable(
            {}, now, "Published model record could not be read"
        )
    return model_allocation_view.read(root, record, now)


# Serve authenticated percentages without recalculating or recording advice.
@router.get("/desk/model-allocation")
async def model_allocation(user_id: market.UserId, response: Response):
    market._operator_only(user_id)
    response.headers["Cache-Control"] = "private, no-store"
    return await asyncio.to_thread(allocation, market._root(), datetime.now(UTC))
