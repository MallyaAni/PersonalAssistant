"""The trading desk as the workspace sees it: the day's record and what changed.

Every field comes from the JSON records `market_daily` writes under the
market data root, so the page cannot show a grade, a weight or a flag the
desk did not write. The user path segment keeps the same authorization as
every other per-user route; the records themselves are the operator's own.
"""

import asyncio
import json
import re
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


# The desk is one person's, or the few the operator has named. A valid token
# for any other user is refused here, before a record is read.
def _operator_only(user_id: str) -> None:
    if user_id not in settings.market_desk_operators:
        raise HTTPException(status_code=403, detail="the desk is the operator's")


# Writing the desk - replacing the shared holdings - is the primary operator's
# alone. A named extra account reads the desk and never overwrites the
# operator's book, which a single shared holdings file would let them do.
def _desk_writer_only(user_id: str) -> None:
    if user_id != settings.MARKET_DESK_USER:
        raise HTTPException(status_code=403, detail="read-only desk access")


# The root the records are read from.
def _root() -> Path:
    return Path(settings.MARKET_DATA_ROOT)


# The candle's live snapshot written by `market_balancer` beside the intraday
# plan: quotes, the technical read and its detail, so the live endpoints serve
# the candle without fetching quotes or running the analyst themselves. The
# page is designed around fifteen-minute candles, so the snapshot's age is the
# candle's age; only a missing file falls back to computing live.
def _live_snapshot() -> dict | None:
    path = _root() / "desk" / "live.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# A snapshot older than a candle is no longer the current candle; it is served
# anyway (a closed market has nothing fresher), but the page is told it is
# stale rather than presenting it as live. One candle: fifteen minutes.
SNAPSHOT_STALE_AFTER_SECONDS = 15 * 60


# How old a snapshot is, in seconds, or None when it cannot be dated.
def _snapshot_age_seconds(snap: dict) -> float | None:
    as_of = snap.get("as_of")
    if not as_of:
        return None
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(str(as_of))).total_seconds()
    except (ValueError, TypeError):
        return None


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
    """Return the candle's live quotes and technical read for the board."""
    _operator_only(user_id)
    snap = _live_snapshot()
    if snap is not None and snap.get("quotes"):
        age = _snapshot_age_seconds(snap)
        stale = age is None or age > SNAPSHOT_STALE_AFTER_SECONDS
        return {
            "user_id": user_id,
            **snap,
            "age_seconds": age,
            "stale": stale,
        }
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
        "age_seconds": 0.0,
        "stale": False,
        "quotes": {symbol: asdict(quote) for symbol, quote in found.items()},
    }


# The live read is model-written prose, cached per candle so the drill-down
# pays one call per name per candle rather than per open. The deterministic
# lines are the fallback when the model is away and the text it is given to
# rewrite, so the same numbers are never rendered two ways.
_live_read_cache: dict[str, object] = {"key": None, "value": {}}


# What the model's live read still has to mention: both levels with a
# distance, and each horizon that had readings. A gap means the model
# skipped a trigger, which is exactly what the read is forbidden to do.
def _live_read_gaps(features: dict[str, list[str]], read: str) -> list[str]:
    """Return the levels and horizons the live read left out."""
    gaps: list[str] = []
    low = read.lower()
    for side in ("support", "resistance"):
        if re.search(rf"{side}.{{0,80}}\d+(?:\.\d+)?\s*%", low) is None:
            gaps.append(f"the nearest {side} and how far it sits")
    if features.get("medium") and "week" not in low:
        gaps.append("the medium-term (weekly) readings")
    if features.get("long") and not (
        "52" in low or "momentum" in low or "200-day" in low
    ):
        gaps.append("the long-term (52-week or momentum) readings")
    # The 200-day simple average is its own line in the features, and it is
    # easily folded into the 200-day EMA by a model that treats the two as
    # one reading. The person watches the SMA; make sure it is named.
    if any("simple average" in line for line in features.get("long", [])) and (
        "simple average" not in low and "sma" not in low
    ):
        gaps.append("the 200-day simple average")
    return gaps


# Write the live read for one name through the model, or None when the
# runtime is away. Unstructured prose, greedy for a reproducible answer,
# with a single retry naming what the first pass left out.
def _model_live_read(
    features: dict[str, list[str]],
    client,
    system: str,
) -> str | None:
    """Return the model's live read for the feature lines, or None."""
    text = "\n".join(
        f"{horizon}: " + ("; ".join(items) if items else "no readings")
        for horizon, items in (
            ("short", features["short"]),
            ("medium", features["medium"]),
            ("long", features["long"]),
        )
    )
    if not text.strip():
        return None
    try:
        read = str(
            client.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                400,
                None,
                0.0,
            )["content"]
        ).strip()
    except Exception:  # the runtime being away must not fail the page
        return None
    gaps = _live_read_gaps(features, read)
    if gaps:
        try:
            read = str(
                client.chat(
                    [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": (
                                f"{text}\n\nYou left out: {', '.join(gaps)}. "
                                "Cover those too, and every other reading you "
                                "were given."
                            ),
                        },
                    ],
                    400,
                    None,
                    0.0,
                )["content"]
            ).strip()
        except Exception:
            return None
        if _live_read_gaps(features, read):
            return None
    return _fit_live_read(features, read)


