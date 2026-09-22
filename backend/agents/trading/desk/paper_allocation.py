"""The funded-allocation paper path: one daily decision and its order plan.

`paper.plan` with an `allocation_context` delegates here. The shared
`allocation.decide` and `funded_execution.plan_funded` do the deciding and the
cash-bounded whole-share sizing; this module owns the paper-account boundary:
persisting the stable selection, gating on unresolved pending orders, applying
the existing band-reversal buy blocker, converting the shared plan's orders to
the paper `PaperOrder` type with risk-cut priority metadata, and serializing the
`allocation_plan` display payload the contract's snapshot schema names.

Rules this boundary keeps:

* The selection is the caller's explicit unscaled stock weights, adopted only
  on a scheduled rebalance (or when no selection is persisted yet). Between
  rebalances the persisted selection is what is decided against, so a risk-only
  cut - which `allocation.decide` expresses by scaling the same names - never
  drops a name for re-entry. A genuine company exit shows up as the name
  leaving the caller's selection at the next scheduled rebalance, or
  immediately as an explicit `excluded_symbols` name: the shared
  `funded_execution.exclude_names` removes it from the stable composition
  before the daily decision on every day and the removal is persisted, so it
  cannot be resurrected by a later daily selection.
* Unresolved pending orders block the plan for the session, explicitly. A
  pending order may still fill (no assumed cancellation), its proceeds cannot
  be counted as cash (no pending-sale proceeds), and re-submitting the same
  order would duplicate it, so nothing new is issued until the caller has
  settled the outstanding set. Partial and rejected fills are reconciled the
  same way the incumbent is: they are folded into the journal and the next plan
  sizes from the actual holdings and cash the caller passes in.
* Risk-cut sells carry `priority` metadata naming the binding constraint; they
  are never dropped by a min-trade threshold or a buy gate.
* An explicitly `excluded_symbols` name is a mandatory exit on every day, not a
  policy call: the held name is stripped from the shared decision's desired
  weights so the planner always sells it, even when the policy evidence is
  missing and the unavailable fallback would otherwise retain the holding, and
  the sale is labeled an explicit company exit.
* The whole-share rounding and the fee/cash/name-cap re-check come from
  `plan_funded` with `whole_shares=True`; SPY is exempt from the name cap only
  under explicit index eligibility.
* The `allocation_plan` payload follows the shared metadata schema and defaults
  `adopted` to False. Money-market and duration assets are reported as
  unavailable; no invented eligibility, fill or yield is ever written.

The incumbent path never imports this module, so its behaviour and state JSON
are unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from backend.agents.trading.desk import allocation, funded_execution, paper
from backend.agents.trading.desk.allocation import QQQ, SPY

# The view version the shared metadata schema names.
VIEW_VERSION = "portfolio-allocation-view/1"

# Classes the contract names as unavailable: no actual eligibility, dealing or
# settlement exists for them, so they are never sized, filled or given yield.
UNAVAILABLE = (
    (
        "SWVXX",
        "cash",
        "money-market asset unavailable: no actual eligibility/dealing/settlement",
    ),
)


@dataclass(frozen=True)
class AllocationContext:
    """The optional daily decision inputs a caller passes into paper.plan.

    `excluded_symbols` names the explicit company exits for the decision: the
    shared `funded_execution.exclude_names` drops them from the stable
    composition before the daily decision, on every day, and the removal is
    persisted. It is a caller's explicit exit signal - a missing score or a
    risk cut is never an exit and must never be passed here.
    """

    policy: str = "vol_trend"
    index_eligible: bool = False
    dates: object | None = None
    prices: object | None = None
    tickers: list[str] | None = None
    t: int | None = None
    regime_cap: float | None = None
    event_cap: float | None = None
    desired_stock_weights: dict[str, float] | None = None
    cost_bps: float = 10.0
    excluded_symbols: frozenset[str] = frozenset()


# The excluded company symbols as an immutable set, whatever shape was given.
def _excluded(raw) -> frozenset:
    """Return `raw` as a frozenset of its string entries, empty when None."""
    if raw is None:
        return frozenset()
    if isinstance(raw, frozenset):
        return raw
    return frozenset(str(symbol) for symbol in raw)


# Accept the context as the dataclass, a mapping, or any object with the named
# attributes, so callers can hand the smallest structure they have.
def _coerce(context) -> AllocationContext:
    """Return an AllocationContext from an object or mapping."""
    if isinstance(context, AllocationContext):
        return context
    if isinstance(context, dict):
        raw = dict(context)
        raw["excluded_symbols"] = _excluded(raw.get("excluded_symbols", ()))
        return AllocationContext(**raw)
    return AllocationContext(
        policy=str(getattr(context, "policy", "vol_trend")),
        index_eligible=bool(getattr(context, "index_eligible", False)),
        dates=getattr(context, "dates", None),
        prices=getattr(context, "prices", None),
        tickers=getattr(context, "tickers", None),
        t=getattr(context, "t", None),
        regime_cap=getattr(context, "regime_cap", None),
        event_cap=getattr(context, "event_cap", None),
        desired_stock_weights=getattr(context, "desired_stock_weights", None),
        cost_bps=float(getattr(context, "cost_bps", 10.0)),
        excluded_symbols=_excluded(getattr(context, "excluded_symbols", ())),
    )


# Whether a price is usable as valuation evidence.
def _price_ok(value) -> bool:
    """Return True when `value` is a finite positive price."""
    return value is not None and np.isfinite(value) and value > 0


# The asset class the schema's rows and capabilities speak in.
def _kind(symbol: str) -> str:
    """Return "index" for SPY/QQQ and "stock" otherwise."""
    return "index" if symbol in (SPY, QQQ) else "stock"


# The current state as fractions of the account's own NAV, which is the marked
# positions plus the cash on hand - never the caller's separately-passed
# equity, which may be stale or approximate and would make the current stage
# fail to total one against itself.
def _nav_weights(held_set, price_map, cash) -> tuple[dict, float | None]:
    """Return ({symbol: weight of actual NAV}, cash fraction) for the account."""
    marked = {
        symbol: qty * price_map[symbol]
        for symbol, qty in held_set.items()
        if qty > 0 and symbol in price_map and _price_ok(price_map[symbol])
    }
    nav = sum(marked.values()) + (float(cash) if cash is not None else 0.0)
    if nav <= 0:
        return {}, None
    weights = {symbol: value / nav for symbol, value in marked.items()}
    cash_fraction = (float(cash) / nav) if cash is not None else None
    return weights, cash_fraction


# The projected state as fractions of the post-fee NAV of the actual filtered
# order basket: the cash the basket leaves plus the remaining marked
# positions, the same denominator the shared plan_funded uses. Held-back buys
# and blocked legs never shift the projection, because only the orders that
# actually made the paper basket move it.
def _projected_nav(
    held_set, price_map, cash, orders, cost_bps
) -> tuple[dict, float | None]:
    """Return ({symbol: projected weight}, cash fraction) against post-fee NAV.

    When the account's cash is not known, the marked weights of the remaining
    positions (fractions of their own value) are still reported so the rows and
    buckets do not collapse to zero, but the cash fraction is None - a missing
    value, never a fabricated 0.0.
    """
    remaining = dict(held_set)
    for order in orders:
        if not _price_ok(price_map.get(order.symbol)):
            continue
        remaining[order.symbol] = remaining.get(order.symbol, 0.0) + (
            order.qty if order.side == "buy" else -order.qty
        )
    remaining = {
        symbol: qty
        for symbol, qty in remaining.items()
        if qty > 1e-9 and symbol in price_map
    }
    if cash is None:
        final_value = sum(qty * price_map[symbol] for symbol, qty in remaining.items())
        if final_value <= 0:
            return {}, None
        return (
            {
                symbol: qty * price_map[symbol] / final_value
                for symbol, qty in remaining.items()
            },
            None,
        )
    projected_cash = _projected_cash(cash, orders, price_map, cost_bps)
    final_value = sum(qty * price_map[symbol] for symbol, qty in remaining.items())
    nav = projected_cash + final_value
    if nav <= 0:
        return {}, None
    weights = {
        symbol: qty * price_map[symbol] / nav for symbol, qty in remaining.items()
    }
    return weights, projected_cash / nav


# The cash the final order basket leaves, from the starting cash and fees.
def _projected_cash(cash, orders, price_map, cost_bps: float) -> float:
    """Return the cash after executing `orders` at their prices and fees."""
    cost = cost_bps / 1e4
    balance = float(cash)
    for order in orders:
        price = price_map.get(order.symbol)
        if not _price_ok(price):
            continue
        if order.side == "buy":
            balance -= order.qty * price * (1.0 + cost)
        else:
            balance += order.qty * price * (1.0 - cost)
    return max(0.0, balance)


# The funded plan's risk-cut marker: the binding constraint, when a sell is one.
def _risk_priority(order, decision) -> str | None:
    """Return the binding reason when `order` is a risk cut, else None."""
    if order.side == "sell" and str(order.reason).startswith("risk reduction"):
        return decision.binding
    return None


# Sum the stock and SPY-index weights of a weight map.
def _breakdown(weights) -> tuple[float, float]:
    """Return (stock weight, index weight) from a weight map."""
    stocks = sum(w for s, w in weights.items() if _kind(s) == "stock")
    indexes = sum(w for s, w in weights.items() if s == SPY)
    return float(stocks), float(indexes)


# One display row per symbol, plus the CASH display row.
def _rows(
    context,
    tickers,
    held_set,
    price_map,
    current_weights,
    current_cash_fraction,
    target,
    target_cash,
    projected_weights,
    projected_cash_fraction,
    orders,
):
    """Return the {symbol: row} display map for the allocation_plan.

    The per-symbol weights are fractions of the same NAVs as the stage
    buckets: `current_*` of the account's own NAV and `projected_*` of the
    post-fee basket NAV, so the rows and the buckets cannot drift apart.
    A symbol in the universe with no target weight reads 0.0 on a complete
    target rather than null, so the detail agrees with the bucket.
    """
    symbols = sorted(s for s in set(tickers) | set(held_set) if s != QQQ)
    rows: dict = {}
    for symbol in symbols:
        delta = sum(
            order.qty if order.symbol == symbol and order.side == "buy" else -order.qty
            for order in orders
            if order.symbol == symbol
        )
        order_reason = next(
            (order.reason for order in orders if order.symbol == symbol), None
        )
        if _price_ok(price_map.get(symbol)):
            current_weight = current_weights.get(symbol, 0.0)
        else:
            current_weight = None
        rows[symbol] = {
            "kind": _kind(symbol),
            "current_weight": current_weight,
            "target_weight": target.get(symbol, 0.0) if target is not None else None,
            "projected_weight": projected_weights.get(symbol, 0.0),
            "action": "BUY" if delta > 0 else "SELL" if delta < 0 else "HOLD",
            "reason": order_reason
            or (
                "retain current position"
                if held_set.get(symbol, 0) > 0
                else "no funded order this session"
            ),
        }
    rows["CASH"] = {
        "kind": "cash",
        "current_weight": current_cash_fraction,
        "target_weight": target_cash,
        "projected_weight": projected_cash_fraction,
        "action": "HOLD",
        "reason": "cash residual; display asset, never an order",
    }
    return rows


# The explicit eligibility list: the index under the caller's flag, the always
# available cash residual, and the classes that are unavailable by design.
def _capabilities(context) -> list[dict]:
    """Return the capabilities list for the allocation_plan."""
    out = [
        {
            "symbol": SPY,
            "kind": "index",
            "eligible": bool(context.index_eligible),
            "reason": (
                "SPY residual eligible under the current policy"
                if context.index_eligible
                else "SPY residual not eligible; "
                "index selection requires explicit index eligibility"
            ),
        },
        {
            "symbol": "CASH",
            "kind": "cash",
            "eligible": True,
            "reason": "cash residual is always available",
        },
    ]
    for symbol, kind, reason in UNAVAILABLE:
        out.append(
            {
                "symbol": symbol,
                "kind": kind,
                "eligible": False,
                "reason": reason,
            }
        )
    return out


# Serialize one decision day into the shared metadata schema.
def _allocation_plan(
    context,
    held_set,
    price_map,
    cash,
    status,
    reason,
    blocked,
    missing,
    decision,
    orders,
):
    """Return the allocation_plan display payload for one funded day.

    The current stage is fractions of the account's own NAV (marked positions
    plus cash) and the projected stage is fractions of the post-fee NAV of the
    actual filtered order basket - the same denominators the rows use - so each
    bucket totals one against itself and the payload passes the shared
    serializer. A missing valuation or a null target stays null; no invented
    fraction is written for it.
    """
    current_weights, current_cash_fraction = _nav_weights(held_set, price_map, cash)
    stock_now, index_now = _breakdown(current_weights)
    if decision is not None:
        target = decision.desired_weights
        target_cash = float(decision.cash)
        target_stock, target_index = _breakdown(target)
    else:
        target = {}
        target_cash = None
        target_stock = target_index = None
    projected_weights, projected_cash_fraction = _projected_nav(
        held_set, price_map, cash, orders, float(context.cost_bps)
    )
    projected_stock, projected_index = _breakdown(projected_weights)
    return {
        "version": VIEW_VERSION,
        "as_of": decision.as_of if decision is not None else None,
        "policy": context.policy,
        "status": status,
        "adopted": False,
        "reason": reason,
        "missing": list(missing),
        "blocked": list(blocked),
        "current": {
            "stocks": stock_now,
            "indexes": index_now,
            "cash": current_cash_fraction,
        },
        "target": {
            "stocks": target_stock,
            "indexes": target_index,
            "cash": target_cash,
        },
        "projected": {
            "stocks": projected_stock,
            "indexes": projected_index,
            "cash": projected_cash_fraction,
        },
        "rows": _rows(
            context,
            list(context.tickers or ()),
            held_set,
            price_map,
            current_weights,
            current_cash_fraction,
            target,
            target_cash,
            projected_weights,
            projected_cash_fraction,
            orders,
        ),
        "capabilities": _capabilities(context),
    }


# The allocation_state dict that is persisted on every funded day.
def _persisted_state(stable, context, plan_payload) -> dict:
    """Return the allocation_state block to persist for one decision day."""
    return {
        "stable_desired": dict(stable),
        "policy": context.policy,
        "index_eligible": bool(context.index_eligible),
        "cost_bps": float(context.cost_bps),
        "excluded_symbols": sorted(context.excluded_symbols),
        "plan": plan_payload,
    }


# A blocked funded day: no decision, no orders, an explicit payload.
def _blocked(
    new,
    stable,
    context,
    held_set,
    price_map,
    cash,
    reason,
    blocked,
) -> tuple[list, paper.PaperState, str]:
    """Return the empty plan and state for a funded day that cannot size."""
    payload = _allocation_plan(
        context,
        held_set,
        price_map,
        cash,
        "blocked",
        reason,
        blocked,
        [],
        None,
        [],
    )
    new.allocation_state = _persisted_state(stable, context, payload)
    return [], new, "allocation-blocked"


# The held positions that are actually nonzero, as plain floats.
def _positive_held(held: dict[str, float]) -> dict[str, float]:
    """Return the positive finite holdings of `held`."""
    return {s: float(q) for s, q in held.items() if q and q > 0}


# The stable selection and whether today refreshes it.
def _selection(
    state, prior, context, force_rebalance: bool
) -> tuple[bool, dict[str, float]]:
    """Return (rebalance, stable selection) for today's funded day.

    The selection is refreshed only on a scheduled rebalance. Between
    rebalances the persisted selection is kept as it is - including an
    intentionally empty (all-cash) composition, which must not be treated as
    uninitialized and silently replaced with the caller's daily selection. The
    caller's selection is only adopted to establish a book when no funded state
    has ever been persisted (a fresh or legacy state).
    """
    rebalance = (
        force_rebalance
        or state.last_rebalance is None
        or state.sessions_since_rebalance + 1 >= paper.REBALANCE_EVERY
    )
    if rebalance:
        return rebalance, dict(context.desired_stock_weights or {})
    if state.allocation_state is not None:
        return rebalance, dict(prior.get("stable_desired") or {})
    return rebalance, dict(context.desired_stock_weights or {})


# Whether the context and cash are complete enough to size a funded day.
def _complete(context, cash, session) -> bool:
    """Return True when the funded day has every input it needs.

    The decision matrix must line up with the dates and tickers and `t` must
    name a row in range, and the decision date must not be in the future of the
    session it is being used for (a later matrix mark must never value an
    earlier session or persist a future as_of).
    """
    if (
        context.dates is None
        or context.prices is None
        or not context.tickers
        or context.t is None
        or context.regime_cap is None
        or context.event_cap is None
        or cash is None
        or not math.isfinite(cash)
        or cash < 0
    ):
        return False
    prices = np.asarray(context.prices)
    t = int(context.t)
    if prices.ndim != 2 or not len(context.tickers) or not 0 <= t < prices.shape[0]:
        return False
    if prices.shape[0] != len(np.asarray(context.dates)) or prices.shape[1] != len(
        context.tickers
    ):
        return False
    decision_date = np.asarray(context.dates)[t]
    if isinstance(decision_date, np.datetime64) and np.isnat(decision_date):
        return False
    # The decision date must be the session being planned. Consuming a matrix
    # whose decision row is any other date - in particular one in the future -
    # would value this session with later marks and persist a wrong as_of, so a
    # misaligned context is rejected.
    return not (
        _is_date(session)
        and isinstance(decision_date, np.datetime64)
        and decision_date.astype("datetime64[D]") != np.datetime64(session, "D")
    )


# Whether a session label is a plain ISO date.
def _is_date(session: str) -> bool:
    """Return True when `session` parses as an ISO YYYY-MM-DD date."""
    try:
        np.datetime64(str(session), "D")
        return len(str(session)) == 10
    except (TypeError, ValueError):
        return False


# The price and held maps the decision and plan read.
def _priced_held(context, held, prices, t) -> tuple[dict, dict, list]:
    """Return (held_set, price_map, held names that cannot be valued)."""
    held_set = _positive_held(held)
    price_map = {s: float(p) for s, p in prices.items() if _price_ok(p)}
    for column, ticker in enumerate(list(context.tickers or ())):
        if not _price_ok(price_map.get(ticker)):
            value = float(context.prices[t, column])
            if _price_ok(value):
                price_map[ticker] = value
    unvalued = sorted(
        s
        for s in held_set
        if s not in context.tickers or not _price_ok(price_map.get(s))
    )
    return held_set, price_map, unvalued


# Convert the shared plan's orders into paper orders, gating band-rejected buys.
def _paper_orders(new, session, plan, decision, blocked_names, excluded):
    """Return (held-back names, the paper PaperOrder list).

    A sell of an explicitly excluded name is labeled a company exit rather than
    the planner's generic reason, so the mandatory exit is visible in the rows
    and to whoever executes the order.
    """
    held_back: list[str] = []
    orders: list[paper.PaperOrder] = []
    for order in plan.orders:
        if order.side == "buy" and order.symbol in blocked_names:
            held_back.append(order.symbol)
            continue
        reason = (
            "explicit company exit (excluded_symbols)"
            if order.side == "sell" and order.symbol in excluded
            else order.reason
        )
        seq = new.order_seq
        new.order_seq += 1
        orders.append(
            paper.PaperOrder(
                order.symbol,
                order.side,
                int(order.qty),
                reason,
                client_order_id=paper.order_id(session, order.symbol, order.side, seq),
                priority=_risk_priority(order, decision),
            )
        )
    return held_back, orders


# The status and day label for a sized funded plan.
def _status_and_what(plan, decision, rebalance: bool) -> tuple[str, str]:
    """Return (status, what) for a funded day that reached the plan."""
    if plan.blocked:
        return "blocked", "allocation-blocked"
    if not decision.available:
        return "unavailable", "allocation-unavailable"
    return "available", ("allocation-rebalance" if rebalance else "allocation")


# The headline reason, with the mandatory exits named so the payload's summary
# never contradicts the exit orders it carries.
def _excluded_reason(plan_reason, orders, excluded) -> str:
    """Return `plan_reason`, extended with the explicitly exited names."""
    exited = sorted(
        {o.symbol for o in orders if o.side == "sell" and o.symbol in excluded}
    )
    if not exited:
        return plan_reason
    return f"{plan_reason}; explicit company exit for {', '.join(exited)}"


# The account equity is a sizing input, not a display detail.
def _equity_reason(equity: float) -> str | None:
    """Return the block reason when `equity` cannot size a day, else None."""
    if not math.isfinite(equity) or equity <= 0:
        return "blocked: account equity must be a finite positive number"
    return None


# After a plan is actually made, record the session and the rebalance clock.
def _mark_planned(new, state, session, orders, rebalance):
    """Mark the planned session and advance the rebalance clock on `new`."""
    if session not in state.sessions_seen:
        new.sessions_seen = state.sessions_seen + [session]
    if rebalance:
        new.previous_rebalance = state.last_rebalance
        new.last_rebalance = session
        new.sessions_since_rebalance = 0
    else:
        new.sessions_since_rebalance = state.sessions_since_rebalance + 1
    for order in orders:
        if order.side == "buy":
            new.opened.setdefault(order.symbol, session)


# One funded-allocation day for the paper book: decide, size, gate, persist.
def plan_funded_paper(
    session: str,
    state: paper.PaperState,
    equity: float,
    held: dict[str, float],
    prices: dict[str, float],
    cash: float | None,
    context,
    *,
    force_rebalance: bool = False,
    entry_blocked: set[str] | None = None,
) -> tuple[list[paper.PaperOrder], paper.PaperState, str]:
    """Return (orders, new state, what) for one funded-allocation day.

    The stable selection is chosen before any blocking: a pending-blocked day
    persists the same composition the retry would decide against, so an
    explicitly empty (all-cash) selection is never replaced by the caller's
    daily selection. An explicitly excluded held name is a mandatory exit on
    every day - even when policy evidence is missing - because it is stripped
    from the decision's desired weights before the shared planner runs. Missing
    cash is reported as missing (a null fraction) rather than a fabricated 0.0,
    and a non-finite or non-positive account equity blocks the day instead of
    sizing against nonsense.
    """
    from dataclasses import asdict

    context = _coerce(context)
    new = paper.PaperState(**asdict(state))
    prior = state.allocation_state or {}
    context = replace(
        context,
        excluded_symbols=frozenset(context.excluded_symbols)
        | frozenset(prior.get("excluded_symbols", ())),
    )
    blocked_names = set(entry_blocked or ())

    # The stable selection is computed first, so a day blocked by unresolved
    # orders persists the same composition the retry would decide against -
    # never the caller's daily selection when an explicitly empty one is on
    # record. An explicit company exit removes the name from the stable
    # composition on every day - a scheduled refresh, a plain day and a
    # pending-blocked day alike - and the removal is persisted, so the name
    # cannot be resurrected by a later daily selection. A risk-only cut never
    # reaches here: it scales the same names, so the composition is retained
    # for re-entry.
    rebalance, stable = _selection(state, prior, context, force_rebalance)
    stable = funded_execution.exclude_names(stable, context.excluded_symbols)

    # Unresolved orders block the day outright. A pending order may still fill
    # (never assume a cancellation), its proceeds are not cash yet, and a
    # replacement would duplicate it, so nothing new is issued until the caller
    # has settled the outstanding set. A blocked attempt does not mark the
    # session as planned, so the same session can be retried once it resolves.
    if state.pending:
        ids = [str(row.get("client_order_id") or "") for row in state.pending]
        return _blocked(
            new,
            stable,
            context,
            _positive_held(held),
            prices,
            cash,
            f"unresolved orders pending settlement: {', '.join(ids)}",
            [],
        )

    if not _complete(context, cash, session):
        return _blocked(
            new,
            stable,
            context,
            _positive_held(held),
            prices,
            cash,
            "incomplete or misaligned allocation_context: dates, prices, "
            "tickers, t, regime_cap, event_cap, a finite nonnegative cash, an "
            "in-range decision index and a decision date not in the future of "
            "the session are required",
            [],
        )

    # A non-finite or non-positive equity would size orders against nonsense,
    # so it is a blocked day here, never sized against.
    equity_reason = _equity_reason(equity)
    if equity_reason is not None:
        return _blocked(
            new,
            stable,
            context,
            _positive_held(held),
            prices,
            cash,
            equity_reason,
            [],
        )

    held_set, price_map, unvalued = _priced_held(context, held, prices, context.t)
    if unvalued:
        return _blocked(
            new,
            stable,
            context,
            held_set,
            price_map,
            cash,
            "blocked: a held position cannot be valued; sizing deferred",
            unvalued,
        )
    # Size and display against the same marked ledger NAV. The broker's
    # separately supplied equity can be stale or include unrelated positions.
    equity = float(cash) + sum(held_set[s] * price_map[s] for s in held_set)
    if equity <= 0:
        return _blocked(
            new,
            stable,
            context,
            held_set,
            price_map,
            cash,
            "blocked: marked account NAV must be positive",
            [],
        )
    blocked: list[str] = []

    held_weights = {
        symbol: held_set[symbol] * price_map[symbol] / equity for symbol in held_set
    }
    try:
        decision = allocation.decide(
            context.dates,
            context.prices,
            list(context.tickers),
            context.t,
            desired=stable,
            # Match the simulator: remove explicit exits before applying the
            # missing-evidence ceiling to the remaining holdings.
            held=funded_execution.exclude_names(held_weights, context.excluded_symbols),
            regime_cap=context.regime_cap,
            event_cap=context.event_cap,
            policy=context.policy,
            index_eligible=context.index_eligible,
        )
    except ValueError as exc:
        return _blocked(
            new,
            stable,
            context,
            held_set,
            price_map,
            cash,
            f"allocation decision input invalid: {exc}",
            [],
        )

    plan = funded_execution.plan_funded(
        decision,
        held_set,
        price_map,
        equity,
        cash,
        cost_bps=float(context.cost_bps),
        whole_shares=True,
        index_eligible=context.index_eligible,
        entry_cap=paper.ENTRY_NAME_CAP,
        min_trade=paper.MIN_TRADE,
    )
    held_back, orders = _paper_orders(
        new, session, plan, decision, blocked_names, context.excluded_symbols
    )
    for symbol in sorted(held_back):
        blocked.append(
            f"{symbol}: buy held back; the daily is rejecting its upper Bollinger band"
        )
    # The shared planner's own blocked legs (e.g. an unexecutable fractional
    # residual after whole-share rounding) are reported alongside ours.
    blocked.extend(list(plan.blocked))

    status, what = _status_and_what(plan, decision, rebalance)
    payload = _allocation_plan(
        context,
        held_set,
        price_map,
        cash,
        status,
        _excluded_reason(plan.reason, orders, context.excluded_symbols),
        blocked,
        plan.missing,
        decision,
        orders,
    )
    new.allocation_state = _persisted_state(stable, context, payload)
    # A plan was actually made for this session, so it is never planned twice.
    # A blocked attempt above never marks the session, keeping it retryable.
    _mark_planned(new, state, session, orders, rebalance)
    return orders, new, what
