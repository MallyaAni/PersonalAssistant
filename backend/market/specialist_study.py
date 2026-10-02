"""Separate specialist contributions through the shared funded research ledger.

This is a fixed retrospective diagnostic, not an exact live-policy replay or
an automatic promotion path. Models and their outputs never reach live orders.
"""

from datetime import date, datetime, time
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.market import open_source_forecast_evaluation as frozen
from backend.market import open_source_forecasts as forecasts
from backend.market.allocation_evaluation import metrics
from backend.market.allocation_replay import AllocationInstruction, replay
from backend.market.specialist_risk import MonthlySelector, causal_regime, risk_sizing

PROTOCOL = "specialist-contributions/1"
EXPERTS = ("joint-chronos2", "risk-sized", "joint-risk")


# Compare forecast errors on identical labels without treating error as profit.
def paired_forecasts(payload, joint_records, baselines, grades, eligible, prices):
    source = frozen.source_rows(payload)
    report = {}
    for name, records in joint_records.items():
        _, independent = frozen.artifact_records(payload, baselines[name])
        rows = []
        for t, day in enumerate(payload["decisions"]):
            intent = policy_v5.targets(
                grades[t], prices[t], eligible[t], frozen.COHORT.index("SPY")
            )
            horizon = payload["calendar"][payload["calendar"].index(day) + 10]
            for j, symbol in enumerate(frozen.COHORT):
                row = {
                    "decision": day,
                    "symbol": symbol,
                    "grade_eligible": bool(intent[j] > 0),
                    "horizon_session": horizon,
                    "label_status": "immature",
                }
                if horizon <= payload["source_cutoff"]:
                    actual = frozen.realized_label(
                        payload, source, symbol, day, horizon, "terminal_close"
                    )
                    row["label_status"] = "missing" if actual is None else "mature"
                    a, b = records[day, symbol], independent[day, symbol]
                    if actual is not None and a["status"] == b["status"] == "forecast":
                        row.update(
                            actual=actual,
                            joint_squared_error=float(
                                (a["predicted_excess_return"] - actual) ** 2
                            ),
                            independent_squared_error=float(
                                (b["predicted_excess_return"] - actual) ** 2
                            ),
                        )
                rows.append(row)
        measured = [
            row
            for row in rows
            if row["grade_eligible"] and "joint_squared_error" in row
        ]
        report[name] = {
            "requested": len(rows),
            "mature_labels": sum(row["label_status"] == "mature" for row in rows),
            "immature_labels": sum(row["label_status"] == "immature" for row in rows),
            "missing_labels": sum(row["label_status"] == "missing" for row in rows),
            "paired_grade_eligible_labels": len(measured),
            "joint_mse": float(
                np.mean([row["joint_squared_error"] for row in measured])
            )
            if measured
            else None,
            "independent_mse": float(
                np.mean([row["independent_squared_error"] for row in measured])
            )
            if measured
            else None,
            "rows": rows,
            "target": "terminal_close_return_relative_SPY",
            "profit_evidence": False,
        }
    return report


# Expand the fixed cohort in memory without manufacturing absent grades.
def cohort_panel(payload, panel, grades, eligible):
    fields = {
        key: np.full((len(panel.dates), len(frozen.COHORT)), np.nan)
        for key in ("open", "close", "adj_close")
    }
    new_grades = np.full(fields["close"].shape, -1, dtype=np.int16)
    members = np.zeros(fields["close"].shape, dtype=bool)
    date_index = {str(day): i for i, day in enumerate(panel.dates)}
    for j, symbol in enumerate(frozen.COHORT):
        if symbol in panel.tickers:
            old = panel.tickers.index(symbol)
            for key in fields:
                fields[key][:, j] = getattr(panel, key)[:, old]
            new_grades[:, j] = grades[:, old]
            members[:, j] = eligible[:, old]
        else:
            for row in payload["rows"]:
                if row["symbol"] == symbol and row["session"] in date_index:
                    i = date_index[row["session"]]
                    fields["open"][i, j] = row["open"]
                    fields["close"][i, j] = fields["adj_close"][i, j] = row["close"]
    members[:, -2:] = False
    return (
        SimpleNamespace(dates=panel.dates.copy(), tickers=frozen.COHORT, **fields),
        new_grades,
        members,
    )


