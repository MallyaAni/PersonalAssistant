"""Funded candle-path timing research, separate from broker shares and live policy.

One-share permissions probe prices only. The existing ledger executes the
actual adjusted research units, with one session cash budget and no sale
recycling, retry, shorting or invented fills. Raw-to-adjusted scaling belongs
only to economic labels after the permission has been established.
"""

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, time
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import policy_v5, simulate
from backend.market import open_source_forecast_evaluation as frozen
from backend.market import open_source_forecasts as forecasts
from backend.market import specialist_timing as timing
from backend.market.allocation_controls import adjusted_open

SESSIONS = ("2026-09-04", "2026-09-21")
LINES = ("next-open", "available-permission-first-open", "kronos-path")


# Authenticate bytes before reading a supplied cache or model record.
def checked_json(path, expected=None):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError("Timing evidence bytes changed")
    return json.loads(raw), digest


# Authenticate the full timing cohort and its separate causal and outcome sources.
def load_cases(  # noqa: C901 - preserve explicit source identity refusals
    manifest_path, paths_path, basis_path
):
    manifest, manifest_hash = checked_json(manifest_path)
    artifact, artifact_hash = checked_json(paths_path)
    basis, basis_hash = checked_json(basis_path)
    if (
        artifact.get("manifest_sha256") != manifest_hash
        or basis.get("manifest_sha256") != manifest_hash
        or artifact.get("basis_sha256") != basis_hash
    ):
        raise ValueError("Timing source manifest identity mismatch")
    if (
        artifact.get("version") != timing.VERSION
        or artifact.get("price_basis") != "raw"
        or artifact.get("target") != "remaining_regular_ohlcv_path"
    ):
        raise ValueError("Frozen raw path protocol required")
    if artifact.get("checkpoint") != asdict(forecasts.CHECKPOINTS["kronos"]):
        raise ValueError("Pinned Kronos checkpoint required")
    if (
        artifact.get("runtime", {}).get("kronos_source_revision")
        != forecasts.CODE_REVISIONS["kronos"]
    ):
        raise ValueError("Pinned Kronos source required")
    if artifact.get("device") != "cpu" or artifact.get("seeds") != list(timing.SEEDS):
        raise ValueError("CPU eight-path seed contract required")
    expected = {(day, symbol) for day in SESSIONS for symbol in frozen.COHORT}
    predictions = {}
    for row in artifact["records"]:
        key = (row["session"], row["symbol"])
        if key in predictions or key not in expected:
            raise ValueError("Duplicate or unexpected timing forecast")
        if row.get("status") not in ("forecast", "unavailable") or (
            row["status"] == "unavailable" and not row.get("reason")
        ):
            raise ValueError("Declared timing status and unavailable reason required")
        if row.get("paths") is not None and row.get("path_sha256") != timing.digest(
            row["paths"]
        ):
            raise ValueError("Native path identity mismatch")
        predictions[key] = row
    if set(predictions) != expected:
        raise ValueError("All 24 timing opportunities required")
    sources, economics = {}, {}
    for row in manifest["records"]:
        key = (row["session"], row["symbol"])
        if key in sources:
            raise ValueError("Duplicate timing source")
        sources[key] = row
    for row in basis["records"]:
        key = (row["session"], row["symbol"])
        if key in economics:
            raise ValueError("Duplicate timing economic label")
        if row.get("decision_input") is not False:
            raise ValueError("Execution adjustment must be label-only")
        economics[key] = row
    cases = {}
    for key in sorted(expected):
        source, prediction = sources.get(key), predictions[key]
        if source is None:
            raise ValueError("Missing timing source declaration")
        result = {"status": prediction["status"], "reason": prediction.get("reason")}
        if source["status"] == "prepared":
            payload, _ = checked_json(source["prefix_path"], source["prefix_sha256"])
            prepared = timing.prepare(payload)
            if prepared["context_sha256"] != source["context_sha256"]:
                raise ValueError("Timing prefix identity mismatch")
            if prediction.get("context_sha256") != prepared["context_sha256"]:
                raise ValueError("Timing forecast input identity mismatch")
            future, _ = checked_json(
                source["execution_path"], source["execution_sha256"]
            )
            if (
                (payload["session"], payload["symbol"]) != key
                or (future["session"], future["symbol"]) != key
                or future.get("price_basis") != "raw"
            ):
                raise ValueError("Timing partition identity mismatch")
            result.update(
                prepared=prepared,
                future=future["bars"],
                paths=prediction.get("paths"),
                basis=economics.get(key),
            )
        elif prediction["status"] == "forecast":
            raise ValueError("Forecast on unavailable timing prefix")
        cases[key] = result
    return cases, {
        "manifest_sha256": manifest_hash,
        "paths_sha256": artifact_hash,
        "execution_basis_sha256": basis_hash,
        "requested": 24,
        "original_publication": "unknown",
        "later_vintage": True,
    }


