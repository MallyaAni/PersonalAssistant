"""Owner-only historical current-model quantities, separate from broker history."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import Path as PathParam

from backend.api.v1.market import _operator_only
from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.market import live_model_history_reader

router = APIRouter(
    prefix="/market/{user_id}/desk/live-model-history",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, PathParam(min_length=1, max_length=50)]


# Serve authenticated historical sizes without reading or changing any broker account.
@router.get("/{ticker}")
async def stock(user_id: UserId, ticker: str, response: Response):
    _operator_only(user_id)
    response.headers["Cache-Control"] = "private, no-store"
    try:
        value = await asyncio.to_thread(
            live_model_history_reader.read, settings.MARKET_DATA_ROOT, ticker
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=503, detail="Live-model historical sizing unavailable."
        ) from exc
    return {"user_id": user_id, **value}
