"""Read-only published model percentages, independent of live paper-account access."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Response

from backend.api.v1 import market
from backend.core.auth import authorize_path_user
from backend.market import deskrecord, model_allocation_view, strategy_publication, strategy_entries, strategy_entry_history, strategy_position_view

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)


# Read original publication and persisted model objectives without recovering, recalculating or accessing accounts.
def allocation(root, now):
    root = Path(root)
    if (root / strategy_publication.DIRECTORY).exists():
        try:
            snapshot = strategy_publication.read(root, now)
            positions = strategy_position_view.read(root, snapshot, now)
            return {**snapshot, 'entry_assessment':strategy_entries.read(root,snapshot,now),
                **({'reference_positions': positions} if positions is not None else {}),
                'recorded_history_version':strategy_entry_history.PAGE_SCHEMA}
        except strategy_publication.ExpiredError as expired:
            snapshot = expired.value
            return {"version": strategy_publication.VERSION,
                    "status": "awaiting_nightly", "policy": snapshot["policy"],
                    "rows": {}, "expired_at": snapshot["valid_until"],
                    "next_publication_at": strategy_publication.next_publication_at(
                        now).isoformat(),
                    "last_session": snapshot["session"], "last_rows": snapshot["rows"],
                    "as_of": now.isoformat(), "valid_until": None}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return {"version": strategy_publication.VERSION, "status": "unavailable",
                    "policy": "grade-led-learned-sizing/1", "rows": {},
                    "reason": "Independent strategy publication could not be verified",
                    "as_of": now.isoformat(), "valid_until": None}
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
