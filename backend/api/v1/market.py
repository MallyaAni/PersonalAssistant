"""The trading desk as the workspace sees it: the day's record and what changed.

Every field comes from the JSON records `market_daily` writes under the
market data root, so the page cannot show a grade, a weight or a flag the
desk did not write. The user path segment keeps the same authorization as
every other per-user route; the records themselves are the operator's own.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam

from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.market import deskrecord

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, PathParam(min_length=1, max_length=50)]
Session = Annotated[str, PathParam(pattern=r"^\d{4}-\d{2}-\d{2}$")]


# The desk is one person's. A valid token for any other user is refused
# here, before a record is read.
def _operator_only(user_id: str) -> None:
    if user_id != settings.MARKET_DESK_USER:
        raise HTTPException(status_code=403, detail="the desk is the operator's")


# The root the records are read from.
def _root() -> Path:
    return Path(settings.MARKET_DATA_ROOT)


# The latest record, the changes since the one before, the headline
# summary, and the sessions on file.
@router.get("/desk")
async def latest_desk(user_id: UserId) -> dict[str, object]:
    _operator_only(user_id)
    latest, previous = deskrecord.latest_pair(_root())
    if latest is None:
        return {"user_id": user_id, "latest": None, "sessions": []}
    return {
        "user_id": user_id,
        "latest": latest,
        "summary": deskrecord.summary(latest),
        "changes": deskrecord.changes(latest, previous).to_dict(),
        "sessions": deskrecord.sessions(_root()),
    }


# One earlier session's record, as it was written.
@router.get("/desk/{session}")
async def desk_for_session(user_id: UserId, session: Session) -> dict[str, object]:
    _operator_only(user_id)
    record = deskrecord.load(_root(), session)
    if record is None:
        raise HTTPException(status_code=404, detail="no desk record for that session")
    return {"user_id": user_id, "record": record}
