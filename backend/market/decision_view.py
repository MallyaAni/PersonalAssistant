"""Present the adopted plan's eligibility without promoting research allocations."""

import math
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np

from backend.market import (
    allocation_view,
    calendar,
    desk_freshness,
    execution_quotes,
    holdings,
    opportunity,
)

VERSION = "desk-decision-view/1"


# Project one account-wide paper plan so all displayed moves share caps and cash.
def apply_account_plan(result, record, snapshot, entries, paused, now):
    from backend.agents.trading.desk import paper

    account = record.get("paper") or {}
    if paused or not account or account.get("cash") is None:
        return
    positions = account.get("positions") or []
    quotes = snapshot.get("quotes") or {}
    levels = record.get("levels") or {}
    prices = {
        s: float(
            (quotes.get(s) or {}).get("last")
            or (levels.get(s) or {}).get("last_close")
            or 0
        )
        for s in result
    }
    held = {}
    for position in positions:
        symbol = position["symbol"]
        held[symbol] = float(position.get("qty") or 0)
        prices[symbol] = prices.get(symbol) or float(position.get("current_price") or 0)
    cash = float(account["cash"])
    if not math.isfinite(cash) or any(
        not math.isfinite(q) or q < 0 for q in held.values()
    ):
        return
    if any(
        q and (not math.isfinite(prices[s]) or prices[s] <= 0) for s, q in held.items()
    ):
        return
    equity = cash + sum(q * prices[s] for s, q in held.items())
    if equity <= 0:
        return
    grades = {s: r.get("grade", "") for s, r in (record.get("grades") or {}).items()}
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    grades.update(
        {
            s: r["grade_live"]
            for s, r in holdings.live_grades(record, technical, value).items()
        }
    )
    finished = {
        s: "grade below A; close position"
        for s in held
        if s in grades and grades[s] not in paper.ENTRY_MIN_GRADE
    }
    blocked = {s for s, level in levels.items() if level.get("rejecting_band")}
    remaining = account.get("until_rebalance")
    state = paper.PaperState(
        last_rebalance=record["session"],
        sessions_since_rebalance=(
            paper.REBALANCE_EVERY - int(remaining) if remaining is not None else 0
        ),
    )
    orders, _, _ = paper.plan(
        record["session"],
        state,
        equity,
        held,
        prices,
        {r["ticker"]: r["weight"] for r in record.get("book") or []},
        grades,
        finished=finished,
        entry_blocked=blocked,
        entries=entries or {},
        cash=max(0, cash),
    )
    moves = {}
    for order in orders:
        moves[order.symbol] = moves.get(order.symbol, 0) + order.qty * (
            1 if order.side == "buy" else -1
        )
    reasons = {o.symbol: o.reason for o in orders}
    for symbol, row in result.items():
        qty = moves.get(symbol, 0)
        row["action"] = (
            Action.BUY if qty > 0 else Action.SELL if qty < 0 else Action.HOLD
        )
        row["move_weight"] = qty * prices.get(symbol, 0) / equity
        row["current_weight"] = held.get(symbol, 0) * prices.get(symbol, 0) / equity
        row["delta_weight"] = row["target_weight"] - row["current_weight"]
        row["reason"] = reasons.get(
            symbol, "No funded strategy order; retain current position"
        )
        row["reason"] += "; preview from recorded account and dated prices"


