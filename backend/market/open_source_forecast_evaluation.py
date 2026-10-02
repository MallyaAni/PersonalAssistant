"""Frozen pretrained scorecard; funded next-open economics separate from labels."""

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, time
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.market import open_source_forecasts as forecasts
from backend.market.allocation_controls import adjusted_open
from backend.market.allocation_evaluation import metrics
from backend.market.allocation_replay import AllocationInstruction, replay

COHORT = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AVGO",
    "AMD",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AAOI",
    "SPY",
    "QQQ",
)
START, END = "2026-09-03", "2026-09-30"
SOURCE_SHA256 = "e880fad45d38a1d52880f3aae54b7a306b49a7372661d58cd777553d424e6e13"
SCHEMA = "open-source-forecast-scorecard/1"
COSTS = (10, 25)
CONTROLS = ("membership-equal-weight", "grade-v5-cadence10-control", "SPY", "QQQ")


# Hash immutable evidence without accepting nonfinite JSON values.
def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


# Require finite forecast numbers without accepting booleans as financial values.
def finite(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not np.isfinite(value)
    ):
        raise ValueError("Finite forecast value required")
    return float(value)


# Bind the shared portfolio calendar and adjusted prices to the forecast source.
def common_panel(payload, panel, grades, eligible):
    decisions = payload["decisions"]
    if (
        decisions != sorted(set(decisions))
        or decisions[0] != START
        or decisions[-1] != END
    ):
        raise ValueError("Fixed ordered decision interval required")
    if len(decisions) != 19 or payload.get("source_cutoff") != END:
        raise ValueError("Nineteen decisions and fixed source cutoff required")
    symbols = tuple(panel.tickers)
    if not set(COHORT).issubset(symbols):
        raise ValueError("Full fixed cohort required")
    positions = [symbols.index(symbol) for symbol in COHORT]
    dates = [str(day) for day in panel.dates]
    selected = [i for i, day in enumerate(dates) if START <= day <= END]
    if [dates[i] for i in selected] != decisions:
        raise ValueError("Source and executable calendars disagree")
    values = {
        key: np.asarray(getattr(panel, key))[np.ix_(selected, positions)].copy()
        for key in ("open", "close", "adj_close")
    }
    membership = np.asarray(eligible)
    if (
        membership.dtype.kind != "b"
        or membership.shape != np.asarray(panel.adj_close).shape
    ):
        raise ValueError("Explicit dated Boolean membership required")
    if np.any(membership[:, [symbols.index("SPY"), symbols.index("QQQ")]]):
        raise ValueError("Benchmarks cannot be eligible book members")
    opened = adjusted_open(values["open"], values["close"], values["adj_close"])
    source = source_rows(payload)
    for t, day in enumerate(decisions):
        for n, symbol in enumerate(COHORT):
            row = source.get((day, symbol))
            if (
                row is None
                or not np.isclose(values["adj_close"][t, n], row["close"], rtol=1e-9)
                or not np.isclose(opened[t, n], row["open"], rtol=1e-9)
            ):
                raise ValueError("Portfolio/forecast adjusted price bases disagree")
    return (
        SimpleNamespace(
            dates=np.array(decisions, dtype="datetime64[D]"), tickers=COHORT, **values
        ),
        np.asarray(grades)[np.ix_(selected, positions)],
        np.asarray(eligible)[np.ix_(selected, positions)],
    )


# Index source rows without erasing duplicate or unavailable historical evidence.
def source_rows(payload):
    result = {}
    for row in payload["rows"]:
        key = (row["session"], row["symbol"])
        if key in result:
            raise ValueError("Duplicate source row")
        result[key] = row
    return result


# Bind checkpoint, implementation and original source declarations before scoring.
def artifact_spec(payload, artifact):
    if artifact.get("input_sha256") != SOURCE_SHA256:
        raise ValueError("Model frozen input source hash mismatch")
    if type(artifact.get("seed")) is not int or artifact["seed"] != 0:
        raise ValueError("Fixed protocol seed zero required")
    spec = forecasts.CHECKPOINTS.get(artifact.get("checkpoint", {}).get("name"))
    if spec is None or artifact.get("checkpoint") != asdict(spec):
        raise ValueError("Checkpoint provenance mismatch")
    if (
        artifact.get("protocol") != forecasts.PROTOCOL
        or artifact.get("source_revision") != payload["source_revision"]
    ):
        raise ValueError("Forecast protocol or source revision mismatch")
    for field in ("availability_mode", "volume_basis", "data_mode"):
        if artifact.get(field) != payload.get(field):
            raise ValueError("Forecast source declaration mismatch")
    if (
        artifact.get("device") != "cpu"
        or artifact.get("production_eligible") is not False
    ):
        raise ValueError("Research-only CPU forecast required")
    runtime = artifact.get("runtime", {})
    source_key = {
        "kronos": "kronos_source_revision",
        "timesfm3": "timesfm_source_revision",
    }.get(spec.name)
    if source_key and runtime.get(source_key) != forecasts.CODE_REVISIONS[spec.name]:
        raise ValueError("Model implementation revision mismatch")
    return spec