# Observe the first consecutive open strictly after a causal permission exists.
def first_open(prepared, future):
    indexed = timing.execution_rows(
        future, [timing.aware(at) for at in prepared["future_starts"]]
    )
    observed = timing.aware(prepared["observed_at"])
    for stamp in prepared["future_starts"]:
        at = timing.aware(stamp)
        rows = indexed.get(at, [])
        if len(rows) != 1:
            return {
                "status": "unavailable",
                "reason": "missing_or_duplicate_consecutive_open",
            }
        row = rows[0]
        if timing.aware(row["available_at"]) < at + timing.BAR or timing.aware(
            row["available_at"]
        ) > timing.aware(prepared["expires_at"]):
            return {"status": "unavailable", "reason": "unavailable_consecutive_bar"}
        opening, _, _, _, _ = timing.values(row)
        if at > observed:
            return {
                "status": "opportunity",
                "proxy_price": opening,
                "proxy_at": at.isoformat(),
                "convention": "first-strictly-later-open-after-permission",
                "fill_proof": False,
            }
    return {"status": "unavailable", "reason": "no_later_open"}


# Establish a causal permission before converting outcome prices to economic units.
def opportunity(case, symbol, session, side, decision, adjusted_close, *, first=False):
    if case["status"] != "forecast":
        return {
            "status": "unavailable",
            "reason": case.get("reason") or case["status"],
            "causal_permission_available": False,
        }
    intent = {
        "symbol": symbol,
        "session": session,
        "side": side,
        "qty": 1,
        "created_at": datetime.combine(
            date.fromisoformat(decision), time(16), forecasts.NY
        ).isoformat(),
        "client_order_id": f"price-probe:{decision}:{symbol}:{side}",
    }
    try:
        order = timing.permission(case["prepared"], intent, case["paths"])
    except ValueError as exc:
        return {
            "status": "unavailable",
            "reason": str(exc),
            "causal_permission_available": False,
        }
    try:
        price = (
            first_open(case["prepared"], case["future"])
            if first and order["status"] == "resting"
            else timing.price_opportunity(
                order, case["future"], data_as_of=case["prepared"]["expires_at"]
            )
        )
    except ValueError as exc:
        price = {"status": "unavailable", "reason": str(exc)}
    result = {
        **price,
        "permission_sha256": order["permission_sha256"],
        "causal_permission_available": order["status"] == "resting",
        "unit_probe_not_trade_quantity": True,
    }
    if price["status"] != "opportunity":
        return result
    label = case.get("basis")
    if (
        not label
        or label.get("status") != "available"
        or label.get("decision_input") is not False
    ):
        return {
            **result,
            "status": "unavailable",
            "reason": "missing_label_only_execution_basis",
        }
    raw_close = label.get("official_close")
    if (
        isinstance(raw_close, bool)
        or not isinstance(raw_close, (int, float))
        or not np.isfinite(raw_close)
        or raw_close <= 0
    ):
        return {
            **result,
            "status": "unavailable",
            "reason": "missing_raw_official_close",
        }
    scale = float(adjusted_close / raw_close)
    return {
        **result,
        "adjusted_proxy_price": float(price["proxy_price"] * scale),
        "economic_label_scale": scale,
        "fill_proof": False,
    }


# Fill in time order without using later prices or recycling session sale proceeds.
def chronological_fills(book, target, events, *, session, line):
    budget = float(book.cash)
    before = book.shares.copy()
    for at in sorted(events, key=timing.aware):
        prices = np.full(len(book.shares), np.nan)
        submitted = book.shares.copy()
        for j, price in events[at]:
            prices[j], submitted[j] = price, target[j]
        reserve = book.cash - budget
        if reserve < -1e-12:
            raise ValueError("Timing cash budget exceeded")
        old_units = book.shares.copy()
        book.cash = max(0.0, budget)
        book._fill(submitted, prices, recycle_sells=False, session=session, phase=line)
        bought = np.maximum(book.shares - old_units, 0)
        spent = float((bought * np.nan_to_num(prices, nan=0)).sum()) * (1 + book.cost)
        budget = max(0.0, budget - spent)
        book.cash += max(0.0, reserve)
    return book.shares - before


