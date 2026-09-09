"""The trading desk as the workspace sees it: the day's record and what changed.

Every field comes from the JSON records `market_daily` writes under the
market data root, so the page cannot show a grade, a weight or a flag the
desk did not write. The user path segment keeps the same authorization as
every other per-user route; the records themselves are the operator's own.
"""

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam

from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.core.dependencies import (
    DependencyAgentMemoryManager,
    get_structured_llm_client,
)
from backend.market import (
    alpaca,
    alpaca_trading,
    deskrecord,
    holdings,
    live_quotes,
    live_technical,
)
from backend.market.store import MarketStore

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
        # The track-record curve the record carries; absent on older records.
        "curve": (latest or {}).get("curve") or {},
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
    # The technical analyst re-read at the live price, one run per candle;
    # a failure here leaves the quotes standing.
    technical: dict = {}
    technical_detail: dict = {}
    if found:
        try:
            store = MarketStore(_root())
            technical = await asyncio.to_thread(
                live_technical.technical_now, store, found
            )
            technical_detail = await asyncio.to_thread(
                live_technical.technical_detail, store, found
            )
        except Exception as exc:  # noqa: BLE001 - the quotes must still reach the page
            technical = {"reason": str(exc)}  # type: ignore[dict-item]
    return {
        "technical": technical,
        "technical_detail": technical_detail,
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


# The balancer's persisted plan: the ranked buys for this moment, re-read on
# each fifteen-minute candle and written by `market_balancer`, so the page
# has the current plan even when no browser has been open to compute it.
@router.get("/desk/intraday")
async def desk_intraday(user_id: UserId) -> dict[str, object]:
    """Return the latest persisted intraday plan, or 404 when none exists."""
    _operator_only(user_id)
    path = _root() / "desk" / "intraday.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no intraday plan yet")
    return json.loads(path.read_text(encoding="utf-8"))


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
    technical: dict = {}
    try:
        found = live_quotes.quotes(symbols, headers=alpaca.credentials())
        quotes = {s: asdict(q) for s, q in found.items()}
        if found:
            try:
                technical = await asyncio.to_thread(
                    live_technical.technical_now, MarketStore(_root()), found
                )
            except Exception:  # noqa: BLE001 - the board stands without the live read
                technical = {}
    except alpaca.AlpacaUnavailableError:
        pass
    return {
        "user_id": user_id,
        "session": latest.get("session"),
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": holdings.board(latest, rows, equity, quotes, technical),
    }


# The practice account as the broker reports it now, not as the evening
# record left it: money, every position with its cost and price, and the
# orders waiting for the open. Read-only, paper endpoint only.
@router.get("/desk/paper")
async def desk_paper(user_id: UserId) -> dict[str, object]:
    """Return the paper account's live money, positions and open orders."""
    _operator_only(user_id)

    def fetch() -> dict[str, object]:
        client = alpaca_trading.client_from_env()
        account = client.account()
        return {
            "equity": account.equity,
            "cash": account.cash,
            "day_pl": account.equity - account.last_equity,
            "positions": [asdict(p) for p in client.positions()],
            "orders": [
                {
                    "symbol": o.get("symbol"),
                    "side": o.get("side"),
                    "qty": float(o.get("qty") or 0),
                    "status": o.get("status"),
                }
                for o in client.open_orders()
            ],
        }

    try:
        live = await asyncio.to_thread(fetch)
    except alpaca_trading.AlpacaTradingError as exc:
        return {"user_id": user_id, "reason": str(exc)}
    return {
        "user_id": user_id,
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        **live,
    }


# One name's history and backtest, from the files the nightly run wrote:
# what the desk said about it session by session and what happened next.
# The desk rebuilds in the nightly job (the serving container has no
# torch), so the drill-down reads the record the job left behind.
@router.get("/desk/history/{ticker}")
async def desk_history(user_id: UserId, ticker: str) -> dict[str, object]:
    """Return a name's grade history and backtest, or 404 without it."""
    _operator_only(user_id)
    path = _root() / "history" / f"{ticker.upper()}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no history for that name yet")
    return {
        "user_id": user_id,
        "ticker": ticker.upper(),
        **json.loads(path.read_text(encoding="utf-8")),
    }


# The autopsy: read the caller's own trading passages and name what their
# trading keeps doing. This one is not operator-only - it is the person's
# own history, and `authorize_path_user` already keeps the boundary.
@router.get("/trading/autopsy")
async def trading_autopsy(
    user_id: UserId, agent_memory: DependencyAgentMemoryManager
) -> dict[str, object]:
    """Return the autopsy of the caller's own trading documents, or why not."""
    from backend.agents.trading.autopsy import MAX_PASSAGES, TradeAutopsy

    passages = await agent_memory.search(
        user_id,
        "trading trades buy sell position entry exit loss win earnings",
        top_k=MAX_PASSAGES,
    )
    if not passages:
        return {
            "user_id": user_id,
            "result": None,
            "reason": (
                "No trading documents to read yet. Share a statement, a "
                "journal, or notes about your trades and try again."
            ),
        }
    result = await TradeAutopsy(get_structured_llm_client()).analyze(passages)
    if result is None:
        return {
            "user_id": user_id,
            "result": None,
            "reason": "The analysis model was not reachable; try again shortly.",
        }
    sources = sorted(
        {str(p.get("document", {}).get("title") or "a document") for p in passages}
    )
    return {
        "user_id": user_id,
        "result": {
            "patterns": [dict(p) for p in result.patterns],
            "costs": [dict(c) for c in result.costs],
            "plan": result.plan,
            "unknowns": list(result.unknowns),
        },
        "sources": sources,
        "passages_used": len(passages),
    }


@router.get("/desk/{session}")
async def desk_for_session(user_id: UserId, session: Session) -> dict[str, object]:
    _operator_only(user_id)
    record = deskrecord.load(_root(), session)
    if record is None:
        raise HTTPException(status_code=404, detail="no desk record for that session")
    return {"user_id": user_id, "record": record}
