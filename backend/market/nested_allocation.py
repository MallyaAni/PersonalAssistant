"""Actual nested fits and funded selection for a separate research allocation.

This runner consumes externally supplied, dated regression observations and stock
baskets. It neither reconstructs those inputs nor authenticates their historical
availability. It fits real ridge models, selects only on earlier funded account
wealth, and executes one continuous outer account. No live policy is changed.
It is validation machinery, not a qualified strategy or a complete benchmark
study: exact /3, funded index controls and source assembly remain separate.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from itertools import product
from types import SimpleNamespace

import numpy as np

from backend.market import nested_ridge
from backend.market.allocation_controls import adjusted_open
from backend.market.allocation_replay import AllocationInstruction, replay
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot

POLICY = "nested-ridge-allocation/1-research"
COSTS = (10, 25)
MODES = ("cash", "stock", "SPY", "QQQ")
STOCK_CADENCE = 20


@dataclass(frozen=True)
class NestedProtocol:
    """Explicit chronological geometry and the complete, ordered candidate grid."""

    first_outer: int = 1260
    outer_sessions: int = 126
    inner_sessions: int = 126
    inner_blocks: int = 3
    min_train_rows: int = 504
    alphas: tuple[float, ...] = (1.0, 100.0)
    switch_margins: tuple[float, ...] = (0.0, 0.005)


DEFAULT_PROTOCOL = NestedProtocol()


# Fingerprint JSON evidence deterministically without serializing nonfinite numbers.
def _digest(payload):
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


# Reject implicit geometry changes and preserve the declared tie-breaking order.
def _protocol(value, rows):
    if not isinstance(value, NestedProtocol):
        raise ValueError("protocol must be an explicit NestedProtocol")
    for name in (
        "first_outer",
        "outer_sessions",
        "inner_sessions",
        "inner_blocks",
        "min_train_rows",
    ):
        number = getattr(value, name)
        if type(number) is not int or number < 1:
            raise ValueError(f"{name} must be a positive integer")
    first_inner = value.first_outer - value.inner_blocks * value.inner_sessions - 1
    if first_inner < value.min_train_rows or value.first_outer >= rows - 1:
        raise ValueError("insufficient history for inner training and outer execution")
    for name in ("alphas", "switch_margins"):
        sequence = getattr(value, name)
        if not isinstance(sequence, tuple) or not sequence:
            raise ValueError(f"{name} must be an ordered nonempty tuple")
        for number in sequence:
            if (
                isinstance(number, (bool, np.bool_))
                or not isinstance(number, (int, float, np.integer, np.floating))
                or not math.isfinite(number)
                or number < 0
                or (name == "alphas" and float(number) == 0)
            ):
                raise ValueError(f"invalid {name}")
        if len({float(number) for number in sequence}) != len(sequence):
            raise ValueError(f"duplicate {name}")
    payload = asdict(value)
    payload.update(
        policy=POLICY,
        costs_bps=list(COSTS),
        stock_cadence_sessions=STOCK_CADENCE,
        stock_cadence_anchor="source row zero, never a fold boundary",
        target_order=["stock", "SPY", "QQQ"],
        calibration="none; return regression, not probability forecasting",
        selection="max worst-cost terminal log wealth; declaration order breaks ties",
        mode_rule="switch only when best forecast exceeds current by margin",
        mode_tie_order=list(MODES),
        initial_mode="cash",
        adoption_eligible=False,
        historical_availability_verified=False,
    )
    payload["alphas"] = [float(x) for x in value.alphas]
    payload["switch_margins"] = [float(x) for x in value.switch_margins]
    return payload


# Own the execution grid and enforce the single absolute stock-refresh schedule.
def _inputs(panel, regression, stock_weights):  # noqa: C901 - explicit input refusals
    if not isinstance(regression, nested_ridge.RegressionInputs):
        raise ValueError("dated RegressionInputs are required")
    dates = np.asarray(panel.dates)
    if (
        dates.dtype != np.dtype("datetime64[D]")
        or dates.ndim != 1
        or len(dates) < 2
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
        or not np.array_equal(dates, regression.dates)
    ):
        raise ValueError("regression and execution must share an ordered daily grid")
    if not isinstance(panel.tickers, (tuple, list)):
        raise ValueError("execution symbols must be ordered")
    symbols = tuple(panel.tickers)
    if (
        not symbols
        or any(
            not isinstance(s, str) or not s.strip() or s.strip() != s for s in symbols
        )
        or len(set(symbols)) != len(symbols)
        or not {"SPY", "QQQ"}.issubset(symbols)
    ):
        raise ValueError("execution symbols must be unique and include SPY and QQQ")
    shape = (len(dates), len(symbols))
    prices = {}
    for name in ("open", "close", "adj_close"):
        values = np.asarray(getattr(panel, name))
        if values.shape != shape or values.dtype.kind not in "iuf":
            raise ValueError("prices must be real numeric arrays on the declared grid")
        if np.isinf(values).any() or np.any(np.isfinite(values) & (values <= 0)):
            raise ValueError("prices must be positive or explicitly missing")
        with np.errstate(over="ignore", invalid="ignore"):
            copied = np.array(values, dtype=float, copy=True)
        if np.isinf(copied).any() or np.any(np.isfinite(copied) & (copied <= 0)):
            raise ValueError("prices must remain positive or missing in float64")
        prices[name] = copied
    weights = np.asarray(stock_weights)
    if weights.shape != shape or weights.dtype.kind not in "iuf":
        raise ValueError("stock weights must match the real numeric source grid")
    weights = np.array(weights, dtype=float, copy=True)
    if (
        not np.isfinite(weights).all()
        or np.any(weights < 0)
        or np.any(weights.sum(axis=1) > 1 + 1e-12)
        or np.any(weights[:, [symbols.index("SPY"), symbols.index("QQQ")]] != 0)
    ):
        raise ValueError("stock weights must be cash-bounded and exclude indexes")
    for t in range(1, len(dates)):
        if t % STOCK_CADENCE and not np.array_equal(weights[t], weights[t - 1]):
            raise ValueError("stock composition changed outside the absolute cadence")
    return SimpleNamespace(dates=dates.copy(), tickers=symbols, **prices), weights


# Keep caller mutation outside a run and own the normalized observation arrays.
def _regression_copy(inputs):
    return replace(
        inputs,
        **{
            name: np.array(getattr(inputs, name), copy=True)
            for name in (
                "dates",
                "features",
                "feature_available_on",
                "labels",
                "label_end_on",
                "label_available_on",
            )
        },
    )


# Bind full input identity separately from hashes of past-only fitted observations.
def _source_evidence(panel, regression, weights):
    arrays = {
        "dates": panel.dates,
        "raw_open": panel.open,
        "raw_close": panel.close,
        "adjusted_close": panel.adj_close,
        "stock_weights": weights,
        **{
            name: getattr(regression, name)
            for name in (
                "features",
                "feature_available_on",
                "labels",
                "label_end_on",
                "label_available_on",
            )
        },
    }
    manifest = {
        "schema": "nested-allocation-inputs/1",
        "symbols": list(panel.tickers),
        "feature_names": list(regression.feature_names)
        if regression.feature_names is not None
        else None,
        "arrays": {},
        "normalization": (
            "float64 numeric arrays; daily dates; not original vendor bytes"
        ),
        "historical_availability_verified": False,
    }
    for name, values in arrays.items():
        array = np.ascontiguousarray(values)
        manifest["arrays"][name] = {
            "shape": list(array.shape),
            "dtype": array.dtype.str,
            "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
        }
    return {"manifest": manifest, "sha256": _digest(manifest), "arrays": arrays}


# Preserve current intent on ties and treat indexes as risky alternatives to cash.
def choose_mode(prediction, current, margin):
    values = np.asarray(prediction)
    if (
        values.shape != (3,)
        or values.dtype.kind not in "iuf"
        or not np.isfinite(values).all()
    ):
        raise ValueError("three finite stock/SPY/QQQ forecasts are required")
    with np.errstate(over="ignore", invalid="ignore"):
        values = values.astype(float)
    if not np.isfinite(values).all():
        raise ValueError("forecasts must remain finite in float64")
    if current not in MODES:
        raise ValueError("unknown current allocation mode")
    if (
        isinstance(margin, (bool, np.bool_))
        or not isinstance(margin, (int, float, np.integer, np.floating))
        or not math.isfinite(margin)
        or margin < 0
    ):
        raise ValueError("margin must be a finite nonnegative log-return difference")
    margin = float(margin)
    forecasts = dict(zip(MODES, (0.0, *map(float, values)), strict=True))
    best = max(MODES, key=lambda name: forecasts[name])
    return best if forecasts[best] > forecasts[current] + margin else current


# Translate cost-independent predictions into dated intent with stable stock updates.
def _instructions(
    panel, weights, predictions, first, mode, margin, evidence, *, initial
):
    rows = []
    for offset, prediction in enumerate(predictions):
        t = first + offset
        mode = choose_mode(prediction, mode, margin)
        update = t % STOCK_CADENCE == 0 or (initial and offset == 0)
        basket = (
            {
                s: float(w)
                for s, w in zip(panel.tickers, weights[t], strict=True)
                if w > 0
            }
            if update
            else None
        )
        rows.append(
            AllocationInstruction(
                session=str(panel.dates[t]),
                information_through=str(panel.dates[t]),
                evidence_id=f"{evidence}:{t}",
                stock_scale=float(mode == "stock"),
                spy_weight=float(mode == "SPY"),
                qqq_weight=float(mode == "QQQ"),
                stock_weights=basket,
            )
        )
    return rows, mode


# Execute only this account's price window, then independently reconcile every mark.
def _account(panel, instructions, first, last_mark, cost, account_id):
    cut = slice(first, last_mark + 1)
    window = SimpleNamespace(
        dates=panel.dates[cut],
        tickers=panel.tickers,
        open=panel.open[cut],
        close=panel.close[cut],
        adj_close=panel.adj_close[cut],
    )
    journal = ResearchJournal(
        window.dates,
        window.tickers,
        adjusted_open(window.open, window.close, window.adj_close),
        window.adj_close,
        run_id=POLICY,
        account_id=account_id,
        policy_id=POLICY,
        cost_bps=cost,
        provenance={
            "evidence_basis": "caller-declared-research-inputs",
            "source_first_index": first,
            "source_last_mark_index": last_mark,
            "label_derivation_verified": False,
        },
    )
    result = replay(window, instructions, cost_bps=cost, journal=journal)
    snapshot = journal.snapshot()
    proof = verify_snapshot(snapshot)
    if not proof["ok"]:
        raise ValueError(f"independent account verification failed: {proof['errors']}")
    return {
        "result": result,
        "journal": snapshot,
        "verification": proof,
        "journal_sha256": _digest(snapshot),
    }


# Fit every inner model on its own past, without sharing transforms across cutoffs.
def _inner_predictions(regression, protocol, start, stop, alpha):
    predictions = []
    fits = []
    for first in range(start, stop, protocol.inner_sessions):
        end = min(first + protocol.inner_sessions, stop)
        model = nested_ridge.fit(
            regression, first, alpha, min_train_rows=protocol.min_train_rows
        )
        values = model.predict(regression, np.arange(first, end))
        predictions.append(values)
        fits.append(
            {
                "first": first,
                "stop": end,
                "fit": model.receipt,
                "predictions": values.tolist(),
                "predictions_sha256": _digest(
                    {"first": first, "stop": end, "values": values.tolist()}
                ),
            }
        )
    return np.concatenate(predictions), fits


# Select one candidate using the worst of two actual earlier funded account results.
def _select(panel, regression, weights, protocol, outer_start):
    first = outer_start - protocol.inner_blocks * protocol.inner_sessions - 1
    last_mark = outer_start - 1
    by_alpha = {
        float(alpha): _inner_predictions(regression, protocol, first, last_mark, alpha)
        for alpha in protocol.alphas
    }
    candidates, accounts = [], []
    for number, (alpha, margin) in enumerate(
        product(protocol.alphas, protocol.switch_margins)
    ):
        identifier = f"candidate-{number}"
        predictions, fits = by_alpha[float(alpha)]
        rows, ending_mode = _instructions(
            panel,
            weights,
            predictions,
            first,
            "cash",
            margin,
            f"inner:{outer_start}:{identifier}",
            initial=True,
        )
        growth = {}
        for cost in COSTS:
            account = _account(
                panel,
                rows,
                first,
                last_mark,
                cost,
                f"inner:{outer_start}:{identifier}:{cost}",
            )
            nav = account["result"]["nav"]
            growth[str(cost)] = math.log(float(nav[-1] / nav[0]))
            accounts.append(
                {
                    "outer_start": outer_start,
                    "candidate_id": identifier,
                    "cost_bps": cost,
                    "first": first,
                    "last_mark": last_mark,
                    **account,
                }
            )
        candidates.append(
            {
                "id": identifier,
                "alpha": float(alpha),
                "margin": float(margin),
                "score": min(growth.values()),
                "log_growth_by_cost": growth,
                "inner_fits": fits,
                "ending_mode": ending_mode,
            }
        )
    selected = max(candidates, key=lambda item: item["score"])
    return selected, candidates, accounts


# Run genuine inner selection followed by one unbroken outer funded instruction path.
def run(panel, regression, stock_weights, *, protocol=DEFAULT_PROTOCOL):
    panel, weights = _inputs(panel, regression, stock_weights)
    regression = _regression_copy(regression)
    declared = _protocol(protocol, len(panel.dates))
    protocol = replace(
        protocol,
        alphas=tuple(declared["alphas"]),
        switch_margins=tuple(declared["switch_margins"]),
    )
    instructions, folds, inner_runs = [], [], []
    mode = "cash"
    for start in range(
        protocol.first_outer, len(panel.dates) - 1, protocol.outer_sessions
    ):
        stop = min(start + protocol.outer_sessions, len(panel.dates) - 1)
        selected, candidates, earlier = _select(
            panel, regression, weights, protocol, start
        )
        inner_runs.extend(earlier)
        model = nested_ridge.fit(
            regression, start, selected["alpha"], min_train_rows=protocol.min_train_rows
        )
        prediction = model.predict(regression, np.arange(start, stop))
        starting_mode = mode
        rows, mode = _instructions(
            panel,
            weights,
            prediction,
            start,
            mode,
            selected["margin"],
            f"outer:{start}:{model.model_state_sha256}",
            initial=not instructions,
        )
        instructions.extend(rows)
        folds.append(
            {
                "start": start,
                "stop": stop,
                "inner_first": start
                - protocol.inner_blocks * protocol.inner_sessions
                - 1,
                "inner_last_mark": start - 1,
                "candidates": candidates,
                "selected_id": selected["id"],
                "fit": model.receipt,
                "model_hash": model.model_state_sha256,
                "fit_receipt_sha256": model.sha256,
                "predictions": prediction.tolist(),
                "predictions_sha256": _digest(
                    {"start": start, "stop": stop, "values": prediction.tolist()}
                ),
                "starting_mode": starting_mode,
                "ending_mode": mode,
            }
        )
    # A stock-only adapter control isolates timing from the unchanged basket cadence.
    no_gate, _ = _instructions(
        panel,
        weights,
        np.tile([1.0, 0.0, 0.0], (len(instructions), 1)),
        protocol.first_outer,
        "stock",
        0.0,
        "no-gate-adapter",
        initial=True,
    )
    accounts = {
        str(cost): {
            name: _account(
                panel,
                rows,
                protocol.first_outer,
                len(panel.dates) - 1,
                cost,
                f"outer:{name}:{cost}",
            )
            for name, rows in (
                ("candidate", instructions),
                ("no_gate_adapter", no_gate),
            )
        }
        for cost in COSTS
    }
    output = {
        "policy": POLICY,
        "protocol": declared,
        "protocol_sha256": _digest(declared),
        "outer_folds": folds,
        "inner_runs": inner_runs,
        "accounts": accounts,
        "instructions": tuple(instructions),
        "adoption_eligible": False,
        "source_inputs": _source_evidence(panel, regression, weights),
        "historical_availability_verified": False,
        "label_derivation_verified": False,
        "benchmark_study_complete": False,
    }
    output["decision_output_sha256"] = _digest(
        {
            "protocol_sha256": output["protocol_sha256"],
            "outer_folds": folds,
            "instructions": [asdict(row) for row in instructions],
        }
    )
    output["decision_output_hash_scope"] = (
        "protocol, fits, selections, predictions, instructions; not account results"
    )
    return output
