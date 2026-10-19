"""Read-only published model percentages, independent of live paper-account access."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response

from backend.api.v1 import market
from backend.core.auth import authorize_path_user
from backend.market import deskrecord, model_allocation_view

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)


# Read only the original record, never current accounts or personal inputs.
def allocation(root, now):
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
