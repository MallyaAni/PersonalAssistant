"""Read-only published model percentages, independent of live paper-account access."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Response

from backend.api.v1 import market
from backend.core.auth import authorize_path_user
from backend.market import deskrecord, model_allocation_view, strategy_publication, strategy_entries, strategy_entry_history

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)


# Read only the original record, never current accounts or personal inputs.
def allocation(root, now):
    root = Path(root)
    if (root / strategy_publication.DIRECTORY).exists():
        try:
            snapshot = strategy_publication.read(root, now)
            return {**snapshot, 'entry_assessment':strategy_entries.read(root,snapshot,now),
                'recorded_history_version':strategy_entry_history.PAGE_SCHEMA}
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
