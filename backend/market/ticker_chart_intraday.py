"""One name's fifteen-minute bars with the desk's decisions marked on them.

The daily chart (`ticker_chart`) is the smallest bar the operator could
see, and a decision marker on a daily candle says which session the desk
acted on but not when in that session. The operator asked for a
fifteen-minute view with the buy, trim and sell marked on it at the time
they happen. This module draws that view from the raw-basis SIP store
(`intraday_sip`): the last N complete stored sessions, 26 regular bars
each (14 on an early close) plus the closing-auction bar when the
partition has one, on the raw basis the tape printed them, so the
candles are the prices the fills actually crossed at.

WHEN THINGS HAPPEN. A decision is dated to the close it was made at
(`decision_history`): it goes on the session's last regular bar, the
15:45 slot on a normal day. The executor fills a buy or an add at the
next session's open (`market_daily._submit` queues it market-on-open),
so its "fills at" marker goes on the next session's 09:30 bar; an
ordinary sell or trim is queued market-on-close, so its marker goes on
the next session's last regular bar. A recorded fill is placed by the
same convention (a buy on the 09:30 bar, a sell on the close bar) unless
the fill row carries an explicit instant, in which case it goes on the
bar whose quarter hour contains it. Sizes are the policy's target
weight as a whole percent of equity, the way the daily chart writes them.

There are no overlays or levels at this resolution: nothing the desk
scores on is computed from fifteen-minute bars. The one line offered is
the session VWAP (closes weighted by volume, restarting each session),
which is the reference a trader checks a fill against.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.market import intraday_sip
from backend.market.alpaca import IntradayBar
from backend.market.store import MarketStore

TIMEFRAME = "15m"
DEFAULT_SESSIONS = 10
MIN_SESSIONS, MAX_SESSIONS = 1, 60
BASIS = "raw prices as printed (consolidated SIP)"
# The actions the daily chart draws; a hold is no marker.
TRADED_ACTIONS = ("buy", "sell", "add", "trim")
# The actions the executor sends market-on-open; the rest go market-on-close.
OPEN_FILLED = ("buy", "add")
# The fill-row keys an explicit fill instant may sit under.
FILL_INSTANT_KEYS = ("filled_at", "time", "at")


# The number of sessions to draw, clamped to what the endpoint allows.
def clamp_sessions(sessions: int | None) -> int:
    """Return ``sessions`` within [MIN_SESSIONS, MAX_SESSIONS], default 10."""
    if sessions is None:
        return DEFAULT_SESSIONS
    return max(MIN_SESSIONS, min(int(sessions), MAX_SESSIONS))


# Read one name's history file the way `/desk/history/{ticker}` does, or
# None when the nightly has not written one.
def read_history(root: Path, ticker: str) -> dict[str, Any] | None:
    """Return the parsed `<root>/history/<TICKER>.json`, or None."""
    path = Path(root) / "history" / f"{ticker.upper()}.json"
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


# A bar's start as ISO-8601 in New York with its offset, so the browser
# shows the time a trader means without guessing a zone.
def _iso_new_york(instant: datetime) -> str:
    return instant.astimezone(intraday_sip.NEW_YORK).isoformat()


# The last N complete stored sessions of the ticker, oldest first, with
# their bars. Walks back from the newest partition and stops once N are
# found, reading at most twice that many plus a few, so a name with a long
# history is not read whole to draw its last two weeks.
def _complete_sessions(
    store: MarketStore, ticker: str, sessions: int
) -> list[tuple[date, list[IntradayBar], IntradayBar | None]]:
    """Return [(session, regular bars, auction bar or None)] oldest first."""
    found: list[tuple[date, list[IntradayBar], IntradayBar | None]] = []
    budget = sessions * 2 + 5
    for session in reversed(intraday_sip.sessions_available(store, ticker)):
        if len(found) >= sessions or budget <= 0:
            break
        budget -= 1
        try:
            read = intraday_sip.read_session_full(store, ticker, session)
        except intraday_sip.SipStoreError:
            continue
        if read is None:
            continue
        regular, auction, meta = read
        if meta.get("complete") != "true" or not regular:
            continue
        found.append((session, regular, auction))
    found.reverse()
    return found


# The exchange sessions the drawn range should hold and which of them the
# store lacks: (status, reason, missing dates, expected dates). Mirrors the
# daily chart's rule: a year the calendar has not reviewed makes the
# count unavailable rather than guessed.
def _data_status(
    drawn: list[date],
) -> tuple[str, str | None, list[str], list[date]]:
    if not drawn:
        return "unavailable", "no fifteen-minute sessions stored", [], []
    expected, unreviewed = intraday_sip.calendar_sessions(drawn[0], drawn[-1])
    if unreviewed:
        return (
            "unavailable",
            "Exchange calendar coverage unavailable for "
            + ", ".join(str(y) for y in unreviewed),
            [],
            drawn,
        )
    have = set(drawn)
    missing = [d.isoformat() for d in expected if d not in have]
    if missing:
        return (
            "incomplete",
            f"Missing fifteen-minute sessions for {len(missing)} exchange sessions",
            missing,
            expected,
        )
    return "complete", None, [], expected


# The words on a decision marker, the way the daily chart writes them:
# the action and the size it leads to. None for a hold or an unknown action.
def decision_text(action: str, target_weight: float | None) -> str | None:
    """Return "Buy 14%", "Add →20%", "Trim →20%" or "Sell", or None."""
    pct = round((target_weight or 0.0) * 100)
    if action == "buy":
        return f"Buy {pct}%"
    if action == "add":
        return f"Add →{pct}%"
    if action == "trim":
        return f"Trim →{pct}%"
    if action == "sell":
        return "Sell"
    return None


# The session VWAP for every drawn bar: closes weighted by volume since
# the session's open, restarting each session, None where no volume has
# printed yet. The auction bar continues the session it closes.
def _session_vwap(
    per_session: list[tuple[date, list[IntradayBar], IntradayBar | None]],
) -> list[float | None]:
    out: list[float | None] = []
    for _session, regular, auction in per_session:
        notional = volume = 0.0
        for bar in regular + ([auction] if auction is not None else []):
            v = float(bar.volume or 0.0)
            if v > 0 and bar.close is not None:
                notional += float(bar.close) * v
                volume += v
            out.append(round(notional / volume, 4) if volume > 0 else None)
    return out


# An explicit fill instant from a fill row, or None when the row carries
# only a date (the nightly's fills do).
def _fill_instant(fill: dict[str, Any]) -> datetime | None:
    for key in FILL_INSTANT_KEYS:
        raw = fill.get(key)
        if not isinstance(raw, str):
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        return parsed
    return None


# The bar of a session whose quarter hour contains an instant, or None
# when the instant falls outside every drawn bar of that session.
def _bar_containing(
    instant: datetime, regular: list[IntradayBar], auction: IntradayBar | None
) -> IntradayBar | None:
    width = timedelta(minutes=intraday_sip.BAR_MINUTES)
    for bar in regular + ([auction] if auction is not None else []):
        if bar.start <= instant < bar.start + width:
            return bar
    return None


# The decision markers and the "fills at" markers they imply, from the
# history rows whose session is drawn. The decision sits on the session's
# last regular bar; the fill it leads to sits on the next exchange
# session's 09:30 bar for a buy or an add and its last regular bar for a
# sell or a trim, only when that next session is drawn (a gap in the
# store must not move a fill onto a later day).
def _decision_markers(
    history: dict[str, Any] | None,
    per_session: list[tuple[date, list[IntradayBar], IntradayBar | None]],
    expected: list[date],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_date = {s.isoformat(): (regular, auction) for s, regular, auction in per_session}
    order = [d.isoformat() for d in expected] or sorted(by_date)
    next_of = {d: order[i + 1] for i, d in enumerate(order[:-1])}
    decisions: list[dict[str, Any]] = []
    fills_at: list[dict[str, Any]] = []
    for row in (history or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "")
        session = str(row.get("date") or "")[:10]
        if action not in TRADED_ACTIONS or session not in by_date:
            continue
        weight = row.get("target_weight")
        weight = float(weight) if isinstance(weight, (int, float)) else None
        text = decision_text(action, weight)
        if text is None:
            continue
        regular, _auction = by_date[session]
        decisions.append(
            {
                "time": _iso_new_york(regular[-1].start),
                "date": session,
                "action": action,
                "target_weight": weight,
                "label": f"{text} decided at the close",
            }
        )
        following = next_of.get(session)
        if following is None or following not in by_date:
            continue
        next_regular, _next_auction = by_date[following]
        at_open = action in OPEN_FILLED
        fills_at.append(
            {
                "time": _iso_new_york(
                    (next_regular[0] if at_open else next_regular[-1]).start
                ),
                "date": following,
                "action": action,
                "target_weight": weight,
                "label": f"{text} fills at the {'open' if at_open else 'close'}",
            }
        )
    return decisions, fills_at


# The paper account's fills on the drawn sessions, each on the bar the
# executor's convention puts it on (a buy fills at the open, a sell at
# the close) unless the row says when it filled.
def _fill_markers(
    history: dict[str, Any] | None,
    per_session: list[tuple[date, list[IntradayBar], IntradayBar | None]],
) -> list[dict[str, Any]]:
    by_date = {s.isoformat(): (regular, auction) for s, regular, auction in per_session}
    out: list[dict[str, Any]] = []
    for fill in (history or {}).get("fills") or []:
        if not isinstance(fill, dict):
            continue
        side = str(fill.get("side") or "").lower()
        session = str(fill.get("date") or "")[:10]
        if side not in ("buy", "sell") or session not in by_date:
            continue
        try:
            qty = int(fill.get("qty") or 0)
            price = float(fill.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or price <= 0:
            continue
        regular, auction = by_date[session]
        instant = _fill_instant(fill)
        bar = _bar_containing(instant, regular, auction) if instant else None
        if bar is None:
            bar = regular[0] if side == "buy" else regular[-1]
        out.append(
            {
                "time": _iso_new_york(bar.start),
                "date": session,
                "side": side,
                "qty": qty,
                "price": price,
                "label": f"Filled {side} {qty} @ {price:.2f}",
            }
        )
    return out


# The wire shape: the same top-level keys as the daily chart where they
# apply, the bars stamped with their New York start, and the three marker
# lists computed from the history file. None when the store holds no
# partition for the name at all, which the API answers with a 404 the way
# the daily chart does for a name with no price history.
def payload(
    store: MarketStore,
    root: Path | str,
    ticker: str,
    sessions: int | None = DEFAULT_SESSIONS,
    history: dict[str, Any] | None = None,
) -> dict[str, object] | None:
    """Return the fifteen-minute chart of ``ticker`` as JSON-ready data, or None."""
    ticker = ticker.upper()
    wanted = clamp_sessions(sessions)
    if not intraday_sip.sessions_available(store, ticker):
        return None
    if history is None:
        history = read_history(Path(root), ticker)
    per_session = _complete_sessions(store, ticker, wanted)
    drawn = [s for s, _r, _a in per_session]
    status, reason, missing, expected = _data_status(drawn)
    bars: list[dict[str, object]] = []
    for session, regular, auction in per_session:
        for bar in regular:
            bars.append(
                {
                    "time": _iso_new_york(bar.start),
                    "date": session.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
            )
        if auction is not None:
            bars.append(
                {
                    "time": _iso_new_york(auction.start),
                    "date": session.isoformat(),
                    "open": auction.open,
                    "high": auction.high,
                    "low": auction.low,
                    "close": auction.close,
                    "volume": auction.volume,
                    "auction": True,
                }
            )
    decisions, fills_at = _decision_markers(history, per_session, expected)
    return {
        "ticker": ticker,
        "timeframe": TIMEFRAME,
        "last_bar_complete": True,
        "quote_bar": None,
        "data_status": status,
        "data_reason": reason,
        "missing_sessions": missing,
        "adjusted": False,
        "basis": BASIS,
        "sessions": len(per_session),
        "sessions_requested": wanted,
        "bars": bars,
        "entries": [],
        "overlays": {"session_vwap": _session_vwap(per_session)} if bars else {},
        "levels": {},
        "decisions": decisions,
        "fills_at": fills_at,
        "fills": _fill_markers(history, per_session),
    }
