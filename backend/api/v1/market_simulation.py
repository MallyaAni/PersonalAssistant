"""Owner-authorized counterfactual strategy views, separate from live accounts."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import Path as PathParam

from backend.api.v1.market import _operator_only
from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.market import strategy_research, strategy_history_publication, strategy_entry_history, strategy_replay_sample
from datetime import UTC, datetime
from pathlib import Path

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
        if (Path(settings.MARKET_DATA_ROOT)/strategy_history_publication.DIRECTORY).exists():
            value=await asyncio.to_thread(strategy_history_publication.read,settings.MARKET_DATA_ROOT,ticker,datetime.now(UTC))
        else:
            value=await asyncio.to_thread(strategy_research.read,settings.MARKET_DATA_ROOT,ticker)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=503, detail="Latest-strategy simulation unavailable."
        ) from exc
    # The frozen-model boundary is stamped on the served rows, not in the sealed
    # artefact, so the chart can mute what the models had already seen.
    return {"user_id": user_id, **strategy_replay_sample.stamp(value), 'recorded_history_version':strategy_entry_history.PAGE_SCHEMA}


# Return the simulated portfolio and dated coverage independently of the paper account.
@router.get("")
async def summary(user_id: UserId, response: Response):
    return await view(user_id, response)


# Return only the requested stock's latest-strategy decisions and simulated trades.
@router.get("/{ticker}")
async def stock(user_id: UserId, ticker: str, response: Response):
    return await view(user_id, response, ticker)


# Restore an original numerical recommendation after expiry, without inferring or reading a funded account.
@router.get('/{ticker}/recommendation')
async def original_recommendation(user_id: UserId, ticker: str, response: Response,
    snapshot_id: Annotated[str, Query(min_length=64,max_length=64)],
    completed_at: Annotated[str, Query(min_length=20,max_length=40)]):
    _operator_only(user_id)
    response.headers['Cache-Control']='private, no-store'
    try:
        value=await asyncio.to_thread(strategy_entry_history.read,settings.MARKET_DATA_ROOT,
            ticker,completed_at,snapshot_id,datetime.now(UTC))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise HTTPException(status_code=503,detail='Original model recommendation unavailable.') from exc
    return {'user_id':user_id,**value}


# Discover original decisions after expiry without inferring, reading an account or substituting current advice.
@router.get('/{ticker}/recommendations')
async def original_recommendations(user_id: UserId, ticker: str, response: Response,
    before: Annotated[str | None, Query(max_length=256)]=None,
    limit: Annotated[int, Query(ge=1,le=strategy_entry_history.MAX_PAGE)]=strategy_entry_history.MAX_PAGE):
    _operator_only(user_id)
    response.headers['Cache-Control']='private, no-store'
    try:
        value=await asyncio.to_thread(strategy_entry_history.recent,settings.MARKET_DATA_ROOT,
            ticker,datetime.now(UTC),before=before,limit=limit)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise HTTPException(status_code=503,detail='Original recorded recommendation history unavailable.') from exc
    return {'user_id':user_id,**value}
