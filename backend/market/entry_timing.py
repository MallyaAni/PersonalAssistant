"""When the board may act on a nightly decision inside the session: the measured level.

The nightly record decides WHAT the book holds (the `/4` targets, the
downgrade exits, the trims at the reset). This module decides WHEN, inside
the next session, the board may say BUY, SELL or TRIM for it, and it decides
nothing else.

The rule is the `dip_or_close` convention measured in
`docs/research/execution-timing-2026-09-27.md` (the engine is
`backend/market/fill_timing.py`, whose `DIP` this module reuses rather than
restates): a buy fills at the first 15-minute bar CLOSE of the session at or
below the session's open times (1 - DIP), else at the close; a sell - and a
trim, which is a sell - mirrors it: the first bar close at or above the open
times (1 + DIP), else at the close. Priced on the `/4` policy's own orders it
earned -0.1 bp a day (t -0.2) on 2016-2023 and +1.0 bp a day (t 2.2) on
2024-2026 against the next open: a price gate that costs nothing. It was
RECORDED, NOT ACTED ON for the paper executor, which still fills at the next
open; the board adopts it for the operator's own manual execution.

Two halves.

`update(root, snapshot, now)` runs on every balancer candle (`market_balancer`
calls it right after writing `live.json`). For each quote it latches, per
session, the session's open and the FIRST bar whose close crossed the level
on each side, in `data/market/desk/entry-timing/<session>.json`. The snapshot
carries only the latest completed bar per name, so the latch is what makes
"a close at or under the level happened today" survive the price moving back
up. A trigger is never un-set.

`timing(latch_row, quote, side, now, session)` turns the latch and the clock
into one of five states for one name and one side:

  pre-open   no opening bar yet today, or no session today at all
  waiting    today's open is known and no close has reached the level
  triggered  a 15-minute close reached the level today: act now
  close      the close window (session close - 30 minutes, 15:30 ET or
             12:30 ET on an early close) with no trigger: act at the close,
             market-on-close before its entry cutoff (close - 10 minutes)
  closed     the session is over; its decisions are finished

Only `triggered` and `close` let a BUY/SELL/TRIM stand (`ACTING`).
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.market import calendar
from backend.market.fill_timing import DIP

# The measured level, as a fraction of the session's open. Reused from the
# research engine so the board and the study can never disagree about it.
LEVEL = DIP
RULE = "dip_or_close"
NEW_YORK = calendar.NEW_YORK
# Where the per-session latch files live, under the desk data root.
LATCH_DIR = "entry-timing"
# How many session files are kept; older ones are pruned on each update.
KEEP_SESSIONS = 30
# One candle.
BAR = timedelta(minutes=15)
# The close window opens this long before the session's close.
CLOSE_WINDOW = timedelta(minutes=30)
# The exchange's market-on-close entry cutoff (3:50 PM ET on a 4:00 close).
MOC_LEAD = timedelta(minutes=10)
PRE_OPEN = "pre-open"
WAITING = "waiting"
TRIGGERED = "triggered"
CLOSE = "close"
CLOSED = "closed"
STATES = (PRE_OPEN, WAITING, TRIGGERED, CLOSE, CLOSED)
# The states in which a timed BUY/SELL/TRIM stands.
ACTING = (TRIGGERED, CLOSE)
CURRENT_ENTRY = "current-dip-limit/1"
SIDES = ("buy", "sell")
_SESSION_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


# A finite positive price, or None for anything a level cannot be built on.
def _price(value: object) -> float | None:
    """Return `value` as a finite positive float, else None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


# A timezone-aware instant from an ISO string, or None.
def _instant(value: object) -> datetime | None:
    """Return the aware datetime `value` names, else None."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


# The New York date a quote's bar belongs to: the session it describes.
def quote_session(quote: dict | None) -> date | None:
    """Return the New York date of the quote's bar, else None."""
    bar = _instant((quote or {}).get("bar"))
    return bar.astimezone(NEW_YORK).date() if bar else None


