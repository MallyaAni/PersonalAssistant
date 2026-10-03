"""Whole-share timing diagnostics on recorded intentions, never broker execution."""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from types import SimpleNamespace

import numpy as np

from backend.market import (
    calendar,
    entry_timing,
    learned_entry_data,
    sequential_execution_replay,
)
from backend.market import sequential_execution_shadow as shadow

METHODS = ("learned", "gate", "first_available")


# Reject invented fractional units and booleans where actual whole shares are required.
def _whole(value, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError("Whole-share integer required")
    if value < int(positive):
        raise ValueError(
            "Nonnegative holdings and positive intention quantities required"
        )
    return int(value)


# Leave incomplete marking explicit rather than quietly deleting held positions.
def _wealth(cash, holdings, marks):
    value = float(cash)
    for symbol, qty in holdings.items():
        mark = marks.get(symbol)
        if qty and (mark is None or not math.isfinite(mark) or mark <= 0):
            return None
        if qty:
            value += qty * mark
    return value


# Validate account inputs and preserve the entire intended opportunity denominator.
def _validate(
    initial_cash,
    holdings,
    intents,
    selected,
    cost_bps,
    delay_slots,
):
    if (
        not math.isfinite(initial_cash)
        or initial_cash < 0
        or not math.isfinite(cost_bps)
        or cost_bps < 0
        or delay_slots not in (1, 2)
    ):
        raise ValueError(
            "Finite nonnegative cash/cost and declared execution delay required"
        )
    owned = {symbol: _whole(qty) for symbol, qty in holdings.items()}
    ids = [row["id"] for row in intents]
    if len(set(ids)) != len(ids) or set(selected) != set(ids):
        raise ValueError(
            "Unique intentions and complete selection denominator required"
        )
    for row in intents:
        _whole(row["qty"], positive=True)
        if row["side"] not in ("buy", "sell") or not row["symbol"]:
            raise ValueError("Valid symbol/side required")
        clock = selected[row["id"]]
        if clock is not None and (
            isinstance(clock, bool)
            or not isinstance(clock, (int, np.integer))
            or not 0 <= clock <= 24
        ):
            raise ValueError("Attempt must be an observed clock or explicitly missing")
    return owned


# Apply locked attempts to identical initial cash and covered whole-share holdings.
def replay(
    initial_cash,
    holdings,
    intents,
    selected,
    opens,
    initial_marks,
    final_marks,
    cost_bps,
    delay_slots,
):
    owned = _validate(
        initial_cash,
        holdings,
        intents,
        selected,
        cost_bps,
        delay_slots,
    )
    initial_wealth = _wealth(initial_cash, owned, initial_marks)
    cash, budget, fees, gross = float(initial_cash), float(initial_cash), 0.0, 0.0
    ledger = {}
    # Preserve archive order at the same clock, including duplicate symbols.
    ordered = sorted(
        enumerate(intents),
        key=lambda pair: (
            25 if selected[pair[1]["id"]] is None else selected[pair[1]["id"]],
            pair[0],
        ),
    )
    rate = cost_bps / 10000
    for _, row in ordered:
        symbol, side, requested = row["symbol"], row["side"], int(row["qty"])
        clock = selected[row["id"]]
        fill_clock = None if clock is None else int(clock) + delay_slots
        event = dict(
            id=row["id"],
            symbol=symbol,
            side=side,
            requested_qty=requested,
            attempt_clock=clock,
            fill_clock=fill_clock,
            filled_qty=0,
            price=None,
            fee=0.0,
            status="no_attempt",
            cash_before=cash,
            initial_buy_budget_before=budget,
        )
        ledger[row["id"]] = event
        if clock is not None:
            series = opens.get(symbol)
            price = (
                None
                if series is None or fill_clock >= len(series) or fill_clock >= 26
                else float(series[fill_clock])
            )
            if price is None or not math.isfinite(price) or price <= 0:
                event["status"] = "missing_execution_price"
            else:
                event["price"] = price
                capacity = (
                    math.floor(budget / (price * (1 + rate)))
                    if side == "buy"
                    else owned.get(symbol, 0)
                )
                qty = min(requested, capacity)
                notional, fee = qty * price, qty * price * rate
                if side == "buy":
                    spend = notional + fee
                    budget -= spend
                    cash -= spend
                    owned[symbol] = owned.get(symbol, 0) + qty
                else:
                    cash += notional - fee
                    owned[symbol] = owned.get(symbol, 0) - qty
                fees += fee
                gross += notional
                event.update(
                    filled_qty=qty,
                    fee=fee,
                    status="filled"
                    if qty == requested
                    else "partial"
                    if qty
                    else "capacity_unavailable",
                )
        event.update(
            cash_after=cash,
            initial_buy_budget_after=budget,
            held_after=owned.get(symbol, 0),
        )
        if cash < -1e-7 or budget < -1e-7 or any(q < 0 for q in owned.values()):
            raise AssertionError("Accounting violated funding or covered holdings")
    ending = _wealth(cash, owned, final_marks)
    gain = None if ending is None or initial_wealth is None else ending - initial_wealth
    return dict(
        initial_wealth=initial_wealth,
        end_wealth=ending,
        net_gain=gain,
        return_pct=None
        if gain is None or initial_wealth <= 0
        else gain / initial_wealth * 100,
        cash=cash,
        holdings=owned,
        fees=fees,
        notional=gross,
        turnover=None if not initial_wealth else gross / initial_wealth,
        remaining_initial_buy_budget=budget,
        ledger=[ledger[row["id"]] for row in intents],
    )


# Prepare causal prefix features once, retaining no labels or execution prices.
def _packets(inputs):
    context = inputs.context
    session = np.datetime64(inputs.session, "D")
    dates = np.asarray(context.panel.dates, dtype="datetime64[D]")
    hits = np.flatnonzero(dates == session)
    if len(hits) != 1:
        raise ValueError("One explicit current context session required")
    stop = int(hits[0]) + 1
    prices = np.asarray(context.panel.adj_close[:stop], dtype=float).copy()
    prices[-1] = np.nan
    past = SimpleNamespace(
        dates=dates[:stop], tickers=context.panel.tickers, adj_close=prices
    )
    stamp = datetime.combine(inputs.session, time(9, 45), calendar.NEW_YORK)
    if set(context.published_at) != {"history", "grades", "membership"} or any(
        shadow._aware(value) > stamp for value in context.published_at.values()
    ):
        raise ValueError("Prior context must be published before the first prefix")
    names = sorted({row["symbol"] for row in inputs.intents})
    cubes = {name: inputs.cubes[name] for name in names}
    for cube in cubes.values():
        if (
            len(cube.dates) != 1
            or cube.dates[0] != session
            or any(
                np.asarray(getattr(cube, field)).shape != (1, 26)
                for field in ("open", "high", "low", "close", "volume")
            )
        ):
            raise ValueError("One explicit 26-slot current cube required")
    prepared = learned_entry_data.prepare(
        past, context.grades[:stop], context.eligible[:stop], cubes
    )
    supported = bool(sequential_execution_replay.supported_sessions([session])[0])
    packets = {}
    for symbol, cube in cubes.items():
        stock = context.panel.tickers.index(symbol)
        packets[symbol] = []
        for clock in range(25):
            received = stamp + timedelta(minutes=15 * clock)
            raw = float(cube.close[0, clock])
            packets[symbol].append(
                shadow.Observation(
                    str(session),
                    clock,
                    received.isoformat(),
                    "sip",
                    symbol,
                    prepared["X"][-1, clock, stock].copy(),
                    bool(prepared["valid"][-1, clock, stock]),
                    raw if np.isfinite(raw) and raw > 0 else None,
                    supported,
                    {
                        side: any(
                            entry_timing.crosses(value, cube.open[0, 0], side)
                            for value in cube.close[0, : clock + 1]
                        )
                        for side in ("buy", "sell")
                    },
                )
            )
    return packets


# Freeze first attempts from completed prefixes before reading fill prices.
def select_attempts(inputs, model):
    selected = {
        method: {row["id"]: None for row in inputs.intents} for method in METHODS
    }
    rows = {
        symbol: [row for row in inputs.intents if row["symbol"] == symbol]
        for symbol in sorted({row["symbol"] for row in inputs.intents})
    }
    decisions = []
    packets = _packets(inputs)
    for symbol, intentions in rows.items():
        for clock, observation in enumerate(packets[symbol]):
            sides = {
                side: shadow.decide(observation, model, side)
                for side in sorted({row["side"] for row in intentions})
            }
            decisions.append(
                dict(
                    symbol=symbol,
                    clock=clock,
                    hypothetical_observation_at=observation.received_at,
                    valid=observation.valid,
                    observed_price=observation.raw_price,
                    legacy_triggered=observation.legacy_triggered,
                    sides=sides,
                )
            )
            for row in intentions:
                conditions = {
                    "learned": sides[row["side"]]["state"]
                    in ("execute", "terminal_attempt"),
                    "gate": observation.supported
                    and observation.raw_price is not None
                    and (observation.legacy_triggered[row["side"]] or clock == 24),
                    "first_available": observation.supported
                    and observation.raw_price is not None,
                }
                for method, execute in conditions.items():
                    if execute and selected[method][row["id"]] is None:
                        selected[method][row["id"]] = clock
    return selected, decisions


# Compare all declared costs and clocks without fitting or selecting a convention.
def evaluate(inputs, model):
    selected, decisions = select_attempts(inputs, model)
    results = {}
    opens = {symbol: cube.open[0] for symbol, cube in inputs.cubes.items()}
    benchmarks = {}
    for symbol in ("SPY", "QQQ"):
        first, last = inputs.initial_marks[symbol], inputs.final_marks[symbol]
        benchmarks[symbol] = (last / first - 1) * 100
    for delay in (1, 2):
        for cost in (0, 10, 25):
            methods = {
                method: replay(
                    inputs.initial_cash,
                    inputs.holdings,
                    inputs.intents,
                    selected[method],
                    opens,
                    inputs.initial_marks,
                    inputs.final_marks,
                    cost,
                    delay,
                )
                for method in METHODS
            }
            for value in methods.values():
                value["benchmark_excess_pct"] = {
                    symbol: None
                    if value["return_pct"] is None
                    else value["return_pct"] - ret
                    for symbol, ret in benchmarks.items()
                }
            results[f"delay{delay}_cost{cost}"] = methods
    return dict(
        session=inputs.session.isoformat(),
        opportunities=len(inputs.intents),
        provenance=inputs.provenance,
        initial_cash=inputs.initial_cash,
        initial_holdings=inputs.holdings,
        initial_marks=inputs.initial_marks,
        final_marks=inputs.final_marks,
        intents=inputs.intents,
        selections=selected,
        decisions=decisions,
        benchmarks_gross_return_pct=benchmarks,
        results=results,
    )
