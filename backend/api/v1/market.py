"""The trading desk as the workspace sees it: the day's record and what changed.

Every field comes from the JSON records `market_daily` writes under the
market data root, so the page cannot show a grade, a weight or a flag the
desk did not write. The user path segment keeps the same authorization as
every other per-user route; the records themselves are the operator's own.
"""

import asyncio
import json
import math
import re
from collections import OrderedDict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, field_validator, model_validator

from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.core.dependencies import (
    DependencyAgentMemoryManager,
    get_structured_llm_client,
)
from backend.market import (
    alpaca,
    alpaca_trading,
    desk_freshness,
    deskrecord,
    economics,
    funding,
    holdings,
    intraday_research,
    language,
    live_quotes,
    live_technical,
    ticker_chart,
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
# The record the page reads: the decision plus the model prose written
# beside it, with a state the page can switch on.
def _with_prose(record: dict) -> dict:
    from backend.market import prose

    return prose.merge(record, prose.load(_root(), record["session"]))


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
    from backend.agents.trading.desk import event_risk

    _operator_only(user_id)
    latest, previous = deskrecord.latest_pair(_root())
    if latest is None:
        return {"user_id": user_id, "latest": None, "sessions": []}
    latest = _with_prose(latest)
    from backend.market import (
        board_paper,
        event_status,
        execution_quality,
        fomc_gate,
        forward_evidence,
        opportunity_shadow,
        record_status,
        reversal,
        strategy_bench,
    )

    event_live = event_status.load(_root())
    research = intraday_research.load(_root(), latest["session"])
    from backend.market.universe import FOCUS, MEMBER, build_universe, tickers_with_role

    tracked = tickers_with_role(build_universe(), FOCUS, MEMBER)
    if event_live["planning_paused"]:
        research = {**research, "event_paused": True}
    return {
        "user_id": user_id,
        "latest": latest,
        "economics": economics.load(_root()),
        "intraday_research": research,
        "board_paper": board_paper.summary(_root()),
        "ml_forward": opportunity_shadow.summary(_root()),
        # Whether the last completed session has its record and its ML
        # observation, so the page can say when it is showing an old decision.
        "record_status": record_status.describe(_root()),
        # The FOMC overlay against the book that never traded it, meeting by
        # meeting, and the standing of the gate written before the outcomes.
        "fomc_gate": fomc_gate.load(_root()),
        # Every paper fill against its decision price, as a series.
        "execution_quality": execution_quality.load(_root()),
        # Candidate trading rules and the indices on identical numbers, split
        # by regime. Evidence for the Research view; only the shipped rule
        # trades anywhere.
        "strategy_bench": strategy_bench.load(_root()),
        # The registered reversal shadows: cycles recorded, nothing traded.
        "reversal_shadow": {
            "meetings": reversal.load(_root()),
            "any_day": reversal.load(_root(), reversal.ANY_DAY_NAME),
        },
        "coverage": {
            "tracked": len(tracked),
            "graded": len(latest.get("grades") or {}),
        },
        "event_status": event_live,
        "forward_evidence": await asyncio.to_thread(forward_evidence.report, _root()),
        "event_policy": {
            "enabled": True,
            "version": event_risk.VERSION,
            "evaluation_since": str(event_risk.GUIDANCE_CHANGE),
        },
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
        return {"user_id": user_id, **desk_freshness.describe(snap)}
    latest, _previous = deskrecord.latest_pair(_root())
    rows = (latest or {}).get("actions") or []
    symbols = [str(r.get("ticker")) for r in rows if r.get("ticker")]
    try:
        headers = alpaca.credentials()
    except alpaca.AlpacaUnavailableError:
        return {"user_id": user_id, "as_of": None, "quotes": {}, "reason": "no keys"}
    found = live_quotes.quotes(symbols, headers=headers)
    # The technical and value analysts re-read at the live price, one run
    # per candle; a failure here leaves the quotes standing.
    technical: dict = {}
    value: dict = {}
    technical_detail: dict = {}
    if found:
        try:
            store = MarketStore(_root())
            technical = await asyncio.to_thread(
                live_technical.technical_now, store, found
            )
            value = await asyncio.to_thread(live_technical.value_now, store, found)
            technical_detail = await asyncio.to_thread(
                live_technical.technical_detail, store, found
            )
        except Exception as exc:  # noqa: BLE001 - the quotes must still reach the page
            technical = {"reason": str(exc)}  # type: ignore[dict-item]
    return desk_freshness.describe(
        {
            "technical": technical,
            "value": value,
            "technical_detail": technical_detail,
            "user_id": user_id,
            "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
            "age_seconds": 0.0,
            "stale": False,
            "quotes": {symbol: asdict(quote) for symbol, quote in found.items()},
            "decision_session": (latest or {}).get("session"),
        }
    )


# The live read is model-written prose, cached per candle so the drill-down
# pays one call per name per candle rather than per open. The deterministic
# lines are the fallback when the model is away and the text it is given to
# rewrite, so the same numbers are never rendered two ways.
_live_read_cache: OrderedDict[tuple, dict] = OrderedDict()


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
# sentence boundary that fits, and if there is none (or cutting would lose
# a required reading), hand back the deterministic lines whole: a complete
# fallback beats a truncated read that silently hides the SMA or stops
# mid-word.
def _fit_live_read(features: dict[str, list[str]], read: str) -> str | None:
    """Return `read` cut to fit the page, falling back to the lines when it cannot."""
    if len(read) <= 1200:
        return read or None
    cut = read.rfind(". ", 0, 1200)
    if cut < 600:
        # No sentence boundary fits: a raw twelve-hundred-character cut
        # could land mid-word, so the complete deterministic lines stand in.
        return _deterministic_read(features)
    fitted = read[: cut + 1]
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
    snapshot = _live_snapshot() or {}
    detail = (snapshot.get("technical_detail") or {}).get(symbol)
    quote = (snapshot.get("quotes") or {}).get(symbol) or {}
    if detail is None:
        try:
            headers = alpaca.credentials()
        except alpaca.AlpacaUnavailableError:
            return {"read": None, "lines": {"short": [], "medium": [], "long": []}}
        store = MarketStore(_root())
        quotes = live_quotes.quotes([symbol], headers=headers)
        if not quotes:
            return {"read": None, "lines": {"short": [], "medium": [], "long": []}}
        quote = asdict(quotes[symbol]) if symbol in quotes else {}
        detail = (
            await asyncio.to_thread(live_technical.technical_detail, store, quotes)
        ).get(symbol)
        if detail is None:
            return {"read": None, "lines": {"short": [], "medium": [], "long": []}}
    lines_ = live_technical.lines(detail)
    evidence = desk_freshness.quote_status(quote, datetime.now(UTC))
    sig = (
        str(_root()),
        symbol,
        evidence["data_at"],
        json.dumps(detail, sort_keys=True),
    )
    if evidence["stale"]:
        return {
            "symbol": symbol,
            "read": _deterministic_read(lines_),
            "lines": lines_,
            "now": detail.get("now"),
            "read_at": None,
            **evidence,
        }
    if sig in _live_read_cache:
        _live_read_cache.move_to_end(sig)
        return {"symbol": symbol, **_live_read_cache[sig], **evidence}
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
    _live_read_cache[sig] = out
    if len(_live_read_cache) > 64:
        _live_read_cache.popitem(last=False)
    return {"symbol": symbol, **out, **evidence}


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


# A person's confirmed account figures for the personal desk read. The body
# is the only channel: account figures are never carried in a URL. `equity`
# must be a finite positive number and `available_cash`, when given, a finite
# nonnegative number no larger than equity. Booleans are refused because
# Pydantic would otherwise coerce `true` to 1.0 and `false` to 0.0 and treat
# them as dollars; empty/invalid cash means "unknown" and the caller keeps
# buys gated.
class DeskMineInput(BaseModel):
    equity: float
    available_cash: float | None = None

    # Reject booleans before dollar amounts are coerced to floats.
    @field_validator("equity", mode="before")
    @classmethod
    def _equity_reject_boolean(cls, value):
        """Refuse a boolean where a dollar figure belongs."""
        if isinstance(value, bool):
            raise ValueError("Equity must be a number, not a boolean")
        return value

    # Preserve unknown cash while rejecting boolean dollar amounts.
    @field_validator("available_cash", mode="before")
    @classmethod
    def _cash_reject_boolean(cls, value):
        """Refuse a boolean where a dollar figure belongs."""
        if value is not None and isinstance(value, bool):
            raise ValueError("Available cash must be a number, not a boolean")
        return value

    # Require an equity value that can size the personal account.
    @field_validator("equity")
    @classmethod
    def _equity_finite_positive(cls, value):
        """Reject a nonfinite or nonpositive equity figure."""
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Equity must be finite and greater than zero")
        return value

    # Bound buys only with a finite nonnegative cash figure.
    @field_validator("available_cash")
    @classmethod
    def _cash_finite_nonnegative(cls, value):
        """Reject a nonfinite or negative cash figure; unknown stays None."""
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("Available cash must be finite and nonnegative")
        return value

    # Reject contradictory cash and equity values for this account.
    @model_validator(mode="after")
    def _cash_within_equity(self):
        """Reject a cash figure that exceeds the account equity."""
        if self.available_cash is not None and self.available_cash > self.equity:
            raise ValueError("Available cash cannot exceed account equity")
        return self


# The board against the person's own holdings at the equity given: the
# latest record's targets and levels, the live candle where the feed has
# one, and the person's entry beside each name they hold. Optional personal
# cash bounds recommendations for this read without changing either account.
# The heavy read lives in one shared helper so GET (backward compatible) and
# POST (the channel the page uses) answer identically without duplicating
# business logic; the account figures are validated before any evidence is
# collected.
async def _desk_mine_payload(
    user_id: str, equity: float, available_cash: float | None
) -> dict[str, object]:
    latest, _previous = deskrecord.latest_pair(_root())
    rows = holdings.load(_root())
    if latest is None:
        return {"user_id": user_id, "session": None, "rows": []}
    from backend.market import event_status

    latest = event_status.for_planning(latest, _root())
    snap = _live_snapshot()
    from backend.market import decision_view, execution_quotes

    quoted = await asyncio.to_thread(
        execution_quotes.fetch, list(latest.get("grades") or {})
    )
    now = datetime.now(UTC)
    # Experimental allocations remain on the research surface; never substitute
    # them for the adopted strategy's targets in the decision endpoint.
    # Each name's position on its own 20-day band at the live price, which is
    # the book's entry trigger. A failure here costs the entry line and
    # nothing else: the plan still renders from the record.
    entries: dict[str, float] = {}
    if snap and snap.get("quotes"):

        class _Quote:
            def __init__(self, fields: dict) -> None:
                self.__dict__.update(fields)

        try:
            reads = await asyncio.to_thread(
                live_technical.entry_now,
                MarketStore(_root()),
                {s: _Quote(f) for s, f in (snap.get("quotes") or {}).items()},
            )
            entries = {
                symbol: read["band_z"]
                for symbol, read in reads.items()
                if read.get("band_z") is not None
            }
        except Exception as exc:  # noqa: BLE001 - the plan stands without it
            print(
                f"desk/mine: live entry read unavailable ({type(exc).__name__}: {exc})"
            )
    decisions = decision_view.build(
        latest,
        rows,
        equity,
        snap or {},
        quoted,
        now,
        None,
        entries,
        # The allocation preview belongs to the account viewing it: a plan
        # naming another account is an explicit unavailable preview.
        expected_account=user_id,
        cash=available_cash,
    )
    if snap is not None and snap.get("quotes"):
        technical, value = desk_freshness.grade_inputs(snap, latest)
        return {
            "user_id": user_id,
            "session": latest.get("session"),
            "as_of": snap.get("as_of"),
            "grade_valid_until": desk_freshness.grade_expiries(
                snap, set(technical) | set(value)
            ),
            "rows": holdings.board(
                latest,
                rows,
                equity,
                snap.get("quotes") or {},
                technical,
                value,
            ),
            "grades_live": holdings.live_grades(latest, technical, value),
            "decisions": decisions,
        }
    symbols = sorted(
        {h.ticker for h in rows}
        | {r["ticker"] for r in latest.get("book") or []}
        | set(latest.get("grades") or {})
    )
    quotes: dict = {}
    technical: dict = {}
    value: dict = {}
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
            try:
                value = await asyncio.to_thread(
                    live_technical.value_now, MarketStore(_root()), found
                )
            except Exception:  # noqa: BLE001 - the board stands without the live read
                value = {}
    except alpaca.AlpacaUnavailableError:
        pass
    as_of = datetime.now(UTC).isoformat(timespec="seconds")
    technical, value = desk_freshness.grade_inputs(
        {
            "as_of": as_of,
            "decision_session": latest.get("session"),
            "quotes": quotes,
            "technical": technical,
            "value": value,
        },
        latest,
    )
    return {
        "user_id": user_id,
        "session": latest.get("session"),
        "as_of": as_of,
        "rows": holdings.board(latest, rows, equity, quotes, technical, value),
        "grades_live": holdings.live_grades(latest, technical, value),
        "decisions": decisions,
        "grade_valid_until": desk_freshness.grade_expiries(
            {"as_of": as_of, "quotes": quotes}, set(technical) | set(value)
        ),
    }


# The historical channel, kept so a caller that cannot send a body still gets
# the personal board. Account figures arrive as query parameters here and are
# validated exactly as the body is, before any evidence is collected.
@router.get("/desk/mine")
async def desk_mine(
    user_id: UserId,
    equity: float = Query(..., gt=0),
    available_cash: float | None = Query(None, ge=0),
) -> dict[str, object]:
    """Return action rows computed against the saved holdings."""
    _operator_only(user_id)
    if not math.isfinite(equity):
        raise HTTPException(status_code=422, detail="Equity must be finite")
    if available_cash is not None and (
        not math.isfinite(available_cash) or available_cash > equity
    ):
        raise HTTPException(
            status_code=422,
            detail="Available cash must be finite and no greater than equity",
        )
    return await _desk_mine_payload(user_id, equity, available_cash)


# The channel the page uses: the confirmed personal account figures travel in
# the request body, never in a URL, and are validated by the body model before
# the shared read runs.
@router.post("/desk/mine")
async def desk_mine_post(user_id: UserId, inputs: DeskMineInput) -> dict[str, object]:
    """Return action rows computed against the saved holdings."""
    _operator_only(user_id)
    return await _desk_mine_payload(user_id, inputs.equity, inputs.available_cash)


# Preview the entire buy budget without persisting cash or placing orders.
@router.post("/desk/funding-preview")
async def desk_funding_preview(user_id: UserId, inputs: dict) -> dict[str, object]:
    _operator_only(user_id)
    try:
        equity = float(
            funding.amount(inputs.get("equity"), "Account equity", positive=True)
        )
        cash = float(funding.amount(inputs.get("available_cash"), "Available cash"))
        latest, _ = deskrecord.latest_pair(_root())
        if latest is None:
            raise HTTPException(
                status_code=409, detail="No evening decision is available"
            )
        snap = _live_snapshot() or {}
        quotes = snap.get("quotes") or {}
        held = holdings.load(_root())
        mode = inputs.get("mode", "evening")
        decision = None
        if mode == "intraday_research":
            decision = intraday_research.load(_root(), latest["session"])
            sizing_record = intraday_research.candidate_record(latest, decision)
            quotes = {
                name: {"last": price, "bar": decision["bar"]}
                for name, price in decision["prices"].items()
            }
        elif mode == "evening":
            sizing_record = latest
        else:
            raise ValueError("Unknown preview mode")
        from backend.market import event_status

        sizing_record = event_status.for_planning(sizing_record, _root())
        rows = holdings.board(sizing_record, held, equity, quotes)
        result = funding.preview(rows, equity, cash)
        if decision:
            result["basis"] = "intraday-macro-research-cash-preview-v1"
        result["reductions"] = funding.reductions(rows, equity) if decision else []
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **result,
        "session": latest.get("session"),
        "calculated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "valid_until": decision["valid_until"] if decision else None,
        "macro": decision["macro"] if decision else None,
        "price_times": {
            r["ticker"]: (quotes.get(r["ticker"]) or {}).get("bar")
            for r in result["rows"]
        },
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
        try:
            activity = client.fill_activity(
                datetime.now(desk_freshness.NEW_YORK).date()
            )
        except (
            alpaca_trading.AlpacaTradingError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ):
            activity = {"reason": "Today's fill history could not be loaded"}
        return {
            "activity": activity,
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


# Read original recommendations alongside an optional nightly grade replay.
@router.get("/desk/history/{ticker}")
async def desk_history(user_id: UserId, ticker: str) -> dict[str, object]:
    """Return recorded recommendations and optional simulated history."""
    _operator_only(user_id)
    from backend.market import recommendation_history

    recommendations = await asyncio.to_thread(
        recommendation_history.load, _root(), ticker.upper()
    )
    path = _root() / "history" / f"{ticker.upper()}.json"
    if not path.exists():
        if not recommendations["observations"]:
            raise HTTPException(status_code=404, detail="no history for that name yet")
        history = {"rows": [], "backtest": None, "horizon": 20, "asof": None}
    else:
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
    return {
        "user_id": user_id,
        "ticker": ticker.upper(),
        **history,
        "recommendations": recommendations,
    }


# Where every graded name sits as an ENTRY, right now.
#
# The board answers "what should I hold". It never answered "is now a time
# to buy it", which is the question a trader has while a price is moving.
# The desk has measured that since `entry.py` was written and used it
# nowhere but the backtest.
#
# Ordering is the point of this endpoint, so it is stated rather than left
# to the browser: a name with a trigger firing comes before one without;
# a dip comes before a breakout, because the dip edge is larger per session
# and decays within the week while the breakout's runs a month; a dip while
# the basket falls comes before an ordinary dip, that being the strongest
# reading measured; and within a tie the better grade wins, then the deeper
# position in the band. Names the desk does not want to hold at all are not
# entries and are left out.
@router.get("/desk/entries")
async def desk_entries(user_id: UserId, grades: str = "A+,A") -> dict[str, object]:
    """Return the graded names ranked by how good an entry they are now."""
    _operator_only(user_id)
    latest, _previous = deskrecord.latest_pair(_root())
    if latest is None:
        return {
            "user_id": user_id,
            "session": None,
            "rows": [],
            "reason": "no decision on file",
        }
    wanted = {g.strip() for g in grades.split(",") if g.strip()}
    snap = _live_snapshot() or {}
    quoted = snap.get("quotes") or {}
    graded = latest.get("grades") or {}
    if not quoted:
        return {
            "user_id": user_id,
            "session": latest.get("session"),
            "as_of": snap.get("as_of"),
            "rows": [],
            "reason": "No live quotes this candle; entries need a current price.",
        }

    class _Quote:
        def __init__(self, fields: dict) -> None:
            self.__dict__.update(fields)

    found = {
        symbol: _Quote(fields)
        for symbol, fields in quoted.items()
        if (graded.get(symbol) or {}).get("grade") in wanted
    }
    if not found:
        return {
            "user_id": user_id,
            "session": latest.get("session"),
            "as_of": snap.get("as_of"),
            "rows": [],
            "reason": f"No name is graded {' or '.join(sorted(wanted))} right now.",
        }
    try:
        reads = await asyncio.to_thread(
            live_technical.entry_now, MarketStore(_root()), found
        )
    except Exception as exc:  # noqa: BLE001 - the board stands without this
        raise HTTPException(
            status_code=503, detail=f"entry read unavailable: {exc}"
        ) from exc

    # Breakout first, because that is the trigger the book now acts on. The
    # paper book's mid-cycle entry takes the upper tail only: the dip tail
    # was measured again over the regime the book trades and stopped paying
    # there. The dip rows stay, because the dip this panel reads is a
    # different and shorter signal than the one that was dropped - five
    # sessions, not the book's hold - and it is still worth a trader seeing.
    # They rank below the entries the desk will actually take.
    order = {"breakout": 0, "dip": 1, None: 2}
    rows = []
    for symbol, read in reads.items():
        grade = (graded.get(symbol) or {}).get("grade")
        quote = quoted.get(symbol) or {}
        rows.append(
            {
                "ticker": symbol,
                "grade": grade,
                "trigger": read["trigger"],
                "with_the_basket_falling": read["with_the_basket_falling"],
                "band_z": read["band_z"],
                "stretch_21": read["stretch_21"],
                "horizon_sessions": read["horizon_sessions"],
                "last": quote.get("last"),
                "bar": quote.get("bar"),
            }
        )
    grade_rank = {"A+": 0, "A": 1, "B": 2, "C": 3}
    rows.sort(
        key=lambda r: (
            order.get(r["trigger"], 2),
            0 if r["with_the_basket_falling"] else 1,
            grade_rank.get(r["grade"], 9),
            r["band_z"] if r["band_z"] is not None else 9.0,
        )
    )
    return {
        "user_id": user_id,
        "session": latest.get("session"),
        "as_of": snap.get("as_of"),
        "bar": (next(iter(quoted.values())) or {}).get("bar"),
        "rows": rows,
        # What each trigger was worth when it was measured, so the page can
        # say it rather than implying an entry is free money.
        "edges": {
            "dip": {
                "horizon_sessions": 5,
                "excess": 0.012,
                "with_basket_falling": 0.021,
            },
            "breakout": {"horizon_sessions": 20, "excess": 0.013},
        },
    }


# One name's drawable price history with the averages and bands the desk
# scores on. Split from /desk/history deliberately: that endpoint answers
# "what did the desk conclude", this one answers "what was it looking at",
# and a drill-down that only wants the grades should not pay to read bars.
@router.get("/desk/chart/{ticker}")
async def desk_chart(
    user_id: UserId,
    ticker: str,
    sessions: int = ticker_chart.DEFAULT_SESSIONS,
    timeframe: str = ticker_chart.DAILY,
) -> dict[str, object]:
    """Return adjusted bars, overlay lines and levels for one name."""
    _operator_only(user_id)
    if timeframe not in ticker_chart.TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"timeframe must be one of {', '.join(ticker_chart.TIMEFRAMES)}",
        )
    capped = max(20, min(int(sessions), 2000))
    # The same candle the board reads, so the averages and bands include
    # today rather than ending at the last close while the price moves.
    snap = _live_snapshot() or {}
    quote = (snap.get("quotes") or {}).get(ticker.upper()) or {}
    live_bar = None
    if quote.get("last") is not None and quote.get("bar"):
        live_bar = {
            "session": datetime.fromisoformat(str(quote["bar"]))
            .astimezone(desk_freshness.NEW_YORK)
            .date()
            .isoformat(),
            "last": quote.get("last"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
        }
    built = await asyncio.to_thread(
        ticker_chart.payload,
        MarketStore(_root()),
        ticker.upper(),
        capped,
        timeframe,
        live_bar,
    )
    if built is None:
        raise HTTPException(status_code=404, detail="no price history for that name")
    return {"user_id": user_id, **built}


# The newest earnings release read for one name, straight from the store the
# release reader writes: the tone it scored (guidance / demand / pricing /
# capex), the numbers it extracted, and the session the market could first
# react. The drill-down shows a fresh 8-K the day it lands instead of waiting
# for the next nightly grade to fold it into the score. Read-only; there is
# no analyst-consensus comparison here, only what the release itself said.
@router.get("/desk/earnings/{symbol}")
async def desk_earnings(user_id: UserId, symbol: str) -> dict[str, object]:
    """Return the newest release read for one name, or read None."""
    _operator_only(user_id)
    ticker = symbol.upper()
    frame = MarketStore(_root()).read_frame(language.TONE_KIND, ticker)
    if frame is None:
        return {"user_id": user_id, "symbol": ticker, "read": None}
    records = language.records_from_frame(frame[0])
    if not records:
        return {"user_id": user_id, "symbol": ticker, "read": None}
    # records are oldest reaction first; the last is the newest release.
    last = records[-1]
    today = datetime.now(desk_freshness.NEW_YORK).date()
    return {
        "user_id": user_id,
        "symbol": ticker,
        "read": {
            "reaction_date": last.reaction_date.isoformat(),
            "guidance": last.guidance,
            "demand": last.demand,
            "pricing": last.pricing,
            "capex": last.capex,
            "supply_constrained": last.supply_constrained,
            "quarter_end": last.quarter_end.isoformat() if last.quarter_end else None,
            "revenue_usd_m": last.revenue_usd_m,
            "eps_usd": last.eps_usd,
            "net_income_usd_m": last.net_income_usd_m,
            "gross_margin_pct": last.gross_margin_pct,
            "summary": last.summary,
            "prompt_version": last.prompt_version,
            "same_day": last.reaction_date == today,
        },
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

    passages = await agent_memory.knowledge.search(
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
    if record is not None:
        record = _with_prose(record)
    if record is None:
        raise HTTPException(status_code=404, detail="no desk record for that session")
    return {"user_id": user_id, "record": record}
