"""The nightly forward earnings calendar as the desk page reads it.

Predicted next releases from stored 8-K item 2.02 dates, with the last release,
the confidence band and the held weight. Descriptive alerting only: no grade,
target, order or prompt reads this block.

The route is registered before the desk's dated-session wildcard, as the fixed
allocation path is, so `/desk/earnings-calendar` is not parsed as a session name.
"""

from fastapi import APIRouter, Depends

from backend.api.v1 import market
from backend.core.auth import authorize_path_user
from backend.market import earnings_calendar_report

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)


# The newest scan and whether it belongs to the session the desk is showing.
@router.get("/desk/earnings-calendar")
async def desk_earnings_calendar(user_id: market.UserId) -> dict[str, object]:
    market._operator_only(user_id)
    latest, _ = market.deskrecord.latest_pair(market._root())
    return {
        "user_id": user_id,
        "earnings_calendar": earnings_calendar_report.load(
            market._root(), (latest or {}).get("session")
        ),
    }