# Validate every artifact and preserve unavailable outcomes instead of dropping them.
def artifact_records(payload, artifact):
    spec = artifact_spec(payload, artifact)
    result = {}
    for record in artifact["records"]:
        key = (record["decision"], record["symbol"])
        if key in result or record.get("model") != spec.name:
            raise ValueError("Duplicate or mismatched forecast record")
        result[key] = record
    expected = {(day, symbol) for day in payload["decisions"] for symbol in COHORT}
    if set(result) != expected:
        raise ValueError("Missing or unexpected forecast records")
    symbol_payloads = {
        symbol: {
            **payload,
            "rows": [row for row in payload["rows"] if row["symbol"] == symbol],
        }
        for symbol in COHORT
    }
    for record in result.values():
        validate_record(symbol_payloads[record["symbol"]], spec, record)
    if spec.target == "terminal_close":
        validate_excess(payload, result)
    return spec, result


# Enforce causal context, checkpoint availability, fixed horizon and forecast units.
def validate_record(payload, spec, record):
    status = record.get("status")
    if status not in ("forecast", "model_error", "unavailable"):
        raise ValueError("Unknown forecast status")
    if record["decision"] < spec.available_on:
        if (
            status != "unavailable"
            or record.get("reason") != "checkpoint_not_available"
        ):
            raise ValueError("Forecast predates checkpoint availability")
        return
    if status != "forecast":
        if not record.get("reason"):
            raise ValueError("Unavailable forecast requires a reason")
        return
    rows, future = forecasts.context(payload, record["symbol"], record["decision"])
    if (
        record.get("context_hash") != forecasts.digest(rows)
        or record.get("last_known_at") != rows[-1]["available_at"]
        or record.get("horizon_session") != future[-1]
    ):
        raise ValueError("Forecast context/hash/horizon mismatch")
    predicted = np.array([finite(value) for value in record["forecast"]])
    if (
        predicted.shape != (10,)
        or np.any(predicted < 0)
        or (spec.target == "terminal_close" and np.any(predicted <= 0))
    ):
        raise ValueError("Forecast shape or target units invalid")
    validate_predictions(spec, record, predicted, rows)


# Check forecast and baseline numerical targets independently of record timing.
def validate_predictions(spec, record, predicted, rows):
    if spec.target == "terminal_close":
        finite(record["predicted_excess_return"])
        calculated = predicted[-1] / rows[-1]["close"] - 1
        if not np.isclose(
            calculated, finite(record["predicted_return"]), atol=1e-10, rtol=1e-9
        ):
            raise ValueError("Forecast price and return disagree")
    else:
        baseline = float(
            np.mean(np.diff(np.log([row["close"] for row in rows[-21:]])) ** 2)
        )
        if not np.isclose(
            predicted.mean(), finite(record["predicted_risk"]), atol=1e-12
        ) or not np.isclose(baseline, finite(record["baseline_risk"]), atol=1e-12):
            raise ValueError("Risk prediction/baseline units disagree")


# Recompute relative returns from the artifact's separately forecast SPY series.
def validate_excess(payload, records):
    for day in payload["decisions"]:
        spy = records[day, "SPY"]
        for symbol in COHORT:
            row = records[day, symbol]
            if row["status"] != "forecast":
                continue
            if spy["status"] != "forecast":
                continue
            expected = row["predicted_return"] - spy["predicted_return"]
            if not np.isclose(
                finite(row["predicted_excess_return"]), expected, atol=1e-10, rtol=1e-9
            ):
                raise ValueError("SPY-relative forecast mismatch")


# Select only predeclared positive-excess eligible names, leaving residual cash.
def model_target(records, day, eligible):
    members = [symbol for n, symbol in enumerate(COHORT[:-2]) if eligible[n]]
    required = members + ["SPY"]
    if any(records[day, symbol]["status"] != "forecast" for symbol in required):
        return {}, "unavailable"
    positive = [
        symbol
        for symbol in members
        if records[day, symbol]["predicted_excess_return"] > 0
    ]
    ranked = sorted(
        positive,
        key=lambda symbol: (-records[day, symbol]["predicted_excess_return"], symbol),
    )[:4]
    return {symbol: 0.25 for symbol in ranked}, "ranked" if ranked else "cash"