# The page reads at most the first twelve hundred characters of the model's
# prose, and a straight cut ends in the middle of a sentence and can drop
# the long-horizon readings the model wrote last - the 200-day average is
# exactly the fact the cut has been observed to remove. Cut at the last
# sentence boundary that fits, and if even that would lose a required
# reading, hand back the deterministic lines whole: a complete fallback
# beats a truncated read that silently hides the SMA.
def _fit_live_read(features: dict[str, list[str]], read: str) -> str | None:
    """Return `read` cut to fit the page, falling back to the lines when it cannot."""
    if len(read) <= 1200:
        return read or None
    cut = read.rfind(". ", 0, 1200)
    end = cut + 1 if cut >= 600 else 1200
    fitted = read[:end]
    if _live_read_gaps(features, fitted):
        return _deterministic_read(features)
    return fitted


# The read the page falls back to when the model's prose will not fit: the
# deterministic feature lines themselves, in the same horizon order the
# model was given, so a name's reading is never lost to a character cut.
def _deterministic_read(features: dict[str, list[str]]) -> str | None:
    """Return the feature lines as plain prose, horizon by horizon."""
    parts: list[str] = []
    for horizon, opener in (
        ("short", "In the near term"),
        ("medium", "Over the coming weeks"),
        ("long", "For the longer run"),
    ):
        items = features.get(horizon) or []
        if items:
            parts.append(f"{opener}: " + "; ".join(items))
    return " ".join(parts) or None


# The live technical read for one name: the model's plain words, or the
# deterministic lines when the model was away, either way with the features
# that produced them.
@router.get("/desk/live/read/{symbol}")
async def desk_live_read(user_id: UserId, symbol: str) -> dict[str, object]:
    """Return the model's live technical read for one name."""
    _operator_only(user_id)
    symbol = symbol.upper()
    detail = ((_live_snapshot() or {}).get("technical_detail") or {}).get(symbol)
    if detail is None:
        try:
            headers = alpaca.credentials()
        except alpaca.AlpacaUnavailableError:
            return {"read": None, "lines": {"short": [], "medium": [], "long": []}}
        store = MarketStore(_root())
        quotes = live_quotes.quotes([symbol], headers=headers)
        if not quotes:
            return {"read": None, "lines": {"short": [], "medium": [], "long": []}}
        detail = (
            await asyncio.to_thread(live_technical.technical_detail, store, quotes)
        ).get(symbol)
        if detail is None:
            return {"read": None, "lines": {"short": [], "medium": [], "long": []}}
    lines_ = live_technical.lines(detail)
    sig = (symbol, json.dumps(detail, sort_keys=True))
    if _live_read_cache["key"] == sig:
        cached = _live_read_cache["value"]  # type: ignore[assignment]
        return {"symbol": symbol, **cached}
    from backend.core.dependencies import get_llm_client
    from backend.core.prompts import render

    try:
        client = get_llm_client()
        system = render("trading/desk_live_read")
        read = _model_live_read(lines_, client, system)
    except Exception:  # noqa: BLE001 - no model, no read, lines still render
        read = None
    out = {
        "read": read,
        "lines": lines_,
        "now": detail.get("now"),
        # When this analysis was written, so the page can show the time of
        # the prose rather than the candle it happens to sit beside: a read
        # is only fresh for the candle it was computed on.
        "read_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _live_read_cache["key"], _live_read_cache["value"] = sig, out
    return {"symbol": symbol, **out}


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
    _desk_writer_only(user_id)
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
    snap = _live_snapshot()
    if snap is not None and snap.get("quotes"):
        return {
            "user_id": user_id,
            "session": latest.get("session"),
            "as_of": snap.get("as_of"),
            "rows": holdings.board(
                latest,
                rows,
                equity,
                snap.get("quotes") or {},
                snap.get("technical") or {},
            ),
            "grades_live": holdings.live_grades(latest, snap.get("technical") or {}),
        }
    symbols = sorted(
        {h.ticker for h in rows}
        | {r["ticker"] for r in latest.get("book") or []}
        | set(latest.get("grades") or {})
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
        "grades_live": holdings.live_grades(latest, technical),
    }


# The practice account as the broker reports it now, not as the evening
# record left it: money, every position with its cost and price, and the
# orders waiting for the open. Read-only, paper endpoint only.
@router.get("/desk/paper")
async def desk_paper(user_id: UserId) -> dict[str, object]:
    """Return the paper account's live money, positions and open orders."""
    _operator_only(user_id)

    def fetch() -> dict[str, object]:
        from backend.agents.trading.desk import paper

        client = alpaca_trading.client_from_env()
        account = client.account()
        equity = float(account.equity)
        day_pl = equity - float(account.last_equity)
        # The paper book's lifetime and day moves as percentages, so the
        # page can read them beside the dollar figures. The lifetime base
        # is the equity the paper book started with; the day base is last
        # night's equity (today's equity minus today's move).
        state = paper.load_state(Path(settings.MARKET_DATA_ROOT))
        start = state.start_equity
        day_base = equity - day_pl
        return {
            "equity": equity,
            "cash": account.cash,
            "day_pl": day_pl,
            "day_pl_pct": (day_pl / day_base) if day_base else None,
            "pl_pct": (equity / start - 1.0) if start else None,
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
    history = json.loads(path.read_text(encoding="utf-8"))
    # The rows are today's rule replayed; where a nightly record exists for
    # the session, the row carries what the desk actually said that night
    # and is marked as said, so a grade that moved because the rule changed
    # is told apart from one that moved because the name did.
    spoken = deskrecord.said(_root(), ticker.upper())
    rows = []
    for row in history.get("rows") or []:
        told = spoken.get(str(row.get("date")))
        rows.append({**row, **told, "said": True} if told else {**row, "said": False})
    history["rows"] = rows
    return {"user_id": user_id, "ticker": ticker.upper(), **history}


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