# Declare economic peers without claiming archived sector membership.
def context_mapping():
    result = {}
    groups = (("NVDA", "AMD", "AVGO"), ("MSFT", "AMZN", "GOOGL", "META"))
    for symbol in frozen.COHORT:
        peers = next(
            ([s for s in group if s != symbol] for group in groups if symbol in group),
            None,
        )
        result[symbol] = {
            "symbols": peers
            if peers is not None
            else (["QQQ"] if symbol != "QQQ" else ["SPY"]),
            "kind": "peer_group" if peers is not None else "broad_market_proxy",
            "source": PROTOCOL + " declared economic peer groups; "
            "not original historical sector membership",
            "available_at": "2026-09-03T16:00:00-04:00",
            "availability_mode": "assumed_research_map",
        }
    return result


# Rank positive forecasts within unchanged incumbent eligibility.
def joint_weights(base, records, day):
    required = [symbol for j, symbol in enumerate(frozen.COHORT) if base[j] > 0]
    if any(records[(day, symbol)]["status"] != "forecast" for symbol in required):
        return base.copy(), "unavailable_incumbent_fallback"
    positive = [
        symbol
        for symbol in required
        if records[(day, symbol)]["predicted_excess_return"] > 0
    ]
    selected = sorted(
        positive,
        key=lambda symbol: (-records[(day, symbol)]["predicted_excess_return"], symbol),
    )[:4]
    weights = np.zeros_like(base)
    for symbol in selected:
        weights[frozen.COHORT.index(symbol)] = min(
            0.25, float(base.sum()) / len(selected)
        )
    return weights, "ranked" if selected else "cash"


# Report funded return and risk metrics with conditional sample counts.
def summary(account, regimes):
    nav = account["nav"]
    daily = nav[1:] / nav[:-1] - 1
    result = {
        **metrics(daily),
        "fees": float(account["fees"].sum()),
        "turnover": float(account["turnover"].sum()),
        "mean_exposure": float(np.mean(1 - account["cash_fraction"])),
        "dates": account["dates"].astype(str).tolist(),
        "nav": nav.tolist(),
        "instruction_sha256": account["instruction_path"]["sha256"],
    }
    conditional = {}
    keys = sorted({row.get("key") or "unavailable" for row in regimes[:-1]})
    for key in keys:
        selected = np.array(
            [(row.get("key") or "unavailable") == key for row in regimes[:-1]]
        )
        values = daily[selected]
        conditional[key] = {
            "sessions": int(selected.sum()),
            "compounded_return_component": float(np.prod(1 + values) - 1),
            "realized_volatility": float(np.std(values) * np.sqrt(252)),
            "worst_session": float(values.min()) if len(values) else None,
            "mean_closing_exposure": float(
                np.mean(1 - account["cash_fraction"][1:][selected])
            ),
            "not_a_separate_reset_account": True,
        }
    result["causal_scenario_components"] = conditional
    result["annualized_metrics_descriptive_only"] = len(daily) < 252
    return result


# Measure compounded gain against all required controls on a common continuous path.
def benchmark_comparisons(results):
    out = {}
    for name, costs in results.items():
        out[name] = {}
        for cost, candidate in costs.items():
            nav = np.asarray(candidate["nav"])
            comparisons = {}
            for benchmark in ("incumbent", "SPY", "QQQ"):
                control = results[benchmark][cost]
                other = np.asarray(control["nav"])
                if candidate["dates"] != control["dates"] or nav.shape != other.shape:
                    raise ValueError("Benchmark calendars must match")
                windows = nav[20:] / nav[:-20] - other[20:] / other[:-20]
                comparisons[benchmark] = {
                    "gain_difference": float(nav[-1] / nav[0] - other[-1] / other[0]),
                    "relative_wealth": float(
                        (nav[-1] / nav[0]) / (other[-1] / other[0]) - 1
                    ),
                    "rolling20_windows": len(windows),
                    "rolling20_win_rate": float(np.mean(windows > 0))
                    if len(windows)
                    else None,
                }
            out[name][cost] = comparisons
    return out


