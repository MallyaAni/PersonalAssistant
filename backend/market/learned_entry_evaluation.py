"""Read-only learned-policy replay on a continuously carried, funded account.

The fixed 1% control is a conditional price-component reconstruction, not a
broker auction replay or exact historical live-policy claim. Every phase is
reported; no favorable phase, regime or parameter is selected afterwards.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.agents.trading.desk.simulate import _Book
from backend.market.allocation_evaluation import metrics
from backend.market.fill_timing import session_scale
from backend.market.learned_entry_policy import decide
from backend.market.sip_cube import SessionCube


# Load original v2 cube bytes without invoking any cache builder or source write.
def read_cubes(directory, tickers):
    cubes, evidence = {}, {}
    for ticker in tickers:
        path = Path(directory) / f"{ticker}.npz"
        if not path.exists():
            evidence[ticker] = {"status": "missing"}
            continue
        raw = path.read_bytes()
        with np.load(io.BytesIO(raw), allow_pickle=False) as z:
            if "key" not in z.files or str(z["key"][-1]) != "2":
                raise ValueError(f"unsupported original cube version: {ticker}")
            dates = z["dates"].astype("datetime64[D]")
            if np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
                raise ValueError(f"ambiguous cube calendar: {ticker}")
            arrays = {key: z[key] for key in ("open", "high", "low", "close", "volume")}
            if any(a.shape != (len(dates), 26) for a in arrays.values()):
                raise ValueError(f"incorrect cube grid: {ticker}")
            excluded = dict(
                zip(
                    z["excluded_reasons"].tolist(),
                    z["excluded_counts"].astype(int).tolist(),
                    strict=True,
                )
            )
            cubes[ticker] = SessionCube(
                ticker,
                dates,
                **arrays,
                prior_close=z["prior_close"],
                excluded=excluded,
                auction_open=z["auction_open"],
                auction_volume=z["auction_volume"],
            )
        evidence[ticker] = {
            "status": "original",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "sessions": len(dates),
            "excluded": excluded,
        }
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence[ticker]["sha256"]:
            raise ValueError(f"source changed while reading: {ticker}")
    return cubes, evidence


# Fill from the morning cash budget while holding all same-day sale proceeds back.
def funded_fill(book, wanted, prices, budget, day, phase):
    if budget < -1e-9 or budget > book.cash + 1e-9:
        raise ValueError("invalid remaining morning cash budget")
    before = book.shares.copy()
    reserved = max(0.0, book.cash - budget)
    book.cash -= reserved
    book._fill(wanted, prices, recycle_sells=False, session=day, phase=phase)
    book.cash += reserved
    delta = book.shares - before
    dollars = delta * np.where(np.isfinite(prices), prices, 0)
    spend = float(np.maximum(dollars, 0).sum()) * (1 + book.cost)
    remaining = max(0.0, budget - spend)
    fees = float(np.abs(dollars).sum()) * book.cost
    if book.cash < -1e-10 or np.any(book.shares < -1e-10):
        raise RuntimeError("funding or covered-sale invariant failed")
    return remaining, dollars, fees


# Allocate a complete continuous daily evidence trace with a real initial NAV slot.
def account_arrays(panel, first):
    days = len(panel.dates) - first
    return {
        "dates": panel.dates[first - 1 :].copy(),
        "nav": np.full(days + 1, np.nan),
        "cash": np.full(days + 1, np.nan),
        "exposure": np.full(days + 1, np.nan),
        "turnover": np.zeros(days + 1),
        "fees": np.zeros(days + 1),
    }


# Price every learned decision only after its completed bar using the shared ledger.
def learned_account(panel, dataset, forecasts, first, cost_bps):
    n = len(panel.tickers)
    book = _Book(n, 1, cost_bps, panel, None, None)
    result = account_arrays(panel, first)
    result["nav"][0] = result["cash"][0] = 1
    result["exposure"][0] = 0
    cashflows = np.zeros(n)
    counts = {
        "decisions": 0,
        "waiting": 0,
        "unknown": 0,
        "missing_execution": 0,
        "missing_held_observation": 0,
        "inconsistent_moments": 0,
        "fills": 0,
        "cash_limited_attempts": 0,
    }
    trades_by_stock = np.zeros(n, dtype=int)
    for day in range(first, len(panel.dates)):
        budget = book.cash
        row = day - first + 1
        for clock in range(25):
            observed = dataset["current_close"][day, clock]
            if np.any((book.shares > 0) & (~np.isfinite(observed) | (observed <= 0))):
                counts["missing_held_observation"] += 1
                continue
            nav = book.equity(observed)
            current = book.shares * np.where(np.isfinite(observed), observed, 0) / nav
            may_add = dataset["prior_eligible"][day] & (
                dataset["prior_grades"][day] >= 2
            )
            if day < 253:
                continue
            target, detail = decide(
                forecasts[day, clock],
                panel.adj_close[day - 253 : day],
                current,
                may_add,
                cost_bps,
            )
            counts["decisions"] += 1
            for name in ("waiting", "unknown", "inconsistent_moments"):
                counts[name] += detail.get(name, 0)
            if detail["status"] != "decided":
                continue
            wanted = book.shares.copy()
            known = np.isfinite(observed) & (observed > 0)
            wanted[known] = target[known] * nav / observed[known]
            move = np.abs(wanted - book.shares) > 1e-10
            prices = dataset["next_open"][day, clock]
            counts["missing_execution"] += int(
                (move & (~np.isfinite(prices) | (prices <= 0))).sum()
            )
            budget, dollars, fees = funded_fill(
                book, wanted, prices, budget, day, f"completed_bar_{clock}"
            )
            actual = np.abs(dollars) > 1e-12
            priced = np.isfinite(prices) & (prices > 0)
            counts["cash_limited_attempts"] += int(
                ((wanted > book.shares + 1e-10) & priced).sum()
            )
            counts["fills"] += int(actual.sum())
            trades_by_stock += actual
            cashflows -= dollars + np.abs(dollars) * book.cost
            result["turnover"][row] += float(np.abs(dollars).sum()) / nav
            result["fees"][row] += fees
        result["nav"][row] = book.equity(panel.adj_close[day])
        result["cash"][row] = book.cash
        result["exposure"][row] = 1 - book.cash / result["nav"][row]
    contribution = cashflows + book.shares * np.where(
        np.isfinite(panel.adj_close[-1]), panel.adj_close[-1], 0
    )
    if not np.isclose(contribution.sum(), result["nav"][-1] - 1, atol=1e-8):
        raise RuntimeError("per-stock gain does not reconcile to account wealth")
    result["counts"] = counts
    result["stocks"] = {
        ticker: {
            "net_gain_initial_nav_units": float(contribution[j]),
            "fills": int(trades_by_stock[j]),
        }
        for j, ticker in enumerate(panel.tickers)
    }
    return result


# Construct the frozen dip/pop control without looking past its closing submission.
def control_prices(panel, cubes):
    shape = panel.adj_close.shape
    buy, sell = np.full(shape, np.nan), np.full(shape, np.nan)
    clock_buy, clock_sell = np.full(shape, -1, dtype=int), np.full(shape, -1, dtype=int)
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None:
            continue
        pos, matched, scale = session_scale(cube, panel.dates, panel.adj_close[:, j])
        for i in np.flatnonzero(matched & np.isfinite(scale) & (scale > 0)):
            if not np.isfinite(cube.open[i, 0]) or cube.open[i, 0] <= 0:
                continue
            for side, out, clocks in ((1, buy, clock_buy), (-1, sell, clock_sell)):
                closes = cube.close[i, :24]
                triggered = (
                    closes <= cube.open[i, 0] * 0.99
                    if side == 1
                    else closes >= cube.open[i, 0] * 1.01
                )
                hits = np.flatnonzero(triggered & np.isfinite(closes) & (closes > 0))
                if len(hits):
                    k = int(hits[0]) + 1
                    price = cube.open[i, k]
                else:
                    k = 26
                    # Only an observed auction print supports the close proxy.
                    price = cube.auction_open[i]
                if np.isfinite(price) and price > 0:
                    out[pos[i], j] = price * scale[i]
                    clocks[pos[i], j] = k
    return buy, sell, clock_buy, clock_sell


# Replay each declared control phase on the same start, funding and missing-data basis.
def control_account(panel, grades, eligible, prices, first, cost_bps, offset):
    book = _Book(len(panel.tickers), 1, cost_bps, panel, None, None)
    result = account_arrays(panel, first)
    result["nav"][0] = result["cash"][0] = 1
    result["exposure"][0] = 0
    buy, sell, buy_clock, sell_clock = prices
    missed, filled, cash_limited = 0, 0, 0
    for day in range(first, len(panel.dates)):
        row = day - first + 1
        if (day - first) % 20 == offset:
            observed = panel.adj_close[day - 1]
            target = policy_v5.targets(
                grades[day - 1], observed, eligible[day - 1], panel.tickers.index("SPY")
            )
            nav = book.equity(observed)
            wanted = np.zeros(len(panel.tickers))
            known = np.isfinite(observed) & (observed > 0)
            wanted[known] = target[known] * nav / observed[known]
            wanted[~known] = book.shares[~known]
            delta = wanted - book.shares
            execution = np.where(delta >= 0, buy[day], sell[day])
            clocks = np.where(delta >= 0, buy_clock[day], sell_clock[day])
            missed += int(((np.abs(delta) > 1e-10) & (clocks < 0)).sum())
            budget = book.cash
            for clock in range(1, 27):
                request = np.where(clocks == clock, wanted, book.shares)
                budget, dollars, fees = funded_fill(
                    book, request, execution, budget, day, f"control_clock_{clock}"
                )
                result["fees"][row] += fees
                result["turnover"][row] += float(np.abs(dollars).sum()) / nav
                filled += int((np.abs(dollars) > 1e-12).sum())
                cash_limited += int(
                    (
                        (request > book.shares + 1e-10)
                        & np.isfinite(execution)
                        & (execution > 0)
                    ).sum()
                )
        result["nav"][row] = book.equity(panel.adj_close[day])
        result["cash"][row] = book.cash
        result["exposure"][row] = 1 - book.cash / result["nav"][row]
    result["counts"] = {
        "missing_execution": missed,
        "fills": filled,
        "cash_limited_attempts": cash_limited,
    }
    return result


# Fund a benchmark once at the same start and retain its total-return adjusted shares.
def benchmark_account(panel, first, cost_bps, ticker):
    col = panel.tickers.index(ticker)
    opens = panel.open[:, col] * panel.adj_close[:, col] / panel.close[:, col]
    if not np.isfinite(opens[first]) or opens[first] <= 0:
        raise ValueError("missing common benchmark entry")
    shares = 1 / (opens[first] * (1 + cost_bps / 1e4))
    values = panel.adj_close[first:, col]
    if not np.isfinite(values).all():
        raise ValueError("missing carried benchmark marks")
    result = account_arrays(panel, first)
    result["nav"] = np.r_[1, values * shares]
    result["cash"][:] = 0
    result["cash"][0] = 1
    result["exposure"][:] = 1
    result["exposure"][0] = 0
    result["fees"][1] = 1 - shares * opens[first]
    result["turnover"][1] = shares * opens[first]
    return result


# Report compounded contiguous windows and non-compounded causal regime diagnostics.
def score(account, references, spy_close):
    dates = account["dates"][1:]
    returns = account["nav"][1:] / account["nav"][:-1] - 1
    windows = []
    for name, start, end in (
        ("all", "1900-01-01", "2100-01-01"),
        ("2016-20", "2016-01-01", "2021-01-01"),
        ("2021-26", "2021-01-01", "2027-01-01"),
        ("frozen_holdout", "2026-08-17", "2026-10-01"),
    ):
        keep = (dates >= np.datetime64(start)) & (dates < np.datetime64(end))
        if not keep.any():
            windows.append({"window": name, "status": "unavailable", "sessions": 0})
            continue
        stats = metrics(returns[keep])
        windows.append(
            {
                "window": name,
                "status": "measured",
                "start": str(dates[keep][0]),
                "end": str(dates[keep][-1]),
                "sessions": int(keep.sum()),
                "total_net_gain": stats["total"],
                "cagr": stats["annual"],
                "max_drawdown_loss": stats["drawdown"],
                "sharpe": stats["sharpe"],
                "average_exposure": float(np.mean(account["exposure"][1:][keep])),
                "turnover_one_way": float(account["turnover"][1:][keep].sum()),
                "fees_initial_nav_units": float(account["fees"][1:][keep].sum()),
            }
        )
    rolling = {}
    if len(returns) >= 252:
        own = account["nav"][252:] / account["nav"][:-252]
        for name, ref in references.items():
            other = ref["nav"][252:] / ref["nav"][:-252]
            rolling[name] = {
                "windows": len(own),
                "win_rate": float(np.mean(own > other)),
            }
    regimes = []
    spy_close = np.asarray(spy_close)
    for trend in (False, True):
        for volatile in (False, True):
            keep = np.zeros(len(returns), dtype=bool)
            for i in range(len(returns)):
                # Row i's return uses only the market history preceding that date.
                end = len(spy_close) - len(returns) + i
                if end < 252:
                    continue
                prior = spy_close[end - 252 : end]
                up = prior[-1] > np.mean(prior[-200:])
                daily = np.diff(np.log(prior))
                high = np.std(daily[-20:]) > np.std(daily)
                keep[i] = up == trend and high == volatile
            regimes.append(
                {
                    "trend_up": trend,
                    "vol_above_trailing_year": volatile,
                    "sessions": int(keep.sum()),
                    "mean_net_return": float(np.mean(returns[keep]))
                    if keep.any()
                    else None,
                    "mean_excess": {
                        name: float(
                            np.mean(
                                (returns - (ref["nav"][1:] / ref["nav"][:-1] - 1))[keep]
                            )
                        )
                        if keep.any()
                        else None
                        for name, ref in references.items()
                    },
                }
            )
    return {
        "windows": windows,
        "rolling_252": rolling,
        "regime_diagnostics": regimes,
        "counts": account.get("counts", {}),
        "stocks": account.get("stocks", {}),
    }
