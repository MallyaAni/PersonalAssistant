"""The trading desk as the workspace sees it: the day's record and what changed.

Every field comes from the JSON records `market_daily` writes under the
market data root, so the page cannot show a grade, a weight or a flag the
desk did not write. The user path segment keeps the same authorization as
every other per-user route; the records themselves are the operator's own.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam

from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.market import alpaca, deskrecord, holdings, live_quotes

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
# The current candle against the board's levels: the last fifteen-minute
# close, the session's high and low, for every name on the board. Read
# from Alpaca's free feed and remembered for a candle. Declared before the
# session route so "live" is not taken for a session.
@router.get("/desk/live")
async def desk_live(user_id: UserId) -> dict[str, object]:
    """Return live quotes for the names on the latest board."""
    _operator_only(user_id)
    latest, _previous = deskrecord.latest_pair(_root())
    rows = (latest or {}).get("actions") or []
    symbols = [str(r.get("ticker")) for r in rows if r.get("ticker")]
    try:
        headers = alpaca.credentials()
    except alpaca.AlpacaUnavailableError:
        return {"user_id": user_id, "as_of": None, "quotes": {}, "reason": "no keys"}
    found = live_quotes.quotes(symbols, headers=headers)
    return {
        "user_id": user_id,
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "quotes": {symbol: asdict(quote) for symbol, quote in found.items()},
    }


# The person's own positions, kept beside the records and never touched
# by the nightly run. PUT replaces the list; a bad row is refused whole.
@router.get("/desk/holdings")
async def desk_holdings(user_id: UserId) -> dict[str, object]:
    """Return the saved holdings."""
    _operator_only(user_id)
    rows = holdings.load(_root())
    return {"user_id": user_id, "holdings": [h.__dict__ for h in rows]}


@router.put("/desk/holdings")
async def desk_save_holdings(user_id: UserId, rows: list[dict]) -> dict[str, object]:
    """Replace the saved holdings with `rows`."""
    _operator_only(user_id)
    try:
        parsed = holdings.parse(rows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    holdings.save(_root(), parsed)
    return {"user_id": user_id, "holdings": [h.__dict__ for h in parsed]}


# The board against the person's own holdings at the equity given: the
# latest record's targets and levels, the live candle where the feed has
# one, and the person's entry beside each name they hold.
@router.get("/desk/mine")
async def desk_mine(
    user_id: UserId, equity: float = Query(..., gt=0)
) -> dict[str, object]:
    """Return action rows computed against the saved holdings."""
    _operator_only(user_id)
    latest, _previous = deskrecord.latest_pair(_root())
    rows = holdings.load(_root())
    if latest is None:
        return {"user_id": user_id, "session": None, "rows": []}
    symbols = sorted(
        {h.ticker for h in rows} | {r["ticker"] for r in latest.get("book") or []}
    )
    quotes: dict = {}
    try:
        found = live_quotes.quotes(symbols, headers=alpaca.credentials())
        quotes = {s: asdict(q) for s, q in found.items()}
    except alpaca.AlpacaUnavailableError:
        pass
    return {
        "user_id": user_id,
        "session": latest.get("session"),
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": holdings.board(latest, rows, equity, quotes),
    }


@router.get("/desk/{session}")
async def desk_for_session(user_id: UserId, session: Session) -> dict[str, object]:
    _operator_only(user_id)
    record = deskrecord.load(_root(), session)
    if record is None:
        raise HTTPException(status_code=404, detail="no desk record for that session")
    return {"user_id": user_id, "record": record}
