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
    personal_risk,
)

VERSION = "desk-decision-view/2"


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
    result,
    held,
    equity,
    cash,
    snapshot,
    entries,
    paused,
    now,
    record,
    *,
    target_buys=None,
    close_grades=False,
):
    """Apply the desk's mid-cycle plan against the person's own account.

    `target_buys` maps a name to (weight to add, sentence) for buys the board
    sized from the active policy's targets; they share the cash bound with
    the band entries, as the executor's redeploy leg shares it with its own.
    `close_grades` (the `/4` board) decides exits and eligibility on the
    record's close grades, as the executor does, instead of re-grading at the
    candle; False keeps the `/3` board exactly as it was.
    """
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
    if not close_grades:
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
    # A buy toward the policy's target passes the same filters as an entry,
    # except the band: the executor's redeploy leg has no band gate either.
    # A name can carry a band reading below the trigger AND a target buy -
    # on a session every name has a reading - so membership in `entries` is
    # not what excludes it; a firing entry already owns its row's Buy and
    # never appears in `target_buys`.
    eligible_targets = {
        s: want
        for s, want in (target_buys or {}).items()
        if grades.get(s) in paper.ENTRY_MIN_GRADE
        and s not in finished
        and result.get(s, {}).get("executable")
    }
    orders = _personal_midcycle_orders(
        equity,
        shares,
        prices,
        finished,
        eligible_entries,
        cash,
        max_add_weights={
            symbol: row["risk_plan"]["max_add_weight"]
            for symbol, row in result.items()
            if (row.get("risk_plan") or {}).get("risk_budget_pct") is not None
        },
        target_buys=eligible_targets,
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
# `said`, when given, is the sized target sentence the row would otherwise
# have carried ("Buy to 9.1% target ..."); it is kept in front of the blocker
# so a board read with the market shut still says where the policy wants the
# name. Rows without it (every `/3`-era record) read exactly as before.
def _not_executable_reason(strategy_action, strategy_move_weight, blocker, said=None):
    """Return the reason an actionable Hold cannot be executed right now."""
    why = blocker or "evidence unusable"
    if strategy_action is Action.BUY:
        why = f"Buy not executable: {why}"
    elif strategy_action is Action.SELL:
        why = f"Exit not executable: {why}"
    else:
        why = f"Not executable: {why}"
    return f"{said}; {why[0].lower()}{why[1:]}" if said else why


# Whether the record's targets are the active allocation policy's, so the
# board sizes toward them. `record["targets"]` is written by the nightly from
# `live_policy.record_targets`; a record from before the stamp, or one stamped
# with another policy, has no standing order behind its weights and keeps the
# `/3`-era rules (a live entry, a covered exit, otherwise Hold).
def _sizes_toward_targets(record) -> bool:
    """Return True when `record["targets"]` carries the active policy's weights."""
    from backend.agents.trading.desk import live_policy

    targets = record.get("targets") or {}
    weights = targets.get("weights")
    return (
        targets.get("policy") == live_policy.ACTIVE
        and isinstance(weights, dict)
        and bool(weights)
    )


# The book the board sizes against when the record carries the active
# policy's targets: every name the policy wants, at its weight. Identical to
# the API's swap (`market._with_active_targets`) so a caller that has already
# swapped sees no change, and a caller that has not cannot size a `/4` label
# against the `/3` book that stays on the record for reference.
def _targets_book(record) -> list[dict]:
    """Return `[{ticker, weight}]` from the record's targets, positive weights only."""
    weights = (record.get("targets") or {}).get("weights") or {}
    return [
        {"ticker": ticker, "weight": float(weight)}
        for ticker, weight in weights.items()
        if isinstance(weight, (int, float)) and math.isfinite(weight) and weight > 0
    ]


# The move from the person's weight to the active policy's target, classified
# exactly as `decision_history.classify` classifies the charts: entering is a
# Buy whatever the size, a shortfall of ADD_TRIM_MIN or more is an add (Buy,
# sized to the gap), an excess of that much is a trim - which the executor
# only takes at the reset, so mid-cycle it is a Hold that says so rather than
# a Sell the book will not place - and anything smaller is a Hold on the
# existing reasons (None here). The downgrade exit is decided before this is
# reached, so a held name the desk no longer rates never arrives.
def _target_move(row, target, current, policy):
    """Return (action, move, reason) toward `target`, or None for an ordinary Hold."""
    from backend.agents.trading.desk import decision_history

    minimum = decision_history.ADD_TRIM_MIN - 1e-9
    label = f"{target:.1%} target (policy {policy})"
    if target <= 0:
        return None
    if current <= 0:
        return Action.BUY, target, f"Buy to {label}"
    delta = target - current
    if delta >= minimum:
        return Action.BUY, delta, f"Add to {label}; holding {current:.1%}"
    if -delta >= minimum:
        # `rebalance_due` reads None as due (a record with no clock); a Sell
        # printed off a missing clock is the one thing this must never do.
        due = bool(row.get("rebalance_due")) and row.get("until_rebalance") is not None
        if due:
            return Action.SELL, delta, f"Trim to {label}; holding {current:.1%}"
        return (
            Action.HOLD,
            0.0,
            f"Above target ({target:.1%}; holding {current:.1%}); "
            "trimmed at the next reset",
        )
    return None


# Size the person's own mid-cycle basket. A covered downgrade is an explicit
# exit; a graded breakout is a buy bounded by the person's available cash
# alone. It deliberately does NOT recycle a downgrade into a buy of another
# holding - that is the paper book's rotation, a rule for an account that
# carries its own positions, and applying it here would turn the person's
# board into entry guidance driven by someone else's sale. Every buy candidate
# was already filtered for fresh evidence before this runs, so nothing here can
# fund a stale read, and the buys share one account-wide cash bound rather than
# each sizing alone.
def _personal_midcycle_orders(
    equity,
    shares,
    prices,
    finished,
    entries,
    cash,
    *,
    max_add_weights=None,
    target_buys=None,
):
    """Return the person's mid-cycle orders: covered exits and cash-bounded entries.

    `target_buys` ({symbol: (weight to add, reason)}) are the buys toward the
    active policy's targets; they are bounded by the target itself (the gap
    is the size), by a risk budget when one is set, and share the one cash
    bound with the band entries.
    """
    from backend.agents.trading.desk import paper

    orders: list[paper.PaperOrder] = []
    for symbol in sorted(finished):
        qty = shares.get(symbol, 0.0)
        price = prices.get(symbol) or 0.0
        if qty > 0 and price > 0:
            orders.append(paper.PaperOrder(symbol, "sell", qty, finished[symbol]))
    entry_reason = "price entry: breakout through its own 20-day band"
    buys: list[tuple[str, float, float, str]] = []
    for symbol in sorted(entries):
        price = prices.get(symbol) or 0.0
        if not math.isfinite(price) or price <= 0:
            continue
        band = float(entries[symbol] or 0.0)
        current = shares.get(symbol, 0.0) * price / equity
        want = min(paper.entry_size(band), paper.ENTRY_NAME_CAP - current)
        if max_add_weights is not None and symbol in max_add_weights:
            want = min(want, max_add_weights[symbol])
        if want < paper.MIN_TRADE:
            continue
        buys.append((symbol, want * equity / price, want * equity, entry_reason))
    buys += _target_buy_legs(target_buys or {}, prices, equity, max_add_weights)
    if buys:
        total = sum(value for _, _, value, _ in buys)
        scale = min(1.0, max(0.0, cash) / total) if total else 1.0
        for symbol, qty, _, reason in buys:
            scaled = qty * scale
            # Cash is shared before this final floor, so small residual balances
            # cannot create an actionable buy below the policy's minimum.
            if scaled <= 0 or scaled * prices[symbol] < paper.MIN_TRADE * equity:
                continue
            orders.append(paper.PaperOrder(symbol, "buy", scaled, reason))
    return orders


# The buy legs toward the active policy's targets, in the shape the cash
# bound shares out: (symbol, shares, dollars, reason). A name without a
# usable price cannot be sized, a risk budget caps the add when one is set,
# and a gap under MIN_TRADE is not an order - the same floors the entry legs
# apply. (A firing entry owns its row's Buy and is never in `target_buys`.)
def _target_buy_legs(target_buys, prices, equity, max_add_weights):
    """Return [(symbol, qty, value, reason)] for the target buys worth placing."""
    from backend.agents.trading.desk import paper

    legs: list[tuple[str, float, float, str]] = []
    for symbol in sorted(target_buys):
        price = prices.get(symbol) or 0.0
        if not math.isfinite(price) or price <= 0:
            continue
        want, reason = target_buys[symbol]
        want = float(want or 0.0)
        if max_add_weights is not None and symbol in max_add_weights:
            want = min(want, max_add_weights[symbol])
        if not math.isfinite(want) or want < paper.MIN_TRADE:
            continue
        legs.append((symbol, want * equity / price, want * equity, reason))
    return legs


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
                (not current_decision, "decision data is stale"),
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
    row,
    quote,
    deadline,
    paused,
    current_decision,
    target,
    current,
    now,
    entry=None,
    *,
    toward_targets=None,
):
    """Return (action, weight, reason): Buy, Sell or Hold, and the weight to move.

    `toward_targets` names the active policy when the record's targets are its
    standing order (`_sizes_toward_targets`); then the gap to the target is
    sized as `_target_move` says. None keeps the `/3`-era rules below.
    """
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
                (not current_decision, "decision data is stale"),
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
                f"Buy not executable: {blocker}",
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
            f"Exit position: grade {row['grade_live']}",
        )

    # Under the active policy the targets ARE the standing order. The
    # `graded-equal-weight/4` executor holds every A/A+ name at equal weight,
    # exits on a downgrade (the branch above) and, since the redeploy leg,
    # puts idle cash back to the targets mid-cycle; trimming waits for the
    # reset. So the gap between what the person holds and the policy's weight
    # is the trade, classified as the charts classify it.
    if toward_targets:
        sized = _target_move(row, target, current, toward_targets)
        if sized is not None:
            return said(*sized)

    # Everything else is a Hold, and the reason says which kind.
    #
    # For a record without the active policy's targets (every `/3`-era
    # record) there is deliberately no branch that compares the position to
    # the target weight: the `/3` targets were a fresh sizing computed every
    # night, not a standing order - on the live record the book held 43% of
    # its equity against targets summing to 22%, so reading the difference as
    # an instruction printed Sell on eight names the desk had no intention of
    # selling. That book only acted on its weights at a reset, and no backtest
    # supported trading toward them in between. The rule applies to `/3`
    # records only; `/4` records take the branch above.
    #
    # So a Hold says what the account being guided is holding rather than only
    # that nothing is due. That is what the column owes a reader who records no
    # positions of his own: the board still shows him the strategy's book.
    if current > 0:
        return said(Action.HOLD, 0.0, f"Maintain position ({current:.1%} of account)")
    if target > 0:
        return said(
            Action.HOLD,
            0.0,
            f"No entry signal; reset target {target:.0%}",
        )
    return said(
        Action.HOLD,
        0.0,
        "Entry criteria not met",
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
            "Entry blocked: daily upper band rejection",
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
        f"Breakout: {above}",
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


# Preserve entry-data failures separately from a valid observation without a signal.
def _entry_evidence(symbol, entries, readings):
    reading = (readings or {}).get(symbol) or {}
    available = (
        reading.get("band_z") is not None
        if readings is not None
        else (entries or {}).get(symbol) is not None
    )
    status = reading.get("entry_status") or (
        "available" if available else "unavailable"
    )
    return {
        "entry_status": status,
        "entry_reason": reading.get("entry_reason")
        or (
            "Entry data unavailable: no current reading"
            if status == "unavailable"
            else None
        ),
        "missing_sessions": reading.get("missing_sessions") or [],
    }


# Apply an explicit personal risk budget without altering the underlying signal.
def _apply_risk_budget(
    row, symbol, snapshot, current, fresh, deadline, now, budget, *, personal
):
    if not personal:
        return
    detail = ((snapshot.get("technical_detail") or {}).get(symbol) or {}).get(
        "short"
    ) or {}
    bar = (snapshot.get("quotes") or {}).get(symbol) or {}
    plan = personal_risk.build(
        entry_price=bar.get("last"),
        support_distance=detail.get("support_distance"),
        resistance_distance=detail.get("resistance_distance"),
        current_weight=current,
        policy_max_add_weight=max(0.0, row["strategy_move_weight"] or 0.0),
        observed_at=desk_freshness.timestamp(snapshot.get("as_of")),
        valid_until=desk_freshness.timestamp(deadline),
        now=now,
        fresh=fresh,
        risk_budget_pct=budget,
    )
    row["risk_plan"] = plan
    if (
        budget is not None
        and row["strategy_action"] is Action.BUY
        and (plan["status"] != "available" or plan["max_add_weight"] <= 0)
    ):
        row.update(
            action=Action.HOLD,
            move_weight=0.0,
            executable=False,
            blocker=row["blocker"] or plan["reason"],
            reason=_not_executable_reason(
                row["strategy_action"], row["strategy_move_weight"], plan["reason"]
            ),
        )


# Show missing entry evidence without overriding a valid exit or event pause.
def _apply_entry_reason(row, readings, paused):
    if (
        readings is not None
        and row["entry_status"] == "unavailable"
        and row["strategy_action"] is Action.HOLD
        and not paused
    ):
        row["reason"] = row["entry_reason"]


# Which policy the board sizes toward, and the record it sizes against. The
# personal board against a record stamped with the active policy sizes toward
# that policy's weights: the book becomes the targets (the API already swaps
# it; doing it here too means a caller that did not cannot size a `/4` label
# against the `/3` book), and `action_for_row` trades the gap. The
# explicit-targets research path (`targets` given) is a different question
# and keeps its own book, as does every record without the stamp.
def _toward_targets(record, targets):
    """Return (policy or None, record) for the board to size against."""
    if targets is not None or not _sizes_toward_targets(record):
        return None, record
    from backend.agents.trading.desk import live_policy

    return live_policy.ACTIVE, {**record, "book": _targets_book(record)}


# The target sentence a Buy sized from the policy's targets carries through
# every blocker, or None for any other row: a Buy from a firing band entry is
# the entry leg's and keeps its own wording, and a record without the active
# policy's targets never has one. `action_for_row` appended the blocker as an
# advisory; it is stripped here so the not-executable sentence names it once.
def _target_intent(toward_targets, strategy_action, entry, reason, blocker):
    """Return the target sentence of a target-sized Buy, else None."""
    if not toward_targets or strategy_action is not Action.BUY:
        return None
    if entry is not None and entry[0] is Action.BUY:
        return None
    return reason.removesuffix(f" ({blocker})") if blocker else reason


# The executor's structure gate for one name, read from the nightly record.
#
# The live executor holds back every buy-side order (reset buys, entries,
# rotation buys, deferred buys) for a name in `entry_blocked`, which
# `market_daily._band_blocked` fills from `exit.evidence(panel).signalled()`
# on the decision session - the same predicate `simulate.run(
# block_overbought=True)` reads: a bearish reversal candle with the close at
# or above 95% of its 20-day band, or the band in the top decile of its year
# with the close in its upper fifth. The nightly writes that very flag on
# every graded name as `levels[T]["rejecting_band"]` (and on the paper
# block's action rows), so the board reads the executor's verdict rather
# than re-deriving it. REJECTING / CLEAR, or UNRECORDED when the record
# carries no flag for the name (a record from before the stamp): that is
# treated as not blocked and said so, never guessed.
REJECTING = "rejecting"
CLEAR = "clear"
UNRECORDED = "unrecorded"
BAND_BLOCKER = "rejecting its upper band (executor's gate)"
BAND_BLOCK = f"Buy blocked: {BAND_BLOCKER}"


# Return REJECTING, CLEAR or UNRECORDED for `symbol` on `record`: the levels
# block first, then the action rows, as `holdings.board` merges them.
def _structure_gate(record, symbol) -> str:
    """Return the record's band-gate answer for `symbol`."""
    level = (record.get("levels") or {}).get(symbol)
    if isinstance(level, dict) and "rejecting_band" in level:
        return REJECTING if level["rejecting_band"] else CLEAR
    for row in record.get("actions") or []:
        if (
            isinstance(row, dict)
            and row.get("ticker") == symbol
            and "rejecting_band" in row
        ):
            return REJECTING if row["rejecting_band"] else CLEAR
    return UNRECORDED


# The board row the `/4` intent is decided from: the same row with its grade
# set to the record's close grade. The executor decides exits and eligibility
# on the nightly close grades and the measured timing rule prices orders
# decided at the close, so under the active policy the intent does not move
# with the intraday re-grade (which is kept, and shown, as `grade_intraday`).
def _at_the_close(row):
    """Return `row` with `grade_live` replaced by its close grade, or None."""
    return {**row, "grade_live": row.get("grade", "")} if row else row


# Which side of the timing rule a row's decision is on: its action when it
# is a Buy or a Sell, else its strategy intent; None when neither trades.
def _timed_side(row) -> str | None:
    """Return "buy", "sell" or None for the row."""
    said = row["action"] if row["action"] is not Action.HOLD else row["strategy_action"]
    if said is Action.BUY:
        return "buy"
    if said is Action.SELL:
        return "sell"
    return None


# The word the board prints for a timed row: a sell that keeps a positive
# target is a trim (the page's `actionWord` reads it the same way).
def _timed_word(row, side) -> str:
    """Return "Buy", "Sell" or "Trim"."""
    if side == "buy":
        return "Buy"
    return "Trim" if (row.get("target_weight") or 0) > 0 else "Sell"


# The measured level and the executor's band gate, applied to the `/4` board
# after the intent is sized and funded.
#
# The operator trades his own account from this board, so a BUY, SELL or
# TRIM must mean "act now". Each row keeps its intent (`strategy_action`,
# `strategy_move_weight`, read by the charts) and gets:
#   - `structure_gate`: the executor's band gate for the name; a Buy intent
#     on a REJECTING name is a Hold whatever else is true.
#   - `timing`: `entry_timing.timing` for its side - a Buy or Sell stands only
#     when triggered (a 15-minute close reached the level today) or in the
#     close window; otherwise it becomes a Hold of size 0 whose reason says
#     what is planned and at what price.
#   - `grade` (the record's close grade, the one the intent read) and
#     `grade_intraday` (the candle's re-grade, None without a fresh read).
# A row already Hold (stale evidence, an unusable quote, no cash, a pause)
# keeps its reason and blocker: the timing only ever holds a trade back,
# never creates one.
def _time_the_board(result, record, snapshot, readings, intents, latch, now):
    """Apply the level and the band gate to every `/4` row in place."""
    from backend.market import entry_timing

    session = now.astimezone(desk_freshness.NEW_YORK).date()
    quotes = (snapshot or {}).get("quotes") or {}
    grades = record.get("grades") or {}
    for symbol, row in result.items():
        gate = _structure_gate(record, symbol)
        row["structure_gate"] = gate
        row["grade"] = (grades.get(symbol) or {}).get("grade")
        row["grade_intraday"] = (readings.get(symbol) or {}).get("grade_live")
        side = _timed_side(row)
        if side is None:
            row["timing"] = None
            continue
        timed = entry_timing.timing(
            entry_timing.row_for(latch, symbol, session),
            quotes.get(symbol),
            side,
            now,
            session,
        )
        row["timing"] = timed
        if side == "buy" and gate == REJECTING:
            intent = intents.get(symbol)
            row.update(
                action=Action.HOLD,
                move_weight=0.0,
                executable=False,
                blocker=BAND_BLOCKER,
                reason=f"{BAND_BLOCK}; {intent}" if intent else BAND_BLOCK,
            )
            continue
        if row["action"] is Action.HOLD:
            continue
        word = _timed_word(row, side)
        if timed["state"] in entry_timing.ACTING:
            row["reason"] = f"{entry_timing.acting(word, timed)}; {row['reason']}"
            continue
        size = abs(row["move_weight"])
        row["reason"] = f"{entry_timing.planned(word, size, timed)}; {row['reason']}"
        row["action"] = Action.HOLD
        row["move_weight"] = 0.0


# Fund the person's board from their cash and, under the active policy, time
# it. `intents` are the target sentences of the target-sized buys (None for
# other rows); they are funded beside the band entries. Under the active
# policy a name the executor's band gate blocks is never bought today, so it
# takes no share of the cash bound, and the funded board is then held to the
# measured level (`_time_the_board`). Without the active policy this is the
# `/3` board's funding call exactly as it was.
def _plan_personal_board(
    result,
    held,
    equity,
    cash,
    snapshot,
    open_entries,
    paused,
    now,
    record,
    intents,
    *,
    toward_targets,
    readings,
    timing_latch,
):
    """Fund the personal rows in place and time them on the `/4` board."""
    blocked = (
        {s for s in intents if _structure_gate(record, s) == REJECTING}
        if toward_targets
        else set()
    )
    apply_personal_account_plan(
        result,
        held,
        equity,
        cash,
        snapshot,
        open_entries,
        paused,
        now,
        record,
        target_buys={
            symbol: (result[symbol]["strategy_move_weight"], intent)
            for symbol, intent in intents.items()
            if intent is not None and symbol not in blocked
        },
        close_grades=bool(toward_targets),
    )
    if toward_targets:
        _time_the_board(result, record, snapshot, readings, intents, timing_latch, now)


# The board-wide half of the timing, for the page: the rule, the level, the
# session it is timing and its close window, and whether today's latch was
# on file when the board was built.
def _timing_summary(latch, now) -> dict:
    """Return the `/4` board's timing summary."""
    from backend.market import entry_timing

    session = now.astimezone(desk_freshness.NEW_YORK).date()
    clock = entry_timing.session_clock(session)
    return {
        "rule": entry_timing.RULE,
        "level": entry_timing.LEVEL,
        "session": session.isoformat(),
        "close_cutoff": clock["cutoff"].isoformat(),
        "moc_deadline": clock["moc"].isoformat(),
        "latched": isinstance(latch, dict)
        and latch.get("session") == session.isoformat(),
    }


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
    risk_budget_pct=None,
    entry_readings=None,
    timing_latch=None,
):
    # `timing_latch` is today's `entry_timing` latch document (or None); only
    # the `/4` board reads it, through `_time_the_board`.
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
    # The personal board against a record stamped with the active policy sizes
    # toward that policy's weights: the book is the targets (the API already
    # swaps it; doing it here too means a caller that did not cannot size a
    # `/4` label against the `/3` book), and `action_for_row` trades the gap.
    # The explicit-targets research path above is a different question and
    # keeps its own book.
    toward_targets, record = _toward_targets(record, targets)
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
    # The target sentence of every Buy sized from the policy's targets rather
    # than a band entry (None for other rows): the personal plan funds those
    # buys from cash beside the entries, and keeps the sentence so a funded
    # row still says its target.
    intents: dict[str, str | None] = {}
    # The person's universe: what the desk grades, plus anything the person
    # actually holds. A name the person holds but the desk does not cover gets
    # a row that says so, because the exit question is the person's own.
    for symbol in sorted(set(record.get("grades") or {}) | set(book)):
        row = rows.get(symbol)
        # Under the active policy the intent reads the record's close grade,
        # the one the executor and the timing study decide on; the `/3`
        # board keeps its re-grade at the candle.
        intent_row = _at_the_close(row) if toward_targets else row
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
        # Intent and the funded plan must use the same refreshed grade.
        # A stale Buy opinion can otherwise suppress a current downgrade exit.
        entry = _unless_taken(
            entry_action(
                intent_row,
                (entries or {}).get(symbol),
                (
                    None
                    if toward_targets
                    else (readings.get(symbol) or {}).get("grade_live")
                )
                or (record.get("grades") or {}).get(symbol, {}).get("grade"),
                current,
            ),
            symbol,
            taken,
        )
        deadline = desk_freshness.timestamp(expiries.get(symbol))
        action, move, reason = action_for_row(
            intent_row,
            quote,
            deadline,
            paused,
            current_decision,
            target,
            current,
            now,
            entry,
            toward_targets=toward_targets,
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
        # A Buy that came from the targets (not from a firing band entry) is
        # the policy's standing order; its sentence survives every blocker.
        intent = _target_intent(toward_targets, strategy_action, entry, reason, blocker)
        intents[symbol] = intent
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
                    strategy_action, strategy_move_weight, blocker, intent
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
            **_entry_evidence(symbol, entries, entry_readings),
        }
        _apply_entry_reason(result[symbol], entry_readings, paused)
        _apply_risk_budget(
            result[symbol],
            symbol,
            snapshot,
            current,
            symbol in technical,
            expiries.get(symbol),
            now,
            risk_budget_pct,
            personal=targets is None,
        )
    if targets is None:
        _plan_personal_board(
            result,
            held,
            equity,
            cash,
            snapshot,
            open_entries,
            paused,
            now,
            record,
            intents,
            toward_targets=toward_targets,
            readings=readings,
            timing_latch=timing_latch,
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
            else "Nightly targets timed by the measured level (dip-or-close); "
            "personal execution is manual"
            if toward_targets
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
        # The `/4` board's actions are timed by the measured level; the key is
        # absent on every other board so their payloads are unchanged.
        **(
            {"timing": _timing_summary(timing_latch, now)}
            if toward_targets and targets is None
            else {}
        ),
    }
