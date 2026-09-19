"""Present the adopted plan's eligibility without promoting research allocations."""

import math
from datetime import UTC, datetime
from enum import Enum

import numpy as np

from backend.agents.trading.desk.actions import action_for
from backend.market import (
    calendar,
    desk_freshness,
    execution_quotes,
    holdings,
    opportunity,
)

VERSION = "desk-decision-view/1"


# The three things the operator can do about a name. A fixed set, so it is a
# type rather than a string literal repeated at a dozen call sites: the old
# vocabulary had seven spellings across the backend, the API contract and the
# page, and "Buy eligible" against "Buy tonight" against "buy" was a bug
# waiting to happen. The str mixin keeps it a plain string over the wire.
class Action(str, Enum):
    """What to do about a name right now."""

    BUY = "Buy"
    SELL = "Sell"
    HOLD = "Hold"


# Three words and a share count: Buy, Sell or Hold, at the live price.
#
# The column used to carry seven states - Buy eligible, Reduce, Wait, Hold,
# blocked, uncovered, and a schedule label beside a share count - and most of
# them answered the desk's calendar rather than the operator's question. He
# reads the board during the session and has to decide what to own by the
# close. So: what does the desk want this name's position to be, right now,
# and how many shares is that away from what he holds?
#
# Everything that used to be its own action is now a Hold with a reason: a
# blocked buy, a stale decision, an FOMC pause and an unpriced name are all
# states in which the answer to "what do I do" is nothing. The reason says
# which, on hover.
def action_for_row(
    row, quote, deadline, paused, current_decision, target, current, now, entry=None
):
    """Return (action, weight, reason): Buy, Sell or Hold, and the weight to move."""
    # Said the way a trader would say it. These were written from inside the
    # system - "No allocation in the adopted plan", "Rebalance timing
    # unavailable" - which names the desk's internals rather than telling the
    # operator what is true of the name in front of him.
    checks = (
        (paused, "FOMC hold"),
        (not row, "Not in the book"),
        (row and not row["in_book"], "Not covered by the desk"),
        (not current_decision, "Last night's decision is stale"),
        (not quote["eligible"], quote["reason"]),
        (not deadline or deadline <= now, "No current price reading"),
        (row and row["until_rebalance"] is None, "Reset timing unknown"),
    )
    reason = next((message for blocked, message in checks if blocked), None)
    if reason:
        return Action.HOLD, 0.0, reason
    # The live entry comes first. It is the one thing on this page that is
    # actionable between resets, and the calendar branch below would otherwise
    # bury it under an answer about a date six months out.
    if entry is not None:
        action, size, why = entry
        return action, (size or 0.0), why
    # A grade falling is NOT a sell, however much it looks like one. Measured
    # on this book over 86,209 holding sessions, a name whose grade falls out
    # of A or better still beat the benchmark by 1.49% over the next twenty
    # sessions (t +4.3) against a +1.95% baseline: the downgrade follows the
    # fall rather than leading it. `desk/exit.py` has the table and the note
    # at the top of `desk/paper.py` records why the book carries no
    # grade-based exit - it cut winners. This view briefly recommended one
    # anyway, which put a retired rule in front of the operator as advice.
    if not row["rebalance_due"]:
        if row["shares"] > 0:
            return Action.HOLD, 0.0, "At its weight; no signal at this price"
        return Action.HOLD, 0.0, "Not held; no entry signal at this price"
    direction = action_for(target, current)
    if row["rejecting_band"] and direction in ("buy", "add"):
        return Action.HOLD, 0.0, "Rejecting its upper band; the buy is held back"
    if direction in ("buy", "add") and row["grade_live"] in ("A", "A+"):
        return Action.BUY, target - current, "Reset is due; below its target weight"
    if direction in ("trim", "sell"):
        return Action.SELL, target - current, "Reset is due; above its target weight"
    return Action.HOLD, 0.0, "At its target weight"


