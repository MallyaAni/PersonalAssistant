"""Fixed A2/B2 bar diagnostics; funded timing accounts, never live activation.

Pinned by test_entry_exit_study.py. Specification and limitations are in the
October-2 section of docs/research/entry-exit-audit-2026-10-01.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import policy_v5, simulate
from backend.market import fill_timing
from backend.market.open_source_portfolio import summarize, validate
from backend.market.sip_cube import SessionCube

VERSION = "entry-exit-bar-diagnostic/1"
CONTROL = "dip_pop_control"
ENTRY = "hold_dip_confirmation"
EXIT = "trail_pop_exit"
ARMS = (CONTROL, ENTRY, EXIT)
COSTS = (10.0, 25.0)


# State the two fixed rules and execution assumptions before reading outcomes.
def specification():
    return {
        "version": VERSION,
        "candidates": [ENTRY, EXIT],
        "entry": "after 1% dip, later close > dip bar low; next bar open",
        "exit": "after 1% pop, later close < preceding bar low; next bar open",
        "fallback": "official close; missing cubes counted, never synthesized",
        "last_bar_execution": "official close assumed, not a proved auction fill",
        "selection": "fixed /5 reset intents plus daily grade/membership exits",
        "reset_phases": 20,
        "costs_bps": list(COSTS),
        "funding": "prior-night cash only; no same-day sale reinvestment",
        "start": "2016-01-04",
        "end": "2026-09-30",
        "cash_yield": 0.0,
        "live_parity": False,
        "adoption_eligible": False,
    }


# Choose a signal using only completed bars in the supplied prefix.
def signal_slot(opens, lows, closes, side, arm):
    if side not in ("buy", "sell") or arm not in ARMS:
        raise ValueError("declared side and timing arm required")
    opens, lows, closes = (np.asarray(x, dtype=float) for x in (opens, lows, closes))
    if (
        opens.ndim != 1
        or not 1 <= len(opens) <= 26
        or lows.shape != opens.shape
        or closes.shape != opens.shape
        or not all(
            np.isfinite(x).all() and (x > 0).all() for x in (opens, lows, closes)
        )
        or np.any(lows > closes)
        or np.any(lows > opens)
    ):
        raise ValueError("valid completed regular-bar prefix required")
    level = opens[0] * (0.99 if side == "buy" else 1.01)
    crossings = np.flatnonzero(closes <= level if side == "buy" else closes >= level)
    if not len(crossings):
        return None
    trigger = int(crossings[0])
    if (arm, side) not in ((ENTRY, "buy"), (EXIT, "sell")):
        return trigger
    for slot in range(trigger + 1, len(closes)):
        confirmed = (
            closes[slot] > lows[trigger]
            if side == "buy"
            else closes[slot] < lows[slot - 1]
        )
        if confirmed:
            return slot
    return None


# Read existing cubes verbatim without invoking their rebuilding cache loader.
def read_cubes(directory, symbols):
    cubes, hashes = {}, {}
    for symbol in symbols:
        path = Path(directory) / f"{symbol}.npz"
        if not path.exists():
            continue
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with np.load(path, allow_pickle=False) as data:
            if str(data["key"][-1]) != "2":
                raise ValueError(f"unsupported cube version: {symbol}")
            cubes[symbol] = SessionCube(
                symbol,
                data["dates"].astype("datetime64[D]"),
                *(
                    data[key].copy()
                    for key in ("open", "high", "low", "close", "volume")
                ),
                data["prior_close"].copy(),
                dict(
                    zip(
                        data["excluded_reasons"].astype(str),
                        data["excluded_counts"].astype(int),
                        strict=True,
                    )
                ),
                data["auction_open"].copy(),
                data["auction_volume"].copy(),
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise ValueError(f"cube changed while reading: {symbol}")
        hashes[str(path)] = before
    return cubes, hashes


# Align all timing arms to identical complete raw sessions and adjusted units.
def grids(panel, cubes):
    shape = panel.adj_close.shape
    result = {
        arm: {
            "buy": panel.adj_close.copy(),
            "sell": panel.adj_close.copy(),
            "buy_slot": np.full(shape, 26, dtype=int),
            "sell_slot": np.full(shape, 26, dtype=int),
        }
        for arm in ARMS
    }
    available = np.zeros(shape, dtype=bool)
    for col, symbol in enumerate(panel.tickers):
        cube = cubes.get(symbol)
        if cube is None or not len(cube):
            continue
        if (
            cube.dates.ndim != 1
            or np.isnat(cube.dates).any()
            or np.any(cube.dates[1:] <= cube.dates[:-1])
            or any(
                x.shape != (len(cube), 26)
                for x in (cube.open, cube.high, cube.low, cube.close)
            )
        ):
            raise ValueError(f"invalid cube grid: {symbol}")
        positions, matched, scale = fill_timing.session_scale(
            cube, panel.dates, panel.adj_close[:, col]
        )
        for raw in np.flatnonzero(matched):
            day = positions[raw]
            prices = (cube.open[raw], cube.high[raw], cube.low[raw], cube.close[raw])
            if (
                not all(np.isfinite(x).all() and (x > 0).all() for x in prices)
                or np.any(cube.low[raw] > np.minimum(cube.open[raw], cube.close[raw]))
                or np.any(cube.high[raw] < np.maximum(cube.open[raw], cube.close[raw]))
                or not np.isfinite(scale[raw])
                or scale[raw] <= 0
            ):
                continue
            available[day, col] = True
            for arm in ARMS:
                for side in ("buy", "sell"):
                    signal = signal_slot(
                        cube.open[raw], cube.low[raw], cube.close[raw], side, arm
                    )
                    if signal is not None and signal < 25:
                        slot = signal + 1
                        result[arm][side][day, col] = cube.open[raw, slot] * scale[raw]
                        result[arm][side + "_slot"][day, col] = slot
    return result, available


# Fill one chronological batch while reserving sale proceeds from entry funding.
def fill_batch(book, ending, prices, day, budget):
    before_units, before_cash = book.shares.copy(), book.cash
    holdback = max(0.0, book.cash - budget)
    book.cash -= holdback
    book._fill(ending, prices, recycle_sells=False, session=day)
    book.cash += holdback
    bought = np.maximum(book.shares - before_units, 0.0)
    spent = float(np.nansum(bought * prices)) * (1 + book.cost)
    if book.cash < -1e-12 or np.any(book.shares < 0) or spent > budget + 1e-9:
        raise ValueError("funded ledger violated cash or long-only bounds")
    return max(0.0, budget - spent), before_cash - book.cash


# Price close-sized intents chronologically with one continuous funded account.
def account(panel, grades, eligible, grid, available, *, first, phase, cost, line):
    names, rows = len(panel.tickers), len(panel.dates)
    book = simulate._Book(names, 1.0, cost, panel, None, None)
    nav, cash, turnover, fees = (np.zeros(rows - first) for _ in range(4))
    nav[0] = cash[0] = 1.0
    base = np.zeros(names)
    orders = unavailable = unfilled = changed = 0
    for day in range(first, rows - 1):
        reset = day >= first + phase and (day - first - phase) % 20 == 0
        before_nav = book.equity(panel.adj_close[day])
        if line in ("SPY", "QQQ"):
            target = np.zeros(names)
            target[panel.tickers.index(line)] = 1.0
            intended = (
                book.plan(target, panel.adj_close[day])
                if day == first
                else book.shares.copy()
            )
        else:
            if reset:
                base = policy_v5.targets(
                    grades[day],
                    panel.adj_close[day],
                    eligible[day],
                    panel.tickers.index("SPY"),
                )
            else:
                base = np.where(eligible[day] & (grades[day] >= 2), base, 0.0)
            if reset:
                intended = book.plan(base, panel.adj_close[day])
            else:
                intended = np.where(base > 0, book.shares, 0.0)
        move = intended - book.shares
        selected = np.flatnonzero(np.abs(move) > 1e-12)
        orders += len(selected)
        fill_day = day + 1
        budget = book.cash
        traded_before = book.traded
        slots = np.full(names, -1, dtype=int)
        prices = np.full(names, np.nan)
        for col in selected:
            side = "buy" if move[col] > 0 else "sell"
            if line in ("SPY", "QQQ"):
                prices[col] = (
                    panel.open[fill_day, col]
                    * panel.adj_close[fill_day, col]
                    / panel.close[fill_day, col]
                )
                slots[col] = 0
            else:
                prices[col] = grid[side][fill_day, col]
                slots[col] = grid[side + "_slot"][fill_day, col]
                unavailable += int(not available[fill_day, col])
        for slot in sorted(set(slots[selected])):
            batch = selected[slots[selected] == slot]
            ending = book.shares.copy()
            ending[batch] = intended[batch]
            marks = np.full(names, np.nan)
            marks[batch] = prices[batch]
            before_units = book.shares.copy()
            budget, _ = fill_batch(book, ending, marks, fill_day, budget)
            if slot < 26:
                changed += int(
                    np.count_nonzero(
                        np.abs(book.shares[batch] - before_units[batch]) > 1e-12
                    )
                )
        unfilled += int(
            np.count_nonzero(np.abs(book.shares[selected] - intended[selected]) > 1e-10)
        )
        offset = fill_day - first
        nav[offset] = book.equity(panel.adj_close[fill_day])
        cash[offset] = book.cash
        turnover[offset] = (book.traded - traded_before) / before_nav
        fees[offset] = (book.traded - traded_before) * book.cost
    return {
        "dates": panel.dates[first:],
        "nav": nav,
        "cash": cash,
        "turnover": turnover,
        "fees": fees,
        "opportunities": orders,
        "missing_cube_close_fallbacks": unavailable,
        "unfilled_or_cash_scaled": unfilled,
        "intraday_fills": changed,
    }


# Evaluate both fixed candidates and benchmark accounts without a parameter search.
def backtest(panel, grades, eligible, provenance, cubes):
    panel, grades, eligible = validate(panel, grades, eligible, provenance)
    last = int(np.searchsorted(panel.dates, np.datetime64("2026-09-30"), side="right"))
    panel.dates, grades, eligible = panel.dates[:last], grades[:last], eligible[:last]
    for key in ("open", "close", "adj_close"):
        setattr(panel, key, getattr(panel, key)[:last])
    first = int(np.searchsorted(panel.dates, np.datetime64("2016-01-04")))
    if first >= len(panel.dates) - 1:
        raise ValueError("fixed evaluation window unavailable")
    price_grids, available = grids(panel, cubes)
    output = []
    for cost in COSTS:
        benchmarks = {
            line: account(
                panel,
                grades,
                eligible,
                None,
                available,
                first=first,
                phase=0,
                cost=cost,
                line=line,
            )
            for line in ("SPY", "QQQ")
        }
        phases = []
        for phase in range(20):
            accounts = {
                arm: account(
                    panel,
                    grades,
                    eligible,
                    price_grids[arm],
                    available,
                    first=first,
                    phase=phase,
                    cost=cost,
                    line=arm,
                )
                for arm in ARMS
            }
            reference = {CONTROL: accounts[CONTROL], **benchmarks}
            phases.append(
                {
                    "phase": phase,
                    "results": [
                        {
                            "line": arm,
                            **summarize(accounts[arm], reference),
                            "mean_exposure": float(
                                np.mean(
                                    1 - accounts[arm]["cash"] / accounts[arm]["nav"]
                                )
                            ),
                            **{
                                key: accounts[arm][key]
                                for key in (
                                    "opportunities",
                                    "missing_cube_close_fallbacks",
                                    "unfilled_or_cash_scaled",
                                    "intraday_fills",
                                )
                            },
                        }
                        for arm in ARMS
                    ],
                }
            )
        output.append(
            {
                "cost_bps": cost,
                "phases": phases,
                "benchmarks": [
                    {"line": line, **summarize(value, {})}
                    for line, value in benchmarks.items()
                ],
            }
        )
    return {
        "specification": specification(),
        "provenance": provenance,
        "costs": output,
        "adoption_eligible": False,
    }