# What the desk itself holds in a name, as a weight of the desk's own equity.
#
# Every action on this board is the desk's, so the only position any of them
# involves is the desk's. The board used to read the operator's recorded
# holdings instead, which made the whole column a function of bookkeeping he
# does not always do: with nothing recorded the page said Hold ninety-three
# times while the book held nine names, and with a stale file it said Sell on
# a name he no longer owned. The nightly never consults that file either -
# `market_daily` rotates on `client.positions()`, the paper account - so
# reading it here made the page a second, wrong answer to a question the book
# had already answered.
#
# The record carries the account under `paper`. A missing or nonsensical
# equity yields no weights rather than a division by zero, and a name the desk
# does not hold is absent rather than zero-valued, so callers can tell "flat"
# from "unknown".
def book_weights(record) -> dict[str, float]:
    """Return {ticker: weight of the desk's equity} for the desk's own book."""
    account = record.get("paper") or {}
    try:
        equity = float(account.get("equity"))
    except (TypeError, ValueError):
        return {}
    if not math.isfinite(equity) or equity <= 0:
        return {}
    out: dict[str, float] = {}
    for position in account.get("positions") or []:
        ticker = position.get("symbol")
        try:
            value = float(position.get("market_value"))
        except (TypeError, ValueError):
            continue
        if ticker and math.isfinite(value):
            out[ticker] = value / equity
    return out


# The three things the operator can do about a name. A fixed set, so it is a
# type rather than a string literal repeated at a dozen call sites: the old
# vocabulary had seven spellings across the backend, the API contract and the
# page, and "Buy eligible" against "Buy tonight" against "buy" was a bug
# waiting to happen. The str mixin keeps it a plain string over the wire.
class Action(StrEnum):
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
    # Two different questions, and they used to be one.
    #
    # "What does the desk want done with this name" is answered by the record:
    # the grade, the target weight, the reset clock. "Can it be traded right
    # now" is answered by the quote. Every gate below used to force a Hold, so
    # a closed market turned all ninety-three rows into Hold whatever the desk
    # thought - and a closed market is most of the time the operator reads
    # this page. The quote being unusable is a fact ABOUT the execution, not a
    # view about the name.
    #
    # So only what genuinely leaves nothing to decide still blocks: an FOMC
    # pause really is a hold, a name with no row has no position and no target,
    # and a name outside coverage has no opinion behind it. Everything else
    # annotates: the action stands and the reason says what is in the way.
    blocking = (
        (paused, "FOMC hold"),
        (not row, "Not in the book"),
        (row and not row["in_book"], "Not covered by the desk"),
    )
    reason = next((message for blocked, message in blocking if blocked), None)
    if reason:
        return Action.HOLD, 0.0, reason
    advisory = next(
        (
            message
            for blocked, message in (
                (not current_decision, "last night's decision is stale"),
                (not quote["eligible"], str(quote["reason"]).lower()),
                (not deadline or deadline <= now, "no current price reading"),
                (row["until_rebalance"] is None, "reset timing unknown"),
            )
            if blocked
        ),
        None,
    )

    # The live entry comes first. It is the one thing on this page that is
    # actionable between resets, and the calendar branch below would otherwise
    # bury it under an answer about a date six months out.
    def said(action, move, why):
        """Return the action with whatever is standing in its way appended."""
        return action, move, f"{why} ({advisory})" if advisory else why

    if entry is not None:
        action, size, why = entry
        return said(action, size or 0.0, why)
    # A name the desk no longer grades A is sold, and the money goes into the
    # names it still wants. This was removed earlier on the evidence that a
    # downgrade is followed by outperformance rather than a fall - which is
    # true, and is why selling one to CASH costs 24 points of CAGR a year. It
    # is not an argument for holding it: rotated into the rest of the book the
    # same signal earned the same return as holding with a 7.3 point shallower
    # drawdown and a better Sharpe. The desk is not leaving the market, it is
    # moving money to a better name, so the row says Sell and the book buys
    # elsewhere the same session. `desk/exit.py` carries the table.
    if current > 0 and row["grade_live"] not in ("A", "A+"):
        return said(
            Action.SELL,
            -current,
            # The whole position, not a trim. The percentage beside a Sell is
            # how big the position IS, while the one beside a Buy is how much
            # to ADD - the same-looking number means two different things, and
            # a row that does not say which invites selling 7.8% of an account
            # instead of closing a 7.8% holding.
            f"Sell all of it: graded {row['grade_live']}, and the desk rotates "
            f"the money into the names it still wants",
        )

    # Everything else is a Hold, and the reason says which kind.
    #
    # There was briefly a fourth branch here that compared the position to the
    # target weight and called the difference a Buy or a Sell. It is deleted,
    # because the targets are a fresh sizing computed every night, not a
    # standing order: on the live record the book holds 43% of its equity
    # against targets summing to 22%, so reading the difference as an
    # instruction printed Sell on eight names the desk has no intention of
    # selling. The book only acts on those weights at a reset, and no backtest
    # supports trading toward them in between - the two rules above are the
    # ones that were measured.
    #
    # So a Hold says what the desk is holding rather than only that nothing is
    # due. That is what the column owes a reader who records no positions of
    # his own: the board still shows him the book.
    if current > 0:
        return said(
            Action.HOLD, 0.0, f"The desk holds {current:.1%}; the thesis is intact"
        )
    if target > 0:
        return said(
            Action.HOLD,
            0.0,
            f"Wanted at {target:.0%} at the next reset; no entry signal today",
        )
    return said(
        Action.HOLD,
        0.0,
        f"Graded {row['grade_live']}; the desk wants no position today",
    )


