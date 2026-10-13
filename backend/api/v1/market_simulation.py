"""Owner-authorized counterfactual strategy views, separate from live accounts."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import Path as PathParam

from backend.api.v1.market import _operator_only
from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.market import strategy_research

router = APIRouter(
    prefix="/market/{user_id}/desk/strategy-simulation",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, PathParam(min_length=1, max_length=50)]


# Serve one authenticated simulation projection without reading or changing a broker.
async def view(user_id, response, ticker=None):
    _operator_only(user_id)
    response.headers["Cache-Control"] = "private, no-store"
    try:
        value = await asyncio.to_thread(
            strategy_research.read, settings.MARKET_DATA_ROOT, ticker
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=503, detail="Latest-strategy simulation unavailable."
        ) from exc
    return {"user_id": user_id, **value}


# Return the simulated portfolio and dated coverage independently of the paper account.
@router.get("")
async def summary(user_id: UserId, response: Response):
    return await view(user_id, response)


# Return only the requested stock's latest-strategy decisions and simulated trades.
@router.get("/{ticker}")
async def stock(user_id: UserId, ticker: str, response: Response):
    return await view(user_id, response, ticker)