# Reuse the existing grade allocator and equally capped membership controls.
def control_target(name, panel, grades, eligible, t):
    if name in ("SPY", "QQQ"):
        return {}, name
    if name == "grade-v5-cadence10-control":
        values = policy_v5.targets(
            grades[t], panel.adj_close[t], eligible[t], COHORT.index("SPY")
        )
        return {
            symbol: float(values[n])
            for n, symbol in enumerate(COHORT[:-2])
            if values[n] > 0
        }, "graded"
    members = [symbol for n, symbol in enumerate(COHORT[:-2]) if eligible[t, n]]
    weight = min(0.25, 1 / len(members)) if members else 0
    return {symbol: weight for symbol in members}, "membership"


# Build one ten-session close-time target path without using future prices or labels.
def instructions(panel, grades, eligible, name, records=None):
    result, resets = [], []
    for t, day_value in enumerate(panel.dates[:-1]):
        day = str(day_value)
        reset = t % 10 == 0
        weights, status = ({}, "held")
        if reset:
            weights, status = (
                model_target(records, day, eligible[t])
                if records is not None
                else control_target(name, panel, grades, eligible, t)
            )
            resets.append({"decision": day, "status": status, "weights": weights})
        result.append(
            AllocationInstruction(
                day,
                day,
                digest(
                    {
                        "name": name,
                        "decision": day,
                        "weights": weights,
                        "status": status,
                    }
                ),
                stock_scale=1.0,
                spy_weight=1.0 if name == "SPY" else 0.0,
                qqq_weight=1.0 if name == "QQQ" else 0.0,
                stock_weights=weights if reset else None,
                rebalance=reset,
            )
        )
    return result, resets


# Retain immature terminal labels while separating return error from risk units.
def label_rows(payload, spec, records, eligible):
    source = source_rows(payload)
    out = []
    for t, day in enumerate(payload["decisions"]):
        for n, symbol in enumerate(COHORT):
            record = records[day, symbol]
            row = {
                "decision": day,
                "symbol": symbol,
                "forecast_status": record["status"],
                "eligible": bool(eligible[t, n]),
                "label_status": "immature",
            }
            horizon = payload["calendar"][payload["calendar"].index(day) + 10]
            row["horizon_session"] = horizon
            if horizon <= payload["source_cutoff"]:
                label = realized_label(
                    payload, source, symbol, day, horizon, spec.target
                )
                if label is None:
                    row["label_status"] = "missing"
                else:
                    row.update(label_status="mature", actual=label)
                    prediction_error(row, record, records[day, "SPY"], spec.target)
            out.append(row)
    return out


# Score available predictions without erasing maturity when inference failed.
def prediction_error(row, record, spy, target):
    if record["status"] != "forecast" or (
        target == "terminal_close" and spy["status"] != "forecast"
    ):
        return
    prediction = (
        record["predicted_risk"]
        if target != "terminal_close"
        else record["predicted_excess_return"]
    )
    row.update(predicted=prediction, squared_error=(prediction - row["actual"]) ** 2)
    if target != "terminal_close":
        row["baseline_squared_error"] = (record["baseline_risk"] - row["actual"]) ** 2


# Publish complete denominators and forecast errors in their declared units.
def label_summary(rows, target):
    measured = [row for row in rows if row["eligible"] and "squared_error" in row]
    return {
        "requested_opportunities": len(rows),
        "eligible_opportunities": sum(row["eligible"] for row in rows),
        "forecast_unavailable": sum(
            row["forecast_status"] != "forecast" for row in rows
        ),
        "mature_labels": sum(row["label_status"] == "mature" for row in rows),
        "immature_labels": sum(row["label_status"] == "immature" for row in rows),
        "missing_labels": sum(row["label_status"] == "missing" for row in rows),
        "scored_eligible_labels": len(measured),
        "target": target,
        "prediction_mse": float(np.mean([row["squared_error"] for row in measured]))
        if measured
        else None,
        "trailing20_risk_baseline_mse": float(
            np.mean([row["baseline_squared_error"] for row in measured])
        )
        if measured and target != "terminal_close"
        else None,
    }