# The level each side waits for, from the session's open: at or under
# open x (1 - LEVEL) for a buy, at or over open x (1 + LEVEL) for a sell.
# The same arithmetic as `fill_timing._dip_or_close`, so the boundary is the
# research's boundary.
def level_for(opened: float, side: str) -> float:
    """Return the price `side` waits for, given the session's open."""
    if side == "buy":
        return opened * (1.0 - LEVEL)
    if side == "sell":
        return opened * (1.0 + LEVEL)
    raise ValueError(f"side must be buy or sell, not {side!r}")


# Whether a bar close reached the side's level: <= for a buy, >= for a sell.
def crosses(close: float, opened: float, side: str) -> bool:
    """Return True when `close` is at or through `side`'s level."""
    level = level_for(opened, side)
    return close <= level if side == "buy" else close >= level


# Where one session's latch lives.
def latch_path(root: Path | str, session: date) -> Path:
    """Return `<root>/desk/entry-timing/<session>.json`."""
    return Path(root) / "desk" / LATCH_DIR / f"{session.isoformat()}.json"


# Read one session's latch, or None when there is none or it cannot be read.
# Never raises: a missing latch only means the board falls back to the
# candle it has.
def load(root: Path | str, session: date) -> dict | None:
    """Return the session's latch document, else None."""
    try:
        data = json.loads(latch_path(root, session).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("session") != session.isoformat():
        return None
    return data


# One name's latch row for `session`, or None when the latch belongs to
# another session or does not know the name.
def row_for(latch: dict | None, symbol: str, session: date) -> dict | None:
    """Return the latch's row for `symbol` on `session`, else None."""
    if not isinstance(latch, dict) or latch.get("session") != session.isoformat():
        return None
    row = (latch.get("symbols") or {}).get(symbol)
    return row if isinstance(row, dict) else None


# Serialise concurrent updates of the latch folder (the cron balancer and a
# manual run) so a read-modify-write can never drop a trigger.
@contextmanager
def _locked(folder: Path):
    """Hold an exclusive lock on the latch folder for the block."""
    import fcntl

    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# Write JSON beside its target and rename it into place, so a reader sees
# either the old file or the new one, never half of one.
def _write_atomic(path: Path, data: dict) -> None:
    """Replace `path` with `data` as JSON atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


# Keep only the newest `keep` session files; the rest are history nobody reads.
def _prune(folder: Path, keep: int = KEEP_SESSIONS) -> None:
    """Delete all but the newest `keep` session latch files."""
    if not folder.is_dir():
        return
    files = sorted(p for p in folder.iterdir() if _SESSION_FILE.match(p.name))
    for stale in files[: max(0, len(files) - keep)]:
        with contextlib.suppress(OSError):
            stale.unlink()


# The earlier of an existing trigger and a new crossing: the latch keeps the
# FIRST bar that reached the level, even if a later bar is read first.
def _first(existing: dict | None, candidate: dict) -> dict:
    """Return whichever trigger names the earlier bar."""
    if not isinstance(existing, dict):
        return candidate
    before = _instant(existing.get("bar"))
    after = _instant(candidate.get("bar"))
    if before is None or (after is not None and after < before):
        return candidate
    return existing


# Whether a bar is the session's opening 15-minute bar (09:30 New York).
def is_opening_bar(bar: datetime) -> bool:
    """Return True when `bar` starts at 09:30 New York time."""
    local = bar.astimezone(NEW_YORK)
    return local.hour == 9 and local.minute == 30


# Fold one completed bar into one name's latch row and return the new row.
# The open is the first one seen (the session's opening bar, which every
# quote carries); the last bar only moves forward; a trigger, once set, is
# only ever replaced by an EARLIER crossing. When the bar read IS the
# opening bar, the quote's session high and last close are that bar's own
# high and close, and they are kept as `first_bar` for the board's level
# tags (`structure.level_tag`), which the later candles can no longer show.
# Receipt times and trigger revisions preserve what earlier decision clocks knew.
def _merge(
    row: dict | None,
    opened: float,
    last: float,
    bar: datetime,
    seen: str,
    high: float | None = None,
) -> dict:
    """Return the latch row after this bar."""
    out = dict(row or {})
    out.setdefault("history_started_at", seen)
    if _price(out.get("open")) is None:
        out["open"] = opened
        out["open_seen_at"] = seen
    if high is not None and is_opening_bar(bar) and "first_bar" not in out:
        out["first_bar"] = {
            "high": high,
            "close": last,
            "bar": bar.isoformat(),
            "seen_at": seen,
        }
    base = float(out["open"])
    out["buy_level"] = level_for(base, "buy")
    out["sell_level"] = level_for(base, "sell")
    known = _instant(out.get("bar"))
    if known is None or bar >= known:
        out["last"] = last
        out["bar"] = bar.isoformat()
    for side in SIDES:
        key = f"{side}_trigger"
        out.setdefault(key, None)
        if crosses(last, base, side):
            before = out.get(key)
            after = _first(
                before, {"bar": bar.isoformat(), "price": last, "seen_at": seen}
            )
            if after != before:
                versions = list(out.get(f"{key}_versions") or [])
                if before is not None and before not in versions:
                    versions.append(before)
                versions.append(after)
                out[f"{key}_versions"] = versions
            out[key] = after
    return out


# Latch today's opens and first crossings from one balancer snapshot.
#
# For every quote with a usable open, last close and bar, the session is the
# New York date of the bar; the session's file is read, each name's row is
# merged (`_merge`), and the file is written atomically only when something
# changed, so running the same snapshot twice writes nothing the second time.
# Only received, completed regular-session bars are admitted. Returns the paths
# written. Raises only on a filesystem failure; the balancer's call wraps it.
def update(root: Path | str, snapshot: dict | None, now: datetime) -> list[Path]:
    """Latch opens and first level crossings; return the latch files written."""
    if now.tzinfo is None:
        raise ValueError("update requires a timezone-aware now")
    seen = str((snapshot or {}).get("as_of") or now.isoformat())
    observed = _instant(seen)
    if observed is None or observed > now:
        return []
    by_session: dict[date, dict[str, tuple[float, float, datetime, float | None]]] = {}
    for symbol, quote in ((snapshot or {}).get("quotes") or {}).items():
        values = _completed_quote(quote, observed)
        if values is not None:
            by_session.setdefault(values[2].astimezone(NEW_YORK).date(), {})[
                str(symbol)
            ] = values
    folder = Path(root) / "desk" / LATCH_DIR
    written: list[Path] = []
    if not by_session:
        return written
    with _locked(folder):
        for session, names in sorted(by_session.items()):
            path = latch_path(root, session)
            current = load(root, session) or {}
            symbols = dict(current.get("symbols") or {})
            before = json.dumps(symbols, sort_keys=True)
            for symbol, (opened, last, bar, high) in names.items():
                symbols[symbol] = _merge(
                    symbols.get(symbol), opened, last, bar, seen, high
                )
            if json.dumps(symbols, sort_keys=True) == before and current:
                continue
            _write_atomic(
                path,
                {
                    "session": session.isoformat(),
                    "rule": RULE,
                    "level": LEVEL,
                    "updated_at": now.isoformat(),
                    "symbols": symbols,
                },
            )
            written.append(path)
        _prune(folder)
    return written


# Whether a date is a regular XNYS session on the reviewed calendar (the
# historical sessions file and the published current years). A date the
# calendar does not cover is not a session here: the board fails closed.
def _is_session(day: date) -> bool:
    """Return True when `day` is a reviewed trading session."""
    import numpy as np

    years, sessions = calendar.reviewed_sessions()
    return day.year in years and bool(
        np.is_busday(np.datetime64(day, "D"), busdaycal=sessions)
    )


# The instants that bound one session's decisions: its open, the close
# window's start (close - 30 minutes), the market-on-close entry cutoff
# (close - 10 minutes) and its close, all in New York time. The close is the
# calendar's, so an early close moves all three.
def session_clock(session: date) -> dict[str, datetime]:
    """Return {"open", "cutoff", "moc", "close"} for `session`."""
    closes = datetime.combine(session, calendar.session_close(session), NEW_YORK)
    return {
        "open": datetime.combine(session, calendar.REGULAR_OPEN, NEW_YORK),
        "cutoff": closes - CLOSE_WINDOW,
        "moc": closes - MOC_LEAD,
        "close": closes,
    }


# A price as the operator reads it: floored to the cent for a buy level and
# ceiled for a sell level, so "at or under $X" is exactly true of a close
# quoted in cents.
def _level_text(level: float, side: str) -> str:
    """Return the level as dollars, rounded the safe way for `side`."""
    cents = level * 100.0
    cents = math.floor(cents + 1e-6) if side == "buy" else math.ceil(cents - 1e-6)
    return f"${cents / 100.0:,.2f}"


# Dollars to the cent.
def _money(value: float) -> str:
    """Return `value` as $1,234.56."""
    return f"${value:,.2f}"


# A New York wall-clock time as the board writes it: 3:30 PM.
def _clock(instant: datetime) -> str:
    """Return `instant` in New York as h:mm AM/PM."""
    local = instant.astimezone(NEW_YORK)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


# "under" for a buy's level, "over" for a sell's.
def _way(side: str) -> str:
    """Return the preposition that goes with `side`'s level."""
    return "under" if side == "buy" else "over"


# Check both market time and observation time before a completed regular bar is usable.
def _observable(bar: datetime | None, seen: Any, now: datetime, session: date) -> bool:
    observed = _instant(seen)
    clock = session_clock(session)
    return bool(
        bar is not None
        and observed is not None
        and clock["open"] <= bar < bar + BAR <= clock["close"]
        and bar + BAR <= observed <= now
        and (bar - clock["open"]).total_seconds() % BAR.total_seconds() == 0
    )


# Admit a quote for persistence only after its completed bar and receipt are observable.
def _completed_quote(quote, now):
    if not isinstance(quote, dict):
        return None
    bar = _instant(quote.get("bar"))
    opened, last = _price(quote.get("open")), _price(quote.get("last"))
    if bar is None or opened is None or last is None:
        return None
    session = bar.astimezone(NEW_YORK).date()
    if _is_session(session) and _observable(bar, quote.get("as_of"), now, session):
        return opened, last, bar, _price(quote.get("high"))
    return None


# Select the earliest observed crossing, retaining revised historical prefixes.
def _observed_trigger(row, opened, side, now, session):
    key = f"{side}_trigger"
    candidates = [row.get(key), *(row.get(f"{key}_versions") or [])]
    valid = [
        found
        for found in candidates
        if isinstance(found, dict)
        and _price(found.get("price")) is not None
        and _observable(_instant(found.get("bar")), found.get("seen_at"), now, session)
        and crosses(float(found["price"]), opened, side)
    ]
    return min(valid, key=lambda found: _instant(found["bar"]), default=None)


# The opening price and this side's trigger for one name on `session`, from
# the latch first and the current quote second. The quote counts only when
# its bar belongs to `session` and was complete at `now`; a quote whose own
# close crosses the level is a trigger even when the latch missed it (the
# first crossing is then at or before that bar, so the rule has filled).
def _open_and_trigger(
    latch_row: dict | None, quote: dict | None, side: str, now: datetime, session: date
) -> tuple[float | None, dict | None]:
    """Return (the session's open, this side's trigger) or Nones."""
    opened = _price((latch_row or {}).get("open"))
    if "open_seen_at" in (latch_row or {}):
        seen = _instant(latch_row["open_seen_at"])
        if seen is None or seen > now:
            opened = None
    trigger = None
    if opened is not None:
        trigger = _observed_trigger(latch_row or {}, opened, side, now, session)
    bar = _instant((quote or {}).get("bar"))
    if _observable(bar, (quote or {}).get("as_of"), now, session):
        quote_open = _price(quote.get("open"))
        quote_last = _price(quote.get("last"))
        if opened is None:
            opened = quote_open
        if (
            trigger is None
            and opened is not None
            and quote_last is not None
            and crosses(quote_last, opened, side)
        ):
            trigger = {
                "bar": bar.isoformat(),
                "price": quote_last,
                "seen_at": quote.get("as_of"),
            }
    return opened, trigger


# One name's timing on one side at `now`: the state, the level it waits for,
# the session's open, the bar that triggered it, and one sentence saying so.
#
# Precedence, first match wins: no session that day -> pre-open; before the
# open -> pre-open; at or after the close -> closed; a trigger (latched, or
# the current bar's own close) -> triggered; inside the close window ->
# close; an open with no trigger -> waiting; otherwise (the opening bar has
# not completed yet) -> pre-open. A trigger outranks the close window
# because the rule fills at the first crossing and uses the close only when
# there was none.
def timing(
    latch_row: dict | None,
    quote: dict | None,
    side: str,
    now: datetime,
    session: date,
) -> dict[str, Any]:
    """Return {state, side, level, open, trigger_bar, trigger_price, reason, ...}."""
    if side not in SIDES:
        raise ValueError(f"side must be buy or sell, not {side!r}")
    if now.tzinfo is None:
        raise ValueError("timing requires a timezone-aware now")
    clock = session_clock(session)
    way = _way(side)
    pct = f"{LEVEL:.0%}"
    trading_day = _is_session(session)
    out: dict[str, Any] = {
        "rule": RULE,
        "side": side,
        "level_fraction": LEVEL,
        "session": session.isoformat(),
        "trading_day": trading_day,
        "open": None,
        "level": None,
        "trigger_bar": None,
        "trigger_price": None,
        "close_cutoff": clock["cutoff"].isoformat(),
        "moc_deadline": clock["moc"].isoformat(),
    }

    if not trading_day:
        state, reason = (
            PRE_OPEN,
            f"No regular session on {session.isoformat()}; the next session's first "
            f"15-minute bar sets its open and the level {pct} {way} it",
        )
    elif now < clock["open"]:
        state, reason = (
            PRE_OPEN,
            f"Before the open: the first 15-minute bar (9:30-9:45 AM ET) sets "
            f"today's open; the level is {pct} {way} it",
        )
    elif now >= clock["close"]:
        state, reason = (
            CLOSED,
            f"The {session.isoformat()} session has closed; the next session sets a "
            "new open and level",
        )
    else:
        state, reason = _in_session(out, latch_row, quote, now, session, clock)
    out["state"] = state
    out["reason"] = reason
    return out


# Keep a recorded dip separate from permission to make a new purchase at today's ask.
def buy_permission(timed: dict, evidence: dict, now: datetime) -> dict | None:
    """Bound a fresh personal entry; preserve the historical timing unchanged."""
    if timed.get("side") != "buy" or timed.get("state") != TRIGGERED:
        return None
    from backend.market.bounded_execution import limit_text

    level = _price(timed.get("level"))
    try:
        label = limit_text(level, "buy") if level else None
    except ValueError:
        label = None
    limit = float(label) if label else None
    ask = _price(evidence.get("ask"))
    observed = _instant(evidence.get("at"))
    expires = _instant(evidence.get("valid_until"))
    ready = (
        evidence.get("eligible") is True
        and ask is not None
        and limit is not None
        and observed is not None
        and expires is not None
        and observed <= now < expires
    )
    allowed = bool(ready and ask <= limit)
    ask_label = f"{ask:,.2f}" if ask and ask >= 1 else f"{ask:.4f}" if ask else None
    feed = str(evidence.get("feed") or "Quote").upper()
    reason = (
        f"Buy limit ${label}"
        if allowed
        else f"{feed} ask ${ask_label} exceeds ${label} entry limit"
        if ready
        else "Current entry quote unavailable"
    )
    return {
        "policy": CURRENT_ENTRY,
        "allowed": allowed,
        "limit_price": limit,
        "ask": ask,
        "quote_at": evidence.get("at"),
        "valid_until": evidence.get("valid_until"),
        "feed": evidence.get("feed"),
        "reason": reason,
    }


# The state of one name inside the regular session, filling `out`'s open,
# level and trigger fields: triggered, close, waiting, or pre-open while the
# opening bar has not completed. Split from `timing` only to keep each part
# readable; `timing` documents the precedence.
def _in_session(
    out: dict[str, Any],
    latch_row: dict | None,
    quote: dict | None,
    now: datetime,
    session: date,
    clock: dict[str, datetime],
) -> tuple[str, str]:
    """Return (state, reason) for a moment inside the regular session."""
    side = out["side"]
    opened, trigger = _open_and_trigger(latch_row, quote, side, now, session)
    if opened is not None:
        out["open"] = opened
        out["level"] = level_for(opened, side)
    if trigger is not None and opened is not None:
        out["trigger_bar"] = trigger.get("bar")
        out["trigger_price"] = float(trigger["price"])
        return TRIGGERED, f"Triggered: {_trigger_text(out)}"
    if now >= clock["cutoff"]:
        return CLOSE, f"At the close: {_close_text(out)}"
    if opened is None:
        return PRE_OPEN, (
            "No opening bar yet today: the first 15-minute bar sets the open; the "
            f"level is {LEVEL:.0%} {_way(side)} it"
        )
    return WAITING, (
        f"Waiting for a 15-minute close at or {_way(side)} {_where(out)}; at the "
        f"close from {_clock(clock['cutoff'])} ET if none"
    )


# "$99.00 (1% under today's open $100.00)": the level as the operator reads it
# and where it comes from.
def _where(timed: dict[str, Any]) -> str:
    """Return the level and its source for a timing with an open."""
    side = timed["side"]
    way = _way(side)
    return (
        f"{_level_text(timed['level'], side)} ({LEVEL:.0%} {way} today's open "
        f"{_money(timed['open'])})"
    )


# "the 10:30 AM ET 15-minute close $98.90 is at or under $99.00 (...)": the
# bar that reached the level, named by the time it closed.
def _trigger_text(timed: dict[str, Any]) -> str:
    """Return the sentence naming a timing's trigger."""
    bar = _instant(timed.get("trigger_bar"))
    ended = f"the {_clock(bar + BAR)} ET" if bar else "a"
    return (
        f"{ended} 15-minute close {_money(float(timed['trigger_price']))} is at or "
        f"{_way(timed['side'])} {_where(timed)}"
    )


# "no 15-minute close reached $99.00 today; market-on-close before 3:50 PM
# ET": what acting at the close means, with the level when there is one.
def _close_text(timed: dict[str, Any]) -> str:
    """Return the sentence for acting at the close."""
    moc = _instant(timed.get("moc_deadline"))
    order = f"market-on-close before {_clock(moc)} ET" if moc else "market-on-close"
    if timed.get("level") is None:
        return order
    level = _level_text(timed["level"], timed["side"])
    return f"no 15-minute close reached {level} today; {order}"


# The sentence a timed Hold carries in place of a BUY/SELL/TRIM that is not
# due yet: what is planned, how big, and the condition that makes it due.
# `word` is Buy, Sell or Trim; `size` the weight it would move.
def planned(word: str, size: float, timed: dict[str, Any]) -> str:
    """Return e.g. "Buy 9.1% planned: on a 15-minute close at or under $X ..."."""
    way = _way(timed["side"])
    pct = f"{LEVEL:.0%}"
    head = f"{word} {size:.1%} planned"
    if timed["state"] == CLOSED:
        return f"{head}: the session has closed; the next session sets a new level"
    if timed.get("open") is not None and timed.get("level") is not None:
        return (
            f"{head}: on a 15-minute close at or {way} {_where(timed)}, "
            "else at the close"
        )
    if timed.get("trading_day"):
        return (
            f"{head}: on a 15-minute close {pct} or more {way} today's open "
            "(the 9:30 AM ET bar), else at the close"
        )
    return (
        f"{head}: on a 15-minute close {pct} or more {way} the next session's "
        "open, else at its close"
    )


# The sentence a timed BUY/SELL/TRIM carries while it stands: why now.
def acting(word: str, timed: dict[str, Any]) -> str:
    """Return e.g. "Buy now: the 10:30 AM ET ..." or "Buy at the close: ..."."""
    if timed["state"] == TRIGGERED:
        return f"{word} now: {_trigger_text(timed)}"
    return f"{word} at the close: {_close_text(timed)}"
