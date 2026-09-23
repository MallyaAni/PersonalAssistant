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


# Reject cash values that cannot bound a personal recommendation basket.
def _validate_cash(cash, equity):
    """Raise ValueError for a nonfinite, negative or oversized personal cash figure."""
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("A finite nonnegative personal cash balance is required")
    if cash > equity:
        raise ValueError("Personal cash cannot exceed account equity")


# Fund eligible personal entries from explicit cash without borrowing paper state.
def apply_personal_account_plan(
    result, held, equity, cash, snapshot, entries, paused, now, record
):
    """Apply the desk's mid-cycle plan against the person's own account."""
    if cash is not None:
        _validate_cash(cash, equity)
    if paused or not math.isfinite(equity) or equity <= 0:
        return
    prices = _account_prices(held, snapshot, record)
    quotes = (snapshot or {}).get("quotes") or {}
    levels = record.get("levels") or {}
    for symbol in result:
        if symbol in prices:
            continue
        raw = (
            (quotes.get(symbol) or {}).get("last")
            or (levels.get(symbol) or {}).get("last_close")
            or 0
        )
        try:
            prices[symbol] = float(raw)
        except (TypeError, ValueError):
            prices[symbol] = 0.0
    shares = {holding.ticker: holding.shares for holding in held}
    if cash is None:
        return
    if any(not math.isfinite(q) or q < 0 for q in shares.values()) or any(
        q and (not math.isfinite(prices[s]) or prices[s] <= 0)
        for s, q in shares.items()
    ):
        for row in result.values():
            row["action"] = Action.HOLD
            row["move_weight"] = 0.0
            row["executable"] = False
            row["blocker"] = "personal account cannot be valued"
            row["reason"] = _not_executable_reason(
                row["strategy_action"], row["strategy_move_weight"], row["blocker"]
            )
        return
    from backend.agents.trading.desk import paper

    grades = {s: r.get("grade", "") for s, r in (record.get("grades") or {}).items()}
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    grades.update(
        {
            s: r["grade_live"]
            for s, r in holdings.live_grades(record, technical, value).items()
        }
    )
    # Only a name the desk actually covers and has turned against is an exit.
    # A name without coverage has no grade behind a sale - it is a Hold for
    # review, never a liquidation - and a name whose evidence is unusable
    # cannot be traded right now either.
    finished = {
        s: "grade below A; close position"
        for s in shares
        if s in grades
        and grades[s] not in paper.ENTRY_MIN_GRADE
        and result.get(s, {}).get("executable")
    }
    blocked = {s for s, level in levels.items() if level.get("rejecting_band")}
    # A buy needs its own fresh, eligible entry signal before it can consume
    # any cash: a stale decision, an unusable quote, an expired reading, a
    # blocked name or a downgrade are all filtered here, so a blocked name
    # consumes no budget and the remaining candidates share the account-wide
    # cash bound one way.
    eligible_entries = {
        s: b
        for s, b in (entries or {}).items()
        if grades.get(s) in paper.ENTRY_MIN_GRADE
        and s not in finished
        and s not in blocked
        and result.get(s, {}).get("executable")
    }
    orders = _personal_midcycle_orders(
        equity, shares, prices, finished, eligible_entries, cash
    )
    _fold_personal_orders(result, orders, prices, equity, shares)
    _enforce_personal_readiness(result)


# Enforce readiness AFTER the basket is folded, so no funded path can bypass
# it. A row that is not executable - however its basket was folded - is an
# actionable Hold, never a claim that can be traded now. And an executable Buy
# that the cash-bound planner did not fund (no room under the name cap, or a
# price it could not value) must not keep a fresh "add this much" claim.
def _enforce_personal_readiness(result):
    """Force every non-executable row to an actionable Hold and unfunded buys off."""
    for row in result.values():
        if not row.get("executable"):
            row["action"] = Action.HOLD
            row["move_weight"] = 0.0
            continue
        if row["strategy_action"] is Action.BUY and row["action"] is not Action.BUY:
            row["action"] = Action.HOLD
            row["move_weight"] = 0.0
            if "not executable" not in row["reason"]:
                row["reason"] = f"{row['reason']} (not funded from available cash)"


# The reason for a row whose strategy opinion could not be executed, keeping
# the desk's intent visible while saying plainly that nothing can be traded on
# it right now. Used both when the evidence is unusable and when the funding
# behind a buy is unknown or absent, so the blocker is never hidden in the
# reason text alone - it is also reflected in `action` and `executable`.
def _not_executable_reason(strategy_action, strategy_move_weight, blocker):
    """Return the reason an actionable Hold cannot be executed right now."""
    why = blocker or "evidence unusable"
    if strategy_action is Action.BUY:
        return (
            f"Wants up to {strategy_move_weight:.1%} of the account "
            f"(not executable: {why})"
        )
    if strategy_action is Action.SELL:
        return f"Wants to close the position (not executable: {why})"
    return f"Held (not executable: {why})"


