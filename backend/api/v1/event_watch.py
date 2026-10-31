"""The nightly event-watch scan as the desk page reads it.

Mechanical detection of earnings shocks, adverse price moves and the reviewed
event calendar from stored data. Descriptive alerting only: no grade, target,
order or prompt reads this block.

The route is registered before the desk's dated-session wildcard, as the fixed
allocation path is, so `/desk/event-watch` is not parsed as a session name.
"""

from fastapi import APIRouter, Depends

from backend.api.v1 import market
from backend.core.auth import authorize_path_user
from backend.market import event_watch_report

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)


# The newest scan and whether it belongs to the session the desk is showing.
@router.get("/desk/event-watch")
async def desk_event_watch(user_id: market.UserId) -> dict[str, object]:
    market._operator_only(user_id)
    latest, _ = market.deskrecord.latest_pair(market._root())
    return {
        "user_id": user_id,
        "event_watch": event_watch_report.load(
            market._root(), (latest or {}).get("session")
        ),
    }