# The book's mid-cycle entry, decided at the live price rather than at the
# close, so the row says what the desk will do tonight instead of what the
# calendar says months from now. The threshold, the grade floor and the name
# cap are read from `paper` rather than restated, because a copy of a trading
# rule in the presentation layer is a copy that drifts.
def entry_action(row, band, grade_live, current=0.0):
    """Return (action, size, reason) when the entry fires now, else None.

    Said in the present tense, and sized. The first version of this answered
    "when does the paper book act", so a name reading 18% above its 21-day at
    eleven in the morning said "Buy tonight" - which describes the desk's cron
    job, not the decision in front of the operator. He is looking at a live
    price and has to size a position against it now. The signal is firing at
    that price, so the row says Buy, and says how much.

    `size` is the weight to put on at this moment, not the eventual target:
    what `paper.entry_size` asks for at this band reading, trimmed to the room
    left under ENTRY_NAME_CAP - the increment the nightly would size and the
    one the operator can act on. It is no longer a flat number: a close
    further through its band is a stronger reading at that price and earns a
    larger position. The target it moves toward is already its own column.
    """
    from backend.agents.trading.desk import paper

    if band is None or not math.isfinite(band) or band < paper.ENTRY_BAND_Z:
        return None
    if grade_live not in paper.ENTRY_MIN_GRADE:
        return None
    # Mid-cycle eligibility follows the grade, independently of reset targets.
    if not row:
        return None
    # The same gate the nightly applies before it sizes anything.
    if row.get("rejecting_band"):
        # Hold, not "Wait". The enum exists because seven spellings of the
        # action had drifted across the backend and the page, and this one
        # survived behind a branch nothing reached: the board passed no live
        # readings, so no entry was ever evaluated. It reaches the column now.
        return (
            Action.HOLD,
            None,
            "Breaking out, but the daily is rejecting its upper band",
        )
    above = f"{band:.1f} on its 20-day band"
    # The cap the nightly checks is the cap on the DESK's own position, so the
    # room left under it is measured against the desk's weight. Measuring it
    # against the operator's recorded holdings made the size an artefact of
    # his bookkeeping: an unrecorded position showed a full 15% of room on a
    # name the book was already capped out of.
    held = current > 0
    room = paper.ENTRY_NAME_CAP - current
    if held and room <= 0:
        return (
            Action.HOLD,
            None,
            f"{above}, already at the {paper.ENTRY_NAME_CAP:.0%} name cap",
        )
    # The same function the book sizes with, not a copy of its constant. The
    # size now follows how far through the band the close is, so a board that
    # reached for ENTRY_ADD directly would quote a number the nightly would
    # not trade - which is how the action vocabulary drifted four times.
    size = min(paper.entry_size(band), room)
    if size <= 0:
        return (
            Action.HOLD,
            None,
            f"{above}, no room under the {paper.ENTRY_NAME_CAP:.0%} name cap",
        )
    return (
        Action.BUY,
        size,
        f"Add up to {size:.1%} of the account: {above}, subject to available cash",
    )


