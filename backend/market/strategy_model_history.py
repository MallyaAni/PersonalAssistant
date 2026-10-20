"""Account-independent historical sizes from the installed strategy's rules.

The caller authenticates original daily grades, prices, OOS model artifacts and
completed-candle grids. This is a NEW counterfactual fractional-capital book,
never a reconstruction of an account or of historically published advice.
The unchanged sizing model selects composition; the unchanged probability
model selects an ordinary attempt after a completed fifteen-minute candle.
Subsequent opens price only already-locked attempts. No broker is imported.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np

from backend.market import calendar, grade_led_policy
from backend.market import daily_arithmetic_bridge as reference
from backend.market import probabilistic_execution as timing

SCHEMA = "latest-strategy-simulation/1"
VERSION = "strategy-model-history/1"
BASIS = "account_independent_unit_capital_targets"
# The sizing and timing heads were fitted through the later of their frozen
# boundaries; decisions at or before it are in-sample for the owner's replay check.
MODEL_FIT_THROUGH = str(max(reference.FREEZE, timing.FREEZE))


# Preserve eligible zero-sized holdings without imposing an account's integer lot size.
def continuous_targets(targets, current, grades):
    selected = dict(targets)
    for name, weight in current.items():
        if grades.get(name, -1) < 0:
            selected[name] = weight
        elif grades[name] >= 2 and selected.get(name, 0.0) <= 0:
            selected[name] = weight
        elif grades[name] < 2:
            selected[name] = 0.0
    increases = sum(max(0.0, weight - current.get(name, 0.0)) for name, weight in selected.items())
    room = max(0.0, 1.0 - sum(min(weight, current.get(name, 0.0)) for name, weight in selected.items()))
    if increases > room and increases:
        selected = {name: min(weight, current.get(name, 0.0)) + room / increases * max(0.0, weight - current.get(name, 0.0)) for name, weight in selected.items()}
    return selected


# Name a simulated exchange instant without modifying the real calculation clock.
def instant(day, minutes):
    return datetime.combine(day.astype(object), calendar.REGULAR_OPEN, calendar.NEW_YORK) + timedelta(minutes=minutes)


# Retain an original positive action size even when the remaining position is zero.
def action_row(name, at, side, size, remaining, sequence):
    return {"id": f"{VERSION}:{sequence}:{name}", "ticker": name,
            "date": at.date().isoformat(), "at": at.isoformat(),
            "valid_until": (at + timedelta(minutes=15)).isoformat(),
            "action": "BUY" if side == "buy" else "SELL", "weight": float(size),
            "target_weight": float(remaining), "state": "recommended",
            "counterfactual": True}


# Walk one new fractional-capital book, keeping future execution prices out of selection.
def replay(policy, panel, grades, blocked, eligible, observations, execution_opens,
           provider, *, first, provenance, generated_at, allocations=None,
           daily_evidence=None, initial_book=None):
    names, dates = tuple(panel.tickers), panel.dates
    shape = (len(dates), len(names))
    close = getattr(panel, 'close', None)
    if close is None:
        raise ValueError(
            "Panel close is required to align open and intraday prices "
            "to adjusted close")
    close = np.asarray(close)
    eligible = np.asarray(eligible)
    if (grades.shape != shape or blocked.shape != shape or eligible.shape != shape
            or eligible.dtype.kind != 'b'
            or observations.shape != (len(dates), 25, len(names))
            or execution_opens.shape != observations.shape
            or panel.adj_close.shape != shape or panel.open.shape != shape
            or close.shape != shape
            or not 1 <= first < len(dates) or not callable(provider)
            or generated_at.utcoffset() is None
            or not np.isin(grades, (-1, 0, 1, 2, 3)).all()
            or np.any(dates[1:] <= dates[:-1])
            or (allocations is not None and allocations.shape != shape)):
        raise ValueError("Aligned original simulation inputs required")
    # The book marks in adjusted close; scale every raw open and intraday price
    # by the same factor so a split cannot misprice one leg of a trade.
    with np.errstate(divide='ignore', invalid='ignore'):
        adjustment = np.where(
            np.isfinite(close) & (close > 0), panel.adj_close / close, np.nan)
    stocks = [i for i, name in enumerate(names) if name not in ("SPY", "QQQ")]
    projections = {names[i]: {"ticker": names[i], "decisions": [], "trades": [], "targets": [], "grade_rows": [], "splits": []} for i in stocks}
    shares, cash, fees, sequence = np.zeros(len(names)), 1.0, 0.0, 0
    if initial_book is not None:
        from backend.market.strategy_model_extension import InitialBook
        if type(initial_book) is not InitialBook:
            raise ValueError("Typed original numerical continuation required")
        initial_book.validate(dates, names, first)
        shares = np.array(initial_book.shares, dtype=np.float64)
        cash, fees, sequence = initial_book.cash, initial_book.fees, initial_book.sequence
    counters = {"sizing_unavailable": 0, "unpriced_book": 0, "unavailable_timing": 0, "unpriced_attempt": 0, "decisions": 0}
    curve = []
    cost = policy.cost_bps / 10000
    for day in range(first, len(dates)):
        prior = panel.adj_close[day - 1]
        if np.any((shares > 0) & (~np.isfinite(prior) | (prior <= 0))):
            counters["unpriced_book"] += 1
            continue
        nav = float(cash + np.dot(shares, np.where(np.isfinite(prior), prior, 0)))
        current = {names[i]: float(shares[i] * prior[i] / nav) for i in stocks if shares[i] > 0}
        codes = {names[i]: int(grades[day - 1, i]) for i in stocks}
        report = SimpleNamespace(panel=SimpleNamespace(dates=dates[:day], tickers=names), graded=SimpleNamespace(grades=grades[:day]))
        if allocations is None:
            from backend.market.strategy_model_allocation import targets_from_model
            weights, _, _ = targets_from_model(report, policy.reader, policy.cost_bps, {names[i] for i in stocks if blocked[day - 1, i]})
            weights = continuous_targets(weights, current, codes)
        elif np.isfinite(allocations[day - 1, stocks]).all():
            weights = continuous_targets({names[i]: float(allocations[day - 1, i]) for i in stocks}, current, codes)
        else:
            counters["sizing_unavailable"] += 1
            weights = {name: weight if codes.get(name, -1) < 0 or codes[name] >= 2 else 0.0 for name, weight in current.items()}
        # Membership is dated: a name outside the book on the decision session
        # cannot be selected, sized or bought, whatever its current grade says.
        for i in stocks:
            if not eligible[day - 1, i]:
                weights[names[i]] = 0.0
        wanted = shares.copy()
        for i in stocks:
            if np.isfinite(prior[i]) and prior[i] > 0:
                wanted[i] = weights.get(names[i], 0.0) * nav / prior[i]
            target_rows = projections[names[i]]["targets"]
            if not target_rows or target_rows[-1]['weight'] != weights.get(names[i]):
                target_rows.append({"date": str(dates[day - 1]), "weight": weights.get(names[i])})
            grade_rows = projections[names[i]]["grade_rows"]
            grade = grade_led_policy.LETTERS[codes[names[i]]]
            if not grade_rows or grade_rows[-1]['grade'] != grade:
                grade_rows.append({"date": str(dates[day - 1]), "grade": grade, "said": False})
        pending = np.abs(wanted - shares) > 1e-12
        budget = cash
        # A grade or membership exit is already decided before the open; it never
        # waits for a timing forecast, and both sell on the next adjusted open.
        for i in stocks:
            member = bool(eligible[day - 1, i])
            grade_exit = 0 <= codes[names[i]] < 2
            if shares[i] <= 0 or (member and not grade_exit):
                continue
            sequence += 1
            timing_reason = 'mandatory_grade_exit' if member else 'universe_exit'
            reason = (
                'Grade below A; exit the simulated position' if member
                else 'Not in the point-in-time universe; exit the simulated position')
            row = action_row(names[i], instant(dates[day], 0), "sell", shares[i] * prior[i] / nav, 0.0, sequence)
            row['evidence'] = {
                **(daily_evidence(day - 1, i) if daily_evidence else {}),
                'grade': grade_led_policy.LETTERS[codes[names[i]]],
                'reason': reason,
                'timing_reason': timing_reason}
            price = panel.open[day, i] * adjustment[day, i]
            if np.isfinite(price) and price > 0:
                amount = shares[i] * price
                cash += amount * (1 - cost)
                fees += amount * cost
                shares[i] = 0
                row["state"] = "executed_proxy"
            else:
                counters["unpriced_attempt"] += 1
                row["state"] = "execution_price_unavailable"
            pending[i] = False
            projections[names[i]]["decisions"].append(row)
        for clock in range(25):
            observed = observations[day, clock] * adjustment[day]
            if np.any((shares > 0) & (~np.isfinite(observed) | (observed <= 0))):
                counters["unpriced_book"] += 1
                continue
            nav = float(cash + np.dot(shares, np.where(np.isfinite(observed), observed, 0)))
            delta = wanted - shares
            ready = []
            spend = float(np.maximum(delta, 0) @ np.where(np.isfinite(observed), observed, 0)) * (1 + cost)
            funded = min(1.0, budget / spend) if spend > 0 else 1.0
            for i in stocks:
                if not pending[i] or not np.isfinite(observed[i]) or observed[i] <= 0:
                    continue
                buying = delta[i] > 0
                weight = abs(delta[i]) * observed[i] / nav * (funded if buying else 1.0)
                if not 0 < weight <= 1:
                    continue
                choice = timing.Decision("execute", reason="shared_terminal_deadline") if clock == 24 else timing.decision(provider(day, clock, i), "buy" if buying else "sell", weight, policy.cost_bps, horizon=timing.HORIZON)
                counters["unavailable_timing"] += int(choice.state == "unavailable")
                if choice.state == "execute":
                    ready.append((i, buying, float(weight), float(delta[i]), choice))
            # Only now may the counterfactual ledger read the selected subsequent open.
            for i, buying, weight, change, choice in sorted(ready, key=lambda item: item[1]):
                sequence += 1
                row = action_row(names[i], instant(dates[day], 15 * (clock + 1)), "buy" if buying else "sell", weight, weights.get(names[i], 0.0), sequence)
                row["timing"] = policy.timing_policy
                row['evidence'] = {**(daily_evidence(day - 1, i) if daily_evidence else {}), 'grade': grade_led_policy.LETTERS[codes[names[i]]], 'reason': 'Grade-permitted model allocation increase' if buying else 'Model allocation reduction', 'observed_price': float(observed[i]), 'timing_reason': choice.reason, 'waiting_log_utility': choice.expected_log_utility, 'completed_candle_at': row['at']}
                price = float(execution_opens[day, clock, i] * adjustment[day, i])
                pending[i] = False
                if np.isfinite(price) and price > 0:
                    qty = min(change * funded, max(0.0, min(cash, budget)) / (price * (1 + cost))) if buying else min(-change, shares[i])
                    amount = qty * price
                    fee = amount * cost
                    cash += -amount - fee if buying else amount - fee
                    shares[i] += qty if buying else -qty
                    if buying:
                        budget = max(0.0, budget - amount - fee)
                    fees += fee
                    row["state"] = "executed_proxy" if qty > 0 else "cash_limited"
                else:
                    row["state"] = "execution_price_unavailable"
                    counters["unpriced_attempt"] += 1
                projections[names[i]]["decisions"].append(row)
            if cash < -1e-10 or np.any(shares < -1e-10):
                raise ValueError("Simulation cannot borrow or sell unowned units")
        closing = panel.adj_close[day]
        if not np.any((shares > 0) & ~np.isfinite(closing)):
            curve.append({"date": str(dates[day]), "equity": float(cash + shares @ np.where(np.isfinite(closing), closing, 0)), "cash": float(cash)})
    source = {**provenance, "basis": BASIS, "fractional_capital": True, "timing_policy": policy.timing_policy, "cost_bps": policy.cost_bps,
              "historical_publication_claim": False, "grade_basis": "original_frozen_current_vintage_reconstruction"}
    if initial_book is not None:
        source["continuation_of_sha256"] = initial_book.result_sha256
    result = {"schema": SCHEMA, "version": VERSION, "policy": grade_led_policy.POLICY,
              "start": str(dates[first]), "through": str(dates[-1]), "generated_at": generated_at.isoformat(),
              "counterfactual": True, "real_orders": False, "provenance": source, "stocks": projections,
              "curve": curve, "fees": float(fees), "counters": counters}
    for i in stocks:
        value = projections[names[i]]
        value.update({key: result[key] for key in ("schema", "version", "policy", "start", "through", "generated_at", "counterfactual", "real_orders", "provenance")})
        value["latest_target"] = value["targets"][-1]["weight"] if value["targets"] else None
        value["latest_holding"] = float(shares[i])
        counters["decisions"] += len(value["decisions"])
    return result
