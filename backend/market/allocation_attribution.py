"""Read-only attribution of frozen allocation intent and funded account outcomes.

This diagnostic verifies retained journals; it never runs a strategy or forecasts
returns. Full close-to-close outcomes include gaps before the next permitted fill.
Grouping those outcomes by intent is descriptive, not causal loss-avoidance proof.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date

from backend.market.research_journal_replay import verify_snapshot

REQUIRED = frozenset({"candidate", "no_gate_adapter", "SPY", "QQQ"})
MODES = ("stock", "SPY", "QQQ", "cash", "mixed", "unknown")
SIGNS = ("positive", "negative", "tie")
ADAPTER = "stock-index-cash-adapter/1-research"
TOLERANCE = 1e-12


# Verify every original journal before comparing its complete reconstructed marks.
def _checked(snapshots, cost_bps):
    if type(cost_bps) not in (int, float) or cost_bps not in (10, 25):
        raise ValueError("cost_bps must be 10 or 25")
    if not isinstance(snapshots, Mapping) or not set(snapshots) >= REQUIRED:
        raise ValueError("candidate, no_gate_adapter, SPY and QQQ journals required")
    if any(not isinstance(name, str) or not name.strip() for name in snapshots):
        raise ValueError("account names must be nonempty strings")
    accounts, reference = {}, None
    for name, snapshot in snapshots.items():
        proof = verify_snapshot(snapshot)
        if not proof["ok"]:
            raise ValueError(f"{name}: journal verification failed: {proof['errors']}")
        if snapshot["manifest"]["cost_bps"] != cost_bps:
            raise ValueError(f"{name}: account costs differ")
        marks = proof["marks"]
        dates = [mark["session"] for mark in marks]
        if len(marks) < 2 or any(
            not math.isfinite(mark["nav"]) or mark["nav"] <= 0 for mark in marks
        ):
            raise ValueError(f"{name}: at least two positive finite NAV marks required")
        if reference is not None and dates != reference:
            raise ValueError(f"{name}: reconstructed mark dates differ; no inner join")
        reference = dates
        accounts[name] = (snapshot, proof)
    if not {"SPY", "QQQ"} <= set(snapshots["candidate"]["manifest"]["symbols"]):
        raise ValueError("candidate symbol grid requires SPY and QQQ")
    return accounts, reference


# Accept only finite nonnegative fractions without coercing missing or Boolean data.
def _fractions(values, count):
    return (
        isinstance(values, list)
        and len(values) == count
        and all(
            type(v) in (int, float) and 0 <= v <= 1 and math.isfinite(v) for v in values
        )
        and math.fsum(values) <= 1 + TOLERANCE
    )


# Aggregate actual symbol values without mistaking an underfilled basket for full stock.
def _sleeves(values, symbols, cash):
    return {
        "stock": math.fsum(
            v for s, v in zip(symbols, values, strict=True) if s not in ("SPY", "QQQ")
        ),
        "SPY": values[symbols.index("SPY")],
        "QQQ": values[symbols.index("QQQ")],
        "cash": cash,
    }


# Recognize supported allocation metadata only when its effective targets agree.
def _instruction(decision, symbols):
    metadata = decision["metadata"]
    instruction = metadata.get("instruction")
    if metadata.get("execution_policy") != ADAPTER or not isinstance(instruction, dict):
        return None
    desired, base = (
        decision["desired_weights"],
        metadata.get("effective_stock_composition"),
    )
    declared = [
        instruction.get(key) for key in ("stock_scale", "spy_weight", "qqq_weight")
    ]
    if not _fractions(desired, len(symbols)) or not _fractions(base, len(symbols)):
        return None
    if not all(
        type(v) in (int, float) and 0 <= v <= 1 and math.isfinite(v) for v in declared
    ):
        return None
    known = instruction.get("information_through")
    try:
        dated = (
            isinstance(known, str) and date.fromisoformat(known).isoformat() == known
        )
    except ValueError:
        dated = False
    if (
        not dated
        or known > decision["session"]
        or instruction.get("session") != decision["session"]
        or not isinstance(instruction.get("evidence_id"), str)
        or not instruction["evidence_id"].strip()
    ):
        return None
    expected = [v * declared[0] for v in base]
    for symbol, weight in zip(("SPY", "QQQ"), declared[1:], strict=True):
        column = symbols.index(symbol)
        if base[column] != 0:
            return None
        expected[column] = weight
    if not all(
        math.isclose(a, b, rel_tol=TOLERANCE, abs_tol=TOLERANCE)
        for a, b in zip(desired, expected, strict=True)
    ):
        return None
    return desired, declared


# Keep absent or ambiguous instructions explicit while retaining every decision id.
def _intent(events, symbols, prior_session):
    decisions = [event for event in events if event["type"] == "decision"]
    result = {
        "mode": "unknown",
        "reason": "missing_instruction",
        "decision_ids": [event["decision_id"] for event in decisions],
        "desired_sleeve_weights": None,
        "declared_sleeves": None,
    }
    if len(decisions) != 1:
        if decisions:
            result["reason"] = "ambiguous_multiple_decisions"
        return result
    if decisions[0]["session"] != prior_session:
        result["reason"] = "instruction_not_at_prior_close"
        return result
    parsed = _instruction(decisions[0], symbols)
    if parsed is None:
        result["reason"] = "unsupported_or_inconsistent_instruction"
        return result
    desired, declared = parsed
    weights = _sleeves(desired, symbols, max(0.0, 1 - math.fsum(desired)))
    active = [name for name in ("stock", "SPY", "QQQ") if weights[name] > 0]
    result.update(
        mode="cash" if not active else active[0] if len(active) == 1 else "mixed",
        reason="effective_desired_weights",
        desired_sleeve_weights=weights,
        declared_sleeves=dict(
            zip(("stock_scale", "spy_weight", "qqq_weight"), declared, strict=True)
        ),
    )
    return result


# Preserve actual batches and residual reasons without inventing a future queue.
def _fills(events):
    fields = (
        "event_id",
        "decision_id",
        "session",
        "phase",
        "filled_units",
        "gross_buys",
        "gross_sells",
        "fee_total",
        "notional",
        "fees",
        "buy_budget",
        "scale",
        "residual_units",
        "unfilled_reasons",
    )
    batches = [
        {key: copy.deepcopy(event[key]) for key in fields}
        for event in events
        if event["type"] == "fill_batch"
    ]
    buys = math.fsum(row["gross_buys"] for row in batches)
    sells = math.fsum(row["gross_sells"] for row in batches)
    return {
        "batches": batches,
        "batch_count": len(batches),
        "gross_buys": buys,
        "gross_sells": sells,
        "notional": buys + sells,
        "fees": math.fsum(row["fee_total"] for row in batches),
        "budget_limited_batches": sum(
            "cash_budget_limited" in row["unfilled_reasons"] for row in batches
        ),
    }


# Value the independently reconstructed holdings at this mark, never at decision time.
def _realized(snapshot, mark):
    symbols = snapshot["manifest"]["symbols"]
    prices = snapshot["prices"]["close"][mark["session_index"]]
    values = [
        units * price / mark["nav"] if units > 0 else 0.0
        for units, price in zip(mark["positions"], prices, strict=True)
    ]
    return _sleeves(values, symbols, mark["cash"] / mark["nav"])


# Compute the complete already-charged interval without subtracting fees again.
def _outcome(before, after):
    growth = math.log(after["nav"]) - math.log(before["nav"])
    net = after["nav"] / before["nav"] - 1
    if not math.isfinite(net):
        raise ValueError("interval return exceeds finite numerical range")
    return {"net_return": net, "log_growth": growth}


# Keep a fixed absolute tie band around zero without estimating a threshold.
def _sign(net_return):
    return (
        "tie"
        if abs(net_return) <= TOLERANCE
        else ("positive" if net_return > 0 else "negative")
    )


# Build one fully dated row from events strictly after one mark through the next.
def _interval(accounts, candidate_marks, offset):
    snapshot, proof = accounts["candidate"]
    before, after = proof["marks"][offset : offset + 2]
    first, last = candidate_marks[offset : offset + 2]
    events = snapshot["events"][first["seq"] + 1 : last["seq"] + 1]
    outcomes = {
        name: _outcome(p["marks"][offset], p["marks"][offset + 1])
        for name, (_, p) in accounts.items()
    }
    return {
        "prior_session": before["session"],
        "following_session": after["session"],
        "intent": _intent(events, snapshot["manifest"]["symbols"], before["session"]),
        "fills": _fills(events),
        "realized_sleeve_weights": {
            "prior_close": _realized(snapshot, before),
            "following_close": _realized(snapshot, after),
        },
        "outcomes": outcomes,
        "comparisons": {
            name: {
                "sign": _sign(value["net_return"]),
                "excess_log_growth": outcomes["candidate"]["log_growth"]
                - value["log_growth"],
            }
            for name, value in outcomes.items()
            if name != "candidate"
        },
    }


# Summarize exhaustive intent and comparator-sign partitions without annualization.
def _groups(intervals, names):
    groups = {}
    for mode in MODES:
        selected = [row for row in intervals if row["intent"]["mode"] == mode]
        signs = {}
        for name in names:
            if name == "candidate":
                continue
            signs[name] = {}
            for sign in SIGNS:
                cells = [
                    row for row in selected if row["comparisons"][name]["sign"] == sign
                ]
                own = math.fsum(
                    row["outcomes"]["candidate"]["log_growth"] for row in cells
                )
                other = math.fsum(row["outcomes"][name]["log_growth"] for row in cells)
                signs[name][sign] = {
                    "return_intervals": len(cells),
                    "candidate_log_growth": own,
                    "comparator_log_growth": other,
                    "excess_log_growth": own - other,
                }
        groups[mode] = {
            "return_intervals": len(selected),
            "log_growth_by_account": {
                name: math.fsum(row["outcomes"][name]["log_growth"] for row in selected)
                for name in names
            },
            "by_comparator_sign": signs,
        }
    return groups


# Reconcile each partition with whole-account log growth rather than stitched wealth.
def _reconciliation(accounts, groups, count):
    whole = {
        name: _outcome(proof["marks"][0], proof["marks"][-1])["log_growth"]
        for name, (_, proof) in accounts.items()
    }
    residuals = {
        name: math.fsum(
            group["log_growth_by_account"][name] for group in groups.values()
        )
        - growth
        for name, growth in whole.items()
    }
    sign_counts, sign_residuals = {}, {}
    for name in accounts:
        if name == "candidate":
            continue
        cells = [
            cell
            for group in groups.values()
            for cell in group["by_comparator_sign"][name].values()
        ]
        sign_counts[name] = sum(cell["return_intervals"] for cell in cells)
        sign_residuals[name] = math.fsum(
            cell["excess_log_growth"] for cell in cells
        ) - (whole["candidate"] - whole[name])
    intent_count = sum(group["return_intervals"] for group in groups.values())
    return {
        "ok": intent_count == count
        and all(n == count for n in sign_counts.values())
        and all(
            abs(value) <= TOLERANCE
            for value in (*residuals.values(), *sign_residuals.values())
        ),
        "log_growth_by_account": whole,
        "intent_intervals": intent_count,
        "comparator_sign_intervals": sign_counts,
        "intent_log_growth_residual_by_account": residuals,
        "comparator_sign_excess_log_growth_residual": sign_residuals,
    }


# Describe retained decisions, fills and outcomes without changing any source evidence.
def attribution(snapshots: Mapping[str, dict], *, cost_bps: float) -> dict:
    accounts, dates = _checked(snapshots, cost_bps)
    candidate, _ = accounts["candidate"]
    marks = [event for event in candidate["events"] if event["type"] == "mark"]
    intervals = [_interval(accounts, marks, i) for i in range(len(dates) - 1)]
    groups = _groups(intervals, accounts)
    reconciliation = _reconciliation(accounts, groups, len(intervals))
    if not reconciliation["ok"]:
        raise ValueError("allocation attribution partitions do not reconcile")
    boundaries = {}
    for name, (snapshot, proof) in accounts.items():
        manifest = snapshot["manifest"]
        last_mark = max(
            event["seq"] for event in snapshot["events"] if event["type"] == "mark"
        )
        boundaries[name] = {
            "identity": {
                key: manifest[key] for key in ("run_id", "account_id", "policy_id")
            },
            "symbols": list(manifest["symbols"]),
            "files": copy.deepcopy(manifest["files"]),
            "manifest_sha256": hashlib.sha256(
                (
                    json.dumps(
                        manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
                    )
                    + "\n"
                ).encode("utf-8")
            ).hexdigest(),
            "initial_mark": copy.deepcopy(proof["marks"][0]),
            "terminal": copy.deepcopy(proof["terminal"]),
            "terminal_decision_ids": [
                event["decision_id"]
                for event in snapshot["events"][last_mark + 1 :]
                if event["type"] == "decision"
            ],
        }
    return {
        "schema": "allocation-attribution/1",
        "analysis": "post_hoc_frozen_allocation_attribution",
        "cost_bps": float(cost_bps),
        "first_session": dates[0],
        "last_session": dates[-1],
        "return_intervals": len(intervals),
        "accounts": boundaries,
        "intervals": intervals,
        "by_intent": groups,
        "reconciliation": reconciliation,
        "definitions": {
            "returns": (
                "Already-charged full close-to-close account returns, including "
                "pre-fill gaps; descriptive, not causal losses avoided."
            ),
            "intent": (
                "Effective desired risky sleeve(s) at the prior close; residual cash "
                "is explicit. An empty stock basket can imply a cash target without "
                "a cash-mode forecast."
            ),
            "execution_window": (
                "Events strictly after the prior closing mark through the following "
                "closing mark; never permission timing treated as a fill."
            ),
            "exposure": (
                "Realized sleeve weights at each named closing mark, not exposure "
                "held throughout the interval or at the opening fill."
            ),
            "residuals": (
                "Unfilled batch quantities and reasons are not a future order queue; "
                "terminal pending declarations are retained separately."
            ),
            "comparison_sign": (
                "Comparator net simple return versus zero; absolute values at most "
                "1e-12 are ties. This is not forecast accuracy."
            ),
            "control_roles": (
                "Account role names and portfolio construction are caller-attested. "
                "Journal verification proves accounting, not a SPY or QQQ buy-and-hold "
                "policy merely because an account has that name."
            ),
            "symbol_vectors": (
                "Position, fill, notional, fee, residual and unfilled-reason vectors "
                "follow that account's copied ordered symbols; interval batches "
                "belong to the candidate account."
            ),
            "groups": (
                "Disjoint descriptive log-growth contributions, not annualized "
                "stitched accounts, independent trials, or a rule for switching."
            ),
            "calendar": (
                "Exact reconstructed mark dates; exchange-session completeness "
                "remains caller-attested."
            ),
            "hashes": (
                "Manifest SHA256 binds canonical sorted compact JSON with a trailing "
                "newline, including declared event/price hashes; not signed provenance."
            ),
            "return_tie_absolute_tolerance": TOLERANCE,
            "reconciliation_absolute_tolerance": TOLERANCE,
        },
        "adoption_eligible": False,
        "independent_validation": False,
        "historical_availability_verified": False,
    }