# Record utilities only after their entire funded horizon is marked.
def outcome_rows(accounts, regimes, resets, dates):
    result = []
    baseline = accounts["incumbent"]["10"]["nav"]
    for t in resets:
        if t + 10 >= len(dates) or regimes[t].get("key") is None:
            continue
        stamp = datetime.combine(
            date.fromisoformat(str(dates[t])), time(16), forecasts.NY
        ).isoformat()
        end = datetime.combine(
            date.fromisoformat(str(dates[t + 10])), time(16), forecasts.NY
        ).isoformat()
        base_return = baseline[t + 10] / baseline[t] - 1
        result.append(
            {
                "prediction_at": stamp,
                "known_at": stamp,
                "label_end": end,
                "label_available_at": end,
                "regime": regimes[t]["key"],
                "utilities": {
                    name: float(
                        accounts[name]["10"]["nav"][t + 10]
                        / accounts[name]["10"]["nav"][t]
                        - 1
                        - base_return
                    )
                    for name in EXPERTS
                },
            }
        )
    return result


# Authenticate components and replay their common funded clocks and capital.
def evaluate(  # noqa: C901 - keep authentication, decisions and replay sequential
    payload,
    baselines,
    joints,
    panel,
    grades,
    eligible,
    provenance,
    *,
    source_sha256,
    selector_history=None,
):
    from backend.market.specialist_forecasts import validate_artifact

    if source_sha256 != frozen.SOURCE_SHA256:
        raise ValueError("Frozen original source bytes are required")
    if selector_history:
        raise ValueError(
            "External utilities need an authenticated funded archive; "
            "this fixed study accepts no supplied training history"
        )
    baseline_by_name = {a["checkpoint"]["name"]: a for a in baselines}
    if len(baselines) != 4 or set(baseline_by_name) != set(forecasts.CHECKPOINTS):
        raise ValueError("All four original model artifacts are required")
    for artifact in baselines:
        frozen.artifact_records(payload, artifact)
    joint_by_name = {a["checkpoint"]["name"]: a for a in joints}
    if len(joints) != 2 or set(joint_by_name) != {"chronos2", "timesfm3"}:
        raise ValueError("Both declared joint model artifacts are required")
    if any(artifact.get("symbols") != list(frozen.COHORT) for artifact in joints):
        raise ValueError("The full ordered joint cohort is required")
    joint_records = {
        name: validate_artifact(
            payload, artifact, context_mapping(), baseline_by_name[name]
        )
        for name, artifact in joint_by_name.items()
    }
    _, ttm_records = frozen.artifact_records(payload, baseline_by_name["ttm"])
    panel, grades, eligible = cohort_panel(payload, panel, grades, eligible)
    full_dates = panel.dates.copy()
    positions = [panel.tickers.index(symbol) for symbol in frozen.COHORT]
    full_prices = np.asarray(panel.adj_close)[:, positions].copy()
    panel, grades, eligible = frozen.common_panel(payload, panel, grades, eligible)
    full_indices = [int(np.flatnonzero(full_dates == day)[0]) for day in panel.dates]
    regimes = [causal_regime(full_dates, full_prices[:, -2], t) for t in full_indices]
    names = (
        "incumbent",
        "joint-chronos2",
        "joint-timesfm3",
        "covariance-only",
        "risk-sized",
        "risk-gross-control",
        "joint-risk",
        "joint-gross-control",
        "joint-risk-gross-control",
        "joint-risk-composition-control",
        "combined",
    )
    paths = {name: [] for name in names}
    receipts, resets = [], []
    # This fixed slice cannot qualify a selector or authenticate external history.
    selector = MonthlySelector(EXPERTS)
    for t, day_value in enumerate(panel.dates[:-1]):
        day = str(day_value)
        reset = t % 10 == 0
        weights = {name: None for name in names}
        details = {"decision": day, "reset": reset, "scenario": regimes[t]}
        if reset:
            resets.append(t)
            base = policy_v5.targets(
                grades[t], panel.adj_close[t], eligible[t], frozen.COHORT.index("SPY")
            )
            weights["incumbent"] = base
            for name in ("chronos2", "timesfm3"):
                weights["joint-" + name], status = joint_weights(
                    base, joint_records[name], day
                )
                details[name + "_status"] = status
            i = full_indices[t]
            with np.errstate(divide="ignore", invalid="ignore"):
                returns = full_prices[1 : i + 1] / full_prices[:i] - 1
            decision_at = datetime.combine(
                date.fromisoformat(day), time(16), forecasts.NY
            ).isoformat()
            risk_rows = []
            for symbol in frozen.COHORT:
                original = ttm_records[(day, symbol)]
                risk_rows.append(
                    {
                        **original,
                        "target": "mean_squared_log_return",
                        "prediction_at": decision_at,
                        "known_at": decision_at,
                        "horizon_end": datetime.combine(
                            date.fromisoformat(original["horizon_session"]),
                            time(16),
                            forecasts.NY,
                        ).isoformat()
                        if original["status"] == "forecast"
                        else decision_at,
                    }
                )
            cov = risk_sizing(
                base,
                returns,
                [],
                decision_at,
                return_dates=full_dates[1 : i + 1],
                covariance_only=True,
            )
            risk = risk_sizing(
                base,
                returns,
                risk_rows,
                decision_at,
                reduce_gross=True,
                return_dates=full_dates[1 : i + 1],
            )
            combined = risk_sizing(
                weights["joint-chronos2"],
                returns,
                risk_rows,
                decision_at,
                reduce_gross=True,
                return_dates=full_dates[1 : i + 1],
            )
            weights["covariance-only"] = np.asarray(cov["weights"])
            weights["risk-sized"] = np.asarray(risk["weights"])
            weights["risk-gross-control"] = np.asarray(risk["exposure_matched_control"])
            weights["joint-risk"] = np.asarray(combined["weights"])
            weights["joint-gross-control"] = (
                base * float(weights["joint-chronos2"].sum() / base.sum())
                if base.sum()
                else base.copy()
            )
            weights["joint-risk-gross-control"] = (
                base * float(weights["joint-risk"].sum() / base.sum())
                if base.sum()
                else base.copy()
            )
            weights["joint-risk-composition-control"] = np.asarray(
                combined["exposure_matched_control"]
            )
            selection = selector.select(decision_at, regimes[t], [])
            weights["combined"] = base * selection["incumbent_weight"]
            for name, coefficient in selection["weights"].items():
                weights["combined"] += weights[name] * coefficient
            details.update(
                covariance=cov, risk=risk, joint_risk=combined, selector=selection
            )
        receipts.append(details)
        for name in names:
            basket = weights[name]
            values = (
                None
                if basket is None
                else {
                    symbol: float(basket[j])
                    for j, symbol in enumerate(frozen.COHORT[:-2])
                    if basket[j] > 0
                }
            )
            paths[name].append(
                AllocationInstruction(
                    day,
                    day,
                    forecasts.digest(
                        {"name": name, "decision": day, "weights": values}
                    ),
                    1.0,
                    0.0,
                    0.0,
                    values,
                    reset,
                )
            )
    for benchmark in ("SPY", "QQQ", "membership-equal-weight"):
        paths[benchmark], _ = frozen.instructions(panel, grades, eligible, benchmark)
    accounts = {
        name: {
            str(cost): replay(panel, path, cost_bps=cost, start_equity=1)
            for cost in frozen.COSTS
        }
        for name, path in paths.items()
    }
    results = {
        name: {cost: summary(account, regimes) for cost, account in costs.items()}
        for name, costs in accounts.items()
    }
    return {
        "protocol": PROTOCOL,
        "source_sha256": source_sha256,
        "artifact_sha256": {
            a["checkpoint"]["name"]: forecasts.digest(a) for a in joints
        },
        "baseline_sha256": {
            a["checkpoint"]["name"]: forecasts.digest(a) for a in baselines
        },
        "portfolio_snapshot_sha256": provenance["snapshot_sha256"],
        "costs": results,
        "benchmark_comparisons": benchmark_comparisons(results),
        "decisions": receipts,
        "paired_forecast_diagnostics": paired_forecasts(
            payload, joint_records, baseline_by_name, grades, eligible, panel.adj_close
        ),
        "matured_incremental_utility_rows": outcome_rows(
            accounts, regimes, resets, panel.dates
        ),
        "requested_joint_opportunities": len(payload["decisions"])
        * len(frozen.COHORT)
        * 2,
        "selector_history_status": "insufficient_registered_forward_history",
        "selector_history_sha256": forecasts.digest(selector_history or []),
        "adoption_eligible": False,
        "exact_live_strategy": False,
        "historical_tradability": False,
        "timing_account_status": "separate_permission_proxy",
        "limitations": payload.get("limitations", []),
    }