# The book's mid-cycle entry, decided at the live price rather than at the
# close, so the row says what the desk will do tonight instead of what the
# calendar says months from now. The threshold, the grade floor and the name
# cap are read from `paper` rather than restated, because a copy of a trading
# rule in the presentation layer is a copy that drifts.
def entry_action(row, band, grade_live):
    """Return (action, size, reason) when the entry fires now, else None.

    Said in the present tense, and sized. The first version of this answered
    "when does the paper book act", so a name reading 18% above its 21-day at
    eleven in the morning said "Buy tonight" - which describes the desk's cron
    job, not the decision in front of the operator. He is looking at a live
    price and has to size a position against it now. The signal is firing at
    that price, so the row says Buy, and says how much.

    `size` is the weight to put on at this moment, not the eventual target:
    ENTRY_ADD of equity, trimmed to whatever room is left under
    ENTRY_NAME_CAP, which is the increment the nightly would size and the one
    the operator can act on. The target it moves toward is already its own
    column.
    """
    from backend.agents.trading.desk import paper

    if band is None or not math.isfinite(band) or band < paper.ENTRY_BAND_Z:
        return None
    if grade_live not in paper.ENTRY_MIN_GRADE:
        return None
    # The nightly only enters a name the book wants to hold, so a name with no
    # target is not a candidate however far it has run. Without this the row
    # read "Buy - not picked by the sizing engine", which is two statements
    # that cannot both be true.
    if not row or not row.get("target_weight"):
        return None
    # The same gate the nightly applies before it sizes anything.
    if row.get("rejecting_band"):
        return "Wait", None, "Breaking out, but the daily is rejecting its upper band"
    above = f"{band:.1f} on its 20-day band"
    held = row["shares"] > 0
    room = paper.ENTRY_NAME_CAP - row["current_weight"]
    if held and room <= 0:
        return Action.HOLD, None, f"{above}, already at the {paper.ENTRY_NAME_CAP:.0%} name cap"
    size = min(paper.ENTRY_ADD, room)
    if size <= 0:
        return Action.HOLD, None, f"{above}, no room under the {paper.ENTRY_NAME_CAP:.0%} name cap"
    return (
        Action.BUY,
        size,
        f"{above}, funded by trimming the rest",
    )


# Combine existing strategy gates and quote evidence into one dated, reviewable row.
def build(record, held, equity, snapshot, quoted, now=None, targets=None, entries=None):
    now = now or datetime.now(UTC)
    if targets is not None:
        if (
            set(targets) != set(record.get("grades") or {})
            or not all(math.isfinite(w) and 0 <= w <= 1 for w in targets.values())
            or sum(targets.values()) > 1.000001
        ):
            raise ValueError("Complete funded allocation required")
        record = {
            **record,
            "book": [
                {"ticker": name, "weight": weight} for name, weight in targets.items()
            ],
        }
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    rows = {
        r["ticker"]: r
        for r in holdings.board(
            record, held, equity, snapshot.get("quotes") or {}, technical, value
        )
    }
    expiries = desk_freshness.grade_expiries(snapshot, technical)
    readings = holdings.live_grades(record, technical, value)
    event = record.get("event_risk") or {}
    paused = (
        event.get("factor") == 0.5
        or event.get("execution_pending")
        or event.get("calendar_known") is False
    )
    result = {}
    # The plan is current the session it names and the one after (the nightly
    # record is written on the evening of its own session, so requiring
    # strictly the next session labelled a just-written plan "outdated").
    offset = calendar._future_session_offset(
        np.datetime64(record["session"]),
        np.datetime64(now.astimezone(desk_freshness.NEW_YORK).date()),
    )
    current_decision = offset in (0, 1)
    for symbol in sorted(set(record.get("grades") or {}) | set(rows)):
        row = rows.get(symbol)
        quote = execution_quotes.describe(
            (quoted.get("quotes") or {}).get(symbol, {}),
            quoted.get("feed"),
            quoted.get("market_open", False),
            now,
        )
        target = row["target_weight"] if row else 0.0
        current = row["current_weight"] if row else 0.0
        # Compare percentages at the quoted midpoint when valid prices exist.
        if row and "bid" in quote and math.isfinite(equity) and equity > 0:
            current = row["shares"] * (quote["bid"] + quote["ask"]) / (2 * equity)
        entry = entry_action(
            row,
            (entries or {}).get(symbol),
            (readings.get(symbol) or {}).get("grade")
            or (record.get("grades") or {}).get(symbol, {}).get("grade"),
        )
        action, move, reason = action_for_row(
            row,
            quote,
            desk_freshness.timestamp(expiries.get(symbol)),
            paused,
            current_decision,
            target,
            current,
            now,
            entry,
        )

        deadlines = [
            desk_freshness.timestamp(v)
            for v in (expiries.get(symbol), quote.get("valid_until"))
            if desk_freshness.timestamp(v)
        ]
        result[symbol] = {
            "opportunity": opportunity.explain(
                (record.get("grades") or {}).get(symbol, {}),
                readings.get(symbol),
                (snapshot.get("quotes") or {}).get(symbol, {}),
                expiries.get(symbol),
                now,
                record["session"],
            ),
            "action": action,
            "reason": reason,
            # How much of the account to move, as a weight. The desk reasons
            # in weights and the board shows them; a share count would need
            # the operator's account value, which is a number the page should
            # not have to ask him for.
            "move_weight": move,
            "target_weight": target,
            "current_weight": current,
            "delta_weight": target - current,
            "valid_until": min(deadlines).isoformat() if deadlines else None,
            "quote": quote,
            "session": record["session"],
        }
    return {
        "version": VERSION,
        "as_of": now.isoformat(),
        "session": record["session"],
        "written": record.get("written"),
        "equity": equity,
        "holdings": {h.ticker: h.shares for h in held},
        "policy": "Experimental targets; adopted gates; manual execution"
        if targets is not None
        else "Scheduled next-open strategy; personal execution is manual",
        "rows": result,
    }