# Size the person's own mid-cycle basket. A covered downgrade is an explicit
# exit; a graded breakout is a buy bounded by the person's available cash
# alone. It deliberately does NOT recycle a downgrade into a buy of another
# holding - that is the paper book's rotation, a rule for an account that
# carries its own positions, and applying it here would turn the person's
# board into entry guidance driven by someone else's sale. Every buy candidate
# was already filtered for fresh evidence before this runs, so nothing here can
# fund a stale read, and the buys share one account-wide cash bound rather than
# each sizing alone.
def _personal_midcycle_orders(equity, shares, prices, finished, entries, cash):
    """Return the person's mid-cycle orders: covered exits and cash-bounded entries."""
    from backend.agents.trading.desk import paper

    orders: list[paper.PaperOrder] = []
    for symbol in sorted(finished):
        qty = shares.get(symbol, 0.0)
        price = prices.get(symbol) or 0.0
        if qty > 0 and price > 0:
            orders.append(paper.PaperOrder(symbol, "sell", qty, finished[symbol]))
    buys: list[tuple[str, float, float]] = []
    for symbol in sorted(entries):
        price = prices.get(symbol) or 0.0
        if not math.isfinite(price) or price <= 0:
            continue
        band = float(entries[symbol] or 0.0)
        current = shares.get(symbol, 0.0) * price / equity
        want = min(paper.entry_size(band), paper.ENTRY_NAME_CAP - current)
        if want < paper.MIN_TRADE:
            continue
        buys.append((symbol, want * equity / price, want * equity))
    if buys:
        total = sum(value for _, _, value in buys)
        scale = min(1.0, max(0.0, cash) / total) if total else 1.0
        for symbol, qty, _ in buys:
            scaled = qty * scale
            if scaled <= 0:
                continue
            orders.append(
                paper.PaperOrder(
                    symbol,
                    "buy",
                    scaled,
                    "price entry: breakout through its own 20-day band",
                )
            )
    return orders


# Write one person's mid-cycle order basket onto the decision rows, so the
# displayed moves share the same caps and cash rather than each row sizing
# alone. A buy absent from the funded basket becomes Hold, with its strategy
# intent preserved separately. Existing evidence blockers remain intact.
def _fold_personal_orders(result, orders, prices, equity, shares):
    """Fold the person's mid-cycle orders into the decision rows."""
    moves: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for order in orders:
        sign = 1 if order.side == "buy" else -1
        moves[order.symbol] = moves.get(order.symbol, 0.0) + order.qty * sign
        reasons[order.symbol] = order.reason
    for symbol, row in result.items():
        row["current_weight"] = (
            shares.get(symbol, 0.0) * prices.get(symbol, 0.0) / equity
        )
        row["delta_weight"] = row["target_weight"] - row["current_weight"]
        if symbol not in moves:
            if row["strategy_action"] is Action.BUY and row["executable"]:
                row["action"] = Action.HOLD
                row["move_weight"] = 0.0
                row["executable"] = False
                row["blocker"] = "no funded entry under account limits"
                row["reason"] = _not_executable_reason(
                    row["strategy_action"], row["strategy_move_weight"], row["blocker"]
                )
            continue
        qty = moves[symbol]
        row["action"] = (
            Action.BUY if qty > 0 else Action.SELL if qty < 0 else Action.HOLD
        )
        row["move_weight"] = qty * prices.get(symbol, 0.0) / equity
        row["reason"] = (
            f"{reasons[symbol]}; sized against your holdings and dated prices"
        )


# What the person holds in a name, as a weight of the person's own equity.
#
# The board against the person's account is a statement about that account:
# each row's current weight must move when the person's holdings move and
# must not move when the desk's paper book changes. This used to read the
# desk's own book off `record["paper"]` instead, which made the personal
# column a function of an account it is not about - with a paper book that
# held a name the person did not, the board showed a position he did not own,
# and every paper fill silently changed his guidance. A missing or
# nonsensical equity yields no weights rather than a division by zero, and a
# name the person does not hold is absent rather than zero-valued, so callers
# can tell "flat" from "unknown".
def personal_weights(held, prices: dict[str, float], equity: float) -> dict[str, float]:
    """Return {ticker: weight of the person's equity} from their own holdings."""
    if not math.isfinite(equity) or equity <= 0:
        return {}
    out: dict[str, float] = {}
    for holding in held:
        price = prices.get(holding.ticker) or 0.0
        value = holding.shares * price
        if holding.ticker and math.isfinite(value) and price > 0:
            out[holding.ticker] = value / equity
    return out