# Compute only the registered terminal excess or mean squared log-return label.
def realized_label(payload, source, symbol, day, horizon, target):
    calendar = payload["calendar"]
    selected = calendar[calendar.index(day) : calendar.index(horizon) + 1]
    symbols = (symbol, "SPY") if target == "terminal_close" else (symbol,)
    values = {}
    cutoff = datetime.combine(
        date.fromisoformat(payload["source_cutoff"]), time(16), forecasts.NY
    )
    for ticker in symbols:
        rows = [source.get((session, ticker)) for session in selected]
        if any(row is None for row in rows):
            return None
        if any(forecasts.aware(row["available_at"]) > cutoff for row in rows):
            return None
        values[ticker] = np.array([row["close"] for row in rows], dtype=float)
    if target != "terminal_close":
        return float(np.mean(np.diff(np.log(values[symbol])) ** 2))
    return float(
        values[symbol][-1] / values[symbol][0] - values["SPY"][-1] / values["SPY"][0]
    )


# Report short-window economic evidence without presenting annualization as proof.
def account_summary(account):
    nav = account["nav"]
    summary = metrics(nav[1:] / nav[:-1] - 1)
    return {
        "total_return": summary["total"],
        "maximum_drawdown_loss": summary["drawdown"],
        "annualized_cagr_descriptive": summary["annual"],
        "annualized_sharpe_descriptive": summary["sharpe"],
        "fees_nav_units": float(account["fees"].sum()),
        "funded_turnover_sum": float(account["turnover"].sum()),
        "mean_exposure": float(np.mean(1 - account["cash_fraction"])),
        "dates": [str(day) for day in account["dates"]],
        "nav": nav.tolist(),
        "instruction_path_sha256": account["instruction_path"]["sha256"],
    }


# Evaluate immutable forecast artifacts once through the existing funded ledger.
def evaluate(payload, artifacts, panel, grades, eligible, provenance, *, source_sha256):
    if source_sha256 != SOURCE_SHA256:
        raise ValueError("Frozen source file hash mismatch")
    panel, grades, eligible = common_panel(payload, panel, grades, eligible)
    results, labels, reset_rows, summaries = {}, {}, {}, {}
    price_models = {}
    for artifact in artifacts:
        spec, records = artifact_records(payload, artifact)
        if spec.name in labels:
            raise ValueError("Duplicate model artifact")
        labels[spec.name] = label_rows(payload, spec, records, eligible)
        summaries[spec.name] = label_summary(labels[spec.name], spec.target)
        if spec.target == "terminal_close":
            price_models[spec.name] = records
    for name in (*CONTROLS, *price_models):
        path, resets = instructions(
            panel, grades, eligible, name, price_models.get(name)
        )
        reset_rows[name] = resets
        results[name] = {
            str(cost): account_summary(
                replay(panel, path, first=0, cost_bps=cost, start_equity=1)
            )
            for cost in COSTS
        }
    comparisons = comparison_table(results, reset_rows)
    return {
        "schema": SCHEMA,
        "source_sha256": source_sha256,
        "payload_sha256": digest(payload),
        "portfolio_snapshot_sha256": provenance.get("snapshot_sha256"),
        "artifact_sha256": {
            artifact["checkpoint"]["name"]: digest(artifact) for artifact in artifacts
        },
        "start": START,
        "end": END,
        "cohort": list(COHORT),
        "costs": results,
        "comparison_table": comparisons,
        "resets": reset_rows,
        "opportunities": labels,
        "forecast_diagnostics": summaries,
        "adoption_eligible": False,
        "historical_tradability": False,
        "exact_live_strategy": False,
        "rolling_252_win_rate": None,
        "split_2016_2020": None,
        "split_2021_2026": None,
        "terminal_decision_without_next_open": END,
    }


# Rank no candidates; publish net compounded differences against both benchmarks.
def comparison_table(results, resets):
    rows = []
    for name, costs in results.items():
        for cost, result in costs.items():
            gain = result["total_return"]
            rows.append(
                {
                    "name": name,
                    "cost_bps": int(cost),
                    "start": START,
                    "end": END,
                    "net_total_return": gain,
                    "excess_total_return_vs_spy": gain
                    - results["SPY"][cost]["total_return"],
                    "excess_total_return_vs_qqq": gain
                    - results["QQQ"][cost]["total_return"],
                    "difference_vs_grade_control": gain
                    - results["grade-v5-cadence10-control"][cost]["total_return"],
                    "maximum_drawdown_loss": result["maximum_drawdown_loss"],
                    "fees_nav_units": result["fees_nav_units"],
                    "funded_turnover_sum": result["funded_turnover_sum"],
                    "mean_exposure": result["mean_exposure"],
                    "requested_resets": len(resets[name]),
                    "unavailable_resets": sum(
                        row["status"] == "unavailable" for row in resets[name]
                    ),
                    "annualized_cagr_descriptive": result[
                        "annualized_cagr_descriptive"
                    ],
                    "annualized_sharpe_descriptive": result[
                        "annualized_sharpe_descriptive"
                    ],
                }
            )
    return rows