# Replay common prior-close targets while retaining missed or failed permissions.
def account(  # noqa: C901 - retain explicit plan, fill and mark order
    panel, grades, eligible, cases, *, line, cost_bps
):
    if line not in LINES:
        raise ValueError("Unknown timing line")
    expected = {(day, symbol) for day in SESSIONS for symbol in frozen.COHORT}
    if set(cases) != expected or tuple(panel.tickers) != frozen.COHORT:
        raise ValueError("The complete fixed timing cohort is required")
    closes = np.asarray(panel.adj_close, dtype=float)
    opens = adjusted_open(panel.open, panel.close, panel.adj_close)
    if (
        not np.isfinite(closes).all()
        or np.any(closes <= 0)
        or not np.isfinite(opens).all()
        or np.any(opens <= 0)
    ):
        raise ValueError("Complete common economic marks required")
    _, holidays = timing.calendar.reviewed_sessions()
    dates = np.arange(
        np.datetime64(frozen.START),
        np.datetime64(frozen.END) + np.timedelta64(1, "D"),
        dtype="datetime64[D]",
    )
    expected_dates = dates[np.is_busday(dates, busdaycal=holidays)]
    if not np.array_equal(panel.dates, expected_dates):
        raise ValueError("Fixed timing calendar required")
    if isinstance(cost_bps, bool) or cost_bps not in frozen.COSTS:
        raise ValueError("Fixed nonnegative timing costs required")
    book = simulate._Book(len(panel.tickers), 1, cost_bps, panel, None, None)
    nav, cash = np.ones(len(panel.dates)), np.ones(len(panel.dates))
    fees, turnover = np.zeros(len(nav)), np.zeros(len(nav))
    positions = np.zeros_like(closes)
    receipts = []
    for t in range(len(nav) - 1):
        before_nav = book.equity(closes[t])
        if t % 10 == 0:
            decision, session = str(panel.dates[t]), str(panel.dates[t + 1])
            if session not in SESSIONS:
                raise ValueError("Fixed global timing cadence changed")
            weights = policy_v5.targets(
                grades[t], closes[t], eligible[t], frozen.COHORT.index("SPY")
            )
            target = weights * before_nav / closes[t]
            events = {}
            batch_rows = []
            for j, symbol in enumerate(panel.tickers):
                delta = float(target[j] - book.shares[j])
                row = {
                    "symbol": symbol,
                    "decision": decision,
                    "session": session,
                    "planned_delta_adjusted_units": delta,
                    "status": "no_intent",
                }
                if abs(delta) > 1e-14:
                    if line == "next-open":
                        at = datetime.combine(
                            date.fromisoformat(session), time(9, 30), forecasts.NY
                        ).isoformat()
                        events.setdefault(at, []).append((j, opens[t + 1, j]))
                        row.update(
                            status="next-open-control",
                            proxy_at=at,
                            model_inputs_used=False,
                        )
                        batch_rows.append(row)
                        continue
                    probe = opportunity(
                        cases[session, symbol],
                        symbol,
                        session,
                        "buy" if delta > 0 else "sell",
                        decision,
                        closes[t + 1, j],
                        first=line == "available-permission-first-open",
                    )
                    row.update(probe)
                    if probe["status"] == "opportunity":
                        events.setdefault(probe["proxy_at"], []).append(
                            (j, probe["adjusted_proxy_price"])
                        )
                batch_rows.append(row)
            before = book.shares.copy()
            traded = book.traded
            chronological_fills(book, target, events, session=t + 1, line=line)
            fees[t + 1] = (book.traded - traded) * book.cost
            turnover[t + 1] = (book.traded - traded) / before_nav
            for j, row in enumerate(batch_rows):
                row["executed_adjusted_units"] = float(book.shares[j] - before[j])
                row["funded_status"] = (
                    "no_intent"
                    if abs(row["planned_delta_adjusted_units"]) <= 1e-14
                    else "filled"
                    if abs(
                        row["executed_adjusted_units"]
                        - row["planned_delta_adjusted_units"]
                    )
                    <= 1e-12
                    else (
                        "partial"
                        if abs(row["executed_adjusted_units"]) > 1e-14
                        else "unfilled"
                    )
                )
            receipts.extend(batch_rows)
        nav[t + 1], cash[t + 1] = book.equity(closes[t + 1]), book.cash
        positions[t + 1] = book.shares
        if (
            not np.isfinite(nav[t + 1])
            or nav[t + 1] <= 0
            or book.cash < 0
            or np.any(book.shares < 0)
        ):
            raise ValueError("Invalid funded timing account")
    return {
        "dates": panel.dates.copy(),
        "nav": nav,
        "cash": cash,
        "cash_fraction": cash / nav,
        "positions": positions,
        "fees": fees,
        "turnover": turnover,
        "decisions": receipts,
        "instruction_path": {"sha256": forecasts.digest(receipts)},
        "fill_proof": False,
        "exact_live_strategy": False,
        "no_sale_recycling": True,
        "no_funding_retry": True,
        "research_units": "fractional_adjusted",
        "no_broker_execution": True,
    }
