"""Evaluate frozen execution distributions on unchanged, cash-funded rule plans.

Exactly two saved heads, three costs and twenty phases are evaluated. No model
is fitted and no saved account is replayed. Outputs remain component research.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from backend.cli import market_adaptive_timing_sizing as reused
from backend.cli import market_probabilistic_execution as forecasts
from backend.cli import market_sequential_execution as primary
from backend.cli.market_learned_entry import sha256, write_json
from backend.market import learned_entry_models as original
from backend.market import probabilistic_execution as probability
from backend.market import probabilistic_execution_replay as replay
from backend.market import probabilistic_execution_saved as restored

METHODS = ("boosting", "ridge")
REPORT_SHA = "67084f65042a1defe87cfc5372ef5dd1de9e18e86a50b8c9d94b9d223681bf34"
PROOF_SHA = "c319fa57d520ae28189ba2158d2dc0b6f326f7dad1c671b6c3069ad9c34c2556"
PRIMARY_PROOF_SHA = "3c41c6420a1aa1c01afe8857a6eb3b6f6e4138917be4eb2435059bffe4f94435"
PRIMARY_VERIFICATION_SHA = (
    "2821941a638b1136690cafb0a150507d57ea7a9ff4d9cca62df86b24df2ff85f"
)
PROTOCOL = "docs/research/probabilistic-funded-timing-plan-2026-10-04.md"


# Refuse changed evidence rather than finding a more favorable usable source.
def require(condition, reason):
    if not condition:
        raise ValueError(reason)


# Authenticate the completed diagnostics and independent saved-artifact proof.
def diagnostic_evidence(directory, proof_path):
    directory = Path(directory)
    report = forecasts.evidence(directory / "report.json", REPORT_SHA, json_file=True)
    proof = forecasts.evidence(proof_path, PROOF_SHA, json_file=True)
    require(
        report["adoption_eligible"] is False and tuple(report["methods"]) == METHODS,
        "Both original methods required; no outcome-based selection",
    )
    # Exact proof bytes are pinned; its schema stays independent of this runner.
    return report, proof


# Restore the already authenticated stock/month distributions without calibration.
def distribution_provider(directory, method, report, inputs):
    dates, names, labels, valid, means, risk, _ = inputs
    row = report["methods"][method]
    manifest = forecasts.evidence(
        Path(directory) / f"{method}-calibration.json",
        row["calibration_sha256"],
        json_file=True,
    )
    archive = forecasts.evidence(
        Path(directory) / f"{method}.npz", row["artifact_sha256"]
    )
    with np.load(archive, allow_pickle=False) as saved:
        require(
            np.array_equal(saved["dates"], dates)
            and tuple(saved["symbols"].tolist()) == names,
            "Saved distribution grid differs from original inputs",
        )
        saved_probability = saved["probability"]
        saved_quantiles = saved["quantiles"]
    return restored.load_saved(
        dates,
        names,
        means[method][..., 2],
        risk,
        labels,
        valid,
        dates,
        manifest,
        data_as_of=forecasts.AS_OF,
        horizon=probability.HORIZON,
        saved_probability=saved_probability,
        saved_quantiles=saved_quantiles,
    )


# Pin every new dependency separately from the unchanged saved-control boundary.
def source_identity(args, *, whole_tree=True):
    result = primary.source_identity()
    root = Path(__file__).resolve().parents[2]
    for name in (
        "backend/cli/market_probabilistic_funded_timing.py",
        "backend/cli/market_probabilistic_execution.py",
        "backend/cli/market_adaptive_timing_sizing.py",
        "backend/cli/market_sequential_first_available.py",
        "backend/market/probabilistic_execution.py",
        "backend/market/probabilistic_execution_replay.py",
        "backend/market/probabilistic_execution_saved.py",
        "backend/market/daily_arithmetic_bridge.py",
        "backend/market/retention_study.py",
        PROTOCOL,
        probability.PROTOCOL,
    ):
        result["files"][name] = sha256(root / name)
    if whole_tree:
        from backend.market.retention_study import authenticate_source

        result["whole_tree"] = authenticate_source(
            args.source_revision, args.source_manifest
        )
    return result


# Attribute prices on original planned shares, retaining every unpaired request.
def fixed_quantity_attribution(control, candidate, cost):
    candidate_rows = {row["intent_id"]: row for row in candidate["intent_trace"]}
    require(
        len(candidate_rows) == len(candidate["intent_trace"]),
        "Duplicate candidate intent identity",
    )
    rows = []
    rate = cost / 1e4
    for old in control["intent_trace"]:
        quantity = abs(old["desired_shares"] - old["initial_shares"])
        new = candidate_rows.get(old["intent_id"])
        status = "paired"
        if new is None:
            status = "no_candidate_plan"
        elif new["side"] != old["side"]:
            status = "different_side"
        elif old["realized_price"] is None:
            status = "missing_control_price"
        elif new["realized_price"] is None:
            status = "missing_candidate_price"
        gain = None
        if status == "paired":
            require(
                quantity > 0
                and np.isfinite(
                    [quantity, old["realized_price"], new["realized_price"]]
                ).all()
                and min(old["realized_price"], new["realized_price"]) > 0,
                "Finite positive attribution prices and planned shares required",
            )
            gain = quantity * (
                (old["realized_price"] - new["realized_price"]) * (1 + rate)
                if old["side"] == "buy"
                else (new["realized_price"] - old["realized_price"]) * (1 - rate)
            )
        rows.append(
            {
                "intent_id": old["intent_id"],
                "date": old["date"],
                "symbol": old["symbol"],
                "side": old["side"],
                "status": status,
                "planned_quantity": quantity,
                "control_price": old["realized_price"],
                "candidate_price": new["realized_price"] if new else None,
                "price_component_gain": gain,
                "control_cash_limited_or_partial": abs(old["filled_delta"])
                < quantity - 1e-10,
                "candidate_cash_limited_or_partial": (
                    abs(new["filled_delta"])
                    < abs(new["desired_shares"] - new["initial_shares"]) - 1e-10
                    if new
                    else None
                ),
            }
        )
    return {
        "basis": (
            "control prior-close desired-minus-initial shares; not realized quantity"
        ),
        "investable_counterfactual": False,
        "statuses": dict(Counter(row["status"] for row in rows)),
        "paired_price_gain_initial_nav_units": sum(
            row["price_component_gain"] for row in rows if row["status"] == "paired"
        ),
        "candidate_only_plans": sorted(
            set(candidate_rows) - {row["intent_id"] for row in rows}
        ),
        "rows": rows,
    }


# Summarize all overlapping phases without choosing the best phase or method.
def summarize(rows):
    require(
        [(row["method"], row["cost_bps"], row["phase"]) for row in rows]
        == [
            (method, cost, phase)
            for method in METHODS
            for cost in primary.COSTS
            for phase in range(20)
        ],
        "Complete fixed120-account schedule required",
    )
    result = []
    metrics = (
        "total_net_gain",
        "cagr",
        "max_drawdown_loss",
        "sharpe",
        "gross_traded_weight_per_year",
        "fees_initial_nav_units",
    )
    for method in METHODS:
        for cost in primary.COSTS:
            phases = [
                row
                for row in rows
                if row["method"] == method and row["cost_bps"] == cost
            ]
            windows = []
            for position, window in enumerate(
                ("all", "2018-20", "2021-26", "reused_recent")
            ):
                values = [
                    row["scores"]["candidate"]["windows"][position] for row in phases
                ]
                require(
                    all(
                        v["status"] == "measured" and v["window"] == window
                        for v in values
                    ),
                    "Missing window must not be dropped",
                )
                paired = {}
                for name in ("control", "SPY", "QQQ"):
                    delta = np.array(
                        [
                            row["scores"]["candidate"]["windows"][position][
                                "total_net_gain"
                            ]
                            - row["scores"][name]["windows"][position]["total_net_gain"]
                            for row in phases
                        ]
                    )
                    paired[name] = {
                        "median_gain_difference": float(np.median(delta)),
                        "positive_phases": int((delta > 0).sum()),
                        "minimum": float(delta.min()),
                        "maximum": float(delta.max()),
                    }
                windows.append(
                    {
                        "window": window,
                        "median_metrics": {
                            key: float(np.median([v[key] for v in values]))
                            if all(v[key] is not None for v in values)
                            else None
                            for key in metrics
                        },
                        "paired_gain": paired,
                    }
                )
            result.append(
                {"method": method, "cost_bps": cost, "phases": 20, "windows": windows}
            )
    return result


# Run only the120 new funded accounts using saved controls and benchmark wealth.
def evaluate(args):
    output = Path(args.output)
    require(
        not output.exists(), "Fresh private output required; no restart or overwrite"
    )
    diagnostic, _ = diagnostic_evidence(args.diagnostic, args.probability_proof)
    forecasts.evidence(args.primary_proof, PRIMARY_PROOF_SHA)
    verification = forecasts.evidence(
        args.primary_verification, PRIMARY_VERIFICATION_SHA, json_file=True
    )
    require(
        verification["status"] == "verified_pending_root_review"
        and verification["verifier_exit_code"] == 0
        and verification["verification"]["account_resimulated"] is False,
        "Original independent control verification required",
    )
    loaded = primary.load_inputs(args)
    panel, grades, eligible, cubes, dataset = loaded
    controls_report, controls, etfs = reused.load_primary(
        panel, dataset, args.primary, args.primary_proof
    )
    inputs = forecasts.load_inputs(
        args.prepared / "prepared.npz", args.moments, args.fit_proof
    )
    require(
        np.array_equal(inputs[0], panel.dates) and inputs[1] == tuple(panel.tickers),
        "Forecast and funded panels differ",
    )
    first = primary.comparison_first(panel)
    supported = primary.execution_support(panel, first)
    opens = primary.session_opens(panel, cubes)
    require(
        original._array_hash(opens)
        == controls_report["identity"]["session_open_sha256"]
        and original._array_hash(supported)
        == controls_report["identity"]["supported_sessions_sha256"],
        "Original observation and calendar support changed",
    )
    identity = {
        "source": source_identity(args),
        "data": dataset["provenance"],
        "probability_report_sha256": REPORT_SHA,
        "probability_proof_sha256": PROOF_SHA,
        "primary_sha256": reused.saved.PRIMARY_SHA256,
        "primary_proof_sha256": PRIMARY_PROOF_SHA,
        "primary_verification_sha256": PRIMARY_VERIFICATION_SHA,
        "forecast_inputs": inputs[-1],
        "session_open_sha256": original._array_hash(opens),
        "supported_sessions_sha256": original._array_hash(supported),
        "dates": panel.dates[first - 1 :].astype(str).tolist(),
        "methods": list(METHODS),
        "cost_bps": list(primary.COSTS),
        "phases": list(range(20)),
        "new_accounts": 120,
        "reused_control_accounts": 60,
        "reused_benchmarks": 6,
    }
    output.mkdir(parents=True)
    write_json(output / "identity.json", identity)
    spy = panel.adj_close[:, panel.tickers.index("SPY")]
    rows = []
    for method in METHODS:
        provider = distribution_provider(args.diagnostic, method, diagnostic, inputs)
        for cost in primary.COSTS:
            for phase in range(20):
                account = replay.account(
                    panel,
                    grades,
                    eligible,
                    dataset,
                    provider.provider,
                    first,
                    cost,
                    phase,
                    supported_days=supported,
                )
                control = controls[(cost, phase)]
                others = {"control": control, **etfs[cost]}
                evidence = primary.account_evidence(account, others, spy)
                evidence["score"] = reused.named_score(evidence["score"], account)
                evidence["decision_trace"] = account["decision_trace"]
                evidence["fixed_quantity_attribution"] = fixed_quantity_attribution(
                    control, account, cost
                )
                path = output / f"{method}-{cost}-{phase}.json"
                write_json(path, evidence)
                scores = {"candidate": evidence["score"]}
                for name, other in others.items():
                    scores[name] = reused.named_score(
                        primary.scoring.score(other, {"candidate": account}, spy), other
                    )
                rows.append(
                    {
                        "method": method,
                        "cost_bps": cost,
                        "phase": phase,
                        "file": path.name,
                        "sha256": sha256(path),
                        "scores": scores,
                        "counts": evidence["counts"],
                        "attribution_statuses": evidence["fixed_quantity_attribution"][
                            "statuses"
                        ],
                    }
                )
                write_json(
                    output / "progress.json",
                    {
                        "new_accounts": len(rows),
                        "last_account": path.name,
                        "last_sha256": sha256(path),
                    },
                )
                print(
                    json.dumps(
                        {
                            "method": method,
                            "cost_bps": cost,
                            "phase": phase,
                            "new_accounts": len(rows),
                        }
                    ),
                    flush=True,
                )
                del account, evidence
        del provider
    require(
        source_identity(args) == identity["source"], "Source changed during evaluation"
    )
    report = {
        "policy": replay.POLICY,
        "status": "complete_pending_independent_verification",
        "adoption_eligible": False,
        "identity": identity,
        "runtime": primary.runtime_identity(),
        "summary": summarize(rows),
        "accounts": rows,
        "limitations": [
            "current-vintage grades/universe; periodic-plan component, "
            "not exact live policy",
            "reused outcomes; phase overlaps are not independent trials",
            "cash-bounded intended exposure differs from future realized fills",
            "next-open proxy; no broker/midpoint/auction fill proof",
            "fixed-quantity price attribution is not compounded funded wealth",
        ],
    }
    write_json(output / "evaluation.json", report)
    return report


# Require every original evidence boundary and an exact immutable source artifact.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "cubes",
        "prepared",
        "moments",
        "fit-proof",
        "diagnostic",
        "probability-proof",
        "primary",
        "primary-proof",
        "primary-verification",
        "source-manifest",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    evaluate(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