# Combine existing strategy gates and quote evidence into one dated, reviewable row.
def build(
    record,
    held,
    equity,
    snapshot,
    quoted,
    now=None,
    targets=None,
    entries=None,
    *,
    expected_account=None,
):
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
    book = book_weights(record)
    # `holdings.board` speaks for a name that is targeted or held, which on the
    # live record is twelve of ninety-three. The other eighty-one graded names
    # arrived here with no row at all and the column called them "Not in the
    # book" - which is false, and was most of what the operator saw. The desk
    # grades them; it has simply sized them at zero today.
    #
    # Padding the book with that explicit zero gives every covered name a row
    # to speak for it. It is done on a copy for this call only: `board` also
    # feeds the positions view and the funding preview, where eighty-one empty
    # rows would be noise in one and a changed denominator in the other.
    listed = {row["ticker"] for row in (record.get("book") or [])}
    covered = {
        **record,
        "book": [
            *(record.get("book") or []),
            *(
                {"ticker": ticker, "weight": 0.0}
                for ticker in sorted(record.get("grades") or {})
                if ticker not in listed
            ),
        ],
    }
    rows = {
        r["ticker"]: r
        for r in holdings.board(
            covered, held, equity, snapshot.get("quotes") or {}, technical, value
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
    # The desk's universe: what it grades, plus anything it still holds. Which
    # names appear must not depend on the operator's file either - a holding in
    # something uncovered used to add a row that said "Not covered by the
    # desk", so the length of the board moved with his bookkeeping. His own
    # positions are reported by the positions view, which is where a name the
    # desk has no view on belongs.
    for symbol in sorted(set(record.get("grades") or {}) | set(book)):
        row = rows.get(symbol)
        quote = execution_quotes.describe(
            (quoted.get("quotes") or {}).get(symbol, {}),
            quoted.get("feed"),
            quoted.get("market_open", False),
            now,
        )
        target = row["target_weight"] if row else 0.0
        # The desk's own weight, not the operator's. The midpoint recompute
        # that used to stand here scaled his recorded share count by his
        # account value, which is the one number on this page the desk has no
        # opinion about.
        current = book.get(symbol, 0.0)
        entry = entry_action(
            row,
            (entries or {}).get(symbol),
            (readings.get(symbol) or {}).get("grade")
            or (record.get("grades") or {}).get(symbol, {}).get("grade"),
            current,
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
            # The desk's position and the distance from it to the desk's own
            # target. Both are the book's numbers; neither depends on what the
            # operator has recorded, which is what keeps the column saying the
            # same thing whether or not he keeps his holdings file current.
            "current_weight": current,
            "delta_weight": target - current,
            "valid_until": min(deadlines).isoformat() if deadlines else None,
            "quote": quote,
            "session": record["session"],
        }
    if targets is None:
        apply_account_plan(result, record, snapshot, entries, paused, now)
    return {
        "version": VERSION,
        "as_of": now.isoformat(),
        "session": record["session"],
        "written": record.get("written"),
        "equity": equity,
        "holdings": {h.ticker: h.shares for h in held},
        "policy": (
            "Experimental targets; adopted gates; manual execution"
            if targets is not None
            else "Scheduled next-open strategy; personal execution is manual"
        ),
        # The optional funded-allocation metadata, shown as an explicit preview
        # and never as the adopted plan. The serializer reports an explicit
        # unavailable payload when the snapshot carries no allocation_plan, so
        # the field is always present and never a made-up allocation.
        "portfolio_allocation": allocation_view.serialize(
            (snapshot or {}).get("allocation_plan"),
            session=record.get("session"),
            expected_account=expected_account,
        ),
        "rows": result,
    }