# The person's own prices for the names they hold: the live quote where there
# is one, else the recorded level's close, else the price they paid. A name
# with no usable price is priced at zero, which is "cannot value", not "worth
# nothing", so the callers treat a zero-priced holding as an invalid account.
def _account_prices(held, snapshot, record) -> dict[str, float]:
    """Return {ticker: price} for the supplied personal holdings."""
    quotes = (snapshot or {}).get("quotes") or {}
    levels = record.get("levels") or {}
    prices: dict[str, float] = {}
    for holding in held:
        raw = (
            (quotes.get(holding.ticker) or {}).get("last")
            or (levels.get(holding.ticker) or {}).get("last_close")
            or holding.entry_price
        )
        try:
            prices[holding.ticker] = float(raw)
        except (TypeError, ValueError):
            prices[holding.ticker] = 0.0
    return prices


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


# Whether a row can be acted on right now, as opposed to what the desk wants
# done with the name. A paused book, a stale nightly decision, an unusable
# quote and an expired grade reading each leave nothing to execute; the reset
# clock does not - a mid-cycle entry needs no rebalance date. Shared by
# `action_for_row` (which rewrites a Buy entry's claim when it is not
# executable) and by `build` (which reports the same answer as a field on the
# row, so opinion and readiness stay distinct for the caller).
def _execution_readiness(paused, current_decision, quote, deadline, now):
    """Return (executable, blocker): whether the row can be traded right now."""
    blocker = next(
        (
            message
            for blocked, message in (
                (paused, "FOMC hold"),
                (not current_decision, "last night's decision is stale"),
                (not quote.get("eligible"), str(quote.get("reason") or "").lower()),
                (not deadline or deadline <= now, "no current price reading"),
            )
            if blocked
        ),
        None,
    )
    return blocker is None, blocker


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
    # The reset clock is deliberately not here: whether the paper book's next
    # rebalance is due is another account's schedule, and a personal board must
    # not read it. A mid-cycle entry needs no rebalance date either.
    advisory = next(
        (
            message
            for blocked, message in (
                (not current_decision, "last night's decision is stale"),
                (not quote["eligible"], str(quote["reason"]).lower()),
                (not deadline or deadline <= now, "no current price reading"),
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
        # A Buy from a live entry is the desk's OPINION about the name. Whether
        # it can be executed right now is a separate question, answered by the
        # evidence: a stale decision, an unusable quote or an expired reading
        # leave nothing to act on. When the evidence is missing, the row must
        # not present a fresh "add this much" claim as executable - it says the
        # desk wants the position and that this cannot be done yet. The reset
        # clock is deliberately not part of executability: a mid-cycle entry
        # needs no rebalance date.
        executable, blocker = _execution_readiness(
            paused, current_decision, quote, deadline, now
        )
        if action is Action.BUY and not executable:
            return (
                action,
                size or 0.0,
                f"Wants up to {size:.1%} of the account (not executable: {blocker})",
            )
        return said(action, size or 0.0, why)
    # Preserve the incumbent covered-downgrade exit opinion. A personal sale
    # does not imply a replacement buy or make its future proceeds available.
    if current > 0 and row["grade_live"] not in ("A", "A+"):
        return said(
            Action.SELL,
            -current,
            # The whole position, not a trim. The percentage beside a Sell is
            # how big the position IS, while the one beside a Buy is how much
            # to ADD - the same-looking number means two different things, and
            # a row that does not say which invites selling 7.8% of an account
            # instead of closing a 7.8% holding.
            f"Sell all of it: graded {row['grade_live']}",
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
    # So a Hold says what the account being guided is holding rather than only
    # that nothing is due. That is what the column owes a reader who records no
    # positions of his own: the board still shows him the strategy's book.
    if current > 0:
        return said(Action.HOLD, 0.0, f"Held at {current:.1%}; the thesis is intact")
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
    # Apply the shared cap to the actual account supplied by the caller.
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


# Reading a Buy recommendation is not execution. Suppress another
# same-session Buy only after a recorded fill or a working broker order.
def _entries_taken(held, now, pending, personal) -> dict[str, str]:
    """Return reasons for names with a filled or working buy this session."""
    if not personal:
        # Only the personal board is re-read within a session; the research
        # path is one dated projection and keeps every signal it is given.
        return {}
    session_date = now.astimezone(desk_freshness.NEW_YORK).date().isoformat()
    taken: dict[str, str] = {}
    once = "one entry per name per session"
    for holding in held:
        if holding.last_buy_date == session_date or holding.entry_date == session_date:
            taken[holding.ticker] = (
                f"Bought this session per your recorded fill; {once}"
            )
    for ticker in pending or ():
        taken[ticker] = f"A buy order is already working; {once}"
    return taken


# A breakout that would be a Buy is a Hold once its increment for the session
# has been filled or is working. The signal is still firing, and the
# row says why it is not being sized again.
def _unless_taken(entry, symbol, taken):
    """Return `entry`, or a Hold carrying the reason when the name is taken."""
    if entry is not None and entry[0] is Action.BUY and symbol in taken:
        return (Action.HOLD, None, taken[symbol])
    return entry


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
    cash=None,
    pending=None,
):
    now = now or datetime.now(UTC)
    # A personal cash figure that cannot bound a plan is a caller error, not a
    # reason to fall back to the per-row opinions (which would silently claim
    # unbounded buys). The explicit-targets research path never reads cash, so
    # this gate applies only to the personal board.
    if targets is None and cash is not None:
        _validate_cash(cash, equity)
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
    prices = _account_prices(held, snapshot, record)
    # The person's own weight in each name, from their supplied holdings at the
    # supplied equity - never from the desk's paper book. Personal guidance has
    # to move when the person's holdings move and must not move when the paper
    # account changes, so the paper account is not a source here.
    book = personal_weights(held, prices, equity)
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
    # Names whose entry increment this session is already spoken for, and the
    # signals the cash-bounded plan may still fund: a taken name is not a
    # candidate, or the funded basket would fold the Buy straight back in.
    taken = _entries_taken(held, now, pending, targets is None)
    open_entries = {s: b for s, b in (entries or {}).items() if s not in taken}
    # The person's universe: what the desk grades, plus anything the person
    # actually holds. A name the person holds but the desk does not cover gets
    # a row that says so, because the exit question is the person's own.
    for symbol in sorted(set(record.get("grades") or {}) | set(book)):
        row = rows.get(symbol)
        quote = execution_quotes.describe(
            (quoted.get("quotes") or {}).get(symbol, {}),
            quoted.get("feed"),
            quoted.get("market_open", False),
            now,
        )
        target = row["target_weight"] if row else 0.0
        # The person's own weight in the name, from their supplied holdings at
        # the supplied equity. The desk's book is a separate account and must
        # not shape what this person is told they currently hold.
        current = book.get(symbol, 0.0)
        entry = _unless_taken(
            entry_action(
                row,
                (entries or {}).get(symbol),
                (readings.get(symbol) or {}).get("grade")
                or (record.get("grades") or {}).get(symbol, {}).get("grade"),
                current,
            ),
            symbol,
            taken,
        )
        deadline = desk_freshness.timestamp(expiries.get(symbol))
        action, move, reason = action_for_row(
            row,
            quote,
            deadline,
            paused,
            current_decision,
            target,
            current,
            now,
            entry,
        )
        # Whether the row can be acted on right now, distinct from what the
        # desk wants done. Opinion and readiness are two questions, and the
        # row answers both: `strategy_action`/`strategy_move_weight` say what
        # the desk wants, `action`/`move_weight` say what can actually be
        # done, and `executable` says whether the evidence and the funding
        # support doing it now.
        executable, blocker = _execution_readiness(
            paused, current_decision, quote, deadline, now
        )
        # Investment intent is preserved as data for a future reviewed UI.
        strategy_action = action
        strategy_move_weight = move
        # For a personal buy, unknown cash is not demonstrated funding and a
        # zero cash bound leaves nothing to fund a buy: either way the opinion
        # stands (a strategy Buy) but nothing is claimed executable.
        if (
            targets is None
            and strategy_action is Action.BUY
            and (cash is None or cash == 0)
        ):
            if cash is None:
                blocker = blocker or "available cash is unknown"
            else:
                blocker = blocker or "no available cash"
            executable = False
        # On unusable evidence the actionable answer is always Hold with the
        # blocker named; the desk's opinion is not hidden, it is preserved in
        # the strategy fields above.
        if not executable:
            if strategy_action is Action.BUY or strategy_action is Action.SELL:
                reason = _not_executable_reason(
                    strategy_action, strategy_move_weight, blocker
                )
            action = Action.HOLD
            move = 0.0

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
            # The desk's investment intent, kept distinct from what can be
            # acted on now: existing consumers read `action`/`move_weight`
            # and do not know `executable`, so the opinion lives here and the
            # actionable recommendation in the fields above.
            "strategy_action": strategy_action,
            "strategy_move_weight": strategy_move_weight,
            # What stands in the way of executing right now, or None when
            # nothing does; the same value that shapes `action`, `executable`
            # and the reason text.
            "blocker": blocker,
            "target_weight": target,
            # The person's own position and the distance from it to the desk's
            # target. Both come from the supplied holdings and equity, so they
            # say what THIS person holds, not what the paper book holds.
            "current_weight": current,
            "delta_weight": target - current,
            "valid_until": min(deadlines).isoformat() if deadlines else None,
            "quote": quote,
            "session": record["session"],
            "executable": executable,
        }
    if targets is None:
        apply_personal_account_plan(
            result, held, equity, cash, snapshot, open_entries, paused, now, record
        )
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
